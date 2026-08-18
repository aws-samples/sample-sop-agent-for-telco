# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#!/usr/bin/env python3
"""
SOP Executor Agent - Production-grade SOP execution with auto-remediation.
Demo Demo: AI-Driven 5G App Deployment
"""

from __future__ import annotations
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

from strands import Agent
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookRegistry
from strands.models import BedrockModel

# Shared execution primitives + SOP tools live in core.executor (single source of
# truth). sop_executor previously defined drifted copies of these; they were unified
# into core.executor as part of S2.2. Import them here so the SOP agent reuses the
# canonical, config-driven versions rather than a fork.
from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import (  # noqa: F401
    ARGOCD_TOOLS,
    BASE_TOOLS,
    SOP_TOOLS,
    C,
    CmdResult,
    Colors,
    argocd_status,
    argocd_sync,
    banner,
    check_pod_status,
    describe_node,
    get_pod_logs,
    get_pod_name,
    get_tools_for_sop,
    kubectl,
    kubectl_exec,
    list_nodes,
    list_sops,
    parse_sop,
    read_sop,
    redfish_query,
    run_cmd,
    run_command,
    ssh_command,
    ssh_expect,
    ssm_command,
    telcocli,
    tool_call,
    tool_result,
)

# Configuration via environment variables
_script_dir = os.path.dirname(os.path.abspath(__file__))
SOP_REPO = os.getenv("SOP_REPO", os.path.join(_script_dir, ".."))
AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
DEFAULT_TIMEOUT = int(os.getenv("CMD_TIMEOUT", "120"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ============== SYSTEM PROMPT ==============
SYSTEM_PROMPT_BASE = """You are a strict SOP Executor Agent. You MUST NOT rationalize or explain away failures.

## CRITICAL RULES - VIOLATIONS ARE UNACCEPTABLE

1. **Exit code != 0 means FAILURE** - No exceptions. Do not say "but it might be okay"
2. **grep returning empty means FAILURE** - The thing you searched for is MISSING
3. **Resource count = 0 means FAILURE** - Zero resources is never acceptable
4. **Pod not found means FAILURE** - Missing pods must be reported and fixed

## FORBIDDEN BEHAVIORS

❌ "No SR-IOV plugin running, but pods have interfaces so it's probably fine"
❌ "Command failed but let me check something else instead"
❌ "Exit code 1 but no critical errors"
❌ "Resources show 0 but they may have already been consumed"

## Failure Detection Table

| Check | FAILURE Condition |
|-------|-------------------|
| kubectl exit != 0 | Any non-zero exit |
| grep empty output | Nothing matched |
| SR-IOV = 0 | intel.com resources = 0 |
| Pod not Running | Status != Running |
| ArgoCD OutOfSync | sync.status != Synced |
| GWU sts != act | sts=oos, sts=ini |

## Output Format

For EVERY command result:
- Exit 0 + expected output → "✅ PASS: <description>"
- Exit != 0 OR unexpected → "❌ FAILURE: <description>"

## Tools
list_sops, read_sop, parse_sop, run_command, kubectl, kubectl_exec,
get_pod_name, check_pod_status, get_pod_logs, describe_node, argocd_sync, argocd_status
"""

SYSTEM_PROMPT_REPORT = (
    SYSTEM_PROMPT_BASE
    + """
## MODE: REPORT ONLY

You are in REPORT mode. DO NOT attempt to fix or remediate any failures.
- Execute SOP steps and validate results
- Report all failures with "❌ FAILURE: <description>"
- DO NOT run remediation commands
- Provide a final summary of all issues found

Your job is to FIND and REPORT problems, not fix them."""
)

SYSTEM_PROMPT_FIX = (
    SYSTEM_PROMPT_BASE
    + """
## MODE: AUTONOMOUS FIX

You are in FIX mode. Autonomously remediate all failures found.
- Execute SOP steps and validate results
- On failure: immediately attempt remediation
- Retry validation after remediation
- Continue until all issues resolved or max retries (3) reached
- **Remediation is NOT complete until the affected pod/service is Running.** If a pod is stuck in CrashLoopBackOff after you fix the root cause, run `kubectl rollout restart` on its deployment to bypass the K8s exponential backoff timer. Then verify it reaches Running state.

## Remediation Actions

| Failure | Remediation |
|---------|-------------|
| SR-IOV = 0 | Restart sriov-device-plugin daemonset |
| Pod not Running | Check events, delete stuck pod |
| Pod CrashLoopBackOff | Fix root cause, then `kubectl rollout restart deployment/<name>` |
| ArgoCD OutOfSync | `argocd_sync()` |
| GWU sts != act | Wait 60s for BGP, then `ins_gwu lgwu001` |
| BGP neighbors down | Wait 30s and retry (convergence time) |

Your job is to FIND and FIX problems autonomously. Do not ask for permission."""
)


# ============== STEERING HOOKS ==============
class SOPSteeringHooks:
    """Just-in-time steering for SOP executor — intercepts tool calls to prevent known failures."""

    TOOL_WARN = 80
    TOOL_STOP = 95
    SSH_HEREDOC_MAX = 500

    def __init__(self, fix_mode: bool = False):
        self.fix_mode = fix_mode
        self.tool_count = 0
        self.ledger: list[dict] = []

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call)
        registry.add_callback(AfterToolCallEvent, self._after_tool_call)

    def _before_tool_call(self, event: BeforeToolCallEvent, **kwargs):
        name = event.tool_use["name"]
        inp = event.tool_use.get("input", {})
        self.tool_count += 1

        # --- Tool call budget ---
        if self.tool_count >= self.TOOL_STOP:
            event.cancel_tool = (
                f"Tool call budget exhausted ({self.tool_count}/{self.TOOL_STOP}). "
                "Summarize progress and stop. Do NOT call more tools."
            )
            return
        if self.tool_count >= self.TOOL_WARN:
            logger.warning(f"Tool call budget warning: {self.tool_count}/{self.TOOL_STOP}")

        # --- SSH heredoc guard ---
        if name == "ssh_command":
            cmd = str(inp.get("command", ""))
            if "<<" in cmd and len(cmd) > self.SSH_HEREDOC_MAX:
                event.cancel_tool = (
                    "Long heredocs fail over SSH. Write the content to a file with "
                    "base64 encoding instead: echo '<base64>' | base64 -d > /path/file"
                )
                return

        # --- Namespace guard ---
        if name in ("kubectl", "kubectl_exec"):
            args = str(inp.get("args", inp.get("command", "")))
            ns = str(inp.get("namespace", ""))
            if ns == "default" or "-n default" in args or "--namespace=default" in args:
                event.cancel_tool = (
                    "Check the SOP for the correct namespace. 'default' is rarely correct for NF deployments."
                )
                return

        # --- Dangerous command guard (REPORT mode) ---
        if not self.fix_mode:
            cmd = str(inp.get("command", inp.get("args", "")))
            dangerous = ["sudo reboot", "kubectl delete namespace", "--force --grace-period=0", "pkill -9"]
            for pattern in dangerous:
                if pattern in cmd:
                    event.cancel_tool = (
                        f"Blocked in REPORT mode: '{pattern}' is destructive. "
                        "Switch to FIX mode to execute destructive commands."
                    )
                    return

        # --- Port-forward hang guard ---
        if name in ("run_command", "kubectl"):
            cmd = str(inp.get("command", inp.get("args", "")))
            if "port-forward" in cmd and "&" not in cmd:
                event.cancel_tool = (
                    "port-forward without '&' will hang the agent. "
                    "Add '&' to run in background, or use 'timeout 10 kubectl port-forward ...'."
                )
                return

    def _after_tool_call(self, event: AfterToolCallEvent, **kwargs):
        name = event.tool_use["name"]
        result_text = ""
        if event.result and event.result.get("content"):
            for block in event.result["content"]:
                if isinstance(block, dict) and "text" in block:
                    result_text += block["text"]
        self.ledger.append({"tool": name, "result_snippet": result_text[:200]})


# ============== EVAL TELEMETRY ==============
def setup_eval_telemetry():
    """Initialize in-memory OTel tracing for post-execution evaluation."""
    from strands_evals.telemetry import StrandsEvalsTelemetry

    telemetry = StrandsEvalsTelemetry().setup_in_memory_exporter()
    logger.info("Eval telemetry enabled (in-memory span exporter)")
    return telemetry


def collect_eval_session(telemetry, session_id: str):
    """Map captured spans into an eval session for evaluators."""
    from strands_evals.mappers import StrandsInMemorySessionMapper

    spans = telemetry.in_memory_exporter.get_finished_spans()
    mapper = StrandsInMemorySessionMapper()
    return mapper.map_to_session(spans, session_id=session_id)


# SOP eval metadata — derived from SOP content, not hardcoded
_TOOL_PATTERNS = {
    "check_pod_status": ["check_pod_status"],
    "kubectl_exec": ["kubectl exec"],
    "kubectl": ["kubectl get", "kubectl apply", "kubectl delete", "kubectl describe", "kubectl patch"],
    "ssh_command": ["ssh ", "ssh_command"],
    "argocd_sync": ["argocd_sync", "argocd app sync"],
    "argocd_status": ["argocd_status", "argocd app get"],
    "telcocli": ["telcocli"],
}


def get_sop_eval_meta(sop_path: str) -> dict:
    """Derive eval metadata from SOP content — detects which tools the SOP references."""
    try:
        content = Path(sop_path).read_text().lower()
    except (FileNotFoundError, OSError):
        return {}

    required = []
    for tool_name, patterns in _TOOL_PATTERNS.items():
        if any(p in content for p in patterns):
            required.append(tool_name)
    return {"required_tools": required} if required else {}


def run_post_eval(eval_ctx: dict, sop_path: str, agent_output: str) -> list:
    """Run post-execution evaluators on captured trace. Returns list of EvaluationReport."""
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "evals"))
    from evaluators import SOPCompletionEvaluator, SteeringEffectivenessEvaluator
    from strands_evals import Case, Experiment

    session = collect_eval_session(eval_ctx["telemetry"], eval_ctx["session_id"])
    meta = get_sop_eval_meta(sop_path)

    case = Case[str, str](
        name=Path(sop_path).stem if sop_path else "interactive",
        input=sop_path,
        metadata=meta,
    )

    evaluators = [SteeringEffectivenessEvaluator(), SOPCompletionEvaluator()]
    experiment = Experiment[str, str](cases=[case], evaluators=evaluators)

    def task_fn(c):
        return {"output": agent_output, "trajectory": session}

    reports = experiment.run_evaluations(task_fn)
    return reports


