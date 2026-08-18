# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
ANDA pre-flight and post-deploy validation helpers.

Each public function performs a structured set of checks against the target
cluster/namespace and returns a result dict of the form::

    {
        "status": "ok" | "warning" | "failed",
        "issues": ["<human-readable issue description>", ...]
    }

``status`` is ``"ok"`` when no issues were found, ``"warning"`` when at
least one non-blocking issue was found, and ``"failed"`` when at least one
blocking issue was found.

All Kubernetes interaction is done via ``kubectl`` through
:func:`~core.executor.run_cmd` so that the same audit/logging path is used as
for all other agent shell calls.
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STATUS_OK = "ok"
_STATUS_WARNING = "warning"
_STATUS_FAILED = "failed"


def _build_result(issues: List[Tuple[str, bool]]) -> Dict[str, Any]:
    """Build a standardised result dict.

    Args:
        issues: List of ``(message, is_blocking)`` tuples collected during
                the check.  Blocking issues drive ``status`` to ``"failed"``;
                non-blocking issues drive it to ``"warning"`` at worst.

    Returns:
        Dict with ``status`` and ``issues`` keys.
    """
    status = _STATUS_OK
    messages: List[str] = []
    for msg, blocking in issues:
        messages.append(msg)
        if blocking:
            status = _STATUS_FAILED
        elif status == _STATUS_OK:
            status = _STATUS_WARNING
    return {"status": status, "issues": messages}


def _kubectl(args: str, timeout: int = 30) -> Tuple[int, str, str]:
    """Run a ``kubectl`` command and return ``(returncode, stdout, stderr)``.

    Args:
        args:    Arguments appended to ``kubectl`` (e.g. ``"get nodes -ojson"``).
        timeout: Maximum seconds to wait for the command.

    Returns:
        Tuple of ``(returncode, stdout, stderr)``.
    """
    cmd = f"kubectl {args}"
    log.debug("Running: %s", cmd)
    result = run_cmd(cmd, timeout=timeout)
    if not result.success:
        log.debug("Command failed (rc=%d): %s\nstderr: %s", result.returncode, cmd, result.stderr)
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def preflight_check(cluster_name: str, namespace: str) -> Dict[str, Any]:
    """Run pre-flight checks before deploying an NF to *namespace*.

    Checks performed:
    1. All cluster nodes are in ``Ready`` state.
    2. The target namespace exists.
    3. Any ResourceQuota in the namespace is not at capacity (80 % threshold).
    4. No PVCs in the namespace are in ``Lost`` or ``Pending`` state.

    Args:
        cluster_name: Name of the target cluster (used in log messages and
                      optionally for ``--context`` selection).
        namespace:    Kubernetes namespace where the NF will be deployed.

    Returns:
        Result dict with ``status`` (``"ok"``, ``"warning"``, or
        ``"failed"``) and an ``"issues"`` list of human-readable strings.
    """
    log.info(
        "Running preflight checks for cluster=%s namespace=%s", cluster_name, namespace
    )
    issues: List[Tuple[str, bool]] = []

    # ------------------------------------------------------------------
    # 1. Node readiness
    # ------------------------------------------------------------------
    rc, stdout, _ = _kubectl("get nodes -o json")
    if rc != 0:
        issues.append(
            (f"[{cluster_name}] Unable to list nodes – kubectl returned rc={rc}", True)
        )
    else:
        try:
            node_list = json.loads(stdout)
            not_ready: List[str] = []
            for node in node_list.get("items", []):
                node_name = node.get("metadata", {}).get("name", "<unknown>")
                conditions = (
                    node.get("status", {}).get("conditions", [])
                )
                ready = False
                for cond in conditions:
                    if cond.get("type") == "Ready" and cond.get("status") == "True":
                        ready = True
                        break
                if not ready:
                    not_ready.append(node_name)
            if not_ready:
                issues.append(
                    (
                        f"[{cluster_name}] Node(s) not Ready: {', '.join(not_ready)}",
                        True,
                    )
                )
            else:
                log.info("[%s] All nodes are Ready", cluster_name)
        except (json.JSONDecodeError, KeyError) as exc:
            issues.append(
                (f"[{cluster_name}] Failed to parse node status: {exc}", True)
            )

    # ------------------------------------------------------------------
    # 2. Namespace existence
    # ------------------------------------------------------------------
    rc, _, _ = _kubectl(f"get namespace {namespace}")
    if rc != 0:
        issues.append(
            (f"Namespace '{namespace}' does not exist on cluster {cluster_name}", True)
        )
    else:
        log.info("Namespace '%s' exists on cluster %s", namespace, cluster_name)

    # ------------------------------------------------------------------
    # 3. ResourceQuota capacity
    # ------------------------------------------------------------------
    rc, stdout, _ = _kubectl(f"get resourcequota -n {namespace} -o json")
    if rc == 0 and stdout.strip():
        try:
            rq_list = json.loads(stdout)
            for rq in rq_list.get("items", []):
                rq_name = rq.get("metadata", {}).get("name", "<unknown>")
                hard: Dict[str, str] = rq.get("status", {}).get("hard", {})
                used: Dict[str, str] = rq.get("status", {}).get("used", {})
                for resource, hard_val in hard.items():
                    used_val = used.get(resource, "0")
                    try:
                        hard_f = _parse_quantity(hard_val)
                        used_f = _parse_quantity(used_val)
                        if hard_f > 0 and (used_f / hard_f) >= 0.80:
                            pct = int(used_f / hard_f * 100)
                            issues.append(
                                (
                                    f"ResourceQuota '{rq_name}' resource '{resource}' "
                                    f"is at {pct}% capacity "
                                    f"(used={used_val}, hard={hard_val})",
                                    False,  # warning, not blocking
                                )
                            )
                    except ValueError:
                        pass  # unparseable quantity – skip
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning("Could not parse ResourceQuota in namespace %s: %s", namespace, exc)

    # ------------------------------------------------------------------
    # 4. PVC health
    # ------------------------------------------------------------------
    rc, stdout, _ = _kubectl(f"get pvc -n {namespace} -o json")
    if rc == 0 and stdout.strip():
        try:
            pvc_list = json.loads(stdout)
            unhealthy: List[str] = []
            for pvc in pvc_list.get("items", []):
                pvc_name = pvc.get("metadata", {}).get("name", "<unknown>")
                phase = pvc.get("status", {}).get("phase", "Unknown")
                if phase in ("Lost", "Pending"):
                    unhealthy.append(f"{pvc_name} ({phase})")
            if unhealthy:
                issues.append(
                    (
                        f"PVC(s) in unhealthy state in namespace '{namespace}': "
                        + ", ".join(unhealthy),
                        True,
                    )
                )
            else:
                log.info("All PVCs in namespace '%s' are healthy", namespace)
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning("Could not parse PVCs in namespace %s: %s", namespace, exc)

    result = _build_result(issues)
    log.info(
        "Preflight result for cluster=%s namespace=%s: status=%s issues=%d",
        cluster_name,
        namespace,
        result["status"],
        len(result["issues"]),
    )
    return result


