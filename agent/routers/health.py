# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/api/report-issue")
async def report_issue(req: dict):
    """Forward an issue report to telemetry."""
    try:
        from telemetry import emit

        emit(
            "issue_reported",
            description_length=len(req.get("description", "")),
            description=req.get("description", "")[:500],
        )
    except Exception:
        pass
    return {"status": "received", "message": "Thanks — report logged"}


@router.get("/api/bootstrap-status")
def bootstrap_status():
    """Return bootstrap progress from the status file on the jump host."""
    import json
    from pathlib import Path

    status_file = Path("/var/lib/anra/status.json")
    if not status_file.exists():
        return {"phase": "unknown", "message": "Status file not yet created"}
    try:
        data = json.loads(status_file.read_text())
        # Mark stale if > 1h old
        from datetime import datetime

        current_at = data.get("current_at", "")
        if current_at:
            ts = datetime.fromisoformat(current_at)
            age = (datetime.now(ts.tzinfo) - ts).total_seconds()
            if age > 3600:
                data["stale"] = True
        return data
    except Exception:
        return {"phase": "error", "message": "Could not read status file"}
