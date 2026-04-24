# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Adaptive Steering Plugin — learns from execution history to prevent repeated failures.

Uses Strands SDK Steering pattern: intercepts tool calls just-in-time with
guidance derived from past execution logs. No SOP modification needed.

Flow:
  1. On agent creation, load failure patterns from execution history
  2. Before each tool call, check if it matches a known failure pattern
  3. If match → Guide (cancel tool + provide alternative approach)
  4. If no match → Proceed (let tool execute normally)

Patterns age out naturally: if the bastion exporter gets fixed, recent runs
won't have failures, so the constraint disappears.
"""

import json
import logging
import os
from pathlib import Path

from strands.vended_plugins.steering import SteeringHandler, LedgerProvider, Guide, Proceed
from strands.types.tools import ToolUse

logger = logging.getLogger(__name__)


def _load_failure_patterns(sop_stem: str, log_dir: str = "/app/logs", max_runs: int = 5) -> list[dict]:
    """Analyze recent execution logs and extract repeated failure patterns for a specific SOP.

    A pattern is: same tool + same target (extracted from input) + failed in 2+ recent runs.
    Returns list of {tool, target, count, guidance}.
    """
    logs_path = Path(log_dir)
    if not logs_path.exists():
        return []

    # Collect tool failures for this SOP across recent runs
    target_failures: dict[str, dict] = {}  # "tool:target" -> {count, errors}

    for f in sorted(logs_path.glob("execution_*.json"), reverse=True)[:max_runs]:
        try:
            data = json.loads(f.read_text())
            node = data.get("nodes", {}).get(sop_stem, {})
            for tc in node.get("tool_calls", []):
                if tc.get("error"):
                    # Extract target from tool input (host, namespace, pod, etc.)
                    target = _extract_target(tc.get("tool", ""), tc.get("input", ""))
                    if target:
                        key = f"{tc['tool']}:{target}"
                        entry = target_failures.setdefault(key, {"tool": tc["tool"], "target": target, "count": 0, "errors": set()})
                        entry["count"] += 1
                        entry["errors"].add(tc["error"][:100])
        except Exception:
            continue

    # Only return patterns that failed in 2+ runs (not one-off flakes)
    patterns = []
    for key, entry in target_failures.items():
        if entry["count"] >= 2:
            patterns.append({
                "tool": entry["tool"],
                "target": entry["target"],
                "count": entry["count"],
                "errors": list(entry["errors"])[:3],
                "guidance": _build_guidance(entry["tool"], entry["target"], entry["errors"]),
            })

    if patterns:
        logger.info(f"Loaded {len(patterns)} failure patterns for {sop_stem}: {[p['tool']+':'+p['target'] for p in patterns]}")
    return patterns


def _extract_target(tool: str, tool_input: str) -> str | None:
    """Extract the target identifier from a tool call input.

    For SSH: the host IP. For kubectl: the namespace or resource.
    Returns None if no meaningful target can be extracted.
    """
    inp = str(tool_input)

    # SSH targets: extract IP/hostname
    if tool in ("ssh_command", "ssh_expect") or ("ssh " in inp):
        import re
        # Match IP addresses
        m = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', inp)
        if m:
            return m.group(1)
        # Match hostnames after ssh/@ 
        m = re.search(r'@([\w.-]+)', inp)
        if m:
            return m.group(1)

    # run_command with ssh
    if tool == "run_command" and "ssh " in inp:
        import re
        m = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', inp)
        if m:
            return m.group(1)

    # SSM targets
    if "ssm" in inp.lower() and "instance-id" in inp:
        import re
        m = re.search(r'(i-[0-9a-f]+)', inp)
        if m:
            return m.group(1)

    return None


def _build_guidance(tool: str, target: str, errors: set) -> str:
    """Build actionable guidance for a known failure pattern."""
    error_summary = "; ".join(list(errors)[:2])

    if "ssh" in tool.lower() or "ssh " in str(errors).lower() or "connection refused" in str(errors).lower() or "permission denied" in str(errors).lower():
        return (
            f"SSH to {target} has failed in multiple previous runs ({error_summary}). "
            f"Do NOT attempt SSH to {target}. Instead, verify from Kubernetes: "
            f"check Endpoints, Services, and Prometheus targets using kubectl. "
            f"Report the SSH-dependent check as a known issue requiring manual intervention."
        )

    if "ssm" in str(errors).lower():
        return (
            f"SSM access to {target} has failed in previous runs. "
            f"Do NOT attempt SSM. Verify from Kubernetes instead."
        )

    return (
        f"Tool '{tool}' targeting '{target}' has failed in {len(errors)} previous runs "
        f"({error_summary}). Consider an alternative approach or skip this check."
    )


class AdaptiveSteeringHandler(SteeringHandler):
    """Steering handler that learns from execution history.

    Before each tool call, checks if it matches a known failure pattern
    from past runs. If so, cancels the tool and provides guidance.
    Also enforces tool budget and existing SOPSteeringHooks rules.
    """

    def __init__(self, sop_stem: str, fix_mode: bool = False, log_dir: str = "/app/logs"):
        super().__init__(context_providers=[LedgerProvider()])
        self.sop_stem = sop_stem
        self.fix_mode = fix_mode
        self.patterns = _load_failure_patterns(sop_stem, log_dir)
        self.tool_count = 0
        self.tool_budget = 95
        self._guided_targets: set[str] = set()  # Track what we've already guided on

    async def steer_before_tool(self, *, agent, tool_use: ToolUse, **kwargs) -> "ToolSteeringAction":
        self.tool_count += 1

        # Tool budget enforcement
        if self.tool_count >= self.tool_budget:
            return Guide(
                reason=f"Tool call budget exhausted ({self.tool_count}/{self.tool_budget}). "
                       "Summarize progress and stop. Do NOT call more tools."
            )

        tool_name = tool_use.get("name", "")
        tool_input = str(tool_use.get("input", {}))

        # Check against learned failure patterns
        target = _extract_target(tool_name, tool_input)
        if target:
            for pattern in self.patterns:
                if pattern["target"] == target and target not in self._guided_targets:
                    self._guided_targets.add(target)
                    logger.info(f"Steering {self.sop_stem}: blocking {tool_name} to {target} (failed {pattern['count']}x in history)")
                    return Guide(reason=pattern["guidance"])

        # Namespace guard
        if tool_name in ("kubectl", "kubectl_exec"):
            args = str(tool_use.get("input", {}).get("args", tool_use.get("input", {}).get("command", "")))
            ns = str(tool_use.get("input", {}).get("namespace", ""))
            if ns == "default" or "-n default" in args:
                target_ns = os.environ.get("UPF_NAMESPACE", "aws-app")
                return Guide(reason=f"Target namespace is '{target_ns}', not 'default'. Fix the namespace.")

        # Port-forward hang guard
        if tool_name in ("run_command", "kubectl"):
            cmd = str(tool_use.get("input", {}).get("command", tool_use.get("input", {}).get("args", "")))
            if "port-forward" in cmd and "&" not in cmd:
                return Guide(reason="port-forward without '&' will hang. Add '&' or use 'timeout 10 kubectl port-forward ...'.")

        # Dangerous command guard (REPORT mode)
        if not self.fix_mode:
            cmd = str(tool_use.get("input", {}).get("command", tool_use.get("input", {}).get("args", "")))
            for pattern in ["sudo reboot", "kubectl delete namespace", "--force --grace-period=0", "pkill -9"]:
                if pattern in cmd:
                    return Guide(reason=f"Blocked in REPORT mode: '{pattern}' is destructive.")

        # SSH heredoc guard
        if tool_name == "ssh_command":
            cmd = str(tool_use.get("input", {}).get("command", ""))
            if "<<" in cmd and len(cmd) > 500:
                return Guide(reason="Long heredocs fail over SSH. Use base64 encoding instead.")

        return Proceed(reason="No steering needed")

    async def steer_after_model(self, *, agent, message, stop_reason, **kwargs) -> "ModelSteeringAction":
        return Proceed(reason="Accepting model response")
