# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Day2 Monitoring Agent — Watches RAN/Core metrics and Alertmanager,
generates remediation SOPs via Bedrock, and executes approved fixes.

Supports two alert sources:
1. Alertmanager (Prometheus alerts) — standard K8s monitoring
2. InfluxDB (RAN + Core metrics) — 5G-specific threshold evaluation

Loads vendor-specific alarm references for domain context in SOP generation.
"""

import json
import logging
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import ModelTier

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] [monitor] %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ──
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
ALERTMANAGER_URL = os.getenv("ALERTMANAGER_URL", "")
INFLUX_URL = os.getenv("INFLUX_URL", "")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "srs")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "srsran")
SOP_REPO = os.getenv("SOP_REPO", str(Path(__file__).parent.parent))
BEDROCK_PROFILE = os.getenv("BEDROCK_PROFILE", "")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-west-2")
ALARM_REFERENCE_PATH = os.getenv(
    "ALARM_REFERENCE_PATH", str(Path(__file__).parent.parent / "alarm-references" / "generic-5g.json")
)
APPROVAL_MODE = os.getenv("APPROVAL_MODE", "auto")  # auto | manual | gitlab

# Load alarm reference — from config alarms, fallback to JSON file
_alarm_ref = {}
try:
    from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config as _load_cfg

    _cfg = _load_cfg()
    if _cfg.alarms:
        _alarm_ref = {
            a.name: {
                "layer": a.layer,
                "depends_on": a.depends_on,
                "nf_scope": a.nf_scope,
                "severity": a.severity,
                "service_impact": a.service_impact,
                "probable_cause": a.probable_cause,
                "sop": a.sop,
            }
            for a in _cfg.alarms
        }
        log.info(f"Loaded {len(_alarm_ref)} alarm definitions from config")
except Exception:
    _cfg = None

if not _alarm_ref:
    try:
        with open(ALARM_REFERENCE_PATH) as f:
            _alarm_ref = json.load(f)
        log.info(f"Loaded {len(_alarm_ref)} alarm definitions from {ALARM_REFERENCE_PATH}")
    except FileNotFoundError:
        log.info("No alarm reference file — SOP generation uses generic context only")


def _run(cmd, timeout=10):
    try:
        import shlex
        r = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"(error: {e})"


# ── InfluxDB Alert Source (delegated to agents/kpi_monitor/) ──
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.influx_source import query_influx as _query_influx_impl

_last_influx_results: dict = {}


def _query_influx(measurement, fields):
    """Query InfluxDB for latest values of specified fields."""
    result = _query_influx_impl(measurement, fields)
    _last_influx_results[measurement] = result
    return result


# Statistical anomaly detection lives in
# agents/anra/monitoring/anomaly_detection.py. Imported here so run_loop
# calls it unchanged; BEDROCK_CLASSIFY_COOLDOWN / _baselines are re-exported
# for monitoring_stats, which reads them for the dashboard.
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.anomaly_detection import (  # noqa: E402,F401
    BEDROCK_CLASSIFY_COOLDOWN,
    _baselines,
    evaluate_dynamic_anomalies,
)


_SOURCE_MEASUREMENT = {"ran": "srsran", "core": "core_network", "kubernetes": "core_network", "os": "os_metrics"}


def _eval_condition(val, condition):
    """Parse '> 500' or '< 1' and evaluate."""
    op, threshold = condition.strip().split(None, 1)
    threshold = float(threshold)
    return (
        (op == ">" and val > threshold)
        or (op == "<" and val < threshold)
        or (op == ">=" and val >= threshold)
        or (op == "<=" and val <= threshold)
        or (op == "==" and val == threshold)
    )


def evaluate_thresholds():
    """Evaluate all alarm rules from config against InfluxDB metrics."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config

    cfg = load_config()
    alarms = cfg.alarms
    if not alarms:
        return evaluate_ran_thresholds_legacy() + evaluate_os_thresholds_legacy()

    alerts = []
    # Group by source → single InfluxDB query per measurement
    by_source = {}
    for alarm in alarms:
        by_source.setdefault(alarm.source, []).append(alarm)

    for source, source_alarms in by_source.items():
        measurement = _SOURCE_MEASUREMENT.get(source, source)
        fields = list({a.metric_field for a in source_alarms})
        vals = _query_influx(measurement, fields)
        for alarm in source_alarms:
            val = vals.get(alarm.metric_field)
            if val is None:
                continue
            if _eval_condition(val, alarm.condition):
                alerts.append(
                    {
                        "name": alarm.name,
                        "value": val,
                        "threshold": alarm.condition,
                        "severity": alarm.perceived_severity or alarm.severity,
                        "service_impact": alarm.service_impact,
                        "probable_cause": alarm.probable_cause,
                        "sop": alarm.sop,
                        "source": "influxdb",
                        "alarmId": alarm.alarm_id,
                        "alarmType": alarm.alarm_type,
                        "probableCauseCode": alarm.probable_cause_code,
                        "perceivedSeverity": alarm.perceived_severity or alarm.severity,
                        "managedObjectClass": alarm.managed_object_class,
                        "specificProblem": alarm.specific_problem,
                    }
                )
    return alerts


