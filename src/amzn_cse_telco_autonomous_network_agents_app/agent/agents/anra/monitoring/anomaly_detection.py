# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Statistical anomaly detection for ANRA.

Flags InfluxDB metrics that deviate >3 sigma from a rolling baseline, then asks
Bedrock (rate-limited) to classify the unknown ones into real alarms. Metrics
that already have explicit threshold rules are suppressed here so we don't
double-alarm on them.

This is the canonical version, ported from monitor.py's inline copy (which was
the one run by the ANRA loop). It keeps two behaviors the earlier
kpi_monitor/anomaly.py twin had dropped: the known-fields suppression gate and
the per-cycle cap on how many anomalies are sent to Bedrock.
"""

import json
import logging
import os
import time

from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import ModelTier

# Log under the shared "monitor" logger, like the sibling kpi_monitor / correlator
# modules, so any handler or level config keyed on that name still catches these
# DYNAMIC ALARM records.
log = logging.getLogger("monitor")

_baselines: dict = {}  # field -> {count, sum, sum_sq}
_bedrock_last_classify: float = 0
BEDROCK_CLASSIFY_COOLDOWN = int(os.getenv("BEDROCK_CLASSIFY_COOLDOWN", "300"))  # 5 min

# Fields that already have explicit threshold rules; anomalies on these are
# handled by the threshold path, so we don't also route them through Bedrock.
_KNOWN_THRESHOLD_FIELDS = {
    "cells_0_cell_metrics_error_indication_count",
    "cells_0_ue_list_0_dl_brate",
    "du_du_high_mac_dl_0_cpu_usage_percent",
    "du_du_high_mac_dl_0_max_latency_us",
    "cells_0_cell_metrics_late_dl_harqs",
}

# Cap on how many unknown anomalies we send to Bedrock per cycle (cost control).
_MAX_ANOMALIES_PER_CLASSIFY = 10


def evaluate_dynamic_anomalies():
    """Statistical anomaly detection across all InfluxDB metrics.

    Flags metrics that deviate >3 sigma from a rolling baseline. Unknown
    anomalies (those without an explicit threshold rule) are classified by
    Bedrock, rate-limited to one call per BEDROCK_CLASSIFY_COOLDOWN.
    """
    # Lazy import: importing kpi_monitor.influx_source at module top would pull
    # in kpi_monitor/__init__, which re-exports from this module -> import cycle.
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.influx_source import (
        query_influx_all,
    )

    all_metrics = query_influx_all()
    if not all_metrics:
        return []

    anomalies = []
    for field, value in all_metrics.items():
        if value is None or not isinstance(value, (int, float)):
            continue

        b = _baselines.setdefault(field, {"count": 0, "sum": 0.0, "sum_sq": 0.0})
        b["count"] += 1
        b["sum"] += value
        b["sum_sq"] += value * value

        if b["count"] < 10:
            continue

        mean = b["sum"] / b["count"]
        variance = max((b["sum_sq"] / b["count"]) - (mean * mean), 0)
        std = max(variance**0.5, 0.001)
        z_score = abs(value - mean) / std

        if z_score > 3:
            anomalies.append(
                {
                    "field": field,
                    "value": round(value, 2),
                    "mean": round(mean, 2),
                    "std": round(std, 2),
                    "z": round(z_score, 1),
                }
            )

    if not anomalies:
        return []

    # Skip anomalies on metrics that already have an explicit threshold rule --
    # those are handled by the threshold path, so classifying them here would
    # double-alarm.
    unknown = [a for a in anomalies if a["field"] not in _KNOWN_THRESHOLD_FIELDS]

    if not unknown:
        return []

    # Rate-limit Bedrock calls
    global _bedrock_last_classify
    if time.time() - _bedrock_last_classify < BEDROCK_CLASSIFY_COOLDOWN:
        return []

    _bedrock_last_classify = time.time()
    return _classify_anomalies(unknown[:_MAX_ANOMALIES_PER_CLASSIFY])


def _classify_anomalies(anomalies):
    """Ask Bedrock to classify unknown metric anomalies into alarms."""
    try:
        from strands import Agent

        prompt = f"""You are a 5G RAN expert analyzing metric anomalies from an srsRAN gNodeB.

CRITICAL CONTEXT: This is a TESTMODE deployment (ru_dummy, no real radio hardware).
In testmode, statistical variations in per-UE radio metrics are EXPECTED and normal:
- PUSCH/PUCCH SNR fluctuations - no real RF channel
- HARQ delay variations - simulated scheduling
- CQI/MCS changes - no real channel quality feedback
- Per-UE throughput variations - simulated traffic
- Error indication counts - FAPI timing warnings are normal

Only classify as a REAL alarm if:
- Pod crash or restart (not a radio metric)
- Service connectivity lost (PFCP, SCTP, SBI)
- Hardware failure (thermal, PSU, memory)
- ALL UEs affected simultaneously (not just 1-2 UEs)
- Metric drops to exactly 0 from a non-zero baseline

These metrics deviated >3 sigma from baseline:

{json.dumps(anomalies, indent=2)}

Return a JSON array of REAL problems only: [{{"name": "alarm_name", "severity": "critical|warning",
  "field": "metric_field", "probable_cause": "...", "service_impact": "...",
  "closest_sop": "sop_name_or_null"}}]

If all anomalies are normal testmode variations, return: []"""

        from amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver import (
            build_model,
        )

        model = build_model(ModelTier.FAST)
        agent = Agent(model=model, system_prompt="You classify 5G network anomalies.")
        result = str(agent(prompt))

        # Parse JSON from response
        import re

        match = re.search(r"\[.*\]", result, re.DOTALL)
        if not match:
            return []
        classified = json.loads(match.group())

        alerts = []
        for c in classified:
            if not c.get("name"):
                continue
            alerts.append(
                {
                    "name": c["name"],
                    "severity": c.get("severity", "warning"),
                    "service_impact": c.get("service_impact", ""),
                    "probable_cause": c.get("probable_cause", ""),
                    "sop": c.get("closest_sop", ""),
                    "source": "dynamic-anomaly",
                    "value": next((a["value"] for a in anomalies if a["field"] == c.get("field")), 0),
                }
            )
            log.info(f"DYNAMIC ALARM: {c['name']} ({c.get('severity')}) - {c.get('probable_cause', '')[:80]}")
        return alerts
    except Exception as e:
        log.debug(f"Anomaly classification failed: {e}")
        return []


def reset_baselines():
    """Reset rolling baselines -- useful for testing."""
    _baselines.clear()
