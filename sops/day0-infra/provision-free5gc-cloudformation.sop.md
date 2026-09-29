# Provision the Free5GC Workshop Infrastructure with CloudFormation

## Overview
Provision the workshop-v3 VPC, EKS cluster, bastion, Multus networks, worker nodes, and pinned gtp5g module. Use this SOP instead of ANPA; it does not create or reconcile ANPA resources.

## Parameters

- **stack_name** (required): CloudFormation stack name; use a unique, lowercase workshop identifier.
- **aws_region** (required): AWS Region containing two available Availability Zones and the required EC2 key pair.
- **bastion_key** (required): Existing EC2 key-pair name accepted by the CloudFormation template.
- **worker_key** (optional, default: same as `bastion_key`): Existing key pair for EKS workers.
- **allowed_external_cidr** (optional, default: `127.0.0.1/32`): CIDR allowed to reach SSH and workshop web ports; keep the default when using SSM forwarding.

**Constraints for parameter acquisition:**
- If all required parameters are already provided, You MUST proceed to the Steps
- If any required parameters are missing, You MUST ask for them before proceeding
- When asking for parameters, You MUST request all parameters in a single prompt
- When asking for parameters, You MUST use the exact parameter names as defined

## Prerequisites
- AWS CLI credentials with CloudFormation, EKS, EC2, IAM, SSM, and S3 permissions.
- `jq` and Bash available locally.
- The account MUST be a disposable workshop account because this SOP creates chargeable infrastructure.

## Steps

### 1. Validate the pinned infrastructure contract
Confirm the branch and required artifacts before creating resources.

```bash
test "$(git branch --show-current)" = workshop-v3
test "$(git merge-base HEAD e938040ba0042156e2811d10b9fb097a73268393)" = e938040ba0042156e2811d10b9fb097a73268393
test -f infra/cloudformation/vpc-eks-multus.yaml
test -f scripts/free5gc/01-deploy-infra.sh
test -f scripts/free5gc/install-gtp5g.sh
```

**Expected**: All checks return success and the branch descends from the requested workshop-v2 commit.

**Constraints:**
- You MUST NOT continue from a different branch because dry-run evidence must identify one immutable baseline.
- You MUST NOT modify the N2/N3/N4/N6 CIDRs independently because the bundled Helm charts use matching static Multus addresses.

### 2. Deploy the CloudFormation stack
Deploy the infrastructure using the adapted IND321 template.

```bash
export STACK_NAME="${STACK_NAME:?Set STACK_NAME from stack_name}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:?Set AWS_DEFAULT_REGION from aws_region}"
export BASTION_KEY="${BASTION_KEY:?Set BASTION_KEY from bastion_key}"
export WORKER_KEY="${WORKER_KEY:-$BASTION_KEY}"
export ALLOWED_EXTERNAL_CIDR="${ALLOWED_EXTERNAL_CIDR:-127.0.0.1/32}"
bash scripts/free5gc/01-deploy-infra.sh
```

**Expected**: CloudFormation reaches `CREATE_COMPLETE` or `UPDATE_COMPLETE` and prints the EKS cluster and bastion outputs.

**Constraints:**
- You MUST keep external access restricted unless the dry-run operator explicitly supplies a trusted CIDR.
- If CloudFormation fails, You MUST stop and report the failed resource before attempting Kubernetes installation.

### 3. Verify the Day-0 result
Record the exact stack and cluster identifiers.

```bash
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" --region "$AWS_DEFAULT_REGION" \
  --query 'Stacks[0].{Status:StackStatus,Outputs:Outputs}' --output json
```

**Expected**: The stack is complete and includes `BastionInstanceId`, `EksCluster`, and all four Multus subnet outputs.

**Constraints:**
- You MUST save this output with the dry-run evidence because subsequent SOPs depend on these identifiers.
- You MUST NOT deploy ANPA because CloudFormation is the workshop-v3 Day-0 provisioning mechanism.

## Examples
Use `STACK_NAME=telco-dryrun-01`, a selected AWS Region, and SSM forwarding with `ALLOWED_EXTERNAL_CIDR=127.0.0.1/32`.

## Troubleshooting
If a node does not join, inspect launch-template and `/var/log/cloud-init-output.log` through SSM. If gtp5g fails, verify the running kernel has matching headers and rerun `scripts/free5gc/install-gtp5g.sh` through SSM.
