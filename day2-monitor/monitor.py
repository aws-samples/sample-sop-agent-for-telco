# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#!/usr/bin/env python3
import tempfile
"""
Day2 Monitoring Agent — Self-healing operations for deployed NFs.

Polls Alertmanager + k8s events, auto-generates remediation SOPs via Strands Agent,
creates GitLab issues for approval, executes approved fixes, and self-improves SOPs
through the eval/correct loop.
"""

import os
import sys
import json
import time
import logging
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] [day2] %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ──
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))
ALERTMANAGER_URL = os.getenv(
    "ALERTMANAGER_URL",
    "http://kube-prometheus-stack-alertmanager.monitoring.svc.cluster.local:9093",
)
PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL", "http://localhost:9090"
)
GITLAB_API = os.getenv("GITLAB_API", "https://gitlab.com/api/v4")
GITLAB_PROJECT_ID = os.getenv("GITLAB_PROJECT_ID", "")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "")
SOP_REPO = os.getenv("SOP_REPO", "/app")
BEDROCK_PROFILE = os.getenv("BEDROCK_PROFILE", "")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-west-2")
WATCHED_NAMESPACES = os.getenv("WATCHED_NAMESPACES", "aws-app,monitoring,argocd").split(",")
IGNORED_ALERTS = set(os.getenv("IGNORED_ALERTS", "Watchdog,InfoInhibitor").split(","))
# If set, only these alert names create issues (comma-separated). Empty = all alerts.
ALERT_FILTER = set(filter(None, os.getenv("ALERT_FILTER", "").split(",")))
APPROVAL_TIMEOUT = int(os.getenv("APPROVAL_TIMEOUT", "1800"))  # 30 min
ALARM_REFERENCE_PATH = os.getenv("ALARM_REFERENCE_PATH", "/app/alarm_reference.json")

# Load ISV alarm reference (reaction procedures, service impact, fault details)
_alarm_reference: dict = {}
try:
    with open(ALARM_REFERENCE_PATH, encoding="utf-8") as f:
        _alarm_reference = json.load(f)
    log.info(f"Loaded {len(_alarm_reference)} alarm definitions from {ALARM_REFERENCE_PATH}")
except FileNotFoundError:
    log.info("No alarm reference file found — SOP generation will use generic context only")
except Exception as e:
    log.warning(f"Failed to load alarm reference: {e}")


def _lookup_alarm(alert_name: str) -> dict | None:
    """Look up alarm reference by name. Tries exact → prefix → substring match."""
    if not _alarm_reference:
        return None
    # Exact match
    if alert_name in _alarm_reference:
        return _alarm_reference[alert_name]
    # Alert name starts with a known alarm name (e.g. gwu_fault_information_worker_overload → gwu_fault_information)
    best, best_len = None, 0
    for ref_name, ref_data in _alarm_reference.items():
        if alert_name.startswith(ref_name) and len(ref_name) > best_len:
            best, best_len = ref_data, len(ref_name)
    if best:
        return best
    # Known alarm name starts with alert name (reverse prefix)
    for ref_name, ref_data in _alarm_reference.items():
        if ref_name.startswith(alert_name) and len(alert_name) > best_len:
            best, best_len = ref_data, len(alert_name)
    return best


