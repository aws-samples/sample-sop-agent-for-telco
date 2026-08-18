# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for graph-based SOP orchestrator: node classes + builder logic.

Pure content-analysis tests live in test_sop_metadata.py and the edge-condition
tests in test_graph_conditions.py, mirroring the source module split.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from strands.types.content import ContentBlock

_SOP_GRAPH = "amzn_cse_telco_autonomous_network_agents_app.agent.sop_graph"

# ── Fixtures ──

SOPS_DIR = Path(__file__).parent.parent / "sops"


def _real_sop(name: str) -> str:
    return str(SOPS_DIR / name)


# Pure content-analysis tests (parse_sop_metadata / resolve_dependencies /
# select_model) moved to test_sop_metadata.py; the AND-join / retry-limit edge
# condition tests moved to test_graph_conditions.py, mirroring the source split.


# ── build_sop_graph (structure only, no execution) ──


class TestBuildSopGraph:
    """Test graph construction logic without actually building Graph objects."""

    def test_model_selection_uses_content(self):
        """Verify that build_sop_graph would select different models per SOP complexity."""
        from amzn_cse_telco_autonomous_network_agents_app.agent.sop_graph import (
            parse_sop_metadata,
            select_model,
        )

        deploy = parse_sop_metadata(_real_sop("day1-deploy/deploy-5g-core.md"))
        assert select_model(deploy, "haiku") == "haiku"

    def test_entry_points_are_nodes_without_incoming_edges(self):
        """Verify entry point detection logic."""
        from amzn_cse_telco_autonomous_network_agents_app.agent.sop_graph import (
            parse_sop_metadata,
            resolve_dependencies,
        )

        sop_paths = [str(p) for p in sorted(SOPS_DIR.glob("*.md"))]
        metas = [parse_sop_metadata(p) for p in sop_paths]
        edges = resolve_dependencies(metas)
        stem_set = {m["stem"] for m in metas}
        nodes_with_incoming = {to for _, to in edges if to in stem_set}
        entry_points = [m["stem"] for m in metas if m["stem"] not in nodes_with_incoming]
        # deploy-5g-core should be an entry point (no dependencies)
        assert len(entry_points) >= 1  # ANRA SOPs have no inter-SOP dependencies


# ── build_eval_loop (structure only) ──


class TestBuildEvalLoop:
    def test_eval_loop_needs_correction_condition(self):
        """Test the needs_correction condition logic directly."""
        from strands.multiagent.base import Status

        # Simulate eval result with NEEDS_CORRECTION
        mock_state = MagicMock(spec=["results"])
        mock_result = MagicMock()
        mock_result.status = Status.COMPLETED
        mock_agent_result = MagicMock()
        mock_agent_result.message.content = [ContentBlock(text="SteeringEff: 1.0\nSOPCompl: 0.4\n  FAIL: missing tools\nNEEDS_CORRECTION")]
        mock_result.get_agent_results.return_value = [mock_agent_result]
        mock_state.results = {"eval": mock_result}

        # The condition function checks for NEEDS_CORRECTION in eval output
        # We test the logic inline since build_eval_loop creates it internally
        r = mock_state.results.get("eval")
        assert r is not None
        assert r.status == Status.COMPLETED
        results = r.get_agent_results()
        has_correction = any("NEEDS_CORRECTION" in str(ar.message.content) for ar in results if ar.message)
        assert has_correction is True

    def test_eval_loop_passing_no_correction(self):
        """Test that passing eval does not trigger correction."""
        from strands.multiagent.base import Status

        mock_state = MagicMock(spec=["results"])
        mock_result = MagicMock()
        mock_result.status = Status.COMPLETED
        mock_agent_result = MagicMock()
        mock_agent_result.message.content = [ContentBlock(text="SteeringEff: 1.0\nSOPCompl: 1.0\n  PASS: all good")]
        mock_result.get_agent_results.return_value = [mock_agent_result]
        mock_state.results = {"eval": mock_result}

        r = mock_state.results.get("eval")
        results = r.get_agent_results()
        has_correction = any("NEEDS_CORRECTION" in str(ar.message.content) for ar in results if ar.message)
        assert has_correction is False

    def test_build_eval_loop_invokes_end_to_end(self):
        """Actually call build_eval_loop with its collaborators stubbed.

        Guards against a dropped module-level import (e.g. Path) that the
        condition-only tests above can't catch because they never invoke the
        function, and both sop_graph/sop_nodes sit outside mypy's scope.
        """
        with (
            patch(f"{_SOP_GRAPH}.setup_eval_telemetry", return_value=MagicMock()),
            patch(f"{_SOP_GRAPH}.create_sop_agent", return_value=MagicMock(name="agent")),
            patch(f"{_SOP_GRAPH}.EvalNode", return_value=MagicMock(name="eval")),
            patch(f"{_SOP_GRAPH}.CorrectorNode", return_value=MagicMock(name="corrector")),
            patch(f"{_SOP_GRAPH}.GraphBuilder") as mock_builder,
            patch(f"{_SOP_GRAPH}.parse_sop_metadata", return_value={"bash_blocks": 1, "lines": 10}),
        ):
            sentinel_graph = MagicMock(name="graph")
            mock_builder.return_value.build.return_value = sentinel_graph
            from amzn_cse_telco_autonomous_network_agents_app.agent.sop_graph import (
                build_eval_loop,
            )

            graph = build_eval_loop("day1-deploy/deploy-5g-core.md", no_steering=True)

        assert graph is sentinel_graph


# Node-class tests (TestClassifyFailure / TestEvalNodeStreaming /
# TestCorrectorNode) moved to test_sop_nodes.py alongside the classes they
# exercise. Edge-condition tests are in test_graph_conditions.py.
