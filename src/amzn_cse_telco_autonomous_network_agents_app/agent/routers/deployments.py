# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""FastAPI router for ANDA deployment management API."""

import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

router = APIRouter(tags=["deployments"])

# In-memory deployment plan store (replace with persistent DB at scale)
_deployment_plans: dict = {}


class DeploymentPlanRequest(BaseModel):
    site: str
    cluster: str
    networkFunctions: List[str]


@router.get("/api/deployments")
def list_deployments():
    """List all deployment plans from in-memory state plus active Helm releases."""
    plans = list(_deployment_plans.values())
    helm_result = run_cmd(
        "helm list --all-namespaces -o json 2>/dev/null || echo '[]'",
        timeout=15,
    )
    return {
        "plans": plans,
        "count": len(plans),
        "helm_releases": helm_result.stdout.strip() if helm_result.success else "[]",
    }


@router.post("/api/deployments", status_code=201)
def create_deployment(req: DeploymentPlanRequest):
    """Create a new deployment plan and track it in memory."""
    plan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    plan = {
        "plan_id": plan_id,
        "site": req.site,
        "cluster": req.cluster,
        "networkFunctions": req.networkFunctions,
        "status": "pending",
        "nf_statuses": {nf: "pending" for nf in req.networkFunctions},
        "created_at": now,
        "updated_at": now,
    }
    _deployment_plans[plan_id] = plan
    return plan


@router.get("/api/deployments/{plan_id}")
def get_deployment(plan_id: str):
    """Get deployment plan details enriched with live kubectl pod phase per NF."""
    if plan_id not in _deployment_plans:
        raise HTTPException(404, f"Deployment plan not found: {plan_id}")
    plan = dict(_deployment_plans[plan_id])
    live_status = {}
    for nf in plan.get("networkFunctions", []):
        result = run_cmd(
            f"kubectl get pods -l app.kubernetes.io/name={nf} --all-namespaces "
            f"-o jsonpath='{{.items[*].status.phase}}' 2>/dev/null || true",
            timeout=10,
        )
        live_status[nf] = result.stdout.strip().strip("'") or "unknown"
    plan["live_nf_status"] = live_status
    return plan


@router.post("/api/deployments/{plan_id}/rollback")
def rollback_deployment(plan_id: str):
    """Trigger Helm rollback to the previous revision for every NF in the plan."""
    if plan_id not in _deployment_plans:
        raise HTTPException(404, f"Deployment plan not found: {plan_id}")
    plan = _deployment_plans[plan_id]
    rollback_results = {}
    for nf in plan.get("networkFunctions", []):
        namespace = _resolve_nf_namespace(nf)
        result = run_cmd(
            f"helm rollback {nf} 0 -n {namespace} --wait --timeout 5m",
            timeout=360,
        )
        rollback_results[nf] = "success" if result.success else f"failed: {result.stderr}"
    plan["status"] = "rolling_back"
    plan["updated_at"] = datetime.now(timezone.utc).isoformat()
    return {
        "plan_id": plan_id,
        "status": plan["status"],
        "rollback_results": rollback_results,
    }


@router.get("/api/nf-catalog")
def list_nf_catalog():
    """List available Network Functions from the ANDA NF catalog ConfigMap mount."""
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import load_nf_catalog

        catalog = load_nf_catalog()
        return {
            "nfs": [
                {
                    "name": e.name,
                    "chart": e.chart,
                    "version": e.version,
                    "namespace": e.namespace,
                }
                for e in catalog
            ],
            "count": len(catalog),
        }
    except Exception as exc:
        return {"nfs": [], "count": 0, "error": str(exc)}


@router.get("/api/deployment-strategies")
def list_deployment_strategies():
    """List available upgrade strategies from the ANDA upgrade-strategy ConfigMap mount."""
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import load_upgrade_strategy

        strategies = load_upgrade_strategy()
        return {
            "strategies": [
                {"name": s.name, "applies_to": s.applies_to, "steps": s.steps}
                for s in strategies
            ],
            "count": len(strategies),
        }
    except Exception as exc:
        return {"strategies": [], "count": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_nf_namespace(nf_name: str) -> str:
    """Resolve the Kubernetes namespace for an NF via the ANDA catalog.

    Falls back to ``"default"`` when the catalog is unavailable or the NF is
    not listed.
    """
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import get_catalog_entry, load_nf_catalog

        entry = get_catalog_entry(load_nf_catalog(), nf_name)
        return entry.namespace if entry else "default"
    except Exception:
        return "default"


# ---------------------------------------------------------------------------
# Infrastructure Bootstrap
# ---------------------------------------------------------------------------


@router.get("/api/deployments/infrastructure")
async def list_infrastructure_status():
    """Return the status of all infrastructure components."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import INFRASTRUCTURE_CATALOG, get_missing_infrastructure

    missing = get_missing_infrastructure()
    missing_names = {c.name for c in missing}

    components = []
    for c in INFRASTRUCTURE_CATALOG:
        components.append({
            "name": c.name,
            "type": c.type,
            "namespace": c.namespace,
            "wave": c.wave,
            "healthy": c.name not in missing_names,
        })

    return {
        "components": components,
        "all_healthy": len(missing) == 0,
        "missing": [c.name for c in missing],
    }


@router.post("/api/deployments/bootstrap")
async def trigger_bootstrap():
    """Trigger infrastructure bootstrap — ANDA deploys missing components."""
    import threading
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import _check_and_bootstrap_infrastructure

    thread = threading.Thread(target=_check_and_bootstrap_infrastructure, daemon=True)
    thread.start()

    return {"status": "bootstrap initiated", "message": "ANDA is deploying missing infrastructure components"}



@router.post("/api/anda/wake", status_code=204)
async def wake_anda_orchestrator():
    """Wake the ANDA orchestrator immediately (skip 30s poll wait).

    Used by ANRA's cross-agent tool after creating an emergency DeploymentPlan CR.
    """
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import wake_orchestrator
    wake_orchestrator()
