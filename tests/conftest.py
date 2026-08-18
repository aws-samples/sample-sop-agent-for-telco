# ---------------------------------------------------------------------------
# Collection-time skips: modules that need SDK features unavailable in CI sandbox
# ---------------------------------------------------------------------------
import importlib

collect_ignore_glob = []

# pytest-asyncio not installed in CI sandbox — test_adaptive_steering uses @pytest.mark.asyncio
# throughout and cannot be collected without it
try:
    import pytest_asyncio  # noqa: F401
except ImportError:
    collect_ignore_glob.append("test_adaptive_steering.py")

# test_sop_graph.py + test_sop_nodes.py require both strands.multiagent.base
# (newer SDK than some sandbox machines provide) AND evals/sop_corrector.py
# (only on sys.path inside the hatch test env). test_sop_nodes imports sop_nodes,
# which runs the evals sys.path bootstrap and `from sop_corrector import ...` at
# module load, so it needs the same two-condition gate. Skip if either is missing.
try:
    importlib.import_module("strands.multiagent.base")
    import sop_corrector  # noqa: F401
except (ImportError, ModuleNotFoundError):
    collect_ignore_glob.append("test_sop_graph.py")
    collect_ignore_glob.append("test_sop_nodes.py")

# test_graph_conditions.py imports strands.multiagent.base (via graph_conditions)
# but NOT evals/sop_corrector, so it gates only on the SDK surface -- this lets it
# run in envs that have the SDK but not the evals path.
try:
    importlib.import_module("strands.multiagent.base")
except (ImportError, ModuleNotFoundError):
    collect_ignore_glob.append("test_graph_conditions.py")


# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock strands SDK if not installed (dev environment uses Python 3.7,
# production uses Python 3.11 + strands-agents in Docker).
# This allows tests for pure-logic modules (config, policy, orchestrator
# ordering) to run without the full runtime stack.
# ---------------------------------------------------------------------------
try:
    import strands  # noqa: F401
    # Verify it's a real package, not a stale mock
    import strands.types.tools  # noqa: F401
except (ImportError, ModuleNotFoundError):
    _mock_strands = MagicMock()
    _mock_strands.tool = lambda fn: fn  # @tool decorator is a no-op passthrough
    sys.modules["strands"] = _mock_strands
    sys.modules["strands.hooks"] = MagicMock()
    sys.modules["strands.models"] = MagicMock()
    sys.modules["strands.types"] = MagicMock()
    sys.modules["strands.types.tools"] = MagicMock()
    sys.modules["strands.agent"] = MagicMock()
    sys.modules["strands.agent.agent_result"] = MagicMock()
    sys.modules["strands_evals"] = MagicMock()
    sys.modules["strands_evals.telemetry"] = MagicMock()
    sys.modules["strands_evals.mappers"] = MagicMock()


