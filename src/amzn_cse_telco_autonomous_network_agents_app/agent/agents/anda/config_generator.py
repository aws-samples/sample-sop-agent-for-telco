# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ANDA config generation — ISV-agnostic primitives for the reasoning agent.

Design principle: tools provide RAW data and primitives only. The Strands agent
does all semantic reasoning (what the chart needs, what the site has, how to merge,
what gaps exist). No hardcoded field-name parsing — works for any NF/vendor.
"""

import logging
import os
import tempfile
from pathlib import Path

from strands import tool

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

log = logging.getLogger(__name__)


@tool
def read_helm_values(chart_path: str) -> str:
    """Read a Helm chart's values.yaml (raw content) for the agent to analyze.

    The agent reads this to understand what the NF requires — hardware, infra,
    capabilities. No parsing here; the agent reasons about the content.

    Args:
        chart_path: Path to the Helm chart directory.
    """
    values_path = Path(chart_path) / "values.yaml"
    if not values_path.exists():
        return f"Error: values.yaml not found at {values_path}"
    return values_path.read_text()


@tool
def describe_node(node_name: str = "") -> str:
    """Return raw node JSON (capacity, allocatable, labels) for the agent to analyze.

    The agent inspects this to understand what hardware/resources the site actually
    has. No parsing — the agent reasons about CPU, memory, hugepages, SR-IOV, labels.

    Args:
        node_name: Node to describe. Empty = first node in the cluster.
    """
    if not node_name:
        r = run_cmd("kubectl get nodes --no-headers -o custom-columns=NAME:.metadata.name", timeout=10)
        if not r.success or not r.stdout.strip():
            return f"Error: no nodes found: {r.output}"
        node_name = r.stdout.strip().split("\n")[0]
    result = run_cmd(f"kubectl get node {node_name} -o json", timeout=15)
    return result.stdout if result.success else f"Error: {result.output}"


@tool
def kubectl_query(args: str) -> str:
    """Run a read-only kubectl query for the agent to inspect cluster state.

    Use to check prerequisites: existing secrets, namespaces, NetworkAttachmentDefinitions,
    deployed images, etc. Read-only operations only (get/describe).

    Args:
        args: kubectl arguments (e.g., 'get net-attach-def -A -o json').
    """
    # Safety: only allow read verbs
    first = args.strip().split()[0] if args.strip() else ""
    if first not in ("get", "describe", "api-resources", "explain", "top", "version"):
        return f"Error: only read-only kubectl verbs allowed, got '{first}'"
    result = run_cmd(f"kubectl {args}", timeout=20)
    return result.output


@tool
def helm_dry_run(chart_path: str, values_yaml: str) -> str:
    """Validate generated values by rendering the chart with helm template --dry-run.

    Args:
        chart_path: Path to the Helm chart.
        values_yaml: The agent-generated values.yaml content to validate.
    """
    if not Path(chart_path).exists():
        return f"Error: chart not found at {chart_path}"
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    tmp.write(values_yaml)
    tmp.close()
    try:
        result = run_cmd(f"helm template validate {chart_path} -f {tmp.name} --dry-run 2>&1", timeout=30)
        if result.success:
            return f"PASS: rendered {result.stdout.count('kind:')} resources"
        return f"FAIL: {result.output[:600]}"
    finally:
        try:
            Path(tmp.name).unlink()
        except OSError:
            pass


@tool
def save_generated_values(values_yaml: str, output_name: str) -> str:
    """Save the agent-generated values.yaml to disk for review/commit.

    Args:
        values_yaml: The complete generated values.yaml content.
        output_name: Filename (e.g., 'nec-upf-newsite-values.yaml').
    """
    output_dir = Path(os.getenv("GENERATED_CONFIG_DIR", "/tmp/generated-configs"))  # nosec B108
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / output_name
    path.write_text(values_yaml)
    log.info("Saved generated values to %s", path)
    return f"Saved to {path}"


# System prompt for the config generation agent — reasoning happens here, not in code
SYSTEM_PROMPT_CONFIG_GEN = """You are ANDA's config generation agent. You produce a deployable Helm
values.yaml for a network function on a specific site, and verify the site can host it.

## Your Process

1. **Read the NF requirements**: Call `read_helm_values(chart_path)` to see the NF's base values.yaml.
   Reason about what hardware and infrastructure it needs — CPU, memory, hugepages, SR-IOV VFs,
   node labels, network attachments, privileged access, host mounts, secrets.

2. **Discover the site**: Call `describe_node()` to see what the target node actually has.
   Use `kubectl_query` to check for existing secrets, namespaces, NetworkAttachmentDefinitions,
   and image registries. Reason about whether the site meets the NF's requirements.