def evaluate_ran_thresholds():
    """Config-driven thresholds for RAN + Core (backward compat wrapper)."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config

    cfg = load_config()
    alarms = [a for a in cfg.alarms if a.source in ("ran", "core")]
    if not alarms:
        return evaluate_ran_thresholds_legacy()

    alerts = []
    by_source = {}
    for alarm in alarms:
        by_source.setdefault(alarm.source, []).append(alarm)

    for source, source_alarms in by_source.items():
        measurement = _SOURCE_MEASUREMENT.get(source, source)
        fields = list({a.metric_field for a in source_alarms})
        vals = _query_influx(measurement, fields)
        for alarm in source_alarms:
            val = vals.get(alarm.metric_field)
            if val is not None and _eval_condition(val, alarm.condition):
                alerts.append(
                    {
                        "name": alarm.name,
                        "value": val,
                        "threshold": alarm.condition,
                        "severity": alarm.perceived_severity or alarm.severity,
                        "service_impact": alarm.service_impact,
                        "probable_cause": alarm.probable_cause,
                        "sop": alarm.sop,
                        "source": "influxdb",
                        "alarmId": alarm.alarm_id,
                        "alarmType": alarm.alarm_type,
                        "probableCauseCode": alarm.probable_cause_code,
                        "perceivedSeverity": alarm.perceived_severity or alarm.severity,
                        "managedObjectClass": alarm.managed_object_class,
                        "specificProblem": alarm.specific_problem,
                    }
                )
    return alerts


def evaluate_ran_thresholds_legacy():
    """Legacy hardcoded RAN + Core thresholds — used when config has no alarms."""
    alerts = []
    ran_fields = [
        "cells_0_ue_list_0_dl_brate",
        "cells_0_ue_list_0_cqi",
        "du_du_high_mac_dl_0_cpu_usage_percent",
        "du_du_high_mac_dl_0_max_latency_us",
        "cells_0_cell_metrics_late_dl_harqs",
        "cells_0_cell_metrics_error_indication_count",
    ]
    core_fields = [
        "amf_gnb_connected",
        "upf_pfcp_active",
        "core_nf_health_pct",
        "alarm_amf_reject",
        "alarm_upf_heartbeat_lost",
        "alarm_scp_timeout",
        "amf_fivegs_amffunction_rm_reginitfail",
        "amf_fivegs_amffunction_amf_authreject",
        "smf_fivegs_smffunction_sm_n4sessionestabfail",
        "smf_gtp_peers_active",
        "upf_fivegs_ep_n3_gtp_indatapktn3upf",
        "amf_gnb",
        "smf_ues_active",
    ]
    ran = _query_influx("srsran", ran_fields)
    core = _query_influx("core_network", core_fields)
    vals = {**ran, **core}
    rules = [
        ("du_cpu_overload", "du_du_high_mac_dl_0_cpu_usage_percent", "gt", 80),
        ("du_timing_failure", "cells_0_cell_metrics_error_indication_count", "gt", 500),
        ("du_throughput_drop", "cells_0_ue_list_0_dl_brate", "lt", 500_000),
        ("amf_gnb_disconnect", "amf_gnb", "lt", 1),
        ("nf_crashloop", "core_nf_health_pct", "lt", 95),
        ("sbi_mesh_failure", "alarm_scp_timeout", "gt", 0),
        ("amf_registration_failure", "amf_fivegs_amffunction_rm_reginitfail", "gt", 0),
        ("amf_auth_rejection", "amf_fivegs_amffunction_amf_authreject", "gt", 0),
        ("smf_pfcp_failure", "smf_fivegs_smffunction_sm_n4sessionestabfail", "gt", 0),
        ("upf_no_traffic", "upf_fivegs_ep_n3_gtp_indatapktn3upf", "eq", 0),
    ]
    for alarm_name, field, op, threshold in rules:
        val = vals.get(field)
        if val is None:
            continue
        triggered = (
            (op == "gt" and val > threshold) or (op == "lt" and val < threshold) or (op == "eq" and val == threshold)
        )
        if triggered:
            ref = _alarm_ref.get(alarm_name, {})
            alerts.append(
                {
                    "name": alarm_name,
                    "value": val,
                    "threshold": threshold,
                    "severity": ref.get("severity", "warning"),
                    "service_impact": ref.get("service_impact", ""),
                    "probable_cause": ref.get("probable_cause", ""),
                    "sop": ref.get("sop", ""),
                    "source": "influxdb",
                }
            )
    return alerts


def evaluate_os_thresholds():
    """Config-driven thresholds for OS/infra (backward compat wrapper)."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config

    cfg = load_config()
    alarms = [a for a in cfg.alarms if a.source == "os"]
    if not alarms:
        return evaluate_os_thresholds_legacy()

    alerts = []
    fields = list({a.metric_field for a in alarms})
    vals = _query_influx("os_metrics", fields)
    for alarm in alarms:
        val = vals.get(alarm.metric_field)
        if val is not None and _eval_condition(val, alarm.condition):
            alerts.append(
                {
                    "name": alarm.name,
                    "value": val,
                    "threshold": alarm.condition,
                    "severity": alarm.severity,
                    "service_impact": alarm.service_impact,
                    "probable_cause": alarm.probable_cause,
                    "sop": alarm.sop,
                    "source": "influxdb",
                }
            )
    return alerts


