# Deployment Guide

Deploy the Strands SOP Agent to EKS for NFV validation workflows.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Validation Environment                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌──────────────┐      ┌──────────────────────────────────────┐   │
│   │  CloudFront  │──────│  EKS Cluster (Control Plane)         │   │
│   │   (HTTPS)    │      │  ┌────────────────────────────────┐  │   │
│   └──────────────┘      │  │  SOP Agent Pod                 │  │   │
│                         │  │  - IRSA for Bedrock            │  │   │
│                         │  │  - Multi-cluster kubeconfig    │  │   │
│                         │  └────────────────────────────────┘  │   │
│                         └──────────────────────────────────────┘   │
│                                        │                            │
│         ┌──────────────────────────────┼──────────────────────────┐│
│         ▼                              ▼                          ▼││
│   ┌───────────┐                 ┌───────────┐              ┌───────────┐
│   │ EKS-A     │                 │ EKS-A     │              │ EKS-H     │
│   │ Vendor A  │                 │ Vendor B  │              │ Vendor C  │
│   └───────────┘                 └───────────┘              └───────────┘
│     Outpost 1                    Outpost 2                  Hybrid     │
└─────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. **EKS Cluster** for hosting the SOP Agent
2. **AWS Load Balancer Controller** installed (for ALB Ingress)
3. **Bedrock model access** enabled (Haiku, Sonnet, Opus)
4. **ECR repository** with the agent image

## Step 1: Push Image to ECR

```bash
# Build
docker build -t sample-sop-agent-for-strands .

# Create ECR repo
aws ecr create-repository --repository-name sample-sop-agent-for-strands --region us-west-2

# Push
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin <ACCOUNT>.dkr.ecr.us-west-2.amazonaws.com
docker tag sample-sop-agent-for-strands:latest <ACCOUNT>.dkr.ecr.us-west-2.amazonaws.com/sample-sop-agent-for-strands:latest
docker push <ACCOUNT>.dkr.ecr.us-west-2.amazonaws.com/sample-sop-agent-for-strands:latest
```

## Step 2: Create IAM Role for IRSA

```bash
# Create trust policy
cat > trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::<ACCOUNT>:oidc-provider/oidc.eks.us-west-2.amazonaws.com/id/<OIDC_ID>"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "oidc.eks.us-west-2.amazonaws.com/id/<OIDC_ID>:sub": "system:serviceaccount:default:sample-sop-agent-for-strands"
      }
    }
  }]
}
EOF

# Create role
aws iam create-role --role-name sample-sop-agent-for-strands-role --assume-role-policy-document file://trust-policy.json

# Attach Bedrock policy
cat > bedrock-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse", "bedrock:ConverseStream"],
    "Resource": ["arn:aws:bedrock:*::foundation-model/anthropic.*", "arn:aws:bedrock:*:*:inference-profile/*"]
  }]
}
EOF

aws iam put-role-policy --role-name sample-sop-agent-for-strands-role --policy-name BedrockAccess --policy-document file://bedrock-policy.json
```

## Step 3: Create Kubeconfig Secret (Multi-Cluster)

```bash
# Generate kubeconfig for each target cluster
aws eks update-kubeconfig --name vendor-a-cluster --region us-west-2 --kubeconfig /tmp/vendor-a.kubeconfig
aws eks update-kubeconfig --name vendor-b-cluster --region us-west-2 --kubeconfig /tmp/vendor-b.kubeconfig

# Merge into single config
KUBECONFIG=/tmp/vendor-a.kubeconfig:/tmp/vendor-b.kubeconfig kubectl config view --flatten > /tmp/merged-kubeconfig

# Create secret
kubectl create secret generic target-cluster-kubeconfigs --from-file=config=/tmp/merged-kubeconfig
```

## Step 4: Deploy with Helm

```bash
helm install sample-sop-agent-for-strands ./helm/sample-sop-agent-for-strands \
  --set image.repository=<ACCOUNT>.dkr.ecr.us-west-2.amazonaws.com/sample-sop-agent-for-strands \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=arn:aws:iam::<ACCOUNT>:role/sample-sop-agent-for-strands-role \
  --set kubeconfigs.enabled=true \
  --set kubeconfigs.secretName=target-cluster-kubeconfigs \
  --set ingress.enabled=true
```

## Step 5: Create CloudFront Distribution

```bash
# Get ALB DNS from ingress
ALB_DNS=$(kubectl get ingress sample-sop-agent-for-strands -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

# Create CloudFront distribution pointing to ALB
aws cloudfront create-distribution \
  --origin-domain-name $ALB_DNS \
  --default-root-object "" \
  --query 'Distribution.DomainName'
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `BEDROCK_REGION` | AWS region for Bedrock | `us-west-2` |
| `CORS_ORIGINS` | Allowed origins | `*` |
| `LOG_LEVEL` | Logging level | `INFO` |

## Switching Cluster Context in SOPs

SOPs can specify which cluster to target:

```markdown
### Step 1: Deploy to Vendor A cluster
```bash
kubectl --context vendor-a-cluster apply -f deployment.yaml
```

### Step 2: Verify on Vendor B cluster
```bash
kubectl --context vendor-b-cluster get pods -n nfv
```
```

## Troubleshooting

**Pod can't access Bedrock:**
- Verify IRSA annotation on ServiceAccount
- Check IAM role trust policy has correct OIDC provider

**Can't reach target clusters:**
- Verify kubeconfig secret is mounted
- Check network connectivity (VPC peering, security groups)

**ALB not provisioning:**
- Ensure AWS Load Balancer Controller is installed
- Check ingress annotations
