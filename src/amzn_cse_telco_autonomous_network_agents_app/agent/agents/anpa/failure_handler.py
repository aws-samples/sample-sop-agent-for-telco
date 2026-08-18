# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ANPA AI failure handler — invokes Strands agent to diagnose provisioning failures.

Exposed surface:
  * :func:`handle_provisioning_failure` — used by the reconciler when a
    ProvisioningRequest exhausts retries. Persists the structured diagnosis
    so the API can serve it back to operators.
  * :func:`get_last_diagnosis` — read the last persisted diagnosis for a
    request (consumed by ``GET /api/provisioning/requests/{name}/diagnosis``).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from strands import Agent

logger = logging.getLogger(__name__)


FAILURE_DIAGNOSIS_PROMPT = """You are ANPA's failure diagnosis agent. A bare-metal
provisioning operation has failed or stalled. Use the available tools to find
the root cause and recommend (or apply, if safe) a fix.

YOU HAVE THESE TOOL CATEGORIES:
- Provisioning actions: toggle_provision, bump_provision_hash, power_cycle_server,
  drain_and_delete_node, create_ssm_activation, ssm_run_command.
- Health/state inspection: get_workflow_status, get_node_status, get_hardware_health.
- Diagnosis (PREFERRED FIRST):
    * get_workflow_logs — per-action error messages from Tinkerbell (gold for
      Provisioning-phase failures).
    * read_bmc_sel — BMC System Event Log (hardware/firmware events).
    * inspect_node_join — full post-mortem when WaitingForNodes never advances.

INVESTIGATION ORDER:
1. Identify the failure phase. If it is "Provisioning", call get_workflow_logs
   FIRST — failed_actions[] usually contains the exact error message.
2. If hardware-related (thermal, ECC, NIC link, PSU), call read_bmc_sel.
3. If "WaitingForNodes" never advanced, call inspect_node_join.
4. Cross-check with ANRA only after the local picture is clear.

RULES:
- Read first, act second. Mutating actions (power cycle, bump hash, drain) are
  ONLY justified after diagnostic tools support the action.
- Never retry the same failed action more than once.
- If hardware is physically broken (disk failure, PSU fault, ECC), do NOT
  attempt software fixes — report and stop.
- Always check BMC health before power cycling.

OUTPUT FORMAT:
Structure your response so the first line is a single-sentence ROOT CAUSE,
followed by EVIDENCE (which tools returned what) and a RECOMMENDATION (the
specific next step or "no automated fix safe — escalate").
"""


KNOWN_RECOVERABLE_FAILURES = {
    "VIRTUAL_MEDIA_MOUNT_FAILED",
    "VIRTUAL_MEDIA_EJECT_FAILED",
    "DELL_OEM_BOOT_FAILED",
    "BOOT_OVERRIDE_FAILED",
    "RFS_CONFIGURE_FAILED",
}

# Path where the most recent diagnosis is persisted per (namespace, name).
# Stored as JSON in a per-process directory so the API can read it back.
# Override with ANPA_DIAGNOSIS_DIR for tests / non-default deployments.
_DIAGNOSIS_DIR = Path(os.environ.get("ANPA_DIAGNOSIS_DIR", "/var/lib/anpa/diagnoses"))
_PROFILE_DIR = Path("/var/lib/anpa/profiles")
_dir_lock = threading.Lock()


def _persist_diagnosis(namespace: str, name: str, payload: dict) -> None:
    """Write the latest diagnosis for (namespace, name) to disk."""
    try:
        with _dir_lock:
            _DIAGNOSIS_DIR.mkdir(parents=True, exist_ok=True)
            path = _DIAGNOSIS_DIR / f"{namespace}__{name}.json"
            path.write_text(json.dumps(payload))
    except OSError as exc:
        logger.warning(
            "could not persist diagnosis for %s/%s: %s", namespace, name, exc
        )


