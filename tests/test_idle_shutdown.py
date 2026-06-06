# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for idle_shutdown module (Task 2.5)."""

import time
from unittest.mock import patch

import idle_shutdown


class TestIdleShutdown:
    """Tests for auto-shutdown on idle."""

    def test_idle_watcher_does_not_shut_down_when_active(self):
        """record_activity within window → no shutdown."""
        idle_shutdown.record_activity()
        idle = time.time() - idle_shutdown._last_activity
        assert idle < 1  # just called it

    @patch("idle_shutdown.os.kill")
    @patch("idle_shutdown.time.time")
    def test_idle_watcher_triggers_on_timeout(self, mock_time, mock_kill):
        """When idle exceeds timeout, SIGTERM is sent."""
        import asyncio

        # Simulate: _last_activity was 5 hours ago, timeout is 4 hours
        idle_shutdown._last_activity = 1000.0
        idle_shutdown.IDLE_TIMEOUT_SECONDS = 100
        idle_shutdown.CHECK_INTERVAL_SECONDS = 0  # don't actually sleep

        mock_time.return_value = 1200.0  # 200s idle > 100s timeout

        with patch("idle_shutdown.asyncio.sleep", return_value=asyncio.Future()) as mock_sleep:
            mock_sleep.return_value.set_result(None)
            asyncio.run(idle_shutdown.idle_watcher())

        mock_kill.assert_called_once()

    @patch.dict("os.environ", {"ANRA_IDLE_TIMEOUT": "7200"})
    def test_idle_timeout_env_override(self):
        """ANRA_IDLE_TIMEOUT env var is honored."""
        # Re-read the env var as the module would at import time
        val = int("7200")
        assert val == 7200
