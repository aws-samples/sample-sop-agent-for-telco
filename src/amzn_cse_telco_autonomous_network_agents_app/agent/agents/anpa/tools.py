# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Provisioning-specific tools for ANPA - Autonomous Network Provisioning Agent.

These tools wrap kubectl, AWS CLI, and Redfish API calls to manage the full
lifecycle of bare-metal EKS Hybrid nodes via Tinkerbell and kro.
"""

from __future__ import annotations

import json
import logging
import shlex
import uuid

from strands import tool

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd, tool_call, tool_result

log = logging.getLogger(__name__)


def _run(cmd_list):
    """Run a command given as an argv-style list and return (stdout, stderr, rc).

    Wraps ``run_cmd`` (which takes a string and uses ``shell=True``) so callers
    can keep their existing list-of-args style. Each token is shell-quoted so
    arbitrary content (JSON, paths, etc.) round-trips safely.
    """
    cmd_str = " ".join(shlex.quote(str(arg)) for arg in cmd_list)
    result = run_cmd(cmd_str)
    return result.stdout, result.stderr, result.returncode


def _tool_result(_tc, payload, success: bool = True) -> str:
    """Display + RETURN a tool result as a JSON string.

    The shared ``tool_result`` in :mod:`agent.core.executor` is display-only
    (returns ``None``). Tools that need to return structured data to the
    calling Strands agent use this local wrapper instead — same calling
    convention as the original ``tool_result(tc, payload)`` pattern but it
    actually returns the payload serialized as JSON.
    """
    body = json.dumps(payload) if isinstance(payload, dict) else str(payload)
    try:
        tool_result(body[:200], success=success)
    except Exception:  # pragma: no cover — display failure must never crash a tool
        pass
    return body


@tool
def toggle_provision(server_name: str, namespace: str, enabled: bool) -> str:
    """Enable or disable provisioning on a BareMetalProvision custom resource.

    Patches the `spec.provision` field on the named BareMetalProvision CR so
    that kro will either start or halt the Tinkerbell provisioning workflow for
    the target server.

    Args:
        server_name: Name of the BareMetalProvision CR (usually matches hostname).
        namespace: Kubernetes namespace where the CR lives.
        enabled: True to enable provisioning; False to disable it.

    Returns:
        JSON string with the patch outcome or error details.
    """
    action = "enable" if enabled else "disable"
    log.info("toggle_provision: %s provisioning for %s/%s", action, namespace, server_name)

    patch_json = json.dumps({"spec": {"provision": enabled}})

    cmd = [
        "kubectl", "patch", "baremetalprovision", server_name,
        "--namespace", namespace,
        "--type", "merge",
        "--patch", patch_json,
    ]

    tc = tool_call("toggle_provision", {
        "server_name": server_name,
        "namespace": namespace,
        "enabled": enabled,
    })

    stdout, stderr, rc = _run(cmd)
    if rc != 0:
        log.error("toggle_provision failed for %s: %s", server_name, stderr)
        return _tool_result(tc, {
            "status": "error",
            "server_name": server_name,
            "namespace": namespace,
            "provision_enabled": enabled,
            "error": stderr.strip(),
        })

    log.info("toggle_provision: successfully %sd provisioning for %s", action, server_name)
    return _tool_result(tc, {
        "status": "success",
        "server_name": server_name,
        "namespace": namespace,
        "provision_enabled": enabled,
        "output": stdout.strip(),
    })


@tool
def bump_provision_hash(server_name: str, namespace: str) -> str:
    """Bump the provisionHash annotation on a BareMetalProvision CR to trigger re-provisioning.

    kro watches the `annotations.baremetalprovision/provisionHash` field. Changing
    it forces a full reconciliation cycle, causing Tinkerbell to re-run the
    provisioning workflow for the server without deleting and recreating the CR.

    Args:
        server_name: Name of the BareMetalProvision CR.
        namespace: Kubernetes namespace where the CR lives.

    Returns:
        JSON string with the new hash value or error details.
    """
    new_hash = str(uuid.uuid4())
    log.info("bump_provision_hash: setting hash %s for %s/%s", new_hash, namespace, server_name)

    patch_json = json.dumps({
        "metadata": {
            "annotations": {
                "baremetalprovision/provisionHash": new_hash,
            }
        }
    })

    cmd = [
        "kubectl", "patch", "baremetalprovision", server_name,
        "--namespace", namespace,
        "--type", "merge",
        "--patch", patch_json,
    ]

    tc = tool_call("bump_provision_hash", {
        "server_name": server_name,
        "namespace": namespace,
    })

    stdout, stderr, rc = _run(cmd)
    if rc != 0:
        log.error("bump_provision_hash failed for %s: %s", server_name, stderr)
        return _tool_result(tc, {
            "status": "error",
            "server_name": server_name,
            "namespace": namespace,
            "error": stderr.strip(),
        })

    log.info("bump_provision_hash: success for %s, new hash: %s", server_name, new_hash)
    return _tool_result(tc, {
        "status": "success",
        "server_name": server_name,
        "namespace": namespace,
        "new_hash": new_hash,
        "output": stdout.strip(),
    })


@tool
def get_workflow_status(server_name: str, namespace: str = "tink-system") -> str:
    """Query the Tinkerbell Workflow CR status for a given server.

    Retrieves the current phase, task/action breakdown, and any error messages
    from the Tinkerbell Workflow resource associated with the named server.

    Args:
        server_name: Name of the server; used to find the matching Workflow CR
                     (via label selector `template.device_1_mac` or name convention).
        namespace: Kubernetes namespace where Tinkerbell Workflows live.
                   Defaults to ``tink-system``.

    Returns:
        JSON string with workflow phase, task states, and error info.
    """
    log.info("get_workflow_status: querying workflow for %s in %s", server_name, namespace)

    # EKS-H provisioning RGD labels each workflow with `hardware: <server>`
    # (see platform/manifests/infrastructure/provision-rgd.yaml).
    cmd = [
        "kubectl", "get", "workflow",
        "--namespace", namespace,
        "--selector", f"hardware={server_name}",
        "--output", "json",
    ]

    tc = tool_call("get_workflow_status", {
        "server_name": server_name,
        "namespace": namespace,
    })

    stdout, stderr, rc = _run(cmd)
    if rc != 0:
        log.error("get_workflow_status: label query failed for %s, trying name: %s", server_name, stderr)
        # Fall back to direct name lookup
        cmd_by_name = [
            "kubectl", "get", "workflow", server_name,
            "--namespace", namespace,
            "--output", "json",
        ]
        stdout, stderr, rc = _run(cmd_by_name)
        if rc != 0:
            return _tool_result(tc, {
                "status": "error",
                "server_name": server_name,
                "namespace": namespace,
                "error": stderr.strip(),
            })

    try:
        data = json.loads(stdout)
        # Handle both single object and list responses
        if data.get("kind") == "List":
            items = data.get("items", [])
            workflow = items[0] if items else None
        else:
            workflow = data

        if not workflow:
            return _tool_result(tc, {
                "status": "not_found",
                "server_name": server_name,
                "namespace": namespace,
                "message": "No Tinkerbell Workflow found for this server.",
            })

        wf_status = workflow.get("status", {})
        tasks = wf_status.get("tasks", [])

        # Summarise task/action progress
        task_summary = []
        for task in tasks:
            actions = task.get("actions", [])
            task_summary.append({
                "task_name": task.get("name"),
                "worker": task.get("workerAddr"),
                "actions": [
                    {
                        "name": a.get("name"),
                        "status": a.get("status"),
                        "seconds": a.get("seconds"),
                        "message": a.get("message", ""),
                    }
                    for a in actions
                ],
            })

        return _tool_result(tc, {
            "status": "success",
            "server_name": server_name,
            "namespace": namespace,
            "workflow_name": workflow.get("metadata", {}).get("name"),
            "phase": wf_status.get("state", "Unknown"),
            "current_task_index": wf_status.get("currentTaskIndex", 0),
            "current_action_index": wf_status.get("currentActionIndex", 0),
            "tasks": task_summary,
        })

    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        log.exception("get_workflow_status: failed to parse response for %s", server_name)
        return _tool_result(tc, {
            "status": "error",
            "server_name": server_name,
            "namespace": namespace,
            "error": str(exc),
            "raw_output": stdout[:2000],
        })


@tool
def get_node_status(hostname: str) -> str:
    """Get Kubernetes node status for an EKS Hybrid node by its hostname label.

    Looks up the node using the ``kubernetes.io/hostname`` label, then returns
    the node's conditions (Ready, MemoryPressure, DiskPressure, etc.) and
    allocatable resource summary.

    Args:
        hostname: Node hostname as registered with EKS (matches the
                  ``node.kubernetes.io/hostname`` label value).

    Returns:
        JSON string with node conditions, capacity, and readiness.
    """
    log.info("get_node_status: querying node for hostname %s", hostname)

    cmd = [
        "kubectl", "get", "node",
        "--selector", f"node.kubernetes.io/hostname={hostname}",
        "--output", "json",
    ]

    tc = tool_call("get_node_status", {"hostname": hostname})

    stdout, stderr, rc = _run(cmd)
    if rc != 0:
        log.error("get_node_status: query failed for %s: %s", hostname, stderr)
        return _tool_result(tc, {
            "status": "error",
            "hostname": hostname,
            "error": stderr.strip(),
        })

    try:
        data = json.loads(stdout)
        items = data.get("items", []) if data.get("kind") == "List" else [data]

        if not items:
            return _tool_result(tc, {
                "status": "not_found",
                "hostname": hostname,
                "message": "No node found with this hostname label.",
            })

        node = items[0]
        node_status = node.get("status", {})

        conditions = {
            c["type"]: {
                "status": c["status"],
                "reason": c.get("reason", ""),
                "message": c.get("message", ""),
                "last_transition": c.get("lastTransitionTime", ""),
            }
            for c in node_status.get("conditions", [])
        }

        is_ready = conditions.get("Ready", {}).get("status") == "True"

        return _tool_result(tc, {
            "status": "success",
            "hostname": hostname,
            "node_name": node.get("metadata", {}).get("name"),
            "ready": is_ready,
            "conditions": conditions,
            "allocatable": node_status.get("allocatable", {}),
            "capacity": node_status.get("capacity", {}),
            "node_info": node_status.get("nodeInfo", {}),
            "taints": node.get("spec", {}).get("taints", []),
        })

    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        log.exception("get_node_status: failed to parse response for %s", hostname)
        return _tool_result(tc, {
            "status": "error",
            "hostname": hostname,
            "error": str(exc),
            "raw_output": stdout[:2000],
        })


@tool
def create_ssm_activation(cluster_name: str, region: str, node_name: str) -> str:
    """Create an AWS SSM hybrid activation for EKS Hybrid node registration.

    Generates a one-time SSM activation (activation code + activation ID) that
    the provisioned server uses to register as an EKS Hybrid node without
    requiring manually managed TLS certificates.

    Args:
        cluster_name: EKS cluster name; used as the SSM IAM role name prefix and
                      to tag the activation for traceability.
        region: AWS region where the EKS cluster and SSM endpoint reside.
        node_name: Intended node name / hostname for correlation in SSM/EKS logs.

    Returns:
        JSON string with ActivationId, ActivationCode, and expiry metadata.
    """
    log.info(
        "create_ssm_activation: creating activation for node %s in cluster %s (%s)",
        node_name, cluster_name, region,
    )

    iam_role = f"EKSHybridNode-{cluster_name}"
    description = f"EKS Hybrid activation for node {node_name} in cluster {cluster_name}"

    cmd = [
        "aws", "ssm", "create-activation",
        "--iam-role", iam_role,
        "--description", description,
        "--default-instance-name", node_name,
        "--registration-limit", "1",
        "--region", region,
        "--tags",
        f"Key=cluster,Value={cluster_name}",
        f"Key=node,Value={node_name}",
        "--output", "json",
    ]

    tc = tool_call("create_ssm_activation", {
        "cluster_name": cluster_name,
        "region": region,
        "node_name": node_name,
    })

    stdout, stderr, rc = _run(cmd)
    if rc != 0:
        log.error(
            "create_ssm_activation: failed for node %s in cluster %s: %s",
            node_name, cluster_name, stderr,
        )
        return _tool_result(tc, {
            "status": "error",
            "cluster_name": cluster_name,
            "region": region,
            "node_name": node_name,
            "error": stderr.strip(),
        })

    try:
        activation = json.loads(stdout)
        log.info(
            "create_ssm_activation: success for %s, activation_id=%s",
            node_name, activation.get("ActivationId"),
        )
        return _tool_result(tc, {
            "status": "success",
            "cluster_name": cluster_name,
            "region": region,
            "node_name": node_name,
            "activation_id": activation.get("ActivationId"),
            "activation_code": activation.get("ActivationCode"),
            "expiration_date": activation.get("ExpirationDate"),
        })
    except (json.JSONDecodeError, KeyError) as exc:
        log.exception("create_ssm_activation: failed to parse response for %s", node_name)
        return _tool_result(tc, {
            "status": "error",
            "cluster_name": cluster_name,
            "region": region,
            "node_name": node_name,
            "error": str(exc),
            "raw_output": stdout[:2000],
        })


@tool
def drain_and_delete_node(hostname: str, timeout: int = 300) -> str:
    """Safely cordon, drain, and delete an EKS Hybrid node from the cluster.

    Executes the three-step decommission sequence:
    1. ``kubectl cordon`` – marks the node as unschedulable.
    2. ``kubectl drain`` – evicts all pods with the given timeout.
    3. ``kubectl delete node`` – removes the node object from the API server.

    Args:
        hostname: Node hostname matching the ``node.kubernetes.io/hostname`` label.
        timeout: Seconds to wait for pod eviction during drain. Defaults to 300.

    Returns:
        JSON string with success/failure status and per-step output.
    """
    log.info("drain_and_delete_node: starting decommission for hostname %s (timeout=%ds)", hostname, timeout)

    tc = tool_call("drain_and_delete_node", {"hostname": hostname, "timeout": timeout})
    steps = {}

    # Step 1: Cordon
    cordon_cmd = ["kubectl", "cordon", "--selector", f"node.kubernetes.io/hostname={hostname}"]
    stdout, stderr, rc = _run(cordon_cmd)
    steps["cordon"] = {"rc": rc, "stdout": stdout.strip(), "stderr": stderr.strip()}
    if rc != 0:
        log.error("drain_and_delete_node: cordon failed for %s: %s", hostname, stderr)
        return _tool_result(tc, {
            "status": "error",
            "hostname": hostname,
            "failed_step": "cordon",
            "steps": steps,
        })

    # Step 2: Drain
    drain_cmd = [
        "kubectl", "drain",
        "--selector", f"node.kubernetes.io/hostname={hostname}",
        "--ignore-daemonsets",
        "--delete-emptydir-data",
        f"--timeout={timeout}s",
        "--force",
    ]
    stdout, stderr, rc = _run(drain_cmd)
    steps["drain"] = {"rc": rc, "stdout": stdout.strip(), "stderr": stderr.strip()}
    if rc != 0:
        log.error("drain_and_delete_node: drain failed for %s: %s", hostname, stderr)
        return _tool_result(tc, {
            "status": "error",
            "hostname": hostname,
            "failed_step": "drain",
            "steps": steps,
        })

    # Step 3: Delete
    delete_cmd = [
        "kubectl", "delete", "node",
        "--selector", f"node.kubernetes.io/hostname={hostname}",
    ]
    stdout, stderr, rc = _run(delete_cmd)
    steps["delete"] = {"rc": rc, "stdout": stdout.strip(), "stderr": stderr.strip()}
    if rc != 0:
        log.error("drain_and_delete_node: delete failed for %s: %s", hostname, stderr)
        return _tool_result(tc, {
            "status": "error",
            "hostname": hostname,
            "failed_step": "delete",
            "steps": steps,
        })

    log.info("drain_and_delete_node: successfully decommissioned node %s", hostname)
    return _tool_result(tc, {
        "status": "success",
        "hostname": hostname,
        "message": f"Node {hostname} cordoned, drained, and deleted successfully.",
        "steps": steps,
    })


@tool
def power_cycle_server(bmc_ip: str) -> str:
    """Perform a hard reset (ForceRestart) on a server via its Redfish BMC API.

    Issues a ``POST /redfish/v1/Systems/System.Embedded.1/Actions/ComputerSystem.Reset``
    with ``ResetType=ForceRestart``. Use this only when a server is completely
    unresponsive and a Tinkerbell workflow is stuck.

    Args:
        bmc_ip: IP address of the BMC (iDRAC / iLO / BMC) Redfish endpoint.

    Returns:
        JSON string with the HTTP status and Redfish response body.
    """
    log.warning("power_cycle_server: initiating ForceRestart on BMC %s", bmc_ip)

    reset_url = f"https://{bmc_ip}/redfish/v1/Systems/System.Embedded.1/Actions/ComputerSystem.Reset"
    payload = json.dumps({"ResetType": "ForceRestart"})

    cmd = [
        "curl", "--silent", "--show-error",
        "--insecure",                          # BMCs commonly use self-signed certs
        "--write-out", "\n%{http_code}",
        "--request", "POST",
        "--header", "Content-Type: application/json",
        "--data", payload,
        reset_url,
    ]

    tc = tool_call("power_cycle_server", {"bmc_ip": bmc_ip})

    stdout, stderr, rc = _run(cmd)
    if rc != 0:
        log.error("power_cycle_server: curl failed for %s: %s", bmc_ip, stderr)
        return _tool_result(tc, {
            "status": "error",
            "bmc_ip": bmc_ip,
            "error": stderr.strip(),
        })

    # Last line is the HTTP status code written by --write-out
    lines = stdout.strip().rsplit("\n", 1)
    body = lines[0].strip() if len(lines) > 1 else ""
    http_code = lines[-1].strip() if lines else "0"

    try:
        http_status = int(http_code)
    except ValueError:
        http_status = 0

    success = http_status in (200, 202, 204)
    if success:
        log.info("power_cycle_server: ForceRestart accepted for BMC %s (HTTP %d)", bmc_ip, http_status)
    else:
        log.error("power_cycle_server: unexpected HTTP %d from BMC %s", http_status, bmc_ip)

    try:
        response_body = json.loads(body) if body else {}
    except json.JSONDecodeError:
        response_body = {"raw": body[:500]}

    return _tool_result(tc, {
        "status": "success" if success else "error",
        "bmc_ip": bmc_ip,
        "http_status": http_status,
        "response": response_body,
        "action": "ForceRestart",
    })


@tool
def get_hardware_health(bmc_ip: str) -> str:
    """Query Redfish for a hardware health summary including thermal, power, and storage.

    Fetches the Chassis and System health from the Redfish API to surface fan
    failures, temperature thresholds, PSU faults, and drive predictive failures
    before committing a server to the provisioning queue.

    Args:
        bmc_ip: IP address of the BMC Redfish endpoint.

    Returns:
        JSON string with overall health status, thermal summary, power summary,
        and storage controller / drive health.
    """
    log.info("get_hardware_health: querying Redfish health on BMC %s", bmc_ip)

    tc = tool_call("get_hardware_health", {"bmc_ip": bmc_ip})

    def _redfish_get(path: str) -> tuple[dict, str | None]:
        """Run a Redfish GET and return (parsed_json, error_string)."""
        url = f"https://{bmc_ip}{path}"
        get_cmd = [
            "curl", "--silent", "--show-error",
            "--insecure",
            "--write-out", "\n%{http_code}",
            "--request", "GET",
            "--header", "Accept: application/json",
            url,
        ]
        out, err, code = _run(get_cmd)
        if code != 0:
            return {}, err.strip()
        parts = out.strip().rsplit("\n", 1)
        raw_body = parts[0].strip() if len(parts) > 1 else ""
        try:
            return json.loads(raw_body), None
        except json.JSONDecodeError:
            return {"raw": raw_body[:500]}, None

    results: dict = {"bmc_ip": bmc_ip}

    # --- System overall health ---
    system_data, err = _redfish_get("/redfish/v1/Systems/System.Embedded.1")
    if err:
        return _tool_result(tc, {
            "status": "error",
            "bmc_ip": bmc_ip,
            "error": f"Failed to reach Redfish System endpoint: {err}",
        })

    results["system_health"] = system_data.get("Status", {}).get("HealthRollup", "Unknown")
    results["model"] = system_data.get("Model", "Unknown")
    results["bios_version"] = system_data.get("BiosVersion", "Unknown")
    results["power_state"] = system_data.get("PowerState", "Unknown")

    # --- Thermal (fans + temperatures) ---
    thermal_data, _ = _redfish_get("/redfish/v1/Chassis/System.Embedded.1/Thermal")
    if thermal_data:
        fan_issues = [
            {"name": f.get("Name"), "status": f.get("Status", {}).get("Health"), "rpm": f.get("Reading")}
            for f in thermal_data.get("Fans", [])
            if f.get("Status", {}).get("Health") not in ("OK", None)
        ]
        temp_warnings = [
            {
                "name": t.get("Name"),
                "reading_celsius": t.get("ReadingCelsius"),
                "upper_threshold_critical": t.get("UpperThresholdCritical"),
            }
            for t in thermal_data.get("Temperatures", [])
            if t.get("ReadingCelsius") is not None
            and t.get("UpperThresholdCritical") is not None
            and t.get("ReadingCelsius", 0) >= t.get("UpperThresholdCritical", 9999) * 0.9
        ]
        results["thermal"] = {
            "status": thermal_data.get("Status", {}).get("Health", "Unknown"),
            "fan_issues": fan_issues,
            "temperature_warnings": temp_warnings,
        }

    # --- Power (PSUs) ---
    power_data, _ = _redfish_get("/redfish/v1/Chassis/System.Embedded.1/Power")
    if power_data:
        psu_issues = [
            {"name": p.get("Name"), "status": p.get("Status", {}).get("Health"), "watts": p.get("LastPowerOutputWatts")}
            for p in power_data.get("PowerSupplies", [])
            if p.get("Status", {}).get("Health") not in ("OK", None)
        ]
        results["power"] = {
            "status": power_data.get("PowerControl", [{}])[0].get("Status", {}).get("Health", "Unknown")
            if power_data.get("PowerControl") else "Unknown",
            "psu_issues": psu_issues,
            "consumed_watts": power_data.get("PowerControl", [{}])[0].get("PowerConsumedWatts")
            if power_data.get("PowerControl") else None,
        }

    # --- Storage ---
    storage_data, _ = _redfish_get("/redfish/v1/Systems/System.Embedded.1/Storage")
    if storage_data:
        drive_issues = []
        for controller in storage_data.get("Members", []):
            ctrl_path = controller.get("@odata.id", "")
            ctrl_data, _ = _redfish_get(ctrl_path)
            for drive_ref in ctrl_data.get("Drives", []):
                drive_path = drive_ref.get("@odata.id", "")
                drive_data, _ = _redfish_get(drive_path)
                health = drive_data.get("Status", {}).get("Health", "Unknown")
                if health not in ("OK", None):
                    drive_issues.append({
                        "drive": drive_data.get("Name", drive_path),
                        "model": drive_data.get("Model"),
                        "capacity_bytes": drive_data.get("CapacityBytes"),
                        "health": health,
                        "failure_predicted": drive_data.get("FailurePredicted", False),
                    })
        results["storage"] = {
            "controller_count": len(storage_data.get("Members", [])),
            "drive_issues": drive_issues,
        }

    # Derive overall verdict
    system_health = results.get("system_health", "Unknown")
    has_fan_issues = bool(results.get("thermal", {}).get("fan_issues"))
    has_psu_issues = bool(results.get("power", {}).get("psu_issues"))
    has_drive_issues = bool(results.get("storage", {}).get("drive_issues"))

    results["overall_healthy"] = (
        system_health == "OK"
        and not has_fan_issues
        and not has_psu_issues
        and not has_drive_issues
    )

    log.info(
        "get_hardware_health: BMC %s overall_healthy=%s system_health=%s",
        bmc_ip, results["overall_healthy"], system_health,
    )

    return _tool_result(tc, {"status": "success", **results})


@tool
def ssm_run_command(instance_id: str, command: str) -> str:
    """Run a shell command on a node via AWS Systems Manager (SSM).

    Use this to cross-validate hardware state reported by BMC with actual
    OS-level observations (CPU count, memory, disk, network interfaces).

    Args:
        instance_id: SSM managed instance ID (e.g., 'mi-0abc123def456').
        command: Shell command to execute on the remote node.
    """
    tc = tool_call("ssm_run_command", {"instance_id": instance_id, "command": command})
    result = run_cmd(
        f"aws ssm send-command --instance-ids {instance_id} "
        f"--document-name AWS-RunShellScript "
        f"--parameters commands='{command}' "
        f"--output-s3-bucket-name '' --query Command.CommandId --output text",
        timeout=30,
    )
    if not result.success:
        return _tool_result(tc, {"status": "error", "error": result.output})

    cmd_id = result.stdout.strip()
    # Wait for command to complete
    run_cmd(
        f"aws ssm wait command-executed --command-id {cmd_id} --instance-id {instance_id}",
        timeout=60,
    )
    # Get output
    output_result = run_cmd(
        f"aws ssm get-command-invocation --command-id {cmd_id} "
        f"--instance-id {instance_id} --query StandardOutputContent --output text",
        timeout=15,
    )
    if output_result.success:
        return _tool_result(tc, {"status": "success", "output": output_result.stdout.strip()})
    return _tool_result(tc, {"status": "error", "error": output_result.output})


# ---------------------------------------------------------------------------
# Exported tool list – register all ANPA tools with the Strands agent
# ---------------------------------------------------------------------------
PROVISION_TOOLS = [
    toggle_provision,
    bump_provision_hash,
    get_workflow_status,
    get_node_status,
    create_ssm_activation,
    drain_and_delete_node,
    power_cycle_server,
    get_hardware_health,
    ssm_run_command,
]
