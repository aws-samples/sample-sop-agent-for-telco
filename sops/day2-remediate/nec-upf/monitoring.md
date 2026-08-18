# UPF Metrics & Monitoring SOP

**Status:** ✅ DEPLOYED  
**Stage:** 6 of 8  
**Last Updated:** 2026-02-17  
**Severity:** warning  
**Trigger:** upf_metrics_missing, exporter_down

---

## Description
Real-time performance monitoring for NEC 5G UPF using Prometheus and Grafana. This SOP covers:
- Built-in UPF metrics exporter configuration (throughput, sessions, packets)
- Bastion exporter for DPDK fast path CPU metrics
- Prometheus scraping setup
- Grafana dashboard access and usage
- UPF alarm rules (NEC alarm spec compliant)
- Key performance indicators (KPIs)

---

## Architecture

```
UPF Pod (aws-upf namespace)
  ├── DPDK Fast Path (32 workers, cores 12-27 + 108-123)
  │   └── Writes stats to shared memory/API
  │
  ├── kpi_collector (UTR)
  │   ├── Reads stats every 60s
  │   ├── Aggregates metrics (UL+DL, per-interface)
  │   └── Writes to /var/log/software/exporter/
  │
  └── Built-in Exporter (port 2112)
      └── Exposes 300+ Prometheus metrics
          (throughput, sessions, packets, events)
          NOTE: Does NOT expose DPDK fast path CPU

                    ↓

Service: upf-builtin-exporter (ClusterIP:2112)
                    ↓
ServiceMonitor (60s interval, 10s timeout)
                    ↓
Prometheus (monitoring namespace)  ←── ServiceMonitor (60s interval)
                    ↑                          ↑
                    │                          │
                    │              Bastion Exporter (100.77.0.105:9100)
                    │                ├── Runs fp-cpu-usage via kubectl exec
                    │                ├── Runs stats-port via fpdebug
                    │                ├── Exposes upf_cpu_usage_percent (per-worker)
                    │                └── systemd: upf-exporter.service
                    ↓
              Grafana Dashboard
                ├── "NEC UPF Performance - MWC 2026"
                └── Alertmanager → 🚨 UPF Alarms panel

PrometheusRule: upf-alarms (12 alert rules, NEC alarm spec)
                    ↓
              Alertmanager (monitoring namespace)
```

---

## Prerequisites
- UPF deployed and running (Stage 3 complete)
- Prometheus Operator installed (kube-prometheus-stack)
- Grafana accessible via LoadBalancer
- Bastion host (100.77.0.105) has kubectl access to EKS cluster

---

## Steps

### 1. Verify Built-in Exporter

Check that the UPF's built-in exporter is running:

```bash
SVC=$(kubectl get pod -n aws-upf -l app=upf-service-01 -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n aws-upf $SVC -- curl -s localhost:2112/metrics | head -20
```

**Expected:** Prometheus-formatted metrics including:
- `system_upf_uldl_throughput_send_rate`
- `system_upf_uldl_throughput_receive_rate`
- `pfcp_upf_current_pdu_session_count_total`
- `event_upf_*` counters

### 2. Verify Service and ServiceMonitor

**If missing (e.g., after teardown), recreate:**
```bash
kubectl apply -f configs/upf-builtin-exporter.yaml
```

**Verify:**
# Check service
kubectl get svc -n aws-upf upf-builtin-exporter

# Check ServiceMonitor
kubectl get servicemonitor -n aws-upf upf-builtin-exporter -o yaml
```

**Expected Service:**
```yaml
spec:
  ports:
  - name: metrics
    port: 2112
    targetPort: 2112
  selector:
    app: upf-service-01
```

**Expected ServiceMonitor:**
```yaml
spec:
  endpoints:
  - interval: 60s
    port: metrics
    scrapeTimeout: 10s
  selector:
    matchLabels:
      app: upf-exporter
  namespaceSelector:
    matchNames:
    - aws-upf
metadata:
  labels:
    release: kube-prometheus-stack
  namespace: aws-upf
