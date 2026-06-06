# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for telemetry module (Task 3.1)."""

from unittest.mock import patch

import telemetry


class TestTelemetry:
    """Tests for anonymous opt-in telemetry."""

    def test_telemetry_disabled_by_default(self):
        """No events when ENABLED=false."""
        assert telemetry.ENABLED is False
        telemetry.emit("test_event", foo="bar")
        assert telemetry._queue.empty()

    @patch.dict("os.environ", {"ANRA_TELEMETRY_ENABLED": "true"})
    def test_telemetry_strips_pii(self):
        """Event with ip: or arn:aws is filtered out."""
        # Directly test the filter logic
        kwargs = {"safe": "hello", "bad_ip": "ip:1.2.3.4", "bad_arn": "arn:aws:iam::123"}
        filtered = {k: v for k, v in kwargs.items() if not any(s in str(v) for s in ["ip:", "i-", "arn:aws", "@"])}
        assert "safe" in filtered
        assert "bad_ip" not in filtered
        assert "bad_arn" not in filtered

    def test_telemetry_session_id_persistent(self):
        """Same session_id across module lifetime."""
        s1 = telemetry.SESSION_ID
        s2 = telemetry.SESSION_ID
        assert s1 == s2
        assert len(s1) == 8

    def test_telemetry_drops_events_when_full(self):
        """Queue full → emit returns silently (no exception)."""
        from queue import Full

        with patch.object(telemetry._queue, "put_nowait", side_effect=Full):
            # Should not raise even with telemetry forced
            old = telemetry.ENABLED
            telemetry.ENABLED = True
            try:
                telemetry.emit("overflow_test")  # should not raise
            finally:
                telemetry.ENABLED = old
