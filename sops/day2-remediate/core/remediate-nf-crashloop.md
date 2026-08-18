# Remediate NF CrashLoop

**Duration:** ~5 minutes
**Severity:** critical
**Trigger:** `core_nf_degraded` — core NF health below 100%, pod in CrashLoopBackOff

## Overview
One or more Open5GS core NFs are crashlooping. This degrades the SBI service mesh and can cascade to other NFs. Common causes: OOM kill, config error, dependency unavailable.

## Prerequisites
- kubectl access to cluster

## Steps

### Step 1: Identify crashlooping pods
```bash
kubectl get pods -n open5gs --no-headers | grep -v Running
```
**Expected**: List of non-Running pods

### Step 2: Check pod events for crash reason
```bash
kubectl describe pod $(kubectl get pods -n open5gs --no-headers | grep -v Running | head -1 | awk '{print $1}') -n open5gs | tail -20
```
**Expected**: Events showing OOMKilled, ImagePullBackOff, or error reason

### Step 3: Check pod logs for error
```bash
kubectl logs $(kubectl get pods -n open5gs --no-headers | grep -v Running | head -1 | awk '{print $1}') -n open5gs --previous --tail=30
```
**Expected**: Error messages before crash

### Step 4: If OOMKilled, increase memory limit
```bash
DEPLOY=$(kubectl get pods -n open5gs --no-headers | grep -v Running | head -1 | awk '{print $1}' | sed 's/-[a-z0-9]*-[a-z0-9]*$//')
kubectl patch deployment $DEPLOY -n open5gs --type=json -p='[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"512Mi"}]'
```
**Expected**: Deployment patched, new pod starts

### Step 5: If config error, check configmap
```bash
DEPLOY=$(kubectl get pods -n open5gs --no-headers | grep -v Running | head -1 | awk '{print $1}' | sed 's/-[a-z0-9]*-[a-z0-9]*$//')
kubectl get configmap -n open5gs | grep $DEPLOY
```
**Expected**: ConfigMap exists. Review content for syntax errors.

### Step 6: If SBI mesh is broken after multiple NF restarts, nuclear restart
```bash
kubectl delete pods --all -n open5gs
sleep 90
kubectl get pods -n open5gs --no-headers | awk '{print $1, $3}'
```
**Expected**: All pods Running after 90 seconds

## Verification

### Final Check: Force restart if backoff timer is stale
After fixing the root cause (killed stale process, fixed config, freed port), the pod may still be in CrashLoopBackOff due to Kubernetes exponential backoff. Force a restart to bypass:
```bash
DEPLOY=$(kubectl get pods -n open5gs --no-headers | grep -v Running | head -1 | awk '{print $1}' | sed 's/-[a-z0-9]*-[a-z0-9]*$//')
kubectl rollout restart deployment/$DEPLOY -n open5gs
sleep 30
kubectl get pods -n open5gs -l app.kubernetes.io/name=$(echo $DEPLOY | sed 's/open5gs-//') --no-headers
```
**Expected**: New pod in Running state within 30 seconds.

### Verify alarm clears
```bash
kubectl get pods -n open5gs --no-headers | grep -v Running | wc -l
```
**Expected**: `0` (all pods Running)

## Rollback
No destructive changes — remediation steps are additive (restart services, re-add routes).
If remediation worsens the situation, escalate to manual intervention.

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| OOMKilled | `kubectl describe pod` events | Increase memory limits |
| ImagePullBackOff | Image registry accessible? | Check ECR/Docker Hub connectivity |
| Config syntax error | Pod logs show YAML parse error | Fix configmap, restart pod |
| SBI mesh broken | Multiple NFs failing after restarts | Nuclear restart all pods |
| PCRF crashlooping | Expected for 5G SA | Scale to 0: `kubectl scale deploy open5gs-pcrf -n open5gs --replicas=0` |

## Related SOPs
- **Deploy:** `day1-deploy/deploy-5g-core.md`