```

### 3. Verify Bastion Exporter (DPDK CPU Metrics)

The built-in exporter does not expose DPDK fast path per-worker CPU. A bastion exporter
runs on 100.77.0.105:9100 and collects this via `fp-cpu-usage` and `fpdebug` CLI commands.

**Check service status (run locally on bastion):**
```bash
sudo systemctl status upf-exporter
```

**Expected:** `active (running)`

**If not running, start it (run locally on bastion):**
```bash
sudo systemctl start upf-exporter
sudo systemctl enable upf-exporter  # ensure starts on boot
```

**If service unit missing (e.g., after OS rebuild), reinstall:**
```bash
sudo cp configs/upf-exporter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable upf-exporter
sudo systemctl start upf-exporter
```

**Verify metrics (run locally on bastion):**
```bash
curl -s http://localhost:9100/metrics | grep upf_cpu_usage_percent | head -5
```

**Expected:** 32 workers with CPU percentages:
```
upf_cpu_usage_percent{cpu="12"} 64
upf_cpu_usage_percent{cpu="13"} 65
...
```

**Verify Prometheus target:**
```bash
kubectl port-forward -n monitoring prometheus-kube-prometheus-stack-prometheus-0 9090:9090 &
curl -s "http://localhost:9090/api/v1/targets" | \
  jq -r '.data.activeTargets[] | select(.labels.job == "upf-exporter") | {health: .health, lastScrapeDuration: .lastScrapeDuration}'
```

**Expected:** health=up, scrape duration ~12s

**Kubernetes resources:**
- Service: `upf-exporter` (monitoring namespace, headless, Endpoints → 100.77.0.105:9100)
- ServiceMonitor: `upf-exporter` (60s interval, 50s timeout)
- Systemd: `upf-exporter.service` on bastion
- Script: `/home/ec2-user/nec-mwc-2026/upf-exporter/exporter.py`

**Metrics provided (not available from built-in exporter):**
| Metric | Description |
|--------|-------------|
| `upf_cpu_usage_percent{cpu="N"}` | DPDK fast path per-worker CPU % (32 workers) |
| `upf_port_ipackets{port="N"}` | NIC port RX packet count |
| `upf_port_opackets{port="N"}` | NIC port TX packet count |
| `upf_port_imissed{port="N"}` | NIC port missed/dropped packets |
| `upf_throughput_recvpackets_ipv4` | Total received IPv4 packets |
| `upf_throughput_recvbytes_ipv4` | Total received IPv4 bytes |

### 4. Verify Prometheus Scraping

```bash
# Port-forward Prometheus
kubectl port-forward -n monitoring prometheus-kube-prometheus-stack-prometheus-0 9090:9090 &

# Check target health
curl -s "http://localhost:9090/api/v1/targets" | \
  jq -r '.data.activeTargets[] | select(.labels.job == "upf-builtin-exporter") | {health: .health, lastScrape: .lastScrape}'

# Test query
curl -s "http://localhost:9090/api/v1/query?query=system_upf_uldl_throughput_send_rate" | \
  jq -r '.data.result[0].value[1]' | awk '{printf "%.2f Gbps\n", $1/1e9}'
```

**Expected:**
- Health: `up`
- Throughput value: `> 0`

### 5. Access Grafana Dashboard

```bash
# Get Grafana URL
kubectl get svc -n monitoring kube-prometheus-stack-grafana -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

**Dashboard Details:**
- **Name:** NEC UPF Performance - MWC 2026
- **UID:** `3a2bdcf1-8e2f-4270-b92a-e609c510dbfd`
- **Credentials:** admin / admin123
- **Refresh:** 5 seconds

**Direct URL:**
```
http://<grafana-lb>/d/3a2bdcf1-8e2f-4270-b92a-e609c510dbfd/nec-upf-performance-mwc-2026
```

---

## Dashboard Panels

### 📊 Combined Throughput (UL+DL)
- **Metric:** `system_upf_uldl_throughput_receive_rate` / `send_rate`
- **Unit:** Gbps
- **Scale:** 0-150 Gbps
- **Type:** Time-series with gradient fill

