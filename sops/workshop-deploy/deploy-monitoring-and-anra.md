# Deploy Monitoring Stack and ANRA Agent

**Duration:** ~5 minutes
**Target:** EKS cluster (anra namespace)

## Overview
Deploy the ANRA agent with bundled InfluxDB and Telegraf monitoring. One Helm install deploys the full Day 2 stack: metrics collection, storage, alarm detection, and autonomous remediation.

## Prerequisites
- 5G Core deployed (deploy-5g-core.md completed)
- E2E validated (validate-e2e.md completed)

## Steps

### Step 1: Deploy ANRA with monitoring stack
```tool: shell
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text) && CLUSTER_NAME=$(kubectl config current-context | awk -F/ '{print $NF}') && REGION=$(kubectl config current-context | awk -F: '{print $4}') && helm upgrade --install anra helm/anra --namespace anra --create-namespace --set image.repository=public.ecr.aws/a4u0k5h0/anra-workshop --set image.tag=v3 --set bedrock.region=us-west-2 --set approval.mode=auto --set config.cluster.name=$CLUSTER_NAME --set config.cluster.region=$REGION --set env.AUTH_USERNAME=admin --set env.AUTH_PASSWORD=anra2026 --set env.BEDROCK_ROLE_ARN=arn:aws:iam::${ACCOUNT_ID}:role/anra-workshop-jumphost --timeout 120s
```
**Expected**: `STATUS: deployed`

### Step 1b: Ensure BEDROCK_ROLE_ARN is set on ANRA pod (idempotent safety check)
```tool: shell
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text) && kubectl set env deploy/anra -n anra BEDROCK_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/anra-workshop-jumphost"
```
**Expected**: `deployment.apps/anra env updated` (or unchanged)

### Step 1c: Configure assume-role IAM policies for Bedrock access
```tool: shell
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text) && NODE_ROLE=$(aws iam list-roles --query 'Roles[?contains(RoleName,`node-group`)].RoleName' --output text) && cat > /tmp/trust.json << EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"},{"Effect":"Allow","Principal":{"AWS":"arn:aws:iam::${ACCOUNT_ID}:role/${NODE_ROLE}"},"Action":"sts:AssumeRole"}]}
EOF
aws iam update-assume-role-policy --role-name anra-workshop-jumphost --policy-document file:///tmp/trust.json && aws iam put-role-policy --role-name "$NODE_ROLE" --policy-name AllowAssumeJumphost --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Resource\":\"arn:aws:iam::${ACCOUNT_ID}:role/anra-workshop-jumphost\"}]}"
```
**Expected**: Trust policy and inline policy applied successfully

> **Note:** This deploys 3 components: ANRA agent, InfluxDB (metrics store), Telegraf (NF metrics collector). Auth is enabled for public access.

### Step 2: Wait for all pods
```tool: kubectl
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=anra -n anra --timeout=120s && kubectl wait --for=condition=ready pod -l app=influxdb -n anra --timeout=120s
```
**Expected**: All conditions met

### Step 3: Verify monitoring stack
```tool: kubectl
kubectl get pods -n anra --no-headers | awk '{print $1, $3}' | column -t
```
**Expected**: anra, influxdb, telegraf-core all Running

### Step 4: Verify service is internal LoadBalancer
```tool: kubectl
kubectl get svc anra -n anra -o jsonpath='{.metadata.annotations.service\.beta\.kubernetes\.io/aws-load-balancer-internal}' && echo " (internal)"
```
**Expected**: `true (internal)`

> **Note:** The Helm chart creates an internal LoadBalancer by default. Access the dashboard via SSM port-forwarding from the jump host.

### Step 5: Start port forward for public access
```tool: shell
kubectl port-forward deploy/anra -n anra 8080:8080 --address 0.0.0.0 &
sleep 5 && echo "Dashboard accessible at http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):8080"
```
**Expected**: Dashboard URL with public IP. Login: admin / anra2026

### Step 6: Verify ANRA is monitoring
```tool: shell
sleep 10 && kubectl logs deploy/anra -n anra --tail=10 | grep -iE "monitor|alarm|poll|config"
```
**Expected**: Log messages showing monitoring active, alarm definitions loaded

## Verification
Access the ANRA dashboard and verify:
- **Dashboard** page shows cluster topology
- **Alarms** page shows demo trigger buttons
- **SOPs** page lists available SOPs

## Production Alternatives
| Workshop (in-cluster) | Production (AWS managed) |
|---|---|
| InfluxDB pod | Amazon Timestream for InfluxDB |
| Telegraf pod | Amazon CloudWatch Container Insights |
| LoadBalancer | Amazon CloudFront + ALB with WAF |
| Basic Auth | Amazon Cognito |

## Related SOPs
- **Previous:** `workshop-deploy/validate-e2e.md`
- **Next:** Trigger alarms from dashboard → watch ANRA auto-remediate