def _run(cmd: list[str], timeout: int = 10) -> str:
    """Run a command as list of args (no shell), return stdout or error string."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)  # nosec B603
        return (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return "(timeout)"
    except Exception as e:
        return f"(error: {e})"


def _kubectl(args: str, timeout: int = 10) -> str:
    import shlex
    return _run(["kubectl"] + shlex.split(args), timeout)


def _prom_query(query: str) -> str:
    """Query Prometheus via kubectl exec into the prometheus pod."""
    import urllib.parse
    encoded = urllib.parse.quote(query)
    return _run(
        f"kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- "
        f"wget -qO- '{PROMETHEUS_URL}/api/v1/query?query={encoded}'",
        timeout=15,
    )


# ── Alert Discovery ──

def fetch_active_alerts() -> list[dict]:
    """Fetch active alerts from Alertmanager."""
    raw = _run(
        f"kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- "
        f"wget -qO- '{ALERTMANAGER_URL}/api/v2/alerts'",
        timeout=10,
    )
    try:
        alerts = json.loads(raw)
        return [
            a for a in alerts
            if a.get("status", {}).get("state") == "active"
            and a.get("labels", {}).get("alertname") not in IGNORED_ALERTS
            and (not ALERT_FILTER or a.get("labels", {}).get("alertname") in ALERT_FILTER)
        ]
    except (json.JSONDecodeError, TypeError):
        log.warning(f"Failed to parse alerts: {raw[:200]}")
        return []


def fetch_k8s_events() -> list[dict]:
    """Fetch recent Warning events from watched namespaces."""
    events = []
    for ns in WATCHED_NAMESPACES:
        raw = _kubectl(
            f"get events -n {ns} --field-selector type=Warning "
            f"-o json --sort-by='.lastTimestamp'",
            timeout=10,
        )
        try:
            data = json.loads(raw)
            for item in data.get("items", [])[-10:]:  # last 10 per namespace
                events.append({
                    "namespace": ns,
                    "reason": item.get("reason", ""),
                    "message": item.get("message", ""),
                    "object": item.get("involvedObject", {}).get("name", ""),
                    "count": item.get("count", 1),
                    "last_seen": item.get("lastTimestamp", ""),
                })
        except (json.JSONDecodeError, TypeError):
            pass
    return events


def fetch_prometheus_rules() -> list[dict]:
    """Fetch all alerting rules from Prometheus for context."""
    raw = _run(
        f"kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- "
        f"wget -qO- '{PROMETHEUS_URL}/api/v1/rules'",
        timeout=15,
    )
    try:
        data = json.loads(raw)
        rules = []
        for group in data.get("data", {}).get("groups", []):
            for rule in group.get("rules", []):
                if rule.get("type") == "alerting":
                    rules.append({
                        "name": rule.get("name", ""),
                        "group": group.get("name", ""),
                        "expr": rule.get("query", ""),
                        "severity": rule.get("labels", {}).get("severity", ""),
                        "annotations": rule.get("annotations", {}),
                        "duration": rule.get("duration", 0),
                    })
        return rules
    except (json.JSONDecodeError, TypeError):
        log.warning("Failed to fetch Prometheus rules")
        return []


def alert_fingerprint(alert: dict) -> str:
    """Stable fingerprint for dedup."""
    labels = alert.get("labels", {})
    key = f"{labels.get('alertname', '')}|{labels.get('namespace', '')}|{labels.get('pod', '')}|{labels.get('job', '')}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]  # nosec B324


# ── SOP Generation ──

def generate_remediation_sop(alert: dict, rules: list[dict], existing_sops: list[str]) -> str:
    """Use Strands Agent to generate a remediation SOP for an alert."""
    try:
        from strands import Agent
        from strands.models.bedrock import BedrockModel
        from strands_agents_sops import get_sop_format

        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alert_name = labels.get("alertname", "unknown")

        # Look up ISV alarm reference for this alert
        alarm_ref = _lookup_alarm(alert_name)
        alarm_context = ""
        if alarm_ref:
            alarm_context = "\n\nISV Alarm Reference (use this as the authoritative source for reaction procedures):\n"
            for k, v in alarm_ref.items():
                alarm_context += f"- {k}: {v}\n"

        # Find matching rule for context
        matching_rule = next(
            (r for r in rules if r["name"] == alert_name), {}
        )

        # Read existing SOPs for context
        sop_context = ""
        sop_dir = Path(SOP_REPO) / "sops"
        for f in sorted(sop_dir.glob("*.md"))[:3]:  # first 3 as reference
            sop_context += f.read_text()[:1000] + "\n---\n"

        system_prompt = f"""{get_sop_format()}

You generate remediation SOPs for Kubernetes/5G network alerts.
The SOP MUST be executable by an AI agent with kubectl, ssh, and argocd tools.

