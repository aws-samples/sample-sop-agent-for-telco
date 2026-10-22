# Deploy Monitoring Stack (Telegraf → InfluxDB → Grafana)

**Duration:** ~10 minutes
**Target:** EKS cluster

## Overview
Deploy the metrics pipeline for real-time RAN and core network KPI monitoring. The key insight: srsRAN gNB exposes metrics via WebSocket (not UDP), requiring a specific adapter script.

## Prerequisites
- gNB deployed and running (see `day1-deploy/deploy-ran-du.md`)
- 5G Core deployed (see `day1-deploy/deploy-5g-core.md`)

## Steps

### Step 1: Deploy InfluxDB
```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: influxdb
  namespace: monitoring
spec:
  serviceName: influxdb
  replicas: 1
  selector:
    matchLabels:
      app: influxdb
  template:
    metadata:
      labels:
        app: influxdb
    spec:
      nodeSelector:
        role: region
      containers:
      - name: influxdb
        image: influxdb:2.7
        env:
        - name: DOCKER_INFLUXDB_INIT_MODE
          value: setup
        - name: DOCKER_INFLUXDB_INIT_USERNAME
          value: admin
        - name: DOCKER_INFLUXDB_INIT_PASSWORD
          value: adminpassword
        - name: DOCKER_INFLUXDB_INIT_ORG
          value: telco
        - name: DOCKER_INFLUXDB_INIT_BUCKET
          value: metrics
        - name: DOCKER_INFLUXDB_INIT_ADMIN_TOKEN
          value: metrics-token
        ports:
        - containerPort: 8086
---
apiVersion: v1
kind: Service
metadata:
  name: influxdb
  namespace: monitoring
spec:
  selector:
    app: influxdb
  ports:
  - port: 8086
EOF
```
**Expected**: InfluxDB StatefulSet and Service created

### Step 2: Deploy Telegraf with WebSocket adapter for gNB metrics

> **Critical:** srsRAN Project gNB (2024+) exposes metrics via WebSocket on the remote_control port (55555), NOT via UDP. The srsRAN Helm chart's metrics-server (UDP) is incompatible. You must use the `ws_adapter.py` script from the srsRAN source tree (`docker/telegraf/ws_adapter.py`).

The adapter:
1. Connects to `ws://GNB_HOST:55555`
2. Sends `{"cmd": "metrics_subscribe"}`
3. Receives JSON metric pushes every second
4. Pipes them to stdout for Telegraf's `execd` input plugin

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: telegraf-config
  namespace: monitoring
data:
  ws_adapter.py: |
    #!/usr/bin/env python3
    import websocket, json, sys
    ws = websocket.create_connection("ws://GNB_HOST:55555")
    ws.send(json.dumps({"cmd": "metrics_subscribe"}))
    while True:
        msg = ws.recv()
        try:
            data = json.loads(msg)
            print(json.dumps(data), flush=True)
        except:
            pass
  telegraf.conf: |
    [agent]
      interval = "1s"
      flush_interval = "1s"
    [[inputs.execd]]
      command = ["python3", "/etc/telegraf/ws_adapter.py"]
      signal = "none"
      data_format = "json"
      name_override = "srsran"
    [[outputs.influxdb_v2]]
      urls = ["http://influxdb.monitoring.svc.cluster.local:8086"]
      token = "metrics-token"
      organization = "telco"
      bucket = "metrics"
EOF
```
**Expected**: ConfigMap created

> **Note:** The base `telegraf:1.35` image does NOT have python3 or websocket-client. Use a custom image or the srsRAN Docker image which includes both. Build with:
> ```dockerfile
> FROM telegraf:1.35
> RUN apt-get update && apt-get install -y python3 python3-pip && pip3 install websocket-client
> ```

### Step 3: Deploy Telegraf
```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: telegraf
  namespace: monitoring
spec:
  replicas: 1
  selector:
    matchLabels:
      app: telegraf
  template:
    metadata:
      labels:
        app: telegraf
    spec:
      hostNetwork: true
      nodeSelector:
        node-role: du
      containers:
      - name: telegraf
        image: CUSTOM_TELEGRAF_IMAGE
        args: ["--config", "/etc/telegraf/telegraf.conf"]
        volumeMounts:
        - name: config
          mountPath: /etc/telegraf/
      volumes:
      - name: config
        configMap:
          name: telegraf-config
EOF
```
**Expected**: Telegraf pod running on same node as gNB

> **Note:** Telegraf must run on the same node as the gNB (or have network access to port 55555) because the WebSocket connection is to `localhost:55555` when using hostNetwork.

### Step 4: Deploy Grafana
```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
  namespace: monitoring
spec:
  replicas: 1
  selector:
    matchLabels:
      app: grafana
  template:
    metadata:
      labels:
        app: grafana
    spec:
      nodeSelector:
        role: region
      containers:
      - name: grafana
        image: grafana/grafana:11.6.0
        env:
        - name: GF_AUTH_ANONYMOUS_ENABLED
          value: "true"
        - name: GF_AUTH_ANONYMOUS_ORG_ROLE
          value: Viewer
        ports:
        - containerPort: 3000
---
apiVersion: v1
kind: Service
metadata:
  name: grafana
  namespace: monitoring
spec:
  type: NodePort
  selector:
    app: grafana
  ports:
  - port: 3000
    nodePort: 30300
EOF
```
**Expected**: Grafana accessible on NodePort 30300

### Step 5: Verify metrics flowing
```bash
sleep 30
kubectl exec influxdb-0 -n monitoring -- influx query \
  'from(bucket:"metrics") |> range(start:-30s) |> filter(fn:(r) => r._measurement == "srsran") |> count()' \
  --org telco --token metrics-token
```
**Expected**: Non-zero count — metrics are flowing from gNB → Telegraf → InfluxDB

## Available Metrics (55 fields at 1-second resolution)

### Cell-level
- `average_latency`, `max_latency` — scheduling latency
- `late_dl_harqs`, `late_ul_harqs` — HARQ deadline misses
- `error_indication_count` — protocol errors
- `pdsch_prbs_used_per_tdd_slot_idx` — PRB utilization

### UE-level
- `dl_brate`, `ul_brate` — throughput (bps)
- `cqi`, `dl_mcs`, `dl_ri` — channel quality
- `dl_nof_ok`, `dl_nof_nok` — HARQ success/failure
- `pusch_rsrp_db`, `pusch_snr_db` — signal quality
- `bsr` — buffer status

### DU MAC
- `cpu_usage_percent` — DU processing load
- `average_latency_us`, `max_latency_us` — MAC scheduling latency

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| No metrics in InfluxDB | Telegraf logs | Check WebSocket connection to gNB |
| `websocket` module not found | Telegraf image | Use custom image with python3 + websocket-client |
| Connection refused on :55555 | gNB config has remote_control? | Add `remote_control: enabled: true, port: 55555` |
| Metrics stop after gNB restart | WebSocket disconnected | Restart Telegraf pod |

## Related SOPs
- **Previous:** `day1-deploy/deploy-ran-du.md`
- **Next:** `day1-deploy/validate-e2e.md`
