# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Safety guardrails — protected namespaces, blocked commands, rate limits."""

import logging
import re
import time

log = logging.getLogger("monitor")


def load_guardrails():
    """Load guardrails from config."""
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config
        cfg = load_config()
        return cfg.guardrails
    except Exception:
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import GuardrailsConfig
        return GuardrailsConfig()


def is_command_blocked(command: str, guardrails=None) -> bool:
    """Check if a command matches any blocked pattern."""
    if guardrails is None:
        guardrails = load_guardrails()
    for pattern in guardrails.blocked_commands:
        if re.search(pattern, command, re.IGNORECASE):
            return True
    return False


def is_namespace_protected(namespace: str, guardrails=None) -> bool:
    """Check if a namespace is protected."""
    if guardrails is None:
        guardrails = load_guardrails()
    return namespace in guardrails.protected_namespaces


class RateLimiter:
    """Rate limiter for dynamic SOP execution."""

    def __init__(self, max_per_hour: int = 3):
        self.max_per_hour = max_per_hour
        self._count = 0
        self._reset_time = time.time()

    def allow(self) -> bool:
        now = time.time()
        if now - self._reset_time > 3600:
            self._count = 0
            self._reset_time = now
        if self._count >= self.max_per_hour:
            return False
        self._count += 1
        return True

    @property
    def remaining(self) -> int:
        return max(0, self.max_per_hour - self._count)
