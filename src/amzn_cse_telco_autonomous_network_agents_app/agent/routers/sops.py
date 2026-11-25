# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
from fnmatch import fnmatch
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["sops"])

# Bedrock-generated SOPs (monitor._generate_sop) and enriched copies
# (monitor._enrich_sop_file) are written here. Only files matching
# GENERATED_SOP_PATTERNS are exposed, so other /tmp content is never listed or served.
GENERATED_SOP_DIRS = [Path("/tmp/generated-sops"), Path("/tmp")]  # nosec B108 — read-only, name-filtered
GENERATED_SOP_PATTERNS = ("remediate-*.md", "*-enriched.md")
GENERATED_PREFIX = "generated/"


def _sop_entry(f: Path, rel: str, phase: str) -> dict:
    content = f.read_text()
    title = content.split("\n")[0].lstrip("# ").strip()
    severity = ""
    for line in content.split("\n")[:5]:
        if "**Severity:**" in line:
            severity = line.split("**Severity:**")[1].strip()
    return {"path": rel, "title": title, "severity": severity, "phase": phase}


def _is_generated_name(name: str) -> bool:
    return any(fnmatch(name, pattern) for pattern in GENERATED_SOP_PATTERNS)


def _generated_files() -> dict[str, Path]:
    """Map filename -> file for generated SOPs; earlier dirs win on a name clash."""
    found: dict[str, Path] = {}
    for d in GENERATED_SOP_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.name in found or not _is_generated_name(f.name):
                continue
            resolved = _resolve_generated(f.name, d)
            if resolved is not None:
                found[f.name] = resolved
    return found


def _resolve_generated(name: str, d: Path) -> Path | None:
    """Return the file only if it is a regular file directly inside d after symlink resolution."""
    root = d.resolve()
    f = (d / name).resolve()
    if f.parent != root or not f.is_file() or not _is_generated_name(f.name):
        return None
    return f


def generated_view_path(sop_path: str) -> str:
    """Path under /api/sops/ that serves sop_path, or "" if it is not viewable there."""
    if not sop_path:
        return ""
    p = Path(sop_path)
    if _is_generated_name(p.name) and any(p.parent == d for d in GENERATED_SOP_DIRS):
        return GENERATED_PREFIX + p.name
    sop_dir = Path(os.getenv("SOP_REPO", "/app")) / "sops"
    if p.is_absolute() and p.is_relative_to(sop_dir):
        return str(p.relative_to(sop_dir))
    return "" if p.is_absolute() else sop_path


def _read_or_404(f: Path, path: str) -> str:
    try:
        return f.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        raise HTTPException(404, f"SOP not found: {path}") from exc


@router.get("/api/sops")
def list_sops():
    sop_dir = Path(os.getenv("SOP_REPO", "/app")) / "sops"
    sops = []
    for f in sorted(sop_dir.rglob("*.md")):
        # TEMPLATE.md is scaffolding; sops/archive/ holds retired SOPs kept for
        # reference (see sops/archive/README.md) — neither is operator-facing.
        if f.name == "TEMPLATE.md" or "archive" in f.relative_to(sop_dir).parts:
            continue
        rel = str(f.relative_to(sop_dir))
        sops.append(_sop_entry(f, rel, rel.split("/")[0]))
    generated = _generated_files()
    for name, f in generated.items():
        # The enrich step writes <stem>-enriched.md next to the draft and the
        # decision uses the enriched copy, so list only that one. The draft
        # is still served by its own path.
        if not name.endswith("-enriched.md") and f"{name[:-3]}-enriched.md" in generated:
            continue
        try:
            entry = _sop_entry(f, GENERATED_PREFIX + name, "generated")
        except (OSError, UnicodeDecodeError):
            continue  # removed, unreadable or not UTF-8
        entry["generated"] = True
        sops.append(entry)
    return {"sops": sops, "count": len(sops)}


@router.get("/api/sops/{path:path}")
def get_sop(path: str):
    if ".." in Path(path).parts or "\\" in path:
        raise HTTPException(400, f"Invalid SOP path: {path}")
    sop_dir = Path(os.getenv("SOP_REPO", "/app")) / "sops"
    sop_file = (sop_dir / path).resolve()
    if sop_file.is_relative_to(sop_dir.resolve()) and sop_file.is_file():
        return {"path": path, "content": _read_or_404(sop_file, path)}

    name = path.removeprefix(GENERATED_PREFIX)
    if "/" in name and path.startswith(GENERATED_PREFIX):
        raise HTTPException(400, f"Invalid SOP path: {path}")
    if "/" not in name and _is_generated_name(name):
        for d in GENERATED_SOP_DIRS:
            f = _resolve_generated(name, d)
            if f is not None:
                content = _read_or_404(f, path)
                return {"path": GENERATED_PREFIX + name, "content": content, "generated": True}
    raise HTTPException(404, f"SOP not found: {path}")