### 📦 Packet Rate (UL+DL)
- **Calculation:** `throughput / (avg_packet_length * 8) / 1e6`
- **Unit:** Mpps (Million packets per second)
- **Scale:** 0-15 Mpps
- **Type:** Time-series

### ⚙️ CPU Usage per Worker
- **Metric:** `upf_cpu_usage_percent` (from bastion exporter, NOT built-in)
- **Source:** Bastion exporter → `fp-cpu-usage` CLI → DPDK fast path stats
- **Workers:** 32 cores (12-27 + 108-123)
- **Unit:** Percent
- **Thresholds:** Green <70%, Yellow <90%, Red ≥90%
- **Type:** Horizontal bar gauge

### 📈 Performance Summary
- **Metrics:**
  - RX/TX Throughput (Gbps)
  - RX/TX Packet Rate (Mpps)
  - Average/Max CPU (%)
- **Type:** Stat panel with background color

### 👥 Active UE Sessions
- **Metrics:**
  - `pfcp_upf_current_pdu_session_count_total` (Total)
  - `pfcp_upf_current_pdu_session_ipv4_count_total` (IPv4)
  - `pfcp_upf_current_pdu_session_ipv6_count_total` (IPv6)
- **Type:** Stat panel with area graph

### ⚠️ Packet Drops
- **Metrics:**
  - `rate(system_upf_uldl_packet_drop_count_total[1m])`
  - `system_upf_uldl_packet_drop_count_rate`
- **Type:** Time-series

### 🔴 Worker Overload Events
- **Metric:** `event_upf_send_rx_to_worker_ng_packet_count_total`
- **Thresholds:** Green=0, Red>0
- **Type:** Stat panel

### 🚨 UPF Alarms
- **Source:** Alertmanager alert list
- **Filter:** `objectClass=UPF`
- **Shows:** Firing and pending UPF alarms in real-time
- **Type:** Alert list panel

### 🔔 Alarm History (24h)
- **Metric:** `ALERTS{objectClass="UPF"}`
- **Columns:** Alarm name, State, Severity (color-coded)
- **Severity colors:** Red=Critical, Orange=Major, Yellow=Warning
- **Type:** Table panel

---

## Key Metrics Reference

### Throughput Metrics (Gauge, bps)
```
system_upf_uldl_throughput_send_rate       # Combined UL+DL TX
system_upf_uldl_throughput_receive_rate    # Combined UL+DL RX
```

### Packet Counters (Counter)
```
system_upf_uldl_packet_send_count_total    # Total packets sent
system_upf_uldl_packet_receive_count_total # Total packets received
system_upf_uldl_packet_drop_count_total    # Total packets dropped
```

### Session Metrics (Gauge)
```
pfcp_upf_current_pdu_session_count_total       # Total active sessions
pfcp_upf_current_pdu_session_ipv4_count_total  # IPv4 sessions
pfcp_upf_current_pdu_session_ipv6_count_total  # IPv6 sessions
```

### Interface-Specific Metrics
```
system_upf_n3_ul_packet_count_total    # N3 uplink packets
system_upf_n3_dl_packet_count_total    # N3 downlink packets
system_upf_n6_ul_packet_count_total    # N6 uplink packets
system_upf_n6_dl_packet_count_total    # N6 downlink packets
```

### Event Counters (Counter)
```
event_upf_send_rx_to_worker_ng_packet_count_total  # Worker overload
event_upf_receive_ipv4_no_session_count_total      # No session errors
event_upf_drop_packet_qos_rate_over_count_total    # QoS drops
```

### CPU Metrics (Gauge, %)
```
upf_cpu_usage_percent{cpu="12"}  # Per-worker DPDK fast path CPU (bastion exporter)
```
Note: `system_upf_cp_cpu_usage_average` and `system_upf_cp_cpu_usage_peak` from the
built-in exporter measure control plane CPU only (near 0% under normal operation).

---

## Typical Performance Values

Based on current deployment with 10,000 UE sessions:

