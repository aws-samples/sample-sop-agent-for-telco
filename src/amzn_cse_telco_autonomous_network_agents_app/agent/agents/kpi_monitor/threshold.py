# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Threshold-based alarm evaluation — Tier 1 of the detection pipeline."""

import logging

from .influx_source import query_influx

log = logging.getLogger("monitor")

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
    by_source = {}
    for alarm in alarms:
        by_source.setdefault(alarm.source, []).append(alarm)

    for source, source_alarms in by_source.items():
        measurement = _SOURCE_MEASUREMENT.get(source, source)
        fields = list({a.metric_field for a in source_alarms})
        vals = query_influx(measurement, fields)
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
    """Config-driven thresholds for RAN + Core."""
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
        vals = query_influx(measurement, fields)
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


def evaluate_os_thresholds():
    """Config-driven thresholds for OS/infra."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config

    cfg = load_config()
    alarms = [a for a in cfg.alarms if a.source == "os"]
    if not alarms:
        return evaluate_os_thresholds_legacy()

    alerts = []
    fields = list({a.metric_field for a in alarms})
    vals = query_influx("os_metrics", fields)
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


# ── Legacy hardcoded thresholds (fallback when config has no alarms) ──


def evaluate_ran_thresholds_legacy():
    """Legacy hardcoded RAN + Core thresholds."""
    alerts = []
    ran_fields = [
        "cells_0_ue_list_0_dl_brate", "cells_0_ue_list_0_cqi",
        "du_du_high_mac_dl_0_cpu_usage_percent", "du_du_high_mac_dl_0_max_latency_us",
        "cells_0_cell_metrics_late_dl_harqs", "cells_0_cell_metrics_error_indication_count",
    ]
    core_fields = [
        "amf_gnb_connected", "upf_pfcp_active", "core_nf_health_pct",
        "alarm_amf_reject", "alarm_upf_heartbeat_lost", "alarm_scp_timeout",
        "amf_fivegs_amffunction_rm_reginitfail", "amf_fivegs_amffunction_amf_authreject",
        "smf_fivegs_smffunction_sm_n4sessionestabfail", "smf_gtp_peers_active",
        "upf_fivegs_ep_n3_gtp_indatapktn3upf", "amf_gnb", "smf_ues_active",
    ]
    ran = query_influx("srsran", ran_fields)
    core = query_influx("core_network", core_fields)
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
    # Need alarm_ref for severity/impact — import lazily
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import _alarm_ref
    except ImportError:
        _alarm_ref = {}

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


def evaluate_os_thresholds_legacy():
    """Legacy hardcoded OS thresholds."""
    alerts = []
    os_fields = [
        "node_pressure_memory_stalled_seconds_total", "node_memory_HugePages_Free",
        "node_cpu_steal_percent", "ptp_offset_ns",
    ]
    vals = query_influx("os_metrics", os_fields)
    rules = [
        ("memory_pressure", "node_pressure_memory_stalled_seconds_total", "gt", 10),
        ("hugepage_exhaustion", "node_memory_HugePages_Free", "eq", 0),
        ("high_cpu_steal", "node_cpu_steal_percent", "gt", 5),
        ("ptp_offset_drift", "ptp_offset_ns", "gt", 1500),
    ]
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import _alarm_ref
    except ImportError:
        _alarm_ref = {}

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
