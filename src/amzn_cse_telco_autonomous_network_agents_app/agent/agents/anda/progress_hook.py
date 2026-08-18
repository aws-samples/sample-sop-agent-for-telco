# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""ANDA Deployment Progress Hook — publishes SOP execution progress.

Writes live tool-by-tool progress to the in-memory activity store
(consumed by WebUI via GET /api/agents/reasoning every 5s) and batches
CR status patches on phase transitions only (max 3-5 writes per NF).

Usage::

    from agents.anda.progress_hook import DeploymentProgressHook

    hook = DeploymentProgressHook(plan_name="deploy-core-v2", nf_name="amf")
    hook.register_hooks(agent.hooks)
    # ... agent executes ...
    hook.patch_cr_phase("Completed")
"""

import json
import logging
import time

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookRegistry

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd
from amzn_cse_telco_autonomous_network_agents_app.agent.core.state import push_activity

log = logging.getLogger(__name__)

# CR group/resource for kubectl patch commands
_CR_GROUP = "deployment.anda.aws.io"
_CR_PLURAL = "deploymentplans"


class DeploymentProgressHook:
    """Publishes SOP execution progress to shared state for WebUI consumption.

    Two output channels:
    - **In-memory** (push_activity): Every tool call, real-time, no K8s API cost.
      WebUI reads via GET /api/agents/reasoning (polls every 5s).
    - **CR status** (kubectl patch): Phase transitions only — start, complete, fail.
      Max 3-5 patches per NF to avoid etcd write amplification.
    """

    # Minimum seconds between CR status patches (throttle)
    CR_PATCH_MIN_INTERVAL = 10

    def __init__(
        self,
        plan_name: str,
        nf_name: str,
        namespace: str = "anda-system",
    ):
        self.plan_name = plan_name
        self.nf_name = nf_name
        self.namespace = namespace
        self.step_count = 0
        self.started_at = time.time()
        self._last_cr_patch_time = 0.0

    def register_hooks(self, registry: HookRegistry) -> None:
        """Register before/after tool call hooks on the agent's hook registry."""
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call)
        registry.add_callback(AfterToolCallEvent, self._after_tool_call)

    def _before_tool_call(self, event: BeforeToolCallEvent, **kwargs):
        """Log tool invocation to activity feed (pre-execution)."""
        tool_name = event.tool_use.get("name", "unknown")
        tool_input = str(event.tool_use.get("input", {}))[:200]

        push_activity(
            stage=f"deploy-{self.nf_name}",
            message=f"Executing: {tool_name}",
            detail=tool_input,
            status="running",
        )

    def _after_tool_call(self, event: AfterToolCallEvent, **kwargs):
        """Log tool result to activity feed (post-execution)."""
        self.step_count += 1
        tool_name = event.tool_use.get("name", "unknown")

        # Extract result text from event
        result_text = self._extract_result_text(event)

        # Determine status from result content
        if any(marker in result_text for marker in ("✅", "PASS", "success")):
            status = "success"
            icon = "✅"
        elif any(marker in result_text for marker in ("❌", "FAIL", "error", "Error")):
            status = "failed"
            icon = "❌"
        else:
            status = "info"
            icon = "⏳"

        push_activity(
            stage=f"deploy-{self.nf_name}",
            message=f"Step {self.step_count}: {tool_name} → {icon}",
            detail=result_text[:200],
            status=status,
        )

    def patch_cr_phase(self, phase: str, message: str = "") -> None:
        """Patch the DeploymentPlan CR status with SOP execution state.

        Call this only on phase transitions (start, per-NF complete, fail).
        Throttled to minimum CR_PATCH_MIN_INTERVAL seconds between patches.

        Args:
            phase:   Status string (InProgress, Completed, Failed, TimedOut, etc.)
            message: Optional human-readable detail.
        """
        _TERMINAL_PHASES = frozenset({"Completed", "Failed", "TimedOut", "PartiallyCompleted"})
        now = time.time()
        if (
            phase not in _TERMINAL_PHASES
            and now - self._last_cr_patch_time < self.CR_PATCH_MIN_INTERVAL
        ):
            log.debug("CR patch throttled (%.1fs since last)", now - self._last_cr_patch_time)
            return
        self._last_cr_patch_time = now

        elapsed = int(now - self.started_at)
        sop_status = {
            "status": phase,
            "stepsExecuted": self.step_count,
            "elapsed": f"{elapsed}s",
        }
        if message:
            sop_status["message"] = message[:200]

        patch = json.dumps({
            "status": {
                "sopExecution": {
                    self.nf_name: sop_status,
                }
            }
        })

        cmd = (
            f"kubectl patch {_CR_PLURAL}.{_CR_GROUP} {self.plan_name} "
            f"-n {self.namespace} "
            f"--subresource=status "
            f"--type=merge "
            f"-p '{patch}'"
        )
        result = run_cmd(cmd, timeout=10)
        if not result.success:
            log.warning(
                "Failed to patch CR status for %s/%s: %s",
                self.nf_name, self.plan_name, result.output[:200],
            )
        else:
            log.debug(
                "Patched CR %s sopExecution.%s → %s",
                self.plan_name, self.nf_name, phase,
            )

    @staticmethod
    def _extract_result_text(event: AfterToolCallEvent) -> str:
        """Extract text content from a tool call result event."""
        if not event.result:
            return ""
        content = event.result.get("content", [])
        parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
        return "\n".join(parts)
