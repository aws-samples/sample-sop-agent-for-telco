# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Phase 3.2 / 3.3 — server-group + tuning generator unit tests."""

from pathlib import Path

import pytest
import yaml

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.server_group_generator import (
    ProvisioningIntent,
    generate_group_document,
    generate_server_entry,
    generate_yaml,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tuning_generator import (
    TuningRequest,
    generate_tuning_profile,
    tuning_profile_name,
)

SAMPLE_HWI_30_10 = {
    "hostname": "mi-0c32a0cb4c4c06fdd",
    "bmcAddress": "192.168.30.10",
    "systemUUID": "4c4c4544-0057-5a10-8035-b7c04f364734",
    "serialNumber": "7WZ56G4",
    "interfaces": [
        {"name": "NIC.Integrated.1-1-1", "mac": "aa:bb:cc:dd:ee:01", "speed": "10000"},
        {"name": "NIC.Slot.1-1-1", "mac": "aa:bb:cc:dd:ee:02", "speed": "25000"},
    ],
    "cpu": {"cores": 64, "model": "Xeon"},
    "memory": {"totalGiB": 256},
}


CANONICAL_INTENT = ProvisioningIntent(
    cluster_name="site-002-workload",
    cluster_region="us-west-1",
    group_name="site-002-rack-1",
    machine_profile="poweredge-xr8000r-2disk",
    os_profile="ubuntu-noble",
    network_profile="site-002-baremetal-net",
    tuning_profile="upf-tuning",
    ip="192.168.31.151",
)


# ============================================================================
# Phase 3.2 — server-group entry generator
# ============================================================================


class TestServerEntry:
    def test_emits_required_eks_h_fields(self):
        entry = generate_server_entry(SAMPLE_HWI_30_10, CANONICAL_INTENT)
        # Schema fields per day0/server-groups/example.yaml
        assert entry["name"] == "mi-0c32a0cb4c4c06fdd"
        assert entry["bmcAddress"] == "192.168.30.10"
        assert entry["machineProfile"] == "poweredge-xr8000r-2disk"
        assert entry["osProfile"] == "ubuntu-noble"
        assert entry["networkProfile"] == "site-002-baremetal-net"
        assert entry["tuningProfile"] == "upf-tuning"
        assert entry["bmcUser"] == "root"
        assert entry["provision"] is False  # default — must be flipped via PR review
        assert entry["provisionHash"] == "v1"

    def test_picks_first_mac_from_interfaces(self):
        entry = generate_server_entry(SAMPLE_HWI_30_10, CANONICAL_INTENT)
        assert entry["mac"] == "aa:bb:cc:dd:ee:01"

    def test_bmc_pass_is_a_reference_not_a_value(self):
        """Never embed literal credentials in the generated entry."""
        entry = generate_server_entry(SAMPLE_HWI_30_10, CANONICAL_INTENT)
        assert entry["bmcPass"].startswith("$") or entry["bmcPass"].startswith("ref:")

    def test_missing_hostname_raises(self):
        with pytest.raises(ValueError):
            generate_server_entry({"bmcAddress": "x"}, CANONICAL_INTENT)

    def test_missing_bmc_raises(self):
        with pytest.raises(ValueError):
            generate_server_entry({"hostname": "x"}, CANONICAL_INTENT)

    def test_overrides_apply_last(self):
        intent = ProvisioningIntent(**{**CANONICAL_INTENT.__dict__, "overrides": {"customLabel": "demo"}})
        entry = generate_server_entry(SAMPLE_HWI_30_10, intent)
        assert entry["customLabel"] == "demo"


class TestGroupDocument:
    def test_round_trips_through_yaml(self):
        doc = generate_group_document([SAMPLE_HWI_30_10], CANONICAL_INTENT)
        rendered = generate_yaml([SAMPLE_HWI_30_10], CANONICAL_INTENT)
        parsed = yaml.safe_load(rendered)
        assert parsed["cluster"]["name"] == "site-002-workload"
        assert parsed["groupName"] == "site-002-rack-1"
        assert len(parsed["servers"]) == 1
        assert parsed["servers"][0]["name"] == "mi-0c32a0cb4c4c06fdd"

    def test_matches_eks_h_example_shape(self):
        """Compare top-level keys against day0/server-groups/example.yaml."""
        pytest.skip("day0/server-groups/example.yaml not available in App package")
        repo = Path(__file__).resolve().parent.parent.parent
        ref_path = repo / "day0" / "server-groups" / "example.yaml"
        ref = yaml.safe_load(ref_path.read_text())
        doc = generate_group_document([SAMPLE_HWI_30_10], CANONICAL_INTENT)
        assert set(ref.keys()) == set(doc.keys()), f"top-level keys diverge: ref={ref.keys()} vs gen={doc.keys()}"
        ref_server_keys = set(ref["servers"][0].keys())
        gen_server_keys = set(doc["servers"][0].keys())
        # Generator must produce at least every key the reference has.
        missing = ref_server_keys - gen_server_keys
        assert not missing, f"generator missing reference keys: {missing}"


# ============================================================================
# Phase 3.3 — hardware-aware tuning generator
# ============================================================================


class TestTuningGenerator:
    def test_two_socket_64_cores_isolates_correctly(self):
        topo = {"sockets": 2, "total_cores": 64, "total_threads": 128, "models": ["Xeon"]}
        out = generate_tuning_profile(topo, TuningRequest(nf="upf", hugepages_1gi=8))
        # 2 cores per socket reserved (0-1, 32-33), rest isolated
        assert "isolcpus=2-31,34-63" in out["kernelCmdline"]
        assert "nohz_full=2-31,34-63" in out["kernelCmdline"]
        assert "rcu_nocbs=2-31,34-63" in out["kernelCmdline"]
        assert "hugepages=8" in out["kernelCmdline"]
        assert "intel_iommu=on" in out["kernelCmdline"]
        assert out["sysctl"]["vm.nr_hugepages"] == "8"
        assert "irqbalance" in out["disabledServices"]

    def test_single_socket(self):
        topo = {"sockets": 1, "total_cores": 16, "total_threads": 32, "models": []}
        out = generate_tuning_profile(topo, TuningRequest(nf="gnb", hugepages_1gi=4))
        assert "isolcpus=2-15" in out["kernelCmdline"]
        assert "hugepages=4" in out["kernelCmdline"]

    def test_empty_topology_is_safe(self):
        out = generate_tuning_profile(
            {"sockets": 0, "total_cores": 0, "total_threads": 0, "models": []},
            TuningRequest(nf="upf"),
        )
        # No isolcpus when topology is unknown; basic IOMMU + hugepages still emit
        assert "isolcpus" not in out["kernelCmdline"]
        assert "intel_iommu=on" in out["kernelCmdline"]

    def test_sysctl_overrides_merge(self):
        topo = {"sockets": 1, "total_cores": 8, "total_threads": 16, "models": []}
        out = generate_tuning_profile(
            topo,
            TuningRequest(
                nf="upf",
                sysctl_overrides={"net.core.busy_poll": "100", "kernel.something": "1"},
            ),
        )
        assert out["sysctl"]["net.core.busy_poll"] == "100"
        assert out["sysctl"]["kernel.something"] == "1"

    def test_profile_name_is_deterministic_and_safe(self):
        n1 = tuning_profile_name("upf", "mi-0c32a0cb4c4c06fdd")
        n2 = tuning_profile_name("UPF", "MI-0C32A0CB4C4C06FDD")
        assert n1 == n2 == "upf-mi-0c32a0cb4c4c06fdd"
        assert "_" not in n1 and "." not in n1
