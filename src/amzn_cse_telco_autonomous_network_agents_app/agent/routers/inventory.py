# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""FastAPI router for ANPA hardware inventory API.

Provides read access to ``HardwareInventory`` custom resources, a health
summary endpoint, and a background discovery trigger.
"""

from __future__ import annotations
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

router = APIRouter(tags=["inventory"])

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Endpoints  (order matters: static paths before path-param routes)
# ---------------------------------------------------------------------------


@router.get("/api/inventory")
def list_inventory():
    """List all HardwareInventory CRs across all namespaces.

    Returns a compact summary of each server (name, hostname, bmcAddress,
    model, serialNumber, cpu_count, memory_gib, phase, lastDiscovered).
    """
    result = run_cmd("kubectl get hardwareinventories -A -o json", timeout=30)
    if not result.success:
        raise HTTPException(
            status_code=502,
            detail=f"kubectl failed: {result.stderr}",
        )
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to parse kubectl output: {exc}")

    items: list = data.get("items", [])
    servers = [_summarise_inventory(item) for item in items]
    return {"servers": servers, "count": len(servers)}


@router.get("/api/inventory/health")
def inventory_health():
    """Return an aggregated health summary for the hardware inventory.

    Response shape::

        {
            "total":    int,
            "by_phase": {"Available": int, "Provisioned": int, ...},
            "errors":   [{"hostname": str, "issue": str}, ...],
        }

    An entry appears in ``errors`` when the ``HardwareInventory`` CR's
    ``status.error`` field is non-empty.
    """
    result = run_cmd("kubectl get hardwareinventories -A -o json", timeout=30)
    if not result.success:
        raise HTTPException(
            status_code=502,
            detail=f"kubectl failed: {result.stderr}",
        )
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to parse kubectl output: {exc}")

    by_phase: dict[str, int] = {}
    errors: list[dict] = []

    for item in data.get("items", []):
        meta = item.get("metadata", {})
        spec = item.get("spec", {})
        status = item.get("status", {})

        hostname: str = spec.get("hostname") or meta.get("name", "unknown")
        phase: str = status.get("phase", "Unknown")
        by_phase[phase] = by_phase.get(phase, 0) + 1

        error_msg: str = status.get("error", "")
        if error_msg:
            errors.append({"hostname": hostname, "issue": error_msg})

    return {
        "total": sum(by_phase.values()),
        "by_phase": by_phase,
        "errors": errors,
    }


@router.post("/api/inventory/discover", status_code=202)
def trigger_discovery(background_tasks: BackgroundTasks):
    """Trigger a manual Redfish BMC discovery scan.

    The scan runs asynchronously as a FastAPI background task so that this
    endpoint returns immediately.  Progress is logged to the application log.
    """
    background_tasks.add_task(_run_discovery_background)
    return {
        "status": "accepted",
        "message": "Discovery scan queued; check application logs for progress",
    }


@router.get("/api/inventory/{hostname}/readiness")
def get_readiness(hostname: str, nf: str = "upf"):
    """Assess whether *hostname* is ready to host the named NF.

    Loads the HardwareInventory CR for *hostname*, fetches live BIOS +
    firmware details from its BMC, and compares them against the declarative
    profile under ``configs/nf-profiles/<nf>.yaml``.

    Read-only: never mutates BIOS, BMC, or cluster state.

    Query params:
      nf: profile name to evaluate against (default ``upf``).

    Returns: structured ReadinessReport (see preflight_reasoner).
    """
    # Local imports keep the router lightweight and avoid circulars.
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import bios_inspector  # noqa: WPS433
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.preflight_reasoner import (  # noqa: WPS433
        ai_explain,
        assess_readiness,
        load_profile,
    )

    try:
        profile = load_profile(nf)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"NF profile '{nf}' not found")

    cr_name = hostname.lower().replace("_", "-").replace(".", "-")
    result = run_cmd(f"kubectl get hardwareinventory {cr_name} -o json", timeout=15)
    if not result.success:
        if "not found" in (result.stderr or "").lower():
            raise HTTPException(
                status_code=404,
                detail=f"HardwareInventory for '{hostname}' not found — run discovery first",
            )
        raise HTTPException(status_code=502, detail=f"kubectl failed: {result.stderr}")

    try:
        cr = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"could not parse CR: {exc}")

    spec = cr.get("spec", {}) or {}
    bmc_address = spec.get("bmcAddress", "")
    if not bmc_address:
        raise HTTPException(
            status_code=409,
            detail=f"HardwareInventory for '{hostname}' has no bmcAddress",
        )

    # Live BIOS + firmware fetch (read-only Redfish). Failures are tolerated:
    # the deterministic checker degrades to "BIOS attribute not exposed" gaps.
    bios_attrs = bios_inspector.get_bios_attributes(bmc_address)
    firmware = bios_inspector.get_firmware_inventory(bmc_address)

    report = assess_readiness(
        nf=nf,
        hostname=hostname,
        hardware_inventory=spec,
        bios_attributes=bios_attrs,
        firmware_inventory=firmware,
        profile=profile,
    )
    response = report.to_dict()
    response["explanation"] = ai_explain(report)
    return response


@router.get("/api/inventory/{hostname}")
def get_inventory(hostname: str):
    """Get the full HardwareInventory CR for *hostname*.

    The hostname is normalised to a valid Kubernetes name (lowercase, dots and
    underscores replaced with dashes) before querying the API server.
    """
    cr_name = hostname.lower().replace("_", "-").replace(".", "-")
    # Search across all namespaces using a label/name match
    result = run_cmd(
        f"kubectl get hardwareinventory {cr_name} -A -o json",
        timeout=15,
    )
    if not result.success:
        stderr = result.stderr or ""
        if "not found" in stderr.lower():
            raise HTTPException(
                status_code=404,
                detail=f"HardwareInventory for '{hostname}' not found",
            )
        raise HTTPException(status_code=502, detail=f"kubectl failed: {stderr}")

    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to parse kubectl output: {exc}")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _summarise_inventory(item: dict) -> dict:
    """Return a compact summary dict from a raw HardwareInventory CR."""
    meta = item.get("metadata", {})
    spec = item.get("spec", {})
    status = item.get("status", {})
    hardware = spec.get("hardware", {})
    return {
        "name": meta.get("name"),
        "namespace": meta.get("namespace"),
        "hostname": spec.get("hostname"),
        "bmcAddress": spec.get("bmcAddress"),
        "model": spec.get("model"),
        "serialNumber": spec.get("serialNumber"),
        "cpu_count": hardware.get("cpu", {}).get("count", 0),
        "memory_gib": hardware.get("memory", {}).get("totalGiB", 0),
        "phase": status.get("phase", "Unknown"),
        "lastDiscovered": meta.get("creationTimestamp", ""),
    }


def _run_discovery_background() -> None:
    """Background task: scan BMC subnets and register discovered hardware.

    Derives subnets from the site-config BMC IP list.  Each discovered server
    is applied as a ``HardwareInventory`` CR via ``kubectl apply``.
    """
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import discovery  # pylint: disable=import-outside-toplevel
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config     # pylint: disable=import-outside-toplevel

        config = load_config()
        namespace: str = config.tinkerbell_namespace

        # Derive unique /24 subnets from configured BMC IPs
        subnets: list[str] = []
        for node in config.nodes:
            if node.bmc.ip:
                octets = node.bmc.ip.rsplit(".", 1)
                if len(octets) == 2:
                    subnets.append(f"{octets[0]}.0/24")
        subnets = list(dict.fromkeys(subnets))

        if not subnets:
            logger.info("No BMC subnets found in config; background discovery skipped")
            return

        total = 0
        for subnet in subnets:
            logger.info("Background Redfish scan: %s", subnet)
            try:
                discovered = discovery.scan_redfish_endpoints(subnet_cidr=subnet)
                for hw in discovered:
                    try:
                        discovery.create_hardware_inventory_cr(hw, namespace=namespace)
                        total += 1
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.warning(
                            "Failed to register %s: %s",
                            hw.get("hostname", hw.get("ip", "?")),
                            exc,
                        )
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Scan of %s failed: %s", subnet, exc)

        logger.info("Background discovery complete: %d server(s) registered", total)

    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Background discovery task failed: %s", exc)
