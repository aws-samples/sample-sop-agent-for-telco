# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for graph_conditions: AND-join and retry-limit edge predicates.

graph_conditions imports strands.multiagent.base at load, which the conftest
MagicMock shim does NOT provide, so conftest gates this file out on SDK-less
sandboxes (collect_ignore_glob) -- same as test_sop_graph.
"""

from unittest.mock import MagicMock

from strands.multiagent.base import Status

from amzn_cse_telco_autonomous_network_agents_app.agent.graph_conditions import (
    _all_upstreams_passed,
    _corrector_made_changes,
    _needs_correction,
)


class TestAllUpstreamsPassed:
    def _make_state(self, results: dict):
        state = MagicMock(spec=["results"])
        state.results = results
        return state

    def test_returns_true_when_all_completed(self):
        nr_a = MagicMock()
        nr_a.status = Status.COMPLETED
        nr_b = MagicMock()
        nr_b.status = Status.COMPLETED
        state = self._make_state({"node_a": nr_a, "node_b": nr_b})
        assert _all_upstreams_passed(["node_a", "node_b"])(state) is True

    def test_returns_false_when_one_missing(self):
        nr_a = MagicMock()
        nr_a.status = Status.COMPLETED
        state = self._make_state({"node_a": nr_a})
        assert _all_upstreams_passed(["node_a", "node_b"])(state) is False

    def test_returns_false_when_one_failed(self):
        nr_a = MagicMock()
        nr_a.status = Status.COMPLETED
        nr_b = MagicMock()
        nr_b.status = Status.FAILED
        state = self._make_state({"node_a": nr_a, "node_b": nr_b})
        assert _all_upstreams_passed(["node_a", "node_b"])(state) is False

    def test_single_node_works(self):
        nr = MagicMock()
        nr.status = Status.COMPLETED
        state = self._make_state({"node_a": nr})
        assert _all_upstreams_passed(["node_a"])(state) is True

    def test_empty_list_returns_true(self):
        state = self._make_state({})
        assert _all_upstreams_passed([])(state) is True


class TestCorrectorMadeChanges:
    """Tests for _corrector_made_changes edge condition."""

    def _make_state(self, node_id, text):
        from strands.agent.agent_result import AgentResult
        from strands.types.content import ContentBlock, Message

        state = MagicMock()
        ar = AgentResult(
            stop_reason="end_turn",
            message=Message(role="assistant", content=[ContentBlock(text=text)]),
            state={},
            metrics={},
        )
        nr = MagicMock()
        nr.status = Status.COMPLETED
        nr.get_agent_results = MagicMock(return_value=[ar])
        # GraphState.results is a dict
        result_mock = MagicMock()
        result_mock.status = Status.COMPLETED
        result_mock.get_agent_results.return_value = [ar]
        state.results = {node_id: result_mock}
        return state

    def test_returns_true_when_sop_patched(self):
        cond = _corrector_made_changes("correct-04")
        state = self._make_state("correct-04", "SOP patched: 04-app-config.md\nFailures addressed: 2")
        assert cond(state) is True

    def test_returns_false_when_skipped(self):
        cond = _corrector_made_changes("correct-04")
        state = self._make_state("correct-04", "No actionable failures found — skipping SOP patch.")
        assert cond(state) is False

    def test_returns_false_when_node_missing(self):
        cond = _corrector_made_changes("correct-04")
        state = MagicMock()
        state.results = {}
        assert cond(state) is False


class TestNeedsCorrectionRetryLimit:
    """Tests for _needs_correction retry cap."""

    def _make_state(self, eval_id, text):
        from strands.agent.agent_result import AgentResult
        from strands.types.content import ContentBlock, Message

        ar = AgentResult(
            stop_reason="end_turn",
            message=Message(role="assistant", content=[ContentBlock(text=text)]),
            state={},
            metrics={},
        )
        result_mock = MagicMock()
        result_mock.status = Status.COMPLETED
        result_mock.get_agent_results.return_value = [ar]
        state = MagicMock()
        state.results = {eval_id: result_mock}
        return state

    def test_allows_corrections_up_to_limit(self):
        cond = _needs_correction("eval-01", max_retries=2)
        state = self._make_state("eval-01", "FAIL: something\nNEEDS_CORRECTION:AGENT_FAULT")
        assert cond(state) is True  # attempt 1
        assert cond(state) is True  # attempt 2
        assert cond(state) is False  # attempt 3 — capped

    def test_no_correction_needed_doesnt_count(self):
        cond = _needs_correction("eval-01", max_retries=2)
        passing = self._make_state("eval-01", "PASS: all good")
        assert cond(passing) is False  # no correction needed, counter stays 0
        failing = self._make_state("eval-01", "NEEDS_CORRECTION:AGENT_FAULT")
        assert cond(failing) is True  # attempt 1 — still allowed
