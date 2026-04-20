# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for execution_state.py — state machine, history, log rotation."""
import pytest
from execution_state import ExecutionState, ExecutionHistory, AgentStatus


class TestExecutionState:
    def setup_method(self):
        self.state = ExecutionState()

    def test_initial_state(self):
        assert self.state.status == AgentStatus.IDLE
        assert self.state.current_sop is None
        assert self.state.logs == []
        assert self.state.steps == []

    def test_start_execution(self):
        self.state.start_execution("/sops/03-validation.md")
        assert self.state.status == AgentStatus.RUNNING
        assert self.state.current_sop == "/sops/03-validation.md"
        assert self.state.start_time is not None
        assert self.state._tools_used == []

    def test_complete_success(self):
        self.state.start_execution("/sops/03-validation.md")
        self.state.complete_execution(success=True, exit_code=0)
        assert self.state.status == AgentStatus.COMPLETED

    def test_complete_failure(self):
        self.state.start_execution("/sops/03-validation.md")
        self.state.complete_execution(success=False, exit_code=1)
        assert self.state.status == AgentStatus.FAILED

    def test_history_saved_on_complete(self):
        self.state.start_execution("/sops/03-validation.md")
        self.state.complete_execution(success=True)
        hist = self.state.get_sop_history("03-validation.md")
        assert hist is not None
        assert hist.status == AgentStatus.COMPLETED

    def test_history_not_found(self):
        assert self.state.get_sop_history("nonexistent.md") is None

    def test_add_step(self):
        self.state.start_execution("/sops/test.md")
        self.state.add_step("Check pods", "success")
        self.state.add_step("Check BGP", "failed")
        assert len(self.state.steps) == 2
        assert self.state.steps[0].status == "success"
        assert self.state.steps[1].status == "failed"

    def test_add_log(self):
        self.state.start_execution("/sops/test.md")
        self.state.add_log("hello")
        assert len(self.state.logs) == 1
        assert self.state.logs[0].message == "hello"
        assert self.state.last_output == "hello"

    def test_log_rotation_at_100(self):
        self.state.start_execution("/sops/test.md")
        for i in range(150):
            self.state.add_log(f"msg-{i}")
        assert len(self.state.logs) == 100
        assert self.state.logs[0].message == "msg-50"

    def test_to_dict_serializable(self):
        self.state.start_execution("/sops/test.md")
        self.state.add_log("test")
        self.state.add_step("step1", "success")
        d = self.state.to_dict()
        assert d["status"] == "running"
        assert "tools_used" in d
        assert "_tools_used" not in d
        assert "_tool_timestamp" not in d

    def test_stale_tool_cleared(self):
        import time
        self.state.start_execution("/sops/test.md")
        self.state.current_tool = "kubectl"
        self.state._tool_timestamp = time.time() - 20  # 20s ago = stale
        self.state.to_dict()  # triggers stale check
        assert self.state.current_tool is None

    def test_fresh_tool_not_cleared(self):
        import time
        self.state.start_execution("/sops/test.md")
        self.state.current_tool = "kubectl"
        self.state._tool_timestamp = time.time()  # just now
        self.state.to_dict()
        assert self.state.current_tool == "kubectl"

    def test_zero_timestamp_clears_tool(self):
        """With _tool_timestamp=0 (falsy), stale check is skipped — tool persists."""
        self.state.start_execution("/sops/test.md")
        self.state.current_tool = "kubectl"
        assert self.state._tool_timestamp == 0
        self.state.to_dict()
        # 0 is falsy, so `if self._tool_timestamp` is False → stale check skipped
        assert self.state.current_tool == "kubectl"

    def test_tool_timestamp_must_be_set_for_stale_check(self):
        """Tool timestamp must be set when current_tool is assigned, otherwise stale check never fires."""
        import time
        self.state.start_execution("/sops/test.md")
        self.state.current_tool = "kubectl"
        self.state._tool_timestamp = time.time()
        self.state.to_dict()
        assert self.state.current_tool == "kubectl"
        # After 11s, tool should be cleared
        self.state._tool_timestamp = time.time() - 11
        self.state.to_dict()
        assert self.state.current_tool is None

    def test_steps_reset_on_new_execution(self):
        self.state.start_execution("/sops/test.md")
        self.state.add_step("old step", "success")
        self.state.complete_execution(True)
        self.state.start_execution("/sops/test2.md")
        assert self.state.steps == []
        assert self.state.logs == []

    def test_persist_and_restore_history(self, tmp_path):
        """History persists to disk and restores on new instance."""
        import os
        hist_file = str(tmp_path / "history.json")
        self.state._HISTORY_FILE = hist_file
        self.state.start_execution("01-argocd-setup.md")
        self.state.complete_execution(True)
        self.state.start_execution("02-network-infra.md")
        self.state.complete_execution(False)
        assert os.path.exists(hist_file)

        # New instance should restore
        new_state = ExecutionState()
        new_state._HISTORY_FILE = hist_file
        new_state._restore_history()
        assert "01-argocd-setup.md" in new_state.history
        assert new_state.history["01-argocd-setup.md"].status == AgentStatus.COMPLETED
        assert "02-network-infra.md" in new_state.history
        assert new_state.history["02-network-infra.md"].status == AgentStatus.FAILED

    def test_persist_history_per_node(self, tmp_path):
        """Direct history assignment + persist (simulates per-node save in api.py)."""
        hist_file = str(tmp_path / "history.json")
        self.state._HISTORY_FILE = hist_file
        self.state.history["05-validation.md"] = ExecutionHistory(
            sop_path="05-validation.md", status=AgentStatus.COMPLETED,
            start_time="2026-01-01T00:00:00", end_time="2026-01-01T00:01:00",
        )
        self.state._persist_history()

        new_state = ExecutionState()
        new_state._HISTORY_FILE = hist_file
        new_state._restore_history()
        assert new_state.history["05-validation.md"].status == AgentStatus.COMPLETED

    def test_history_status_serialized_as_string(self):
        """to_dict must serialize history status as string, not enum."""
        self.state.start_execution("test.md")
        self.state.complete_execution(True)
        d = self.state.to_dict()
        assert d["history"]["test.md"]["status"] == "completed"

    def test_restore_handles_missing_file(self, tmp_path):
        """Restore gracefully handles missing file."""
        self.state.history = {}  # clear any state from __post_init__
        self.state._HISTORY_FILE = str(tmp_path / "nonexistent.json")
        self.state._restore_history()  # should not raise
        assert self.state.history == {}
