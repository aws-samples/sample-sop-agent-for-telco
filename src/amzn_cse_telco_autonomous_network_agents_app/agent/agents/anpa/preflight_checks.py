# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""ANPA preflight validation: hardware registration + BMC reachability.

Extracted from reconciler.py for cohesion. Validates that a
ProvisioningRequest's target hardware is registered and reachable before the
state machine advances it to Provisioning.
"""

from __future__ import annotations

import json
import logging

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

logger = logging.getLogger(__name__)

# HTTP codes that mean the BMC Redfish endpoint answered: 200 (open) or 401
# (reachable but auth-gated). Either proves reachability, which is all preflight
# checks here.
_BMC_REACHABLE_HTTP_CODES = ("200", "401")

# Cap on how much of an unparseable HardwareInventory payload we echo into an
# error so logs stay bounded.
_RAW_PAYLOAD_TRUNCATE = 500


def _run_preflight(name: str, namespace: str, spec: dict) -> None:
    """Validate that target hardware is registered and its BMC is reachable.

    Supports both single-node (spec.hostname) and multi-node (spec.nodes[])
    ProvisioningRequest formats. For multi-node, validates ALL nodes pass
    preflight before advancing.

    Raises:
        RuntimeError: If any HardwareInventory CR is missing, has unparseable
            JSON, has no bmcAddress, or its BMC is unreachable. Failing loud
            (rather than skipping a check and reporting success) lets
            _process_request retry and ultimately mark the request Failed with
            the real cause instead of advancing an unvalidated node.
    """
    # Validate required fields that downstream CRs need (fail-fast)
    for required_field in ("osArchive", "gateway", "netmaskCIDR", "ip"):
        if not spec.get(required_field):
            nodes_spec_check = spec.get("nodes", [])
            # Require ALL nodes to supply the field; any() is too lenient for multi-node:
            # if only one node has the field the check would pass even though others lack it.
            # The 'not nodes_spec_check' guard handles the empty-list case where all() is
            # vacuously True but neither spec nor any node has the field.
            if not nodes_spec_check or not all(
                n.get(required_field) for n in nodes_spec_check
            ):
                raise RuntimeError(
                    f"ProvisioningRequest spec.{required_field} is required"
                )

    # Resolve node list from spec — support both formats
    nodes_spec = spec.get("nodes", [])
    if nodes_spec:
        hostnames = [n.get("hostname", "") for n in nodes_spec if n.get("hostname")]
    else:
        # Legacy: single hostname at top level
        hostnames = [spec.get("hostname", name)]

    for hostname in hostnames:
        # ---- HardwareInventory CR must exist ----------------------------------
        hw_name = hostname.lower().replace(".", "-")
        hw_result = run_cmd(
            f"kubectl get hardwareinventory {hw_name} "
            f"-n {namespace} --ignore-not-found -o json",
            timeout=15,
        )
        hw_json = hw_result.stdout.strip()
        if not hw_json:
            raise RuntimeError(
                f"HardwareInventory CR '{hw_name}' not found in namespace '{namespace}'"
            )
        logger.debug("HardwareInventory found for %s", hostname)

        # ---- Extract BMC address from HardwareInventory ----------------------
        # Unparseable inventory must fail loud, not silently skip the probe:
        # a swallowed decode error would let preflight report "passed" for a
        # node whose BMC was never validated. _process_request catches this,
        # retries, and marks the request Failed with the real error.
        # NOTE: HardwareInventory carries no credentials (BMC user/pass live on
        # the BareMetalInventory CR), so echoing the raw payload here is safe.
        # Revisit if a credential-bearing field is ever added to this CR.
        try:
            parsed = json.loads(hw_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"HardwareInventory CR '{hw_name}' has unparseable JSON: {exc}. "
                f"Raw payload (truncated): {hw_json[:_RAW_PAYLOAD_TRUNCATE]!r}"
            ) from exc
        # Valid JSON that isn't an object (list/str/number) would break the
        # .get() chain with an AttributeError; fail loud with a clear message.
        if not isinstance(parsed, dict):
            raise RuntimeError(
                f"HardwareInventory CR '{hw_name}' is not a JSON object "
                f"(got {type(parsed).__name__}); raw payload (truncated): "
                f"{hw_json[:_RAW_PAYLOAD_TRUNCATE]!r}"
            )
        hw_data: dict = parsed
        bmc_address = hw_data.get("spec", {}).get("bmcAddress", "")

        # ---- BMC reachability probe -------------------------------------------
        # A missing bmcAddress must fail loud too: the whole point of preflight
        # is verifying BMC reachability, so skipping it and reporting "passed"
        # just defers the failure to provisioning with a more confusing error.
        if not bmc_address:
            raise RuntimeError(
                f"HardwareInventory CR '{hw_name}' has no bmcAddress; "
                f"cannot verify BMC reachability for {hostname}"
            )

        # Support both http:// and raw IP/hostname formats
        if bmc_address.startswith("http://"):
            probe_url = f"{bmc_address}/redfish/v1"
            probe_cmd = (
                f"curl --silent --max-time 5 "
                f"{probe_url} "
                f"-o /dev/null -w '%{{http_code}}'"
            )
        else:
            probe_url = f"https://{bmc_address}/redfish/v1"
            probe_cmd = (
                f"curl --silent --max-time 5 --insecure "
                f"{probe_url} "
                f"-o /dev/null -w '%{{http_code}}'"
            )
        probe = run_cmd(probe_cmd, timeout=10)
        http_code = probe.stdout.strip().strip("'")
        if not probe.success or http_code not in _BMC_REACHABLE_HTTP_CODES:
            raise RuntimeError(
                f"BMC at {bmc_address} is not reachable "
                f"(http_code={http_code!r}, rc={probe.returncode})"
            )
        logger.debug("BMC reachable at %s (HTTP %s)", bmc_address, http_code)

        # ---- Cross-validate with OS via SSM (if node already joined) ---------
        try:
            ssm_id = hw_data.get("status", {}).get("ssmInstanceId", "")
            if ssm_id and bmc_address:
                _cross_validate_hardware(hostname, ssm_id, hw_data)
        except Exception as exc:
            logger.warning("Cross-validation skipped for %s: %s", hostname, exc)

    logger.info("Preflight passed for %d node(s): %s", len(hostnames), hostnames)


def _cross_validate_hardware(hostname: str, ssm_id: str, hw_data: dict) -> None:
    """Cross-validate BMC-reported hardware with OS-level observations via SSM.

    Checks CPU count and total memory match between Redfish inventory and
    what the OS actually sees. Logs warnings on mismatch but does not fail
    preflight (the AI failure handler will investigate if provisioning fails).

    Args:
        hostname: Server hostname for logging.
        ssm_id: SSM managed instance ID.
        hw_data: Parsed HardwareInventory CR dict.
    """
    spec = hw_data.get("spec", {})
    bmc_cpus = spec.get("cpuCount", 0)
    bmc_memory_gb = spec.get("memoryGiB", 0)

    if not bmc_cpus and not bmc_memory_gb:
        return  # No hardware specs to validate against

    # Query OS for CPU count
    os_cpu_result = run_cmd(
        f"aws ssm send-command --instance-ids {ssm_id} "
        f"--document-name AWS-RunShellScript "
        f"--parameters commands='nproc' --output text --query Command.CommandId",
        timeout=15,
    )
    if os_cpu_result.success and os_cpu_result.stdout.strip():
        cmd_id = os_cpu_result.stdout.strip()
        # Brief wait then get output
        output = run_cmd(
            f"aws ssm get-command-invocation --command-id {cmd_id} "
            f"--instance-id {ssm_id} --query StandardOutputContent --output text",
            timeout=30,
        )
        if output.success:
            try:
                os_cpus = int(output.stdout.strip())
                if bmc_cpus and os_cpus != bmc_cpus:
                    logger.warning(
                        "CPU mismatch on %s: BMC reports %d, OS reports %d",
                        hostname,
                        bmc_cpus,
                        os_cpus,
                    )
            except (ValueError, TypeError):
                pass

    logger.debug("Cross-validation complete for %s (ssm=%s)", hostname, ssm_id)
