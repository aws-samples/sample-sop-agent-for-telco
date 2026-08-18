# Bootstrap Management Cluster for Bare-Metal Provisioning

**Duration:** ~20 minutes  
**Severity:** n/a (Day 0 setup)  
**Trigger:** Manual — new environment setup  

## Overview

This SOP bootstraps an EKS management cluster with ArgoCD, ACK, kro, and the Tinkerbell bare-metal provisioning stack. Upon completion, ANPA SHALL be able to process `ProvisioningRequest` CRs and drive zero-touch server onboarding.

This procedure follows the `eks-h-bare-metal-provisioning` USER-GUIDE (Phase 4–7).

## Key Words (RFC 2119)

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

## Prerequisites

- The management EKS cluster MUST exist and be in ACTIVE state.
- The operator MUST have `cluster-admin` access to the management cluster.
- Helm 3 MUST be installed locally.
- `values.yaml` MUST be configured with environment-specific details (see Step 2).
- The Git repository MUST be accessible from the ArgoCD Capability on the management cluster.
- EKS Capabilities (ArgoCD, ACK) MUST be enabled on the management cluster.
- Network connectivity from the management cluster VPC to the bare-metal BMC network MUST be established (Direct Connect, TGW, or VPN).

## Steps

### Step 1: Verify Cluster Access

The operator MUST confirm the management cluster is reachable and responsive.

```bash
kubectl --context eks-h-mgmt get ns
kubectl --context eks-h-mgmt get nodes
```

**Expected**: Cluster responds. The `argocd` namespace MAY exist but SHOULD be empty. If the cluster is unreachable, the operator MUST NOT proceed.

### Step 2: Verify EKS Capabilities

ArgoCD and ACK Capabilities MUST be active on the management cluster.

```bash
aws eks list-capabilities --cluster-name eks-h-mgmt-cluster-beta-v2-cl --region us-west-1 --profile cse-dev-test
```

**Expected**: Both `ack` and `argocd` capabilities listed with status ACTIVE. If either is missing, the operator MUST create them via the AWS Console or CLI before proceeding.

### Step 3: Validate Configuration

The operator MUST verify that `values.yaml` contains correct values for the target environment.

```bash
cd /local/home/awaizkh/ericsson-ran/eks-h-bare-metal-provisioning
cat values.yaml
```

The following fields are REQUIRED:

| Field | Description |
|-------|-------------|
| `git.repoURL` | MUST point to the accessible Git repository |
| `aws.accountId` | MUST match the target AWS account |
| `aws.region` | MUST match the management cluster region |
| `mgmtCluster.name` | MUST match the EKS cluster name |
| `mgmtCluster.arn` | MUST match the cluster ARN |
| `argoCD.idcInstanceARN` | MUST reference a valid IAM Identity Center instance |
| `bareMetalNetwork.cidr` | MUST match the bare-metal OAM network CIDR |
| `workloadClusters` | MUST contain at least one workload cluster entry |

The following fields are OPTIONAL:

| Field | Description |
|-------|-------------|
| `argoCD.rbacRoleMappings` | RECOMMENDED for production; MAY be omitted for PoC |
| `accessEntries.adminPrincipals` | SHOULD include operator IAM principals |

### Step 4: Apply Bootstrap Resources

The operator MUST apply the management bootstrap Helm template. This is the only imperative step; all subsequent operations SHALL be GitOps-driven.

```bash
helm template eks-h-bare-metal charts/mgmt-bootstrap/ -f values.yaml | kubectl --context eks-h-mgmt apply -f -
```

This creates:
- A Secret registering the management cluster as an ArgoCD deployment target.
- An `eks-h-bare-metal` Application that renders the full Helm chart.

The operator MUST NOT modify these resources manually after creation.

### Step 5: Verify ArgoCD Application

The operator MUST confirm ArgoCD has detected the bootstrap application.

```bash
kubectl --context eks-h-mgmt get applications -n argocd
```

**Expected**: `eks-h-bare-metal` application appears with status `Syncing` or `Synced`. If the application does not appear within 60 seconds, the operator SHOULD check ArgoCD controller logs.

### Step 6: Wait for Workload Cluster Creation

ACK SHALL create the workload cluster automatically from the rendered manifests. This step is NOT operator-driven.

```bash
kubectl --context eks-h-mgmt get clusters.eks.services.k8s.aws -A
aws eks describe-cluster --name <workload-cluster-name> --region us-west-1 --profile cse-dev-test --query 'cluster.status'
```

**Expected**: Workload cluster transitions to ACTIVE within 10–15 minutes. The operator SHOULD NOT intervene unless the cluster remains in CREATING for more than 20 minutes.

### Step 7: Verify Workload Cluster Self-Bootstrap

Once the workload cluster is ACTIVE, its ArgoCD Capability SHALL deploy the Tinkerbell stack automatically.

```bash
aws eks update-kubeconfig --name <workload-cluster-name> --region us-west-1 --profile cse-dev-test --alias <workload-cluster>
kubectl --context <workload-cluster> get pods -n tink-system
```

