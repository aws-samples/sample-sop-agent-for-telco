# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Kubernetes pod-failure detection for ANRA.

Two sources for the same signal (pod crash / OOM / scheduling failure):

* ``poll_cloudwatch_k8s_events`` queries CloudWatch Container Insights logs
  (the primary path when Container Insights is enabled on the cluster).
* ``poll_k8s_pod_health`` is a kubectl fallback for clusters without
  Container Insights.

The run loop calls both and unions the results.
"""

import logging
import time

from amzn_cse_telco_autonomous_network_agents_app.agent.util.aws import aws_session

log = logging.getLogger(__name__)

CW_POLL_INTERVAL = 60  # seconds
# Ordered most-specific first: reason matching is a substring test, and
# "CrashLoopBackOff" contains "BackOff", so the longer token must be tried
# first or a CrashLoopBackOff event would mis-match "BackOff" and be downgraded
# from critical to warning. A tuple (not a set) makes that order deterministic.
CW_ALARM_REASONS = ("UnexpectedAdmissionError", "CrashLoopBackOff", "OOMKilled", "FailedScheduling", "BackOff")

_cw_last_poll: float = 0
_cw_seen: dict = {}  # dedup key -> timestamp


def poll_cloudwatch_k8s_events():
    """Query CloudWatch Container Insights for K8s Warning events."""
    global _cw_last_poll
    now = time.time()
    if now - _cw_last_poll < CW_POLL_INTERVAL:
        return []
    _cw_last_poll = now

    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config

        cfg = load_config()
        session = aws_session(cfg.bedrock_profile, cfg.cluster_region)
        client = session.client("logs")
        log_group = f"/aws/containerinsights/{cfg.cluster_name}/performance"

        # Also check application log group for pod events
        app_log_group = f"/aws/containerinsights/{cfg.cluster_name}/application"

        # Get watched namespaces from node config
        watched_ns = set()
        for n in cfg.nodes:
            watched_ns.update(n.namespaces)
        if not watched_ns:
            watched_ns = {"srsran", "open5gs"}

        alerts = []
        for lg in [log_group, app_log_group]:
            try:
                resp = client.start_query(
                    logGroupName=lg,
                    startTime=int((now - 120) * 1000),  # last 2 min
                    endTime=int(now * 1000),
                    queryString=(
                        "fields @timestamp, kubernetes.namespace_name as ns, kubernetes.pod_name as pod, "
                        "message | filter @message like /UnexpectedAdmissionError|CrashLoopBackOff|OOMKilled|FailedScheduling|BackOff/ "
                        "| sort @timestamp desc | limit 20"
                    ),
                )
                query_id = resp["queryId"]
                # Wait for query
                for _ in range(5):
                    time.sleep(1)
                    result = client.get_query_results(queryId=query_id)
                    if result["status"] == "Complete":
                        break

                for row in result.get("results", []):
                    fields = {f["field"]: f["value"] for f in row}
                    ns = fields.get("ns", "")
                    pod = fields.get("pod", "")
                    msg = fields.get("message", "")[:200]

                    if ns not in watched_ns:
                        continue

                    # Match reason
                    reason = next((r for r in CW_ALARM_REASONS if r.lower() in msg.lower()), None)
                    if not reason:
                        continue

                    # Dedup
                    key = f"{ns}/{reason}/{pod}"
                    if key in _cw_seen and now - _cw_seen[key] < 300:
                        continue
                    _cw_seen[key] = now

                    alerts.append({
                        "name": f"k8s_{reason.lower()}",
                        "severity": "critical" if reason in {"CrashLoopBackOff", "OOMKilled", "UnexpectedAdmissionError"} else "warning",
                        "source": "cloudwatch-k8s",
                        "service_impact": f"Pod {pod} in {ns}: {reason}",
                        "probable_cause": msg,
                        "sop": "",
                    })
                    log.info(f"CW K8S ALARM: {reason} on {pod} in {ns}")
            except client.exceptions.ResourceNotFoundException:
                continue
            except Exception as e:
                log.debug(f"CloudWatch query error for {lg}: {e}")

        # Clean old dedup entries
        for k in list(_cw_seen):
            if now - _cw_seen[k] > 300:
                del _cw_seen[k]

        return alerts
    except Exception as e:
        log.debug(f"CloudWatch K8s event poll skipped: {e}")
        return []


def poll_k8s_pod_health():
    """Fallback pod health check via kubectl -- detects CrashLoopBackOff, OOMKilled.

    Used when CloudWatch Container Insights is not available.
    """
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config
        from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

        cfg = load_config()

        watched_ns = set()
        for n in cfg.nodes:
            watched_ns.update(getattr(n, "namespaces", []))
        if not watched_ns:
            watched_ns = {"srsran", "open5gs"}

        alerts = []
        for ns in watched_ns:
            result = run_cmd(
                f"kubectl get pods -n {ns} --no-headers "
                f"-o custom-columns=NAME:.metadata.name,STATUS:.status.phase,RESTARTS:.status.containerStatuses[0].restartCount,REASON:.status.containerStatuses[0].state.waiting.reason",
                timeout=10,
            )
            if not result.success:
                continue
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) < 4:
                    continue
                pod_name, _phase, restarts, reason = parts[0], parts[1], parts[2], parts[3]
                if reason in ("CrashLoopBackOff", "OOMKilled", "Error", "ImagePullBackOff"):
                    alerts.append({
                        "name": "nf_crashloop",
                        "severity": "critical" if reason == "CrashLoopBackOff" else "major",
                        "source": "k8s-pod-health",
                        "value": int(restarts) if restarts.isdigit() else 0,
                        "threshold": "reason=" + reason,
                        "service_impact": f"Pod {pod_name} in {ns} is {reason} (restarts: {restarts})",
                        "probable_cause": f"Pod {pod_name} failing to start: {reason}",
                        "node_name": "",
                        "nf_instance": pod_name,
                    })
        return alerts
    except Exception as e:
        log.debug(f"K8s pod health check failed: {e}")
        return []
