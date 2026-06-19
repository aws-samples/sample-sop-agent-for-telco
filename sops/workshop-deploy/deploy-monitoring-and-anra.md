# Deploy ANRA with Monitoring Stack

## Overview

This SOP deploys the ANRA (Autonomous Network Remediation Agent) with bundled InfluxDB and Telegraf monitoring on an EKS cluster. A single Helm install provisions the complete Day 2 stack: metrics collection, time-series storage, alarm detection, and autonomous remediation. The SOP also configures the IAM assume-role chain required for ANRA to access Amazon Bedrock through the jumphost role.

Use this SOP after the 5G Core has been deployed and end-to-end connectivity has been validated. Estimated duration: 5 minutes.

## Parameters

- **bedrock_region** (optional, default: `"us-west-2"`): AWS region for Bedrock model invocation
- **image_tag** (optional, default: `"latest"`): Container image tag for the ANRA agent
- **auth_username** (optional, default: `"admin"`): HTTP Basic Auth username for the dashboard
- **auth_password** (optional, default: `"anra2026"`): HTTP Basic Auth password for the dashboard

**Constraints for parameter acquisition:**
- You MUST detect the AWS account ID using `aws sts get-caller-identity`
- You MUST detect the cluster name and region from the current kubectl context
- You SHOULD use the default values for optional parameters unless explicitly overridden

## Prerequisites

- 5G Core deployed (`deploy-5g-core.md` completed successfully)
- End-to-end connectivity validated (`validate-e2e.md` completed successfully)
- `helm`, `kubectl`, and `aws` CLI tools available on the jump host
- `anra-workshop-jumphost` IAM role exists in the account

## Steps

### 1. Deploy ANRA via Helm

Install the ANRA agent with bundled InfluxDB and Telegraf using the Helm chart. The deployment includes the `BEDROCK_ROLE_ARN` environment variable so the container entrypoint can configure the assume-role chain at startup.

**Constraints:**
- You MUST resolve `ACCOUNT_ID`, `CLUSTER_NAME`, and `REGION` before running helm
- You MUST pass `--set env.BEDROCK_ROLE_ARN` with the jumphost role ARN
- You MUST use `image.tag=latest` to pull the most recent workshop image
- You MUST set `--timeout 120s` to accommodate slow pulls of the public image
- You MUST NOT skip this step even if a previous deployment exists; helm upgrade is idempotent

```tool: shell
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text) && CLUSTER_NAME=$(kubectl config current-context | awk -F/ '{print $NF}') && REGION=$(kubectl config current-context | awk -F: '{print $4}') && helm upgrade --install anra helm/anra --namespace anra --create-namespace --set image.repository=public.ecr.aws/t2j9i5y9/anra-workshop --set image.tag=latest --set bedrock.region=us-west-2 --set approval.mode=auto --set config.cluster.name=$CLUSTER_NAME --set config.cluster.region=$REGION --set env.AUTH_USERNAME=admin --set env.AUTH_PASSWORD=anra2026 --set env.BEDROCK_ROLE_ARN=arn:aws:iam::${ACCOUNT_ID}:role/anra-workshop-jumphost --timeout 120s
```

**Expected:** `STATUS: deployed`

### 2. Ensure BEDROCK_ROLE_ARN environment variable is set

This is an idempotent safety check. If the helm command in Step 1 was modified or stripped of long flags during execution, this step explicitly sets the required environment variable on the deployment.

**Constraints:**
- You MUST run this step even if Step 1 succeeded, to guarantee the env var is present
- You MUST use the same role ARN format as Step 1
- You SHOULD verify the deployment rolled out successfully after this step

```tool: shell
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text) && kubectl set env deploy/anra -n anra BEDROCK_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/anra-workshop-jumphost"
```

**Expected:** `deployment.apps/anra env updated` or no change if already set

### 3. Configure IAM assume-role policies

ANRA pods run with the EKS node group role, which Workshop Studio SCPs do not permit Bedrock access. This step adds a trust relationship allowing the node role to assume the jumphost role (which has Bedrock permissions), and adds an inline policy on the node role granting `sts:AssumeRole`.

**Constraints:**
- You MUST update the trust policy on `anra-workshop-jumphost` to include the node group role as a trusted principal
- You MUST add an inline policy on the node group role allowing `sts:AssumeRole` on the jumphost role
- You MUST preserve the existing EC2 service trust principal in the trust policy
- You MUST NOT remove or replace any existing inline policies on the node role; use a unique policy name

```tool: shell
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text) && NODE_ROLE=$(aws iam list-roles --query 'Roles[?contains(RoleName,`node-group`)].RoleName' --output text) && cat > /tmp/trust.json << EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"},{"Effect":"Allow","Principal":{"AWS":"arn:aws:iam::${ACCOUNT_ID}:role/${NODE_ROLE}"},"Action":"sts:AssumeRole"}]}
EOF
aws iam update-assume-role-policy --role-name anra-workshop-jumphost --policy-document file:///tmp/trust.json && aws iam put-role-policy --role-name "$NODE_ROLE" --policy-name AllowAssumeJumphost --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Resource\":\"arn:aws:iam::${ACCOUNT_ID}:role/anra-workshop-jumphost\"}]}"
```

