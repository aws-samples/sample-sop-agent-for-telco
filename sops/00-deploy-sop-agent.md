# Deploy SOP Agent to EKS

## Overview
Deploy the Strands SOP Agent to an EKS cluster with CloudFront CDN.

## Parameters
- `CLUSTER_NAME`: Target EKS cluster (e.g., `my-eks-cluster`) - passed via environment
- `AWS_REGION`: AWS region (e.g., `us-west-2`) - passed via environment

---

## Phase 1: Prerequisites

### Step 1.1: Verify AWS CLI
```bash
aws --version && aws sts get-caller-identity --query Account --output text
```
**Expected**: AWS CLI version and 12-digit account ID  
**If missing**: Install AWS CLI:
- macOS: `brew install awscli`
- Linux: `curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && unzip awscliv2.zip && sudo ./aws/install`

### Step 1.2: Verify kubectl
```bash
kubectl version --client 2>/dev/null | head -1
```
**Expected**: kubectl version output  
**If missing**:
- macOS: `brew install kubectl`
- Linux: `curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && chmod +x kubectl && sudo mv kubectl /usr/local/bin/`

### Step 1.3: Verify Helm
```bash
helm version --short
```
**Expected**: Helm version (v3.x)  
**If missing**:
- macOS: `brew install helm`
- Linux: `curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash`

### Step 1.4: Verify Docker
```bash
docker info --format '{{.ServerVersion}}' 2>/dev/null || docker --version
```
**Expected**: Docker version  
**If not running**: Start Docker Desktop or `sudo systemctl start docker`

---

## Phase 2: Cluster Setup

### Step 2.1: Check cluster exists
```bash
aws eks describe-cluster --name $CLUSTER_NAME --region $AWS_REGION --query 'cluster.status' --output text
```
**Expected**: `ACTIVE`  
**If not found**: Cluster must exist first.

### Step 2.2: Configure kubectl and check nodes
```bash
aws eks update-kubeconfig --name $CLUSTER_NAME --region $AWS_REGION
kubectl get nodes
```
**Expected**: At least 1 node in Ready state  
**If no nodes**: Run Step 2.3

### Step 2.3: Create node group (only if no nodes)
```bash
# Check if node role exists, create if not
if ! aws iam get-role --role-name eksNodeRole 2>/dev/null; then
  echo "Creating eksNodeRole..."
  aws iam create-role --role-name eksNodeRole --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
  aws iam attach-role-policy --role-name eksNodeRole --policy-arn arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy
  aws iam attach-role-policy --role-name eksNodeRole --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
  aws iam attach-role-policy --role-name eksNodeRole --policy-arn arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy
fi

# Check if node group already exists
if aws eks describe-nodegroup --cluster-name $CLUSTER_NAME --nodegroup-name sop-agent-nodes --region $AWS_REGION 2>/dev/null; then
  echo "Node group already exists"
else
  ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
  SUBNETS=$(aws eks describe-cluster --name $CLUSTER_NAME --region $AWS_REGION --query 'cluster.resourcesVpcConfig.subnetIds[0:2]' --output text)
  
  aws eks create-nodegroup --cluster-name $CLUSTER_NAME --region $AWS_REGION --nodegroup-name sop-agent-nodes \
    --node-role arn:aws:iam::${ACCOUNT_ID}:role/eksNodeRole \
    --subnets $SUBNETS --instance-types t3.medium \
    --scaling-config minSize=1,maxSize=2,desiredSize=1
  
  echo "Waiting for node group (3-5 minutes)..."
  aws eks wait nodegroup-active --cluster-name $CLUSTER_NAME --region $AWS_REGION --nodegroup-name sop-agent-nodes
fi

kubectl get nodes
```
**Expected**: Node in Ready state

---

## Phase 3: Build and Push Image

### Step 3.1: Create ECR repository and login
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr create-repository --repository-name sample-sop-agent-for-strands --region $AWS_REGION 2>/dev/null || echo "Repository exists"
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```
**Expected**: "Login Succeeded"

### Step 3.2: Build and push Docker image
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
docker build -t sample-sop-agent-for-strands .
docker tag sample-sop-agent-for-strands:latest $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/sample-sop-agent-for-strands:latest
docker push $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/sample-sop-agent-for-strands:latest
```
**Expected**: Image pushed successfully