def evaluate_os_thresholds_legacy():
    """Legacy hardcoded OS thresholds — used when config has no alarms."""
    alerts = []
    os_fields = [
        "node_pressure_memory_stalled_seconds_total",
        "node_memory_HugePages_Free",
        "node_cpu_steal_percent",
        "ptp_offset_ns",
    ]
    vals = _query_influx("os_metrics", os_fields)
    rules = [
        ("memory_pressure", "node_pressure_memory_stalled_seconds_total", "gt", 10),
        ("hugepage_exhaustion", "node_memory_HugePages_Free", "eq", 0),
        ("high_cpu_steal", "node_cpu_steal_percent", "gt", 5),
        ("ptp_offset_drift", "ptp_offset_ns", "gt", 1500),
    ]
    for alarm_name, field, op, threshold in rules:
        val = vals.get(field)
        if val is None:
            continue
        triggered = (op == "gt" and val > threshold) or (op == "eq" and val == threshold)
        if triggered:
            ref = _alarm_ref.get(alarm_name, {})
            alerts.append(
                {
                    "name": alarm_name,
                    "value": val,
                    "threshold": threshold,
                    "severity": ref.get("severity", "warning"),
                    "service_impact": ref.get("service_impact", ""),
                    "probable_cause": ref.get("probable_cause", ""),
                    "sop": ref.get("sop", ""),
                    "source": "influxdb",
                }
            )
    return alerts


# ANRA detection sources now live in agents/anra/monitoring/. Imported here so
# run_loop calls them unchanged.
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.cloudwatch_events import (  # noqa: E402
    poll_cloudwatch_k8s_events,
    poll_k8s_pod_health,
)


# Hardware event-log polling (BMC/iDRAC System Event Log over Redfish) lives
# in agents/anra/monitoring/hardware_event_log.py. Imported here so run_loop
# calls it unchanged.
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.hardware_event_log import (  # noqa: E402
    poll_redfish_sel,
)


# ── Alertmanager Source ──


def fetch_alertmanager_alerts():
    """Fetch active alerts from Alertmanager."""
    if not ALERTMANAGER_URL:
        return []
    raw = _run(f"curl -s {ALERTMANAGER_URL}/api/v2/alerts", timeout=10)
    try:
        data = json.loads(raw)
        return [
            {
                "name": a["labels"].get("alertname", "unknown"),
                "severity": a["labels"].get("severity", "warning"),
                "service_impact": a.get("annotations", {}).get("summary", ""),
                "probable_cause": a.get("annotations", {}).get("description", ""),
                "sop": "",
                "source": "alertmanager",
            }
            for a in data
            if a.get("status", {}).get("state") == "active"
            and a["labels"].get("alertname") not in {"Watchdog", "InfoInhibitor"}
        ]
    except (json.JSONDecodeError, TypeError):
        return []


