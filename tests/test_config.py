# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for config.py — YAML parsing, node lookups, BMC paths."""
from pathlib import Path

import pytest


from amzn_cse_telco_autonomous_network_agents_app.agent.config import BMCConfig, NodeConfig, SiteConfig, _parse, load_config


class TestBMCConfig:
    def test_idrac_redfish_base(self):
        bmc = BMCConfig(ip="10.0.0.1", type="idrac")
        assert "System.Embedded.1" in bmc.redfish_base

    def test_ilo_redfish_base(self):
        bmc = BMCConfig(ip="10.0.0.1", type="ilo")
        assert "Chassis/1" in bmc.redfish_base

    def test_thermal_path(self):
        bmc = BMCConfig(ip="10.0.0.1", type="idrac")
        assert bmc.thermal_path.endswith("/Thermal")

    def test_power_path(self):
        bmc = BMCConfig(ip="10.0.0.1", type="idrac")
        assert bmc.power_path.endswith("/Power")


class TestSiteConfigLookups:
    @pytest.fixture
    def cfg(self):
        c = SiteConfig()
        c.nodes = [
            NodeConfig(name="w1", oam_ip="10.0.0.1", ssm_id="mi-aaa",
                       bmc=BMCConfig(ip="10.0.1.1"), roles=["du", "cu"], namespaces=["srsran"]),
            NodeConfig(name="w2", oam_ip="10.0.0.2", ssm_id="mi-bbb",
                       bmc=BMCConfig(ip="10.0.1.2"), roles=["upf"], namespaces=["open5gs"]),
        ]
        return c

    def test_get_node_by_ssm(self, cfg):
        n = cfg.get_node_by_ssm("mi-aaa")
        assert n.name == "w1"

    def test_get_node_by_ssm_not_found(self, cfg):
        assert cfg.get_node_by_ssm("mi-zzz") is None

    def test_get_node_by_oam(self, cfg):
        n = cfg.get_node_by_oam("10.0.0.2")
        assert n.name == "w2"

    def test_get_node_by_bmc(self, cfg):
        n = cfg.get_node_by_bmc("10.0.1.1")
        assert n.name == "w1"

    def test_get_node_by_role(self, cfg):
        n = cfg.get_node_by_role("upf")
        assert n.name == "w2"

    def test_get_nodes_by_role(self, cfg):
        nodes = cfg.get_nodes_by_role("du")
        assert len(nodes) == 1
        assert nodes[0].name == "w1"

    def test_all_bmc_ips(self, cfg):
        assert set(cfg.all_bmc_ips) == {"10.0.1.1", "10.0.1.2"}

    def test_all_ssm_ids(self, cfg):
        assert set(cfg.all_ssm_ids) == {"mi-aaa", "mi-bbb"}


class TestParse:
    def test_minimal_config(self):
        cfg = _parse({})
        assert cfg.cluster_name == ""
        assert cfg.nodes == []

    def test_cluster_section(self):
        cfg = _parse({"cluster": {"name": "prod", "region": "us-east-1"}})
        assert cfg.cluster_name == "prod"
        assert cfg.cluster_region == "us-east-1"

    def test_nodes_parsed(self):
        cfg = _parse({"nodes": [{"name": "n1", "oam_ip": "1.2.3.4", "roles": ["du"]}]})
        assert len(cfg.nodes) == 1
        assert cfg.nodes[0].roles == ["du"]

    def test_bmc_parsed(self):
        cfg = _parse({"nodes": [{"name": "n1", "bmc": {"ip": "10.0.0.1", "type": "ilo"}}]})
        assert cfg.nodes[0].bmc.ip == "10.0.0.1"
        assert cfg.nodes[0].bmc.type == "ilo"

    def test_alarms_parsed(self):
        cfg = _parse({"alarms": [
            {"name": "test", "layer": 2, "source": "core", "field": "metric_x", "condition": "> 5", "severity": "critical"}
        ]})
        assert len(cfg.alarms) == 1
        assert cfg.alarms[0].name == "test"
        assert cfg.alarms[0].metric_field == "metric_x"

    def test_guardrails_parsed(self):
        cfg = _parse({"guardrails": {"protected_namespaces": ["ns1"], "blocked_commands": ["rm -rf"]}})
        assert "ns1" in cfg.guardrails.protected_namespaces
        assert "rm -rf" in cfg.guardrails.blocked_commands

    def test_anomaly_detection_parsed(self):
        cfg = _parse({"anomaly_detection": {"enabled": False, "sigma_threshold": 4}})
        assert cfg.anomaly_detection.enabled is False
        assert cfg.anomaly_detection.sigma_threshold == 4

    def test_field_alias_mapping(self):
        """'field' in YAML maps to 'metric_field' in AlarmRule."""
        cfg = _parse({"alarms": [{"name": "x", "field": "my_metric", "condition": "> 0"}]})
        assert cfg.alarms[0].metric_field == "my_metric"

    def test_unknown_fields_ignored(self):
        """Extra fields in YAML don't crash parsing."""
        cfg = _parse({"alarms": [{"name": "x", "field": "m", "condition": "> 0", "unknown_field": "ignored"}]})
        assert cfg.alarms[0].name == "x"

    def test_plugins_default_empty(self):
        assert _parse({}).plugins == []

    def test_plugins_list_parsed(self):
        cfg = _parse({"plugins": ["pkg.mod_a", "pkg.mod_b"]})
        assert cfg.plugins == ["pkg.mod_a", "pkg.mod_b"]

    def test_plugins_non_list_fails_loud(self):
        # A bare string (forgotten YAML list dashes) must fail clearly, naming
        # the field, rather than being iterated character-by-character later.
        with pytest.raises(ValueError, match="plugins"):
            _parse({"plugins": "pkg.mod_a"})


