# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Cross-agent query tools for ANRA.

These tools allow ANRA's Strands agent to query ANPA and ANDA during
its reasoning loop (Agents-as-Tools pattern). All calls are read-only
HTTP queries — no state mutations.
"""

import logging

from strands import tool

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

log = logging.getLogger(__name__)

_ANPA_BASE = "http://anpa.anpa-system.svc:8080"
_ANDA_BASE = "http://anda.anda-system.svc:8080"


@tool
def ask_anpa_provisioning_status(server_name: str) -> str:
    """Query ANPA for the provisioning status of a specific server.

    Use this when investigating hardware-related alarms to check if a server
    was recently provisioned, is mid-provisioning, or had provisioning failures.

    Args:
        server_name: Hostname or HardwareInventory CR name of the server.
    """
    result = run_cmd(
        f"curl -sf --max-time 10 {_ANPA_BASE}/api/provisioning/requests?server={server_name}",
        timeout=15,
    )
    if not result.success:
        return f"ANPA unreachable or no data for server '{server_name}': {result.stderr}"
    return result.stdout


@tool
def ask_anpa_hardware_inventory(server_name: str) -> str:
    """Query ANPA for hardware inventory details of a server.

    Use this to get BMC address, firmware versions, CPU/memory specs, and
    hardware health status from the HardwareInventory CR.

    Args:
        server_name: Hostname or HardwareInventory CR name.
    """
    result = run_cmd(
        f"curl -sf --max-time 10 {_ANPA_BASE}/api/inventory/{server_name}",
        timeout=15,
    )
    if not result.success:
        return f"ANPA unreachable or server '{server_name}' not in inventory: {result.stderr}"
    return result.stdout


@tool
def ask_anda_recent_deployments(namespace: str = "") -> str:
    """Query ANDA for recent deployment activity.

    Use this when correlating alarms with recent changes — a deployment in the
    last 30 minutes is a likely root cause for new failures.

    Args:
        namespace: Filter by namespace (optional, empty = all namespaces).
    """
    url = f"{_ANDA_BASE}/api/deployments"
    if namespace:
        url += f"?namespace={namespace}"
    result = run_cmd(f"curl -sf --max-time 10 {url}", timeout=15)
    if not result.success:
        return f"ANDA unreachable or no deployment data: {result.stderr}"
    return result.stdout


@tool
def ask_anda_deployment_plan_status(plan_name: str) -> str:
    """Query ANDA for the status of a specific DeploymentPlan.

    Use this to check if a deployment is in progress, completed, or failed.

    Args:
        plan_name: Name of the DeploymentPlan CR.
    """
    result = run_cmd(
        f"curl -sf --max-time 10 {_ANDA_BASE}/api/deployments/{plan_name}",
        timeout=15,
    )
    if not result.success:
        return f"ANDA unreachable or plan '{plan_name}' not found: {result.stderr}"
    return result.stdout



@tool
def trigger_anda_redeploy(
    nf_name: str,
    namespace: str,
    reason: str,
    priority: str = "normal",
    intent: str = "remediation",
    vendor: str = "open5gs",
) -> str:
    """Trigger ANDA to redeploy a network function by creating a DeploymentPlan CR.

    Use this when alarm correlation determines that redeploying an NF is the best
    remediation action. This creates a DeploymentPlan CR and wakes ANDA immediately.

    IMPORTANT: Only use this after confirming the root cause is software-related
    (not hardware). For hardware issues, escalate to ANPA instead.

    Args:
        nf_name: Network function to redeploy (e.g., "amf", "upf", "nrf").
        namespace: Kubernetes namespace where the NF runs (e.g., "open5gs").
        reason: Why this redeploy is needed (include alarm context).
        priority: "normal" for standard, "emergency" for immediate force-deploy.
        intent: Action type — "remediation" (default), "deploy", "upgrade".
        vendor: NF vendor for SOP selection (default: "open5gs").
    """
    import json
    import shlex
    import time

    plan_name = f"anra-{nf_name}-{int(time.time())}"
    cr_manifest = json.dumps({
        "apiVersion": "deployment.anda.aws.io/v1alpha1",
        "kind": "DeploymentPlan",
        "metadata": {
            "name": plan_name,
            "namespace": "anda-system",
        },
        "spec": {
            "site": "auto",
            "cluster": "auto",
            "intent": intent,
            "reason": reason,
            "triggeredBy": "anra",
            "priority": priority,
            "executionMode": "live",
            "networkFunctions": [
                {
                    "name": nf_name,
                    "type": vendor,
                    "namespace": namespace,
                    "action": "redeploy" if intent == "remediation" else "deploy",
                    "vendor": vendor,
                }
            ],
        },
    })

    # Create the DeploymentPlan CR via stdin (avoids shell injection from reason/nf_name)
    create_result = run_cmd(
        f"echo {shlex.quote(cr_manifest)} | kubectl apply -f -",
        timeout=15,
    )
    if not create_result.success:
        return f"❌ Failed to create DeploymentPlan: {create_result.stderr}"

    # Wake ANDA orchestrator for immediate pickup
    wake_result = run_cmd(
        f"curl -sf --max-time 5 -X POST {_ANDA_BASE}/api/anda/wake",
        timeout=10,
    )
    wake_status = "woken" if wake_result.success else "wake failed (will poll in ≤30s)"

    log.info("Created DeploymentPlan '%s' for %s (priority=%s), ANDA %s",
             plan_name, nf_name, priority, wake_status)

    return (
        f"✅ Created DeploymentPlan '{plan_name}' in anda-system namespace.\n"
        f"  NF: {nf_name}, Intent: {intent}, Priority: {priority}\n"
        f"  ANDA status: {wake_status}\n"
        f"  Monitor: kubectl get deploymentplan {plan_name} -n anda-system -o yaml"
    )


@tool
def watch_anda_deployment_completion(plan_name: str, timeout_seconds: int = 300) -> str:
    """Wait for an ANDA DeploymentPlan to complete and return its final status.

    Use this after triggering a redeploy with trigger_anda_redeploy to confirm
    the deployment succeeded before closing the alarm.

    Args:
        plan_name: Name of the DeploymentPlan CR to watch.
        timeout_seconds: Max seconds to wait (default 300 = 5 min).
    """
    import time

    start = time.time()
    terminal_phases = {"Completed", "Failed", "PartiallyFailed", "TimedOut"}
    last_phase = ""

    while (time.time() - start) < timeout_seconds:
        result = run_cmd(
            f"kubectl get deploymentplan {plan_name} -n anda-system "
            f"-o jsonpath='{{.status.phase}}'",
            timeout=10,
        )
        if result.success and result.stdout.strip():
            phase = result.stdout.strip().strip("'")
            if phase != last_phase:
                log.info("DeploymentPlan '%s' phase: %s", plan_name, phase)
                last_phase = phase
            if phase in terminal_phases:
                # Get full status for context
                detail = run_cmd(
                    f"kubectl get deploymentplan {plan_name} -n anda-system "
                    f"-o jsonpath='{{.status}}'",
                    timeout=10,
                )
                status_detail = detail.stdout if detail.success else "(could not fetch details)"
                if phase == "Completed":
                    return f"✅ DeploymentPlan '{plan_name}' completed successfully.\nStatus: {status_detail}"
                else:
                    return f"❌ DeploymentPlan '{plan_name}' ended with phase: {phase}\nStatus: {status_detail}"

        time.sleep(10)

    return f"⏰ Timed out waiting for DeploymentPlan '{plan_name}' after {timeout_seconds}s. Last phase: {last_phase}"


CROSS_AGENT_TOOLS = [
    ask_anpa_provisioning_status,
    ask_anpa_hardware_inventory,
    ask_anda_recent_deployments,
    ask_anda_deployment_plan_status,
    trigger_anda_redeploy,
    watch_anda_deployment_completion,
]

