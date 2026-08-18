# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for ANPA tuning_generator — Phase 5.3.

Two function surfaces, two test groups:

  1. ``generate_tuning_profile`` (existing, P3.3) — returns dict shape
     compatible with the EKS-H ``tuningProfiles.<name>`` values catalog
     (operator-driven manual path).

  2. ``generate_tuning_fields`` (new, P5.3) — returns the three string
     fields the EKS-H ``BareMetalProvision`` CR carries
     (``tuningKernelCmdline``, ``tuningSysctl``, ``tuningDisabledServices``).
     Used by ANPA's autonomous reconciler when emitting the CR directly.

Key serialization invariants (must match EKS-H's
``day0/.../bare-metal-server.yaml`` rendering exactly, otherwise the
downstream Tinkerbell action consuming the strings will misparse):

  * ``tuningKernelCmdline`` — space-separated kernel args
  * ``tuningSysctl`` — semicolon-separated ``key=value`` pairs, sorted
  * ``tuningDisabledServices`` — comma-separated systemd unit names
"""
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tuning_generator import (
    TuningRequest,
    generate_tuning_fields,
    generate_tuning_profile,
    tuning_profile_name,
)

# ---- representative topologies -----------------------------------------------

ONE_SOCKET_32C = {"sockets": 1, "total_cores": 32}
TWO_SOCKET_64C = {"sockets": 2, "total_cores": 64}  # 32 cores per socket
EMPTY_TOPO = {}


# ---- generate_tuning_profile (existing) --------------------------------------

class TestGenerateTuningProfile:
    def test_two_socket_isolates_correct_range(self):
        result = generate_tuning_profile(TWO_SOCKET_64C, TuningRequest(nf="upf"))
        # House cores 0-1 + 32-33 reserved; isolate 2-31 + 34-63
        assert "isolcpus=2-31,34-63" in result["kernelCmdline"]
        assert "nohz_full=2-31,34-63" in result["kernelCmdline"]

    def test_one_socket_isolates_correct_range(self):
        result = generate_tuning_profile(ONE_SOCKET_32C, TuningRequest(nf="upf"))
        assert "isolcpus=2-31" in result["kernelCmdline"]
        # Single socket → no comma in the mask
        assert "isolcpus=2-31," not in result["kernelCmdline"]

    def test_iommu_and_hugepages_always_present(self):
        result = generate_tuning_profile(TWO_SOCKET_64C, TuningRequest(nf="upf", hugepages_1gi=16))
        assert "intel_iommu=on" in result["kernelCmdline"]
        assert "iommu=pt" in result["kernelCmdline"]
        assert "hugepagesz=1G" in result["kernelCmdline"]
        assert "hugepages=16" in result["kernelCmdline"]

    def test_empty_topology_skips_isolation(self):
        result = generate_tuning_profile(EMPTY_TOPO, TuningRequest(nf="upf"))
        assert "isolcpus" not in result["kernelCmdline"]
        # IOMMU / hugepages still applied
        assert "intel_iommu=on" in result["kernelCmdline"]

    def test_default_disabled_services_includes_irqbalance(self):
        result = generate_tuning_profile(TWO_SOCKET_64C, TuningRequest(nf="upf"))
        assert "irqbalance" in result["disabledServices"]

    def test_sysctl_overrides_merge(self):
        req = TuningRequest(nf="upf", sysctl_overrides={"net.ipv4.tcp_mem": "1 2 3"})
        result = generate_tuning_profile(TWO_SOCKET_64C, req)
        assert result["sysctl"]["net.ipv4.tcp_mem"] == "1 2 3"
        # Defaults still present
        assert "vm.nr_hugepages" in result["sysctl"]


# ---- generate_tuning_fields (new, RGD-direct) --------------------------------

class TestGenerateTuningFields:
    def test_returns_only_the_three_eks_h_keys(self):
        result = generate_tuning_fields(TWO_SOCKET_64C, TuningRequest(nf="upf"))
        assert set(result.keys()) == {
            "tuningKernelCmdline",
            "tuningSysctl",
            "tuningDisabledServices",
        }
        # All three are strings (not dicts/lists) — that's the RGD's contract
        assert all(isinstance(v, str) for v in result.values())

    def test_kernel_cmdline_is_space_separated(self):
        result = generate_tuning_fields(TWO_SOCKET_64C, TuningRequest(nf="upf"))
        cmdline = result["tuningKernelCmdline"]
        assert "isolcpus=2-31,34-63" in cmdline
        assert "intel_iommu=on" in cmdline
        # Space-separated, not comma- or semicolon-separated
        assert ";" not in cmdline
        assert "  " not in cmdline  # no double spaces

    def test_sysctl_is_semicolon_separated_kv_pairs_alphabetical(self):
        """Per day0/.../bare-metal-server.yaml line 67, EKS-H renders sysctl
        as semicolon-delimited key=value pairs sorted alphabetically. The
        downstream Tinkerbell template (template.yaml) does ``tr ';' '\\n'``
        on this string. Must match exactly or the action misparses."""
        result = generate_tuning_fields(TWO_SOCKET_64C, TuningRequest(nf="upf"))
        sysctl = result["tuningSysctl"]
        # Splittable by ; into key=value pairs
        pairs = sysctl.split(";")
        assert len(pairs) > 0
        for pair in pairs:
            assert "=" in pair, f"malformed sysctl pair: {pair!r}"
            key, _, _ = pair.partition("=")
            assert key, f"empty key in sysctl pair: {pair!r}"
        # Alphabetically sorted (matches Helm's sortAlpha)
        keys = [p.split("=", 1)[0] for p in pairs]
        assert keys == sorted(keys), "sysctl keys must be alphabetically sorted"

    def test_disabled_services_is_comma_separated(self):
        """Per day0/.../bare-metal-server.yaml line 68, EKS-H renders
        disabledServices as comma-joined."""
        req = TuningRequest(nf="upf", disabled_services=["irqbalance", "tuned"])
        result = generate_tuning_fields(TWO_SOCKET_64C, req)
        assert result["tuningDisabledServices"] == "irqbalance,tuned"

    def test_disabled_services_default(self):
        result = generate_tuning_fields(TWO_SOCKET_64C, TuningRequest(nf="upf"))
        assert result["tuningDisabledServices"] == "irqbalance"

    def test_one_socket_box(self):
        result = generate_tuning_fields(ONE_SOCKET_32C, TuningRequest(nf="upf"))
        assert "isolcpus=2-31" in result["tuningKernelCmdline"]

    def test_empty_topology_yields_no_isolcpus(self):
        result = generate_tuning_fields(EMPTY_TOPO, TuningRequest(nf="upf"))
        assert "isolcpus" not in result["tuningKernelCmdline"]
        # IOMMU and hugepages are topology-independent — still present
        assert "intel_iommu=on" in result["tuningKernelCmdline"]

    def test_hugepages_override_propagates(self):
        result = generate_tuning_fields(TWO_SOCKET_64C, TuningRequest(nf="upf", hugepages_1gi=32))
        assert "hugepages=32" in result["tuningKernelCmdline"]
        # vm.nr_hugepages in sysctl reflects same value
        assert "vm.nr_hugepages=32" in result["tuningSysctl"]


# ---- tuning_profile_name (helper, unchanged) ---------------------------------

class TestTuningProfileName:
    def test_basic_naming(self):
        assert tuning_profile_name("upf", "Dell-R760-001") == "upf-dell-r760-001"

    def test_replaces_dots_and_underscores(self):
        assert tuning_profile_name("UPF", "host_01.lab") == "upf-host-01-lab"