# ============== AGENT FACTORY ==============
# Model resolution is dynamic — uses model_resolver which checks active Bedrock
# profiles. Legacy hardcoded MODELS dict kept only as CLI shorthand fallback.
_MODEL_TIER_MAP = {
    "haiku": "fast",
    "sonnet": "smart",
    "opus": "powerful",
}


def _resolve_model_id(model_name: str) -> str:
    """Resolve model name to an active Bedrock model ID dynamically.

    Priority:
    1. BEDROCK_MODEL_ID env var (explicit override)
    2. model_resolver.get_model(tier=...) (dynamic, checks active profiles)
    3. model_name passed as-is (allows full ARN/model ID)
    """
    env_override = os.environ.get("BEDROCK_MODEL_ID")
    if env_override:
        return env_override

    # Map friendly names to tiers for dynamic resolution
    tier = _MODEL_TIER_MAP.get(model_name)
    if tier:
        try:
            from amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver import get_model
            resolved = get_model(tier=tier)
            if resolved:
                logger.info("Model resolved: %s (tier=%s) → %s", model_name, tier, resolved)
                return resolved
        except Exception as exc:
            logger.warning("Dynamic model resolution failed: %s; falling back", exc)

    # Fallback: treat model_name as a literal model ID
    return model_name


def create_agent(
    profile: Optional[str] = None,
    region: str = AWS_REGION,
    model_name: str = "sonnet",
    fix_mode: bool = False,
    sop_path: str = "",
    no_steering: bool = False,
    eval_mode: bool = False,
) -> tuple:
    """Create the SOP executor agent with tools scoped to the SOP.

    Returns:
        (agent, eval_context) where eval_context is a dict with telemetry/session_id
        when eval_mode=True, or an empty dict otherwise.
    """
    from amzn_cse_telco_autonomous_network_agents_app.agent.util.aws import aws_session

    # Eval telemetry (must init before Agent so OTel provider is global)
    eval_ctx = {}
    if eval_mode:
        telemetry = setup_eval_telemetry()
        session_id = str(uuid.uuid4())
        eval_ctx = {"telemetry": telemetry, "session_id": session_id}
        print(f"{C.CYAN}📊 Eval mode enabled (session: {session_id[:8]}...){C.END}")

    model_id = _resolve_model_id(model_name)
    mode_str = "FIX (autonomous)" if fix_mode else "REPORT (read-only)"
    logger.info(f"Initializing agent: profile={profile or 'default'}, region={region}")
    print(f"{C.CYAN}🤖 Initializing Strands Agent with {model_name}{C.END}")
    print(f"{C.CYAN}☁️  AWS Profile: {profile or 'default'} | Region: {region}{C.END}")
    print(f"{C.CYAN}🔧 Mode: {mode_str}{C.END}")

    try:
        session = aws_session(profile, region)
        # Verify credentials
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        print(f"{C.CYAN}🔑 Account: {identity['Account']}{C.END}")
    except Exception as e:
        print(f"{C.RED}❌ AWS credentials error: {e}{C.END}")
        raise SystemExit(1)

    try:
        model = BedrockModel(model_id=model_id, boto_session=session)
    except Exception as e:
        print(f"{C.RED}❌ Bedrock model error: {e}{C.END}")
        raise SystemExit(1)

    system_prompt = SYSTEM_PROMPT_FIX if fix_mode else SYSTEM_PROMPT_REPORT
    tools = get_tools_for_sop(sop_path) if sop_path else BASE_TOOLS

    hooks = [] if no_steering else [SOPSteeringHooks(fix_mode=fix_mode)]
    trace_attrs = {}
    if eval_mode:
        trace_attrs = {
            "session.id": eval_ctx["session_id"],
            "gen_ai.conversation.id": eval_ctx["session_id"],
        }
    agent = Agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        hooks=hooks,
        trace_attributes=trace_attrs or None,
    )
    print(f"{C.GREEN}✅ Agent ready with {len(tools)} tools{C.END}")
    return agent, eval_ctx


