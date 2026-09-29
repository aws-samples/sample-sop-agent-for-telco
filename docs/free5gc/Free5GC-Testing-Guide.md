# Free5GC 5G Core Network Testing Guide

## Prerequisites
- Free5GC deployed and running on EKS cluster
- PacketRusher UE simulator deployed
- Multus CNI configured for multi-network support
- kubectl access to the cluster

## Section 1: Pre-Test Verification

### 1.1 Verify Core Components
```bash
# Check all Free5GC components are running
kubectl get pods -n default | grep free5gc

# Expected: 11 pods in Running state
# - AMF, AUSF, MongoDB, NRF, NSSF, PCF, SMF, UDM, UDR, UPF, WebUI
```

### 1.2 Verify PacketRusher Status
```bash
# Check PacketRusher pod status
kubectl get pods -l app=packetrusher -n default

# Get PacketRusher pod name for testing
export PACKETRUSHER_POD=$(kubectl get pods -l app=packetrusher -o jsonpath='{.items[0].metadata.name}')
echo "PacketRusher Pod: $PACKETRUSHER_POD"
```

### 1.3 Verify Multi-Network Interfaces
```bash
# Check 5G network interfaces on PacketRusher
kubectl exec $PACKETRUSHER_POD -- ip addr show | grep -E "(n2|n3|val)"

# Expected interfaces:
# - n2: Control plane interface (N2 network)
# - n3: User plane interface (N3 network)
# - val0000000003: 5G data interface with UE IP
```

## Section 2: Core Functional Tests

### 2.1 5G Registration and Session Establishment Test
```bash
# Check if UE has been assigned a 5G IP address
kubectl exec $PACKETRUSHER_POD -- ip vrf exec vrf0000000003 ip addr show val0000000003

# Expected: UE IP in 10.63.0.x/32 range
# Status should be UP and LOWER_UP
```

### 2.2 5G Data Connectivity Test
```bash
# Test internet connectivity via 5G data path
kubectl exec $PACKETRUSHER_POD -- ip vrf exec vrf0000000003 ping -c 4 8.8.8.8

# Expected results:
# - 4 packets transmitted, 4 received
# - 0% packet loss
# - RTT: 5-15ms typical
```

### 2.3 DNS Resolution Test
```bash
# Test DNS resolution via 5G interface
kubectl exec $PACKETRUSHER_POD -- ip vrf exec vrf0000000003 nslookup google.com

# Expected: Successful DNS resolution
```

## Section 3: Performance Testing

### 3.1 Deploy Test Infrastructure
```bash
# Deploy iperf3 server for performance testing
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: iperf-server
  namespace: default
  labels:
    app: iperf-server
spec:
  containers:
  - name: iperf-server
    image: networkstatic/iperf3:latest
    command: ["iperf3", "-s", "-p", "5201"]
    ports:
    - containerPort: 5201
---
apiVersion: v1
kind: Service
metadata:
  name: iperf-server-svc
  namespace: default
spec:
  selector:
    app: iperf-server
  ports:
  - port: 5201
    targetPort: 5201
    nodePort: 30201
    protocol: TCP
  type: NodePort
EOF

# Wait for iperf server to be ready
kubectl wait --for=condition=ready pod -l app=iperf-server --timeout=60s
```

### 3.2 5G Throughput Test
```bash
# Get worker node IP for testing
export NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
echo "Testing against node IP: $NODE_IP"

# Run 5G performance test (10 second test with 2 second intervals)
kubectl exec $PACKETRUSHER_POD -- ip vrf exec vrf0000000003 iperf3 -c $NODE_IP -p 30201 -t 10 -i 2

# Expected performance baselines:
# - Throughput: 2-4 Gbps (depending on instance type)
# - Low retransmissions (<100)
# - Consistent performance across intervals
```

### 3.3 Extended Performance Test
```bash
# Run longer test for stability assessment
kubectl exec $PACKETRUSHER_POD -- ip vrf exec vrf0000000003 iperf3 -c $NODE_IP -p 30201 -t 60 -i 10

# Monitor for:
# - Sustained throughput over time
# - Stability of connection
# - Minimal retransmissions
```

## Section 4: Network Interface Validation

### 4.1 Multus Interface Verification
```bash
# Check all network interfaces on PacketRusher
kubectl exec $PACKETRUSHER_POD -- ip link show

# Verify interface statistics
kubectl exec $PACKETRUSHER_POD -- ip -s link show n2
kubectl exec $PACKETRUSHER_POD -- ip -s link show n3
```

### 4.2 UPF Interface Verification
```bash
# Get UPF pod name
export UPF_POD=$(kubectl get pods | grep upf | awk '{print $1}')
echo "UPF Pod: $UPF_POD"

# Check N6 interface on UPF (external data network interface)
kubectl exec $UPF_POD -- ip -s link show n6

# Expected: Interface UP with RX/TX statistics showing traffic
```