class TestLoadConfig:
    def test_loads_from_env(self, set_config_path):
        cfg = load_config()
        assert cfg.cluster_name == "test-cluster"
        assert len(cfg.nodes) == 2

    def test_defaults_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANRA_CONFIG", str(tmp_path / "nonexistent.yaml"))
        monkeypatch.setattr("amzn_cse_telco_autonomous_network_agents_app.agent.config._CONFIG_PATHS", [])
        cfg = load_config()
        assert cfg.cluster_name == ""


class TestConfigValidation:
    """Tests for validate() — role-specific required fields and schema version."""

    def _minimal_config(self, **overrides):
        c = SiteConfig(
            cluster_name="test",
            cluster_region="us-west-1",
            bedrock_region="us-west-2",
        )
        for k, v in overrides.items():
            setattr(c, k, v)
        return c

    def test_valid_anra_config_passes(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = self._minimal_config(influxdb_url="http://influx:8086")
        assert validate(cfg, role="anra") == []

    def test_valid_anra_alertmanager_only_passes(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = self._minimal_config(alertmanager_url="http://am:9093")
        assert validate(cfg, role="anra") == []

    def test_valid_anda_config_passes(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = self._minimal_config(helm_repo="oci://my-repo")
        assert validate(cfg, role="anda") == []

    def test_valid_anda_gitops_passes(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = self._minimal_config(gitops_repo="https://git.example.com/repo")
        assert validate(cfg, role="anda") == []

    def test_valid_anpa_config_passes(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = self._minimal_config(tinkerbell_namespace="tink-system")
        assert validate(cfg, role="anpa") == []

    def test_missing_cluster_name_fails(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = self._minimal_config(cluster_name="")
        errors = validate(cfg, role="anra")
        assert any("cluster.name" in e for e in errors)

    def test_missing_cluster_region_fails(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = self._minimal_config(cluster_region="")
        errors = validate(cfg, role="anra")
        assert any("cluster.region" in e for e in errors)

    def test_missing_bedrock_region_fails(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = self._minimal_config(bedrock_region="")
        errors = validate(cfg, role="anra")
        assert any("bedrock.region" in e for e in errors)

    def test_anra_missing_monitoring_fails(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = self._minimal_config(influxdb_url="", alertmanager_url="")
        errors = validate(cfg, role="anra")
        assert any("monitoring" in e.lower() for e in errors)

    def test_anpa_missing_tinkerbell_namespace_fails(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = self._minimal_config(tinkerbell_namespace="")
        errors = validate(cfg, role="anpa")
        assert any("tinkerbell_namespace" in e for e in errors)

    def test_anda_missing_deploy_target_fails(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = self._minimal_config(helm_repo="", gitops_repo="")
        errors = validate(cfg, role="anda")
        assert any("helm_repo" in e or "gitops_repo" in e for e in errors)

    def test_unsupported_schema_version_fails(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = self._minimal_config(schema_version="99")
        errors = validate(cfg, role="anra")
        assert any("Unsupported config version" in e for e in errors)

    def test_missing_version_defaults_to_1(self):
        """No version in YAML → parsed as '1' → passes validation."""
        cfg = _parse({"cluster": {"name": "x", "region": "us-west-1"}, "bedrock": {"region": "us-west-2"},
                      "monitoring": {"influxdb_url": "http://x"}})
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        assert cfg.schema_version == "1"
        assert validate(cfg, role="anra") == []

    def test_multiple_errors_reported(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = SiteConfig(cluster_name="", cluster_region="", bedrock_region="")
        errors = validate(cfg, role="anra")
        assert len(errors) >= 3


class TestEnumFieldValidation:
    """validate() rejects out-of-enum values for the enumerated config fields."""

    def _minimal_config(self, **overrides):
        c = SiteConfig(
            cluster_name="test",
            cluster_region="us-west-1",
            bedrock_region="us-west-2",
            influxdb_url="http://influx:8086",
        )
        for k, v in overrides.items():
            setattr(c, k, v)
        return c

    def test_defaults_pass(self):
        # The dataclass defaults (auto/direct/yaml/smart) must validate clean —
        # the no-config-change guarantee.
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        assert validate(self._minimal_config(), role="anra") == []

    def test_all_valid_enum_values_pass(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        cfg = self._minimal_config(
            approval_mode="gitlab",
            remediation_mode="gitops",
            topology_provider="neptune",
            bedrock_model_tier="fast",
        )
        assert validate(cfg, role="anra") == []

    def test_bad_topology_provider_fails(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        errors = validate(self._minimal_config(topology_provider="neptun"), role="anra")
        assert any("topology.provider" in e and "neptun" in e for e in errors)

    def test_bad_approval_mode_fails(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        errors = validate(self._minimal_config(approval_mode="automatic"), role="anra")
        assert any("approval.mode" in e for e in errors)

    def test_bad_remediation_mode_fails(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        errors = validate(self._minimal_config(remediation_mode="gitpush"), role="anra")
        assert any("remediation.mode" in e for e in errors)

    def test_bad_model_tier_fails(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        errors = validate(self._minimal_config(bedrock_model_tier="turbo"), role="anra")
        assert any("bedrock.model_tier" in e for e in errors)

    def test_error_message_names_valid_set_and_offending_value(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        errors = validate(self._minimal_config(topology_provider="neptun"), role="anra")
        msg = next(e for e in errors if "topology.provider" in e)
        assert "yaml" in msg and "neptune" in msg  # the valid set
        assert "neptun" in msg  # the offending value, quoted

    def test_mis_cased_value_rejected(self):
        # Match is exact/case-sensitive by design (values flow to exact-match
        # lookups downstream); "Auto" is not "auto" and must fail loud.
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        errors = validate(self._minimal_config(approval_mode="Auto"), role="anra")
        assert any("approval.mode" in e for e in errors)

    def test_manual_approval_mode_passes(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import validate
        assert validate(self._minimal_config(approval_mode="manual"), role="anra") == []


class TestConfigBackwardCompat:
    """Tests for ANRA_CONFIG deprecation and AGENT_CONFIG priority."""

    def test_anra_config_env_still_works(self, tmp_path, monkeypatch):
        import warnings as w
        import yaml
        cfg_file = tmp_path / "old-config.yaml"
        cfg_file.write_text(yaml.dump({"cluster": {"name": "from-anra-env", "region": "us-west-1"}}))
        monkeypatch.setenv("ANRA_CONFIG", str(cfg_file))
        monkeypatch.delenv("AGENT_CONFIG", raising=False)
        monkeypatch.setattr("amzn_cse_telco_autonomous_network_agents_app.agent.config._CONFIG_PATHS", [])
        with w.catch_warnings(record=True) as caught:
            w.simplefilter("always")
            cfg = load_config()
        assert cfg.cluster_name == "from-anra-env"
        assert any("deprecated" in str(x.message).lower() for x in caught)

    def test_agent_config_env_takes_priority(self, tmp_path, monkeypatch):
        import yaml
        old_file = tmp_path / "old.yaml"
        old_file.write_text(yaml.dump({"cluster": {"name": "old"}}))
        new_file = tmp_path / "new.yaml"
        new_file.write_text(yaml.dump({"cluster": {"name": "new"}}))
        monkeypatch.setenv("ANRA_CONFIG", str(old_file))
        monkeypatch.setenv("AGENT_CONFIG", str(new_file))
        cfg = load_config()
        assert cfg.cluster_name == "new"


class TestNewSchemaFields:
    """Tests for bedrock_model_tier, bedrock_model_override, topology_emit_service_topology."""

    def test_bedrock_model_tier_parsed(self):
        cfg = _parse({"bedrock": {"region": "us-west-2", "model_tier": "fast"}})
        assert cfg.bedrock_model_tier == "fast"

    def test_bedrock_model_tier_defaults_to_smart(self):
        cfg = _parse({"bedrock": {"region": "us-west-2"}})
        assert cfg.bedrock_model_tier == "smart"

    def test_bedrock_model_override_parsed(self):
        cfg = _parse({"bedrock": {"region": "us-west-2", "model_override": "us.anthropic.claude-sonnet-4-6"}})
        assert cfg.bedrock_model_override == "us.anthropic.claude-sonnet-4-6"

    def test_topology_emit_flag_true_by_default(self):
        cfg = _parse({"topology": {"provider": "yaml"}})
        assert cfg.topology_emit_service_topology is True

    def test_topology_emit_flag_false(self):
        cfg = _parse({"topology": {"provider": "yaml", "emit_service_topology": False}})
        assert cfg.topology_emit_service_topology is False

    def test_schema_version_parsed(self):
        cfg = _parse({"version": "1", "cluster": {"name": "x"}})
        assert cfg.schema_version == "1"

    def test_schema_version_missing_defaults_1(self):
        cfg = _parse({"cluster": {"name": "x"}})
        assert cfg.schema_version == "1"