# ============== MAIN ==============
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="SOP Executor Agent - Demo")
    parser.add_argument("sop", nargs="+", help="SOP filename(s) to execute")
    parser.add_argument("--profile", "-p", help="AWS profile for Bedrock")
    parser.add_argument("--region", "-r", default=AWS_REGION, help="AWS region")
    parser.add_argument(
        "--model",
        "-m",
        default="haiku",
        choices=list(_MODEL_TIER_MAP.keys()),
        help="Model: haiku (fast), sonnet3.5, sonnet (default: haiku)",
    )
    parser.add_argument(
        "--fix", "-f", action="store_true", help="Autonomous fix mode - remediate failures automatically"
    )
    parser.add_argument("--mode", choices=["sop", "gitops"], default="sop")
    parser.add_argument("--repo", default=SOP_REPO, help="SOP repository path")
    parser.add_argument("--no-steering", action="store_true", help="Disable steering hooks")
    parser.add_argument("--eval", action="store_true", help="Enable post-execution evaluation")
    parser.add_argument(
        "--auto-correct", action="store_true", help="Auto-correct SOP from eval failures (requires --eval)"
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation for auto-correct commits")
    args = parser.parse_args()

    banner("🚀 AI-Driven NF Deployment Agent", C.HEADER)
    print(f"{C.BOLD}Strands Agent + Amazon Bedrock{C.END}\n")

    # Resolve SOP paths
    sop_paths = []
    if args.sop:
        for s in args.sop:
            sop_paths.append(s if "/" in s else f"{args.repo}/sops/{s}")
    sop_path = sop_paths[0] if sop_paths else ""

    agent, eval_ctx = create_agent(
        profile=args.profile,
        region=args.region,
        model_name=args.model,
        fix_mode=args.fix,
        sop_path=sop_path,
        no_steering=args.no_steering,
        eval_mode=args.eval,
    )

    if args.mode == "gitops":
        banner("🔄 GitOps Pre-Commit Gate", C.BLUE)
        prompt = f"""GitOps workflow:
1. Check ArgoCD status with `argocd_status`
2. If OutOfSync: validate SR-IOV/Multus, then `argocd_sync`
3. Run validation SOP: {args.repo}/sops/03-validation.md
4. Remediate failures, report final status"""
    elif len(sop_paths) > 1:
        banner(f"📋 Executing: {len(sop_paths)} SOPs via graph", C.BLUE)
        import asyncio

        from amzn_cse_telco_autonomous_network_agents_app.agent.sop_graph import build_sop_graph

        graph = build_sop_graph(
            sop_paths=sop_paths,
            profile=args.profile,
            region=args.region,
            default_model=args.model,
            fix_mode=args.fix,
            eval_mode=args.eval,
            auto_correct=args.auto_correct,
        )
        task = "Execute your assigned SOP. Read it, run each step, and report pass/fail results."
        result = asyncio.run(graph.invoke_async(task))
        print(f"\n{C.GREEN}Graph complete: {result.completed_nodes}/{result.total_nodes} nodes{C.END}")
        sys.exit(0)
    elif sop_paths:
        banner(f"📋 Executing: {sop_paths[0]}", C.BLUE)
        prompt = f"Execute SOP: {sop_paths[0]}\nValidate and remediate as needed."
    else:
        banner("📂 Interactive Mode", C.BLUE)
        prompt = f"List SOPs in {args.repo}/sops/ and ask which to execute."

    print(f"{C.CYAN}{'─' * 60}{C.END}\n")

    try:
        result = agent(prompt)
        banner("📊 Final Report", C.GREEN)
        print(result)

        # Post-execution evaluation
        if args.eval and eval_ctx:
            banner("🧪 Post-Execution Evaluation", C.CYAN)
            try:
                reports = run_post_eval(eval_ctx, sop_path, str(result))
                has_failures = False
                for report in reports:
                    print(f"\n{C.BOLD}{report.evaluator_name}{C.END}")
                    print(f"  Score: {report.overall_score:.2f}")
                    for i, reason in enumerate(report.reasons):
                        status = f"{C.GREEN}✅" if report.test_passes[i] else f"{C.RED}❌"
                        print(f"  {status} {reason}{C.END}")
                        if not report.test_passes[i]:
                            has_failures = True

                # SOP auto-correction
                if args.auto_correct and has_failures and sop_path:
                    banner("🔧 SOP Auto-Correction", C.YELLOW)
                    try:
                        sys.path.insert(0, os.path.join(_script_dir, "..", "evals"))
                        from sop_corrector import correct_sop, extract_failures

                        failures = extract_failures(reports)
                        print(f"{C.YELLOW}Found {len(failures)} failure(s) to correct{C.END}")
                        for f in failures:
                            print(f"  • [{f['evaluator']}] {f['reason']}")

                        if not args.yes:
                            confirm = input(f"\n{C.BOLD}Apply corrections to {sop_path}? [y/N] {C.END}")
                            if confirm.lower() != "y":
                                print(f"{C.YELLOW}Skipped.{C.END}")
                                return

                        corrected = correct_sop(
                            reports,
                            sop_path,
                            profile=args.profile,
                            region=args.region,
                            auto_commit=args.yes,
                        )
                        if corrected:
                            print(f"{C.GREEN}✅ SOP corrected: {sop_path}{C.END}")
                        else:
                            print(f"{C.YELLOW}No corrections applied.{C.END}")
                    except Exception as e:
                        print(f"{C.RED}❌ Auto-correction failed: {e}{C.END}")
                        logger.warning(f"Auto-correction failed: {e}")
            except Exception as e:
                print(f"{C.YELLOW}⚠️  Eval failed: {e}{C.END}")
                logger.warning(f"Eval failed: {e}")
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}⚠️  Interrupted by user{C.END}")
        raise SystemExit(130)
    except Exception as e:
        banner("❌ Agent Error", C.RED)
        print(f"{C.RED}Error type: {type(e).__name__}{C.END}")
        print(f"{C.RED}Error: {e}{C.END}")
        import traceback

        traceback.print_exc()
        logger.exception("Agent execution failed")
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}⚠️  Interrupted{C.END}")
    except SystemExit:
        raise
    except Exception as e:
        print(f"{C.RED}❌ Unexpected error type: {type(e).__name__}{C.END}")
        print(f"{C.RED}❌ Unexpected error: {e}{C.END}")
        import traceback

        traceback.print_exc()
        logger.exception("Unhandled exception")
        raise SystemExit(1)
