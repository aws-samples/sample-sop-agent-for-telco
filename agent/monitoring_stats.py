# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Monitoring coverage payload for /api/monitoring-stats and chat context."""

import logging

from cluster import check_source_status

log = logging.getLogger(__name__)


def build_monitoring_stats_payload() -> dict:
    """Build monitoring stats; used by /api/monitoring-stats and chat context."""
    detail_parts: list[str] = []
    tier1_rules = 0
    alarm_definitions = 0
    tier2_metrics = 0
    tier2_ready = 0
    tier2_pct = 0
    tier3_cooldown = 300
    sources: dict[str, bool] = {}

    try:
        from config import load_config

        cfg = load_config()
        if cfg.alarms:
            tier1_rules = len(cfg.alarms)
    except Exception as e:
        log.warning("monitoring-stats: config: %s", e)
        detail_parts.append("config")

    try:
        from monitor import BEDROCK_CLASSIFY_COOLDOWN, _alarm_ref, _baselines

        alarm_definitions = len(_alarm_ref) if _alarm_ref else 0
        if tier1_rules == 0:
            tier1_rules = alarm_definitions
        baseline_count = len(_baselines)
        tier2_metrics = baseline_count
        tier2_ready = sum(1 for b in _baselines.values() if b.get("count", 0) >= 10)
        tier2_pct = round(tier2_ready / max(baseline_count, 1) * 100)
        tier3_cooldown = BEDROCK_CLASSIFY_COOLDOWN
    except Exception as e:
        log.warning("monitoring-stats: monitor baselines: %s", e)
        detail_parts.append("baselines")

    try:
        sources = check_source_status()
    except Exception as e:
        log.warning("monitoring-stats: sources: %s", e)
        detail_parts.append("sources")

    status = "ok" if not detail_parts else "degraded"
    detail = ", ".join(detail_parts) if detail_parts else None
    return {
        "status": status,
        "detail": detail,
        "tier1_rules": tier1_rules,
        "tier2_metrics": tier2_metrics,
        "tier2_ready": tier2_ready,
        "tier2_pct": tier2_pct,
        "tier3_cooldown": tier3_cooldown,
        "alarm_definitions": alarm_definitions,
        "sources": sources,
    }
