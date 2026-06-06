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
