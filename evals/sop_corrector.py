# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""SOP Correction Agent — patches SOPs based on eval failures."""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CORRECTOR_PROMPT = """You are an SOP editor for network function deployment and operations procedures.

Given evaluation failures from a real agent execution, patch the SOP markdown to prevent those failures in future runs.

Rules:
- Only modify or add steps that directly address the reported failures
- Preserve ALL existing content — do not remove or rewrite working steps
- Use RFC 2119 keywords (MUST, SHOULD) for critical additions
- Add steps in the correct position (prerequisites before actions, waits before checks)
- Keep the same markdown formatting style as the original
- Output the COMPLETE corrected SOP markdown, not just the diff

Common corrections:
- "Missing required tools: [check_pod_status]" → Add a pod status check step before kubectl_exec steps
- "Repeated failures: ssh_command:timeout" → Add retry guidance or alternative approach
- "Tool budget exceeded" → Consolidate verbose multi-step sections into single commands
- "BGP wait skipped" → Add explicit "MUST wait 120s" step with sleep command
"""

MAX_CORRECTIONS_PER_SESSION = 3


def build_correction_prompt(sop_content: str, failures: list[dict]) -> str:
    """Build the prompt for the correction agent."""
    failure_text = "\n".join(
        f"- [{f['evaluator']}] {f['reason']}" for f in failures
    )
    return f"""## Evaluation Failures

{failure_text}

## Current SOP

{sop_content}

## Task
Output the corrected SOP markdown that addresses the failures above."""


def extract_failures(reports: list) -> list[dict]:
    """Extract actionable failures from eval reports."""
    failures = []
    for report in reports:
        for i, passed in enumerate(report.test_passes):
            if not passed:
                failures.append({
                    "evaluator": report.evaluator_name,
                    "reason": report.reasons[i],
                    "score": report.scores[i],
                })
    return failures


def correct_sop(
    reports: list,
    sop_path: str,
    profile: str = None,
    region: str = "us-east-1",
    auto_commit: bool = False,
    _correction_count: dict = None,
) -> str | None:
    """Run the SOP correction agent on eval failures.

    Args:
        reports: EvaluationReport list from run_post_eval()
        sop_path: Path to the SOP markdown file
        profile: AWS profile for Bedrock
        region: AWS region
        auto_commit: If True, git commit without confirmation
        _correction_count: Mutable dict tracking corrections per session

    Returns:
        Corrected SOP content, or None if no corrections needed.
    """
    if _correction_count is None:
        _correction_count = {}

    failures = extract_failures(reports)
    if not failures:
        logger.info("No eval failures — no corrections needed")
        return None

    # Rate limit
    sop_key = Path(sop_path).stem
    count = _correction_count.get(sop_key, 0)
    if count >= MAX_CORRECTIONS_PER_SESSION:
        logger.warning(f"Max corrections ({MAX_CORRECTIONS_PER_SESSION}) reached for {sop_key}")
        return None
    _correction_count[sop_key] = count + 1

    # Read current SOP
    sop_content = Path(sop_path).read_text()
    prompt = build_correction_prompt(sop_content, failures)

    # Run correction agent (haiku — cheap and fast)
    from strands import Agent
    from strands.models import BedrockModel
    import boto3

    session = boto3.Session(profile_name=profile, region_name=region)
    model = BedrockModel(
        model_id="us.anthropic.claude-3-5-haiku-20241022-v1:0",
        boto_session=session,
    )
    agent = Agent(
        model=model,
        system_prompt=CORRECTOR_PROMPT,
        callback_handler=None,
    )

    result = str(agent(prompt))

    # Extract markdown from response (strip any preamble)
    if "# " in result:
        result = result[result.index("# "):]

    # Write corrected SOP
    Path(sop_path).write_text(result)
    logger.info(f"SOP corrected: {sop_path}")

    # Git commit if requested
    if auto_commit:
        _git_commit_sop(sop_path, failures)

    return result


def _git_commit_sop(sop_path: str, failures: list[dict]):
    """Git add + commit the corrected SOP."""
    import subprocess
    summary = failures[0]["reason"][:60] if failures else "eval correction"
    try:
        subprocess.run(["git", "add", sop_path], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"fix(sop): auto-correct from eval — {summary}"],
            check=True, capture_output=True,
        )
        logger.info(f"Committed SOP correction: {sop_path}")
    except subprocess.CalledProcessError as e:
        logger.warning(f"Git commit failed: {e.stderr.decode()}")
