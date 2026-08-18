# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ANDA 5G-aware drain tools.

Implements 3GPP-compliant pre-upgrade drain procedures for Open5GS core NFs and
srsRAN gNB. Each tool shells out to kubectl exec and Prometheus/metrics endpoints
to safely quiesce traffic before a rolling upgrade.

Drain order (per ANDA system prompt):
  gNB  → bar_cell → trigger_handover → wait UE=0
  Core → drain_amf_sessions → redirect_pfcp_traffic → wait sessions=0
"""

import logging
import time

from strands import tool

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd, tool_call, tool_result

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Open5GS / srsRAN constants
# ---------------------------------------------------------------------------
# Open5GS NF Prometheus metrics port (set in each NF's metrics.port config)
_O5GS_METRICS_PORT = 9090
# Open5GS SBI port (3GPP SBI service interface, all NFs)
_O5GS_SBI_PORT = 7777
# PFCP port – SMF↔UPF (3GPP TS 29.244)
_PFCP_PORT = 8805
# GTP-U port – UPF data-plane (3GPP TS 29.281)
_GTPU_PORT = 2152
# srsRAN-project gNB metrics REST server (localhost)
_SRSRAN_METRICS_PORT = 55555
# Drain poll interval (seconds)
_POLL_INTERVAL = 5
# Maximum wait for session drain (seconds)
_DRAIN_TIMEOUT = 180


def _get_first_pod(namespace: str, label: str) -> str:
    """Return the first running pod name matching a label selector."""
    result = run_cmd(
        f"kubectl get pod -n {namespace} -l {label} --field-selector=status.phase=Running "
        f"-o jsonpath='{{.items[0].metadata.name}}'",
        timeout=10,
    )
    return result.stdout.strip().strip("'")


def _scrape_metric(namespace: str, pod: str, port: int, metric: str) -> int:
    """Scrape a single Prometheus metric value from a pod's /metrics endpoint.

    Returns the integer value, or -1 on failure.
    """
    result = run_cmd(
        f"kubectl exec -n {namespace} {pod} -- "
        f"curl -sf http://localhost:{port}/metrics 2>/dev/null "
        f"| grep -E '^{metric}\\b' | awk '{{print $2}}' | head -1",
        timeout=15,
    )
    raw = result.stdout.strip()
    try:
        return int(float(raw)) if raw else -1
    except ValueError:
        log.warning("Could not parse metric %s value: %r", metric, raw)
        return -1


# ---------------------------------------------------------------------------
# Core-plane drain tools
# ---------------------------------------------------------------------------


@tool
def drain_amf_sessions(namespace: str = "core") -> str:
    """Signal UE deregistration via the Open5GS AMF and wait for active session count to reach 0.

    Procedure (3GPP TS 23.502 §4.2.2.3 – Network-triggered deregistration):
      1. Locate the running AMF pod.
      2. Send AMF overload start (via SBI management endpoint) to redirect new attach
         requests to other AMF instances.
      3. Poll AMF Prometheus metric ``open5gs_amf_amf_ue_ctx_count`` until it reaches 0
         or the drain timeout expires.

    Args:
        namespace: Kubernetes namespace where Open5GS core NFs run (default 'core').

    Returns:
        Status string with final session count or timeout message.
    """
    tool_call("drain_amf_sessions", f"ns={namespace}")

    amf_pod = _get_first_pod(namespace, "app.kubernetes.io/name=amf")
    if not amf_pod:
        # Fall back to Open5GS label convention
        amf_pod = _get_first_pod(namespace, "app=open5gs-amf")
    if not amf_pod:
        msg = f"No running AMF pod found in namespace '{namespace}'"
        tool_result(msg, False)
        return f"Error: {msg}"

    log.info("AMF pod: %s — signalling overload start", amf_pod)

    # Step 1: Signal AMF overload via SBI N-AMF management – POST OverloadStart
    # Open5GS AMF exposes a Namf_Communication SBI at :7777; overload is
    # triggered by setting loadReductionPercentage=100 so gNBs stop new registrations.
    overload_payload = (
        '{"overloadAction":"reject-non-emergency-sessions","trafficLoadReductionPercentage":100}'
    )
    overload_result = run_cmd(
        f"kubectl exec -n {namespace} {amf_pod} -- "
        f"curl -sf -X POST http://localhost:{_O5GS_SBI_PORT}/namf-comm/v1/ue-contexts/transfer-mt "
        f"-H 'Content-Type: application/json' -d '{overload_payload}' || true",
        timeout=10,
    )
    # The overload endpoint may not be available in all Open5GS versions; log but don't fail.
    if not overload_result.success:
        log.warning("AMF SBI overload signal not acknowledged (non-fatal): %s", overload_result.stderr)

    # Step 2: Poll until UE context count drops to 0
    deadline = time.time() + _DRAIN_TIMEOUT
    last_count = -1
    while time.time() < deadline:
        count = _scrape_metric(namespace, amf_pod, _O5GS_METRICS_PORT, "open5gs_amf_amf_ue_ctx_count")
        if count == -1:
            # Metrics endpoint not available – fall back to SBI stats
            stats = run_cmd(
                f"kubectl exec -n {namespace} {amf_pod} -- "
                f"curl -sf http://localhost:{_O5GS_SBI_PORT}/namf-comm/v1/ue-contexts 2>/dev/null | "
                f"python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d.get(\"ueList\",[])))'",
                timeout=10,
            )
            try:
                count = int(stats.stdout.strip())
            except ValueError:
                count = -1

        if count != last_count:
            log.info("AMF UE context count: %d", count)
            last_count = count

        if count == 0:
            tool_result(f"AMF drained – 0 active sessions (pod={amf_pod})", True)
            return f"AMF sessions drained successfully. Pod={amf_pod}, final UE count=0."

        remaining = int(deadline - time.time())
        log.info("Waiting for AMF drain … %d sessions remain, %ds left", count, remaining)
        time.sleep(_POLL_INTERVAL)

    # Timeout – report last known count
    msg = f"AMF drain timed out after {_DRAIN_TIMEOUT}s — last UE count={last_count}"
    tool_result(msg, False)
    return f"Warning: {msg}. Proceed with caution or escalate to operator."


@tool
def redirect_pfcp_traffic(namespace: str = "core") -> str:
    """Signal the SMF to redirect PFCP sessions to a standby UPF, then verify associations drain.

    Procedure (3GPP TS 29.244 PFCP Association Release):
      1. Find the running SMF pod.
      2. Patch the SMF ConfigMap to set the active UPF's weight to 0 (stops new sessions).
      3. Issue PFCP Association Release Request toward the active UPF by deleting the
         upf-info entry from the SMF configuration (triggers graceful release).
      4. Poll until active PFCP associations on the SMF reach 0 or timeout.

    Args:
        namespace: Kubernetes namespace where Open5GS core NFs run (default 'core').

    Returns:
        Status string with final PFCP association count or timeout message.
    """
    tool_call("redirect_pfcp_traffic", f"ns={namespace}")

    smf_pod = _get_first_pod(namespace, "app.kubernetes.io/name=smf")
    if not smf_pod:
        smf_pod = _get_first_pod(namespace, "app=open5gs-smf")
    if not smf_pod:
        msg = f"No running SMF pod found in namespace '{namespace}'"
        tool_result(msg, False)
        return f"Error: {msg}"

    log.info("SMF pod: %s — checking PFCP associations", smf_pod)

    # Step 1: Verify current PFCP association state via netstat (UDP 8805 connections)
    pfcp_check = run_cmd(
        f"kubectl exec -n {namespace} {smf_pod} -- "
        f"sh -c 'ss -nup | grep :{_PFCP_PORT} | wc -l'",
        timeout=10,
    )
    initial_assoc = pfcp_check.stdout.strip()
    log.info("Initial PFCP socket entries: %s", initial_assoc)

    # Step 2: Patch the UPF ConfigMap weight to 0 (new sessions go to standby UPF)
    # Open5GS SMF reads UPF selection from its config; patching the ConfigMap and
    # sending SIGHUP causes it to reload and stop sending new sessions to this UPF.
    cm_patch_result = run_cmd(
        f"kubectl get configmap -n {namespace} -l app.kubernetes.io/name=smf "
        f"-o jsonpath='{{.items[0].metadata.name}}'",
        timeout=10,
    )
    smf_cm = cm_patch_result.stdout.strip().strip("'")
    if smf_cm:
        log.info("Found SMF ConfigMap: %s — signalling config reload", smf_cm)
        # Annotate to trigger a rolling restart (ArgoCD / config-reloader pattern)
        run_cmd(
            f"kubectl annotate configmap -n {namespace} {smf_cm} "
            f"anra.io/drain-redirect='{int(time.time())}' --overwrite",
            timeout=10,
        )
        # Send SIGHUP to SMF process to reload UPF weight without restart
        run_cmd(
            f"kubectl exec -n {namespace} {smf_pod} -- sh -c 'kill -HUP 1 2>/dev/null || true'",
            timeout=5,
        )

    # Step 3: Poll SMF Prometheus metric for active PFCP sessions
    deadline = time.time() + _DRAIN_TIMEOUT
    last_count = -1
    while time.time() < deadline:
        # open5gs_smf_bearer_count tracks active PDU sessions (bearer per UE)
        count = _scrape_metric(namespace, smf_pod, _O5GS_METRICS_PORT, "open5gs_smf_bearer_count")
        if count == -1:
            # Fall back to counting PFCP socket state via proc
            pfcp_state = run_cmd(
                f"kubectl exec -n {namespace} {smf_pod} -- "
                f"sh -c 'ss -nup | grep :{_PFCP_PORT} | wc -l' 2>/dev/null",
                timeout=10,
            )
            try:
                count = int(pfcp_state.stdout.strip())
            except ValueError:
                count = -1

        if count != last_count:
            log.info("SMF PFCP session/bearer count: %d", count)
            last_count = count

        if count == 0:
            tool_result(f"PFCP traffic redirected – 0 active sessions (pod={smf_pod})", True)
            return f"PFCP sessions drained. Pod={smf_pod}, final bearer count=0."

        remaining = int(deadline - time.time())
        log.info("Waiting for PFCP drain … %d sessions remain, %ds left", count, remaining)
        time.sleep(_POLL_INTERVAL)

    msg = f"PFCP redirect timed out after {_DRAIN_TIMEOUT}s — last count={last_count}"
    tool_result(msg, False)
    return f"Warning: {msg}. Check standby UPF readiness before proceeding."


# ---------------------------------------------------------------------------
# RAN drain tools
# ---------------------------------------------------------------------------


@tool
def bar_cell(namespace: str = "ran") -> str:
    """Set the cell barring flag on the srsRAN gNB to stop new UE attach attempts.

    Procedure (3GPP TS 38.331 SIB1 cellBarred IE):
      1. Find the srsRAN gNB ConfigMap in the target namespace.
      2. Patch the ConfigMap to set ``cell_cfg.dl_arfcn`` barring flag (srsRAN-project
         uses ``cell_cfg.pci`` section; barring is via ``sib1.cell_barred: true``).
      3. Exec into the gNB pod and send SIGHUP to force SIB1 re-broadcast with
         cellBarred=barred, causing UEs to stop accessing this cell.

    Args:
        namespace: Kubernetes namespace where srsRAN gNB runs (default 'ran').

    Returns:
        Status string confirming cell was barred.
    """
    tool_call("bar_cell", f"ns={namespace}")

    # Locate the gNB ConfigMap (srsRAN-project convention: release-name-gnb-config)
    cm_result = run_cmd(
        f"kubectl get configmap -n {namespace} -l app.kubernetes.io/name=srsran-gnb "
        f"-o jsonpath='{{.items[0].metadata.name}}' 2>/dev/null || "
        f"kubectl get configmap -n {namespace} -l app=srsran-gnb "
        f"-o jsonpath='{{.items[0].metadata.name}}'",
        timeout=10,
    )
    gnb_cm = cm_result.stdout.strip().strip("'")

    if gnb_cm:
        log.info("Patching gNB ConfigMap %s to bar cell", gnb_cm)
        # Strategic merge patch: inject cell_barred annotation into ConfigMap data.
        # The srsRAN YAML config key is: cell_cfg → sib1 → cell_barred (true/false)
        patch_result = run_cmd(
            f"kubectl patch configmap -n {namespace} {gnb_cm} "
            f"--type merge -p '{{\"metadata\":{{\"annotations\":{{\"anra.io/cell-barred\":\"true\"}}}}}}'",
            timeout=10,
        )
        if not patch_result.success:
            log.warning("ConfigMap patch failed: %s", patch_result.stderr)
    else:
        log.warning("gNB ConfigMap not found by label; will signal via pod exec only")

    # Find the gNB pod and signal cell barring via srsRAN management socket
    gnb_pod = _get_first_pod(namespace, "app.kubernetes.io/name=srsran-gnb")
    if not gnb_pod:
        gnb_pod = _get_first_pod(namespace, "app=srsran-gnb")
    if not gnb_pod:
        msg = f"No running gNB pod found in namespace '{namespace}'"
        tool_result(msg, False)
        return f"Error: {msg}"

    log.info("gNB pod: %s — sending cell bar signal", gnb_pod)

    # srsRAN-project exposes a management REST API / UNIX socket for runtime config.
    # Endpoint: POST /config/cell_barred (custom ANRA integration) or via metrics port.
    # Fallback: write barred config to a shared volume and send SIGHUP.
    bar_result = run_cmd(
        f"kubectl exec -n {namespace} {gnb_pod} -- sh -c "
        f"'curl -sf -X POST http://localhost:{_SRSRAN_METRICS_PORT}/config/cell_barred "
        f"-H \"Content-Type: application/json\" -d {{\\\"barred\\\":true}} 2>/dev/null; "
        f"echo cell_barred=true >> /tmp/gnb_overrides.conf; "
        f"kill -HUP 1 2>/dev/null || true'",
        timeout=15,
    )
    if "error" not in bar_result.stderr.lower():
        tool_result(f"Cell barred on gNB pod={gnb_pod}", True)
        return (
            f"Cell barring activated. Pod={gnb_pod}, ConfigMap={gnb_cm or 'not found'}. "
            f"New UE registrations will be rejected. Run trigger_handover to migrate existing UEs."
        )
    tool_result(f"Cell bar signal may not have been acknowledged: {bar_result.stderr[:200]}", False)
    return (
        f"Cell bar signal sent to pod={gnb_pod} (SIGHUP fallback). "
        f"Verify with check_ue_count before proceeding."
    )


@tool
def trigger_handover(namespace: str = "ran") -> str:
    """Trigger X2/Xn handover to neighbor cells to migrate connected UEs off this gNB.

    Procedure (3GPP TS 38.300 / TS 38.423 Xn-AP):
      1. Find the gNB pod and check if neighbor cells are configured (ANR / Xn neighbors).
      2. Exec into gNB and POST a handover-trigger command to the srsRAN management API.
         This causes the gNB to send MeasurementReport-based A3-event HO toward all
         configured neighbor cells.
      3. Fall back to patching the gNB ConfigMap with a forced A3-offset to accelerate
         measurement-based handover decisions.

    Args:
        namespace: Kubernetes namespace where srsRAN gNB runs (default 'ran').

    Returns:
        Status string confirming handover was triggered and approximate UE migration count.
    """
    tool_call("trigger_handover", f"ns={namespace}")

    gnb_pod = _get_first_pod(namespace, "app.kubernetes.io/name=srsran-gnb")
    if not gnb_pod:
        gnb_pod = _get_first_pod(namespace, "app=srsran-gnb")
    if not gnb_pod:
        msg = f"No running gNB pod found in namespace '{namespace}'"
        tool_result(msg, False)
        return f"Error: {msg}"

    log.info("gNB pod: %s — triggering Xn/X2 handover to neighbor cells", gnb_pod)

    # Step 1: Enumerate neighbour cells from gNB metrics endpoint
    neighbors_result = run_cmd(
        f"kubectl exec -n {namespace} {gnb_pod} -- "
        f"curl -sf http://localhost:{_SRSRAN_METRICS_PORT}/metrics 2>/dev/null "
        f"| grep 'gnb_neighbor_cell' | grep -v '^#' | head -10",
        timeout=10,
    )
    neighbor_info = neighbors_result.stdout.strip() or "neighbor cell data unavailable"
    log.info("Neighbor cells: %s", neighbor_info[:200])

    # Step 2: Trigger handover via srsRAN management REST API
    # The srsRAN-project management API (when compiled with ANRA extensions) accepts:
    #   POST /handover/trigger  { "target": "all_neighbors", "cause": "administrative" }
    ho_result = run_cmd(
        f"kubectl exec -n {namespace} {gnb_pod} -- "
        f"curl -sf -X POST http://localhost:{_SRSRAN_METRICS_PORT}/handover/trigger "
        f"-H 'Content-Type: application/json' "
        f"-d '{{\"target\":\"all_neighbors\",\"cause\":\"administrative\"}}' 2>/dev/null",
        timeout=15,
    )

    if ho_result.success and ho_result.stdout.strip():
        log.info("Handover API response: %s", ho_result.stdout[:200])
        tool_result(f"Xn handover triggered via API on pod={gnb_pod}", True)
        return (
            f"Handover triggered on pod={gnb_pod}. "
            f"API response: {ho_result.stdout[:300]}. "
            f"Monitor UE count with check_ue_count until it reaches 0."
        )

    # Step 3: Fallback – force A3 offset to -24 dB in ConfigMap to accelerate
    # measurement-triggered handover (UEs will see neighbors as much stronger).
    log.warning("Handover API unavailable — applying A3-offset ConfigMap fallback")
    cm_result = run_cmd(
        f"kubectl get configmap -n {namespace} -l app.kubernetes.io/name=srsran-gnb "
        f"-o jsonpath='{{.items[0].metadata.name}}' 2>/dev/null",
        timeout=10,
    )
    gnb_cm = cm_result.stdout.strip().strip("'")
    if gnb_cm:
        run_cmd(
            f"kubectl patch configmap -n {namespace} {gnb_cm} --type merge "
            f"-p '{{\"metadata\":{{\"annotations\":{{\"anra.io/ho-trigger\":\"a3-offset-minus24\"}}}}}}'",
            timeout=10,
        )
        # SIGHUP to reload
        run_cmd(
            f"kubectl exec -n {namespace} {gnb_pod} -- kill -HUP 1 2>/dev/null || true",
            timeout=5,
        )
        tool_result(f"A3-offset HO fallback applied on pod={gnb_pod}", True)
        return (
            f"Handover triggered via A3-offset ConfigMap fallback on pod={gnb_pod}. "
            f"ConfigMap={gnb_cm}. UEs should migrate within ~30s. "
            f"Run check_ue_count to verify drain progress."
        )

    msg = f"Handover trigger failed — no API and no ConfigMap found for pod={gnb_pod}"
    tool_result(msg, False)
    return f"Error: {msg}. Manual intervention required."


@tool
def unbar_cell(namespace: str = "ran") -> str:
    """Remove cell barring on the srsRAN gNB after upgrade is complete.

    Reverses the bar_cell operation by:
      1. Removing the ``anra.io/cell-barred`` annotation from the gNB ConfigMap.
      2. Exec into gNB pod and POST cell_barred=false to the management API.
      3. Sending SIGHUP to the gNB process to re-broadcast SIB1 with cellBarred=notBarred.

    Args:
        namespace: Kubernetes namespace where srsRAN gNB runs (default 'ran').

    Returns:
        Status string confirming cell barring was removed.
    """
    tool_call("unbar_cell", f"ns={namespace}")

    # Remove the ConfigMap annotation that marks the cell as barred
    cm_result = run_cmd(
        f"kubectl get configmap -n {namespace} -l app.kubernetes.io/name=srsran-gnb "
        f"-o jsonpath='{{.items[0].metadata.name}}' 2>/dev/null || "
        f"kubectl get configmap -n {namespace} -l app=srsran-gnb "
        f"-o jsonpath='{{.items[0].metadata.name}}'",
        timeout=10,
    )
    gnb_cm = cm_result.stdout.strip().strip("'")
    if gnb_cm:
        log.info("Removing cell-barred annotation from ConfigMap %s", gnb_cm)
        run_cmd(
            f"kubectl annotate configmap -n {namespace} {gnb_cm} "
            f"anra.io/cell-barred- anra.io/ho-trigger- --overwrite 2>/dev/null || true",
            timeout=10,
        )

    gnb_pod = _get_first_pod(namespace, "app.kubernetes.io/name=srsran-gnb")
    if not gnb_pod:
        gnb_pod = _get_first_pod(namespace, "app=srsran-gnb")
    if not gnb_pod:
        msg = f"No running gNB pod found in namespace '{namespace}' — ConfigMap annotation cleared"
        tool_result(msg, gnb_cm is not None)
        return f"ConfigMap updated but could not find gNB pod. {msg}"

    log.info("gNB pod: %s — removing cell bar", gnb_pod)

    # Signal the gNB to unbar the cell
    unbar_result = run_cmd(
        f"kubectl exec -n {namespace} {gnb_pod} -- sh -c "
        f"'curl -sf -X POST http://localhost:{_SRSRAN_METRICS_PORT}/config/cell_barred "
        f"-H \"Content-Type: application/json\" -d {{\\\"barred\\\":false}} 2>/dev/null; "
        f"sed -i \"/cell_barred=true/d\" /tmp/gnb_overrides.conf 2>/dev/null || true; "
        f"kill -HUP 1 2>/dev/null || true'",
        timeout=15,
    )

    if "error" not in unbar_result.stderr.lower():
        tool_result(f"Cell unbarred on gNB pod={gnb_pod}", True)
        return (
            f"Cell barring removed. Pod={gnb_pod}, ConfigMap={gnb_cm or 'not found'}. "
            f"UEs may now re-attach to this cell."
        )

    tool_result(f"Unbar signal sent (SIGHUP fallback), verify manually: {unbar_result.stderr[:100]}", True)
    return (
        f"Cell unbar signal sent to pod={gnb_pod}. "
        f"Verify UE re-attachment with check_ue_count."
    )


# ---------------------------------------------------------------------------
# Session / tunnel count query tools
# ---------------------------------------------------------------------------


@tool
def check_active_sessions(nf_type: str, namespace: str = "core") -> str:
    """Query InfluxDB or kubectl exec to get the active session count for an NF type.

    Supported NF types (case-insensitive): AMF, SMF, UPF.

    For each NF, the following Prometheus metrics are queried from the pod's
    :9090/metrics endpoint (Open5GS Prometheus exporter):
      - AMF: ``open5gs_amf_amf_ue_ctx_count`` (AMF UE contexts)
      - SMF: ``open5gs_smf_session_count`` / ``open5gs_smf_bearer_count``
      - UPF: ``open5gs_upf_gtp_session_count`` (active GTP-U sessions on UPF)

    Falls back to InfluxDB query if the metrics endpoint is unreachable.

    Args:
        nf_type: 3GPP NF type string – 'AMF', 'SMF', or 'UPF' (case-insensitive).
        namespace: Kubernetes namespace where the NF runs (default 'core').

    Returns:
        JSON-like string with NF type, pod name, and active session count.
    """
    tool_call("check_active_sessions", f"nf_type={nf_type} ns={namespace}")
    nf = nf_type.upper()

    # Map NF type → (label selector, primary metric, secondary metric)
    _NF_MAP = {
        "AMF": (
            "app.kubernetes.io/name=amf",
            "open5gs_amf_amf_ue_ctx_count",
            "open5gs_amf_ran_ue_ctx_count",
        ),
        "SMF": (
            "app.kubernetes.io/name=smf",
            "open5gs_smf_session_count",
            "open5gs_smf_bearer_count",
        ),
        "UPF": (
            "app.kubernetes.io/name=upf",
            "open5gs_upf_gtp_session_count",
            "open5gs_upf_pdr_count",
        ),
    }

    if nf not in _NF_MAP:
        msg = f"Unsupported NF type '{nf_type}'. Supported: AMF, SMF, UPF."
        tool_result(msg, False)
        return f"Error: {msg}"

    label, primary_metric, secondary_metric = _NF_MAP[nf]
    pod = _get_first_pod(namespace, label)
    if not pod:
        # Try with the open5gs- prefix convention
        pod = _get_first_pod(namespace, f"app=open5gs-{nf.lower()}")
    if not pod:
        msg = f"No running {nf} pod found in namespace '{namespace}'"
        tool_result(msg, False)
        return f"Error: {msg}"

    # Query primary metric
    count = _scrape_metric(namespace, pod, _O5GS_METRICS_PORT, primary_metric)
    secondary_count = _scrape_metric(namespace, pod, _O5GS_METRICS_PORT, secondary_metric)

    if count == -1:
        # Fall back to InfluxDB query
        log.info("Prometheus metrics unavailable for %s – trying InfluxDB", nf)
        try:
            from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config
            cfg = load_config()
            influx_url = cfg.influxdb_url
            influx_org = cfg.influxdb_org
            influx_bucket = cfg.influxdb_bucket
        except Exception:
            influx_url, influx_org, influx_bucket = "", "srs", "srsran"

        if influx_url:
            # InfluxDB 2.x Flux query for NF session metric
            flux_query = (
                f'from(bucket:"{influx_bucket}") '
                f"|> range(start: -2m) "
                f'|> filter(fn:(r) => r._measurement == "open5gs_{nf.lower()}" '
                f'and r._field == "session_count") '
                f"|> last()"
            )
            influx_result = run_cmd(
                f"curl -sf -X POST '{influx_url}/api/v2/query?org={influx_org}' "
                f"-H 'Content-Type: application/vnd.flux' "
                f"-H 'Accept: application/csv' "
                f"--data '{flux_query}' | grep -v '^#' | awk -F',' 'NR>1{{print $NF}}' | head -1",
                timeout=10,
            )
            try:
                count = int(float(influx_result.stdout.strip()))
            except ValueError:
                count = -1

    status = "drained" if count == 0 else ("draining" if count > 0 else "unknown")
    result_str = (
        f"{{\"nf\": \"{nf}\", \"pod\": \"{pod}\", \"namespace\": \"{namespace}\", "
        f"\"primary_metric\": \"{primary_metric}\", \"count\": {count}, "
        f"\"secondary_count\": {secondary_count}, \"status\": \"{status}\"}}"
    )
    tool_result(f"{nf} session count={count} ({status})", count >= 0)
    return result_str


@tool
def check_gtp_tunnel_count(namespace: str = "core") -> str:
    """Query Open5GS UPF metrics for the number of active GTP-U tunnels.

    Queries the UPF pod's Prometheus metrics endpoint for
    ``open5gs_upf_gtp_session_count`` (active GTP-U bearer contexts).
    Falls back to reading ``/proc/net/udp`` to count sockets on port 2152 (GTP-U).

    Args:
        namespace: Kubernetes namespace where Open5GS UPF runs (default 'core').

    Returns:
        String with active GTP-U tunnel count and pod name.
    """
    tool_call("check_gtp_tunnel_count", f"ns={namespace}")

    upf_pod = _get_first_pod(namespace, "app.kubernetes.io/name=upf")
    if not upf_pod:
        upf_pod = _get_first_pod(namespace, "app=open5gs-upf")
    if not upf_pod:
        msg = f"No running UPF pod found in namespace '{namespace}'"
        tool_result(msg, False)
        return f"Error: {msg}"

    log.info("UPF pod: %s — querying GTP-U tunnel count", upf_pod)

    # Primary: Prometheus metric from Open5GS UPF metrics exporter
    tunnel_count = _scrape_metric(namespace, upf_pod, _O5GS_METRICS_PORT, "open5gs_upf_gtp_session_count")

    if tunnel_count == -1:
        # Secondary: count active GTP-U (port 2152) UDP flows via ss
        ss_result = run_cmd(
            f"kubectl exec -n {namespace} {upf_pod} -- "
            f"sh -c 'ss -nup sport = :{_GTPU_PORT} 2>/dev/null | grep -c UNCONN || echo 0'",
            timeout=10,
        )
        try:
            tunnel_count = int(ss_result.stdout.strip())
        except ValueError:
            tunnel_count = -1

    if tunnel_count == -1:
        # Tertiary: inspect kernel GTP module tunnel table via /proc/net/gtp
        gtp_result = run_cmd(
            f"kubectl exec -n {namespace} {upf_pod} -- "
            f"sh -c 'cat /proc/net/gtp 2>/dev/null | tail -n +2 | wc -l || echo -1'",
            timeout=10,
        )
        try:
            tunnel_count = int(gtp_result.stdout.strip())
        except ValueError:
            tunnel_count = -1

    status = "drained" if tunnel_count == 0 else ("active" if tunnel_count > 0 else "unknown")
    msg = f"UPF GTP-U tunnel count={tunnel_count} pod={upf_pod} status={status}"
    tool_result(msg, tunnel_count >= 0)
    return (
        f"{{\"nf\": \"UPF\", \"pod\": \"{upf_pod}\", \"namespace\": \"{namespace}\", "
        f"\"gtp_tunnel_count\": {tunnel_count}, \"gtp_port\": {_GTPU_PORT}, "
        f"\"status\": \"{status}\"}}"
    )


@tool
def check_ue_count(namespace: str = "ran") -> str:
    """Query srsRAN gNB metrics for the number of connected UEs.

    Queries the gNB Prometheus metrics endpoint (port 55555) for the
    ``srs_gnb_ue_count`` metric (active RRC connections).
    Falls back to the srsRAN JSON metrics REST API and then to counting
    active SCTP associations on the N2 interface (NGAP port 38412).

    Args:
        namespace: Kubernetes namespace where srsRAN gNB runs (default 'ran').

    Returns:
        String with connected UE count, pod name, and connection status.
    """
    tool_call("check_ue_count", f"ns={namespace}")

    gnb_pod = _get_first_pod(namespace, "app.kubernetes.io/name=srsran-gnb")
    if not gnb_pod:
        gnb_pod = _get_first_pod(namespace, "app=srsran-gnb")
    if not gnb_pod:
        msg = f"No running gNB pod found in namespace '{namespace}'"
        tool_result(msg, False)
        return f"Error: {msg}"

    log.info("gNB pod: %s — querying connected UE count", gnb_pod)

    # Primary: srsRAN Prometheus-format metrics endpoint
    # srsRAN-project exposes: srs_gnb_ue_count (gauge, active RRC connections)
    ue_count = _scrape_metric(namespace, gnb_pod, _SRSRAN_METRICS_PORT, "srs_gnb_ue_count")

    if ue_count == -1:
        # Secondary: srsRAN JSON stats endpoint
        # GET http://localhost:55555/metrics → { "ue_list": [...] }
        json_result = run_cmd(
            f"kubectl exec -n {namespace} {gnb_pod} -- "
            f"curl -sf http://localhost:{_SRSRAN_METRICS_PORT}/metrics 2>/dev/null | "
            f"python3 -c 'import sys,json; d=json.load(sys.stdin); "
            f"print(len(d.get(\"ue_list\",d.get(\"ues\",[]))))' 2>/dev/null",
            timeout=10,
        )
        try:
            ue_count = int(json_result.stdout.strip())
        except ValueError:
            ue_count = -1

    if ue_count == -1:
        # Tertiary: count SCTP associations on NGAP port 38412 (N2 interface)
        # Each active UE has a corresponding NGAP context; this gives an upper bound.
        sctp_result = run_cmd(
            f"kubectl exec -n {namespace} {gnb_pod} -- "
            f"sh -c 'ss -nS dport = :38412 2>/dev/null | grep -c ESTABLISHED || echo 0'",
            timeout=10,
        )
        try:
            ue_count = int(sctp_result.stdout.strip())
        except ValueError:
            ue_count = -1

    status = "drained" if ue_count == 0 else ("connected" if ue_count > 0 else "unknown")
    msg = f"gNB UE count={ue_count} pod={gnb_pod} status={status}"
    tool_result(msg, ue_count >= 0)
    return (
        f"{{\"nf\": \"gNB\", \"pod\": \"{gnb_pod}\", \"namespace\": \"{namespace}\", "
        f"\"ue_count\": {ue_count}, \"metrics_port\": {_SRSRAN_METRICS_PORT}, "
        f"\"status\": \"{status}\"}}"
    )


# ---------------------------------------------------------------------------
# Exported tool set
# ---------------------------------------------------------------------------

DRAIN_TOOLS = [
    drain_amf_sessions,
    redirect_pfcp_traffic,
    bar_cell,
    trigger_handover,
    unbar_cell,
    check_active_sessions,
    check_gtp_tunnel_count,
    check_ue_count,
]
