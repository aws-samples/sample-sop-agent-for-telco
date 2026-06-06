# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for idle_shutdown module (Task 2.5)."""

import asyncio
import time
from unittest.mock import patch, AsyncMock

import idle_shutdown


class TestIdleShutdown:
    """Tests for auto-shutdown on idle."""

    def test_idle_watcher_does_not_shut_down_when_active(self):
        """record_activity within window → no shutdown."""
        idle_shutdown.record_activity()
        idle = time.time() - idle_shutdown._last_activity
        assert idle < 1

    @patch("idle_shutdown.os.kill")
    def test_idle_watcher_triggers_on_timeout(self, mock_kill):
        """When idle exceeds timeout, SIGTERM is sent."""
        old_last = idle_shutdown._last_activity
        old_timeout = idle_shutdown.IDLE_TIMEOUT_SECONDS
        old_interval = idle_shutdown.CHECK_INTERVAL_SECONDS

        idle_shutdown._last_activity = time.time() - 200
        idle_shutdown.IDLE_TIMEOUT_SECONDS = 100
        idle_shutdown.CHECK_INTERVAL_SECONDS = 0

        try:
            with patch("idle_shutdown.asyncio.sleep", new_callable=AsyncMock):
                asyncio.run(idle_shutdown.idle_watcher())
        finally:
            idle_shutdown._last_activity = old_last
            idle_shutdown.IDLE_TIMEOUT_SECONDS = old_timeout
            idle_shutdown.CHECK_INTERVAL_SECONDS = old_interval

        mock_kill.assert_called_once()
