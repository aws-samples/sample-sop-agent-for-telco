# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""SOP content analysis: metadata parsing, dependency resolution, model tiering.

Pure functions extracted from sop_graph.py. Everything here is derived from SOP
markdown content at runtime -- no hardcoded SOP names or stages, no strands or
AWS dependencies. Kept together because they form the read-only "understand the
SOPs" layer the graph builder consumes before wiring any agents.
"""

from __future__ import annotations

import re
from pathlib import Path

# Model tiers select_model can return, cheapest to most capable. These are the
# SOP-complexity tier labels (distinct from framework ModelTier FAST/SMART);
# named here so callers and tests reference symbols, not scattered literals.
MODEL_HAIKU = "haiku"
MODEL_SONNET = "sonnet"
MODEL_OPUS = "opus4.6"

# Complexity thresholds that gate the tier bump. A SOP with many bash blocks or
# many lines is harder to execute reliably, so it earns a stronger model:
#   >= OPUS_*  -> opus (large / script-heavy runbooks)
#   >= SONNET_* -> sonnet (mid-size)
#   else       -> the caller's default tier
# The bash-block and line cutoffs are independent (either one trips the bump).
_OPUS_BASH_BLOCKS = 20
_OPUS_LINES = 300
_SONNET_BASH_BLOCKS = 10
_SONNET_LINES = 150


def parse_sop_metadata(sop_path: str) -> dict:
    """Extract metadata from SOP content: stage, dependencies, complexity.

    Returns:
        {
            "stem": "05-validation",
            "stage": 5,              # from "Stage: 5 of 8"
            "dep_stages": [4],       # from "Stages 1-4 complete"
            "dep_files": ["02-app-config"],  # from SOP filename refs
            "bash_blocks": 18,
            "lines": 176,
        }
    """
    try:
        content = Path(sop_path).read_text()
    except (FileNotFoundError, OSError):
        # Keep this shape identical to the success-path return below so callers
        # can rely on every key (e.g. sleep_seconds) regardless of read outcome.
        return {
            "stem": Path(sop_path).stem,
            "stage": None,
            "dep_stages": [],
            "dep_files": [],
            "bash_blocks": 0,
            "lines": 0,
            "sleep_seconds": 0,
        }

    stem = Path(sop_path).stem
    lines = content.split("\n")
    bash_blocks = len(re.findall(r"```bash", content))

    # Parse stage number: "Stage: 5 of 8" or "Stage: 1 (Infrastructure)"
    stage = None
    m = re.search(r"\*\*Stage:\*\*\s*(\d+)", content)
    if m:
        stage = int(m.group(1))

    # Parse prerequisite dependencies
    dep_stages = set()
    dep_files = set()

    # Find prerequisites section
    prereq_match = re.search(r"## Prerequisites?\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
    prereq_text = prereq_match.group(1) if prereq_match else ""

    # "Stages 1-4 complete" → depends on stages 1,2,3,4
    for m in re.finditer(r"[Ss]tages?\s+(\d+)[-–](\d+)\s+complete", prereq_text):
        for s in range(int(m.group(1)), int(m.group(2)) + 1):
            dep_stages.add(s)

    # "Stage 3 complete" → depends on stage 3
    for m in re.finditer(r"[Ss]tage\s+(\d+)\s+complete", prereq_text):
        dep_stages.add(int(m.group(1)))

    # SOP filename references in prerequisites: "02-app-config.md" or "`05-validation.md`"
    for m in re.finditer(r"`?(\d{2}-[\w-]+)\.md`?", prereq_text):
        dep_files.add(m.group(1))

    return {
        "stem": stem,
        "stage": stage,
        "dep_stages": sorted(dep_stages),
        "dep_files": sorted(dep_files),
        "bash_blocks": bash_blocks,
        "lines": len(lines),
        "sleep_seconds": sum(int(m.group(1)) for m in re.finditer(r"sleep\s+(\d+)", content)),
    }


def resolve_dependencies(sop_metas: list[dict]) -> list[tuple[str, str]]:
    """Resolve SOP dependencies into (from_stem, to_stem) edges.

    Uses three strategies (in priority order):
    1. Explicit stage references: "Stage 3 complete" or "Stages 1-4 complete"
    2. File references: "02-app-config.md" in prerequisites
    3. Implicit stage chain: stage N depends on stage N-1 (if no explicit deps found)
    """
    # Build stage→stem lookup
    stage_to_stem = {}
    for meta in sop_metas:
        if meta["stage"] is not None:
            stage_to_stem[meta["stage"]] = meta["stem"]

    stem_set = {m["stem"] for m in sop_metas}
    edges = []
    has_explicit_deps = set()

    for meta in sop_metas:
        # Stage-based deps
        for dep_stage in meta["dep_stages"]:
            dep_stem = stage_to_stem.get(dep_stage)
            if dep_stem and dep_stem in stem_set and dep_stem != meta["stem"]:
                edges.append((dep_stem, meta["stem"]))
                has_explicit_deps.add(meta["stem"])

        # File-based deps
        for dep_file in meta["dep_files"]:
            if dep_file in stem_set and dep_file != meta["stem"]:
                edges.append((dep_file, meta["stem"]))
                has_explicit_deps.add(meta["stem"])

    # Implicit chain: stage N depends on stage N-1 (when no explicit deps found)
    for meta in sop_metas:
        if meta["stem"] in has_explicit_deps:
            continue
        if meta["stage"] is not None and meta["stage"] > 1:
            prev_stem = stage_to_stem.get(meta["stage"] - 1)
            if prev_stem and prev_stem in stem_set:
                edges.append((prev_stem, meta["stem"]))

    # Deduplicate
    return list(set(edges))


def select_model(meta: dict, default: str = MODEL_HAIKU) -> str:
    """Select a model tier from SOP complexity metrics (bash blocks + line count).

    Returns the strongest tier whose threshold the SOP trips, else ``default``.
    """
    if meta["bash_blocks"] >= _OPUS_BASH_BLOCKS or meta["lines"] >= _OPUS_LINES:
        return MODEL_OPUS
    if meta["bash_blocks"] >= _SONNET_BASH_BLOCKS or meta["lines"] >= _SONNET_LINES:
        return MODEL_SONNET
    return default