Format requirements:
- Title: "Remediation: {{alert name}}"
- Prerequisites section
- Diagnostic steps (verify the issue is real)
- Remediation steps with bash commands in code blocks
- Verification steps (confirm fix worked)
- Rollback steps (if fix makes things worse)
- Success Criteria section

Reference SOPs from this project:
{sop_context}"""

        import boto3
        session = boto3.Session(
            profile_name=BEDROCK_PROFILE if BEDROCK_PROFILE else None,
            region_name=BEDROCK_REGION,
        )
        model = BedrockModel(
            model_id="anthropic.claude-3-haiku-20240307-v1:0",
            boto_session=session,
        )
        agent = Agent(model=model, system_prompt=system_prompt)

        prompt = f"""Generate a remediation SOP for this alert:

Alert: {alert_name}
Severity: {labels.get('severity', 'unknown')}
Namespace: {labels.get('namespace', 'N/A')}
Pod: {labels.get('pod', 'N/A')}
Summary: {annotations.get('summary', annotations.get('description', 'No description'))}
PromQL Expression: {matching_rule.get('expr', 'N/A')}
Rule Annotations: {json.dumps(matching_rule.get('annotations', {}), indent=2)}
Duration: {matching_rule.get('duration', 'N/A')}s
{alarm_context}
Current cluster state:
- Namespaces watched: {', '.join(WATCHED_NAMESPACES)}
"""
        result = agent(prompt)
        return str(result)
    except Exception as e:
        log.error(f"SOP generation failed for {alert.get('labels', {}).get('alertname')}: {e}")
        alert_name = alert.get('labels', {}).get('alertname', 'unknown')
        summary = alert.get('annotations', {}).get('summary', alert.get('annotations', {}).get('description', ''))
        return (
            f"# Remediation: {alert_name}\n\n"
            f"**Alert:** {alert_name}  \n"
            f"**Summary:** {summary}\n\n"
            f"## Procedure\n\n"
            f"1. Investigate the alert in the affected namespace\n"
            f"2. Check pod logs and events for root cause\n"
            f"3. Apply appropriate remediation\n"
            f"4. Verify alert resolves\n\n"
            f"## Notes\n\n"
            f"AI-generated remediation was unavailable. Review manually and add steps above.\n"
        )


# ── GitLab Integration ──

def _gitlab_headers() -> dict:
    return {"PRIVATE-TOKEN": GITLAB_TOKEN, "Content-Type": "application/json"}


def create_gitlab_issue(alert: dict, sop_content: str) -> dict | None:
    """Create a GitLab issue with remediation proposal."""
    if not GITLAB_TOKEN or not GITLAB_PROJECT_ID:
        log.warning("GitLab not configured — skipping issue creation")
        return None

    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    alert_name = labels.get("alertname", "unknown")
    severity = labels.get("severity", "warning")

    title = f"[Auto-Detected] {severity.upper()}: {alert_name}"
    description = f"""## Alert Details

| Field | Value |
|-------|-------|
| Alert | `{alert_name}` |
| Severity | `{severity}` |
| Namespace | `{labels.get('namespace', 'N/A')}` |
| Pod | `{labels.get('pod', 'N/A')}` |
| Summary | {annotations.get('summary', annotations.get('description', 'N/A'))} |
| Detected | {datetime.now(timezone.utc).isoformat()} |

## Proposed Remediation SOP

{sop_content}

---