# ── SOP Resolution ──


def resolve_sop(alert):
    """Find existing SOP or generate one via Bedrock."""
    # Check if alarm reference points to an existing SOP
    sop_path = alert.get("sop", "")
    if sop_path:
        full = Path(SOP_REPO) / "sops" / sop_path
        if full.exists():
            log.info(f"Using existing SOP: {sop_path}")
            return str(full)

    # Generate remediation SOP via Bedrock
    log.info(f"Generating SOP for {alert['name']} via Bedrock")
    return _generate_sop(alert)


def _generate_sop(alert):
    """Generate a remediation SOP using Bedrock with full context."""
    try:
        from strands import Agent

        from amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver import (
            build_model,
        )

        model = build_model(ModelTier.FAST)

        # Load SOP template for format reference
        template = (Path(SOP_REPO) / "sops" / "TEMPLATE.md").read_text()

        # Build context from alert — includes vendor resolution for Redfish events
        context_parts = [
            f"Alarm: {alert['name']}",
            f"Severity: {alert['severity']}",
            f"Service Impact: {alert.get('service_impact', 'Unknown')}",
            f"Probable Cause: {alert.get('probable_cause', 'Unknown')}",
            f"Current Value: {alert.get('value', 'N/A')}",
            f"Threshold: {alert.get('threshold', 'N/A')}",
        ]
        # Redfish-enriched context
        if alert.get("vendor_resolution"):
            context_parts.append(f"Vendor Resolution: {alert['vendor_resolution']}")
        if alert.get("vendor_description"):
            context_parts.append(f"Vendor Description: {alert['vendor_description']}")
        if alert.get("live_thermal"):
            context_parts.append(f"Live Thermal: {json.dumps(alert['live_thermal'])}")
        if alert.get("live_power"):
            context_parts.append(f"Live Power: {json.dumps(alert['live_power'])}")
        if alert.get("running_pods"):
            context_parts.append(f"Running Pods on Node:\n{alert['running_pods']}")
        if alert.get("node_roles"):
            context_parts.append(f"Node Roles: {alert['node_roles']}")

        agent = Agent(
            model=model,
            system_prompt=f"""You generate remediation SOPs for 5G network and hardware alarms.
Follow this template format exactly:
{template}

The SOP must be executable by an AI agent with kubectl, ssm_command, and redfish_query tools.
Include diagnostic steps, remediation, verification, and rollback.
Use the vendor's recommended resolution as the primary remediation approach.""",
        )

        result = agent("\n".join(context_parts))
        # Save generated SOP
        sop_dir = Path("/tmp/generated-sops")  # nosec B108 — container tmpfs, no symlink risk
        sop_dir.mkdir(parents=True, exist_ok=True)
        sop_file = sop_dir / f"remediate-{alert['name']}.md"
        sop_file.write_text(str(result))
        log.info(f"Generated SOP: {sop_file}")
        return str(sop_file)
    except Exception as e:
        log.error(f"SOP generation failed: {e}")
        return None


# ── Execution ──


def execute_sop(sop_path, alert):
    """Execute a remediation SOP through the SOP executor."""
    log.info(f"Executing SOP: {sop_path} for alarm: {alert['name']}")
    start = time.time()
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.sop_executor import create_agent

        agent, _ = create_agent(
            profile=BEDROCK_PROFILE or None,
            region=BEDROCK_REGION,
            model_name="haiku",
            fix_mode=True,
            sop_path=sop_path,
        )
        result = agent(f"Execute this remediation SOP: {sop_path}\nAlarm: {alert['name']}, Value: {alert.get('value')}")
        duration = round(time.time() - start, 1)
        # Extract eval data from steering hooks if available
        hooks = getattr(agent, "_hooks", None) or {}
        tool_count = getattr(hooks, "tool_count", 0) if hasattr(hooks, "tool_count") else 0
        log.info(f"SOP execution complete for {alert['name']}")
        try:
            from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_activity
            push_activity("execute", "%s SOP completed" % alert["name"], status="success")
        except Exception:
            pass
        return {
            "status": "completed",
            "duration_seconds": duration,
            "tool_count": tool_count,
            "model": "haiku",
            "output": str(result)[:500],
        }
    except Exception as e:
        duration = round(time.time() - start, 1)
        log.error(f"SOP execution failed: {e}")
        return {"status": "error", "duration_seconds": duration, "error": str(e)}


