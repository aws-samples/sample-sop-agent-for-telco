# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for SOP enrichment pipeline and core Prometheus alarm rules."""
from unittest.mock import MagicMock, patch


class TestCorePrometheusAlarms:
    """Test alarm rules using Open5GS Prometheus metrics."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_amf_registration_failure(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_ran_thresholds,
        )
        mock_query.side_effect = [
            {},  # RAN metrics
            {"amf_fivegs_amffunction_rm_reginitfail": 5},  # Core metrics
        ]
        alerts = evaluate_ran_thresholds()
        assert any(a["name"] == "amf_registration_failure" for a in alerts)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_amf_auth_rejection(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_ran_thresholds,
        )
        mock_query.side_effect = [
            {},
            {"amf_fivegs_amffunction_amf_authreject": 1},
        ]
        alerts = evaluate_ran_thresholds()
        assert any(a["name"] == "amf_auth_rejection" for a in alerts)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_smf_pfcp_failure(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_ran_thresholds,
        )
        mock_query.side_effect = [
            {},
            {"smf_fivegs_smffunction_sm_n4sessionestabfail": 3},
        ]
        alerts = evaluate_ran_thresholds()
        assert any(a["name"] == "smf_pfcp_failure" for a in alerts)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_upf_no_traffic(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_ran_thresholds,
        )
        mock_query.side_effect = [
            {},
            {"upf_fivegs_ep_n3_gtp_indatapktn3upf": 0},
        ]
        alerts = evaluate_ran_thresholds()
        assert any(a["name"] == "upf_no_traffic" for a in alerts)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._query_influx")
    def test_healthy_core_no_prometheus_alarms(self, mock_query):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            evaluate_ran_thresholds,
        )
        mock_query.side_effect = [
            {"cells_0_ue_list_0_dl_brate": 66_000_000, "cells_0_cell_metrics_error_indication_count": 0,
             "du_du_high_mac_dl_0_cpu_usage_percent": 0.001},
            {"amf_gnb_connected": 1, "core_nf_health_pct": 100,
             "amf_fivegs_amffunction_rm_reginitfail": 0,
             "amf_fivegs_amffunction_amf_authreject": 0,
             "smf_fivegs_smffunction_sm_n4sessionestabfail": 0,
             "upf_fivegs_ep_n3_gtp_indatapktn3upf": 100},
        ]
        alerts = evaluate_ran_thresholds()
        core_alarms = [a for a in alerts if a["name"] in
                       ("amf_registration_failure", "amf_auth_rejection", "smf_pfcp_failure", "upf_no_traffic")]
        assert len(core_alarms) == 0


class TestAlarmReferenceNewAlarms:
    """Verify alarm definitions from config."""

    def _alarm_ref(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import (
            load_config,
        )
        cfg = load_config()
        return {a.name: {"layer": a.layer, "depends_on": a.depends_on, "nf_scope": a.nf_scope} for a in cfg.alarms}

    def test_new_alarms_exist(self):
        d = self._alarm_ref()
        for name in ["amf_gnb_disconnect", "nf_crashloop", "du_timing_failure"]:
            assert name in d, f"Missing alarm: {name}"

    def test_core_alarms_layer_2(self):
        d = self._alarm_ref()
        for name in ["amf_gnb_disconnect", "nf_crashloop"]:
            if name in d:
                assert d[name]["layer"] == 2, f"{name} should be layer 2"

    def test_alarms_have_depends_on(self):
        d = self._alarm_ref()
        for name, ref in d.items():
            assert isinstance(ref["depends_on"], list), f"{name} missing depends_on"

    def test_alarm_count(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import (
            load_config,
        )
        assert len(load_config().alarms) >= 7


class TestEnvironmentScanners:
    """Test per-layer environment scanners."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._run")
    def test_scan_core_returns_pods(self, mock_run):
        mock_run.return_value = MagicMock(stdout="open5gs-amf-xxx Running\nopen5gs-smf-xxx Running\n")
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            _scan_environment,
        )
        scan = _scan_environment({"name": "amf_gnb_disconnect"})
        assert "pods" in scan or "tools" in scan

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._run")
    def test_scan_ran_includes_no_ductl(self, mock_run):
        mock_run.return_value = MagicMock(stdout="srsran-gnb-xxx Running\n")
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            _scan_environment,
        )
        scan = _scan_environment({"name": "du_timing_failure"})
        assert "ran_info" in scan
        assert "no ductl" in scan["ran_info"].lower() or "NO vendor CLI" in scan["ran_info"]

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._run")
    def test_scan_ue_returns_logs(self, mock_run):
        mock_run.return_value = MagicMock(stdout="Registration is successful\n")
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            _alarm_ref,
            _scan_environment,
        )
        # Add a fake UE alarm to alarm_ref so scanner picks layer 4
        _alarm_ref["ue_registration_failure"] = {"layer": 4}
        scan = _scan_environment({"name": "ue_registration_failure"})
        del _alarm_ref["ue_registration_failure"]
        assert "ue_logs" in scan


class TestSOPEnrichment:
    """Test SOP enrichment pipeline."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._scan_environment")
    def test_enrichment_calls_scan(self, mock_scan):
        mock_scan.return_value = {"pods": "amf-xxx Running", "tools": "kubectl"}
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            _enrich_sop,
        )
        # Will fail on Bedrock call but scan should be called
        _enrich_sop("# Raw SOP", {"name": "du_timing_failure"})
        mock_scan.assert_called_once()

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._scan_environment")
    def test_enrichment_failure_returns_original(self, mock_scan):
        mock_scan.side_effect = Exception("scan failed")
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
            _enrich_sop,
        )
        original = "# Original SOP content"
        result = _enrich_sop(original, {"name": "test"})
        assert result == original