> **To approve**: Add the `approved` label to this issue.
> **To reject**: Add the `rejected` label or close the issue.
> The monitoring agent will automatically execute the remediation once approved.
"""

    import urllib.request
    req = urllib.request.Request(
        f"{GITLAB_API}/projects/{GITLAB_PROJECT_ID}/issues",
        data=json.dumps({
            "title": title,
            "description": description,
            "labels": f"auto-detected,severity:{severity},needs-approval",
        }).encode(),
        headers=_gitlab_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            issue = json.loads(resp.read())
            log.info(f"Created GitLab issue #{issue['iid']}: {title}")
            return issue
    except Exception as e:
        log.error(f"Failed to create GitLab issue: {e}")
        return None


def check_issue_approval(issue_iid: int) -> str:
    """Check if a GitLab issue has been approved/rejected. Returns 'approved'|'rejected'|'pending'."""
    import urllib.request
    req = urllib.request.Request(
        f"{GITLAB_API}/projects/{GITLAB_PROJECT_ID}/issues/{issue_iid}",
        headers=_gitlab_headers(),
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            issue = json.loads(resp.read())
            labels = [l.lower() if isinstance(l, str) else "" for l in issue.get("labels", [])]
            if "approved" in labels:
                return "approved"
            if "rejected" in labels or issue.get("state") == "closed":
                return "rejected"
            return "pending"
    except Exception as e:
        log.error(f"Failed to check issue #{issue_iid}: {e}")
        return "pending"


def close_gitlab_issue(issue_iid: int, comment: str):
    """Close a GitLab issue with a comment."""
    import urllib.request
    # Add comment
    req = urllib.request.Request(
        f"{GITLAB_API}/projects/{GITLAB_PROJECT_ID}/issues/{issue_iid}/notes",
        data=json.dumps({"body": comment}).encode(),
        headers=_gitlab_headers(),
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass
    # Close issue
    req = urllib.request.Request(
        f"{GITLAB_API}/projects/{GITLAB_PROJECT_ID}/issues/{issue_iid}",
        data=json.dumps({"state_event": "close", "add_labels": "auto-remediated"}).encode(),
        headers=_gitlab_headers(),
        method="PUT",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        log.info(f"Closed GitLab issue #{issue_iid}")
    except Exception as e:
        log.error(f"Failed to close issue #{issue_iid}: {e}")


# ── Remediation Execution ──

def execute_remediation_sop(sop_path: str) -> dict:
    """Execute a remediation SOP through the graph orchestrator, with full logging."""
    try:
        sys.path.insert(0, os.path.join(SOP_REPO, "app-sop-agent"))
        sys.path.insert(0, os.path.join(SOP_REPO, "webui", "backend"))
        from sop_graph import build_eval_loop
        from execution_logger import ExecutionLogger

        exec_log = ExecutionLogger([sop_path], eval_mode=True)
        graph = build_eval_loop([sop_path])
        result = None
        steps = []  # human-readable execution log for GitLab

        for event in graph.stream({"task": f"Execute remediation SOP: {sop_path}"}):
            etype = event.get("type", "")

            if etype == "multiagent_node_start":
                node_id = event.get("node_id", "")
                exec_log.node_start(node_id)
                steps.append(f"▶ Starting: {node_id}")

            elif etype == "multiagent_node_stream":
                node_id = event.get("node_id", "")
                inner = event.get("event", {})
                # Tool calls
                tool_use = inner.get("current_tool_use", {})
                if tool_use and tool_use.get("name"):
                    tool_name = tool_use["name"]
                    tool_input = str(tool_use.get("input", ""))[:500]
                    exec_log.tool_call(node_id, tool_name, tool_input)
                    steps.append(f"  🔧 {tool_name}: {tool_input[:100]}")
                # Tool results
                msg = inner.get("message")
                if msg and isinstance(msg, dict):
                    for block in msg.get("content", []):
                        tr = block.get("toolResult") if isinstance(block, dict) else None
                        if tr:
                            content = ""
                            for c in tr.get("content", []):
                                if isinstance(c, dict) and "text" in c:
                                    content += c["text"]
                            is_err = tr.get("status") == "error"
                            exec_log.tool_result(node_id, tr.get("toolUseId", ""), content[:1000], is_err)
                            status_icon = "❌" if is_err else "✅"
                            steps.append(f"  {status_icon} {content[:150]}")
                # Eval scores
                if "eval_score" in inner:
                    es = inner["eval_score"]
                    exec_log.eval_score(node_id, es["evaluator"], es["score"], es["passed"],
                                        "; ".join(r["reason"] for r in es.get("reasons", [])))
                    steps.append(f"  🧪 {es['evaluator']}: {es['score']:.2f} {'✅' if es['passed'] else '❌'}")

            elif etype == "multiagent_node_stop":
                node_id = event.get("node_id", "")
                node_result = event.get("node_result")
                status = "completed"
                if node_result and hasattr(node_result, "status"):
                    status = node_result.status.value if hasattr(node_result.status, "value") else str(node_result.status)
                exec_time = getattr(node_result, "execution_time", 0) if node_result else 0
                token_usage = None
                if node_result:
                    usage = getattr(node_result, "accumulated_usage", None)
                    if usage:
                        token_usage = {k: usage.get(k, 0) for k in ("inputTokens", "outputTokens", "totalTokens")}
                exec_log.node_complete(node_id, "success" if status == "completed" else "failed",
                                       exec_time, token_usage)
                icon = "✅" if status == "completed" else "❌"
                steps.append(f"{icon} {node_id} ({exec_time}ms)")

            elif etype == "multiagent_result":
                result = event.get("result")

        # Save execution log to /app/logs/
        exec_log._save()
        log.info(f"Execution log saved: execution_{exec_log.run_id}.json")

        if result:
            completed = sum(1 for n in (result.node_results or {}).values()
                          if getattr(n, "status", None) and "completed" in str(n.status))
            failed = sum(1 for n in (result.node_results or {}).values()
                        if getattr(n, "status", None) and "failed" in str(n.status))
            return {"status": "completed" if failed == 0 else "failed",
                    "completed": completed, "failed": failed,
                    "run_id": exec_log.run_id, "steps": steps}
        return {"status": "unknown", "run_id": exec_log.run_id, "steps": steps}
    except Exception as e:
        log.error(f"Remediation execution failed: {e}")
        return {"status": "error", "error": str(e), "steps": []}


# ── Main Loop ──

class MonitorState:
    """Tracks seen alerts and pending issues to avoid duplicates."""

    def __init__(self):
        self.seen_fingerprints: dict[str, float] = {}  # fingerprint -> first_seen timestamp
        self.pending_issues: dict[str, dict] = {}  # fingerprint -> {iid, sop_path, created}
        import tempfile
        default_dir = Path(tempfile.gettempdir()) / "remediation-sops"
        self.remediation_dir = Path(os.getenv("REMEDIATION_DIR", str(default_dir)))
        self.remediation_dir.mkdir(parents=True, exist_ok=True)

    def is_new(self, fingerprint: str) -> bool:
        if fingerprint in self.seen_fingerprints:
            return False
        self.seen_fingerprints[fingerprint] = time.time()
        return True

    def cleanup_stale(self, active_fingerprints: set[str]):
        """Remove fingerprints for alerts that are no longer firing."""
        stale = set(self.seen_fingerprints) - active_fingerprints
        for fp in stale:
            del self.seen_fingerprints[fp]
            if fp in self.pending_issues:
                log.info(f"Alert resolved naturally, closing issue #{self.pending_issues[fp]['iid']}")
                close_gitlab_issue(
                    self.pending_issues[fp]["iid"],
                    "✅ Alert resolved naturally — no remediation needed.",
                )
                del self.pending_issues[fp]


def _recover_pending_issues(state: "MonitorState"):
    """On startup, re-discover open auto-detected issues from GitLab."""
    if not GITLAB_TOKEN or not GITLAB_PROJECT_ID:
        return
    import urllib.request
    req = urllib.request.Request(
        f"{GITLAB_API}/projects/{GITLAB_PROJECT_ID}/issues?labels=auto-detected&state=opened&per_page=100",
        headers=_gitlab_headers(),
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            issues = json.loads(resp.read())
            for issue in issues:
                # Use iid as a synthetic fingerprint for recovered issues
                fp = f"recovered-{issue['iid']}"
                state.seen_fingerprints[fp] = time.time()
                state.pending_issues[fp] = {
                    "iid": issue["iid"],
                    "sop_path": "",
                    "created": time.time(),
                }
            if issues:
                log.info(f"Recovered {len(issues)} pending issues from GitLab")
    except Exception as e:
        log.warning(f"Failed to recover pending issues: {e}")


def run_loop():
    """Main monitoring loop."""
    state = MonitorState()
    rules = []  # cached, refreshed every 10 cycles
    cycle = 0

    log.info(f"Day2 Monitor starting — polling every {POLL_INTERVAL}s")
    log.info(f"Watching namespaces: {WATCHED_NAMESPACES}")
    log.info(f"GitLab project: {GITLAB_PROJECT_ID or '(not configured)'}")

    # Create health file for k8s liveness/readiness probes
    Path(tempfile.gettempdir() + "/healthy").touch()

    _recover_pending_issues(state)

    while True:
        try:
            cycle += 1

            # Refresh rules every 10 cycles (~10 min)
            if cycle % 10 == 1:
                rules = fetch_prometheus_rules()
                log.info(f"Loaded {len(rules)} alert rules from Prometheus")

            # 1. Fetch active alerts
            alerts = fetch_active_alerts()
            active_fps = {alert_fingerprint(a) for a in alerts}
            state.cleanup_stale(active_fps)

            # 2. Process new alerts
            for alert in alerts:
                fp = alert_fingerprint(alert)
                if not state.is_new(fp):
                    continue

                alert_name = alert.get("labels", {}).get("alertname", "unknown")
                severity = alert.get("labels", {}).get("severity", "unknown")
                log.info(f"New alert: {severity.upper()} {alert_name} (fp={fp})")

                # Generate remediation SOP
                sop_content = generate_remediation_sop(alert, rules, [])
                sop_filename = f"{alert_name.lower().replace(' ', '-')}.md"
                sop_path = state.remediation_dir / sop_filename
                sop_path.write_text(sop_content)
                log.info(f"Generated remediation SOP: {sop_path}")

                # Create GitLab issue
                issue = create_gitlab_issue(alert, sop_content)
                if issue:
                    state.pending_issues[fp] = {
                        "iid": issue["iid"],
                        "sop_path": str(sop_path),
                        "created": time.time(),
                    }

            # 3. Check pending issues for approval
            for fp, info in list(state.pending_issues.items()):
                age = time.time() - info["created"]
                status = check_issue_approval(info["iid"])

                if status == "approved":
                    log.info(f"Issue #{info['iid']} approved — executing remediation")
                    result = execute_remediation_sop(info["sop_path"])
                    steps_md = "\n".join(f"- `{s}`" for s in result.get("steps", [])[-30:])
                    run_id = result.get("run_id", "")
                    close_gitlab_issue(
                        info["iid"],
                        f"## Remediation Result\n\n"
                        f"Status: **{result['status']}**\n"
                        f"Completed: {result.get('completed', '?')}, "
                        f"Failed: {result.get('failed', '?')}\n"
                        f"Run ID: `{run_id}`\n\n"
                        f"{'✅ Remediation applied successfully.' if result['status'] == 'completed' else '❌ Remediation had failures — manual review needed.'}"
                        f"\n\n<details><summary>Execution Log ({len(result.get('steps', []))} steps)</summary>\n\n"
                        f"{steps_md}\n\n</details>",
                    )
                    del state.pending_issues[fp]

                elif status == "rejected":
                    log.info(f"Issue #{info['iid']} rejected — skipping")
                    del state.pending_issues[fp]

                elif age > APPROVAL_TIMEOUT:
                    log.warning(f"Issue #{info['iid']} timed out after {APPROVAL_TIMEOUT}s")
                    close_gitlab_issue(
                        info["iid"],
                        f"⏰ Approval timed out after {APPROVAL_TIMEOUT // 60} minutes. "
                        f"Re-open and add `approved` label to execute remediation.",
                    )
                    del state.pending_issues[fp]
                    # Remove from seen so alert gets re-detected if still firing
                    state.seen_fingerprints.pop(fp, None)

            # 4. Fetch k8s events (log only, alerts are the primary trigger)
            events = fetch_k8s_events()
            if events:
                log.debug(f"{len(events)} warning events across watched namespaces")

            log.info(
                f"Cycle {cycle}: {len(alerts)} active alerts, "
                f"{len(state.pending_issues)} pending issues, "
                f"{len(state.seen_fingerprints)} tracked"
            )

        except Exception as e:
            log.error(f"Monitor cycle failed: {e}", exc_info=True)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_loop()
