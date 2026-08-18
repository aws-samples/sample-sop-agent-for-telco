# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the AI-first SOP Bridge."""

from unittest.mock import patch


from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.sop_bridge import (
    SOPBridge,
    SOPResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_plan(intent="deploy", reason="", nfs=None, execution_mode="live"):
    """Create a minimal DeploymentPlan dict."""
    plan = {
        "metadata": {"name": "test-plan-001"},
        "spec": {
            "intent": intent,
            "reason": reason,
            "executionMode": execution_mode,
            "networkFunctions": nfs or [{"name": "amf", "vendor": "open5gs"}],
        },
    }
    return plan


# ---------------------------------------------------------------------------
# TestSOPBridge.execute
# ---------------------------------------------------------------------------


class TestExecuteFlow:
    """Tests for the simplified execute() flow."""

    def setup_method(self):
        self.bridge = SOPBridge()

    def test_execute_returns_sop_result(self):
        """execute() always returns a SOPResult dataclass."""
        with patch.object(self.bridge, "_run_config_gen_if_needed"):
            with patch.object(self.bridge, "_execute_ai") as mock_ai:
                mock_ai.return_value = SOPResult(success=True, phase="Deployed")
                result = self.bridge.execute(
                    nf_name="amf",
                    plan=_make_plan(),
                    namespace="open5gs",
                    cluster="site-002",
                )
                assert isinstance(result, SOPResult)
                assert result.success is True

    def test_execute_calls_config_gen_for_deploy(self):
        """Phase 0 config gen runs for deploy intent."""
        with patch.object(self.bridge, "_run_config_gen_if_needed") as mock_cg:
            with patch.object(self.bridge, "_execute_ai", return_value=SOPResult(success=True)):
                self.bridge.execute("amf", _make_plan(intent="deploy"), namespace="open5gs", cluster="c1")
                mock_cg.assert_called_once()

    def test_execute_calls_config_gen_for_upgrade(self):
        """Phase 0 config gen runs for upgrade intent."""
        with patch.object(self.bridge, "_run_config_gen_if_needed") as mock_cg:
            with patch.object(self.bridge, "_execute_ai", return_value=SOPResult(success=True)):
                self.bridge.execute("amf", _make_plan(intent="upgrade"), namespace="open5gs", cluster="c1")
                mock_cg.assert_called_once()

    def test_execute_skips_config_gen_for_decommission(self):
        """Phase 0 config gen does NOT run for decommission."""
        with patch.object(self.bridge, "_run_config_gen_if_needed") as mock_cg:
            with patch.object(self.bridge, "_execute_ai", return_value=SOPResult(success=True)):
                self.bridge.execute("amf", _make_plan(intent="decommission"), namespace="open5gs", cluster="c1")
                mock_cg.assert_not_called()

    def test_execute_replay_mode_returns_stub(self):
        """Replay mode returns success without AI."""
        with patch.object(self.bridge, "_run_config_gen_if_needed"):
            result = self.bridge.execute("amf", _make_plan(execution_mode="replay"), namespace="ns", cluster="c1")
            assert result.success is True
            assert "replay" in result.output.lower()

    def test_execute_dry_run_mode_returns_stub(self):
        """Dry-run mode returns success without AI."""
        with patch.object(self.bridge, "_run_config_gen_if_needed"):
            result = self.bridge.execute("amf", _make_plan(execution_mode="dry-run"), namespace="ns", cluster="c1")
            assert result.success is True
            assert "dry-run" in result.output.lower()

    def test_vendor_resolved_from_plan(self):
        """Vendor is extracted from the plan's networkFunctions."""
        plan = _make_plan(nfs=[{"name": "upf", "vendor": "nec"}])
        with patch.object(self.bridge, "_run_config_gen_if_needed") as mock_cg:
            with patch.object(self.bridge, "_execute_ai", return_value=SOPResult(success=True)) as mock_ai:
                self.bridge.execute("upf", plan, namespace="core", cluster="c1")
                # Verify vendor passed through
                call_kwargs = mock_ai.call_args[1]
                assert call_kwargs["vendor"] == "nec"


# ---------------------------------------------------------------------------
# TestContextPrompt
# ---------------------------------------------------------------------------


class TestContextPrompt:
    """Tests for _build_context_prompt."""

    def setup_method(self):
        self.bridge = SOPBridge()

    def test_prompt_includes_nf_and_namespace(self):
        prompt = self.bridge._build_context_prompt(
            nf_name="amf", namespace="open5gs", cluster="site-002",
            intent="deploy", reason="", vendor="open5gs", strategy=None,
        )
        assert "amf" in prompt
        assert "open5gs" in prompt
        assert "site-002" in prompt

    def test_prompt_includes_intent(self):
        prompt = self.bridge._build_context_prompt(
            nf_name="amf", namespace="ns", cluster="c1",
            intent="remediation", reason="pod crashloop", vendor="x", strategy=None,
        )
        assert "remediation" in prompt
        assert "pod crashloop" in prompt

    def test_prompt_includes_generated_values_if_exists(self, tmp_path):
        """If generated values exist, prompt references them."""
        values_file = tmp_path / "amf-values.yaml"
        values_file.write_text("global: {}")
        with patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.sop_bridge.GENERATED_CONFIG_DIR", str(tmp_path)):
            prompt = self.bridge._build_context_prompt(
                nf_name="amf", namespace="ns", cluster="c1",
                intent="deploy", reason="", vendor="x", strategy=None,
            )
            assert "amf-values.yaml" in prompt
            assert "helm upgrade -f" in prompt

    def test_prompt_includes_assess_decide_execute_verify(self):
        """Prompt has the 4-step structure."""
        prompt = self.bridge._build_context_prompt(
            nf_name="amf", namespace="ns", cluster="c1",
            intent="deploy", reason="", vendor="x", strategy=None,
        )
        assert "ASSESS" in prompt
        assert "DECIDE" in prompt
        assert "EXECUTE" in prompt
        assert "VERIFY" in prompt

    def test_prompt_includes_adaptability_rules(self):
        """Prompt tells agent to adapt, not blindly follow SOPs."""
        prompt = self.bridge._build_context_prompt(
            nf_name="amf", namespace="ns", cluster="c1",
            intent="deploy", reason="", vendor="x", strategy=None,
        )
        assert "Do NOT blindly follow" in prompt
        assert "Adapt to what you actually observe" in prompt


# ---------------------------------------------------------------------------
# TestSOPDiscovery
# ---------------------------------------------------------------------------


class TestSOPDiscovery:
    """Tests for _find_relevant_sop (non-rigid discovery)."""

    def setup_method(self):
        self.bridge = SOPBridge()

    def test_returns_none_when_sops_dir_missing(self, tmp_path):
        with patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.sop_bridge._SOP_ROOT", str(tmp_path)):
            result = self.bridge._find_relevant_sop("deploy", "amf")
            assert result is None

    def test_finds_nf_specific_sop(self, tmp_path):
        """Prefers SOP with NF name in filename."""
        sops = tmp_path / "sops" / "day1-deploy"
        sops.mkdir(parents=True)
        (sops / "deploy-5g-core.md").write_text("# generic")
        (sops / "deploy-amf.md").write_text("# AMF specific")

        with patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.sop_bridge._SOP_ROOT", str(tmp_path)):
            result = self.bridge._find_relevant_sop("deploy", "amf")
            assert result is not None
            assert "amf" in result

    def test_falls_back_to_generic_core_sop(self, tmp_path):
        """If no NF-specific SOP, uses generic 5g-core."""
        sops = tmp_path / "sops" / "day1-deploy"
        sops.mkdir(parents=True)
        (sops / "deploy-5g-core.md").write_text("# generic")

        with patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.sop_bridge._SOP_ROOT", str(tmp_path)):
            result = self.bridge._find_relevant_sop("deploy", "smf")
            assert result is not None
            assert "5g-core" in result

    def test_remediation_uses_day2_directory(self, tmp_path):
        """Remediation intent searches day2-remediate/."""
        sops = tmp_path / "sops" / "day2-remediate" / "core"
        sops.mkdir(parents=True)
        (sops / "remediate-nf-crashloop.md").write_text("# fix it")

        with patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.sop_bridge._SOP_ROOT", str(tmp_path)):
            result = self.bridge._find_relevant_sop("remediation", "amf")
            # Should find something in day2-remediate
            # May be None if "amf" not in filename and no "core"/"5g" match
            # The crashloop SOP has "core" in path via os.walk
            # _find_relevant_sop is best-effort; verify it finds the crashloop SOP
            assert result is not None
            assert "day2-remediate" in result


# ---------------------------------------------------------------------------
# TestHelpers
# ---------------------------------------------------------------------------


class TestHelpers:
    """Tests for static helper methods."""

    def test_find_nf_in_plan_found(self):
        spec = {"networkFunctions": [{"name": "amf", "vendor": "open5gs"}]}
        result = SOPBridge._find_nf_in_plan(spec, "amf")
        assert result == {"name": "amf", "vendor": "open5gs"}

    def test_find_nf_in_plan_case_insensitive(self):
        spec = {"networkFunctions": [{"name": "AMF", "vendor": "open5gs"}]}
        result = SOPBridge._find_nf_in_plan(spec, "amf")
        assert result is not None

    def test_find_nf_in_plan_not_found(self):
        spec = {"networkFunctions": [{"name": "smf", "vendor": "open5gs"}]}
        result = SOPBridge._find_nf_in_plan(spec, "amf")
        assert result is None

    def test_find_nf_in_plan_supports_nfs_key(self):
        spec = {"nfs": [{"name": "upf", "vendor": "nec"}]}
        result = SOPBridge._find_nf_in_plan(spec, "upf")
        assert result == {"name": "upf", "vendor": "nec"}


# ---------------------------------------------------------------------------
# TestSOPResult
# ---------------------------------------------------------------------------


class TestSOPResult:
    """Tests for the SOPResult dataclass."""

    def test_defaults(self):
        r = SOPResult(success=True)
        assert r.phase == "Deployed"
        assert r.output == ""
        assert r.tier_used == 0
        assert r.steps_executed == 0
        assert r.fallback_used is False
        assert r.sop_path is None

    def test_tier_used_backward_compat(self):
        """tier_used field exists for orchestrator logging compatibility."""
        r = SOPResult(success=False, tier_used=2)
        assert r.tier_used == 2