| Metric | Value | Notes |
|--------|-------|-------|
| **Total Throughput** | ~193 Gbps | 97.5 Gbps RX + 95.1 Gbps TX |
| **Packet Rate** | ~21 Mpps | Combined UL+DL |
| **Active Sessions** | 10,000 | IPv4 PDU sessions |
| **CPU Usage** | 60-70% | Per worker (32 DPDK workers, cores 12-27 + 108-123) |
| **Packet Drops** | 0 | No overload |
| **Worker Overload** | 0 | All workers healthy |

---

## Rollback
If the exporter or ServiceMonitor changes break metric collection, the operator MUST revert:
```bash
kubectl delete servicemonitor upf-builtin-exporter -n aws-upf
kubectl rollout undo deployment/upf-management-00 -n aws-upf
```
**Expected**: Prometheus stops scraping the broken endpoint; the previous management pod revision is restored. Existing dashboards continue using cached time-series data.

## Troubleshooting

### No Metrics in Prometheus

**Check exporter is running:**
```bash
SVC=$(kubectl get pod -n aws-upf -l app=upf-service-01 -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n aws-upf $SVC -- ss -tlnp | grep 2112
```

**Check ServiceMonitor labels:**
```bash
kubectl get servicemonitor -n aws-upf upf-builtin-exporter -o jsonpath='{.metadata.labels}'
```
Must have: `release: kube-prometheus-stack`

**Check Prometheus targets:**
```bash
kubectl port-forward -n monitoring prometheus-kube-prometheus-stack-prometheus-0 9090:9090 &
curl -s "http://localhost:9090/api/v1/targets" | jq '.data.activeTargets[] | select(.labels.namespace == "aws-upf")'
```

### Dashboard Shows "No Data"

**Wait for scrapes:**
- Prometheus scrapes every 60s
- Need at least 2 scrapes for `rate()` calculations
- Wait 2-3 minutes after deployment

**Check metric availability:**
```bash
kubectl port-forward -n monitoring prometheus-kube-prometheus-stack-prometheus-0 9090:9090 &
curl -s "http://localhost:9090/api/v1/label/__name__/values" | jq -r '.data[]' | grep system_upf
```

### Packet Rate Shows Zero

Packet rate is calculated from throughput and packet length. Check:
```bash
# Verify throughput
curl -s "http://localhost:9090/api/v1/query?query=system_upf_uldl_throughput_send_rate"

# Verify packet length
curl -s "http://localhost:9090/api/v1/query?query=system_upf_n3_ul_packet_length"
```

If packet_length is 0, no traffic is flowing.

### High CPU Usage

If workers show >90% CPU:
1. Check for worker overload events
2. Verify traffic distribution (all 32 workers active)
3. Consider increasing CPU allocation in `upf/values.yaml`

### CPU Panel Shows "No Data"

The CPU panel uses `upf_cpu_usage_percent` from the bastion exporter, not the built-in exporter.

**Check bastion exporter:**
```bash
sudo systemctl status upf-exporter
curl -s http://localhost:9100/metrics | grep upf_cpu_usage_percent | wc -l
```

**If stopped, restart:**
```bash
sudo systemctl restart upf-exporter
```

**Check Prometheus target:**
```bash
kubectl port-forward -n monitoring prometheus-kube-prometheus-stack-prometheus-0 9090:9090 &
curl -s "http://localhost:9090/api/v1/targets" | \
  jq '.data.activeTargets[] | select(.labels.job == "upf-exporter") | {health, lastError}'
```

**If target missing, verify Kubernetes resources:**
```bash
kubectl get endpoints,svc,servicemonitor -n monitoring | grep upf-exporter
```

---

## Maintenance

### Update Dashboard

Dashboard is stored in Grafana database. To update:

1. Edit in Grafana UI (Settings → JSON Model)
2. Or use API:
```bash
GRAFANA_URL="http://admin:admin123@<grafana-lb>"
curl -X POST "${GRAFANA_URL}/api/dashboards/db" \
  -H "Content-Type: application/json" \
  -d @dashboard.json
```

