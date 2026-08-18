# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["sops"])


@router.get("/api/sops")
def list_sops():
    sop_dir = Path(os.getenv("SOP_REPO", "/app")) / "sops"
    sops = []
    for f in sorted(sop_dir.rglob("*.md")):
        if f.name == "TEMPLATE.md":
            continue
        rel = str(f.relative_to(sop_dir))
        content = f.read_text()
        title = content.split("\n")[0].lstrip("# ").strip()
        severity = ""
        for line in content.split("\n")[:5]:
            if "**Severity:**" in line:
                severity = line.split("**Severity:**")[1].strip()
        sops.append({"path": rel, "title": title, "severity": severity, "phase": rel.split("/")[0]})
    return {"sops": sops, "count": len(sops)}


@router.get("/api/sops/{path:path}")
def get_sop(path: str):
    sop_file = Path(os.getenv("SOP_REPO", "/app")) / "sops" / path
    if not sop_file.exists():
        raise HTTPException(404, f"SOP not found: {path}")
    return {"path": path, "content": sop_file.read_text()}
