# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""SOP graph node classes + the per-SOP agent factory.

Extracted from sop_graph.py for cohesion. These are the executable pieces the
graph builder wires together:

* ``EvalNode`` -- deterministic (no-LLM) evaluator node that scores a run.
* ``CorrectorNode`` -- LLM node that patches an SOP markdown on eval failure.
* ``create_sop_agent`` -- factory building a scoped Strands Agent for one SOP.
* ``_classify_failure`` / ``FaultType`` -- fault attribution shared by EvalNode.

Model construction (``_create_model`` / ``_CORRECTOR_MODEL``) lives here too
since only these node classes use it -- keeping it here avoids a circular import
back into sop_graph.
"""

from __future__ import annotations

import logging
import os

# Ensure the evals/ directory is importable (sop_corrector, evaluators,
# adaptive_steering are top-level modules under the package's evals/ tree). This
# mirrors the bootstrap in sop_graph and is idempotent -- both resolve to the
# same dir, so the second insert is a no-op.
import sys as _sys
import time as _time
from enum import StrEnum
from pathlib import Path
from typing import Optional

from amzn_cse_telco_autonomous_network_agents_app.agent.graph_conditions import (
    NEEDS_CORRECTION_MARKER,
    SOP_PATCHED_MARKER,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.sop_executor import (
    MODELS,
    SYSTEM_PROMPT_FIX,
    SYSTEM_PROMPT_REPORT,
    collect_eval_session,
    get_sop_eval_meta,
    get_tools_for_sop,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.sop_metadata import (
    parse_sop_metadata,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.util.aws import aws_session
from strands import Agent
from strands.agent.agent_result import AgentResult
from strands.multiagent.base import MultiAgentBase, MultiAgentResult, NodeResult, Status
from strands.types.content import ContentBlock, Message

_evals_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "evals")
if _evals_dir not in _sys.path:
    _sys.path.insert(0, _evals_dir)

from sop_corrector import CORRECTOR_PROMPT

logger = logging.getLogger(__name__)

# Corrector always uses the best available model — no point retrying with a weaker one
_CORRECTOR_MODEL = "opus4.6"


class FaultType(StrEnum):
    """Attribution for an eval failure.

    ``SOP_FAULT`` means the SOP markdown itself is flawed (needs patching);
    ``AGENT_FAULT`` means the model executed poorly (re-run with a better model).
    StrEnum so a member compares equal to its legacy string value -- the eval
    output text and the tests that assert on it stay byte-identical.
    """

    AGENT_FAULT = "AGENT_FAULT"
    SOP_FAULT = "SOP_FAULT"


def _create_model(model_id: str, boto_session) -> "BedrockModel":
    """Build a BedrockModel with runtime legacy/unavailable down-shift.

    Thin delegate to core.model_resolver.build_probed_model, which owns the
    probe-and-cascade logic (and the fallback chain + per-(model_id, region)
    cache) so all model construction lives in one module.
    """
    from amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver import (
        build_probed_model,
    )

    return build_probed_model(model_id, boto_session)


# ── Custom Node: Deterministic Evaluator (no LLM) ──


class EvalNode(MultiAgentBase):
    """Run deterministic evaluators on captured traces. Zero LLM cost."""

    def __init__(self, eval_ctx: dict, sop_path: str, name: str = "eval"):
        super().__init__()
        self.eval_ctx = eval_ctx
        self.sop_path = sop_path
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def invoke_async(self, task, invocation_state=None, **kwargs):
        # Not used directly — stream_async drives execution
        return MultiAgentResult(status=Status.COMPLETED)

    async def stream_async(self, task, invocation_state=None, **kwargs):
        """Stream eval score lines as data events so the backend can parse them."""
        import asyncio

        from evaluators import (
            ExecutionTimeEvaluator,
            SOPCompletionEvaluator,
            SteeringEffectivenessEvaluator,
            ToolSuccessRateEvaluator,
            _extract_tool_spans,
        )
        from strands_evals import Case, Experiment

        start = _time.time()
        agent_output = str(task)
        lines = []
        eval_scores = []

        try:
            session = collect_eval_session(self.eval_ctx["telemetry"], self.eval_ctx["session_id"])
            meta = get_sop_eval_meta(self.sop_path)
            # Merge SOP complexity metrics for per-SOP tool budgets
            sop_meta = parse_sop_metadata(self.sop_path)
            meta["bash_blocks"] = sop_meta.get("bash_blocks", 0)
            meta["lines"] = sop_meta.get("lines", 0)
            # Derive execution time from telemetry span timestamps
            spans = []
            for trace in session.traces if session else []:
                spans.extend(trace.spans)
            if spans:
                starts = [s.span_info.start_time for s in spans if s.span_info.start_time]
                ends = [s.span_info.end_time for s in spans if s.span_info.end_time]
                if starts and ends:
                    meta["execution_time_s"] = (max(ends) - min(starts)).total_seconds()
            case = Case[str, str](name=Path(self.sop_path).stem, input=self.sop_path, metadata=meta)
            evaluators = [
                SteeringEffectivenessEvaluator(),
                SOPCompletionEvaluator(),
                ExecutionTimeEvaluator(),
                ToolSuccessRateEvaluator(),
            ]
            experiment = Experiment[str, str](cases=[case], evaluators=evaluators)

            loop = asyncio.get_event_loop()
            reports = await loop.run_in_executor(
                None, experiment.run_evaluations, lambda c: {"output": agent_output, "trajectory": session}
            )

            has_failures = False
            fault_type = None
            for report in reports:
                lines.append(report.evaluator_name)
                lines.append(f"  Score: {report.overall_score:.2f}")
                for i, reason in enumerate(report.reasons):
                    passed = report.test_passes[i]
                    lines.append(f"  {'PASS' if passed else 'FAIL'}: {reason}")
                    if not passed:
                        has_failures = True
                        fault_type = _classify_failure(report.evaluator_name, reason, fault_type)
                # Yield structured eval event (backend parses this directly)
                eval_scores.append(
                    {
                        "evaluator": report.evaluator_name,
                        "score": report.overall_score,
                        "passed": report.overall_score >= 0.5,
                        "reasons": [
                            {"passed": report.test_passes[i], "reason": report.reasons[i]}
                            for i in range(len(report.reasons))
                        ],
                    }
                )
            if has_failures:
                # Include tool error details so the corrector knows WHAT failed
                tool_errors = []
                for span in _extract_tool_spans(session):
                    if span.tool_result and span.tool_result.error:
                        err = f"{span.tool_call.name}: {span.tool_result.error[:150]}"
                        if err not in tool_errors:
                            tool_errors.append(err)
                if tool_errors:
                    lines.append("Tool errors encountered:")
                    for e in tool_errors[:5]:
                        lines.append(f"  FAIL: {e}")
                lines.append(f"{NEEDS_CORRECTION_MARKER}:{fault_type or FaultType.AGENT_FAULT}")
        except Exception as e:
            logger.exception(f"EvalNode {self._name} failed: {e}")
            lines.append(f"Eval error: {e}")

        # Stream text lines for log display
        for line in lines:
            yield {"data": line}

        # Stream structured eval scores (backend parses directly, no regex needed)
        for es in eval_scores:
            yield {"eval_score": es}

        elapsed = int((_time.time() - start) * 1000)
        result_text = "\n".join(lines)
        agent_result = AgentResult(
            stop_reason="end_turn",
            message=Message(role="assistant", content=[ContentBlock(text=result_text)]),
            state={},
            metrics={"latencyMs": elapsed},
        )
        yield {
            "result": MultiAgentResult(
                status=Status.COMPLETED,
                execution_time=elapsed,
                results={
                    self._name: NodeResult(
                        result=agent_result,
                        status=Status.COMPLETED,
                        execution_time=elapsed,
                    )
                },
            )
        }


def _classify_failure(evaluator_name: str, reason: str, current: str | None) -> FaultType:
    """Classify eval failure as AGENT_FAULT or SOP_FAULT.

    SOP_FAULT wins if any failure is SOP-related (the SOP needs patching).
    AGENT_FAULT = model was inefficient/crashed, re-run with better model.
    SOP_FAULT = SOP itself is flawed, needs markdown patch.
    """
    # SOP_FAULT always takes priority — if the SOP is broken, model upgrade won't help
    if current == FaultType.SOP_FAULT:
        return FaultType.SOP_FAULT

    if "Missing required tools" in reason:
        return FaultType.SOP_FAULT  # SOP doesn't reference the right tools
    if "Success pattern" in reason and "not found" in reason:
        return FaultType.SOP_FAULT  # SOP success criteria wrong

    # Everything else is agent execution quality
    return FaultType.AGENT_FAULT


class CorrectorNode(MultiAgentBase):
    """Patches the SOP markdown file based on eval failures, then streams what changed."""

    def __init__(self, sop_path: str, profile: str | None, region: str, name: str = "corrector"):
        super().__init__()
        self.sop_path = sop_path
        self.profile = profile
        self.region = region
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def invoke_async(self, task, invocation_state=None, **kwargs):
        return MultiAgentResult(status=Status.COMPLETED)

    def _save_snapshot(self, content: str, failures: list[dict]):
        """Save SOP content before correction for audit trail."""
        try:
            snap_dir = Path(os.environ.get("SOP_REPO", "/app")) / "logs" / "corrector_snapshots"
            snap_dir.mkdir(parents=True, exist_ok=True)
            import json

            ts = _time.strftime("%Y%m%d_%H%M%S")
            stem = Path(self.sop_path).stem
            snap_dir.joinpath(f"{stem}_{ts}.md").write_text(content)
            snap_dir.joinpath(f"{stem}_{ts}_failures.json").write_text(json.dumps(failures, indent=2, default=str))
        except Exception as e:
            logger.warning(f"Failed to save corrector snapshot: {e}")

    async def stream_async(self, task, invocation_state=None, **kwargs):
        """Read eval failures from upstream, patch the SOP, stream what changed."""
        import asyncio

        from sop_corrector import build_correction_prompt

        start = _time.time()
        # task may be a list of ContentBlocks or a string — extract text properly
        if isinstance(task, list):
            eval_output = "\n".join(b["text"] if isinstance(b, dict) else str(b) for b in task)
        else:
            eval_output = str(task)
        lines = []

        try:
            # Parse failure lines from eval output
            failures = []
            for line in eval_output.split("\n"):
                line = line.strip()
                if line.startswith("FAIL:"):
                    failures.append({"evaluator": "eval", "reason": line[5:].strip(), "score": 0.0})

            if not failures:
                lines.append("No actionable failures found — skipping SOP patch.")
            else:
                sop_content = Path(self.sop_path).read_text()

                # P3: Save snapshot before correction for audit trail
                self._save_snapshot(sop_content, failures)

                prompt = build_correction_prompt(sop_content, failures)

                session = aws_session(self.profile, self.region)
                model = _create_model(MODELS[_CORRECTOR_MODEL], session)
                agent = Agent(model=model, system_prompt=CORRECTOR_PROMPT, callback_handler=None)

                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: str(agent(prompt)))

                # Extract markdown from response
                if "# " in result:
                    result = result[result.index("# ") :]

                # Git-safe write: commit current state before overwriting
                import subprocess

                try:
                    subprocess.run(["git", "add", self.sop_path], capture_output=True, timeout=10)
                    subprocess.run(
                        ["git", "commit", "-m", f"pre-correct: {Path(self.sop_path).stem}"],
                        capture_output=True,
                        timeout=10,
                    )
                except Exception:
                    pass  # Not a git repo or nothing to commit — still safe via snapshot

                Path(self.sop_path).write_text(result)
                lines.append(f"{SOP_PATCHED_MARKER}: {Path(self.sop_path).name}")
                lines.append(f"Failures addressed: {len(failures)}")
                for f in failures:
                    lines.append(f"  Fixed: {f['reason'][:80]}")
                # Retry guidance for the re-run agent
                lines.append("RETRY GUIDANCE FOR NEXT AGENT:")
                for f in failures:
                    lines.append(f"  Previous failure: {f['reason'][:120]}")
                lines.append("  Strategy: Check before creating. Error c002 = already exists = PASS.")
        except Exception as e:
            logger.exception(f"CorrectorNode {self._name} failed: {e}")
            lines.append(f"Correction error: {e}")

        for line in lines:
            yield {"data": line}

        elapsed = int((_time.time() - start) * 1000)
        result_text = "\n".join(lines)
        agent_result = AgentResult(
            stop_reason="end_turn",
            message=Message(role="assistant", content=[ContentBlock(text=result_text)]),
            state={},
            metrics={"latencyMs": elapsed},
        )
        yield {
            "result": MultiAgentResult(
                status=Status.COMPLETED,
                execution_time=elapsed,
                results={
                    self._name: NodeResult(
                        result=agent_result,
                        status=Status.COMPLETED,
                        execution_time=elapsed,
                    )
                },
            )
        }


# ── Agent Factory ──


def create_sop_agent(
    sop_path: str,
    profile: Optional[str] = None,
    region: str = "us-east-1",
    model_name: str = "haiku",
    fix_mode: bool = False,
    no_steering: bool = False,
    eval_ctx: Optional[dict] = None,
) -> Agent:
    """Create a scoped agent for a single SOP."""
    model_id = MODELS.get(model_name, model_name)
    session = aws_session(profile, region)
    model = _create_model(model_id, session)

    system_prompt = SYSTEM_PROMPT_FIX if fix_mode else SYSTEM_PROMPT_REPORT
    system_prompt += f"\n\n## YOUR ASSIGNED SOP\nYou are responsible for executing ONLY this SOP: {sop_path}\nDo NOT execute any other SOPs. Read this SOP, execute its steps, and report results."
    system_prompt += """