---

## Phase 4: IAM Setup for IRSA

### Step 4.1: Create OIDC provider (if not exists)
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
OIDC_URL=$(aws eks describe-cluster --name $CLUSTER_NAME --region $AWS_REGION --query "cluster.identity.oidc.issuer" --output text)
OIDC_ID=$(echo $OIDC_URL | cut -d'/' -f5)

# Check if OIDC provider exists
if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn arn:aws:iam::${ACCOUNT_ID}:oidc-provider/oidc.eks.${AWS_REGION}.amazonaws.com/id/${OIDC_ID} 2>/dev/null; then
  echo "Creating OIDC provider..."
  eksctl utils associate-iam-oidc-provider --cluster $CLUSTER_NAME --region $AWS_REGION --approve 2>/dev/null || \
  aws iam create-open-id-connect-provider \
    --url $OIDC_URL \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 9e99a48a9960b14926bb7f3b02e22da2b0ab7280
fi
echo "OIDC ID: $OIDC_ID"
```
**Expected**: OIDC provider exists or created

### Step 4.2: Create IAM role for service account
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
OIDC_ID=$(aws eks describe-cluster --name $CLUSTER_NAME --region $AWS_REGION --query "cluster.identity.oidc.issuer" --output text | cut -d'/' -f5)

# Check if role exists
if aws iam get-role --role-name sample-sop-agent-for-strands-role 2>/dev/null; then
  echo "Role already exists"
else
  cat > /tmp/trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/oidc.eks.${AWS_REGION}.amazonaws.com/id/${OIDC_ID}"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {"StringEquals": {"oidc.eks.${AWS_REGION}.amazonaws.com/id/${OIDC_ID}:sub": "system:serviceaccount:default:sample-sop-agent-for-strands"}}
  }]
}
EOF
  aws iam create-role --role-name sample-sop-agent-for-strands-role --assume-role-policy-document file:///tmp/trust-policy.json
fi
```
**Expected**: Role exists or created

### Step 4.3: Attach Bedrock permissions
```bash
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
aws iam put-role-policy --role-name sample-sop-agent-for-strands-role --policy-name BedrockAccess --policy-document file:///tmp/bedrock-policy.json
echo "Bedrock permissions attached"
```
**Expected**: Policy attached

---

## Phase 5: Deploy Application

### Step 5.1: Deploy with Helm
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
helm upgrade --install sample-sop-agent-for-strands ./helm/sample-sop-agent-for-strands \
  --set image.repository=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/sample-sop-agent-for-strands \
  --set image.tag=latest \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=arn:aws:iam::$ACCOUNT_ID:role/sample-sop-agent-for-strands-role \
  --set service.type=LoadBalancer
```
**Expected**: Release deployed

### Step 5.2: Wait for deployment
```bash
kubectl rollout status deployment/sample-sop-agent-for-strands --timeout=180s
```
**Expected**: "successfully rolled out"

### Step 5.3: Wait for LoadBalancer
```bash
echo "Waiting for LoadBalancer (1-3 minutes)..."
for i in {1..30}; do
  LB_HOST=$(kubectl get svc sample-sop-agent-for-strands -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)
  if [ -n "$LB_HOST" ]; then
    echo "LoadBalancer ready: $LB_HOST"
    break
  fi
  echo "  waiting... ($i/30)"
  sleep 10
done

if [ -z "$LB_HOST" ]; then
  echo "ERROR: LoadBalancer not ready after 5 minutes"
  kubectl describe svc sample-sop-agent-for-strands
