# ArgoCD GitOps Management SOP

**Status:** ✅ DEPLOYED  
**Stage:** 3 of 8  
**Last Updated:** 2026-01-29

---

## Prerequisites
- ArgoCD MUST be installed and running in the `argocd` namespace
- The operator MUST have kubectl access and ArgoCD application permissions
- The GitLab repository containing the UPF Helm chart MUST be reachable from ArgoCD
- The target `aws-upf` namespace SHOULD exist (ArgoCD MAY create it via syncOptions)

## Description
GitOps-driven deployment and monitoring for NEC UPF using ArgoCD. This SOP covers:
- **Enable auto-sync** - Let ArgoCD manage UPF deployment
- **Disable auto-sync** - Manual control for maintenance/testing
- **Check status** - Verify sync and health state
- **Force sync** - Trigger immediate deployment

## Architecture

```
GitLab (deploy branch)
        ↓
   ArgoCD Detects Change (~3min)
        ↓
   PreSync Validation Job
   ├── Check pods (3 running)
   ├── Check gRPC (port 1024)
   ├── Check GWU status
   ├── Check BGP neighbors
   └── Check CNI stack
        ↓
   ┌────┴────┐
   ↓         ↓
 PASS      FAIL
   ↓         ↓
 Deploy   Blocked
   ↓
 PostSync Validation
```

---

## Current Configuration

### Repository
- **URL:** https://gitlab.com/amazon-web-services-group1/nec-mwc-2026.git
- **Branch:** deploy
- **Path:** upf

### Sync Policy
- **Auto-sync:** Enabled
- **Prune:** Enabled (removes deleted resources)
- **Self-heal:** Enabled (reverts manual changes)

---

## Steps

### 0. Create ArgoCD Application (if deleted)

If the nec-upf application was removed (e.g., after teardown via `09-teardown.md`):

```bash
kubectl apply -f argocd/application.yaml
```

**Verify:**
```bash
kubectl get application -n argocd nec-upf
```

Then enable auto-sync (Step 6) or force sync (Step 5) to deploy UPF.

### 1. Verify ArgoCD Installation
```bash
kubectl get pods -n argocd
```
**Expected**: All pods Running (server, controller, repo-server, redis, dex)

### 2. Check Application Status
```bash
kubectl get application nec-upf -n argocd
```
**Expected**: `Synced` and `Healthy`

### 3. Validate Application Configuration (Critical)

> **WARNING:** If the destination namespace is wrong, ArgoCD will deploy UPF to the wrong namespace while reporting "Synced, Healthy". Always verify these fields.

```bash
kubectl get application nec-upf -n argocd -o jsonpath='
Repo: {.spec.source.repoURL}
Branch: {.spec.source.targetRevision}
Path: {.spec.source.path}
Namespace: {.spec.destination.namespace}
Sync: {.status.sync.status}
Health: {.status.health.status}
'
```

**Expected values — ALL must match:**
| Field | Expected | Failure if wrong |
|-------|----------|-----------------|
| Repo | `https://gitlab.com/amazon-web-services-group1/nec-mwc-2026.git` | Wrong repo |
| Branch | `deploy` | Wrong manifests |
| Path | `upf` | Wrong chart |
| **Namespace** | **`aws-upf`** | **UPF deploys to wrong namespace — all SOPs break** |

**Auto-fix if namespace is wrong:**
```bash
kubectl -n argocd patch application nec-upf --type merge -p '{"spec":{"destination":{"namespace":"aws-upf"}}}'
```

### 4. Check Sync Policy
```bash
kubectl get application nec-upf -n argocd -o jsonpath='{.spec.syncPolicy}' | jq .
```
**Expected**:
```json
{
  "automated": {
    "prune": true,
    "selfHeal": true
  },
  "syncOptions": ["CreateNamespace=true"]
}
```

### 5. View Managed Resources
```bash
kubectl get application nec-upf -n argocd -o json | jq -r '.status.resources[] | "\(.kind)/\(.name)"'
```

### 6. Check PreSync Hook
```bash
kubectl get jobs -n aws-upf | grep presync
```

---

## Validation Checks (PreSync Gate)

The PreSync hook validates before any deployment:

| Check | Command | Expected |
|-------|---------|----------|
| Pods | `kubectl get pods -n aws-upf` | 3 Running |
| gRPC | `ss -anp \| grep :1024` | LISTEN + ESTAB |
| GWU | `view_gwur` | sts=act |
| BGP | Check bgpd log | Neighbors Up |
| CNI | `kubectl get pods -n kube-system` | multus + sriov Running |

---

## Pre-Check Before Enable/Disable

Before enabling or disabling auto-sync, check current state:

