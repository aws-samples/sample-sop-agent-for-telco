# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Alarm trend detection — identifies escalating alarm patterns over time."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List

logger = logging.getLogger(__name__)

# In-memory alarm history: alarm_name -> list of timestamps
_alarm_history: dict = defaultdict(list)

# Retention period
_RETENTION_DAYS = 7

# Minimum occurrences before trend analysis kicks in
_MIN_OCCURRENCES = 5

# Escalation threshold: last_24h must be this multiple of prev_24h
_ESCALATION_MULTIPLIER = 2


def record_alarm(alarm_name: str, timestamp: datetime = None) -> None:
    """Record an alarm firing for trend analysis.

    Args:
        alarm_name: Name of the alarm that fired.
        timestamp: When it fired (defaults to now).
    """
    ts = timestamp or datetime.utcnow()
    _alarm_history[alarm_name].append(ts)
    # Prune old entries
    cutoff = datetime.utcnow() - timedelta(days=_RETENTION_DAYS)
    _alarm_history[alarm_name] = [t for t in _alarm_history[alarm_name] if t > cutoff]


def detect_escalating_alarms() -> List[dict]:
    """Find alarms that are firing more frequently over time.

    Compares the last 24h count vs the previous 24h count. An alarm is
    escalating if it fired at least 2x more in the recent window.

    Returns:
        List of dicts with alarm name, counts, and trend info.
    """
    escalating = []
    now = datetime.utcnow()
    for name, times in _alarm_history.items():
        if len(times) < _MIN_OCCURRENCES:
            continue
        last_24h = sum(1 for t in times if t > now - timedelta(hours=24))
        prev_24h = sum(1 for t in times if now - timedelta(hours=48) < t <= now - timedelta(hours=24))
        if prev_24h > 0 and last_24h >= prev_24h * _ESCALATION_MULTIPLIER and last_24h >= _MIN_OCCURRENCES:
            escalating.append({
                "alarm": name,
                "last_24h": last_24h,
                "prev_24h": prev_24h,
                "ratio": round(last_24h / prev_24h, 1),
                "trend": "escalating",
                "total_7d": len(times),
            })
    return escalating


def get_alarm_frequency(alarm_name: str) -> dict:
    """Get frequency stats for a specific alarm.

    Args:
        alarm_name: Name of the alarm.

    Returns:
        Dict with occurrence counts per time window.
    """
    times = _alarm_history.get(alarm_name, [])
    now = datetime.utcnow()
    return {
        "alarm": alarm_name,
        "last_1h": sum(1 for t in times if t > now - timedelta(hours=1)),
        "last_24h": sum(1 for t in times if t > now - timedelta(hours=24)),
        "last_7d": len(times),
    }


def clear_history() -> None:
    """Clear all alarm history (for testing)."""
    _alarm_history.clear()
