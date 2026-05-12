# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from datetime import datetime, timezone

from app_state import _pending_approvals
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["approvals"])


class ApprovalRequest(BaseModel):
    alarm_name: str
    action: str  # "approve" | "reject"


@router.get("/api/approvals")
def get_approvals():
    return {"pending": list(_pending_approvals.values()), "count": len(_pending_approvals)}


@router.post("/api/approve")
def approve(req: ApprovalRequest):
    if req.alarm_name not in _pending_approvals:
        raise HTTPException(404, f"No pending approval for {req.alarm_name}")
    entry = _pending_approvals.pop(req.alarm_name)
    entry["action"] = req.action
    entry["actioned_at"] = datetime.now(timezone.utc).isoformat()
    return {"status": req.action, "alarm": req.alarm_name, "sop": entry.get("sop")}
