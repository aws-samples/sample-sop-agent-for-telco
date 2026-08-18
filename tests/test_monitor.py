# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for monitor.py — alarm evaluation and SOP resolution."""

from unittest.mock import patch


class TestRanThresholdEvaluation:
    """Test InfluxDB-based RAN/Core threshold evaluation."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_healthy_system_no_alarms(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_ran_thresholds,
        )

        mock_query.side_effect = [
            {
                "cells_0_ue_list_0_dl_brate": 66_000_000,
                "cells_0_ue_list_0_cqi": 15,
                "du_du_high_mac_dl_0_cpu_usage_percent": 0.001,
                "du_du_high_mac_dl_0_max_latency_us": 50,
                "cells_0_cell_metrics_late_dl_harqs": 0,
                "cells_0_cell_metrics_error_indication_count": 0,
            },
            {"amf_gnb_connected": 1, "upf_pfcp_active": 1, "core_nf_health_pct": 100, "alarm_amf_reject": 0, "alarm_upf_heartbeat_lost": 0, "alarm_scp_timeout": 0},
        ]
        alerts = evaluate_ran_thresholds()
        assert len(alerts) == 0

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_cpu_overload_triggers(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_ran_thresholds,
        )

        mock_query.side_effect = [
            {"du_du_high_mac_dl_0_cpu_usage_percent": 85},
            {},
        ]
        alerts = evaluate_ran_thresholds()
        assert any(a["name"] == "du_cpu_overload" for a in alerts)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_amf_gnb_disconnect_triggers(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_ran_thresholds,
        )

        mock_query.side_effect = [
            {},
            {"amf_gnb": 0},
        ]
        alerts = evaluate_ran_thresholds()
        assert any(a["name"] == "amf_gnb_disconnect" for a in alerts)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_throughput_drop_triggers(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_ran_thresholds,
        )

        mock_query.side_effect = [
            {"cells_0_ue_list_0_dl_brate": 100_000},
            {},
        ]
        alerts = evaluate_ran_thresholds()
        assert any(a["name"] == "du_throughput_drop" for a in alerts)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_multiple_alarms(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_ran_thresholds,
        )

        mock_query.side_effect = [
            {"du_du_high_mac_dl_0_cpu_usage_percent": 95, "cells_0_cell_metrics_error_indication_count": 600},
            {"amf_gnb": 0, "core_nf_health_pct": 80},
        ]
        alerts = evaluate_ran_thresholds()
        names = {a["name"] for a in alerts}
        assert "du_cpu_overload" in names
        assert "du_timing_failure" in names
        assert "amf_gnb_disconnect" in names

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_influx_returns_empty(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_ran_thresholds,
        )

        mock_query.return_value = {}
        alerts = evaluate_ran_thresholds()
        assert len(alerts) == 0

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_alert_has_alarm_ref_context(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_ran_thresholds,
        )

        mock_query.side_effect = [
            {"du_du_high_mac_dl_0_cpu_usage_percent": 85},
            {},
        ]
        alerts = evaluate_ran_thresholds()
        alert = next(a for a in alerts if a["name"] == "du_cpu_overload")
        assert alert["severity"] == "critical"
        assert "CPU" in alert.get("service_impact", "") or "throughput" in alert.get("service_impact", "").lower()


class TestOsThresholdEvaluation:
    """Test OS + PTP threshold evaluation."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_memory_pressure_triggers(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_os_thresholds,
        )

        mock_query.return_value = {"node_pressure_memory_stalled_seconds_total": 15}
        alerts = evaluate_os_thresholds()
        assert any(a["name"] == "memory_pressure" for a in alerts)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_ptp_drift_triggers(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_os_thresholds,
        )

        mock_query.return_value = {"ptp_offset_ns": 2000}
        alerts = evaluate_os_thresholds()
        assert any(a["name"] == "ptp_offset_drift" for a in alerts)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_hugepage_exhaustion_triggers(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_os_thresholds,
        )

        mock_query.return_value = {"node_memory_HugePages_Free": 0}
        alerts = evaluate_os_thresholds()
        assert any(a["name"] == "hugepage_exhaustion" for a in alerts)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_healthy_os_no_alarms(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_os_thresholds,
        )

        mock_query.return_value = {
            "node_pressure_memory_stalled_seconds_total": 2,
            "node_memory_HugePages_Free": 16,
            "node_cpu_steal_percent": 1,
            "ptp_offset_ns": 100,
        }
        alerts = evaluate_os_thresholds()
        assert len(alerts) == 0

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_cpu_steal_triggers(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_os_thresholds,
        )

        mock_query.return_value = {"node_cpu_steal_percent": 8}
        alerts = evaluate_os_thresholds()
        assert any(a["name"] == "high_cpu_steal" for a in alerts)


class TestSOPResolution:
    """Test SOP lookup and generation."""

    def test_existing_sop_found(self, tmp_path):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            resolve_sop,
        )

        sop_dir = tmp_path / "sops" / "day2-remediate" / "ran"
        sop_dir.mkdir(parents=True)
        (sop_dir / "remediate-du-cpu-overload.md").write_text("# Test SOP")

        import amzn_cse_telco_autonomous_network_agents_app.agent.monitor as monitor

        old_repo = monitor.SOP_REPO
        monitor.SOP_REPO = str(tmp_path)
        try:
            result = resolve_sop({"name": "test", "sop": "day2-remediate/ran/remediate-du-cpu-overload.md"})
            assert result is not None
            assert "remediate-du-cpu-overload" in result
        finally:
            monitor.SOP_REPO = old_repo

    def test_missing_sop_returns_none_without_bedrock(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            resolve_sop,
        )

        with patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._generate_sop", return_value=None):
            result = resolve_sop({"name": "unknown_alarm", "sop": ""})
            assert result is None
