# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
ANDA deployment orchestrator.

Provides a polling loop that watches for ``DeploymentPlan`` custom resources
on the target cluster and drives each plan through the full NF lifecycle:

  preflight → drain (optional) → deploy (ArgoCD / Helm) → wait → postdeploy

The orchestrator is deliberately stateless between poll cycles; all
persistent state is stored in the ``DeploymentPlan`` CR's ``status``
sub-resource so that the agent can be restarted safely.

Usage::

    from agents.anda.orchestrator import run_orchestrator
    run_orchestrator()          # blocks; use threading/asyncio to run as task
"""

import os


import json
import logging
import time
import threading
from typing import Any, Dict, List, Optional

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import (
    load_nf_catalog,
    load_upgrade_strategy,
    get_catalog_entry,
    get_strategy_for_nf,
    get_missing_infrastructure,
    UpgradeStrategy,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.validation import preflight_check, postdeploy_check

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POLL_INTERVAL_SECONDS = 30

# Feature flag: set SOP_BRIDGE_ENABLED=false to bypass SOP bridge and use legacy helm path
_SOP_BRIDGE_ENABLED = os.getenv("SOP_BRIDGE_ENABLED", "true").lower() in ("true", "1", "yes")

# Threading event for urgent wake (set by POST /api/anda/wake)
_urgent_wake = threading.Event()

# 3GPP NF dependency order – later entries depend on earlier ones.
# A partial ordering: NFs not listed are placed at the end.
_3GPP_ORDER: List[str] = [
    "nrf",   # Network Repository Function (must come first)
    "udr",   # Unified Data Repository
    "udm",   # Unified Data Management
    "ausf",  # Authentication Server Function
    "nssf",  # Network Slice Selection Function
    "pcf",   # Policy Control Function
    "smf",   # Session Management Function
    "upf",   # User Plane Function
    "amf",   # Access and Mobility Management Function
    "af",    # Application Function
]

# Default Helm/ArgoCD deploy timeout in seconds
_DEPLOY_TIMEOUT_SECONDS = 600

# Deployment plan CR group/version/resource
_CR_GROUP = "deployment.anda.aws.io"
_CR_VERSION = "v1alpha1"
_CR_PLURAL = "deploymentplans"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------



def wake_orchestrator() -> None:
    """Wake the orchestrator immediately (skips the 30s poll wait).

    Called by POST /api/anda/wake when ANRA creates an emergency CR.
    """
    _urgent_wake.set()

def run_orchestrator() -> None:
    """Start the ANDA orchestrator polling loop.

    Runs indefinitely, polling for pending ``DeploymentPlan`` CRs every
    :data:`POLL_INTERVAL_SECONDS` seconds.  Blocks the calling thread.

    The loop is designed to be crash-resistant: exceptions from individual
    plan processing are caught and logged so that a single bad plan does not
    stop the orchestrator from processing other plans.
    """
    log.info(
        "ANDA orchestrator starting (poll_interval=%ds)", POLL_INTERVAL_SECONDS
    )

    # Phase 1: Check if infrastructure bootstrap is needed
    _check_and_bootstrap_infrastructure()

    # Load config once at startup; reload on each poll cycle so that
    # ConfigMap updates are picked up without restarting the agent.
    while True:
        try:
            _poll_once()
        except Exception as exc:  # pylint: disable=broad-except
            log.error("Unhandled exception in orchestrator poll cycle: %s", exc, exc_info=True)

        log.debug("Waiting %ds for next poll (or wake signal)", POLL_INTERVAL_SECONDS)
        _urgent_wake.wait(timeout=POLL_INTERVAL_SECONDS)
        _urgent_wake.clear()


# ---------------------------------------------------------------------------
# Infrastructure Bootstrap
# ---------------------------------------------------------------------------


def _check_and_bootstrap_infrastructure() -> None:
    """Detect missing infrastructure components and deploy them in wave order."""
    missing = get_missing_infrastructure()
    if not missing:
        log.info("Infrastructure bootstrap: all components healthy")
        return

    log.info("Infrastructure bootstrap needed: %s", [c.name for c in missing])
    from amzn_cse_telco_autonomous_network_agents_app.agent.core.state import push_activity
    push_activity("anda", "Bootstrap started", f"Missing: {[c.name for c in missing]}", "running")

    # Sort by wave for dependency ordering
    missing.sort(key=lambda c: c.wave)

    for component in missing:
        # Check dependencies are satisfied
        deps_met = all(
            component_is_healthy(dep) for dep in component.depends_on
        )
        if not deps_met:
            log.warning("Skipping %s — dependencies not met: %s", component.name, component.depends_on)
            continue

        log.info("Deploying infrastructure: %s (wave=%d, method=%s)", component.name, component.wave, component.install_method)

        if component.install_method == "helm":
            result = run_cmd(
                f"helm upgrade --install {component.name} {component.source} "
                f"--namespace {component.namespace} --create-namespace --wait --timeout 300s",
                timeout=360,
            )
        elif component.install_method == "kubectl_apply":
            result = run_cmd(
                f"kubectl apply -f {component.source} -n {component.namespace}",
                timeout=60,
            )
        else:
            log.error("Unknown install method for %s: %s", component.name, component.install_method)
            continue

        if not result.success:
            log.error("Failed to deploy %s: %s", component.name, result.output[:200])
            push_activity("anda", f"Bootstrap failed: {component.name}", result.output[:200], "failed")
        else:
            log.info("Successfully deployed %s", component.name)
            push_activity("anda", f"Deployed: {component.name}", result.output[:200], "success")

    # Final check
    still_missing = get_missing_infrastructure()
    if not still_missing:
        log.info("Infrastructure bootstrap complete — all components healthy")
        push_activity("anda", "Bootstrap complete", "All infrastructure components deployed", "success")
    else:
        log.warning("Bootstrap incomplete — still missing: %s", [c.name for c in still_missing])
        push_activity("anda", "Bootstrap incomplete", f"Still missing: {[c.name for c in still_missing]}", "warning")


def component_is_healthy(name: str) -> bool:
    """Check if a named infrastructure component passes its health check."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import get_infra_component
    comp = get_infra_component(name)
    if not comp or not comp.health_check:
        return True  # No health check = assume OK
    result = run_cmd(comp.health_check, timeout=10)
    return result.success and bool(result.output.strip())


