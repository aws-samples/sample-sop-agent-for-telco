# Remediate NF CrashLoopBackOff

**Severity:** Major
**Duration:** ~3 minutes

## Overview
A core network function pod is in CrashLoopBackOff. Diagnose the root cause and restore service.

## Steps

### Step 1: Identify the failing pod
```tool: kubectl
kubectl get pods -n open5gs --field-selector=status.phase!=Running --no-headers
```
**Expected**: One or more pods showing CrashLoopBackOff or Error

### Step 2: Check pod logs for crash reason
```tool: kubectl
kubectl logs -l app.kubernetes.io/name=NF_NAME -n open5gs --tail=20 --previous 2>/dev/null || kubectl logs -l app.kubernetes.io/name=NF_NAME -n open5gs --tail=20
```
**Expected**: Error message indicating crash cause

### Step 3: Check pod events
```tool: kubectl
kubectl describe pod -l app.kubernetes.io/name=NF_NAME -n open5gs | tail -20
```
**Expected**: Events showing OOMKilled, ImagePullBackOff, or application error

### Step 4: Apply fix based on diagnosis

**If OOMKilled:** Increase memory limits
```tool: kubectl
kubectl patch deployment NF_NAME -n open5gs -p '{"spec":{"template":{"spec":{"containers":[{"name":"NF_NAME","resources":{"limits":{"memory":"512Mi"}}}]}}}}'
```

**If Diameter/fd_init error (SMF):** Disable PCRF
```tool: shell
helm upgrade open5gs oci://registry-1.docker.io/gradiantcharts/open5gs --version 2.3.4 --namespace open5gs --reuse-values --set smf.config.pcrf.enabled=false --timeout 300s
```

**If MongoDB connection error:** Wait for MongoDB and restart the NF
```tool: kubectl
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=mongodb -n open5gs --timeout=120s && kubectl delete pod -l app.kubernetes.io/name=NF_NAME -n open5gs
```

### Step 5: Verify recovery
```tool: kubectl
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=NF_NAME -n open5gs --timeout=120s && echo "NF recovered"
```
**Expected**: `NF recovered`

## Known Issues

### SBI mesh breaks after individual NF restart
If other NFs start failing after fixing one, do a nuclear restart:
```tool: kubectl
kubectl delete pods --all -n open5gs
```
Wait 90 seconds for full re-registration with NRF.