3. **Identify gaps**: Compare what the NF needs vs what the site has. For each gap, determine
   if it's auto-fixable (missing label, missing namespace, secret to copy) or requires manual
   intervention (insufficient hugepages needing node reconfiguration).

4. **Take operator network params**: The operator provides network parameters (VLANs, IP subnets,
   BGP peers, AS numbers, UE pool, APN) — these CANNOT be discovered from Kubernetes.

5. **Generate values.yaml**: Produce a complete values.yaml by taking the base template and
   substituting site-specific values you discovered (registry, image pull secret, node affinity
   label, SR-IOV device resource names) plus the operator's network params. Preserve all static
   NF configuration (ports, volumes, security contexts, DPDK tuning) from the template.

6. **Validate**: Call `helm_dry_run(chart_path, generated_values)` to confirm it renders.
   If it fails, fix and retry.

7. **Save**: Call `save_generated_values` with the validated config.

## Rules
- Never invent values. Discovered values come from the cluster; network params come from the operator.
- Report any gaps you find with a specific remediation command (kubectl) the operator/executor can run.
- The NF vendor is irrelevant — reason from the chart and cluster state, not vendor-specific knowledge.
"""


# RAN-specific system prompt addendum — teaches the agent how to generate gnb-config.yml
SYSTEM_PROMPT_RAN_ADDENDUM = """## RAN Configuration Generation (gNB / DU / CU)

For RAN NFs (gnb, du, cu-cp, cu-up), you generate TWO artifacts:
1. A Helm `values.yaml` (image, resources, node affinity, SR-IOV)
2. A `gnb-config.yml` (radio configuration wrapped in a ConfigMap)

### RAN-Specific Discovery

Before generating, query the cluster for ANPA-provisioned platform state:

1. **Node hardware readiness**:
   - `kubectl get nodes -o json` → check for `role=edge` label, `hugepages-1Gi` allocatable,
     SR-IOV resources (e.g., `intel.com/pci_sriov_net_fronthaul`)
   - Verify RT kernel: node annotation or `kubectl get node <name> -o jsonpath='{.status.nodeInfo.kernelVersion}'` (look for `-rt` suffix)

2. **ANPA provisioning status**:
   - `kubectl get provisioningrequests -A -o json` → check node role is `ran`, tuning applied
   - `kubectl get hardwareinventories -A -o json` → verify CPU topology matches site descriptor

3. **Network readiness**:
   - `kubectl get net-attach-def -A -o json` → verify fronthaul/midhaul NADs exist
   - SR-IOV VFs allocated: `kubectl get node <name> -o json` → `.status.allocatable["intel.com/pci_sriov_net_fronthaul"]`

4. **Timing**:
   - If `timing.ptp_enabled: true` in site descriptor, verify PTP daemon is running:
     `kubectl get pods -A -l app=linuxptp-daemon` or check node annotations

### gnb-config.yml Generation

The radio config MUST be generated from the site descriptor `ran:` section. Structure:

```yaml
cu_cp:
  amf:
    addr: {ran.amf_addr}
    port: {ran.amf_port}
    bind_addr: {ran.gnb_bind_addr}
    supported_tracking_areas:
      - tac: {ran.tac}
        plmn_list:
          - plmn: "{ran.plmn}"
            tai_slice_support_list:
              - sst: 1
cells:
  - dl_arfcn: {cell.dl_arfcn}
    band: {cell.band}
    channel_bandwidth_MHz: {cell.channel_bandwidth_mhz}
    common_scs: {cell.scs_khz}
    plmn: "{ran.plmn}"
    tac: {ran.tac}
    pci: {cell.pci}
    nof_antennas_dl: {cell.nof_antennas_dl}
    nof_antennas_ul: {cell.nof_antennas_ul}
    prach:
      prach_config_index: {cell.prach.config_index}
      prach_root_sequence_index: {cell.prach.root_sequence_index}
      zero_correlation_zone: {cell.prach.zero_correlation_zone}
      prach_frequency_start: {cell.prach.frequency_start}
    tdd_ul_dl_cfg:
      dl_ul_tx_period: {cell.tdd_ul_dl_cfg.dl_ul_tx_period}
      nof_dl_slots: {cell.tdd_ul_dl_cfg.nof_dl_slots}
      nof_dl_symbols: {cell.tdd_ul_dl_cfg.nof_dl_symbols}
      nof_ul_slots: {cell.tdd_ul_dl_cfg.nof_ul_slots}
      nof_ul_symbols: {cell.tdd_ul_dl_cfg.nof_ul_symbols}
```

