# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Graph-based SOP orchestrator using Strands multi-agent Graph pattern.

Fully SOP-agnostic — all dependencies, tools, and model selection are
derived from SOP content at runtime. No hardcoded SOP names or stages.
"""

import os
import re
import uuid
import logging
import time as _time
from pathlib import Path
from typing import Optional

import boto3
from strands import Agent
from strands.models import BedrockModel
from strands.multiagent import GraphBuilder
from strands.multiagent.base import MultiAgentBase, NodeResult, Status, MultiAgentResult
from strands.multiagent.graph import GraphState
from strands.agent.agent_result import AgentResult
from strands.types.content import ContentBlock, Message

from sop_executor import (
    MODELS, SOPSteeringHooks,
    SYSTEM_PROMPT_REPORT, SYSTEM_PROMPT_FIX,
    get_tools_for_sop, get_sop_eval_meta,
    setup_eval_telemetry, collect_eval_session,
)

# Ensure evals directory is importable
import sys as _sys
_evals_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "evals")
if _evals_dir not in _sys.path:
    _sys.path.insert(0, _evals_dir)

from sop_corrector import CORRECTOR_PROMPT

logger = logging.getLogger(__name__)

# Model fallback chain: if a model is deprecated/legacy, try the next one
_MODEL_FALLBACKS = {
    "us.anthropic.claude-3-5-haiku-20241022-v1:0": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "us.anthropic.claude-3-5-sonnet-20241022-v2:0": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "us.anthropic.claude-sonnet-4-20250514-v1:0": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": "us.anthropic.claude-opus-4-20250514-v1:0",
    "us.anthropic.claude-opus-4-20250514-v1:0": "us.anthropic.claude-opus-4-6-v1",
}

# Corrector always uses the best available model — no point retrying with a weaker one
_CORRECTOR_MODEL = "opus4.6"


_model_cache: dict[tuple[str, str], str] = {}  # (model_id, region) -> resolved model_id


def _create_model(model_id: str, boto_session) -> BedrockModel:
    """Create a BedrockModel, probing for legacy/deprecated models and falling back.

    Results are cached per (model_id, region) so each model is probed at most once.
    """
    region = boto_session.region_name
    cache_key = (model_id, region)
    if cache_key in _model_cache:
        resolved = _model_cache[cache_key]
        return BedrockModel(model_id=resolved, boto_session=boto_session)

    tried = set()
    current = model_id
    while current and current not in tried:
        tried.add(current)
        try:
            client = boto_session.client("bedrock-runtime", region_name=region)
            client.converse(
                modelId=current,
                messages=[{"role": "user", "content": [{"text": "hi"}]}],
                inferenceConfig={"maxTokens": 1},
            )
            logger.info(f"Model OK: {current}")
            _model_cache[cache_key] = current
            return BedrockModel(model_id=current, boto_session=boto_session)
        except Exception as e:
            if "Legacy" in str(e) or "ResourceNotFoundException" in type(e).__name__:
                fallback = _MODEL_FALLBACKS.get(current)
                logger.warning(f"Model {current} unavailable ({e.__class__.__name__}), falling back to {fallback}")
                current = fallback
            else:
                raise
    raise RuntimeError(f"All model fallbacks exhausted starting from {model_id}: tried {tried}")


# ── SOP Content Analysis (all derived, nothing hardcoded) ──

def parse_sop_metadata(sop_path: str) -> dict:
    """Extract metadata from SOP content: stage, dependencies, complexity.

    Returns:
        {
            "stem": "05-validation",
            "stage": 5,              # from "Stage: 5 of 8"
            "dep_stages": [4],       # from "Stages 1-4 complete"
            "dep_files": ["02-app-config"],  # from SOP filename refs
            "bash_blocks": 18,
            "lines": 176,
        }
    """
    try:
        content = Path(sop_path).read_text()
    except (FileNotFoundError, OSError):
        return {"stem": Path(sop_path).stem, "stage": None, "dep_stages": [],
                "dep_files": [], "bash_blocks": 0, "lines": 0}

    stem = Path(sop_path).stem
    lines = content.split("\n")
    bash_blocks = len(re.findall(r"```bash", content))

    # Parse stage number: "Stage: 5 of 8" or "Stage: 1 (Infrastructure)"
    stage = None
    m = re.search(r"\*\*Stage:\*\*\s*(\d+)", content)
    if m:
        stage = int(m.group(1))

    # Parse prerequisite dependencies
    dep_stages = set()
    dep_files = set()

    # Find prerequisites section
    prereq_match = re.search(r"## Prerequisites?\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
    prereq_text = prereq_match.group(1) if prereq_match else ""

    # "Stages 1-4 complete" → depends on stages 1,2,3,4
    for m in re.finditer(r"[Ss]tages?\s+(\d+)[-–](\d+)\s+complete", prereq_text):
        for s in range(int(m.group(1)), int(m.group(2)) + 1):
            dep_stages.add(s)

    # "Stage 3 complete" → depends on stage 3
    for m in re.finditer(r"[Ss]tage\s+(\d+)\s+complete", prereq_text):
        dep_stages.add(int(m.group(1)))

    # SOP filename references in prerequisites: "02-app-config.md" or "`05-validation.md`"
    for m in re.finditer(r"`?(\d{2}-[\w-]+)\.md`?", prereq_text):
        dep_files.add(m.group(1))

    return {
        "stem": stem,
        "stage": stage,
        "dep_stages": sorted(dep_stages),
        "dep_files": sorted(dep_files),
        "bash_blocks": bash_blocks,
        "lines": len(lines),
        "sleep_seconds": sum(int(m.group(1)) for m in re.finditer(r"sleep\s+(\d+)", content)),
    }


def resolve_dependencies(sop_metas: list[dict]) -> list[tuple[str, str]]:
    """Resolve SOP dependencies into (from_stem, to_stem) edges.

    Uses three strategies (in priority order):
    1. Explicit stage references: "Stage 3 complete" or "Stages 1-4 complete"
    2. File references: "02-app-config.md" in prerequisites
    3. Implicit stage chain: stage N depends on stage N-1 (if no explicit deps found)
    """
    # Build stage→stem lookup
    stage_to_stem = {}
    for meta in sop_metas:
        if meta["stage"] is not None:
            stage_to_stem[meta["stage"]] = meta["stem"]

    stem_set = {m["stem"] for m in sop_metas}
    edges = []
    has_explicit_deps = set()

    for meta in sop_metas:
        # Stage-based deps
        for dep_stage in meta["dep_stages"]:
            dep_stem = stage_to_stem.get(dep_stage)
            if dep_stem and dep_stem in stem_set and dep_stem != meta["stem"]:
                edges.append((dep_stem, meta["stem"]))
                has_explicit_deps.add(meta["stem"])

        # File-based deps
        for dep_file in meta["dep_files"]:
            if dep_file in stem_set and dep_file != meta["stem"]:
                edges.append((dep_file, meta["stem"]))
                has_explicit_deps.add(meta["stem"])

    # Implicit chain: stage N depends on stage N-1 (when no explicit deps found)
    for meta in sop_metas:
        if meta["stem"] in has_explicit_deps:
            continue
        if meta["stage"] is not None and meta["stage"] > 1:
            prev_stem = stage_to_stem.get(meta["stage"] - 1)
            if prev_stem and prev_stem in stem_set:
                edges.append((prev_stem, meta["stem"]))

    # Deduplicate
    return list(set(edges))


def select_model(meta: dict, default: str = "haiku") -> str:
    """Select model based on SOP complexity. Derived from content metrics."""
    if meta["bash_blocks"] >= 20 or meta["lines"] >= 300:
        return "opus4.6"
    if meta["bash_blocks"] >= 10 or meta["lines"] >= 150:
        return "sonnet"
    return default


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
        from evaluators import (SteeringEffectivenessEvaluator, SOPCompletionEvaluator,
                                _extract_tool_spans,
                                 ExecutionTimeEvaluator, ToolSuccessRateEvaluator)
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
            for trace in (session.traces if session else []):
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
                eval_scores.append({
                    "evaluator": report.evaluator_name,
                    "score": report.overall_score,
                    "passed": report.overall_score >= 0.5,
                    "reasons": [{"passed": report.test_passes[i], "reason": report.reasons[i]}
                                for i in range(len(report.reasons))],
                })
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
                lines.append(f"NEEDS_CORRECTION:{fault_type or 'AGENT_FAULT'}")
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
        yield {"result": MultiAgentResult(
            status=Status.COMPLETED, execution_time=elapsed,
            results={self._name: NodeResult(
                result=agent_result, status=Status.COMPLETED, execution_time=elapsed,
            )},
        )}


def _classify_failure(evaluator_name: str, reason: str, current: str | None) -> str:
    """Classify eval failure as AGENT_FAULT or SOP_FAULT.

    SOP_FAULT wins if any failure is SOP-related (the SOP needs patching).
    AGENT_FAULT = model was inefficient/crashed, re-run with better model.
    SOP_FAULT = SOP itself is flawed, needs markdown patch.
    """
    # SOP_FAULT always takes priority — if the SOP is broken, model upgrade won't help
    if current == "SOP_FAULT":
        return "SOP_FAULT"

    if "Missing required tools" in reason:
        return "SOP_FAULT"  # SOP doesn't reference the right tools
    if "Success pattern" in reason and "not found" in reason:
        return "SOP_FAULT"  # SOP success criteria wrong

    # Everything else is agent execution quality
    return "AGENT_FAULT"


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
            snap_dir.joinpath(f"{stem}_{ts}_failures.json").write_text(
                json.dumps(failures, indent=2, default=str)
            )
        except Exception as e:
            logger.warning(f"Failed to save corrector snapshot: {e}")

    async def stream_async(self, task, invocation_state=None, **kwargs):
        """Read eval failures from upstream, patch the SOP, stream what changed."""
        import asyncio
        from sop_corrector import build_correction_prompt, extract_failures

        start = _time.time()
        # task may be a list of ContentBlocks or a string — extract text properly
        if isinstance(task, list):
            eval_output = "\n".join(
                b["text"] if isinstance(b, dict) else str(b) for b in task
            )
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

                session = boto3.Session(profile_name=self.profile if self.profile else None, region_name=self.region)
                model = _create_model(MODELS[_CORRECTOR_MODEL], session)
                agent = Agent(model=model, system_prompt=CORRECTOR_PROMPT, callback_handler=None)

                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: str(agent(prompt)))

                # Extract markdown from response
                if "# " in result:
                    result = result[result.index("# "):]

                # Git-safe write: commit current state before overwriting
                import subprocess
                try:
                    subprocess.run(["git", "add", self.sop_path], capture_output=True, timeout=10)
                    subprocess.run(["git", "commit", "-m", f"pre-correct: {Path(self.sop_path).stem}"],
                                   capture_output=True, timeout=10)
                except Exception:
                    pass  # Not a git repo or nothing to commit — still safe via snapshot

                Path(self.sop_path).write_text(result)
                lines.append(f"SOP patched: {Path(self.sop_path).name}")
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
        yield {"result": MultiAgentResult(
            status=Status.COMPLETED, execution_time=elapsed,
            results={self._name: NodeResult(
                result=agent_result, status=Status.COMPLETED, execution_time=elapsed,
            )},
        )}


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
    session = boto3.Session(profile_name=profile if profile else None, region_name=region)
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
    steering = None if no_steering else (
        __import__('adaptive_steering', fromlist=['AdaptiveSteeringHandler'])
        .AdaptiveSteeringHandler(sop_stem=Path(sop_path).stem, fix_mode=fix_mode)
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


# ── Graph Builders ──

def _all_upstreams_passed(terminal_ids: list[str], target: str = ""):
    """AND-join condition: only traverse when ALL upstream terminals have completed.

    The Strands Graph uses OR-join (any edge satisfied → node ready).
    We need AND-join for DAG dependencies. This condition is placed on every
    incoming edge, so whenever any upstream completes, the condition is checked.
    It only returns True when ALL upstreams are done.
    """
    def check(state: GraphState) -> bool:
        satisfied = [tid for tid in terminal_ids
                     if (r := state.results.get(tid)) is not None and r.status == Status.COMPLETED]
        result = len(satisfied) == len(terminal_ids)
        if satisfied:  # Only log when at least one upstream done (avoid noise)
            logger.info(f"AND-join {target}: {len(satisfied)}/{len(terminal_ids)} satisfied={satisfied} → {'PASS' if result else 'WAIT'}")
        return result
    return check


def _corrector_made_changes(corrector_id: str):
    """Condition: only re-run SOP if corrector actually patched the markdown.

    When corrector finds no actionable failures (AGENT_FAULT with nothing to
    fix), it outputs "skipping SOP patch" — no point re-running the same SOP.
    """
    def check(state: GraphState) -> bool:
        r = state.results.get(corrector_id)
        if not r or r.status != Status.COMPLETED:
            return False
        results = r.get_agent_results()
        return any("SOP patched" in str(ar.message["content"]) for ar in results if ar.message)
    return check


def _needs_correction(eval_id: str, max_retries: int = 2):
    """Condition: traverse if eval output contains NEEDS_CORRECTION, up to max_retries times."""
    attempts = {"count": 0}
    def check(state: GraphState) -> bool:
        r = state.results.get(eval_id)
        if not r or r.status != Status.COMPLETED:
            return False
        results = r.get_agent_results()
        needs = any("NEEDS_CORRECTION" in str(ar.message["content"]) for ar in results if ar.message)
        if needs:
            attempts["count"] += 1
            if attempts["count"] > max_retries:
                logger.warning(f"{eval_id}: max correction retries ({max_retries}) reached, skipping")
                return False
        return needs
    return check


def _derive_timeout(metas: list[dict], eval_mode: bool, auto_correct: bool) -> int:
    """Derive graph timeout from SOP complexity. No hardcoded values.

    Per-SOP budget: 60s base + 5s per bash block + 0.5s per line + explicit sleeps, min 120s.
    Eval adds 30s per SOP. Auto-correct multiplies by 2 (re-run cycles).
    """
    total = 0
    for meta in metas:
        per_sop = max(120, 60 + meta.get("bash_blocks", 0) * 5 + meta.get("lines", 0) // 2
                       + meta.get("sleep_seconds", 0))
        if eval_mode:
            per_sop += 30
        total += per_sop
    if auto_correct:
        total *= 2
    return total


def build_sop_graph(
    sop_paths: list[str],
    profile: Optional[str] = None,
    region: str = "us-east-1",
    default_model: str = "haiku",
    fix_mode: bool = False,
    no_steering: bool = False,
    eval_mode: bool = False,
    auto_correct: bool = False,
) -> "Graph":
    """Build a DAG from SOP files. Dependencies and models derived from content."""
    metas = [parse_sop_metadata(p) for p in sop_paths]
    edges = resolve_dependencies(metas)

    # Per-SOP eval contexts — each SOP gets its own session_id so the
    # evaluator only counts tool spans from that specific agent, not all
    # agents running in parallel.
    shared_telemetry = setup_eval_telemetry() if eval_mode else None

    builder = GraphBuilder()

    for meta, sop_path in zip(metas, sop_paths):
        # Per-SOP eval context: shared telemetry, unique session_id
        eval_ctx = None
        if shared_telemetry:
            eval_ctx = {
                "telemetry": shared_telemetry,
                "session_id": uuid.uuid4().hex,
            }

        model = select_model(meta, default_model)
        agent = create_sop_agent(
            sop_path, profile=profile, region=region,
            model_name=model, fix_mode=fix_mode, no_steering=no_steering,
            eval_ctx=eval_ctx,
        )
        builder.add_node(agent, meta["stem"])

        # When eval is on, add an EvalNode after each SOP agent
        if eval_mode:
            eval_node_id = f"eval-{meta['stem']}"
            eval_node = EvalNode(eval_ctx, sop_path, name=eval_node_id)
            builder.add_node(eval_node, eval_node_id)
            builder.add_edge(meta["stem"], eval_node_id)

            # Two-stage auto-correct: AGENT_FAULT → re-run with best model
            #                          SOP_FAULT   → patch SOP then re-run
            if auto_correct:
                corrector_id = f"correct-{meta['stem']}"
                corrector = CorrectorNode(sop_path, profile, region, name=corrector_id)
                builder.add_node(corrector, corrector_id)

                # AGENT_FAULT or SOP_FAULT → corrector patches the SOP
                builder.add_edge(eval_node_id, corrector_id,
                                 condition=_needs_correction(eval_node_id))
                # After correction → re-run ONLY if corrector actually patched the SOP
                builder.add_edge(corrector_id, meta["stem"],
                                 condition=_corrector_made_changes(corrector_id))

    # Determine the "terminal" node for each SOP (for inter-SOP dependency edges)
    # The eval node is always the last to run in the SOP cycle:
    #   SOP agent → eval → (if fail: corrector → SOP re-run → eval again)
    # So eval is always the terminal, regardless of auto_correct.
    terminal = {}
    for meta in metas:
        s = meta["stem"]
        if eval_mode:
            terminal[s] = (f"eval-{s}",)
        else:
            terminal[s] = (s,)

    # Add dependency edges (from terminal of upstream to SOP agent of downstream)
    # The Graph uses OR-join (any satisfied edge → node ready). We need AND-join
    # (ALL upstream deps complete before downstream starts). Fix: add an edge from
    # every upstream terminal, each carrying the SAME compound AND condition that
    # checks ALL terminals. When any upstream completes, its edge fires and the
    # condition checks if all others are also done. Only the last one to complete
    # will see True.
    stem_set = {m["stem"] for m in metas}

    from collections import defaultdict
    deps_by_target: dict[str, list[str]] = defaultdict(list)
    for from_stem, to_stem in edges:
        if from_stem in stem_set and to_stem in stem_set:
            deps_by_target[to_stem].append(from_stem)

    for to_stem, from_stems in deps_by_target.items():
        all_terminals = []
        for fs in from_stems:
            all_terminals.extend(terminal[fs])
        cond = _all_upstreams_passed(all_terminals, target=to_stem)
        for t in all_terminals:
            builder.add_edge(t, to_stem, condition=cond)

    # Entry points = nodes with no incoming edges in this run
    nodes_with_incoming = {to_s for _, to_s in edges if to_s in stem_set}
    for meta in metas:
        if meta["stem"] not in nodes_with_incoming:
            builder.set_entry_point(meta["stem"])

    builder.set_execution_timeout(_derive_timeout(metas, eval_mode, auto_correct))
    logger.info(f"Derived timeout: graph={_derive_timeout(metas, eval_mode, auto_correct)}s from {len(metas)} SOPs")
    if auto_correct:
        builder.reset_on_revisit(True)
        builder.set_max_node_executions(len(metas) * 9)  # 3 cycles per SOP
    builder.set_graph_id("sop-orchestrator")
    graph = builder.build()
    logger.info(f"Graph built: {len(graph.nodes)} nodes, {len(graph.edges)} edges, entries={[n.node_id for n in graph.entry_points]}")
    for e in graph.edges:
        logger.debug(f"  Edge: {e.from_node.node_id} -> {e.to_node.node_id} (cond={e.condition is not None})")
    return graph


def build_eval_loop(
    sop_path: str,
    profile: Optional[str] = None,
    region: str = "us-east-1",
    model_name: str = "haiku",
    fix_mode: bool = False,
    no_steering: bool = False,
    max_corrections: int = 2,
) -> "Graph":
    """Build a single-SOP graph with eval feedback loop.

    execute → eval → correct → execute ... (max N cycles)
                  → done (if passing)
    """
    eval_ctx = {
        "telemetry": setup_eval_telemetry(),
        "session_id": uuid.uuid4().hex,
    }

    stem = Path(sop_path).stem
    meta = parse_sop_metadata(sop_path)
    model = select_model(meta, model_name)

    agent = create_sop_agent(
        sop_path, profile=profile, region=region,
        model_name=model, fix_mode=fix_mode,
        no_steering=no_steering, eval_ctx=eval_ctx,
    )
    eval_node = EvalNode(eval_ctx, sop_path, name="eval")

    builder = GraphBuilder()
    builder.add_node(agent, stem)
    builder.add_node(eval_node, "eval")

    builder.add_edge(stem, "eval")

    if max_corrections > 0:
        corrector = CorrectorNode(sop_path, profile, region, name="corrector")
        builder.add_node(corrector, "corrector")
        builder.add_edge("eval", "corrector", condition=_needs_correction("eval"))
        builder.add_edge("corrector", stem, condition=_corrector_made_changes("corrector"))

    builder.set_entry_point(stem)
    builder.set_max_node_executions(3 + max_corrections * 3)
    builder.set_execution_timeout(_derive_timeout([meta], True, max_corrections > 0))
    builder.reset_on_revisit(True)
    builder.set_graph_id("sop-eval-loop")
    return builder.build()
