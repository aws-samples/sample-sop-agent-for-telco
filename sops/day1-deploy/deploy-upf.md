# Deploy UPF on Edge Node

**Duration:** ~5 minutes
**Target:** Edge/bare-metal worker node with hostNetwork

## Overview
Deploy Open5GS UPF on an edge worker node using hostNetwork for PFCP and GTP-U connectivity. The UPF handles user plane traffic and must be reachable from the SMF (control plane) via the node's IP address — not via Kubernetes service DNS.

## Prerequisites
- 5G Core deployed (see `day1-deploy/deploy-5g-core.md`)
- Edge node labeled `role=edge`
- SSH access to edge node

## Steps

### Step 1: Create ogstun interface on edge node BEFORE deploying UPF
```bash
ssh WORKER_NODE "sudo ip tuntap add name ogstun mode tun && sudo ip addr add 10.45.0.1/16 dev ogstun && sudo ip link set ogstun up"
```
**Expected**: No error output. Verify with `ip addr show ogstun`.

> **Critical:** The ogstun interface MUST exist before the UPF pod starts. If the UPF starts without ogstun, it will fail silently and PDU sessions won't work.

### Step 2: Get the edge node's host IP
```bash
NODE_IP=$(kubectl get node EDGE_NODE_NAME -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')
echo "UPF will bind to: $NODE_IP"
```
**Expected**: Edge node IP (e.g., `192.168.31.195`)

### Step 3: Create UPF config with hostNetwork IP
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: open5gs-upf-host-config
  namespace: open5gs
data:
  upf.yaml: |
    upf:
      pfcp:
        server:
          - address: ${NODE_IP}
      gtpu:
        server:
          - address: ${NODE_IP}
      session:
        - subnet: 10.45.0.0/16
    logger:
      level: info
EOF
```
**Expected**: `configmap/open5gs-upf-host-config created`

### Step 4: Update SMF config to point to UPF's host IP
```bash
kubectl get configmap open5gs-smf -n open5gs -o yaml | \
  sed "s|upf:.*|upf:\n        - address: ${NODE_IP}|" | \
  kubectl apply -f -
kubectl rollout restart deployment -l app.kubernetes.io/name=smf -n open5gs
```
**Expected**: SMF restarted with UPF address pointing to edge node IP

> **Critical:** The SMF must use the UPF's hostNetwork IP (e.g., `192.168.31.195`), NOT the Kubernetes service name. Service DNS resolves to a Cilium/VPC CNI pod IP which may not be routable from the SMF on EC2 nodes.

### Step 5: Deploy UPF with hostNetwork
```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: open5gs-upf-host
  namespace: open5gs
  labels:
    app: open5gs-upf-host
spec:
  replicas: 1
  selector:
    matchLabels:
      app: open5gs-upf-host
  template:
    metadata:
      labels:
        app: open5gs-upf-host
    spec:
      hostNetwork: true
      nodeSelector:
        role: edge
      containers:
      - name: upf
        image: gradiant/open5gs:2.7.7
        command: ["open5gs-upfd"]
        args: ["-c", "/config/upf.yaml"]
        securityContext:
          privileged: true
        volumeMounts:
        - name: config
          mountPath: /config
      volumes:
      - name: config
        configMap:
          name: open5gs-upf-host-config
EOF
```
**Expected**: `deployment.apps/open5gs-upf-host created`

### Step 6: Verify PFCP association between SMF and UPF
```bash
kubectl logs -l app.kubernetes.io/name=smf -n open5gs | grep "PFCP associated"
```
**Expected**: `PFCP associated [NODE_IP]:8805`

## Verification

### Final Check
```bash
echo "=== UPF Pod ==="
kubectl get pod -l app=open5gs-upf-host -n open5gs -o wide
echo "=== PFCP ==="
kubectl logs -l app.kubernetes.io/name=smf -n open5gs | grep "PFCP" | tail -3
```
**Expected**: UPF Running on edge node, PFCP associated

## Known Issues

### Hybrid networking: EC2 ↔ Edge pod IPs not routable
On EKS Hybrid, EC2 nodes use VPC CNI (10.100.x.x) and edge nodes use Cilium (172.16.x.x). Pod-to-pod traffic across these CNIs may not work due to VPN routing limitations. **This is why the UPF uses hostNetwork** — the edge node's host IP (192.168.31.x) IS routable from EC2 via the S2S VPN.

### ogstun not persisted across reboots
The `ip tuntap add` command is not persistent. Add to `/etc/rc.local` or a systemd unit:
```bash
ssh WORKER_NODE "echo 'ip tuntap add name ogstun mode tun; ip addr add 10.45.0.1/16 dev ogstun; ip link set ogstun up' | sudo tee /etc/rc.local && sudo chmod +x /etc/rc.local"
```

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| PFCP not associating | SMF using service name instead of host IP? | Update SMF config with `NODE_IP` |
| UPF pod CrashLoop | ogstun exists on host? | Create ogstun BEFORE deploying UPF |
| PDU sessions fail | UPF logs show `User Traffic Buffered`? | Check ogstun interface, verify NAT/routing |
| SMF can't reach UPF | Network path EC2→Edge? | Verify VPN tunnel, check route tables |

## Related SOPs
- **Previous:** `day1-deploy/deploy-5g-core.md`
- **Next:** `day1-deploy/deploy-ran-du.md`
- **Remediation:** `day2-remediate/core/remediate-upf-pfcp-loss.md`