# ---------------------------------------------------------------------------
# Poll cycle
# ---------------------------------------------------------------------------


def _poll_once() -> None:
    """Execute a single poll cycle.

    Lists all ``DeploymentPlan`` CRs whose ``status.phase`` is ``Pending``
    (or missing) and processes each one sequentially.
    """
    log.debug("Polling for DeploymentPlan CRs …")

    result = run_cmd(
        f"kubectl get {_CR_PLURAL}.{_CR_GROUP} "
        f"--all-namespaces -o json",
        timeout=30,
    )
    if not result.success:
        log.warning(
            "Failed to list DeploymentPlan CRs: %s", result.output[:200]
        )
        return

    try:
        cr_list = json.loads(result.stdout)  # Use .stdout (full), not .output (truncated)
    except json.JSONDecodeError as exc:
        log.error("Could not parse DeploymentPlan list: %s", exc)
        return

    plans = cr_list.get("items", [])
    log.debug("Found %d DeploymentPlan CR(s)", len(plans))

    for plan in plans:
        phase = (
            plan.get("status", {}).get("phase", "Pending")
        )
        if phase not in ("Pending", ""):
            log.debug(
                "Skipping plan %s (phase=%s)",
                _plan_name(plan),
                phase,
            )
            continue

        try:
            process_deployment_plan(plan)
        except Exception as exc:  # pylint: disable=broad-except
            log.error(
                "Error processing DeploymentPlan %s: %s",
                _plan_name(plan),
                exc,
                exc_info=True,
            )
            _update_plan_status(plan, "Failed", f"Orchestrator error: {exc}")


# ---------------------------------------------------------------------------
# Plan processing
# ---------------------------------------------------------------------------


