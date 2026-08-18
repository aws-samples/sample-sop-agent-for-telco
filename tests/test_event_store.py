# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for event_store.py — ring buffer and event recording."""
import time


import amzn_cse_telco_autonomous_network_agents_app.agent.event_store as event_store

class TestRecord:
    def setup_method(self):
        event_store._buffer.clear()

    def test_record_adds_to_buffer(self):
        event_store.record({"name": "test_alarm", "severity": "critical", "source": "influxdb"})
        assert len(event_store._buffer) == 1
        assert event_store._buffer[0]["name"] == "test_alarm"

    def test_record_includes_timestamp(self):
        event_store.record({"name": "a", "severity": "warning"})
        assert "ts" in event_store._buffer[0]
        assert event_store._buffer[0]["ts"] <= time.time()

    def test_record_enriches_from_alarm_ref(self):
        ref = {"test_alarm": {"layer": 3, "nf_scope": "per-node"}}
        event_store.record({"name": "test_alarm", "severity": "critical"}, ref)
        assert event_store._buffer[0]["layer"] == 3

    def test_record_missing_ref_uses_defaults(self):
        event_store.record({"name": "unknown", "severity": "warning"}, {})
        assert event_store._buffer[0]["layer"] == -1

    def test_record_never_raises(self):
        # Even with bad input, should not raise
        event_store.record(None)  # type: ignore

    def test_buffer_max_size(self):
        for i in range(2100):
            event_store.record({"name": f"alarm_{i}", "severity": "warning"})
        assert len(event_store._buffer) == 2000


class TestGetRecent:
    def setup_method(self):
        event_store._buffer.clear()

    def test_empty_buffer(self):
        assert event_store.get_recent() == []

    def test_returns_within_window(self):
        event_store._buffer.append({"ts": time.time() - 10, "name": "recent"})
        event_store._buffer.append({"ts": time.time() - 120, "name": "old"})
        result = event_store.get_recent(window=60)
        assert len(result) == 1
        assert result[0]["name"] == "recent"

    def test_default_window_60s(self):
        event_store._buffer.append({"ts": time.time() - 30, "name": "a"})
        event_store._buffer.append({"ts": time.time() - 90, "name": "b"})
        result = event_store.get_recent()
        assert len(result) == 1


class TestPrune:
    def setup_method(self):
        event_store._buffer.clear()

    def test_prune_removes_old(self):
        event_store._buffer.append({"ts": time.time() - 700, "name": "stale"})
        event_store._buffer.append({"ts": time.time() - 10, "name": "fresh"})
        event_store._prune()
        assert len(event_store._buffer) == 1
        assert event_store._buffer[0]["name"] == "fresh"

    def test_prune_respects_ttl(self):
        event_store._buffer.append({"ts": time.time() - 500, "name": "within_ttl"})
        event_store._prune()
        assert len(event_store._buffer) == 1
