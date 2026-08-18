# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the ANPA provisioning policy engine.

All functions under test are *pure* (no I/O, no side effects, no cluster
access), so the vast majority of tests need no mocking at all.
"""

from datetime import datetime, timezone

import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub heavy transitive dependencies that are unavailable in plain unit-test
# environments (CI Docker image has the full install; local Python 3.7 does not).
# The policy module itself has no runtime dependency on strands/fastapi/pydantic.
# ---------------------------------------------------------------------------
# Only stub strands — the package that isn't available in lightweight test
# environments.  All other transitive imports (yaml, fastapi, etc.) are
# either stdlib or installed as test dependencies.
if "strands" not in sys.modules:
    sys.modules["strands"] = MagicMock()

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.policy import (
    get_os_image,
    get_provision_wave,
    is_in_maintenance_window,
    should_deprovision,
    should_provision,
)


# ---------------------------------------------------------------------------
# Test-data factories
# ---------------------------------------------------------------------------


def _server(
    phase: str = "Available",
    bmc_healthy: bool = True,
    not_ready_seconds: int = 0,
    hardware_fault: bool = False,
    role: str = "worker",
) -> dict:
    """Build a minimal server dict."""
    return {
        "phase": phase,
        "bmc_healthy": bmc_healthy,
        "not_ready_seconds": not_ready_seconds,
        "hardware_fault": hardware_fault,
        "role": role,
    }


def _cluster(
    current_nodes: int = 3,
    desired_nodes: int = 5,
    provisioning_count: int = 0,
) -> dict:
    """Build a minimal cluster-status dict."""
    return {
        "current_nodes": current_nodes,
        "desired_nodes": desired_nodes,
        "provisioning_count": provisioning_count,
    }


def _cfg(**kwargs) -> dict:
    """Build a policy config dict with sensible defaults."""
    defaults: dict = {
        "capacity_threshold": 1.0,
        "max_concurrent": 3,
        "not_ready_threshold_seconds": 300,
        "over_provision_buffer": 0,
        "maintenance_windows": [],
    }
    defaults.update(kwargs)
    return defaults


def _window_now(duration_hours: int = 2) -> dict:
    """Return a maintenance window that covers the current UTC time."""
    now = datetime.now(timezone.utc)
    return {
        "day_of_week": now.isoweekday(),
        "start_hour": now.hour,
        "duration_hours": duration_hours,
    }


def _window_other_day() -> dict:
    """Return a maintenance window on a day that is NOT today."""
    today = datetime.now(timezone.utc).isoweekday()
    other = (today % 7) + 1   # cycles 1-7, always != today
    return {"day_of_week": other, "start_hour": 0, "duration_hours": 1}


# ===========================================================================
# Test suite
# ===========================================================================


class TestAnpaPolicy:
    """Tests for the ANPA policy engine pure functions."""

    # ------------------------------------------------------------------
    # should_provision — positive paths
    # ------------------------------------------------------------------

    def test_should_provision_available_server(self):
        """Available server with capacity needed returns True."""
        ok, reason = should_provision(_server(), _cluster(), _cfg())
        assert ok is True
        assert "passed" in reason.lower()

    def test_should_provision_one_below_max_concurrent(self):
        """Returns True when provisioning_count is one below max_concurrent."""
        ok, _ = should_provision(
            _server(),
            _cluster(provisioning_count=2),
            _cfg(max_concurrent=3),
        )
        assert ok is True

    # ------------------------------------------------------------------
    # should_provision — negative paths
    # ------------------------------------------------------------------

    def test_should_not_provision_during_maintenance(self):
        """A window matching the current UTC time blocks provisioning."""
        ok, reason = should_provision(
            _server(),
            _cluster(),
            _cfg(maintenance_windows=[_window_now()]),
        )
        assert ok is False
        assert "maintenance" in reason.lower()

    def test_should_not_provision_at_max_concurrent(self):
        """Returns False when provisioning_count equals max_concurrent."""
        ok, reason = should_provision(
            _server(),
            _cluster(provisioning_count=3),
            _cfg(max_concurrent=3),
        )
        assert ok is False
        assert "max concurrent" in reason.lower()

    def test_should_not_provision_non_available_phase(self):
        """Non-Available phase (e.g. Provisioned) is rejected immediately."""
        ok, reason = should_provision(
            _server(phase="Provisioned"),
            _cluster(),
            _cfg(),
        )
        assert ok is False
        assert "phase" in reason.lower()

    def test_should_not_provision_unhealthy_bmc(self):
        """BMC unhealthy blocks provisioning regardless of capacity."""
        ok, reason = should_provision(
            _server(bmc_healthy=False),
            _cluster(),
            _cfg(),
        )
        assert ok is False
        assert "bmc" in reason.lower()

    def test_should_not_provision_cluster_at_capacity(self):
        """Returns False when current_nodes / desired_nodes >= threshold."""
        ok, reason = should_provision(
            _server(),
            _cluster(current_nodes=5, desired_nodes=5),
            _cfg(capacity_threshold=1.0),
        )
        assert ok is False
        assert "capacity" in reason.lower()

    def test_should_not_provision_zero_desired_nodes(self):
        """Returns False when desired_nodes is 0 and cluster has nodes."""
        ok, _ = should_provision(
            _server(),
            _cluster(current_nodes=2, desired_nodes=0),
            _cfg(),
        )
        assert ok is False

    # ------------------------------------------------------------------
    # should_deprovision — positive paths
    # ------------------------------------------------------------------

    def test_should_deprovision_not_ready_node(self):
        """NotReady duration exceeding the threshold triggers deprovisioning."""
        ok, reason = should_deprovision(
            _server(not_ready_seconds=400),
            _cluster(),
            _cfg(not_ready_threshold_seconds=300),
        )
        assert ok is True
        assert "notready" in reason.lower().replace(" ", "")

    def test_should_deprovision_hardware_fault(self):
        """A hardware_fault flag triggers deprovisioning immediately."""
        ok, reason = should_deprovision(
            _server(hardware_fault=True),
            _cluster(),
            _cfg(),
        )
        assert ok is True
        assert "fault" in reason.lower()

    def test_should_deprovision_over_provisioned(self):
        """Over-provisioned cluster (above desired + buffer) triggers removal."""
        ok, reason = should_deprovision(
            _server(),
            _cluster(current_nodes=6, desired_nodes=5),
            _cfg(over_provision_buffer=0),
        )
        assert ok is True
        assert "over" in reason.lower() or "provisioned" in reason.lower()

    # ------------------------------------------------------------------
    # should_deprovision — negative paths
    # ------------------------------------------------------------------

    def test_should_not_deprovision_healthy_node(self):
        """No deprovision conditions met → returns False."""
        ok, _ = should_deprovision(_server(), _cluster(), _cfg())
        assert ok is False

    def test_should_not_deprovision_within_buffer(self):
        """current_nodes within desired + buffer is tolerated."""
        ok, _ = should_deprovision(
            _server(),
            _cluster(current_nodes=6, desired_nodes=5),
            _cfg(over_provision_buffer=1),
        )
        assert ok is False

    # ------------------------------------------------------------------
    # get_provision_wave — batching
    # ------------------------------------------------------------------

    def test_get_provision_wave_batching(self):
        """7 servers with max_concurrent=3 produces waves of sizes [3, 3, 1]."""
        servers = [{"id": i} for i in range(7)]
        waves = get_provision_wave(servers, max_concurrent=3)
        assert len(waves) == 3
        assert len(waves[0]) == 3
        assert len(waves[1]) == 3
        assert len(waves[2]) == 1

    def test_get_provision_wave_exact_fit(self):
        """6 servers with max_concurrent=3 produces 2 waves of exactly 3."""
        servers = [{"id": i} for i in range(6)]
        waves = get_provision_wave(servers, max_concurrent=3)
        assert len(waves) == 2
        assert all(len(w) == 3 for w in waves)

    def test_get_provision_wave_single_server(self):
        """A single server produces exactly one wave of one."""
        waves = get_provision_wave([{"id": 0}], max_concurrent=3)
        assert len(waves) == 1
        assert len(waves[0]) == 1

    def test_get_provision_wave_empty_list(self):
        """Empty input produces an empty list of waves."""
        assert get_provision_wave([], max_concurrent=3) == []

    def test_get_provision_wave_preserves_order(self):
        """Servers appear in the same order across waves."""
        servers = [{"id": i} for i in range(5)]
        waves = get_provision_wave(servers, max_concurrent=2)
        flat = [s for wave in waves for s in wave]
        assert flat == servers

    def test_get_provision_wave_invalid_max_concurrent(self):
        """max_concurrent < 1 raises ValueError."""
        with pytest.raises(ValueError):
            get_provision_wave([{"id": 0}], max_concurrent=0)

    # ------------------------------------------------------------------
    # get_os_image
    # ------------------------------------------------------------------

    def test_get_os_image_ran_worker(self):
        """ran-worker role resolves to the real-time kernel image."""
        image = get_os_image({"role": "ran-worker"}, {})
        assert image == "ubuntu-2204-eks-hybrid-rt"

    def test_get_os_image_default(self):
        """An unknown role falls back to the default Ubuntu EKS hybrid image."""
        image = get_os_image({"role": "unknown-role-xyz"}, {})
        assert image == "ubuntu-2204-eks-hybrid"

    def test_get_os_image_caller_override(self):
        """Caller-supplied image_profiles take precedence over built-in defaults."""
        image = get_os_image(
            {"role": "worker"},
            {"worker": "custom-worker-image-v2"},
        )
        assert image == "custom-worker-image-v2"

    def test_get_os_image_no_role_defaults_to_worker(self):
        """A server dict with no role key defaults to the worker (standard) image."""
        image = get_os_image({}, {})
        assert image == "ubuntu-2204-eks-hybrid"

    def test_get_os_image_worker_role(self):
        """Standard worker role returns the default EKS hybrid image."""
        image = get_os_image({"role": "worker"}, {})
        assert image == "ubuntu-2204-eks-hybrid"

    # ------------------------------------------------------------------
    # is_in_maintenance_window
    # ------------------------------------------------------------------

    def test_is_not_in_maintenance_window(self):
        """Returns False when the window is scheduled on a different day."""
        windows = [_window_other_day()]
        assert is_in_maintenance_window(windows) is False

    def test_is_in_maintenance_window_true(self):
        """Returns True when the current UTC time falls inside a window."""
        assert is_in_maintenance_window([_window_now()]) is True

    def test_is_in_maintenance_window_empty_list(self):
        """Returns False for an empty window list (no windows = no block)."""
        assert is_in_maintenance_window([]) is False

    def test_is_in_maintenance_window_skips_malformed(self):
        """Malformed window dicts are logged and skipped without raising."""
        windows = [
            {"bad_key": "value"},          # missing all required keys
            {"day_of_week": 1},            # missing start_hour, duration_hours
        ]
        result = is_in_maintenance_window(windows)
        assert isinstance(result, bool)   # no exception; result is False

    def test_is_in_maintenance_window_zero_duration_skipped(self):
        """A window with duration_hours=0 is skipped (non-positive duration)."""
        now = datetime.now(timezone.utc)
        window = {
            "day_of_week": now.isoweekday(),
            "start_hour": now.hour,
            "duration_hours": 0,
        }
        assert is_in_maintenance_window([window]) is False