def process_deployment_plan(plan: Dict[str, Any]) -> None:
    """Process a single ``DeploymentPlan`` CR end-to-end.

    Workflow for each NF declared in the plan:

    1. Parse the NF list and determine deployment order.
    2. Run :func:`~agents.anda.validation.preflight_check` for each NF.
    3. Resolve the upgrade strategy.
    4. Drain the NF if the strategy requires it.
    5. Deploy via ArgoCD Application sync or ``helm upgrade``.
    6. Wait for rollout to complete.
    7. Run :func:`~agents.anda.validation.postdeploy_check`.
    8. Update ``DeploymentPlan`` status.

    Args:
        plan: Raw ``DeploymentPlan`` CR dict as returned by ``kubectl get -o json``.
    """
    name = _plan_name(plan)
    namespace = plan.get("metadata", {}).get("namespace", "default")
    cluster_name = plan.get("spec", {}).get("clusterName", "unknown-cluster")

    log.info("Processing DeploymentPlan '%s' on cluster '%s'", name, cluster_name)
    _update_plan_status(plan, "InProgress", "Orchestrator started processing")

    # Reload config each time so live ConfigMap changes are reflected
    catalog = load_nf_catalog()
    strategies = load_upgrade_strategy()

    # ------------------------------------------------------------------
    # 1. Parse NF list and resolve order
    # ------------------------------------------------------------------
    nfs_raw: List[Dict[str, Any]] = plan.get("spec", {}).get("networkFunctions", []) or plan.get("spec", {}).get("nfs", [])
    if not nfs_raw:
        log.warning("DeploymentPlan '%s' has no NFs defined; marking complete", name)
        _update_plan_status(plan, "Completed", "No NFs to deploy")
        return

    ordered_nfs = _resolve_nf_order(nfs_raw)
    log.info(
        "NF deployment order for plan '%s': %s",
        name,
        [nf.get("name") for nf in ordered_nfs],
    )

    failed_nfs: List[str] = []

    for nf in ordered_nfs:
        nf_name: str = nf.get("name", "unknown")
        nf_namespace: str = nf.get("namespace", namespace)

        log.info("--- Processing NF: %s (namespace=%s) ---", nf_name, nf_namespace)

        # ------------------------------------------------------------------
        # 2. Pre-flight check
        # ------------------------------------------------------------------
        preflight_result = preflight_check(cluster_name, nf_namespace)
        if preflight_result["status"] == "failed":
            log.error(
                "Preflight failed for NF '%s': %s",
                nf_name,
                preflight_result["issues"],
            )
            failed_nfs.append(nf_name)
            _update_plan_nf_status(plan, nf_name, "PreflightFailed")
            continue  # skip this NF, continue with others
        if preflight_result["status"] == "warning":
            log.warning(
                "Preflight warnings for NF '%s': %s",
                nf_name,
                preflight_result["issues"],
            )

        # ------------------------------------------------------------------
        # 3. Resolve strategy
        # ------------------------------------------------------------------
        strategy = _get_strategy(nf_name, strategies)
        if strategy:
            log.info(
                "Using upgrade strategy '%s' for NF '%s'", strategy.name, nf_name
            )
        else:
            log.info("No specific strategy for NF '%s'; using default rolling", nf_name)

        # ------------------------------------------------------------------
        # 4. Deploy via SOP Bridge or legacy path
        # ------------------------------------------------------------------
        if _SOP_BRIDGE_ENABLED:
            from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.sop_bridge import SOPBridge

            bridge = SOPBridge()
            bridge_result = bridge.execute(
                nf_name=nf_name,
                plan=plan,
                strategy=strategy,
                namespace=nf_namespace,
                cluster=cluster_name,
            )
            if not bridge_result.success:
                log.error(
                    "SOP Bridge failed for NF '%s': %s (tier=%d, fallback=%s)",
                    nf_name, bridge_result.output[:200],
                    bridge_result.tier_used, bridge_result.fallback_used,
                )
                failed_nfs.append(nf_name)
                _update_plan_nf_status(plan, nf_name, bridge_result.phase)
                continue
            log.info(
                "SOP Bridge succeeded for NF '%s' (tier=%d, steps=%d)",
                nf_name, bridge_result.tier_used, bridge_result.steps_executed,
            )
        else:
            # Legacy path: direct drain + helm/argocd (SOP_BRIDGE_ENABLED=false)
            should_drain = _strategy_requires_drain(strategy)
            if should_drain:
                log.info("Draining NF '%s' before upgrade \u2026", nf_name)
                if not _drain_nf(nf_name, nf_namespace):
                    log.error("Drain failed for NF '%s'; aborting NF deployment", nf_name)
                    failed_nfs.append(nf_name)
                    _update_plan_nf_status(plan, nf_name, "DrainFailed")
                    continue

            catalog_entry = get_catalog_entry(catalog, nf_name)
            if catalog_entry:
                deploy_ok = _deploy_nf_helm(
                    nf_name=nf_name,
                    namespace=nf_namespace,
                    chart=catalog_entry.chart,
                    version=catalog_entry.version,
                )
            else:
                deploy_ok = _deploy_nf_argocd(nf_name, nf_namespace)

            if not deploy_ok:
                log.error("Deployment failed for NF '%s'", nf_name)
                failed_nfs.append(nf_name)
                _update_plan_nf_status(plan, nf_name, "DeployFailed")
                continue

            log.info("Waiting for rollout of NF '%s' \u2026", nf_name)
            if not _wait_for_rollout(nf_name, nf_namespace):
                log.error("Rollout timed-out for NF '%s'", nf_name)
                failed_nfs.append(nf_name)
                _update_plan_nf_status(plan, nf_name, "RolloutTimeout")
                continue


        # ------------------------------------------------------------------
        # 7. Post-deploy check
        # ------------------------------------------------------------------
        postdeploy_result = postdeploy_check(nf_name, nf_namespace)
        if postdeploy_result["status"] == "failed":
            log.error(
                "Post-deploy check failed for NF '%s': %s",
                nf_name,
                postdeploy_result["issues"],
            )
            failed_nfs.append(nf_name)
            _update_plan_nf_status(plan, nf_name, "PostDeployFailed")
            continue
        if postdeploy_result["status"] == "warning":
            log.warning(
                "Post-deploy warnings for NF '%s': %s",
                nf_name,
                postdeploy_result["issues"],
            )

        log.info("NF '%s' deployed successfully", nf_name)
        _update_plan_nf_status(plan, nf_name, "Deployed")

    # ------------------------------------------------------------------
    # 8. Update overall plan status
    # ------------------------------------------------------------------
    if failed_nfs:
        msg = f"Deployment completed with failures: {', '.join(failed_nfs)}"
        log.error(msg)
        _update_plan_status(plan, "PartiallyFailed", msg)
    else:
        msg = "All NFs deployed successfully"
        log.info("DeploymentPlan '%s': %s", name, msg)
        _update_plan_status(plan, "Completed", msg)


