"""Regression tests for the state.py thread-safety fix.

The monitor background thread mutates these collections concurrently with
FastAPI handlers reading them. Without the lock, ``push_alarm``'s
find-replace-append-pop sequence is non-atomic and a parallel reader can
observe partial state or get an IndexError on slicing during a pop.

These tests stress-drive writers from multiple threads and verify that the
final state and concurrent snapshots are consistent.
"""

import threading

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.core import state


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test starts with empty collections."""
    with state._lock:
        state._alarms.clear()
        state._active_alarm_names.clear()
        state._executions.clear()
        state._correlations.clear()
        state._activity.clear()
        state._pending_approvals.clear()


def test_push_alarm_concurrent_writers_no_data_loss() -> None:
    """N writers push N distinct alarms each; final state must contain min(N*N, 200) entries."""
    n_writers = 8
    per_writer = 25

    def worker(idx: int) -> None:
        for j in range(per_writer):
            state.push_alarm({"name": f"writer-{idx}-alarm-{j}", "severity": "warning"})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = state.snapshot_alarms()
    # 8 writers * 25 alarms = 200 distinct alarms; bounded list cap is 200.
    assert len(final) == min(n_writers * per_writer, 200)
    # Every entry must be a complete dict (no partial state).
    assert all("name" in a and "severity" in a and "timestamp" in a for a in final)


def test_push_alarm_dedup_replaces_in_place() -> None:
    """Same alarm name pushed twice replaces the existing entry, not a new append."""
    state.push_alarm({"name": "foo", "severity": "warning"})
    state.push_alarm({"name": "foo", "severity": "critical"})
    snap = state.snapshot_alarms()
    assert len(snap) == 1
    assert snap[0]["severity"] == "critical"


def test_concurrent_push_alarm_dedup_invariant() -> None:
    """Targets the find-replace-append-trim path that motivated the lock.

    push_alarm has the only compound writer logic in this module: iterate
    _alarms looking for a matching name, replace if found, otherwise append
    + trim. Without the lock, two writers pushing the same name can race
    past the dedup check and both append. Single-append writers like
    push_execution are individually atomic under CPython's GIL and don't
    catch a regression of the lock removal.

    Four writers each push the same five alarm names in a loop. Final
    snapshot must contain exactly five entries (one per name, deduped) and
    the most-recent severity per name (never a torn dict).
    """
    n_writers = 4
    iterations = 50
    names = [f"alarm-{i}" for i in range(5)]
    barrier = threading.Barrier(n_writers)

    def worker(writer_idx: int) -> None:
        barrier.wait()  # maximize contention by starting all writers together
        for it in range(iterations):
            for name in names:
                state.push_alarm({"name": name, "severity": f"writer-{writer_idx}-it-{it}"})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snap = state.snapshot_alarms()
    # Dedup invariant: one entry per name, regardless of how many writers raced.
    assert len(snap) == len(names), f"dedup race: expected {len(names)} entries, got {len(snap)}"
    assert {a["name"] for a in snap} == set(names)
    # No torn dicts — every entry has both keys.
    assert all("name" in a and "severity" in a and "timestamp" in a for a in snap)


def test_pop_pending_approval_atomic() -> None:
    """pop_pending_approval is the atomic check-and-remove for the approval handler."""
    state.push_pending_approval("alpha", "sops/alpha.md", {"severity": "high", "source": "test"})
    state.push_pending_approval("beta", "sops/beta.md", {"severity": "low", "source": "test"})

    popped = state.pop_pending_approval("alpha")
    assert popped is not None
    assert popped["alarm_name"] == "alpha"
    assert popped["sop"] == "sops/alpha.md"

    # Second pop on the same key returns None (idempotent).
    assert state.pop_pending_approval("alpha") is None

    # Other entries unaffected.
    snap = state.snapshot_pending_approvals()
    assert "beta" in snap
    assert "alpha" not in snap


def test_snapshot_alarms_with_active_names_consistent_under_writers() -> None:
    """Combined snapshot must guarantee active_names ⊆ {a['name'] for a in alarms}.

    Two separate snapshot calls (snapshot_alarms then snapshot_active_alarm_names)
    are racy: a concurrent push_alarm between the calls can add a name to
    active_names whose alarm dict isn't in the alarms list, or a clear_alarms
    can drop a name whose alarm is still snapshotted. The combined helper takes
    the lock once for both reads.

    This test runs writers + churners + checkers concurrently and asserts the
    pair invariant holds. Without the combined helper this would break under
    contention.
    """
    stop = threading.Event()
    errors: list[str] = []
    names = [f"alarm-{i}" for i in range(8)]

    def writer() -> None:
        i = 0
        while not stop.is_set():
            state.push_alarm({"name": names[i % len(names)], "severity": "warning"})
            i += 1

    def churner() -> None:
        i = 0
        while not stop.is_set():
            if i % 10 == 0:
                state.clear_alarms({names[i % len(names)]})
            i += 1

    def checker() -> None:
        while not stop.is_set():
            alarms, active_names = state.snapshot_alarms_with_active_names()
            alarm_names = {a["name"] for a in alarms}
            missing = active_names - alarm_names
            if missing:
                errors.append(f"active names without alarm entries: {missing}")
                return

    threads = (
        [threading.Thread(target=writer) for _ in range(3)]
        + [threading.Thread(target=churner) for _ in range(2)]
        + [threading.Thread(target=checker) for _ in range(3)]
    )
    for t in threads:
        t.start()
    threading.Event().wait(0.2)
    stop.set()
    for t in threads:
        t.join()

    assert errors == [], errors[0]


def test_snapshot_list_is_independent_but_entries_are_aliased() -> None:
    """Snapshot is a SHALLOW copy: appending/removing from the snap list is safe,
    but the dict objects inside are the same references that live in _alarms.

    Document the contract explicitly so callers don't accidentally mutate
    snap[0]['severity'] = 'critical' and silently mutate live state under
    the eyes of any concurrent reader.
    """
    state.push_alarm({"name": "foo", "severity": "warning"})

    snap = state.snapshot_alarms()

    # List independence: appending to the snap doesn't grow the live list.
    snap.append({"name": "bar", "severity": "critical"})
    assert len(state.snapshot_alarms()) == 1

    # Entry aliasing: snap[0] IS the same dict object as _alarms[0].
    # Callers MUST NOT mutate dicts pulled from a snapshot.
    snap = state.snapshot_alarms()
    assert snap[0] is state.snapshot_alarms()[0]