# ── Main Loop ──

_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="sop")
_active_sops: set = set()
_suppressed: dict = {}
_dynamic_sop_count: int = 0
_dynamic_sop_reset: float = 0
MAX_DYNAMIC_SOPS_PER_HOUR = int(
    os.getenv("MAX_DYNAMIC_SOPS_PER_HOUR", str(_cfg.anomaly_detection.max_sops_per_hour if _cfg else 3))
)


# ── SOP Enrichment Pipeline ──


def _scan_environment(alert):
    """Scan live environment for SOP enrichment. Layer-aware."""
    layer = _alarm_ref.get(alert.get("name", ""), {}).get("layer", -1)
    scan = {"tools": "kubectl, ssm_command(instance_id, cmd), redfish_query(bmc_ip, endpoint)"}

    if layer == 0:
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config

        cfg = load_config()
        for n in cfg.nodes:
            if n.bmc.ip:
                scan[f"node_{n.name}"] = f"SSM={n.ssm_id} IP={n.oam_ip} BMC={n.bmc.ip}"
        scan["affected_pods"] = _run("kubectl get pods --all-namespaces --no-headers")[:500]
    elif layer == 1:
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config

        cfg = load_config()
        for n in cfg.nodes:
            scan[f"node_{n.name}"] = f"SSM_ID={n.ssm_id} IP={n.oam_ip} roles={n.roles}"
        scan["nodes"] = _run("kubectl get nodes -o wide --no-headers")[:500]
    elif layer == 2:
        scan["pods"] = _run("kubectl get pods -n open5gs -o wide --no-headers")[:800]
        scan["events"] = _run(
            "kubectl get events -n open5gs --sort-by=.lastTimestamp --field-selector type=Warning --no-headers"
        )[:500]
        scan["nf_deps"] = "Auth: AMF→AUSF→UDM→UDR→MongoDB. Session: SMF→UPF(PFCP:8805). UPF on edge hostNetwork."
        scan["cross_cni"] = "Region pods CANNOT reach edge Cilium pod IPs. UPF reachable via host IP only."
    elif layer == 3:
        scan["pods"] = _run("kubectl get pods -n srsran -o wide --no-headers")[:500]
        scan["gnb_logs"] = _run("kubectl logs deploy/srsran-gnb -n srsran --tail=20")[:1000]
        scan["ran_info"] = (
            "srsRAN: NO vendor CLI (no ductl). WebSocket :55555 for metrics. testmode=ru_dummy. FAPI warnings are normal."
        )
    elif layer == 4:
        scan["ue_logs"] = _run("kubectl logs deploy/ueransim-ue -n srsran -c ue --tail=20")[:500]
    else:
        scan["pods"] = _run("kubectl get pods -n open5gs -o wide --no-headers")[:500]
    return scan


def _enrich_sop(sop_content, alert):
    """Rewrite SOP with real environment values. One Haiku call."""
    try:
        scan = _scan_environment(alert)
        from strands import Agent

        from amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver import (
            build_model,
        )

        model = build_model(ModelTier.FAST)
        agent = Agent(
            model=model,
            system_prompt="Rewrite SOPs with real environment values. Output ONLY the rewritten SOP markdown.",
        )
        result = str(
            agent(f"""Rewrite this SOP replacing placeholders with real values from the environment scan.
RULES: Replace <pod-name>/<namespace>/MI_INSTANCE_ID with actual values. Remove fictional vendor CLIs (ductl, srsctl). Use ONLY kubectl/ssm_command/redfish_query.

ENVIRONMENT:
{json.dumps(scan, indent=2)[:3000]}

SOP:
{sop_content[:4000]}""")
        )
        log.info(f"SOP enriched ({len(sop_content)}→{len(result)} chars)")
        return result
    except Exception as e:
        log.warning(f"SOP enrichment Bedrock call failed: {e}")
        return sop_content


