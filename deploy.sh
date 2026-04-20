#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# deploy.sh - One-command deployment for Strands SOP Agent
# 
# Usage:
#   ./deploy.sh --cluster my-cluster --region us-west-2
#   ./deploy.sh --cluster my-cluster --profile my-aws-profile
#   ./deploy.sh --cluster my-cluster --dry-run

set -e

# Parse arguments
CLUSTER=""
REGION="us-west-2"
PROFILE=""
DRY_RUN=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --cluster) CLUSTER="$2"; shift 2 ;;
        --region) REGION="$2"; shift 2 ;;
        --profile) PROFILE="$2"; shift 2 ;;
        --dry-run) DRY_RUN="--dry-run"; shift ;;
        -h|--help)
            echo "Usage: ./deploy.sh --cluster CLUSTER_NAME [--region REGION] [--profile AWS_PROFILE] [--dry-run]"
            echo ""
            echo "Deploys the Strands SOP Agent to an EKS cluster."
            echo "The script will install any missing prerequisites automatically."
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ -z "$CLUSTER" ]; then
    echo "Error: --cluster is required"
    echo "Usage: ./deploy.sh --cluster CLUSTER_NAME [--region REGION] [--profile AWS_PROFILE]"
    exit 1
fi

echo "=============================================="
echo "Strands SOP Agent Deployment"
echo "=============================================="
echo "Cluster: $CLUSTER"
echo "Region:  $REGION"
[ -n "$PROFILE" ] && echo "Profile: $PROFILE"
echo ""

# Check Python3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    echo "Install Python 3 and try again."
    exit 1
fi

# Set AWS profile for commands
AWS_OPTS=""
[ -n "$PROFILE" ] && AWS_OPTS="--profile $PROFILE"

echo "Setting up prerequisites..."

# Step 1: Configure kubectl
echo "  Configuring kubectl..."
aws eks update-kubeconfig --name $CLUSTER --region $REGION $AWS_OPTS 2>/dev/null

# Step 2: Get account info
ACCOUNT_ID=$(aws sts get-caller-identity $AWS_OPTS --query Account --output text)
echo "  Account: $ACCOUNT_ID"

# Step 3: Setup OIDC provider for IRSA
echo "  Setting up OIDC provider..."
OIDC_URL=$(aws eks describe-cluster --name $CLUSTER --region $REGION $AWS_OPTS --query "cluster.identity.oidc.issuer" --output text)
OIDC_ID=$(echo $OIDC_URL | cut -d'/' -f5)

if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn arn:aws:iam::${ACCOUNT_ID}:oidc-provider/oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID} $AWS_OPTS 2>/dev/null; then
    echo "  Creating OIDC provider..."
    aws iam create-open-id-connect-provider \
        --url $OIDC_URL \
        --client-id-list sts.amazonaws.com \
        --thumbprint-list 9e99a48a9960b14926bb7f3b02e22da2b0ab7280 \
        $AWS_OPTS 2>/dev/null || true
fi

# Step 4: Create IAM role for Bedrock access
ROLE_NAME="sample-sop-agent-role"
echo "  Setting up IAM role ($ROLE_NAME)..."

if ! aws iam get-role --role-name $ROLE_NAME $AWS_OPTS 2>/dev/null; then
    cat > /tmp/trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {"StringEquals": {"oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}:sub": "system:serviceaccount:sop-agent:sample-sop-agent-for-strands"}}
  }]
}
EOF
    aws iam create-role --role-name $ROLE_NAME --assume-role-policy-document file:///tmp/trust-policy.json $AWS_OPTS
fi

# Step 5: Attach Bedrock permissions
echo "  Attaching Bedrock permissions..."
cat > /tmp/bedrock-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse", "bedrock:ConverseStream"],
    "Resource": ["arn:aws:bedrock:*::foundation-model/anthropic.*", "arn:aws:bedrock:*:*:inference-profile/*"]
  }]
}
EOF
aws iam put-role-policy --role-name $ROLE_NAME --policy-name BedrockAccess --policy-document file:///tmp/bedrock-policy.json $AWS_OPTS 2>/dev/null || true

# Step 6: Create ECR repo
echo "  Creating ECR repository..."
aws ecr create-repository --repository-name sample-sop-agent --region $REGION $AWS_OPTS 2>/dev/null || true

# Step 7: Build and push image
echo "  Building Docker image..."
ECR_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/sample-sop-agent"
aws ecr get-login-password --region $REGION $AWS_OPTS | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com 2>/dev/null
docker build -t sample-sop-agent:latest "$(dirname "$0")" 2>&1 | tail -3
docker tag sample-sop-agent:latest $ECR_URI:latest
echo "  Pushing to ECR..."
docker push $ECR_URI:latest 2>&1 | tail -3

# Step 8: Deploy with Helm
echo "  Deploying with Helm..."
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

# Generate random password for auth
AUTH_PASSWORD=$(openssl rand -base64 12)

helm upgrade --install sop-agent "$(dirname "$0")/helm/sample-sop-agent-for-strands" \
    --namespace sop-agent --create-namespace \
    --set image.repository=$ECR_URI \
    --set image.tag=latest \
    --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=$ROLE_ARN \
    --set env.AUTH_PASSWORD="$AUTH_PASSWORD" \
    --set service.type=LoadBalancer

echo ""
echo "=============================================="
echo "Deployment complete!"
echo "=============================================="
echo ""
echo "Waiting for LoadBalancer..."
sleep 10
LB_URL=$(kubectl get svc -n sop-agent sample-sop-agent-for-strands -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)
echo ""
echo "Access URL: http://$LB_URL:8000"
echo "Username:   admin"
echo "Password:   $AUTH_PASSWORD"
echo ""
echo "Note: LoadBalancer may take 2-3 minutes to become available."
