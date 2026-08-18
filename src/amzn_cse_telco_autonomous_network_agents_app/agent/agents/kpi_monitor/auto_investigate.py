# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Auto-investigation for escalating alarm trends.

When trend detection identifies an alarm firing with increasing frequency,
this module generates a targeted investigation SOP and submits it for
execution (respecting approval mode).
"""

import logging
import time

logger = logging.getLogger(__name__)

# Track which alarms we've already triggered investigation for (avoid spam)
_investigated: dict = {}  # alarm_name -> timestamp of last investigation
_INVESTIGATION_COOLDOWN = 3600  # Don't re-investigate same alarm within 1 hour


def maybe_investigate_trend(escalating_alarms: list) -> list:
    """For each escalating alarm, generate and submit an investigation if not recently done.

    Args:
        escalating_alarms: Output from detect_escalating_alarms().

    Returns:
        List of alarm names that had investigations triggered.
    """
    triggered = []
    now = time.time()

    for esc in escalating_alarms:
        alarm_name = esc["alarm"]

        # Cooldown check
        last = _investigated.get(alarm_name, 0)
        if now - last < _INVESTIGATION_COOLDOWN:
            logger.debug("Skipping investigation for %s (cooldown)", alarm_name)
            continue

        logger.info(
            "Triggering auto-investigation for escalating alarm: %s "
            "(last_24h=%d, prev_24h=%d, ratio=%.1f)",
            alarm_name, esc["last_24h"], esc["prev_24h"], esc["ratio"],
        )

        # Build a synthetic alert that represents the trend observation
        trend_alert = {
            "name": f"trend_escalating_{alarm_name}",
            "severity": "warning",
            "source": "trend-detection",
            "service_impact": (
                f"Alarm '{alarm_name}' is firing {esc['ratio']}x more frequently "
                f"({esc['last_24h']} times in last 24h vs {esc['prev_24h']} previously). "
                f"Total in 7 days: {esc['total_7d']}."
            ),
            "probable_cause": (
                f"Possible progressive degradation. Investigate why '{alarm_name}' "
                f"is escalating — check for firmware bugs, config drift, or hardware wear."
            ),
            "value": esc["ratio"],
            "threshold": ">2.0x increase",
        }

        _investigated[alarm_name] = now
        triggered.append(alarm_name)

        # Submit through the standard SOP pipeline
        try:
            from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import _submit_sop
            _submit_sop(trend_alert)
        except Exception as e:
            logger.warning("Failed to submit trend investigation for %s: %s", alarm_name, e)

    return triggered


def clear_investigated() -> None:
    """Clear investigation history (for testing)."""
    _investigated.clear()
