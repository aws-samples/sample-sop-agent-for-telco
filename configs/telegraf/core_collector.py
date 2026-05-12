#!/usr/bin/env python3
"""Core network metrics collector — scrapes Open5GS Prometheus + kubectl pod status."""
import json, subprocess, time

CORE_NS = "open5gs"
PROM_TARGETS = {
    "amf": "open5gs-amf-metrics.open5gs.svc.cluster.local:9090",
    "smf": "open5gs-smf-metrics.open5gs.svc.cluster.local:9090",
    "pcf": "open5gs-pcf-metrics.open5gs.svc.cluster.local:9090",
}


def run(args):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=10)
        return r.stdout
    except Exception:
        return ""


def scrape_prom(url):
    raw = run(["curl", "-s", f"http://{url}/metrics"])
    metrics = {}
    for line in raw.strip().split("\n"):
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                metrics[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return metrics


while True:
    m = {}

    # Scrape Prometheus from AMF, SMF, PCF
    for nf, target in PROM_TARGETS.items():
        for k, v in scrape_prom(target).items():
            if not k.startswith("process_"):
                m[f"{nf}_{k}"] = v

    # kubectl pod status (always)
    out = run(["/usr/local/bin/kubectl", "get", "pods", "-n", CORE_NS, "--no-headers"])
    lines = [l for l in out.strip().split("\n") if l]
    running = sum(1 for l in lines if "Running" in l)
    # Count desired replicas from deployments (catches scale-to-zero)
    dep_out = run(["/usr/local/bin/kubectl", "get", "deploy", "-n", CORE_NS, "-o", "jsonpath={range .items[*]}{.spec.replicas} {.status.readyReplicas}{\"\\n\"}{end}"])
    desired = 0
    ready = 0
    for dl in dep_out.strip().split("\n"):
        parts = dl.split()
        if parts:
            desired += int(parts[0] or 0)
            ready += int(parts[1]) if len(parts) > 1 and parts[1] else 0
    total = max(desired, len(lines))
    m["core_nf_total"] = total
    m["core_nf_running"] = ready
    m["core_nf_failed"] = total - ready
    m["core_nf_health_pct"] = round(ready / max(total, 1) * 100, 1)

    print(json.dumps(m), flush=True)
    time.sleep(15)