### 4.3 Route Table Verification
```bash
# Check 5G VRF routing table
kubectl exec $PACKETRUSHER_POD -- ip vrf exec vrf0000000003 ip route

# Expected: Default route via 5G tunnel interface
```

## Section 5: Advanced Diagnostics

### 5.1 5G Protocol Stack Verification
```bash
# Check GTP tunnel status (if available)
kubectl exec $PACKETRUSHER_POD -- ip tunnel show

# Check for GTP5G kernel module
kubectl exec $PACKETRUSHER_POD -- lsmod | grep gtp
```

### 5.2 Service Connectivity Tests
```bash
# Test connectivity to Free5GC services
kubectl exec $PACKETRUSHER_POD -- curl -s http://free5gc-nrf:8000/nnrf-nfm/v1/nf-instances

# Test AMF connectivity
kubectl exec $PACKETRUSHER_POD -- nc -zv free5gc-amf 8000
```

## Section 6: Performance Baselines and Expectations

### 6.1 Expected Performance Metrics
| Metric | Target | Excellent | Good | Needs Investigation |
|--------|--------|-----------|------|-------------------|
| Throughput | 2-4 Gbps | >3 Gbps | 1-3 Gbps | <1 Gbps |
| Latency | 5-10ms | <7ms | 7-15ms | >15ms |
| Packet Loss | <0.1% | 0% | <0.01% | >0.1% |
| Jitter | <2ms | <1ms | 1-3ms | >3ms |

### 6.2 Instance Type Considerations
- **m6i.4xlarge**: Expected 3-4 Gbps throughput
- **m6i.2xlarge**: Expected 2-3 Gbps throughput
- **m6i.xlarge**: Expected 1-2 Gbps throughput

## Section 7: Troubleshooting Guide

### 7.1 Common Issues and Solutions

#### No 5G Connectivity
```bash
# Check AMF logs
kubectl logs -f $(kubectl get pods | grep amf | awk '{print $1}')

# Check PacketRusher registration
kubectl logs -f $PACKETRUSHER_POD

# Verify network policies
kubectl get networkpolicies -A
```

#### Low Performance
```bash
# Verify instance types
kubectl get nodes -o wide

# Check resource utilization
kubectl top nodes
kubectl top pods

# Verify Multus configuration
kubectl get network-attachment-definitions -A
```

#### Connection Drops
```bash
# Check for pod restarts
kubectl get pods -o wide

# Monitor interface statistics
watch kubectl exec $PACKETRUSHER_POD -- ip -s link show val0000000003

# Check UPF logs
kubectl logs -f $UPF_POD
```

### 7.2 Health Check Script
```bash
#!/bin/bash
# 5G Health Check Script

echo "=== 5G Core Health Check ==="

# Check core components
echo "Checking Free5GC components..."
kubectl get pods | grep free5gc | grep -v Running && echo "WARNING: Some Free5GC pods not running"

# Check PacketRusher
echo "Checking PacketRusher..."
PACKETRUSHER_POD=$(kubectl get pods -l app=packetrusher -o jsonpath='{.items[0].metadata.name}')
kubectl get pod $PACKETRUSHER_POD | grep Running || echo "ERROR: PacketRusher not running"

# Test connectivity
echo "Testing 5G connectivity..."
kubectl exec $PACKETRUSHER_POD -- ip vrf exec vrf0000000003 ping -c 2 8.8.8.8 > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "5G connectivity: PASS"
else
    echo "5G connectivity: FAIL"
fi

echo "=== Health Check Complete ==="
```

## Section 8: Automated Testing Script

### 8.1 Complete Test Automation
```bash
#!/bin/bash
# Free5GC Automated Test Suite

set -e

echo "Starting Free5GC 5G Core Testing Suite"

# Get pod names
PACKETRUSHER_POD=$(kubectl get pods -l app=packetrusher -o jsonpath='{.items[0].metadata.name}')
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')

echo "PacketRusher Pod: $PACKETRUSHER_POD"
echo "Node IP: $NODE_IP"

# Test 1: Basic connectivity
echo "🔍 Test 1: 5G Data Connectivity"
kubectl exec $PACKETRUSHER_POD -- ip vrf exec vrf0000000003 ping -c 4 8.8.8.8
echo "Connectivity test completed"

# Test 2: Interface verification
echo "Test 2: Network Interface Verification"
kubectl exec $PACKETRUSHER_POD -- ip vrf exec vrf0000000003 ip addr show val0000000003
echo "Interface verification completed"

# Test 3: Performance test
echo "Test 3: Performance Testing"
kubectl exec $PACKETRUSHER_POD -- ip vrf exec vrf0000000003 iperf3 -c $NODE_IP -p 30201 -t 10 -i 2
echo "Performance test completed"

echo "All tests completed successfully!"
```