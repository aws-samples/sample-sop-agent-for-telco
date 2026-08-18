# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""ANDA SOP Bridge — AI-first deployment execution.

The bridge sits between the orchestrator (which watches DeploymentPlan CRs) and
the AI agent (which executes deployments autonomously). Rather than rigid tier
classification or SOP registry dispatch, the AI agent receives full context
about the cluster state and decides the right action itself.

Architecture:
    DeploymentPlan CR → Phase 0 (config gen) → AI Agent (full context + tools)

The agent has access to:
- All SOPs on disk (reads them as reference, adapts to reality)
- Helm tools (install, upgrade, rollback, status)
- kubectl (full cluster introspection)
- Generated values from config gen
- NF catalog (chart references)

Usage::

    from agents.anda.sop_bridge import SOPBridge

    bridge = SOPBridge()
    result = bridge.execute(
        nf_name="amf",
        plan=plan_cr_dict,
        namespace="open5gs",
        cluster="site-002-workload",
    )
"""

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


class BedrockUnavailableError(Exception):
    """Raised when Bedrock is unreachable or credentials are invalid."""


from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import (
    ARGOCD_TOOLS,
    BASE_TOOLS,
    run_cmd,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# SOP repository root (relative to app install)
_SOP_ROOT = os.getenv(
    "SOP_REPO", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

# Generated config output directory (shared with config_generator.py)
GENERATED_CONFIG_DIR = os.getenv("GENERATED_CONFIG_DIR", "/tmp/generated-configs")  # nosec B108

# NF Catalog path
_CATALOG_PATH = os.getenv("ANDA_CATALOG_PATH", "/etc/anda/catalog/catalog.yaml")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class SOPResult:
    """Result of a bridge execution."""

    success: bool
    phase: str = "Deployed"         # Deployed, DeployFailed, Failed, etc.
    output: str = ""
    tier_used: int = 0              # Legacy compat (orchestrator logs this)
    steps_executed: int = 0
    fallback_used: bool = False
    sop_path: Optional[str] = None


# ---------------------------------------------------------------------------
# SOPBridge — AI-first
# ---------------------------------------------------------------------------


class SOPBridge:
    """AI-first adapter between the orchestrator and the deployment agent.

    Instead of classifying complexity into tiers and dispatching to rigid
    code paths, this bridge gives the AI agent full context (cluster state,
    intent, available SOPs, generated config, catalog) and lets it decide
    the right course of action.
    """

    def get_tools(self) -> list:
        """Build the full tool set for the deployment agent.

        Includes all base + deploy + drain + argocd tools. The agent uses
        whichever subset is relevant for the situation.
        """
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.tools import DEPLOY_TOOLS
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.drain import DRAIN_TOOLS

        tools = list(BASE_TOOLS) + list(DEPLOY_TOOLS) + list(DRAIN_TOOLS) + list(ARGOCD_TOOLS)

        # Deduplicate by function name
        seen = set()
        deduped = []
        for tool in tools:
            name = getattr(tool, "__name__", str(tool))
            if name not in seen:
                seen.add(name)
                deduped.append(tool)

        return deduped

    def execute(
        self,
        nf_name: str,
        plan: Dict[str, Any],
        strategy: Optional[Any] = None,
        namespace: str = "default",
        cluster: str = "unknown",
    ) -> SOPResult:
        """Execute deployment for a single NF via AI agent.

        The agent receives full context and autonomously:
        1. Assesses current cluster state
        2. Decides the right action (install, upgrade, remediate)
        3. Executes using available tools
        4. Verifies the result

        Args:
            nf_name:   NF to deploy (e.g., "amf")
            plan:      Raw DeploymentPlan CR dict
            strategy:  Upgrade strategy hint (optional, passed as context)
            namespace: Target K8s namespace
            cluster:   Target cluster name

        Returns:
            SOPResult with success/failure info
        """
        spec = plan.get("spec", {})
        intent = spec.get("intent", "deploy")
        reason = spec.get("reason", "")
        execution_mode = spec.get("executionMode", "live")
        plan_name = plan.get("metadata", {}).get("name", "unknown")

        # Resolve vendor from NF spec in the plan
        nf_spec = self._find_nf_in_plan(spec, nf_name)
        vendor = nf_spec.get("vendor", "unknown") if nf_spec else "unknown"

        # ── Phase 0: Config generation ──
        if intent in ("deploy", "upgrade", "remediation"):
            self._run_config_gen_if_needed(nf_name, vendor, namespace, cluster, plan_name)

        # ── Phase 1: AI Agent execution ──
        log.info(
            "SOP Bridge: nf=%s intent=%s → AI agent (full context)",
            nf_name, intent,
        )

        # Replay/dry-run modes (stubs for Phase 4)
        if execution_mode == "replay":
            return self._execute_replay(nf_name, plan_name)
        if execution_mode == "dry-run":
            return self._execute_dry_run(nf_name, plan_name)

        # Live AI execution
        return self._execute_ai(
            nf_name=nf_name,
            namespace=namespace,
            cluster=cluster,
            plan_name=plan_name,
            intent=intent,
            reason=reason,
            vendor=vendor,
            strategy=strategy,
        )

    # -----------------------------------------------------------------------
    # Phase 0: Config Generation
    # -----------------------------------------------------------------------

    def _run_config_gen_if_needed(
        self, nf_name: str, vendor: str, namespace: str, cluster: str, plan_name: str
    ) -> None:
        """Run config generation if no values file exists yet."""
        from .config_generator import load_site_descriptor, run_config_generation

        values_path = os.path.join(GENERATED_CONFIG_DIR, f"{nf_name}-values.yaml")
        if os.path.isfile(values_path):
            log.info("Phase 0: config already exists at %s, skipping generation", values_path)
            return

        site_desc = load_site_descriptor(cluster)
        if site_desc:
            log.info("Phase 0: generating config for %s from site descriptor", nf_name)
            run_config_generation(
                nf_name=nf_name,
                vendor=vendor,
                namespace=namespace,
                site_descriptor=site_desc,
                plan_name=plan_name,
            )
        else:
            log.info("Phase 0: no site descriptor found for cluster '%s', skipping config gen", cluster)

    # -----------------------------------------------------------------------
    # Phase 1: AI Agent Execution
    # -----------------------------------------------------------------------

    def _execute_ai(
        self,
        nf_name: str,
        namespace: str,
        cluster: str,
        plan_name: str,
        intent: str,
        reason: str,
        vendor: str,
        strategy: Optional[Any],
    ) -> SOPResult:
        """Execute deployment via AI agent with full context."""
        from amzn_cse_telco_autonomous_network_agents_app.agent.sop_executor import create_agent
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.progress_hook import (
            DeploymentProgressHook,
        )

        tools = self.get_tools()
        prompt = self._build_context_prompt(
            nf_name=nf_name,
            namespace=namespace,
            cluster=cluster,
            intent=intent,
            reason=reason,
            vendor=vendor,
            strategy=strategy,
        )

        # Create progress hook for live status updates
        progress_hook = DeploymentProgressHook(
            plan_name=plan_name, nf_name=nf_name,
        )

        # Find the best SOP for context (agent reads it, but doesn't blindly follow)
        sop_path = self._find_relevant_sop(intent, nf_name)

        try:
            agent, _ = create_agent(
                sop_path=sop_path or os.path.join(_SOP_ROOT, "sops/TEMPLATE.md"),
                fix_mode=True,
                no_steering=False,
            )
            # Inject progress hook
            progress_hook.register_hooks(agent.hooks)

            # Give the agent ALL tools
            agent.tools = tools

            log.info(
                "AI agent executing: nf=%s intent=%s tools=%d sop=%s",
                nf_name, intent, len(tools), sop_path or "none",
            )
            progress_hook.patch_cr_phase("InProgress")

            result = agent(prompt)

            output = str(result) if result else ""
            success = "❌" not in output and "FAILURE" not in output.upper()

            progress_hook.patch_cr_phase("Completed" if success else "Failed")

            return SOPResult(
                success=success,
                phase="Deployed" if success else "Failed",
                output=output[:1000],
                steps_executed=progress_hook.step_count,
                sop_path=sop_path,
            )

        except (SystemExit, BedrockUnavailableError) as exc:
            if isinstance(exc, SystemExit) and exc.code not in (1,):
                raise
            # Bedrock unavailable — cannot proceed without AI
            log.error("Bedrock unavailable for %s — cannot execute deployment", nf_name)
            progress_hook.patch_cr_phase("Failed", "Bedrock unavailable")
            return SOPResult(
                success=False,
                phase="Failed",
                output="Bedrock AI service unavailable. Cannot execute autonomous deployment.",
                fallback_used=False,
            )

        except Exception as exc:
            log.error("AI agent execution error for %s: %s", nf_name, exc, exc_info=True)
            progress_hook.patch_cr_phase("Failed", str(exc)[:200])
            return SOPResult(
                success=False,
                phase="Failed",
                output=str(exc)[:500],
                steps_executed=progress_hook.step_count,
                sop_path=sop_path,
            )

    # -----------------------------------------------------------------------
    # Context-Aware Prompt
    # -----------------------------------------------------------------------

    def _build_context_prompt(
        self,
        nf_name: str,
        namespace: str,
        cluster: str,
        intent: str,
        reason: str,
        vendor: str,
        strategy: Optional[Any],
    ) -> str:
        """Build a context-rich prompt that lets the AI agent decide the approach."""
        parts: List[str] = []

        parts.append(f"# Deployment Task: {intent} {nf_name}")
        parts.append("")
        parts.append("## Context")
        parts.append(f"- **NF:** {nf_name}")
        parts.append(f"- **Namespace:** {namespace}")
        parts.append(f"- **Cluster:** {cluster}")
        parts.append(f"- **Intent:** {intent}")
        parts.append(f"- **Vendor:** {vendor}")
        if reason:
            parts.append(f"- **Reason:** {reason}")
        if strategy:
            parts.append(f"- **Upgrade strategy hint:** {getattr(strategy, 'name', str(strategy))}")

        # Generated values
        values_path = os.path.join(GENERATED_CONFIG_DIR, f"{nf_name}-values.yaml")
        if os.path.isfile(values_path):
            parts.append(f"- **Generated values:** `{values_path}` (use with `helm upgrade -f`)")

        # NF Catalog
        if os.path.isfile(_CATALOG_PATH):
            parts.append(f"- **NF Catalog:** `{_CATALOG_PATH}` (contains chart references)")

        # Available SOPs
        sops_dir = os.path.join(_SOP_ROOT, "sops")
        if os.path.isdir(sops_dir):
            parts.append(f"- **SOPs directory:** `{sops_dir}` (read with `read_sop` tool for guidance)")

        parts.append("")
        parts.append("## Instructions")
        parts.append("")
        parts.append("You are an autonomous deployment agent. Execute this task by following these steps:")
        parts.append("")
        parts.append("### Step 1: ASSESS current state")
        parts.append(f"- Run `helm list -n {namespace}` to check if '{nf_name}' or a parent chart is already deployed")
        parts.append(f"- Run `kubectl get pods -n {namespace}` to check pod health")
        parts.append(f"- If the NF catalog exists, read it to find the chart reference for '{nf_name}'")
        parts.append("")
        parts.append("### Step 2: DECIDE the right action")
        parts.append("Based on what you observe:")
        parts.append(f"- If '{nf_name}' (or its parent chart) is **already deployed and healthy** → "
                     f"`helm upgrade` with the generated values file")
        parts.append(f"- If '{nf_name}' is **not deployed** → `helm install` using chart from catalog")
        parts.append(f"- If '{nf_name}' is **unhealthy** (CrashLoop, Error) → diagnose from logs, fix root cause")
        parts.append(f"- If helm repo is needed → add it first (`helm repo add`)")
        parts.append(f"- If you need guidance → read the relevant SOP from {sops_dir}")
        parts.append("")
        parts.append("### Step 3: EXECUTE")
        parts.append("- Use the appropriate helm/kubectl tools")
        parts.append(f"- Always include `--namespace {namespace}`")
        if os.path.isfile(values_path):
            parts.append(f"- Include `-f {values_path}` to apply generated site-specific config")
        parts.append("- Use `--wait --timeout 5m` for helm operations")
        parts.append("")
        parts.append("### Step 4: VERIFY")
        parts.append(f"- Run `kubectl get pods -n {namespace}` — all pods should be Running/Ready")
        parts.append(f"- Check logs of '{nf_name}' pod for errors")
        parts.append("- Report final status: ✅ SUCCESS or ❌ FAILURE with explanation")
        parts.append("")
        parts.append("## Important Rules")
        parts.append("- Do NOT blindly follow a SOP if the cluster state doesn't match its assumptions")
        parts.append("- Adapt to what you actually observe in the cluster")
        parts.append("- If a helm install fails because release already exists, use helm upgrade instead")
        parts.append("- If a helm repo is not added, add it before installing")
        parts.append("- If you encounter an error, diagnose and fix it — don't just report failure")

        return "\n".join(parts)

    # -----------------------------------------------------------------------
    # SOP Discovery (non-rigid — agent uses as reference, not dispatch)
    # -----------------------------------------------------------------------

    def _find_relevant_sop(self, intent: str, nf_name: str) -> Optional[str]:
        """Find the most relevant SOP file for context.

        This is a best-effort lookup — the agent reads the SOP for guidance
        but adapts to reality. Unlike the old SOP_REGISTRY, this doesn't
        fail if no exact match exists.
        """
        sops_dir = os.path.join(_SOP_ROOT, "sops")

        # Intent-based directory mapping
        intent_dirs = {
            "deploy": "day1-deploy",
            "upgrade": "day1-deploy",
            "remediation": "day2-remediate",
        }
        sub_dir = intent_dirs.get(intent, "day1-deploy")
        search_dir = os.path.join(sops_dir, sub_dir)

        if not os.path.isdir(search_dir):
            return None

        # Look for SOPs mentioning the NF name
        nf_lower = nf_name.lower()
        best_match = None

        for root, _, files in os.walk(search_dir):
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(root, fname)
                # Prefer file names that contain the NF name
                if nf_lower in fname.lower():
                    return fpath
                # Fallback: generic deploy/remediate SOP (check path too for dir matches)
                if "core" in fpath.lower() or "5g" in fpath.lower():
                    best_match = fpath

        return best_match

    # -----------------------------------------------------------------------
    # Replay / Dry-Run (Phase 4 stubs)
    # -----------------------------------------------------------------------

    def _execute_replay(self, nf_name: str, plan_name: str) -> SOPResult:
        """Replay a pre-recorded execution trace (deterministic, no AI)."""
        log.info("Replay mode: %s (not yet implemented)", nf_name)
        return SOPResult(
            success=True,
            phase="Deployed",
            output="[replay mode — not yet implemented]",
        )

    def _execute_dry_run(self, nf_name: str, plan_name: str) -> SOPResult:
        """Dry-run: AI executes but all tool calls are mocked."""
        log.info("Dry-run mode: %s (not yet implemented)", nf_name)
        return SOPResult(
            success=True,
            phase="Deployed",
            output="[dry-run mode — not yet implemented]",
        )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _find_nf_in_plan(spec: Dict[str, Any], nf_name: str) -> Optional[Dict[str, Any]]:
        """Find the NF spec dict within the plan's networkFunctions list."""
        for nf in spec.get("networkFunctions", []) or spec.get("nfs", []):
            if nf.get("name", "").lower() == nf_name.lower():
                return nf
        return None