def _submit_sop(alert, correlation_result=None):
    """Submit SOP execution to thread pool. Non-blocking."""
    global _dynamic_sop_count, _dynamic_sop_reset

    if alert["name"] in _active_sops:
        log.info(f"SOP already running for {alert['name']}")
        return

    # Rate limit dynamic anomaly SOPs
    if alert.get("source") == "dynamic-anomaly":
        if time.time() - _dynamic_sop_reset > 3600:
            _dynamic_sop_count = 0
            _dynamic_sop_reset = time.time()
        if _dynamic_sop_count >= MAX_DYNAMIC_SOPS_PER_HOUR:
            log.warning(f"RATE LIMITED: {alert['name']} — max {MAX_DYNAMIC_SOPS_PER_HOUR} dynamic SOPs/hour reached")
            return
        _dynamic_sop_count += 1
    sop_path = resolve_sop(alert)
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_activity
        push_activity("resolve", "SOP: %s" % (sop_path or "generating..."))
    except Exception:
        pass
    if not sop_path:
        log.warning(f"No SOP available for {alert['name']}")
        return

    # Enrich SOP with real environment values before execution
    try:
        sop_content = Path(sop_path).read_text()
        log.info(f"Enriching SOP for {alert['name']} ({len(sop_content)} chars)")
        enriched = _enrich_sop(sop_content, alert)
        try:
            from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_activity
            push_activity("enrich", "Bedrock enriching SOP for %s" % alert["name"])
        except Exception:
            pass
        if enriched != sop_content:
            enriched_path = f"/tmp/{Path(sop_path).stem}-enriched.md"  # nosec B108
            Path(enriched_path).write_text(enriched)
            sop_path = enriched_path
            log.info(f"Using enriched SOP: {enriched_path}")
        else:
            log.info("Enrichment returned original (Bedrock unavailable or no changes)")
    except Exception as e:
        log.warning(f"Enrichment failed for {alert['name']}: {e}")

    if APPROVAL_MODE != "auto":
        log.info(f"Approval required for {alert['name']} — SOP: {sop_path}")
        try:
            from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_pending_approval

            # Enrich alert with alarm reference context (NF identity for cross-agent handover)
            ref = _alarm_ref.get(alert["name"], {})
            alert["layer"] = ref.get("layer", -1)
            alert["nf_scope"] = ref.get("nf_scope", "")
            push_pending_approval(alert["name"], sop_path, alert)
        except Exception as e:
            log.debug(f"Non-critical: {e}")
        return
    _active_sops.add(alert["name"])

    def _run():
        try:
            result = execute_sop(sop_path, alert)
            log.info(f"SOP complete for {alert['name']}: {result.get('status')}")
            try:
                from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_execution

                push_execution(
                    {
                        "alarm": alert["name"],
                        "sop": sop_path,
                        "result": result.get("status", "unknown"),
                        "correlation": (correlation_result or {}).get("reasoning", ""),
                    }
                )
            except Exception as e:
                log.debug(f"Non-critical: {e}")
        except Exception as e:
            log.error(f"SOP failed for {alert['name']}: {e}")
        finally:
            _active_sops.discard(alert["name"])

    _executor.submit(_run)


