# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""ANPA diagnosis tools — Phase 4.1.

Read-only primitives the AI failure handler uses to reason about a stuck
or failed provisioning. These are *complementary* to ``PROVISION_TOOLS``
in :mod:`agent.agents.anpa.tools`:

  ``PROVISION_TOOLS``       -- mostly ACTIONS (toggle, bump hash, power cycle,
                                drain, SSM run-command). Some are read-only.
  ``DIAGNOSIS_TOOLS``       -- READ-ONLY introspection: workflow per-action
                                state, BMC SEL events, node-join post-mortem.

Vendor coverage: Redfish/iDRAC works as-is; non-Redfish BMCs degrade
gracefully (return an empty record rather than raising).
"""

from __future__ import annotations

import json
import logging
import os

from strands import tool

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools import _run, _tool_result
from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import tool_call

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bmc_creds() -> tuple[str, str]:
    """Return (user, password) from the wired BMC env."""
    return (
        os.environ.get("BMC_USERNAME", "root"),
        os.environ.get("BMC_PASSWORD", ""),
    )


def _curl_bmc(bmc_ip: str, path: str, timeout: int = 15) -> tuple[bool, dict]:
    """Authenticated Redfish GET helper.

    Credentials go via curl's stdin config (util.bmc.curl_bmc), never a command
    string.
    """
    from amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc import curl_bmc

    user, pwd = _bmc_creds()
    result = curl_bmc(f"https://{bmc_ip}{path}", user, pwd, timeout=timeout)
    if result.returncode != 0:
        return False, {}
    try:
        return True, json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return False, {}


# ---------------------------------------------------------------------------
# Tool 1 — workflow per-action logs (the goldmine for diagnosis)
# ---------------------------------------------------------------------------


@tool
def get_workflow_logs(server_name: str, namespace: str = "tinkerbell") -> str:
    """Extract per-action statuses + error messages from a Tinkerbell Workflow.

    The Workflow CR's ``status.tasks[].actions[]`` carries the play-by-play
    of provisioning: which action ran, which succeeded, which failed, and
    the failure ``message``. This is exactly what the AI needs to root-cause
    a STATE_FAILED workflow.

    Read-only; does not modify cluster state.

    Args:
        server_name: hostname (matches the ``hardware`` label on the Workflow).
        namespace:   namespace where Tinkerbell runs (default ``tinkerbell``).

    Returns:
        JSON string: ``{ workflow_name, state, failed_actions: [...], all_actions: [...] }``
        or an error/empty record when no workflow matches.
    """
    tc = tool_call("get_workflow_logs", {"server_name": server_name, "namespace": namespace})
    cmd = [
        "kubectl", "get", "workflow",
        "-n", namespace,
        "-l", f"hardware={server_name}",
        "-o", "json",
    ]
    stdout, stderr, rc = _run(cmd)
    if rc != 0:
        return _tool_result(tc, {"status": "error", "error": stderr.strip()}, success=False)
    try:
        data = json.loads(stdout or "{}")
    except json.JSONDecodeError as exc:
        return _tool_result(tc, {"status": "error", "error": f"parse: {exc}"}, success=False)

    items = data.get("items", [])
    if not items:
        return _tool_result(tc, {
            "status": "not_found",
            "server_name": server_name,
            "message": "no Workflow with that hardware label",
        }, success=False)

    wf = items[0]
    state = wf.get("status", {}).get("state", "UNKNOWN")
    workflow_name = wf.get("metadata", {}).get("name", "")
    all_actions: list[dict] = []
    failed_actions: list[dict] = []
    for task in wf.get("status", {}).get("tasks", []) or []:
        for action in task.get("actions", []) or []:
            entry = {
                "task": task.get("name", ""),
                "action": action.get("name", ""),
                "status": action.get("status", ""),
                "message": action.get("message", "") or "",
                "started_at": action.get("startedAt", ""),
                "seconds": action.get("seconds", 0),
            }
            all_actions.append(entry)
            if entry["status"] in ("STATE_FAILED", "STATE_TIMEOUT"):
                failed_actions.append(entry)

    return _tool_result(tc, {
        "status": "ok",
        "workflow_name": workflow_name,
        "state": state,
        "failed_actions": failed_actions,
        "all_actions": all_actions,
        "summary": (
            f"Workflow {workflow_name} is {state}; "
            f"{len(failed_actions)} of {len(all_actions)} action(s) failed."
        ),
    })


# ---------------------------------------------------------------------------
# Tool 2 — BMC System Event Log (hardware/firmware events)
# ---------------------------------------------------------------------------


@tool
def read_bmc_sel(bmc_ip: str, max_entries: int = 20) -> str:
    """Read the most recent System Event Log entries from a BMC via Redfish.

    Useful when provisioning fails for hardware reasons (thermal, PSU,
    DIMM ECC, NIC link-down) — the SEL records them with timestamps the
    operator's terminal can't see.

    Read-only. Returns an empty record if the BMC has no SEL service or
    is unreachable.

    Args:
        bmc_ip:      BMC IP/hostname (no scheme).
        max_entries: Cap on entries returned (newest first).
    """
    tc = tool_call("read_bmc_sel", {"bmc_ip": bmc_ip, "max_entries": max_entries})
    ok, listing = _curl_bmc(
        bmc_ip,
        "/redfish/v1/Managers/iDRAC.Embedded.1/LogServices/Sel/Entries",
    )
    if not ok:
        return _tool_result(tc, {
            "status": "unavailable",
            "bmc_ip": bmc_ip,
            "message": "SEL endpoint not reachable or returned non-JSON",
        }, success=False)

    members = listing.get("Members", []) or []
    entries: list[dict] = []
    for m in members[:max_entries]:
        entries.append({
            "id": m.get("Id", ""),
            "created": m.get("Created", ""),
            "severity": m.get("Severity", ""),
            "message": m.get("Message", ""),
            "sensor_type": m.get("SensorType", ""),
            "entry_type": m.get("EntryType", ""),
        })

    return _tool_result(tc, {
        "status": "ok",
        "bmc_ip": bmc_ip,
        "total_entries": listing.get("Members@odata.count", len(members)),
        "returned": len(entries),
        "entries": entries,
    })


# ---------------------------------------------------------------------------
# Tool 3 — Node-join post-mortem (when WaitingForNodes never advances)
# ---------------------------------------------------------------------------


@tool
def inspect_node_join(hostname: str) -> str:
    """Diagnose why a provisioned host hasn't registered as an EKS node yet.

    Aggregates four read-only signals:
      1. kubectl node existence (`kubectl get node <hostname>`).
      2. The matching SSM managed-instance entry (`aws ssm describe-instance-information`).
      3. The HardwareInventory CR for context.
      4. Last 10 events related to the node, if it exists.

    Returns structured JSON the AI can reason over to pick the right fix:
    cert/clock skew (SSM dial-out fails), hybrid IAM role (managed
    instance shows but node never registers), networking, etc.
    """
    tc = tool_call("inspect_node_join", {"hostname": hostname})
    out: dict = {"hostname": hostname}

    # 1. Node existence
    node_json, _, _ = _run(["kubectl", "get", "node", hostname, "-o", "json", "--ignore-not-found"])
    if node_json.strip():
        try:
            n = json.loads(node_json)
            ready = next(
                (c["status"] for c in n.get("status", {}).get("conditions", []) if c.get("type") == "Ready"),
                "Unknown",
            )
            out["node"] = {
                "exists": True,
                "ready": ready,
                "kubelet_version": n.get("status", {}).get("nodeInfo", {}).get("kubeletVersion", ""),
                "system_uuid": n.get("status", {}).get("nodeInfo", {}).get("systemUUID", ""),
            }
        except json.JSONDecodeError:
            out["node"] = {"exists": True, "parse_error": True}
    else:
        out["node"] = {"exists": False}

    # 2. SSM managed instance
    ssm_json, _, rc_ssm = _run([
        "aws", "ssm", "describe-instance-information",
        "--filters", f"Key=tag:node,Values={hostname}",
        "--output", "json",
    ])
    if rc_ssm == 0 and ssm_json.strip():
        try:
            d = json.loads(ssm_json)
            instances = d.get("InstanceInformationList", [])
            out["ssm"] = {
                "managed_instances": len(instances),
                "ping_status": (instances[0].get("PingStatus") if instances else None),
                "last_ping": (instances[0].get("LastPingDateTime") if instances else None),
            }
        except json.JSONDecodeError:
            out["ssm"] = {"parse_error": True}
    else:
        out["ssm"] = {"available": False}

    # 3. HardwareInventory
    cr_name = hostname.lower().replace("_", "-").replace(".", "-")
    hwi_json, _, _ = _run([
        "kubectl", "get", "hardwareinventory", cr_name, "-o", "json", "--ignore-not-found",
    ])
    if hwi_json.strip():
        try:
            h = json.loads(hwi_json)
            out["hardware_inventory"] = {
                "exists": True,
                "phase": h.get("status", {}).get("phase", ""),
                "system_uuid": h.get("spec", {}).get("systemUUID", ""),
                "bmc_address": h.get("spec", {}).get("bmcAddress", ""),
            }
        except json.JSONDecodeError:
            out["hardware_inventory"] = {"exists": True, "parse_error": True}
    else:
        out["hardware_inventory"] = {"exists": False}

    # 4. Recent events (best-effort)
    if out["node"]["exists"]:
        events_out, _, _ = _run([
            "kubectl", "get", "events",
            "--field-selector", f"involvedObject.name={hostname}",
            "--sort-by", ".lastTimestamp",
            "-o", "json",
        ])
        try:
            ev = json.loads(events_out or "{}").get("items", [])
            out["recent_events"] = [
                {"reason": e.get("reason"), "message": e.get("message"), "time": e.get("lastTimestamp")}
                for e in ev[-10:]
            ]
        except json.JSONDecodeError:
            out["recent_events"] = []

    return _tool_result(tc, out)


# ---------------------------------------------------------------------------
# Public registry — appended to the failure handler's tool set
# ---------------------------------------------------------------------------


DIAGNOSIS_TOOLS = [
    get_workflow_logs,
    read_bmc_sel,
    inspect_node_join,
]
