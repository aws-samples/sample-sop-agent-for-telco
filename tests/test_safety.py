# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for agents/remediation/safety.py — guardrails and rate limiting."""
import time

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.remediation.safety import (
    RateLimiter,
    is_command_blocked,
    is_namespace_protected,
)


class TestIsCommandBlocked:
    def test_scale_to_zero_blocked(self):
        assert is_command_blocked("kubectl scale deploy/x --replicas 0 -n srsran") is True

    def test_delete_deployment_blocked(self):
        assert is_command_blocked("kubectl delete deployment my-app -n open5gs") is True

    def test_delete_namespace_blocked(self):
        assert is_command_blocked("kubectl delete namespace srsran") is True

    def test_get_pods_allowed(self):
        assert is_command_blocked("kubectl get pods -n srsran") is False

    def test_restart_allowed(self):
        assert is_command_blocked("kubectl rollout restart deploy/amf -n open5gs") is False

    def test_case_insensitive(self):
        assert is_command_blocked("kubectl DELETE DEPLOYMENT x") is True

    def test_scale_nonzero_allowed(self):
        assert is_command_blocked("kubectl scale deploy/x --replicas 2 -n srsran") is False


class TestIsNamespaceProtected:
    def test_srsran_protected(self):
        assert is_namespace_protected("srsran") is True

    def test_open5gs_protected(self):
        assert is_namespace_protected("open5gs") is True

    def test_kube_system_protected(self):
        assert is_namespace_protected("kube-system") is True

    def test_anra_protected(self):
        assert is_namespace_protected("anra") is True

    def test_custom_ns_not_protected(self):
        assert is_namespace_protected("my-app") is False

    def test_default_not_protected(self):
        assert is_namespace_protected("default") is False


class TestRateLimiter:
    def test_allows_within_limit(self):
        rl = RateLimiter(max_per_hour=3)
        assert rl.allow() is True
        assert rl.allow() is True
        assert rl.allow() is True

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_per_hour=2)
        rl.allow()
        rl.allow()
        assert rl.allow() is False

    def test_remaining_count(self):
        rl = RateLimiter(max_per_hour=5)
        assert rl.remaining == 5
        rl.allow()
        assert rl.remaining == 4

    def test_resets_after_hour(self):
        rl = RateLimiter(max_per_hour=1)
        rl.allow()
        assert rl.allow() is False
        # Simulate time passing
        rl._reset_time = time.time() - 3601
        assert rl.allow() is True