def run_loop():
    seen = {}  # alarm_name -> last_seen timestamp
    cycle = 0

    log.info(f"Monitor starting — poll every {POLL_INTERVAL}s")
    log.info(f"InfluxDB: {INFLUX_URL or '(disabled)'}")
    log.info(f"Alertmanager: {ALERTMANAGER_URL or '(disabled)'}")
    log.info(f"Approval mode: {APPROVAL_MODE}")
    log.info(f"Alarm reference: {len(_alarm_ref)} definitions")

    # Start Redfish event receiver if any nodes have BMC configured
    from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config

    cfg = load_config()
    redfish_queue = None
    if any(n.bmc.ip for n in cfg.nodes):
        from amzn_cse_telco_autonomous_network_agents_app.agent.redfish_events import enrich_event, event_queue, start_receiver, subscribe_bmc

        start_receiver(port=8081)
        redfish_queue = event_queue
        # Subscribe to all BMCs
        # Subscribe to all BMCs — webhook goes to relay pod on same node (hostNetwork:8080)
        webhook_ip = next((n.oam_ip for n in cfg.nodes if n.bmc.ip), "")
        if webhook_ip:
            for node in cfg.nodes:
                if node.bmc.ip:
                    subscribe_bmc(node, f"http://{node.oam_ip}:8080/redfish-events")
        log.info(f"Redfish events: enabled for {len([n for n in cfg.nodes if n.bmc.ip])} BMCs")

    while True:
        try:
            cycle += 1
            alerts = (
                evaluate_ran_thresholds()
                + evaluate_os_thresholds()
                + fetch_alertmanager_alerts()
                + poll_redfish_sel()
                + poll_cloudwatch_k8s_events()
                + poll_k8s_pod_health()
                + evaluate_dynamic_anomalies()
            )

            # Drain injected alarms (from demo trigger buttons)
            try:
                from amzn_cse_telco_autonomous_network_agents_app.agent.routers.alarms import _injected_queue
                while _injected_queue:
                    alerts.append(_injected_queue.pop(0))
            except Exception:
                pass

            # Update active alarm set (clears alarms that stopped firing)
            from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import clear_alarms

            clear_alarms({a["name"] for a in alerts})
            try:
                from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_activity
                if alerts:
                    push_activity("collect", "Cycle %d: %d alerts from 6 sources" % (cycle, len(alerts)))
            except Exception:
                pass

            # Drain Redfish event queue
            if redfish_queue:
                while not redfish_queue.empty():
                    raw_event = redfish_queue.get_nowait()
                    enriched = enrich_event(raw_event, cfg)
                    alerts.append(
                        {
                            "name": enriched.get("message_id", "hw_unknown"),
                            "severity": enriched.get("severity", "warning"),
                            "service_impact": enriched.get("message", ""),
                            "probable_cause": enriched.get("vendor_description", ""),
                            "vendor_resolution": enriched.get("vendor_resolution", ""),
                            "vendor_description": enriched.get("vendor_description", ""),
                            "live_thermal": enriched.get("live_thermal"),
                            "live_power": enriched.get("live_power"),
                            "running_pods": enriched.get("running_pods", ""),
                            "node_roles": enriched.get("node_roles", []),
                            "source": "redfish",
                        }
                    )

            # Record all alerts to event timeline (buffer + InfluxDB)
            try:
                from amzn_cse_telco_autonomous_network_agents_app.agent.event_store import record

                for a in alerts:
                    record(a, _alarm_ref)
            except Exception as e:
                log.debug(f"Event recording failed: {e}")

            # Record for trend analysis
            try:
                from amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.trend import record_alarm as _record_trend

                for a in alerts:
                    _record_trend(a["name"])
            except Exception as e:
                log.debug(f"Trend recording failed: {e}")

            # Dedup — only process new alerts
            new_alerts = []
            for a in alerts:
                if a["name"] not in seen:
                    new_alerts.append(a)
                seen[a["name"]] = time.time()

            # Clean stale (not seen in 5 minutes)
            active = {a["name"] for a in alerts}
            stale = [k for k, v in seen.items() if k not in active and time.time() - v > 300]
            for k in stale:
                del seen[k]

            # Storm batching: if too many alarms at once, batch-correlate
            try:
                from amzn_cse_telco_autonomous_network_agents_app.agent.correlator import STORM_THRESHOLD, correlate_batch
                from amzn_cse_telco_autonomous_network_agents_app.agent.event_store import get_recent

                if len(new_alerts) > STORM_THRESHOLD:
                    log.info(f"ALARM STORM: {len(new_alerts)} alarms, batch correlating")
                    result = correlate_batch(new_alerts, get_recent(), _alarm_ref)
                    try:
                        from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_correlation

                        push_correlation(result)
                    except Exception as e:
                        log.debug(f"Non-critical: {e}")
                    root_alert = next((a for a in new_alerts if a["name"] == result["root_cause"]), new_alerts[0])
                    for a in new_alerts:
                        try:
                            from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_alarm

                            if a["name"] in result["symptoms"]:
                                push_alarm({**a, "suppressed": True, "root_cause": result["root_cause"]})
                                _suppressed[a["name"]] = result["root_cause"]
                            else:
                                push_alarm(a)
                        except Exception as e:
                            log.debug(f"Non-critical: {e}")
                    _submit_sop(root_alert, result)
                    new_alerts = []  # skip per-alarm loop
            except Exception as e:
                log.debug(f"Storm batching failed: {e}")

            for alert in new_alerts:
                log.info(
                    f"NEW ALARM: {alert['severity'].upper()} {alert['name']} "
                    f"(value={alert.get('value')}, source={alert['source']})"
                )

                try:
                    from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_activity
                    push_activity("detect", "%s — %s %s" % (alert["name"], alert.get("value", ""), alert.get("threshold", "")), status="warning")
                except Exception:
                    pass

                # Push to API for dashboard visibility
                try:
                    from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_alarm, push_correlation

                    push_alarm(alert)
                except Exception as e:
                    log.debug(f"Non-critical: {e}")

                # Correlate with recent events
                correlation_result = None
                try:
                    from amzn_cse_telco_autonomous_network_agents_app.agent.correlator import STORM_THRESHOLD, correlate, correlate_batch, rca_investigate
                    from amzn_cse_telco_autonomous_network_agents_app.agent.event_store import get_recent

                    recent = get_recent()
                    result = correlate(alert, recent, _alarm_ref)

                    if result["action"] == "escalate":
                        log.info(f"ESCALATING: {alert['name']} — invoking RCA agent")
                        result = rca_investigate(
                            recent
                            + [
                                {
                                    "name": alert["name"],
                                    "ts": time.time(),
                                    "severity": alert.get("severity", ""),
                                    "layer": _alarm_ref.get(alert["name"], {}).get("layer", -1),
                                    "source": alert.get("source", ""),
                                    "node": alert.get("node_name", ""),
                                    "nf": alert.get("nf_instance", ""),
                                    "value": alert.get("value", 0),
                                }
                            ],
                            _alarm_ref,
                        )

                    correlation_result = result
                    try:
                        push_correlation(result)
                    except Exception as e:
                        log.debug(f"Non-critical: {e}")

                    if result["action"] == "suppress":
                        log.info(f"SUPPRESSED: {alert['name']} ← symptom of {result['root_cause']}")
                        try:
                            push_alarm({**alert, "suppressed": True, "root_cause": result["root_cause"]})
                        except Exception as e:
                            log.debug(f"Non-critical: {e}")
                        _suppressed[alert["name"]] = result["root_cause"]
                        continue

                    log.info(
                        f"CORRELATE: {alert['name']} action={result['action']} "
                        f"confidence={result['confidence']} root={result['root_cause']}"
                    )
                    try:
                        from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_activity
                        push_activity("correlate", "%s -> %s (root: %s)" % (alert["name"], result["action"], result["root_cause"]), status="success")
                    except Exception:
                        pass
                except Exception as e:
                    log.debug(f"Correlation failed: {e}")

                # Execute SOP (async via thread pool)
                _submit_sop(alert, correlation_result)

            # Re-evaluate suppressed alarms after root cause SOP completes
            for sym, root in list(_suppressed.items()):
                if root not in _active_sops and sym in active:
                    log.info(f"RE-EVAL: {sym} still active after {root} fixed")
                    try:
                        from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_activity
                        push_activity("reeval", "%s still active after %s fixed" % (sym, root), status="warning")
                    except Exception:
                        pass
                    del _suppressed[sym]
                    seen.pop(sym, None)

            if cycle % 10 == 0:
                log.info(f"Cycle {cycle}: {len(alerts)} active alarms, {len(seen)} tracked")
                # Check for escalating alarm trends
                try:
                    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.trend import detect_escalating_alarms

                    escalating = detect_escalating_alarms()
                    if escalating:
                        from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_activity
                        for esc in escalating:
                            log.warning(
                                "TREND: %s escalating (%dx in 24h vs %dx prev, ratio=%.1f)",
                                esc["alarm"], esc["last_24h"], esc["prev_24h"], esc["ratio"],
                            )
                            push_activity(
                                "detect",
                                f"Trend: {esc['alarm']} escalating ({esc['last_24h']}x in 24h, was {esc['prev_24h']}x)",
                                status="warning",
                            )
                        # Auto-investigate escalating trends
                        try:
                            from amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.auto_investigate import maybe_investigate_trend
                            maybe_investigate_trend(escalating)
                        except Exception as e:
                            log.debug(f"Auto-investigation failed: {e}")
                except Exception as e:
                    log.debug(f"Trend detection failed: {e}")

        except Exception as e:
            log.error(f"Monitor cycle failed: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_loop()