### Export Dashboard

```bash
GRAFANA_URL="http://admin:admin123@<grafana-lb>"
curl -s "${GRAFANA_URL}/api/dashboards/uid/3a2bdcf1-8e2f-4270-b92a-e609c510dbfd" | \
  jq '.dashboard' > upf-dashboard-backup.json
```

### Adjust Scrape Interval

Edit ServiceMonitor:
```bash
kubectl edit servicemonitor upf-builtin-exporter -n aws-upf
```

Change `interval: 60s` to desired value (minimum 15s recommended).

---

## Success Criteria

- ✅ Built-in exporter responding on port 2112
- ✅ Bastion exporter running (`systemctl status upf-exporter`)
- ✅ ServiceMonitors configured with correct labels (upf-builtin-exporter + upf-exporter)
- ✅ Prometheus targets healthy: both `upf-builtin-exporter` and `upf-exporter` = `up`
- ✅ Grafana dashboard showing live data (all 9 panels)
- ✅ Throughput values > 0 Gbps
- ✅ CPU panel showing 32 workers with usage %
- ✅ Session count matches SMF simulator (10,000)
- ✅ UPF alarm rules loaded (12 rules across 5 groups)
- ✅ Alertmanager receiving UPF alerts

---

## UPF Alarm Rules

Prometheus-based alert rules aligned to the NEC UPF alarm specification (32 alarm types).

### Deploy Alarm Rules

```bash
kubectl apply -f configs/upf-alarms-prometheusrule.yaml
```

### Verify Rules Loaded

```bash
kubectl get prometheusrule -n monitoring upf-alarms
```

### Check Active UPF Alarms

```bash
kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093 &
sleep 3
curl -s "http://localhost:9093/api/v2/alerts" | \
  jq -r '.[] | select(.labels.objectClass == "UPF") | "[\(.status.state)] \(.labels.alertname) severity=\(.labels.severity)"'
```

### Alarm Mapping to NEC Spec

| Alert Name | NEC Alarm # | Severity | Trigger |
|------------|-------------|----------|---------|
| `server_fault` | #1 | Critical | UPF exporter unreachable |
| `gwu_blade_fault` | #3 | Major | UPF service container restart |
| `single_route_fault_per_gwu` | #6 | Major | N3 packet drops with active traffic |
| `dual_route_fault_per_gwu` | #8 | Critical | Zero throughput with active sessions |
| `pfcp_association_released` | #22 | Major | No PFCP heartbeat nodes |
| `pfcp_session_loss` | #22 | Major | >50% session drop in 5 minutes |
| `gwu_fault_information_worker_overload` | #17 | Warning | Worker overload events |
| `upf_packet_drop_rate_high` | #17 | Warning | Drop rate > 1000 pps |
| `upf_throughput_degradation` | #17 | Warning | <100 Gbps with >1000 sessions |
| `upf_cpu_overload` | #17 | Warning | CPU peak > 95% |
| `gwu_blade_inter_device_connection_fault` | #14 | Major | UPF pod not ready |
| `upf_all_pods_down` | #1 | Critical | All UPF pods down |

### Alarm Labels (NEC Spec Compliant)

All alerts include NEC-standard labels:
- `objectClass: UPF`
- `alarmType` — per TS 28.532 (EquipmentAlarm, ProcessingErrorAlarm, Communications Alarm)
- `probableCause` — per TS 32.111-2 Annex B
- `rootCauseIndicator: fs000`
- `receiver` — recoverable or nonrecoverable
- `firing_messageNo` / `resolved_messageNo` — NEC message numbers

### Note on Native UPF Alarms

The UPF management pod supports direct Alertmanager integration via `ENV_ALARM_MODE`.
Current setting: `EFK` (alarms go to logs). To enable direct Alertmanager delivery:

1. Edit `upf/values.yaml`:
```yaml
alarm:
  mode: "AlertManager"  # Change from "EFK"
```
2. Helm upgrade (requires management pod restart)
3. This enables all 32 native alarms including BGP peer events (#2--output truncated--
