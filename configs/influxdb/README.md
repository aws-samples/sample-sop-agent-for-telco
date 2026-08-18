# InfluxDB for ANRA

## Quick Start
```bash
helm repo add influxdata https://helm.influxdata.com/
helm install influxdb influxdata/influxdb2 -n anra --create-namespace -f values.yaml
```

## Or standalone StatefulSet
```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: influxdb
spec:
  replicas: 1
  serviceName: influxdb
  selector:
    matchLabels: { app: influxdb }
  template:
    metadata:
      labels: { app: influxdb }
    spec:
      containers:
        - name: influxdb
          image: influxdb:2.7
          ports: [{ containerPort: 8086 }]
          env:
            - { name: DOCKER_INFLUXDB_INIT_MODE, value: setup }
            - { name: DOCKER_INFLUXDB_INIT_USERNAME, value: admin }
            - { name: DOCKER_INFLUXDB_INIT_PASSWORD, value: adminadmin }
            - { name: DOCKER_INFLUXDB_INIT_ORG, value: srs }
            - { name: DOCKER_INFLUXDB_INIT_BUCKET, value: srsran }
            - { name: DOCKER_INFLUXDB_INIT_ADMIN_TOKEN, value: srsran-metrics-token }
---
apiVersion: v1
kind: Service
metadata:
  name: influxdb
spec:
  ports: [{ port: 8086, targetPort: 8086 }]
  selector: { app: influxdb }
EOF
```