If `test_mode.enabled: true`, add:
```yaml
test_mode:
  test_ue:
    rnti: {ran.test_mode.rnti}
    nof_ues: {ran.test_mode.nof_ues}
    pusch_active: true
    pdsch_active: true
```

Always add:
```yaml
log:
  filename: stdout
  all_level: warning
metrics:
  autostart_stdout_metrics: true
  enable_json: true
```

### Pre-Deployment Gaps (RAN-specific)

Report these as gaps if NOT met:
- ❌ No node with `role=edge` label → FIX: `kubectl label node <name> role=edge`
- ❌ hugepages-1Gi = 0 → FIX: requires node reconfig (kernel cmdline)
- ❌ SR-IOV VF count = 0 → FIX: ANPA must provision SriovNetworkNodePolicy
- ❌ No RT kernel → FIX: ANPA must reprovision with `ran-worker` OS profile
- ❌ PTP not running/locked → FIX: deploy linuxptp-daemon DaemonSet
- ❌ No fronthaul NAD → FIX: create NetworkAttachmentDefinition

### Save Artifacts

1. `save_generated_values(values_yaml, "{nf_name}-values.yaml")` — Helm values
2. `save_generated_values(gnb_config_yml, "{nf_name}-gnb-config.yml")` — radio config

The deployment agent will:
- Create a ConfigMap from the gnb-config.yml
- Deploy via Helm with values.yaml referencing that ConfigMap
"""


CONFIG_GEN_TOOLS = [
    read_helm_values,
    describe_node,
    kubectl_query,
    helm_dry_run,
    save_generated_values,
]


# ── Phase 0 Entry Point ──

GENERATED_CONFIG_DIR = os.getenv("GENERATED_CONFIG_DIR", "/tmp/generated-configs")  # nosec B108 — container tmpfs
SITE_DESCRIPTOR_PATHS = [
    os.getenv("SITE_DESCRIPTOR_PATH", ""),
    "/app/config/site-descriptor.yaml",
    "/etc/anda/site-descriptor.yaml",
    # Baked-in descriptors (from Dockerfile COPY configs/site-descriptors/)
    "/app/configs/site-descriptors/docomo-site-002.yaml",
]


def load_site_descriptor(cluster: str = "") -> dict | None:
    """Load site descriptor from well-known paths. Returns dict or None."""
    import yaml

    for path in SITE_DESCRIPTOR_PATHS:
        if path and os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    desc = yaml.safe_load(f) or {}
                # If a cluster filter was provided, verify it matches
                if cluster and desc.get("site", {}).get("cluster") != cluster:
                    log.debug("Skipping %s — cluster mismatch", path)
                    continue
                log.info("Loaded site descriptor from %s", path)
                return desc
            except Exception as e:
                log.warning("Failed to load site descriptor from %s: %s", path, e)
    return None


def run_config_generation(
    nf_name: str,
    vendor: str,
    namespace: str,
    site_descriptor: dict,
    plan_name: str = "",
) -> str | None:
    """Run AI config generation agent. Returns path to generated values or None.

    The agent uses cluster discovery + site descriptor to produce a complete
    Helm values.yaml for the given NF. Output is saved to GENERATED_CONFIG_DIR.
    """
    import json
    import time

    from amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver import (
        ModelTier,
        build_model,
    )

    # Determine if this is a RAN NF and whether it uses srsRAN config format
    ran_nf_names = ("gnb", "du", "cu-cp", "cu-up", "srsran", "ran")
    is_ran = nf_name.lower() in ran_nf_names or vendor.lower() in ("srsran", "phluido", "ericsson")
    # Only apply srsRAN-specific gnb-config.yml template for srsRAN vendor;
    # other vendors (ericsson, phluido) have different config schemas driven by their chart
    is_srsran = vendor.lower() == "srsran"
    # Single flag for all gnb-config.yml gating (prompt, addendum, skip, success)
    expects_gnb_config = is_srsran and bool(site_descriptor.get("ran"))

    output_path = str(Path(GENERATED_CONFIG_DIR) / f"{nf_name}-values.yaml")
    gnb_config_path = str(Path(GENERATED_CONFIG_DIR) / f"{nf_name}-gnb-config.yml")

    # Skip if already generated (for srsRAN with ran config, both artifacts must exist)
    if os.path.isfile(output_path):
        if not expects_gnb_config or os.path.isfile(gnb_config_path):
            log.info("Config already exists at %s — skipping generation", output_path)
            return output_path
        log.info("values.yaml exists but gnb-config.yml missing — re-running generation")

    # Ensure output directory exists
    Path(GENERATED_CONFIG_DIR).mkdir(parents=True, exist_ok=True)

    # Build the operator context from site descriptor
    network = site_descriptor.get("network", {})
    hardware = site_descriptor.get("hardware", {})
    nf_stack = site_descriptor.get("nf_stack", {})
    site_info = site_descriptor.get("site", {})
    images = site_descriptor.get("images", {})
    ran_config = site_descriptor.get("ran", {})

    prompt = f"""Generate Helm values.yaml for NF: {nf_name}