fi
```
**Expected**: ELB hostname

### Step 5.4: Test LoadBalancer health
```bash
LB_HOST=$(kubectl get svc sample-sop-agent-for-strands -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
echo "Waiting for ELB to be healthy..."
for i in {1..12}; do
  if curl -s --max-time 5 http://$LB_HOST:8000/health | grep -q ok; then
    echo "LoadBalancer healthy!"
    curl -s http://$LB_HOST:8000/health
    break
  fi
  echo "  waiting for health check... ($i/12)"
  sleep 10
done
```
**Expected**: `{"status":"ok"}`

---

## Phase 6: CloudFront Setup

### Step 6.1: Create CloudFront distribution
```bash
LB_HOST=$(kubectl get svc sample-sop-agent-for-strands -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

# Check if distribution already exists
EXISTING_CF=$(aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='SOP Agent CDN'].DomainName" --output text 2>/dev/null)
if [ -n "$EXISTING_CF" ]; then
  echo "CloudFront already exists: https://$EXISTING_CF"
else
  CALLER_REF="sop-agent-$(date +%s)"
  
  cat > /tmp/cf-config.json << EOF
{
  "CallerReference": "${CALLER_REF}",
  "Comment": "SOP Agent CDN",
  "Enabled": true,
  "Origins": {
    "Quantity": 1,
    "Items": [{
      "Id": "sop-agent-origin",
      "DomainName": "${LB_HOST}",
      "CustomOriginConfig": {
        "HTTPPort": 8000,
        "HTTPSPort": 443,
        "OriginProtocolPolicy": "http-only"
      }
    }]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "sop-agent-origin",
    "ViewerProtocolPolicy": "redirect-to-https",
    "AllowedMethods": {"Quantity": 7, "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"], "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}},
    "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
    "OriginRequestPolicyId": "216adef6-5c7f-47e4-b989-5492eafa07d3",
    "Compress": true
  }
}
EOF

  aws cloudfront create-distribution --distribution-config file:///tmp/cf-config.json --query 'Distribution.{Id:Id,DomainName:DomainName}' --output table
fi
```
**Expected**: CloudFront distribution created or exists

### Step 6.2: Wait for CloudFront deployment
```bash
CF_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='SOP Agent CDN'].Id" --output text | head -1)
CF_DOMAIN=$(aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='SOP Agent CDN'].DomainName" --output text | head -1)
echo "CloudFront ID: $CF_ID"
echo "CloudFront Domain: $CF_DOMAIN"
echo ""
echo "Waiting for CloudFront deployment (this can take 5-10 minutes)..."
echo "You can proceed - CloudFront will work once deployed."
aws cloudfront wait distribution-deployed --id $CF_ID 2>/dev/null &
```
**Expected**: CloudFront deploying

---

## Phase 7: Verification

### Step 7.1: Test via LoadBalancer
```bash
LB_HOST=$(kubectl get svc sample-sop-agent-for-strands -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
echo "Testing: http://$LB_HOST:8000/health"
curl -s http://$LB_HOST:8000/health
echo ""
echo "Testing: http://$LB_HOST:8000/api/sops"
curl -s http://$LB_HOST:8000/api/sops | head -c 300
```
**Expected**: Health OK and SOPs list

### Step 7.2: Test via CloudFront (may take a few minutes)
```bash
CF_DOMAIN=$(aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='SOP Agent CDN'].DomainName" --output text | head -1)
echo "Testing: https://$CF_DOMAIN/health"
curl -s --max-time 10 https://$CF_DOMAIN/health || echo "(CloudFront may still be deploying)"
```
**Expected**: `{"status":"ok"}` (or deploying message)

---

## Success Summary
```bash
LB_HOST=$(kubectl get svc sample-sop-agent-for-strands -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
CF_DOMAIN=$(aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='SOP Agent CDN'].DomainName" --output text | head -1)
echo ""
echo "=========================================="
echo "  SOP Agent Deployed Successfully!"
echo "=========================================="
echo ""
echo "LoadBalancer (immediate):"
echo "  http://$LB_HOST:8000"
echo ""
echo "CloudFront (HTTPS, may take 5-10 min):"
echo "  https://$CF_DOMAIN"
echo ""
echo "=========================================="
```

---

## Troubleshooting
- **Pod pending**: `kubectl describe pod -l app=sample-sop-agent-for-strands` - check node/resource issues
- **ImagePullBackOff**: Verify ECR image exists: `aws ecr describe-images --repository-name sample-sop-agent-for-strands`
- **CrashLoopBackOff**: Check logs: `kubectl logs -l app=sample-sop-agent-for-strands`
- **No LoadBalancer IP**: Cluster subnets may not have internet gateway
- **CloudFront 502**: Origin not healthy yet - wait for ELB health checks
- **OIDC errors**: Run `eksctl utils associate-iam-oidc-provider --cluster $CLUSTER_NAME --approve`
