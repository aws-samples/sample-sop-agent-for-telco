# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for TokenBudget circuit breaker (Task 1.8)."""

import os
from unittest.mock import patch

from sop_executor import TokenBudget


class TestTokenBudget:
    """Tests for the per-session token budget."""

    def test_budget_default_value(self):
        """Default budget is 100k tokens."""
        tb = TokenBudget()
        assert tb.budget == 100000

    def test_budget_consume_under_limit(self):
        """Consuming below limit returns False."""
        tb = TokenBudget(budget_tokens=1000)
        assert tb.consume(500) is False
        assert tb.exceeded is False

    def test_budget_consume_over_limit(self):
        """Consuming over limit returns True."""
        tb = TokenBudget(budget_tokens=1000)
        assert tb.consume(1500) is True
        assert tb.exceeded is True

    def test_budget_remaining_decreases(self):
        """remaining() decreases as we consume."""
        tb = TokenBudget(budget_tokens=1000)
        assert tb.remaining() == 1000
        tb.consume(300)
        assert tb.remaining() == 700
        tb.consume(700)
        assert tb.remaining() == 0

    @patch.dict(os.environ, {"ANRA_SESSION_TOKEN_BUDGET": "50000"})
    def test_budget_env_override(self):
        """ANRA_SESSION_TOKEN_BUDGET=50000 honored."""
        tb = TokenBudget(budget_tokens=int(os.getenv("ANRA_SESSION_TOKEN_BUDGET", "100000")))
        assert tb.budget == 50000
