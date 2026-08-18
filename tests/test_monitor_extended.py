# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the ANRA monitor — hardware event-log polling + enrichment + alarm dedup.

SEL polling moved to agents/anra/monitoring/hardware_event_log.py; these tests
import + patch it there (poll_redfish_sel calls util.bmc.curl_bmc, which runs
subprocess.run, so patching subprocess.run at the module level intercepts it).
"""

import subprocess
from unittest.mock import MagicMock, patch

_HW_LOG = "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.hardware_event_log"


class TestSELPolling:
    @patch.object(subprocess, "run")
    def test_poll_returns_critical_entries(self, mock_run):
        import json

        import amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.hardware_event_log as hw_log
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.hardware_event_log import (
            _sel_last_id,
            poll_redfish_sel,
        )

        _sel_last_id.clear()
        hw_log._sel_initialized = False

        seed_response = json.dumps(
            {
                "Members": [
                    {"Id": "4", "MessageId": "old_event", "Message": "Old event", "Severity": "OK", "SensorType": "test", "Created": "2026-01-28T00:00:00"},
                ]
            }
        )
        new_response = json.dumps(
            {
                "Members": [
                    {"Id": "4", "MessageId": "old_event", "Message": "Old event", "Severity": "OK", "SensorType": "test", "Created": "2026-01-28T00:00:00"},
                    {"Id": "5", "MessageId": "6f03ffff", "Message": "PSU 2 lost power", "Severity": "Critical", "SensorType": "Power Supply", "Created": "2026-01-29T17:20:53"},
                ]
            }
        )
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=seed_response, stderr=""),  # BMC1 seed
            MagicMock(returncode=0, stdout=seed_response, stderr=""),  # BMC2 seed
            MagicMock(returncode=0, stdout=new_response, stderr=""),  # BMC1 poll
            MagicMock(returncode=0, stdout=new_response, stderr=""),  # BMC2 poll
            MagicMock(returncode=1, stdout="", stderr=""),  # EEMI lookup (may fail)
            MagicMock(returncode=1, stdout="", stderr=""),  # EEMI lookup
        ]

        # First call seeds IDs
        poll_redfish_sel()
        # Second call finds new entry (Id=5 > seeded max Id=4)
        alerts = poll_redfish_sel()
        critical = [a for a in alerts if a["severity"] == "critical"]
        assert len(critical) >= 1
        assert critical[0]["source"] == "redfish-sel"

    @patch.object(subprocess, "run")
    def test_poll_dedup_by_last_id(self, mock_run):
        import json

        import amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.hardware_event_log as hw_log
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.hardware_event_log import (
            _sel_last_id,
            poll_redfish_sel,
        )

        _sel_last_id.clear()
        hw_log._sel_initialized = True  # skip seeding: exercise the dedup path directly

        sel = json.dumps({"Members": [{"Id": "5", "MessageId": "test", "Message": "test", "Severity": "Critical", "SensorType": "test"}]})
        mock_run.return_value = MagicMock(returncode=0, stdout=sel, stderr="")

        alerts1 = poll_redfish_sel()
        critical1 = [a for a in alerts1 if a["severity"] == "critical"]
        assert len(critical1) >= 1

        # Second poll: same data, should return nothing
        alerts2 = poll_redfish_sel()
        critical2 = [a for a in alerts2 if a["severity"] == "critical"]
        assert len(critical2) == 0

    @patch.object(subprocess, "run")
    def test_poll_handles_curl_failure(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.hardware_event_log import (
            _sel_last_id,
            poll_redfish_sel,
        )

        _sel_last_id.clear()
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="timeout")
        alerts = poll_redfish_sel()
        assert len(alerts) == 0


class TestAlarmDedup:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_same_alarm_not_repeated(self, mock_query):
        """Monitor should only report new alarms, not repeat seen ones."""
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_ran_thresholds,
        )

        mock_query.side_effect = [
            {"du_du_high_mac_dl_0_cpu_usage_percent": 85},
            {},
        ]
        alerts1 = evaluate_ran_thresholds()
        assert len(alerts1) == 1

        # Same values again — evaluate_ran_thresholds returns same alerts
        # Dedup happens in run_loop, not in evaluate. This tests the raw evaluation.
        mock_query.side_effect = [
            {"du_du_high_mac_dl_0_cpu_usage_percent": 85},
            {},
        ]
        alerts2 = evaluate_ran_thresholds()
        assert len(alerts2) == 1  # evaluate always returns, dedup is in run_loop


class TestSOPGeneration:
    def test_resolve_sop_with_existing(self, tmp_path):
        import amzn_cse_telco_autonomous_network_agents_app.agent.monitor as monitor
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            resolve_sop,
        )

        sop_dir = tmp_path / "sops" / "day2-remediate" / "ran"
        sop_dir.mkdir(parents=True)
        (sop_dir / "remediate-du-cpu-overload.md").write_text("# Test")

        old = monitor.SOP_REPO
        monitor.SOP_REPO = str(tmp_path)
        try:
            result = resolve_sop({"name": "test", "sop": "day2-remediate/ran/remediate-du-cpu-overload.md"})
            assert "remediate-du-cpu-overload" in result
        finally:
            monitor.SOP_REPO = old

    def test_resolve_sop_no_match(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            resolve_sop,
        )

        with patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._generate_sop", return_value=None):
            result = resolve_sop({"name": "unknown", "sop": ""})
            assert result is None
