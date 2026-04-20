# SOP Development Guide

Guide for creating Standard Operating Procedures (SOPs) for NFV validation.

## Quick Start

```bash
cp sops/TEMPLATE.md sops/my-sop.md
# Edit with your steps
# Test via Web UI or API
```

## SOP Structure

```markdown
# SOP Title

**Duration:** ~N minutes

## Prerequisites
- Required access/tools
- Prior SOPs completed

## Steps

### 1. Step Name
\`\`\`bash
command here
\`\`\`
**Expected**: What success looks like

## Verification
Final validation steps

## Troubleshooting
| Issue | Check | Fix |
|-------|-------|-----|
```

## Separating Config from Procedure

Keep vendor/deployment-specific data in config files, not hardcoded in SOPs:

### Config File (`configs/my-deployment.yaml`)
```yaml
namespace: my-app
replicas: 3
image: my-registry/my-app:v1.0
```

### SOP References Config
```markdown
### Deploy Application
\`\`\`bash
kubectl apply -f deployment.yaml -n ${config.namespace}
\`\`\`
```

This allows the same SOP to work across different deployments by swapping config files.

## Available Tools

| Tool | Description | Example |
|------|-------------|---------|
| `kubectl` | Kubernetes commands | `kubectl get pods -n demo` |
| `helm` | Helm operations | `helm upgrade --install myapp ./chart` |
| `shell` | Shell commands | `curl`, `sleep`, `jq` |

## Writing Effective Steps

### One Action Per Step
```markdown
# Good
### 1. Create namespace
\`\`\`bash
kubectl create namespace demo
\`\`\`
**Expected**: namespace/demo created
```

### Include Wait Times
```markdown
### 3. Wait for convergence
\`\`\`bash
echo "Waiting 60 seconds..."
sleep 60
\`\`\`
```

### Specific Expected Outputs
```markdown
# Good
**Expected**: `status=active`

# Good
**Expected**: 3 pods in Running state

# Bad
**Expected**: Should work
```

### Retry Guidance
```markdown
### Verify Status
\`\`\`bash
kubectl get deployment myapp -o jsonpath='{.status.readyReplicas}'
\`\`\`
**Expected**: `3`
**If not ready**: Wait 30s and retry up to 3 times
```

### Troubleshooting Tables
```markdown
## Troubleshooting
| Issue | Check | Fix |
|-------|-------|-----|
| Pod pending | `kubectl describe pod` | Check node resources |
| CrashLoop | `kubectl logs <pod>` | Check app config |
```

## Best Practices

1. **Idempotent commands** - Safe to re-run
   ```bash
   kubectl create namespace demo 2>/dev/null || echo "exists"
   ```

2. **Explicit namespaces** - Always specify `-n namespace`

3. **Verification steps** - Confirm each action succeeded

4. **Document timing** - Note any required wait times

5. **Related SOPs** - Link to prerequisites and next steps