# ---------------------------------------------------------------------------
# NF ordering
# ---------------------------------------------------------------------------


def _resolve_nf_order(nfs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return *nfs* sorted according to the 3GPP dependency order.

    NFs whose type appears in :data:`_3GPP_ORDER` are placed first (in the
    declared order); NFs not found in the list are appended at the end,
    preserving their original relative order.

    Args:
        nfs: List of NF spec dicts, each containing at least a ``"name"`` key.

    Returns:
        Re-ordered list of NF dicts.
    """

    def _sort_key(nf: Dict[str, Any]) -> int:
        nf_name = nf.get("name", "").lower()
        try:
            return _3GPP_ORDER.index(nf_name)
        except ValueError:
            return len(_3GPP_ORDER)

    ordered = sorted(nfs, key=_sort_key)
    log.debug(
        "_resolve_nf_order: input=%s output=%s",
        [n.get("name") for n in nfs],
        [n.get("name") for n in ordered],
    )
    return ordered


# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------


def _get_strategy(
    nf_type: str,
    strategies: Optional[List[UpgradeStrategy]] = None,
) -> Optional[UpgradeStrategy]:
    """Map *nf_type* to an :class:`~agents.anda.config.UpgradeStrategy`.

    If *strategies* is ``None`` (e.g. called without pre-loading), the
    strategies are loaded fresh from disk.

    Args:
        nf_type:    NF type name (e.g. ``"amf"``).
        strategies: Pre-loaded strategy list, or ``None`` to load from disk.

    Returns:
        Matching :class:`~agents.anda.config.UpgradeStrategy` or ``None``.
    """
    if strategies is None:
        strategies = load_upgrade_strategy()
    return get_strategy_for_nf(strategies, nf_type)


def _strategy_requires_drain(strategy: Optional[UpgradeStrategy]) -> bool:
    """Return ``True`` if *strategy* contains a drain step.

    Args:
        strategy: Strategy to inspect, or ``None``.

    Returns:
        ``True`` if a step with ``action == "drain"`` is present.
    """
    if strategy is None:
        return False
    return any(
        step.get("action") == "drain" for step in strategy.steps
    )


# ---------------------------------------------------------------------------
# Deployment helpers
# ---------------------------------------------------------------------------


def _deploy_nf_helm(
    nf_name: str,
    namespace: str,
    chart: str,
    version: str,
) -> bool:
    """Deploy or upgrade an NF using ``helm upgrade --install``.

    Args:
        nf_name:   Helm release name (also used as the chart values prefix).
        namespace: Target namespace.
        chart:     Helm chart reference (OCI URI or repo/chart).
        version:   Chart version to install.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    cmd = (
        f"helm upgrade --install {nf_name} {chart} "
        f"--version {version} "
        f"--namespace {namespace} "
        f"--create-namespace "
        f"--wait "
        f"--timeout {_DEPLOY_TIMEOUT_SECONDS}s"
    )
    log.info("helm upgrade: %s", cmd)
    result = run_cmd(cmd, timeout=_DEPLOY_TIMEOUT_SECONDS + 30)
    if not result.success:
        log.error(
            "helm upgrade failed for NF '%s': %s", nf_name, result.output[:200]
        )
        return False
    log.info("helm upgrade succeeded for NF '%s': %s", nf_name, result.output[:200])
    return True


def _deploy_nf_argocd(nf_name: str, namespace: str) -> bool:
    """Trigger an ArgoCD application sync for *nf_name*.

    Assumes an ArgoCD Application named *nf_name* already exists in the
    cluster (created separately via GitOps).

    Args:
        nf_name:   ArgoCD Application name.
        namespace: Namespace where the Application lives (ArgoCD namespace).

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    cmd = (
        f"argocd app sync {nf_name} "
        f"--timeout {_DEPLOY_TIMEOUT_SECONDS} "
        f"--prune "
        f"--force"
    )
    log.info("ArgoCD sync: %s", cmd)
    result = run_cmd(cmd, timeout=_DEPLOY_TIMEOUT_SECONDS + 30)
    if not result.success:
        log.error(
            "ArgoCD sync failed for NF '%s': %s", nf_name, result.output[:200]
        )
        return False
    log.info("ArgoCD sync succeeded for NF '%s': %s", nf_name, result.output[:200])
    return True


def _drain_nf(nf_name: str, namespace: str) -> bool:
    """Cordon and drain pods for an NF before upgrade.

    Uses a label selector ``app=<nf_name>`` to identify the pods to evict,
    then waits for eviction to complete.

    Args:
        nf_name:   NF type name used as the ``app`` label value.
        namespace: Namespace to target.

    Returns:
        ``True`` if drain completed without errors, ``False`` otherwise.
    """
    cmd = (
        f"kubectl delete pods -n {namespace} -l app={nf_name} "
        f"--grace-period=60 --wait=true"
    )
    log.info("Draining NF '%s' in namespace '%s': %s", nf_name, namespace, cmd)
    result = run_cmd(cmd, timeout=120)
    if not result.success:
        log.error(
            "Drain failed for NF '%s': %s", nf_name, result.output[:200]
        )
        return False
    return True


def _wait_for_rollout(nf_name: str, namespace: str) -> bool:
    """Wait for all Deployments/StatefulSets with ``app=<nf_name>`` to roll out.

    Args:
        nf_name:   NF type name used as the ``app`` label value.
        namespace: Namespace to target.

    Returns:
        ``True`` if all rollouts completed within the timeout, ``False`` otherwise.
    """
    for resource_type in ("deployment", "statefulset"):
        result_list = run_cmd(
            f"kubectl get {resource_type} -n {namespace} -l app={nf_name} "
            f"-o jsonpath={{.items[*].metadata.name}}",
            timeout=30,
        )
        if not result_list.success or not result_list.stdout.strip():
            continue

        for resource_name in result_list.stdout.strip().split():
            cmd = (
                f"kubectl rollout status {resource_type}/{resource_name} "
                f"-n {namespace} "
                f"--timeout={_DEPLOY_TIMEOUT_SECONDS}s"
            )
            log.info("Waiting for rollout: %s", cmd)
            result = run_cmd(cmd, timeout=_DEPLOY_TIMEOUT_SECONDS + 30)
            if not result.success:
                log.error(
                    "Rollout status check failed for %s/%s: %s",
                    resource_type,
                    resource_name,
                    result.output[:200],
                )
                return False

    return True


# ---------------------------------------------------------------------------
# CR status helpers
# ---------------------------------------------------------------------------


def _plan_name(plan: Dict[str, Any]) -> str:
    """Extract the name of a DeploymentPlan CR for logging.

    Args:
        plan: Raw CR dict.

    Returns:
        ``"<namespace>/<name>"`` string.
    """
    meta = plan.get("metadata", {})
    ns = meta.get("namespace", "?")
    name = meta.get("name", "?")
    return f"{ns}/{name}"


def _update_plan_status(
    plan: Dict[str, Any], phase: str, message: str
) -> None:
    """Patch the ``status.phase`` and ``status.message`` of a DeploymentPlan CR.

    Args:
        plan:    Raw CR dict (provides namespace and name for the patch).
        phase:   New phase value (e.g. ``"InProgress"``, ``"Completed"``).
        message: Human-readable status message.
    """
    namespace = plan.get("metadata", {}).get("namespace", "default")
    name = plan.get("metadata", {}).get("name", "unknown")
    patch = json.dumps(
        {"status": {"phase": phase, "message": message}}
    )
    cmd = (
        f"kubectl patch {_CR_PLURAL}.{_CR_GROUP} {name} "
        f"-n {namespace} "
        f"--subresource=status "
        f"--type=merge "
        f"-p '{patch}'"
    )
    result = run_cmd(cmd, timeout=15)
    if not result.success:
        log.warning(
            "Failed to update plan status for '%s/%s': %s",
            namespace,
            name,
            result.output[:200],
        )
    else:
        log.debug("Updated plan '%s/%s' status: phase=%s", namespace, name, phase)


def _update_plan_nf_status(
    plan: Dict[str, Any], nf_name: str, status: str
) -> None:
    """Record the per-NF deployment status in the DeploymentPlan CR.

    Patches ``status.nfStatuses.<nf_name>`` with the given *status* string.

    Args:
        plan:    Raw CR dict.
        nf_name: Name of the NF whose status is being updated.
        status:  Status string (e.g. ``"Deployed"``, ``"DeployFailed"``).
    """
    namespace = plan.get("metadata", {}).get("namespace", "default")
    name = plan.get("metadata", {}).get("name", "unknown")
    patch = json.dumps({"status": {"nfStatuses": {nf_name: status}}})
    cmd = (
        f"kubectl patch {_CR_PLURAL}.{_CR_GROUP} {name} "
        f"-n {namespace} "
        f"--subresource=status "
        f"--type=merge "
        f"-p '{patch}'"
    )
    result = run_cmd(cmd, timeout=15)
    if not result.success:
        log.warning(
            "Failed to update NF status for '%s' in plan '%s/%s': %s",
            nf_name,
            namespace,
            name,
            result.output[:200],
        )
    else:
        log.debug(
            "Updated NF '%s' status to '%s' in plan '%s/%s'",
            nf_name,
            status,
            namespace,
            name,
        )
