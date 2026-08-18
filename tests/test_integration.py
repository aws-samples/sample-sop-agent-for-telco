# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Integration tests — validates cross-agent flows in-process without a cluster.

Spins up all three agent roles as FastAPI TestClients and verifies:
1. Chat routing (simple vs complex)
2. Cross-agent HTTP tool calls (mocked at subprocess level)
3. Trend detection wired into monitor
4. Failure handler invocation path
"""

import os
import sys
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

# Mock strands before any agent imports
sys.modules.setdefault("strands", MagicMock())
sys.modules.setdefault("strands.models.bedrock", MagicMock())
sys.modules.setdefault("strands.multiagent", MagicMock())
os.environ.setdefault("ANRA_CONFIG", "/dev/null")

from fastapi.testclient import TestClient

from amzn_cse_telco_autonomous_network_agents_app.agent.api import create_app


@dataclass
class FakeCmdResult:
    success: bool
    output: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0

    def __post_init__(self):
        if not self.stdout:
            self.stdout = self.output


@pytest.fixture
def anra_client():
    app = create_app(role="anra")
    return TestClient(app)


@pytest.fixture
def anda_client():
    app = create_app(role="anda")
    return TestClient(app)


@pytest.fixture
def anpa_client():
    app = create_app(role="anpa")
    return TestClient(app)


class TestChatRouting:
    """Verify chat endpoint routes simple vs complex queries."""

    def test_simple_query_does_not_invoke_swarm(self, anra_client):
        """Simple queries should NOT trigger swarm creation."""
        with patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.swarm.is_complex_query", return_value=False):
            resp = anra_client.post("/api/chat", json={"message": "list alarms"})
            assert resp.status_code == 200
            body = resp.json()
            # Should not be swarm mode
            assert body.get("mode") != "swarm"

    def test_complex_query_routes_to_swarm(self, anra_client):
        """Complex queries should attempt swarm."""
        mock_swarm_instance = MagicMock()
        mock_swarm_instance.return_value = "Swarm diagnosis: root cause is SMF upgrade"
        mock_swarm_instance.__str__ = MagicMock(return_value="Swarm diagnosis: root cause is SMF upgrade")

        with (
            patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.swarm.is_complex_query", return_value=True),
            patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.swarm.create_ano_swarm", return_value=mock_swarm_instance),
        ):
            resp = anra_client.post(
                "/api/chat",
                json={"message": "why did the deployment cause alarms?"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["mode"] == "swarm"
            assert "SMF upgrade" in body["response"]


class TestCrossAgentEndpoints:
    """Verify the API endpoints that cross-agent tools call actually exist and respond."""

    def test_anra_exposes_alarms_endpoint(self, anra_client):
        resp = anra_client.get("/api/alarms")
        assert resp.status_code == 200

    def test_anra_exposes_nodes_endpoint(self, anra_client):
        resp = anra_client.get("/api/nodes")
        assert resp.status_code == 200

    def test_anda_exposes_deployments_endpoint(self, anda_client):
        resp = anda_client.get("/api/deployments")
        assert resp.status_code == 200

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.routers.provisioning.run_cmd")
    def test_anpa_exposes_provisioning_endpoint(self, mock_run, anpa_client):
        mock_run.return_value = FakeCmdResult(success=True, output='{"items":[]}')
        resp = anpa_client.get("/api/provisioning/requests")
        assert resp.status_code == 200

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.routers.inventory.run_cmd")
    def test_anpa_exposes_inventory_endpoint(self, mock_run, anpa_client):
        mock_run.return_value = FakeCmdResult(success=True, output='{"items":[]}')
        resp = anpa_client.get("/api/inventory")
        assert resp.status_code == 200


class TestCrossAgentToolsEndToEnd:
    """Simulate what happens when a cross-agent tool makes an HTTP call."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent.run_cmd")
    def test_anra_queries_anda_deployments(self, mock_run):
        """ANRA asks ANDA for recent deployments — simulates the full flow."""
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent import (
            ask_anda_recent_deployments,
        )

        mock_run.return_value = FakeCmdResult(
            success=True,
            output='{"plans":[{"name":"smf-upgrade","status":"Completed","timestamp":"2026-05-25T20:00:00Z"}]}',
        )
        result = ask_anda_recent_deployments(namespace="core")

        # Verify correct URL constructed
        cmd = mock_run.call_args[0][0]
        assert "anda.anda-system.svc:8080" in cmd
        assert "namespace=core" in cmd
        # Verify response is usable
        assert "smf-upgrade" in result

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools_cross_agent.run_cmd")
    def test_anpa_queries_anra_for_node_health(self, mock_run):
        """ANPA asks ANRA if a node is healthy — used during failure diagnosis."""
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools_cross_agent import (
            ask_anra_node_health,
        )

        mock_run.return_value = FakeCmdResult(
            success=True,
            output='{"node":"worker-003","conditions":[{"type":"Ready","status":"False"}],"alarms":["du_cpu_overload"]}',
        )
        result = ask_anra_node_health(node_name="worker-003")

        cmd = mock_run.call_args[0][0]
        assert "anra.anra-system.svc:8080" in cmd
        assert "worker-003" in cmd
        assert "du_cpu_overload" in result


class TestTrendDetectionIntegration:
    """Verify trend detection works end-to-end with the monitor's recording."""

    def test_record_and_detect_flow(self):
        """Simulate what the monitor loop does: record alarms, then detect trends."""
        from datetime import datetime, timedelta

        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.trend import (
            clear_history,
            detect_escalating_alarms,
            record_alarm,
        )

        clear_history()
        now = datetime.utcnow()

        # Simulate: 3 firings yesterday, 8 firings today
        for i in range(3):
            record_alarm("ptp_drift", timestamp=now - timedelta(hours=30 + i))
        for i in range(8):
            record_alarm("ptp_drift", timestamp=now - timedelta(hours=i + 1))

        escalating = detect_escalating_alarms()
        assert len(escalating) == 1
        assert escalating[0]["alarm"] == "ptp_drift"
        assert escalating[0]["trend"] == "escalating"
        assert escalating[0]["ratio"] > 2.0


class TestFailureHandlerIntegration:
    """Verify the reconciler → failure handler path works."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler.Agent")
    def test_failure_handler_receives_correct_context(self, MockAgent):
        """When reconciler hits max retries, failure handler gets full context."""
        mock_instance = MagicMock()
        mock_instance.return_value = "Diagnosis: disk failure on worker-003"
        MockAgent.return_value = mock_instance

        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler import (
            handle_provisioning_failure,
        )

        result = handle_provisioning_failure(
            name="req-001",
            namespace="tink-system",
            spec={"nodes": [{"hostname": "worker-003"}]},
            phase="Provisioning",
            error="Tinkerbell workflow STATE_FAILED",
        )

        assert "disk failure" in result
        # Verify the prompt sent to the agent contains all context
        prompt = mock_instance.call_args[0][0]
        assert "req-001" in prompt
        assert "worker-003" in prompt
        assert "STATE_FAILED" in prompt


class TestAllRolesStartCleanly:
    """Verify all three roles create apps without import errors."""

    def test_anra_app_starts(self, anra_client):
        resp = anra_client.get("/health")
        assert resp.status_code == 200

    def test_anda_app_starts(self, anda_client):
        resp = anda_client.get("/health")
        assert resp.status_code == 200

    def test_anpa_app_starts(self, anpa_client):
        resp = anpa_client.get("/health")
        assert resp.status_code == 200