Vendor: {vendor}
Namespace: {namespace}
Site: {site_info.get('name', 'unknown')}
Cluster: {site_info.get('cluster', 'unknown')}

Operator Network Parameters (from site descriptor — use these, do NOT discover):
{json.dumps(network, indent=2)[:2000]}

Hardware ({len(hardware.get('nodes', []))} nodes):
{json.dumps(hardware, indent=2)[:1500]}

Images:
  Registry: {images.get('registry', 'N/A')}
  Tag: {images.get('tag', 'latest')}

NF Stack: {json.dumps(nf_stack, indent=2)[:500]}

Chart path for read_helm_values: /app/helm-charts/{vendor}/charts/{nf_name}/
  (if not found, try: /app/helm-charts/{vendor}/)
"""

    # Add srsRAN-specific gnb-config.yml generation instructions
    if expects_gnb_config:
        prompt += f"""
## RAN Radio Parameters (from site descriptor — use these for gnb-config.yml):
{json.dumps(ran_config, indent=2)[:3000]}

Generate BOTH:
1. values.yaml — save as "{nf_name}-values.yaml"
2. gnb-config.yml — save as "{nf_name}-gnb-config.yml"
"""
    elif is_ran and ran_config:
        # Non-srsRAN RAN vendors: provide radio params as context but let the agent
        # derive config format from the vendor's chart (read_helm_values)
        prompt += f"""
## RAN Radio Parameters (context only — derive config format from the vendor chart):
{json.dumps(ran_config, indent=2)[:3000]}

Generate the values.yaml now. Save with output_name="{nf_name}-values.yaml".
"""
    else:
        prompt += f"\nGenerate the values.yaml now. Save with output_name=\"{nf_name}-values.yaml\"."

    # Select system prompt — add srsRAN-specific addendum only when expecting gnb-config
    system_prompt = SYSTEM_PROMPT_CONFIG_GEN
    if expects_gnb_config:
        system_prompt += "\n" + SYSTEM_PROMPT_RAN_ADDENDUM

    log.info("Starting config generation for %s (vendor=%s, site=%s)",
             nf_name, vendor, site_info.get("name", "?"))
    start = time.time()

    try:
        from strands import Agent

        model = build_model(ModelTier.FAST)
        agent = Agent(
            model=model,
            tools=CONFIG_GEN_TOOLS,
            system_prompt=system_prompt,
        )
        agent(prompt)

        duration = round(time.time() - start, 1)

        if os.path.isfile(output_path) and (not expects_gnb_config or os.path.isfile(gnb_config_path)):
            log.info("Config generated for %s in %ss: %s", nf_name, duration, output_path)
            # Emit activity event
            try:
                from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_activity
                push_activity("execute", f"Config generated for {nf_name} ({duration}s)", status="success")
            except Exception:
                pass
            # Patch CR status if plan_name provided
            if plan_name:
                _patch_config_gen_status(plan_name, nf_name, output_path, duration)
            return output_path

        if expects_gnb_config and os.path.isfile(output_path) and not os.path.isfile(gnb_config_path):
            log.warning("Config gen produced values.yaml but gnb-config.yml missing at %s", gnb_config_path)
        else:
            log.warning("Config gen agent ran but output not found at %s", output_path)
        return None

    except Exception as e:
        duration = round(time.time() - start, 1)
        log.error("Config generation failed for %s after %ss: %s", nf_name, duration, e)
        return None


def _patch_config_gen_status(plan_name: str, nf_name: str, values_path: str, duration: float) -> None:
    """Patch DeploymentPlan CR status with config generation result."""
    import json

    namespace = os.getenv("ANDA_NAMESPACE", "anda-system")
    status_patch = json.dumps({
        "status": {
            "sopExecution": {
                nf_name: {
                    "configGenerated": True,
                    "valuesPath": values_path,
                    "configGenDuration": f"{duration}s",
                }
            }
        }
    })
    result = run_cmd(
        f"kubectl patch deploymentplan {plan_name} -n {namespace} "
        f"--type=merge --subresource=status -p '{status_patch}'",
        timeout=10,
    )
    if not result.success:
        log.warning("Failed to patch CR status for config gen: %s", result.stderr)