# ---------------------------------------------------------------------------
# Post-deploy checks
# ---------------------------------------------------------------------------


def postdeploy_check(nf_type: str, namespace: str) -> Dict[str, Any]:
    """Run post-deploy checks after an NF has been rolled out.

    Checks performed:
    1. All pods with ``app=<nf_type>`` label are in ``Running`` phase with all
       containers ready.
    2. Service endpoint slices (or ``Endpoints``) for the NF are populated.
    3. The NF appears in the NRF registration list (best-effort: checked via a
       ``curl`` against the NRF service if it is reachable).

    Args:
        nf_type:   NF type label (e.g. ``amf``, ``smf``).  Used as the value
                   for the ``app`` label selector.
        namespace: Kubernetes namespace where the NF was deployed.

    Returns:
        Result dict with ``status`` and ``"issues"`` list.
    """
    log.info(
        "Running post-deploy checks for nf_type=%s namespace=%s", nf_type, namespace
    )
    issues: List[Tuple[str, bool]] = []

    # ------------------------------------------------------------------
    # 1. Pod readiness
    # ------------------------------------------------------------------
    rc, stdout, _ = _kubectl(
        f"get pods -n {namespace} -l app={nf_type} -o json"
    )
    if rc != 0:
        issues.append(
            (
                f"Failed to list pods for nf_type={nf_type} in namespace={namespace} "
                f"(kubectl rc={rc})",
                True,
            )
        )
    else:
        try:
            pod_list = json.loads(stdout)
            pods = pod_list.get("items", [])
            if not pods:
                issues.append(
                    (
                        f"No pods found for app={nf_type} in namespace '{namespace}'",
                        True,
                    )
                )
            else:
                not_running: List[str] = []
                containers_not_ready: List[str] = []
                for pod in pods:
                    pod_name = pod.get("metadata", {}).get("name", "<unknown>")
                    phase = pod.get("status", {}).get("phase", "Unknown")
                    if phase != "Running":
                        not_running.append(f"{pod_name} (phase={phase})")
                        continue
                    # Check container statuses
                    container_statuses = pod.get("status", {}).get(
                        "containerStatuses", []
                    )
                    for cs in container_statuses:
                        if not cs.get("ready", False):
                            containers_not_ready.append(
                                f"{pod_name}/{cs.get('name', '?')}"
                            )
                if not_running:
                    issues.append(
                        (
                            f"Pod(s) not in Running phase: {', '.join(not_running)}",
                            True,
                        )
                    )
                if containers_not_ready:
                    issues.append(
                        (
                            f"Container(s) not ready: {', '.join(containers_not_ready)}",
                            True,
                        )
                    )
                if not not_running and not containers_not_ready:
                    log.info(
                        "All pods for nf_type=%s in namespace=%s are Running and ready",
                        nf_type,
                        namespace,
                    )
        except (json.JSONDecodeError, KeyError) as exc:
            issues.append(
                (f"Failed to parse pod status for nf_type={nf_type}: {exc}", True)
            )

    # ------------------------------------------------------------------
    # 2. Service endpoint readiness
    # ------------------------------------------------------------------
    rc, stdout, _ = _kubectl(
        f"get endpoints -n {namespace} -l app={nf_type} -o json"
    )
    if rc == 0 and stdout.strip():
        try:
            ep_list = json.loads(stdout)
            empty_endpoints: List[str] = []
            for ep in ep_list.get("items", []):
                ep_name = ep.get("metadata", {}).get("name", "<unknown>")
                subsets = ep.get("subsets", [])
                if not subsets:
                    empty_endpoints.append(ep_name)
                else:
                    # Verify at least one ready address exists
                    has_ready = any(
                        s.get("addresses") for s in subsets
                    )
                    if not has_ready:
                        empty_endpoints.append(f"{ep_name} (no ready addresses)")
            if empty_endpoints:
                issues.append(
                    (
                        f"Service endpoint(s) have no ready addresses for "
                        f"nf_type={nf_type}: {', '.join(empty_endpoints)}",
                        True,
                    )
                )
            else:
                log.info(
                    "Service endpoints for nf_type=%s in namespace=%s are populated",
                    nf_type,
                    namespace,
                )
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning(
                "Could not parse endpoints for nf_type=%s: %s", nf_type, exc
            )
    else:
        log.warning(
            "Could not retrieve endpoints for nf_type=%s in namespace=%s",
            nf_type,
            namespace,
        )

    # ------------------------------------------------------------------
    # 3. NRF registration (best-effort)
    # ------------------------------------------------------------------
    rc_nrf, stdout_nrf, _ = _kubectl(
        f"get service nrf -n {namespace} -o jsonpath={{.spec.clusterIP}}"
    )
    if rc_nrf == 0 and stdout_nrf.strip():
        nrf_ip = stdout_nrf.strip()
        nrf_url = f"http://{nrf_ip}:8080/nnrf-nfm/v1/nf-instances"
        rc_curl, curl_out, _ = run_cmd(
            f"curl -sf --max-time 10 '{nrf_url}'", timeout=15
        )
        if rc_curl != 0:
            issues.append(
                (
                    f"NRF registration check failed – NRF at {nrf_ip} unreachable "
                    f"(curl rc={rc_curl}). NF '{nf_type}' may not be registered.",
                    False,  # warning: NRF may itself be the NF being deployed
                )
            )
        else:
            try:
                nrf_data = json.loads(curl_out)
                nf_instances = nrf_data if isinstance(nrf_data, list) else nrf_data.get("nfInstances", [])
                registered = any(
                    inst.get("nfType", "").lower() == nf_type.lower()
                    for inst in nf_instances
                )
                if not registered:
                    issues.append(
                        (
                            f"NF type '{nf_type}' not found in NRF instance list "
                            f"at {nrf_ip}",
                            False,
                        )
                    )
                else:
                    log.info(
                        "NF type '%s' is registered with NRF at %s", nf_type, nrf_ip
                    )
            except (json.JSONDecodeError, KeyError) as exc:
                log.warning("Could not parse NRF response: %s", exc)
    else:
        log.info(
            "NRF service not found in namespace '%s'; skipping NRF registration check",
            namespace,
        )

    result = _build_result(issues)
    log.info(
        "Post-deploy result for nf_type=%s namespace=%s: status=%s issues=%d",
        nf_type,
        namespace,
        result["status"],
        len(result["issues"]),
    )
    return result


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _parse_quantity(value: str) -> float:
    """Convert a Kubernetes quantity string to a float.

    Handles common suffixes: ``m`` (milli), ``Ki``, ``Mi``, ``Gi``, ``Ti``,
    ``k``, ``M``, ``G``, ``T``, and plain integers/floats.

    Args:
        value: Kubernetes quantity string (e.g. ``"500m"``, ``"2Gi"``, ``"4"``).

    Returns:
        Float representation of the quantity.

    Raises:
        ValueError: If the quantity string cannot be parsed.
    """
    value = value.strip()
    multipliers = {
        "Ki": 2**10,
        "Mi": 2**20,
        "Gi": 2**30,
        "Ti": 2**40,
        "k": 1e3,
        "M": 1e6,
        "G": 1e9,
        "T": 1e12,
        "m": 1e-3,
    }
    for suffix, mult in multipliers.items():
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * mult
    return float(value)