```bash
# Check if UPF pods exist
kubectl get pods -n aws-upf --no-headers 2>/dev/null | wc -l
```

| Pods Found | Action |
|------------|--------|
| 0 | Safe to enable auto-sync - ArgoCD will deploy fresh UPF |
| 3 | UPF deployed - enabling auto-sync may overwrite manual config |

> **WARNING:** If UPF is already configured (GWU active, BGP up), enabling auto-sync will NOT overwrite it. ArgoCD only manages Kubernetes resources, not UPF runtime config.

---

## Manual Operations

### Disable Auto-Sync
Use when: Manual helm install, maintenance, testing, or emergency rollback.

**Pre-check:**
```bash
kubectl get pods -n aws-upf --no-headers 2>/dev/null
```

**Disable:**
```bash
kubectl patch application nec-upf -n argocd --type merge -p '{"spec":{"syncPolicy":null}}'
```
**Verify:** `kubectl get application nec-upf -n argocd -o jsonpath='{.spec.syncPolicy}'` returns empty.

### Enable Auto-Sync
Use when: Hand control back to GitOps after manual operations complete, or deploy fresh UPF.

**Pre-check:**
```bash
kubectl get pods -n aws-upf --no-headers 2>/dev/null | wc -l
```
- If 0 pods: Safe to enable - ArgoCD will deploy UPF
- If 3 pods: UPF already running - ArgoCD will sync but not disrupt

**Enable:**
```bash
kubectl patch application nec-upf -n argocd --type merge -p '{
  "spec": {
    "syncPolicy": {
      "automated": {"prune": true, "selfHeal": true},
      "syncOptions": ["CreateNamespace=true"]
    }
  }
}'
```
**Verify:** Application shows `Synced` status within 60 seconds.

> **NOTE:** When auto-sync is enabled, ArgoCD will automatically deploy UPF from GitLab if namespace is empty. Wait ~60s for pods to start, then ~60s more for BGP to converge.

### Check Status
```bash
kubectl get application nec-upf -n argocd -o jsonpath='Sync: {.status.sync.status}, Health: {.status.health.status}, AutoSync: {.spec.syncPolicy.automated}'
```

### Force Sync
```bash
kubectl patch application nec-upf -n argocd --type merge -p '{"operation":{"sync":{}}}'
```

### Hard Refresh
```bash
kubectl patch application nec-upf -n argocd --type merge -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'
```

---

## Troubleshooting

### Application OutOfSync
```bash
# Check what's different
kubectl get application nec-upf -n argocd -o jsonpath='{.status.sync.status}'

# View diff
kubectl describe application nec-upf -n argocd | grep -A 20 "Sync Status"
```

### PreSync Validation Failed
```bash
# Check job logs
kubectl logs -n aws-upf job/upf-presync-validation

# Check events
kubectl get events -n aws-upf --sort-by='.lastTimestamp' | tail -10
```

### Git Access Issues
```bash
# Check repo-server logs
kubectl logs -n argocd deployment/argocd-repo-server --tail=20 | grep -i error
```

### Git Token Expired / Authentication Failed
```bash
# Check for auth errors in app conditions
kubectl get application nec-upf -n argocd -o jsonpath='{.status.conditions}' | grep -i "ComparisonError\|authentication"
```
**If authentication error found:**
1. Generate new GitLab token with `read_repository` scope
2. Update ArgoCD repo secret:
```bash
NEW_TOKEN_B64=$(echo -n "<new-token>" | base64 -w0)
kubectl -n argocd patch secret repo-docomo-nec -p "{\"data\":{\"password\":\"$NEW_TOKEN_B64\"}}"
```
3. Hard refresh: `kubectl -n argocd patch application nec-upf --type merge -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'`

### Destination Namespace Wrong (UPF in wrong namespace)
```bash
# Check where ArgoCD is deploying
kubectl get application nec-upf -n argocd -o jsonpath='{.spec.destination.namespace}'
```
**If not `aws-upf`:**
```bash
kubectl -n argocd patch application nec-upf --type merge -p '{"spec":{"destination":{"namespace":"aws-upf"}}}'
```

---

## Success Criteria
- ✅ ArgoCD pods running
- ✅ Application synced and healthy (when auto-sync enabled)
- ✅ Application OutOfSync (when auto-sync disabled and resources deleted)
- ✅ PreSync validation hook configured
- ✅ GitLab repo connected (deploy branch)

---

## ISV Instructions (NEC)

To deploy a new UPF version:

1. Clone: `git clone https://gitlab.com/amazon-web-services-group1/nec-mwc-2026.git`
2. Checkout: `git checkout deploy`
3. Update `upf/` folder with new helm chart
4. Commit and push to `deploy` branch
5. ArgoCD auto-deploys after validation passes

