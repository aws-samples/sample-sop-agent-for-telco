# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ANRA agent entry point for Amazon Bedrock AgentCore Runtime.

This module wraps the core SOP execution engine (in `agent/`) for deployment
to AgentCore Runtime. The same agent code can be deployed via this entry point
or via the EKS Helm chart — only the runtime adapter differs.

Local testing:
    agentcore dev --no-browser
    curl -X POST http://localhost:8080/invocations \\
      -H "Content-Type: application/json" \\
      -d '{"prompt": "Run the deploy-5g-core SOP"}'

Deployment:
    agentcore deploy
    agentcore invoke "Run remediation for nf-crashloop alarm"
"""

import logging
import os
import sys
from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp

# Make the existing agent/ modules importable. Two layouts are supported:
#   1. Repo workspace:  agent/ is at <repo>/agent (parent.parent.parent of this file)
#   2. Container:       agent/ is at /app/agent (set via PYTHONPATH=/app:/app/agent)
_here = Path(__file__).resolve().parent
for candidate in (_here.parent.parent / "agent", Path("/app/agent")):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

# Configure logging early
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
log = logging.getLogger("anra.agentcore")

# Lazy imports after sys.path is set so the agent/ modules resolve correctly
from sop_executor import create_agent  # noqa: E402

app = BedrockAgentCoreApp()

# Cached agent instances per (sop_path, model_tier, fix_mode) tuple.
# AgentCore Runtime keeps the Python process alive between invocations within
# a session, so caching saves the cost of model discovery and Bedrock client
# setup on repeated calls.
_agent_cache: dict[tuple, object] = {}

DEFAULT_MODEL = os.getenv("ANRA_DEFAULT_MODEL", "haiku")
DEFAULT_REGION = os.getenv("AWS_REGION", os.getenv("BEDROCK_REGION", "us-west-2"))


def _get_agent(
    sop_path: str = "",
    model_name: str = DEFAULT_MODEL,
    fix_mode: bool = True,
):
    """Return a cached Strands agent for the given SOP + model tier."""
    key = (sop_path, model_name, fix_mode)
    if key not in _agent_cache:
        log.info("Building Strands agent: sop=%s, model=%s, fix=%s", sop_path, model_name, fix_mode)
        agent, _eval_ctx = create_agent(
            region=DEFAULT_REGION,
            model_name=model_name,
            fix_mode=fix_mode,
            sop_path=sop_path,
            no_steering=False,
        )
        _agent_cache[key] = agent
    return _agent_cache[key]


@app.entrypoint
def invoke(payload: dict) -> dict:
    """AgentCore Runtime entry point.

    Expected payload shapes:

    1. Run a named SOP (Day-1 deployment or Day-2 remediation):
       {"action": "run_sop", "sop": "deploy-5g-core", "model": "haiku",
        "fix_mode": true}

    2. Process Day-2 alarms (typically called by EventBridge schedule):
       {"action": "process_alarms", "alarms": [{"name": "nf-crashloop", ...}]}

    3. Free-form prompt (replaces the "Ask ANRA" chat UI):
       {"prompt": "What is the cluster status?"}

    Returns:
       {"result": <agent response>, "session_id": <str>, "metadata": {...}}
    """
    log.info("Invocation payload keys: %s", list(payload.keys()))

    action = payload.get("action")
    if action == "run_sop":
        return _run_sop(payload)
    if action == "process_alarms":
        return _process_alarms(payload)
    if "prompt" in payload:
        return _free_form_prompt(payload)

    return {
        "error": f"Unknown action: {action!r}",
        "supported_actions": ["run_sop", "process_alarms", "prompt"],
    }


def _resolve_sop_path(sop_name: str) -> Path | None:
    """Find an SOP markdown file by name, anywhere under the SOP repo."""
    # SOP_REPO defaults to the repo root in dev or /app in container
    default_repo = "/app" if Path("/app/sops").exists() else str(_here.parent.parent)
    sop_repo = Path(os.getenv("SOP_REPO", default_repo))
    # Allow either bare name ("deploy-5g-core") or relative path
    if "/" in sop_name:
        candidate = sop_repo / sop_name
        if candidate.exists():
            return candidate
        candidate = sop_repo / "sops" / sop_name
        if candidate.exists():
            return candidate
    candidates = list(sop_repo.glob(f"sops/**/{sop_name}.md"))
    return candidates[0] if candidates else None


def _run_sop(payload: dict) -> dict:
    """Execute a named SOP file."""
    sop_name = payload.get("sop")
    if not sop_name:
        return {"error": "Missing required field: sop"}

    sop_path = _resolve_sop_path(sop_name)
    if not sop_path:
        return {"error": f"SOP not found: {sop_name}"}

    model_name = payload.get("model", DEFAULT_MODEL)
    fix_mode = payload.get("fix_mode", True)

    agent = _get_agent(
        sop_path=str(sop_path),
        model_name=model_name,
        fix_mode=fix_mode,
    )

    log.info("Executing SOP: %s (model=%s, fix=%s)", sop_path, model_name, fix_mode)
    prompt = f"Execute SOP: {sop_path}\nValidate each step against the expected output and remediate as needed."
    result = agent(prompt)

    return {
        "sop": sop_name,
        "sop_path": str(sop_path),
        "result": str(result),
        "model": model_name,
        "fix_mode": fix_mode,
    }


def _process_alarms(payload: dict) -> dict:
    """Process a batch of Day-2 alarms.

    Phase 1: simple summarization to validate the round-trip.
    Phase 3: will wire to `agent/correlator.py` for topology-aware RCA.
    """
    alarms = payload.get("alarms", [])
    if not alarms:
        return {"alarms_processed": 0, "message": "No alarms in payload"}

    # Use a fast model for summarization; correlator phase will add escalation logic.
    agent = _get_agent(model_name="haiku", fix_mode=False)
    summary = agent(
        "Summarize the following alarms and identify the most likely root cause. "
        "Recommend the appropriate remediation SOP.\n\n"
        f"Alarms: {alarms}"
    )

    return {
        "alarms_processed": len(alarms),
        "summary": str(summary),
    }


def _free_form_prompt(payload: dict) -> dict:
    """Handle a free-form chat prompt (replaces 'Ask ANRA' UI calls)."""
    prompt = payload.get("prompt", "").strip()
    if not prompt:
        return {"error": "Missing required field: prompt"}

    model_name = payload.get("model", DEFAULT_MODEL)
    agent = _get_agent(model_name=model_name, fix_mode=False)
    result = agent(prompt)
    return {"result": str(result), "model": model_name}


if __name__ == "__main__":
    # For `agentcore dev` local server. AgentCore Runtime invokes app directly.
    app.run()