def get_last_diagnosis(namespace: str, name: str) -> dict | None:
    """Return the last persisted diagnosis dict, or None if none exists."""
    path = _DIAGNOSIS_DIR / f"{namespace}__{name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def try_deterministic_fallback(
    name: str, namespace: str, spec: dict, error: str
) -> bool:
    """Tier 1: immediate deterministic fallback for KNOWN failure patterns.

    Called by the reconciler BEFORE retry counter increment. If recovery
    succeeds, returns True (caller skips the retry). If failure is unknown
    or no fallback available, returns False (caller proceeds with normal retry).
    """
    from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

    strategy_name = _get_current_strategy(name, namespace)
    if not strategy_name:
        return False

    failure_type = _classify_failure(error)
    if failure_type not in KNOWN_RECOVERABLE_FAILURES:
        return False

    profile, quirks = _load_cached_profile(name, namespace)
    if not profile:
        return False

    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.strategy_engine import (
        StrategyEngine,
    )

    engine = StrategyEngine()
    fallback = engine.get_fallback_for_failure(strategy_name, failure_type, quirks)
    if not fallback:
        logger.info(
            "Tier 1: no fallback for %s after %s — deferring to retry/AI",
            strategy_name,
            failure_type,
        )
        return False

    logger.info(
        "Tier 1: %s/%s — %s failed, switching to fallback strategy '%s'",
        namespace,
        name,
        failure_type,
        fallback.name,
    )

    bmc_address = _get_bmc_address_from_spec(spec, name)
    if not bmc_address:
        return False

    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer import (
        BootConfigurer,
    )
    from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config

    config = load_config()
    iso_url = spec.get("isoUrl", getattr(config, "hookos_iso_url", ""))
    if not iso_url:
        return False

    configurer = BootConfigurer(bmc_address, profile, iso_url)
    result = configurer.execute(fallback)
    if not result.success:
        logger.warning(
            "Tier 1 fallback '%s' also failed at '%s': %s",
            fallback.name,
            result.failure_step,
            result.failure_reason,
        )
        return False

    # Update the strategy annotation so next failure uses the new chain position
    annotate_result = run_cmd(
        f"kubectl annotate provisioningrequest {name} -n {namespace} "
        f"--overwrite anpa.aws.io/provisioning-strategy={fallback.name}",
        timeout=15,
    )
    if not annotate_result.success:
        logger.warning(
            "Tier 1: fallback executed but annotation update failed for %s/%s: %s",
            namespace,
            name,
            annotate_result.stderr,
        )
        return False

    _record_outcome(name, namespace, strategy_name, failure_type, fallback.name)
    logger.info(
        "Tier 1 recovery succeeded: %s/%s now using '%s'",
        namespace,
        name,
        fallback.name,
    )
    return True