**Expected:** Both `update-assume-role-policy` and `put-role-policy` complete without errors

### 4. Wait for all pods to become ready

**Constraints:**
- You MUST wait for both ANRA and InfluxDB pods to reach `Ready` condition
- You MUST use a timeout of at least 120 seconds to allow for image pull and startup
- You SHOULD NOT proceed if any pod fails to become ready

```tool: kubectl
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=anra -n anra --timeout=120s && kubectl wait --for=condition=ready pod -l app=influxdb -n anra --timeout=120s
```

**Expected:** All conditions met

### 5. Verify monitoring stack pods are running

**Constraints:**
- You MUST verify three pods exist: `anra`, `influxdb`, and `telegraf-core`
- You MUST verify all three pods show `Running` status
- You SHOULD investigate any pod not in `Running` state before proceeding

```tool: kubectl
kubectl get pods -n anra --no-headers | awk '{print $1, $3}' | column -t
```

**Expected:** anra, influxdb, telegraf-core all Running

### 6. Start port forwarding for dashboard access

The ANRA service uses an internal ClusterIP. Access the dashboard securely via SSM port-forward from your laptop — no public exposure required.

**Constraints:**
- You MUST start `kubectl port-forward` on the jump host (localhost only) so the ANRA port is reachable locally
- You MUST then use SSM port-forward from your laptop to tunnel through to the jump host
- You MUST NOT bind to `0.0.0.0` — the dashboard should not be publicly accessible

**On the jump host** (via SSM session):
```tool: shell
kubectl port-forward deploy/anra -n anra 8080:8080 &
sleep 3 && curl -sf -u admin:anra2026 http://localhost:8080/health && echo " — Dashboard ready on localhost:8080"
```

**Expected:** `{"status":"ok"}` — Dashboard ready on localhost:8080

**On your laptop** (separate terminal — connect via SSM port-forward):
```bash
INSTANCE_ID=<jump-host-instance-id>  # from Workshop Studio outputs
aws ssm start-session --target $INSTANCE_ID \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8080"],"localPortNumber":["8080"]}' \
  --region <workshop-region>
```

Then open http://localhost:8080 in your browser. Login: `admin` / `anra2026`

### 7. Verify ANRA monitoring is active

**Constraints:**
- You MUST verify the ANRA agent has loaded its configuration and started the monitor loop
- You SHOULD look for log messages indicating alarm definitions were loaded
- You SHOULD report the monitoring status as part of the final summary

```tool: shell
sleep 10 && kubectl logs deploy/anra -n anra --tail=10 | grep -iE "monitor|alarm|poll|config"
```

**Expected:** Log messages confirming monitor is running and alarm definitions are loaded

## Examples

### Successful deployment summary

After running this SOP, you should see:
- 3 pods Running in the `anra` namespace
- IAM trust policy on `anra-workshop-jumphost` includes the node group role
- ANRA pod environment includes `BEDROCK_ROLE_ARN`
- Dashboard reachable at `http://localhost:8080` (via SSM port-forward)
- Ask ANRA chat responds to queries (validates Bedrock access via assume-role chain)

## Troubleshooting

### Ask ANRA returns AccessDeniedException for ConverseStream

**Cause:** The pod is not assuming the jumphost role. Either `BEDROCK_ROLE_ARN` is not set, the trust policy is missing, or the inline policy on the node role is missing.

**Resolution:** Re-run Steps 2 and 3, then restart the ANRA pod:
```bash
kubectl delete pod -n anra -l app.kubernetes.io/name=anra
```

### Helm install times out

**Cause:** Image pull from ECR Public is slow on first deployment.

**Resolution:** Re-run Step 1; helm upgrade is idempotent. Increase `--timeout` to `300s` if needed.

### Port 8080 already in use

**Cause:** A previous `kubectl port-forward` is still running.

**Resolution:** Kill the existing port forward before starting a new one:
```bash
pkill -f "port-forward.*anra"
sleep 3
kubectl port-forward deploy/anra -n anra 8080:8080 &
```

## Production Alternatives

| Workshop (in-cluster) | Production (AWS managed) |
|---|---|
| InfluxDB pod | Amazon Timestream for InfluxDB |
| Telegraf pod | Amazon CloudWatch Container Insights |
| Public IP + Basic Auth | Amazon CloudFront + ALB + WAF + Cognito |
| Assume-role workaround | Native IRSA with Bedrock policy attached |

## Related SOPs

- **Previous:** `workshop-deploy/validate-e2e.md`
- **Next:** Trigger alarms from the ANRA dashboard to watch autonomous remediation
