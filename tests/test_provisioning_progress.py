# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the ANPA provisioning_progress module.

Covers the read-only k8s probes the state machine polls to advance a request
(Tinkerbell workflow success + EKS node readiness). run_cmd is patched at the
module the probes live in.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import (
    provisioning_progress,
)


def _r(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode, success=returncode == 0)


class TestProvisioningProgress:
    @patch.object(provisioning_progress, "run_cmd")
    def test_tinkerbell_all_success(self, mock_run):
        mock_run.return_value = _r(stdout="STATE_SUCCESS")
        assert provisioning_progress._check_tinkerbell_workflow("req", "ns") is True

    @patch.object(provisioning_progress, "run_cmd")
    def test_tinkerbell_pending_returns_false(self, mock_run):
        mock_run.return_value = _r(stdout="")
        assert provisioning_progress._check_tinkerbell_workflow("req", "ns") is False

    @patch.object(provisioning_progress, "run_cmd")
    def test_tinkerbell_failed_raises(self, mock_run):
        mock_run.return_value = _r(stdout="STATE_FAILED")
        with pytest.raises(RuntimeError, match="workflow failed"):
            provisioning_progress._check_tinkerbell_workflow("req", "ns")

    @patch.object(provisioning_progress, "run_cmd")
    def test_eks_node_ready_true(self, mock_run):
        mock_run.return_value = _r(stdout="True")
        assert provisioning_progress._check_eks_node_ready("req", {"hostname": "n1"}) is True

    @patch.object(provisioning_progress, "run_cmd")
    def test_eks_node_not_ready_false(self, mock_run):
        mock_run.return_value = _r(stdout="")
        assert provisioning_progress._check_eks_node_ready("req", {"hostname": "n1"}) is False

    @patch.object(provisioning_progress, "run_cmd")
    def test_multi_node_all_must_be_ready(self, mock_run):
        # first Ready, second not registered -> overall False
        mock_run.side_effect = [_r(stdout="True"), _r(stdout="")]
        spec = {"nodes": [{"hostname": "a"}, {"hostname": "b"}]}
        assert provisioning_progress._check_eks_node_ready("req", spec) is False
