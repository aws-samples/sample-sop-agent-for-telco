# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for ANO Swarm and complexity detection."""

import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault("strands", MagicMock())
sys.modules.setdefault("strands.multiagent", MagicMock())

from amzn_cse_telco_autonomous_network_agents_app.agent.core.swarm import (
    is_complex_query,
)


class TestIsComplexQuery:
    """Tests for the complexity heuristic."""

    def test_single_domain_not_complex(self):
        assert is_complex_query("what alarms are active?") is False
        assert is_complex_query("deploy open5gs-amf") is False
        assert is_complex_query("check BMC health on worker-003") is False

    def test_two_domains_is_complex(self):
        assert is_complex_query("did the recent deployment cause this alarm?") is True
        assert is_complex_query("provision failed and now there are alarms") is True
        assert is_complex_query("after the helm upgrade, KPIs degraded") is True

    def test_cross_domain_phrases_are_complex(self):
        assert is_complex_query("what caused the UPF traffic drop?") is True
        assert is_complex_query("investigate why worker-003 is failing") is True
        assert is_complex_query("give me the full picture of this incident") is True
        assert is_complex_query("root cause analysis for PTP drift") is True

    def test_simple_questions_not_complex(self):
        assert is_complex_query("hello") is False
        assert is_complex_query("how many nodes are there?") is False
        assert is_complex_query("list SOPs") is False

    def test_chat_routing_uses_complexity(self):
        """Verify the chat router would route these correctly."""
        # These should go to swarm
        assert is_complex_query("why did the alarm fire after the deployment?") is True
        # These should stay with single agent
        assert is_complex_query("show me active alarms") is False


class TestCreateAnoSwarm:
    """Tests for swarm creation."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.swarm.Agent")
    def test_creates_three_agents(self, MockAgent):
        mock_swarm_mod = MagicMock()
        sys.modules["strands.multiagent"] = mock_swarm_mod

        from amzn_cse_telco_autonomous_network_agents_app.agent.core.swarm import (
            create_ano_swarm,
        )
        create_ano_swarm()

        # Agent called 3 times (ANPA, ANDA, ANRA)
        assert MockAgent.call_count == 3
        # Swarm called with nodes list
        mock_swarm_mod.Swarm.assert_called_once()
        call_kwargs = mock_swarm_mod.Swarm.call_args
        nodes_arg = call_kwargs[1].get("nodes") if call_kwargs[1] else call_kwargs[0][0]
        assert len(nodes_arg) == 3
