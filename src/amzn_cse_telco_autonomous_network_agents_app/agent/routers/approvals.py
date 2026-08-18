# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from threading import Thread

from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import (
    pop_pending_approval,
    push_activity,
    push_execution,
    snapshot_pending_approvals,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter(tags=["approvals"])

# ── Configuration (all from env or Helm values — no hardcoding) ──
ANDA_ENABLED = os.getenv("ANDA_ENABLED", "true").lower() not in ("false", "0", "no")
ANDA_NAMESPACE = os.getenv("ANDA_NAMESPACE", "anda-system")
ANDA_SERVICE_URL = os.getenv(
    "ANDA_SERVICE_URL",
    f"http://anda.{ANDA_NAMESPACE}.svc.cluster.local:8080",
)
DEFAULT_NF_NAMESPACE = os.getenv("DEFAULT_NF_NAMESPACE", "open5gs")
DEFAULT_NF_VENDOR = os.getenv("DEFAULT_NF_VENDOR", "open5gs")


class ApprovalRequest(BaseModel):
    alarm_name: str
    action: str  # "approve" | "reject"


@router.get("/api/approvals")
def get_approvals():
    pending = snapshot_pending_approvals()
    return {"pending": list(pending.values()), "count": len(pending)}


@router.post("/api/approve")
def approve(req: ApprovalRequest):
    entry = pop_pending_approval(req.alarm_name)
    if entry is None:
        raise HTTPException(404, f"No pending approval for {req.alarm_name}")
    entry["action"] = req.action
    entry["actioned_at"] = datetime.now(timezone.utc).isoformat()

    # If approved, trigger SOP execution
    if req.action == "approve":
        sop_path = entry.get("sop")
        if sop_path:
            Thread(
                target=_execute_approved_sop,
                args=(req.alarm_name, sop_path, entry),
                daemon=True,
                name=f"sop-{req.alarm_name}",
            ).start()
            log.info("Approved '%s' — dispatching SOP: %s", req.alarm_name, sop_path)

    return {"status": req.action, "alarm": req.alarm_name, "sop": entry.get("sop")}


def _execute_approved_sop(alarm_name: str, sop_path: str, entry: dict):
    """Dispatch SOP execution after operator approval.

    Strategy:
    1. If ANDA is enabled, create a DeploymentPlan CR → ANDA picks it up,
       runs the SOP via SOPBridge, and shows live progress on the ANDA page.
    2. If ANDA is unavailable/disabled, fall back to local execute_sop().
    """
    try:
        push_activity("execute", f"Operator approved — executing SOP for {alarm_name}")

        if ANDA_ENABLED:
            success = _trigger_anda(alarm_name, sop_path, entry)
            if success:
                return
            log.warning("ANDA trigger failed for '%s' — falling back to local execution", alarm_name)
            push_activity("execute", f"ANDA unavailable — executing locally for {alarm_name}", status="warning")

        # Fallback: execute locally within ANRA
        _execute_locally(alarm_name, sop_path, entry)

    except Exception as e:
        log.error("Approved SOP execution failed for '%s': %s", alarm_name, e)
        push_activity("execute", f"SOP failed for {alarm_name}: {e}", status="error")


def _trigger_anda(alarm_name: str, sop_path: str, entry: dict) -> bool:
    """Create a DeploymentPlan CR to trigger ANDA SOP execution.

    Uses NF context from the approval entry (populated by monitor from alarm reference).
    No hardcoded NF maps — all context flows from config → alarm → approval → here.
    """
    nf_name = _resolve_nf_name(alarm_name, entry)
    namespace = entry.get("namespace") or DEFAULT_NF_NAMESPACE
    vendor = entry.get("vendor") or DEFAULT_NF_VENDOR

    plan_name = f"anra-{nf_name}-{int(time.time())}"
    cr_manifest = json.dumps({
        "apiVersion": "deployment.anda.aws.io/v1alpha1",
        "kind": "DeploymentPlan",
        "metadata": {
            "name": plan_name,
            "namespace": ANDA_NAMESPACE,
            "labels": {
                "triggered-by": "anra",
                "alarm": alarm_name,
            },
        },
        "spec": {
            "site": "auto",
            "cluster": "auto",
            "intent": "remediation",
            "reason": f"Operator approved remediation for alarm: {alarm_name}",
            "description": f"SOP: {sop_path}",
            "sopPath": sop_path,
            "triggeredBy": "anra",
            "priority": "emergency" if entry.get("severity") == "critical" else "normal",
            "executionMode": "live",
            "networkFunctions": [
                {
                    "name": nf_name,
                    "type": vendor,
                    "namespace": namespace,
                    "action": "redeploy",
                    "vendor": vendor,
                }
            ],
        },
    })

    try:
        result = subprocess.run(  # noqa: S603
            ["kubectl", "apply", "-f", "-"],
            input=cr_manifest,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            log.error("Failed to create DeploymentPlan CR: %s", result.stderr)
            return False

        log.info("Created DeploymentPlan '%s' for %s — ANDA will execute SOP", plan_name, nf_name)
        push_activity(
            "execute",
            f"Created DeploymentPlan '{plan_name}' — ANDA executing SOP for {nf_name}",
            status="success",
        )

        # Wake ANDA for immediate pickup (best-effort, ANDA polls every 30s anyway)
        try:
            subprocess.run(  # noqa: S603
                ["curl", "-sf", "--max-time", "5", "-X", "POST", f"{ANDA_SERVICE_URL}/api/anda/wake"],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass

        return True

    except Exception as e:
        log.error("Exception creating DeploymentPlan: %s", e)
        return False


def _execute_locally(alarm_name: str, sop_path: str, entry: dict):
    """Fallback: execute SOP locally within ANRA (no ANDA involvement)."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import execute_sop

    alert = {
        "name": alarm_name,
        "severity": entry.get("severity", ""),
        "source": entry.get("source", ""),
        "service_impact": entry.get("service_impact", ""),
        "value": entry.get("value"),
    }

    result = execute_sop(sop_path, alert)

    push_execution({
        "alarm": alarm_name,
        "sop": sop_path,
        "result": result.get("status", "unknown"),
        "correlation": "operator-approved",
    })
    log.info("Local SOP complete for '%s': %s", alarm_name, result.get("status"))


def _resolve_nf_name(alarm_name: str, entry: dict) -> str:
    """Resolve NF name from approval entry context.

    Priority:
    1. Explicit nf_instance from K8s pod health (e.g., "amf-0")
    2. Alarm name contains a known NF segment (e.g., "amf_registration_failure" → "amf")
    3. Layer-based default: layer 3 = "gnb", layer 2 = "core", layer 1 = "infra"
    """
    # 1. Explicit NF instance (from K8s pod health detection)
    nf_instance = entry.get("nf_instance", "")
    if nf_instance:
        # Extract NF type from pod name: "amf-0" → "amf", "open5gs-upf-6c9f..." → "upf"
        for segment in nf_instance.replace("-", "_").split("_"):
            if segment in _KNOWN_NFS:
                return segment
        return nf_instance.split("-")[0]  # Best guess: first segment

    # 2. Parse alarm name for NF segments
    alarm_parts = set(alarm_name.lower().replace("-", "_").split("_"))
    for nf in _KNOWN_NFS:
        if nf in alarm_parts:
            return nf

    # 3. Layer-based fallback
    layer = entry.get("layer", -1)
    if layer == 3:
        return "gnb"
    if layer == 2:
        return "core"
    if layer == 1:
        return "infra"

    return "core"


# Known NFs — loaded from alarm config at import time, with static fallback.
# This set is extensible via config without code changes.
_KNOWN_NFS: set = set()

def _load_known_nfs() -> set:
    """Load NF names from config. Falls back to common 5G NFs."""
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config
        cfg = load_config()
        # Prefer explicit NF list from config if available (truly extensible)
        explicit_nfs = getattr(cfg, "network_functions", None)
        if explicit_nfs:
            return set(explicit_nfs) | _COMMON_5G_NFS
        return _COMMON_5G_NFS
    except Exception:
        return _COMMON_5G_NFS


# Static fallback — standard 3GPP 5G network functions
_COMMON_5G_NFS = {
    "nrf", "amf", "smf", "upf", "ausf", "udm", "udr",
    "pcf", "nssf", "bsf", "gnb", "du", "cu", "scp",
}

# Initialize at module load
_KNOWN_NFS = _load_known_nfs()
