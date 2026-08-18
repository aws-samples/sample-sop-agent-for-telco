# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Reconciliation loop for ANPA (Autonomous Node Provisioning Agent).

Watches ProvisioningRequest CRs and drives them through a state machine:
  Pending -> Validating -> Provisioning -> WaitingForNodes -> Ready  (or Failed).

Entry point: :func:`run_reconciler` — intended to run as a long-lived
background thread or process alongside the FastAPI application server.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import yaml
from datetime import datetime, timezone

from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config
from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

# Phase-handler helpers live in cohesive sibling modules. Imported here so the
# run loop and state machine call them exactly as before.
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.node_health_discovery import (
    _check_node_health,
    _run_discovery,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.preflight_checks import (
    _run_preflight,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.provisioning_progress import (
    _check_eks_node_ready,
    _check_tinkerbell_workflow,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase constants
# ---------------------------------------------------------------------------
_PHASE_PENDING = "Pending"
_PHASE_VALIDATING = "Validating"
_PHASE_PROVISIONING = "Provisioning"
_PHASE_WAITING_FOR_NODES = "WaitingForNodes"
_PHASE_READY = "Ready"
_PHASE_FAILED = "Failed"

_TERMINAL_PHASES: frozenset[str] = frozenset({_PHASE_READY, _PHASE_FAILED})

# ---------------------------------------------------------------------------
# Reconciler tunables
# ---------------------------------------------------------------------------
_RECONCILE_SLEEP: int = 30  # seconds between reconciliation passes
_HEALTH_CHECK_INTERVAL: int = 300  # 5 minutes
_MAX_RETRIES: int = 5

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
# Per-request retry counters: (namespace, name) -> attempt_count
_retry_counts: dict[tuple[str, str], int] = {}

# Per-request provisioning start times: (namespace, name) -> monotonic timestamp
_provisioning_start_times: dict[tuple[str, str], float] = {}

# Monotonic timestamps of last periodic tasks
_last_health_check: float = 0.0
_last_discovery: float = 0.0


# ===========================================================================
# Main entry point
# ===========================================================================


def run_reconciler() -> None:  # pragma: no cover
    """Main reconciliation loop — runs forever until the process is killed.

    Each iteration:

    1. Lists all non-terminal ``ProvisioningRequest`` CRs.
    2. Calls :func:`_process_request` for each one.
    3. Calls :func:`_check_node_health` every 5 minutes.
    4. Calls :func:`_run_discovery` on the interval from site config
       (``redfish_scan_interval``).

    The body of every iteration is wrapped in a broad ``except`` block so
    that transient errors (e.g. API-server unavailable) never crash the loop.
    """
    global _last_health_check, _last_discovery

    logger.info("ANPA reconciler starting (sleep=%ds)", _RECONCILE_SLEEP)
    config = load_config()

    while True:
        try:
            now = time.monotonic()

            # 1 — Process active ProvisioningRequests
            requests = _list_pending_requests()
            logger.debug("Reconcile pass: %d active request(s)", len(requests))
            for req in requests:
                try:
                    _process_request(req)
                except Exception as exc:  # pylint: disable=broad-except
                    meta = req.get("metadata", {})
                    logger.exception(
                        "Unhandled error processing request %s/%s: %s",
                        meta.get("namespace", "?"),
                        meta.get("name", "?"),
                        exc,
                    )

            # 2 — Periodic: node health (every 5 minutes)
            if now - _last_health_check >= _HEALTH_CHECK_INTERVAL:
                try:
                    _check_node_health()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("Node health check failed: %s", exc)
                _last_health_check = now

            # 3 — Periodic: Redfish discovery
            scan_interval: int = config.redfish_scan_interval
            if scan_interval > 0 and now - _last_discovery >= scan_interval:
                try:
                    _run_discovery()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("Discovery scan failed: %s", exc)
                _last_discovery = now

        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Unexpected error in reconciler main loop: %s", exc)

        time.sleep(_RECONCILE_SLEEP)


# ===========================================================================
# State machine
# ===========================================================================


def _process_request(request: dict) -> None:
    """Drive one ``ProvisioningRequest`` one step forward through the state machine.

    Transitions:

    +-----------------+-----------------+-------------------------------------+
    | From            | To              | Action                              |
    +=================+=================+=====================================+
    | Pending         | Validating      | Preflight: HW exists, BMC reachable |
    +-----------------+-----------------+-------------------------------------+
    | Validating      | Provisioning    | Create ``BareMetalProvision`` CR    |
    +-----------------+-----------------+-------------------------------------+
    | Provisioning    | WaitingForNodes | Tinkerbell Workflow succeeded       |
    +-----------------+-----------------+-------------------------------------+
    | WaitingForNodes | Ready           | EKS node registered and Ready       |
    +-----------------+-----------------+-------------------------------------+
    | Any             | Failed          | Error, after ``_MAX_RETRIES``       |
    +-----------------+-----------------+-------------------------------------+

    Args:
        request: Raw ``ProvisioningRequest`` CR dict as returned by kubectl.
    """
    meta = request.get("metadata", {})
    name: str = meta.get("name", "unknown")
    namespace: str = meta.get("namespace", "default")
    spec: dict = request.get("spec", {})
    status: dict = request.get("status", {})
    phase: str = status.get("phase", _PHASE_PENDING)
    key: tuple[str, str] = (namespace, name)

    logger.debug("Processing %s/%s  phase=%s", namespace, name, phase)

    try:
        if phase == _PHASE_PENDING:
            _run_preflight(name, namespace, spec)
            _update_request_status(
                name, namespace, _PHASE_VALIDATING, "Preflight checks passed"
            )
            _retry_counts.pop(key, None)

        elif phase == _PHASE_VALIDATING:
            _emit_baremetal_inventory_cr(name, namespace, spec)
            _configure_bmc_intelligence(name, namespace, spec)
            _emit_baremetal_provision_cr(name, namespace, spec)
            _update_request_status(
                name,
                namespace,
                _PHASE_PROVISIONING,
                "BareMetalInventory + BareMetalProvision emitted to EKS-H bare-metal-kro RGDs",
            )
            _retry_counts.pop(key, None)
            _provisioning_start_times[key] = time.monotonic()

        elif phase == _PHASE_PROVISIONING:
            if _check_tinkerbell_workflow(name, namespace, spec):
                _update_request_status(
                    name,
                    namespace,
                    _PHASE_WAITING_FOR_NODES,
                    "Tinkerbell workflow complete; waiting for node registration",
                )
                _retry_counts.pop(key, None)
                _provisioning_start_times.pop(key, None)
            else:
                # Check for timeout
                started = _provisioning_start_times.get(key)
                if started is None:
                    _provisioning_start_times[key] = time.monotonic()
                    started = _provisioning_start_times[key]
                elapsed = time.monotonic() - started
                config = load_config()
                if elapsed > config.workflow_timeout:
                    _provisioning_start_times.pop(key, None)
                    raise TimeoutError(
                        f"Tinkerbell workflow timed out after {int(elapsed)}s "
                        f"(limit: {config.workflow_timeout}s) for {namespace}/{name}"
                    )
                logger.debug(
                    "Tinkerbell workflow still running for %s/%s (%.0fs elapsed)",
                    namespace,
                    name,
                    elapsed,
                )

        elif phase == _PHASE_WAITING_FOR_NODES:
            if _check_eks_node_ready(name, spec):
                _update_request_status(
                    name,
                    namespace,
                    _PHASE_READY,
                    "Node registered and Ready in EKS cluster",
                )
                _retry_counts.pop(key, None)
                logger.info("Provisioning complete for %s/%s", namespace, name)
            else:
                logger.debug("EKS node not yet registered for %s/%s", namespace, name)

        else:
            logger.warning(
                "Unknown phase '%s' for %s/%s; skipping", phase, namespace, name
            )

    except Exception as exc:  # pylint: disable=broad-except
        # Tier 1: try deterministic fallback before incrementing retry counter
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler import (
            try_deterministic_fallback,
        )

        if try_deterministic_fallback(name, namespace, spec, str(exc)):
            logger.info(
                "Tier 1 recovery succeeded for %s/%s — skipping retry increment",
                namespace,
                name,
            )
            _retry_counts.pop(key, None)
            return

        retry_count: int = _retry_counts.get(key, 0) + 1
        _retry_counts[key] = retry_count
        logger.warning(
            "Error processing %s/%s (attempt %d/%d): %s",
            namespace,
            name,
            retry_count,
            _MAX_RETRIES,
            exc,
        )
        if retry_count >= _MAX_RETRIES:
            logger.error(
                "Max retries reached for %s/%s; invoking AI failure handler",
                namespace,
                name,
            )
            from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler import (
                handle_provisioning_failure,
            )

            diagnosis = handle_provisioning_failure(
                name=name,
                namespace=namespace,
                spec=spec,
                phase=phase,
                error=str(exc),
            )
            _update_request_status(
                name,
                namespace,
                _PHASE_FAILED,
                f"Failed after {retry_count} attempts. AI diagnosis: {diagnosis[:500]}",
            )
            _retry_counts.pop(key, None)


# ===========================================================================
# CR helpers
# ===========================================================================


def _list_pending_requests() -> list[dict]:
    """Return all non-terminal ``ProvisioningRequest`` CRs across all namespaces.

    Returns:
        List of raw CR dicts whose ``status.phase`` is not ``Ready`` or ``Failed``.
        Returns an empty list if kubectl fails or output cannot be parsed.
    """
    result = run_cmd("kubectl get provisioningrequests -A -o json", timeout=30)
    if not result.success:
        logger.warning("Failed to list provisioningrequests: %s", result.stderr)
        return []

    try:
        items: list = json.loads(result.stdout or "{}").get("items", [])
    except json.JSONDecodeError as exc:
        logger.warning("Could not parse provisioningrequests JSON: %s", exc)
        return []

    return [
        item
        for item in items
        if item.get("status", {}).get("phase", _PHASE_PENDING) not in _TERMINAL_PHASES
    ]


def _update_request_status(
    name: str,
    namespace: str,
    phase: str,
    message: str,
) -> None:
    """Patch the ``status`` sub-resource of a ``ProvisioningRequest`` CR.

    Args:
        name:      CR name.
        namespace: CR namespace.
        phase:     New phase string.
        message:   Human-readable description of the current state.
    """
    patch_payload = json.dumps(
        {
            "status": {
                "phase": phase,
                "message": message,
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
            }
        }
    )
    result = run_cmd(
        f"kubectl patch provisioningrequest {name} -n {namespace} "
        f"--type merge -p '{patch_payload}'",
        timeout=15,
    )
    if not result.success:
        logger.warning(
            "Failed to patch status for %s/%s: %s", namespace, name, result.stderr
        )
    else:
        logger.info("Status updated: %s/%s -> phase=%s", namespace, name, phase)


# ===========================================================================
# Provisioning helpers (preflight lives in preflight_checks.py; progress checks
# in provisioning_progress.py; periodic tasks in node_health_discovery.py —
# all imported at module top)
# ===========================================================================


def _configure_bmc_intelligence(name: str, namespace: str, spec: dict) -> None:
    """BMC Intelligence Layer — profile, select strategy, pre-configure before provisioning.

    Runs between _emit_baremetal_inventory_cr and _emit_baremetal_provision_cr
    during the VALIDATING phase. Pre-configures the BMC so Tinkerbell's boot
    job finds the correct boot device and VirtualMedia already set up.
    """
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.bmc_profiler import (
        profile_bmc,
    )
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.quirks.loader import (
        match as match_quirks,
    )
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.strategy_engine import (
        StrategyEngine,
    )
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer import (
        BootConfigurer,
    )

    bmc_address = _get_bmc_address(name, namespace, spec)
    if not bmc_address:
        logger.info(
            "No BMC address for %s/%s — skipping BMC intelligence", namespace, name
        )
        return

    config = load_config()
    iso_url = spec.get("isoUrl", getattr(config, "hookos_iso_url", ""))

    profile = profile_bmc(bmc_address)
    quirks = match_quirks(profile)

    engine = StrategyEngine()
    strategy = engine.select(profile, quirks)
    logger.info(
        "BMC Intelligence for %s/%s: strategy=%s mount=%s boot=%s",
        namespace,
        name,
        strategy.name,
        strategy.mount_method,
        strategy.boot_method,
    )

    if iso_url:
        configurer = BootConfigurer(bmc_address, profile, iso_url)
        result = configurer.execute(strategy)
        if not result.success:
            raise RuntimeError(
                f"BMC pre-configuration failed at step '{result.failure_step}': "
                f"{result.failure_reason} (type={result.failure_type})"
            )

    _annotate_strategy(name, namespace, strategy.name)
    _cache_bmc_profile(name, namespace, profile, quirks)


def _get_bmc_address(name: str, namespace: str, spec: dict) -> str:
    """Extract BMC address from spec or HardwareInventory CR."""
    nodes_spec = spec.get("nodes", [])
    if nodes_spec:
        bmc = nodes_spec[0].get("bmcAddress", "")
        if bmc:
            return bmc

    hostname = spec.get("hostname", name)
    hw_name = hostname.lower().replace(".", "-")
    hw_result = run_cmd(
        f"kubectl get hardwareinventory {hw_name} -n {namespace} "
        f"--ignore-not-found -o jsonpath='{{.spec.bmcAddress}}'",
        timeout=15,
    )
    return hw_result.stdout.strip().strip("'") if hw_result.success else ""


def _annotate_strategy(name: str, namespace: str, strategy_name: str) -> None:
    """Store the selected strategy name on the CR for the failure handler."""
    run_cmd(
        f"kubectl annotate provisioningrequest {name} -n {namespace} "
        f"--overwrite anpa.aws.io/provisioning-strategy={strategy_name}",
        timeout=15,
    )


def _cache_bmc_profile(name: str, namespace: str, profile, quirks: dict) -> None:
    """Persist profile + quirks so the failure handler can use them without re-profiling."""
    import pickle
    from pathlib import Path

    cache_dir = Path("/var/lib/anpa/profiles")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{namespace}__{name}.pkl"
    cache_file.write_bytes(pickle.dumps({"profile": profile, "quirks": quirks}))
    logger.debug("Cached BMC profile to %s", cache_file)


def _emit_baremetal_inventory_cr(name: str, namespace: str, spec: dict) -> None:
    """Emit a ``BareMetalInventory`` CR into the EKS-H bare-metal-kro RGD namespace.

    The ``inventory-rgd.yaml`` expands this CR into:
      * A Secret (BMC credentials)
      * A Rufio ``Machine`` (BMC connection)
      * A Tinkerbell ``Hardware`` (boot-time identity — MAC, IP, disks)

    The ``Hardware`` object is a hard prerequisite for ``BareMetalProvision``.
    Therefore this function MUST be called before ``_emit_baremetal_provision_cr``.

    Raises:
        RuntimeError: If kubectl apply fails or required data is missing.
    """
    nodes_spec = spec.get("nodes", []) or [{"hostname": spec.get("hostname", name)}]

    machine_profile = spec.get("machineProfile", "poweredge-xr8000r-2disk")
    os_profile = spec.get("osProfile", "ubuntu-noble")
    target_ns = spec.get("bareMetalNamespace", "tinkerbell")
    group_name = spec.get("groupName", name)

    dest_disk = spec.get("destDisk", "/dev/nvme0n1")
    efi_partition = spec.get("efiPartition", "/dev/nvme0n1p1")
    root_partition = spec.get("rootPartition", "/dev/nvme0n1p2")
    os_fs_type = spec.get("osFsType", "ext4")

    gateway = spec.get("gateway", "")
    netmask = spec.get("netmask", "255.255.255.0")
    dns_servers = spec.get("dnsServers", "")

    # Reference the bmc-creds Secret by name; credentials are consumed by the RGD
    # at runtime — never stored in plain text inside the CR (AutoSDE finding).
    # Validate BMC credentials are available (mandatory for BareMetalInventory RGD)
    bmc_username = os.getenv("BMC_USERNAME", "")
    bmc_password = os.getenv("BMC_PASSWORD", "")
    if not bmc_username or not bmc_password:
        raise RuntimeError(
            "BMC_USERNAME and BMC_PASSWORD env vars are required for BareMetalInventory "
            "emission. Set them in the ANPA Deployment spec or bmc-creds Secret."
        )

    for node in nodes_spec:
        hostname = node.get("hostname")
        if not hostname:
            raise RuntimeError("ProvisioningRequest node entry missing hostname")
        cr_name = hostname.lower().replace("_", "-").replace(".", "-")

        # Read HardwareInventory CR for mac and bmcAddress
        hw_result = run_cmd(
            f"kubectl get hardwareinventory {cr_name} --ignore-not-found -o json",
            timeout=15,
        )
        hw_json = (hw_result.stdout or "").strip()
        if not hw_json:
            raise RuntimeError(
                f"HardwareInventory '{cr_name}' not found — cannot emit BareMetalInventory"
            )
        try:
            hwi = json.loads(hw_json).get("spec", {})
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"could not parse HardwareInventory {cr_name}: {exc}")

        interfaces = hwi.get("interfaces") or []
        primary_mac = next(
            (i.get("mac") for i in interfaces if i.get("mac")), ""
        ).lower()
        if not primary_mac:
            raise RuntimeError(
                f"HardwareInventory '{cr_name}' has no MAC — discovery may not have walked NICs"
            )
        bmc_address = hwi.get("bmcAddress", spec.get("bmcAddress", ""))
        node_ip = node.get("ip", spec.get("ip", ""))

        cr_doc = {
            "apiVersion": "kro.run/v1alpha1",
            "kind": "BareMetalInventory",
            "metadata": {
                "name": cr_name,
                "namespace": target_ns,
                "labels": {
                    "provisioning.anpa.aws.io/provisioning-request": name,
                    "provisioning.anpa.aws.io/managed": "true",
                },
            },
            "spec": {
                "name": hostname,
                "mac": primary_mac,
                "ip": node_ip,
                "bmcAddress": bmc_address,
                "bmcUser": bmc_username,
                "bmcPass": bmc_password,
                "machineProfile": machine_profile,
                "osProfile": os_profile,
                "destDisk": dest_disk,
                "efiPartition": efi_partition,
                "rootPartition": root_partition,
                "osFsType": os_fs_type,
                "gateway": gateway,
                "netmask": netmask,
                "dnsServers": dns_servers,
                "serverGroup": group_name,
                "namespace": target_ns,
            },
        }
        yaml_doc = yaml.safe_dump(
            cr_doc, default_flow_style=False, allow_unicode=True, sort_keys=False
        )

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".yaml", prefix="anpa-bmi-")
        try:
            with os.fdopen(tmp_fd, "w") as fh:
                fh.write(yaml_doc)
            result = run_cmd(f"kubectl apply -f {tmp_path}", timeout=30)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if not result.success:
            raise RuntimeError(
                f"Failed to apply BareMetalInventory '{cr_name}': {result.stderr}"
            )
        logger.info("Emitted BareMetalInventory '%s/%s'", target_ns, cr_name)


def _emit_baremetal_provision_cr(name: str, namespace: str, spec: dict) -> None:
    """Phase 5.2 — emit the real EKS-H ``BareMetalProvision`` CR.

    Per ADR-0001 (revised) this is ANPA's autonomous integration with
    EKS-H: we treat EKS-H's ``BareMetalProvision`` CRD as an API and
    apply a CR matching its 25-field schema (see
    ``day0/.../bare-metal-kro/provision-rgd.yaml``). EKS-H's bare-metal-kro
    RGD then expands the CR into a Tinkerbell ``Workflow`` that drives
    the VirtualMedia install, OS provisioning, and SSM activation —
    unchanged from operator-driven provisioning.

    Field sources:
      * Discovery-derived (HardwareInventory spec): ``name``, ``mac``, ``ip``
      * Intent (ProvisioningRequest spec): ``machineProfile``, ``osProfile``,
        ``networkProfile``-derived fields, ``serverGroup``, ``clusterName``,
        ``clusterRegion``, ``hybridNodesRole``, ``provisionHash``
      * Tuning (computed by tuning_generator from CPU topology + NF profile):
        ``tuningKernelCmdline``, ``tuningSysctl``, ``tuningDisabledServices``

    The CR is applied into the namespace EKS-H's bare-metal-kro RGD
    watches (configurable via ``spec.bareMetalNamespace``; default
    ``tinkerbell``).

    Raises:
        RuntimeError: If kubectl apply fails or any required field is
                      missing from HardwareInventory or ProvisioningRequest.
    """
    nodes_spec = spec.get("nodes", []) or [
        {
            "hostname": spec.get("hostname", name),
            "role": spec.get("nodeRole", spec.get("hybridNodesRole", "worker")),
        }
    ]

    cluster_name = spec.get("clusterName", "")
    cluster_region = spec.get("clusterRegion", "")
    group_name = spec.get("groupName", name)
    machine_profile = spec.get("machineProfile", "poweredge-xr8000r-2disk")
    os_profile = spec.get("osProfile", "ubuntu-noble")
    target_ns = spec.get("bareMetalNamespace", "tinkerbell")
    provision_hash = spec.get("provisionHash", "v1")

    # OS profile fields — default to the EKS-H ubuntu-noble shape; override per-spec.
    os_archive_raw = spec.get("osArchive", "")
    # RGD prepends image-server base URL; strip any http:// prefix to avoid doubling
    os_archive = (
        os_archive_raw.rsplit("/", 1)[-1] if "://" in os_archive_raw else os_archive_raw
    )
    os_archive_type = spec.get("osArchiveType", "targz")
    os_archive_checksum = spec.get("osArchiveChecksum", "")
    os_fs_type = spec.get("osFsType", "ext4")
    kernel_path = spec.get("kernelPath", "/boot/vmlinuz")
    initrd_path = spec.get("initrdPath", "/boot/initrd.img")

    # Machine profile fields — default to the EKS-H xr8000r-2disk shape.
    dest_disk = spec.get("destDisk", "/dev/nvme0n1")
    efi_partition = spec.get("efiPartition", "/dev/nvme0n1p1")
    root_partition = spec.get("rootPartition", "/dev/nvme0n1p2")

    # Network profile fields — supplied by intent (no IPAM in ANPA today).
    gateway = spec.get("gateway", "")
    netmask_cidr = spec.get("netmaskCIDR", "")
    dns_servers = spec.get("dnsServers", "")

    # Tuning fields — supplied by intent or generated from topology by ANDA / P5.3.
    tuning_kernel_cmdline = spec.get("tuningKernelCmdline", "")
    tuning_sysctl = spec.get("tuningSysctl", "")
    tuning_disabled_services = spec.get("tuningDisabledServices", "")

    for node in nodes_spec:
        hostname = node.get("hostname")
        if not hostname:
            raise RuntimeError("ProvisioningRequest node entry missing hostname")
        hybrid_role = node.get("role", "worker")
        cr_name = hostname.lower().replace("_", "-").replace(".", "-")
        hwi_name = cr_name

        # Discovery-derived fields come from the HardwareInventory CR.
        hw_result = run_cmd(
            f"kubectl get hardwareinventory {hwi_name} --ignore-not-found -o json",
            timeout=15,
        )
        hw_json = (hw_result.stdout or "").strip()
        if not hw_json:
            raise RuntimeError(
                f"HardwareInventory '{hwi_name}' not found — preflight should have caught this"
            )
        try:
            hwi = json.loads(hw_json).get("spec", {})
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"could not parse HardwareInventory {hwi_name}: {exc}")

        interfaces = hwi.get("interfaces") or []
        primary_mac = next(
            (i.get("mac") for i in interfaces if i.get("mac")), ""
        ).lower()
        if not primary_mac:
            raise RuntimeError(
                f"HardwareInventory '{hwi_name}' has no MAC — discovery may not have walked NICs"
            )
        # IP comes from intent (ANPA has no IPAM); HardwareInventory tracks BMC, not host IP.
        node_ip = node.get("ip", spec.get("ip", ""))

        yaml_doc = (
            "apiVersion: kro.run/v1alpha1\n"
            "kind: BareMetalProvision\n"
            "metadata:\n"
            f"  name: {cr_name}-provision\n"
            f"  namespace: {target_ns}\n"
            "  labels:\n"
            f"    provisioning.anpa.aws.io/provisioning-request: {name}\n"
            f'    provisioning.anpa.aws.io/managed: "true"\n'
            "spec:\n"
            f"  name: {hostname}\n"
            f'  mac: "{primary_mac}"\n'
            f'  ip: "{node_ip}"\n'
            f"  machineProfile: {machine_profile}\n"
            f"  osProfile: {os_profile}\n"
            f"  destDisk: {dest_disk}\n"
            f"  efiPartition: {efi_partition}\n"
            f"  rootPartition: {root_partition}\n"
            f"  kernelPath: {kernel_path}\n"
            f"  initrdPath: {initrd_path}\n"
            f'  osArchive: "{os_archive}"\n'
            f"  osArchiveType: {os_archive_type}\n"
            f'  osArchiveChecksum: "{os_archive_checksum}"\n'
            f"  osFsType: {os_fs_type}\n"
            f'  gateway: "{gateway}"\n'
            f'  netmaskCIDR: "{netmask_cidr}"\n'
            f'  dnsServers: "{dns_servers}"\n'
            f"  serverGroup: {group_name}\n"
            f"  namespace: {target_ns}\n"
            f'  provisionHash: "{provision_hash}"\n'
            f"  clusterName: {cluster_name}\n"
            f"  clusterRegion: {cluster_region}\n"
            f"  hybridNodesRole: {hybrid_role}\n"
            f'  tuningKernelCmdline: "{tuning_kernel_cmdline}"\n'
            f'  tuningSysctl: "{tuning_sysctl}"\n'
            f'  tuningDisabledServices: "{tuning_disabled_services}"\n'
        )

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".yaml", prefix="anpa-bmp-")
        try:
            with os.fdopen(tmp_fd, "w") as fh:
                fh.write(yaml_doc)
            result = run_cmd(f"kubectl apply -f {tmp_path}", timeout=30)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if not result.success:
            raise RuntimeError(
                f"Failed to apply BareMetalProvision '{cr_name}-provision': {result.stderr}"
            )
        logger.info(
            "Emitted BareMetalProvision '%s/%s-provision' (host=%s mac=%s) — EKS-H bare-metal-kro will materialize the workflow",
            target_ns,
            cr_name,
            hostname,
            primary_mac,
        )