@pytest.fixture(autouse=True)
def set_config_path(tmp_path):
    """Point config loader at a test config."""
    config = {
        "cluster": {"name": "test-cluster", "context": "test-ctx", "region": "us-west-1"},
        "bedrock": {"region": "us-west-2", "profile": "test-profile"},
        "monitoring": {
            "influxdb_url": "http://localhost:8086",
            "influxdb_token_secret": "test-token",
            "influxdb_org": "test",
            "influxdb_bucket": "test",
        },
        "nodes": [
            {
                "name": "worker-1",
                "oam_ip": "192.168.31.195",
                "ssm_id": "mi-aaa",
                "bmc": {"ip": "192.168.30.10", "type": "idrac", "username": "root", "password_secret": "bmc-creds"},
                "roles": ["upf"],
                "namespaces": ["open5gs"],
            },
            {
                "name": "worker-2",
                "oam_ip": "192.168.31.222",
                "ssm_id": "mi-bbb",
                "bmc": {"ip": "192.168.30.11", "type": "idrac", "username": "root", "password_secret": "bmc-creds"},
                "roles": ["du", "cu"],
                "namespaces": ["srsran"],
            },
        ],
        "alarms": [
            {"name": "du_cpu_overload", "layer": 3, "source": "ran", "field": "du_du_high_mac_dl_0_cpu_usage_percent",
             "condition": "> 80", "severity": "critical", "depends_on": [], "nf_scope": "per-node",
             "sop": "day2-remediate/ran/remediate-du-cpu-overload.md",
             "service_impact": "DL/UL throughput degradation", "probable_cause": "CPU contention"},
            {"name": "du_timing_failure", "layer": 3, "source": "ran", "field": "cells_0_cell_metrics_error_indication_count",
             "condition": "> 500", "severity": "critical", "depends_on": ["amf_gnb_disconnect", "ptp_drift"], "nf_scope": "per-node",
             "sop": "day2-remediate/ran/remediate-du-timing-failure.md",
             "service_impact": "Cell outage", "probable_cause": "PTP drift"},
            {"name": "du_throughput_drop", "layer": 3, "source": "ran", "field": "cells_0_ue_list_0_dl_brate",
             "condition": "< 500000", "severity": "warning", "depends_on": ["du_timing_failure", "amf_gnb_disconnect"], "nf_scope": "per-node"},
            {"name": "amf_gnb_disconnect", "layer": 2, "source": "core", "field": "amf_gnb",
             "condition": "< 1", "severity": "critical", "depends_on": ["nf_crashloop", "network_partition"], "nf_scope": "per-instance",
             "sop": "day2-remediate/core/remediate-amf-gnb-disconnect.md"},
            {"name": "nf_crashloop", "layer": 2, "source": "core", "field": "core_nf_health_pct",
             "condition": "< 95", "severity": "critical", "depends_on": ["network_partition"], "nf_scope": "per-instance",
             "sop": "day2-remediate/core/remediate-nf-crashloop.md"},
            {"name": "amf_registration_failure", "layer": 2, "source": "core", "field": "amf_fivegs_amffunction_rm_reginitfail",
             "condition": "> 0", "severity": "critical", "depends_on": ["nf_crashloop"], "nf_scope": "per-instance"},
            {"name": "amf_auth_rejection", "layer": 2, "source": "core", "field": "amf_fivegs_amffunction_amf_authreject",
             "condition": "> 0", "severity": "critical", "depends_on": ["nf_crashloop"], "nf_scope": "per-instance"},
            {"name": "smf_pfcp_failure", "layer": 2, "source": "core", "field": "smf_fivegs_smffunction_sm_n4sessionestabfail",
             "condition": "> 0", "severity": "critical", "depends_on": ["network_partition"], "nf_scope": "per-instance"},
            {"name": "upf_no_traffic", "layer": 2, "source": "core", "field": "upf_fivegs_ep_n3_gtp_indatapktn3upf",
             "condition": "== 0", "severity": "warning", "depends_on": ["amf_gnb_disconnect"], "nf_scope": "per-instance"},
            {"name": "sbi_mesh_failure", "layer": 2, "source": "core", "field": "alarm_scp_timeout",
             "condition": "> 0", "severity": "critical", "depends_on": ["nf_crashloop"], "nf_scope": "site-wide"},
            {"name": "network_partition", "layer": 1, "source": "core", "field": "node_not_ready",
             "condition": "> 0", "severity": "critical", "depends_on": [], "nf_scope": "site-wide",
             "sop": "day2-remediate/infra/remediate-network-partition.md"},
            {"name": "ptp_drift", "layer": 1, "source": "ran", "field": "ptp_offset_ns",
             "condition": "> 1500", "severity": "critical", "depends_on": [], "nf_scope": "per-node"},
        ],
        "guardrails": {
            "protected_namespaces": ["srsran", "open5gs", "anra", "kube-system"],
            "blocked_commands": ["scale.*--replicas.*0", "delete deployment", "delete statefulset", "delete namespace"],
            "approval_mode": "auto",
        },
        "anomaly_detection": {"enabled": True, "testmode": True, "max_sops_per_hour": 3, "sigma_threshold": 3},
        "topology": {"provider": "yaml"},
        "approval": {"mode": "auto"},
    }
    cfg_file = tmp_path / "anra-config.yaml"
    import yaml
    cfg_file.write_text(yaml.dump(config))
    os.environ["ANRA_CONFIG"] = str(cfg_file)
    yield
    os.environ.pop("ANRA_CONFIG", None)
