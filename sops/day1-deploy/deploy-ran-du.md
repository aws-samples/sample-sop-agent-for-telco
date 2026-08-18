# Deploy RAN DU (srsRAN gNB)

**Duration:** ~10 minutes
**Target:** Edge/bare-metal worker node with RT kernel

## Overview
Deploy srsRAN Project gNB as a combined CU/DU on an edge worker node. Uses hostNetwork for fronthaul connectivity and testmode for UE emulation at the MAC layer.

## Prerequisites
- RT kernel configured (see `day0-infra/configure-rt-kernel.md`)
- Hugepages allocated (see `day0-infra/configure-hugepages.md`)
- Edge node labeled `role=edge`
- 5G Core deployed with AMF reachable

## Steps

### Step 1: Create gNB ConfigMap
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: srsran-gnb-config
  namespace: ran
data:
  gnb.yml: |
    gnb_id: 1
    gnb_id_bit_length: 32
    ran_node_name: srsgnb01
    amf:
      addr: AMF_SERVICE_IP
      bind_addr: 0.0.0.0
    ru_dummy:
      dl_arfcn: 632628
      band: 78
      channel_bandwidth_MHz: 20
      nof_antennas_dl: 1
      nof_antennas_ul: 1
    cell_cfg:
      pci: 1
      plmn: "99970"
      tac: 1
      nof_antennas_dl: 1
      nof_antennas_ul: 1
    test_mode:
      test_ue:
        rnti: 0x44
        nof_ues: 1
        pdsch_active: true
        pusch_active: true
        cqi: 15
        ri: 1
    remote_control:
      enabled: true
      bind_addr: 0.0.0.0
      port: 55555
    metrics:
      enable_json_metrics: true
      addr: 0.0.0.0
      port: 55555
EOF
```
**Expected**: `configmap/srsran-gnb-config created`

### Step 2: Deploy gNB pod
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: srsran-gnb
  namespace: ran
  labels:
    app: srsran-gnb
spec:
  hostNetwork: true
  nodeSelector:
    role: edge
    node-role: du
  containers:
  - name: gnb
    image: softwareradiosystems/srsran-project:release_avx2-25.10
    command: ["gnb"]
    args: ["-c", "/config/gnb.yml"]
    securityContext:
      privileged: true
    volumeMounts:
    - name: config
      mountPath: /config
  volumes:
  - name: config
    configMap:
      name: srsran-gnb-config
EOF
```
**Expected**: `pod/srsran-gnb created`

### Step 3: Verify gNB started and connected to AMF
```bash
kubectl logs srsran-gnb -n ran --tail=20 | grep -E "RRC|AMF|Cell"
```
**Expected**: Cell started, connected to AMF

### Step 4: Verify testmode metrics flowing
```bash
kubectl logs srsran-gnb -n ran --tail=5 | grep -E "DL|UL|brate"
```
**Expected**: DL/UL throughput values (e.g., 66 Mbps DL)

## Verification

### Final Check
```bash
kubectl get pod srsran-gnb -n ran -o wide
```
**Expected**: Running on edge node with hostNetwork

## Related SOPs
- **Previous:** `day1-deploy/deploy-upf.md`
- **Next:** `day1-deploy/deploy-monitoring-stack.md`
- **Remediation:** `day2-remediate/ran/remediate-du-cpu-overload.md`
