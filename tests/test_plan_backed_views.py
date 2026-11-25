"""The Assurance Agent reports what the Change Agent did, and only live alarms.

Approved remediations run in the Change Agent as DeploymentPlans. These tests
cover the dashboard views and Ask AI context that must read them, and the
monitor rule that keeps a symptom suppressed while its root is being handled.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.core import deployment_plans, executor, state
from amzn_cse_telco_autonomous_network_agents_app.agent.routers import agents, chat, timeline


def _plan(name, phase, created, alarm="free5gc_nf_unavailable", elapsed="86s", steps=16):
    status = {"phase": phase, "message": "All NFs deployed successfully" if phase == "Completed" else ""}
    if elapsed:
        status["sopExecution"] = {"amf": {"elapsed": elapsed, "status": phase, "stepsExecuted": steps}}
    return {
        "metadata": {"name": name, "creationTimestamp": created, "labels": {"alarm": alarm, "triggered-by": "anra"}},
        "spec": {
            "intent": "remediation",
            "networkFunctions": [{"name": "amf"}],
            "reason": f"Operator approved remediation for alarm: {alarm}",
            "sopPath": "/app/sops/day2-remediate/core/free5gc-nf-unavailable.md",
            "triggeredBy": "anra",
        },
        "status": status,
    }


@pytest.fixture
def kubectl(monkeypatch):
    calls = []

    def install(items=None, success=True):
        def fake_run_cmd(cmd, timeout=None):
            calls.append(cmd)
            return SimpleNamespace(success=success, stdout=json.dumps({"items": items or []}))

        monkeypatch.setattr(executor, "run_cmd", fake_run_cmd)
        deployment_plans._reset_cache_for_tests()
        return calls

    yield install
    deployment_plans._reset_cache_for_tests()


@pytest.fixture
def clean_state():
    with state._lock:
        state._alarms.clear()
        state._active_alarm_names.clear()
        state._executions.clear()
        state._correlations.clear()
        state._pending_approvals.clear()
        state._withdrawn_approvals.clear()
        state._activity.clear()
    yield
    with state._lock:
        state._alarms.clear()
        state._active_alarm_names.clear()
        state._pending_approvals.clear()
        state._correlations.clear()
        state._activity.clear()


DONE = _plan("anra-amf-1", "Completed", "2026-11-25T19:11:33Z")
RUNNING = _plan("anra-amf-2", "InProgress", "2026-11-25T19:30:00Z", elapsed=None)


def test_active_deployment_sees_an_in_progress_plan_without_a_field_selector(kubectl):
    calls = kubectl([DONE, RUNNING])
    body = agents.get_active_deployment()
    assert body["active"] is True
    assert body["plan_name"] == "anra-amf-2"
    assert body["stage"] == "InProgress"
    assert body["sop"] == "day2-remediate/core/free5gc-nf-unavailable.md"
    assert [p["name"] for p in body["history"]] == ["anra-amf-2", "anra-amf-1"]
    assert all("--field-selector" not in c for c in calls)
    assert "safety_net" not in body


def test_active_deployment_keeps_history_after_completion(kubectl):
    kubectl([DONE])
    body = agents.get_active_deployment()
    assert body["active"] is False
    (row,) = body["history"]
    assert row["phase"] == "Completed" and row["elapsed_seconds"] == 86 and row["steps"] == 16
    assert row["finished"].startswith("2026-11-25T19:12:59")


def test_active_deployment_reports_unreadable_cluster(kubectl):
    kubectl(success=False)
    assert agents.get_active_deployment() == {"active": False, "history": [], "error": "DeploymentPlans unavailable"}


def test_track_record_comes_from_plans_with_no_invented_numbers(kubectl):
    kubectl([DONE, _plan("anra-amf-0", "Failed", "2026-11-25T18:00:00Z", elapsed="40s")])
    record = agents.get_track_record()
    assert record["incidents_handled"] == 2
    assert record["completed"] == 1 and record["escalated"] == 1
    assert record["sop_success_rate"] == 0.5
    assert record["avg_mttr_auto_seconds"] == 86
    assert "false_positive_rate" not in record and "avg_mttr_manual_seconds" not in record


def test_track_record_is_empty_not_invented_without_plans(kubectl):
    kubectl([])
    record = agents.get_track_record()
    assert record["incidents_handled"] == 0
    assert record["avg_mttr_auto_seconds"] is None
    assert record["sop_success_rate"] is None


def test_status_ignores_resolved_alarm_history(kubectl, clean_state):
    kubectl([DONE])
    state.push_alarm({"name": "free5gc_nf_unavailable", "severity": "critical"})
    state.clear_alarms(set())  # it stopped firing
    status = {a["name"]: a for a in agents.get_agent_status()["agents"]}
    assert status["ANRA"]["state"] == "idle"
    assert status["ANDA"]["state"] == "idle"


def test_status_reports_waiting_for_approval_and_a_running_plan(kubectl, clean_state):
    kubectl([RUNNING])
    state.push_alarm({"name": "free5gc_nf_unavailable", "severity": "critical"})
    state.push_pending_approval("free5gc_nf_unavailable", "/app/sops/x.md", {})
    status = {a["name"]: a for a in agents.get_agent_status()["agents"]}
    assert status["ANRA"]["state"] == "waiting"
    assert "free5gc_nf_unavailable" in status["ANRA"]["detail"]
    assert status["ANDA"]["state"] == "active"


def test_executions_and_activity_include_plan_outcomes(kubectl, clean_state):
    kubectl([DONE])
    state.push_activity("execute", "Operator approved — executing SOP for free5gc_nf_unavailable")
    execs = timeline.get_executions()["executions"]
    assert execs[-1]["result"] == "completed" and execs[-1]["plan"] == "anra-amf-1"
    messages = [a["message"] for a in timeline.get_activity()["activity"]]
    assert any("plan anra-amf-1 Completed in 86s, 16 steps" in m for m in messages)
    reasoning = agents.get_agent_reasoning()["entries"]
    assert any(e["agent"] == "anda" and "Completed" in e["message"] for e in reasoning)


def test_chat_context_uses_live_alarms_sops_and_plans(kubectl, clean_state, monkeypatch, tmp_path):
    kubectl([DONE])
    (tmp_path / "sops" / "day2-remediate" / "core").mkdir(parents=True)
    (tmp_path / "sops" / "day2-remediate" / "core" / "free5gc-nf-unavailable.md").write_text("# x")
    (tmp_path / "sops" / "TEMPLATE.md").write_text("# t")
    monkeypatch.setenv("SOP_REPO", str(tmp_path))
    monkeypatch.setenv("APPROVAL_MODE", "manual")
    monkeypatch.setattr(chat, "build_live_topology", lambda: {"summary": {"nf_count": 13}})
    monkeypatch.setattr(chat, "build_monitoring_stats_payload", lambda: {"tier1_rules": 5})
    state.push_alarm({"name": "Free5GCWorkshopPipelineTest", "severity": "info"})
    state.push_alarm({"name": "free5gc_nf_unavailable", "severity": "critical"})
    state.clear_alarms(set())  # both resolved
    state.push_correlation({"alarm": "free5gc_registration_unavailable", "action": "suppress", "root_cause": "free5gc_nf_unavailable"})

    context = chat.build_chat_context()
    assert "ALARMS FIRING NOW (0): []" in context
    assert "SOPs AVAILABLE (1): day2-remediate/core/free5gc-nf-unavailable.md" in context
    assert '"plan": "anra-amf-1"' in context and '"phase": "Completed"' in context
    assert '"alarm": "free5gc_registration_unavailable", "decision": "suppress"' in context
    assert "Network Assurance Agent" in context and "Remediation Agent" not in context
    assert "edge nodes" not in context


def test_chat_does_not_route_to_the_swarm_by_default():
    source = Path(chat.__file__).read_text()
    assert 'os.getenv("CHAT_SWARM", "0") == "1" and is_complex_query' in source


@pytest.fixture
def monitor():
    # Imported lazily: monitor loads its alarm catalog at import time, so a
    # module-level import here would load it before other tests set up config.
    from amzn_cse_telco_autonomous_network_agents_app.agent import monitor as mod

    return mod


@pytest.fixture
def suppressed(monitor):
    monitor._suppressed.clear()
    monitor._root_cleared_at.clear()
    monitor._active_sops.clear()
    monitor._suppressed["free5gc_registration_unavailable"] = "free5gc_nf_unavailable"
    yield
    monitor._suppressed.clear()
    monitor._root_cleared_at.clear()


def test_symptom_stays_suppressed_while_its_root_waits_for_approval(suppressed, monitor):
    firing = {"free5gc_nf_unavailable", "free5gc_registration_unavailable"}
    for t in (0, 15, 300):
        assert monitor._symptoms_to_reevaluate(firing, {"free5gc_nf_unavailable"}, t) == ([], [])
    # Root no longer firing but still pending approval
    firing = {"free5gc_registration_unavailable"}
    assert monitor._symptoms_to_reevaluate(firing, {"free5gc_nf_unavailable"}, 400) == ([], [])


def test_symptom_that_clears_during_the_grace_period_is_dropped(suppressed, monitor):
    firing = {"free5gc_registration_unavailable"}
    assert monitor._symptoms_to_reevaluate(firing, set(), 100) == ([], [])
    assert monitor._symptoms_to_reevaluate(firing, set(), 100 + monitor.REEVAL_GRACE_SECONDS - 1) == ([], [])
    assert monitor._symptoms_to_reevaluate(set(), set(), 150) == ([], ["free5gc_registration_unavailable"])


def test_symptom_still_firing_after_the_grace_period_is_raised(suppressed, monitor):
    firing = {"free5gc_registration_unavailable"}
    monitor._symptoms_to_reevaluate(firing, set(), 100)
    raise_now, drop = monitor._symptoms_to_reevaluate(firing, set(), 100 + monitor.REEVAL_GRACE_SECONDS)
    assert raise_now == [("free5gc_registration_unavailable", "free5gc_nf_unavailable")]
    assert drop == []


# ── Withdrawing cards whose alarm cleared before a decision ──


@pytest.fixture
def quiet(monitor):
    monitor._card_quiet_since.clear()
    yield monitor
    monitor._card_quiet_since.clear()


def test_card_is_withdrawn_after_its_alarm_is_quiet_for_the_grace_period(quiet):
    m = quiet
    pending = {"free5gc_registration_unavailable"}
    assert m._stale_approvals(set(), pending, 100) == []
    assert m._stale_approvals(set(), pending, 100 + m.WITHDRAW_AFTER_SECONDS - 1) == []
    assert m._stale_approvals(set(), pending, 100 + m.WITHDRAW_AFTER_SECONDS) == ["free5gc_registration_unavailable"]


def test_card_whose_alarm_fires_again_starts_over(quiet):
    m = quiet
    pending = {"free5gc_nf_unavailable"}
    m._stale_approvals(set(), pending, 0)
    m._stale_approvals({"free5gc_nf_unavailable"}, pending, 60)  # firing again
    assert m._stale_approvals(set(), pending, 61) == []  # quiet again from 61
    assert m._stale_approvals(set(), pending, 61 + m.WITHDRAW_AFTER_SECONDS - 1) == []
    assert m._stale_approvals(set(), pending, 61 + m.WITHDRAW_AFTER_SECONDS) == ["free5gc_nf_unavailable"]


def test_firing_alarm_and_pipeline_test_card_are_never_withdrawn(quiet):
    m = quiet
    pending = {"free5gc_nf_unavailable", "Free5GCWorkshopPipelineTest"}
    m._stale_approvals({"free5gc_nf_unavailable"}, pending, 0)
    assert m._stale_approvals({"free5gc_nf_unavailable"}, pending, 10_000) == []


def test_withdrawn_card_explains_a_late_decision(clean_state):
    from fastapi import HTTPException

    from amzn_cse_telco_autonomous_network_agents_app.agent.routers import approvals

    state.push_pending_approval("free5gc_registration_unavailable", "/app/sops/x.md", {})
    assert state.withdraw_pending_approval("free5gc_registration_unavailable") is not None
    assert state.snapshot_pending_approvals() == {}
    with pytest.raises(HTTPException) as err:
        approvals.approve(approvals.ApprovalRequest(alarm_name="free5gc_registration_unavailable", action="approve"))
    assert "withdrawn" in err.value.detail and "Nothing ran" in err.value.detail
    # A new proposal for the same alarm is a normal card again.
    state.push_pending_approval("free5gc_registration_unavailable", "/app/sops/x.md", {})
    assert not state.was_withdrawn("free5gc_registration_unavailable")