## EFFICIENCY RULES
- Before CREATE/INSERT commands, CHECK if the resource already exists. If it exists and matches expected state, SKIP and report PASS.
- Error code c002 means "already exists" — treat as PASS, do not retry.
- When steps are independent, call multiple tools in parallel.
- Do NOT retry a failed command more than twice with the same arguments."""
    tools = get_tools_for_sop(sop_path)
    steering = (
        None
        if no_steering
        else (
            __import__("adaptive_steering", fromlist=["AdaptiveSteeringHandler"]).AdaptiveSteeringHandler(
                sop_stem=Path(sop_path).stem, fix_mode=fix_mode
            )
        )
    )

    trace_attrs = None
    if eval_ctx:
        trace_attrs = {
            "session.id": eval_ctx["session_id"],
            "gen_ai.conversation.id": eval_ctx["session_id"],
        }

    # SteeringHandler is a Plugin in strands>=1.30, HookProvider in older versions
    kwargs = {}
    if steering:
        try:
            from strands.plugins import Plugin

            if isinstance(steering, Plugin):
                kwargs["plugins"] = [steering]
            else:
                kwargs["hooks"] = [steering]
        except ImportError:
            kwargs["hooks"] = [steering]

    return Agent(
        name=Path(sop_path).stem,
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        trace_attributes=trace_attrs,
        **kwargs,
    )