def _get_current_strategy(name: str, namespace: str) -> str:
    """Read the strategy annotation from the ProvisioningRequest CR."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

    result = run_cmd(
        f"kubectl get provisioningrequest {name} -n {namespace} "
        f"-o jsonpath='{{.metadata.annotations.anpa\\.aws\\.io/provisioning-strategy}}'",
        timeout=15,
    )
    return result.stdout.strip().strip("'") if result.success else ""


def _classify_failure(error: str) -> str:
    """Extract a failure_type from the error message."""
    for known_type in KNOWN_RECOVERABLE_FAILURES:
        if known_type in error:
            return known_type
    if "VirtualMedia" in error and (
        "mount" in error.lower() or "insert" in error.lower()
    ):
        return "VIRTUAL_MEDIA_MOUNT_FAILED"
    if "boot" in error.lower() and "override" in error.lower():
        return "BOOT_OVERRIDE_FAILED"
    return ""


def _load_cached_profile(name: str, namespace: str):
    """Load cached BMCProfile + quirks from disk."""
    import pickle

    cache_file = _PROFILE_DIR / f"{namespace}__{name}.pkl"
    if not cache_file.exists():
        return None, {}
    try:
        data = pickle.loads(cache_file.read_bytes())  # nosec B301 — trusted local cache written by this process
        return data.get("profile"), data.get("quirks", {})
    except Exception:
        return None, {}


def _get_bmc_address_from_spec(spec: dict, name: str) -> str:
    """Extract BMC address from spec."""
    nodes_spec = spec.get("nodes", [])
    if nodes_spec:
        return nodes_spec[0].get("bmcAddress", "")
    return spec.get("bmcAddress", "")


def _record_outcome(
    name: str, namespace: str, strategy_name: str, failure_type: str, fallback_name: str
) -> None:
    """Record strategy outcome for future learning."""
    outcome_file = _DIAGNOSIS_DIR / "strategy_outcomes.jsonl"
    try:
        _DIAGNOSIS_DIR.mkdir(parents=True, exist_ok=True)
        entry = json.dumps(
            {
                "request": f"{namespace}/{name}",
                "failed_strategy": strategy_name,
                "failure_type": failure_type,
                "fallback_used": fallback_name,
            }
        )
        with open(outcome_file, "a") as f:
            f.write(entry + "\n")
    except OSError:
        pass


def handle_provisioning_failure(
    name: str,
    namespace: str,
    spec: dict,
    phase: str,
    error: str,
) -> str:
    """Invoke Strands agent to diagnose a provisioning failure.

    On success the diagnosis is persisted (see :func:`get_last_diagnosis`)
    and returned. On any error a templated fallback is returned and the
    underlying exception is logged — never raised — so the reconciler
    can keep moving.

    Args:
        name: ProvisioningRequest CR name.
        namespace: CR namespace.
        spec: CR spec dict.
        phase: Phase where failure occurred.
        error: Error message from the last attempt.

    Returns:
        Diagnosis string (AI-authored or fallback).
    """
    # Tool registry — fail-soft on each subset.
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools import (
            PROVISION_TOOLS,
        )
    except ImportError:
        logger.warning("PROVISION_TOOLS not available; using empty tool list")
        PROVISION_TOOLS = []
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.diagnosis_tools import (
            DIAGNOSIS_TOOLS,
        )
    except ImportError:
        logger.warning("DIAGNOSIS_TOOLS not available; AI loses diagnostic primitives")
        DIAGNOSIS_TOOLS = []
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools_cross_agent import (
            ANPA_CROSS_AGENT_TOOLS,
        )
    except ImportError:
        ANPA_CROSS_AGENT_TOOLS = []

    all_tools = DIAGNOSIS_TOOLS + PROVISION_TOOLS + ANPA_CROSS_AGENT_TOOLS

    # Extract hostname(s) from spec
    nodes_spec = spec.get("nodes", [])
    if nodes_spec:
        hostnames = [n.get("hostname", "") for n in nodes_spec if n.get("hostname")]
    else:
        hostnames = [spec.get("hostname", name)]

    # Enrich with BMC intelligence context if available
    profile, quirks = _load_cached_profile(name, namespace)
    strategy_name = _get_current_strategy(name, namespace)
    hw_context = ""
    if profile:
        hw_context = (
            f"\nHARDWARE CONTEXT: vendor={profile.vendor} model={profile.model} "
            f"fw={profile.firmware_version} bmc_type={profile.bmc_type}\n"
            f"Strategy used: {strategy_name}\n"
            f"Boot override writable: {profile.boot_override_writable}\n"
            f"VirtualMedia base: {profile.virtual_media_base}\n"
        )

    prompt = (
        f"Provisioning request '{name}' in namespace '{namespace}' has FAILED.\n"
        f"Phase at failure: {phase}\n"
        f"Error: {error}\n"
        f"Target server(s): {', '.join(hostnames)}\n"
        f"{hw_context}\n"
        f"NOTE: Tier 1 deterministic fallback was already attempted and did not resolve.\n"
        f"Diagnose the root cause and take corrective action if safe.\n"
        f"If you cannot fix it, explain why and recommend manual steps.\n"
        f"Follow the OUTPUT FORMAT in the system prompt."
    )

    logger.info(
        "Invoking AI failure handler for %s/%s (phase=%s)", namespace, name, phase
    )

    payload: dict = {
        "name": name,
        "namespace": namespace,
        "phase": phase,
        "error": error,
        "hostnames": hostnames,
    }

    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver import (
            get_model,
        )
        from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import (
            ModelTier,
        )

        agent = Agent(
            model=get_model(ModelTier.SMART),
            tools=all_tools,
            system_prompt=FAILURE_DIAGNOSIS_PROMPT,
        )
        result = agent(prompt)
        diagnosis = str(result)
        logger.info(
            "AI failure handler completed for %s/%s: %s",
            namespace,
            name,
            diagnosis[:200],
        )
        payload["diagnosis"] = diagnosis
        payload["source"] = "ai"
        _persist_diagnosis(namespace, name, payload)
        return diagnosis
    except Exception as exc:
        logger.error("AI failure handler crashed for %s/%s: %s", namespace, name, exc)
        fallback = (
            f"AI diagnosis failed: {exc}. Original error: {error}. "
            f"Manual investigation required (start with get_workflow_logs)."
        )
        payload["diagnosis"] = fallback
        payload["source"] = "fallback"
        payload["exception"] = str(exc)
        _persist_diagnosis(namespace, name, payload)
        return fallback
