"""Lambda: Create Taskei ticket on CI failure.

Triggered by SNS message from GitHub Actions CI pipeline.
Creates a task in the CSE AI initiatives Taskei room.
"""

import json
import os
import urllib.request

TASKEI_ROOM_ID = os.environ.get("TASKEI_ROOM_ID", "6849cc35-25d9-45c8-a9fb-0ea1cfc03e12")
TASKEI_API_URL = os.environ.get("TASKEI_API_URL", "https://taskei.amazon.dev/api/v1")
ASSIGNEE = os.environ.get("DEFAULT_ASSIGNEE", "awaizkh")


def handler(event, context):
    """Process SNS event and create Taskei ticket."""
    for record in event.get("Records", []):
        message = json.loads(record["Sns"]["Message"])
        create_ticket(message)
    return {"statusCode": 200}


def create_ticket(failure):
    """Create a Taskei task from CI failure data."""
    repo = failure.get("repository", "sample-sop-agent-for-telco")
    workflow = failure.get("workflow", "CI")
    run_url = failure.get("run_url", "")
    jobs_failed = failure.get("jobs_failed", [])
    ref = failure.get("ref", "unknown")
    sha = failure.get("sha", "unknown")[:7]
    actor = failure.get("actor", "unknown")

    title = f"[CI FAILURE] {workflow} — {', '.join(jobs_failed)} ({ref}@{sha})"
    description = f"""## CI Pipeline Failure

**Repository:** {repo}
**Workflow:** {workflow}
**Ref:** `{ref}`
**Commit:** `{sha}`
**Triggered by:** {actor}
**Run:** {run_url}

### Failed Jobs
{chr(10).join(f'- ❌ {job}' for job in jobs_failed)}

### Action Required
1. Click the run URL above to see full logs
2. Fix the failing job(s)
3. Push fix or re-run workflow
4. Close this ticket once green
"""

    task_payload = {
        "name": title,
        "description": description,
        "roomId": TASKEI_ROOM_ID,
        "assignee": ASSIGNEE,
        "priority": "High" if "security" in jobs_failed else "Medium",
        "tags": ["ci-failure", "automated"],
    }

    # Log for debugging (CloudWatch)
    print(f"Creating ticket: {title}")
    print(f"Payload: {json.dumps(task_payload, indent=2)}")

    # POST to Taskei API
    req = urllib.request.Request(
        f"{TASKEI_API_URL}/rooms/{TASKEI_ROOM_ID}/tasks",
        data=json.dumps(task_payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            print(f"Ticket created: {result.get('id', 'unknown')}")
            return result
    except Exception as e:
        # Fallback: log the failure details so ticket can be created manually
        print(f"Failed to create Taskei ticket (expected if no corp VPC): {e}")
        print(f"MANUAL TICKET NEEDED: {title}")
        print(f"Description: {description}")
        return None
