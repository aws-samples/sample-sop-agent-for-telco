# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Quirk database loader — matches BMCProfile against vendor YAML quirk files."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_QUIRKS_DIR = Path(__file__).parent
_cache: list[dict] | None = None


def _load_all() -> list[dict]:
    """Load all YAML quirk files from the quirks directory. Cached after first call."""
    global _cache
    if _cache is not None:
        return _cache

    quirks = []
    for path in sorted(_QUIRKS_DIR.glob("*.yaml")):
        if path.name.startswith("_"):
            continue  # _default.yaml loaded separately
        try:
            data = yaml.safe_load(path.read_text())
            if data:
                data["_source"] = path.name
                quirks.append(data)
        except Exception as e:
            logger.warning("Failed to load quirk file %s: %s", path, e)

    _cache = quirks
    logger.info("Loaded %d quirk files from %s", len(quirks), _QUIRKS_DIR)
    return quirks


def _load_default() -> dict:
    """Load the _default.yaml fallback quirk."""
    default_path = _QUIRKS_DIR / "_default.yaml"
    if default_path.exists():
        data = yaml.safe_load(default_path.read_text()) or {}
        data["_source"] = "_default.yaml"
        return data
    return {"_source": "_default.yaml", "strategies": []}


def match(profile) -> dict:
    """Match a BMCProfile against the quirk database.

    Args:
        profile: BMCProfile dataclass from bmc_profiler.

    Returns:
        The best-matching quirk dict, or _default.yaml if no match.
    """
    quirks = _load_all()

    for quirk in quirks:
        match_rules = quirk.get("match", {})
        model_pattern = match_rules.get("model_pattern", "")
        firmware_pattern = match_rules.get("firmware_pattern", "")

        # Model must match (required)
        if model_pattern:
            if not re.search(model_pattern, profile.model, re.IGNORECASE):
                continue
        else:
            continue  # No model pattern = skip this quirk

        # Firmware match is optional (if specified, must match)
        if firmware_pattern:
            if not re.search(firmware_pattern, profile.firmware_version, re.IGNORECASE):
                continue

        logger.info(
            "Quirk matched: %s → %s",
            profile.model,
            quirk.get("_source", "unknown"),
        )
        return quirk

    logger.info("No quirk match for %s — using default", profile.model)
    return _load_default()


def invalidate_cache() -> None:
    """Clear the quirk cache (for testing)."""
    global _cache
    _cache = None