**Expected**: The following pods MUST be Running:
- `smee` (DHCP/PXE)
- `rufio` (BMC controller)
- `tink-server` (workflow engine)
- `tootles` (metadata server)

If any pod is in CrashLoopBackOff, the operator SHOULD check its logs before proceeding.

### Step 8: Verify kro and BareMetalServer RGD

kro MUST be installed and the BareMetalServer ResourceGraphDefinition MUST be registered.

```bash
kubectl --context <workload-cluster> get resourcegraphdefinitions
kubectl --context <workload-cluster> get crd | grep baremetal
```

**Expected**: `baremetalservers.kro.run` CRD exists. If missing, the operator MUST check the kro application sync status in ArgoCD.

### Step 9: Verify Image Server

The image server MUST be running and accessible via NLB.

```bash
kubectl --context <workload-cluster> get pods -n tink-system -l app=image-server
kubectl --context <workload-cluster> get svc -n tink-system | grep image-server
```

**Expected**: image-server pod Running, Service has an external NLB address. The NLB MUST be reachable from the bare-metal network.

### Step 10: Deploy ANPA on Management Cluster

ANPA SHOULD be deployed on the management cluster so it can watch ProvisioningRequest CRs across all workload clusters.

```bash
cd /local/home/awaizkh/anra-workspace/eks-hybrid-telco-ops
kubectl --context eks-h-mgmt apply -f helm-charts/anra-common/crds/
helm upgrade --install anpa helm-charts/anpa \
  --kube-context eks-h-mgmt \
  --namespace anpa-system --create-namespace \
  --set image.repository=833542146025.dkr.ecr.us-west-1.amazonaws.com/anra \
  --set image.tag=0.4.2 \
  --set agentRole=anpa \
  --set env.ANRA_CONFIG=/app/config/anra-config.yaml
```

### Step 11: Verify ANPA Reconciler

The ANPA reconciler MUST be running and able to list ProvisioningRequest CRs.

```bash
kubectl --context eks-h-mgmt get pods -n anpa-system
kubectl --context eks-h-mgmt exec -n anpa-system deploy/anpa -- curl -s http://localhost:8080/health
kubectl --context eks-h-mgmt logs deploy/anpa -n anpa-system --tail=10 | grep -v "GET /health"
```

**Expected**: Pod is Running, health returns `{"status": "ok"}`, logs show "ANPA reconciler starting".

## Verification

The operator MUST verify end-to-end by creating a test ProvisioningRequest:

```bash
kubectl --context <workload-cluster> apply -f - <<EOF
apiVersion: provisioning.anpa.aws.io/v1alpha1
kind: ProvisioningRequest
metadata:
  name: test-provision-001
  namespace: default
spec:
  site: site-test
  clusterName: <workload-cluster-name>
  nodes:
    - hostname: test-server-001
      role: ran
      hardwareProfile: dell-xr8620t
      osImage: ubuntu-2204-eks-hybrid-rt
EOF
```

Then confirm ANPA processes it:

```bash
kubectl --context eks-h-mgmt logs -f deploy/anpa -n anpa-system | grep -i "provision\|preflight\|workflow"
```

**Expected**: ANPA detects the CR, runs preflight checks, and creates a BareMetalProvision CR. If bare-metal servers are available, Tinkerbell SHALL begin the provisioning workflow.

## Rollback

If the bootstrap fails or needs to be undone:

```bash
# Remove ANPA
helm uninstall anpa --kube-context eks-h-mgmt -n anpa-system

# Remove the bootstrap application (stops all GitOps reconciliation)
kubectl --context eks-h-mgmt delete application eks-h-bare-metal -n argocd

# Remove workload cluster (if created and unwanted)
aws eks delete-cluster --name <workload-cluster-name> --region us-west-1 --profile cse-dev-test
```

The operator MUST NOT delete the management cluster itself — only the resources deployed by this SOP.

## Troubleshooting

| Issue | Check | Resolution |
|-------|-------|------------|
| ArgoCD app not syncing | `kubectl get app eks-h-bare-metal -n argocd -o yaml` | Verify git.repoURL is accessible; check ArgoCD repo-server logs |
| ACK not creating cluster | `kubectl get clusters.eks -A -o yaml` | Check ACK controller logs; verify IAM role has EKS permissions |
| Tinkerbell pods CrashLoop | `kubectl logs -n tink-system <pod>` | Usually cert-manager not ready; wait for wave ordering |
| kro not reconciling | `kubectl describe rgd baremetalserver` | Check kro controller logs; verify RGD syntax |
| NLB not getting IP | `kubectl get svc -n tink-system` | Check AWS LB Controller logs; verify subnet tags |
| ANPA can't see CRs | `kubectl auth can-i list provisioningrequests --as=system:serviceaccount:anpa-system:anpa-sa` | Patch ClusterRole with provisioning CRD access |

## Related SOPs

- **Next:** [Add Bare Metal Servers](../day1-deploy/deploy-ran-du.md) — after bootstrap, add servers to provision
- **Escalation:** If Tinkerbell fails to provision, ANPA AI brain SHALL diagnose and attempt resolution autonomously
- **Prevention:** Ensure `values.yaml` is validated before bootstrap to avoid configuration drift
