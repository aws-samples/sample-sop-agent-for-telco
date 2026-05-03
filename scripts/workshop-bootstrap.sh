#!/bin/bash
# Workshop bootstrap — all fixes baked in
# Env vars: WORKSHOP, REGION, VPC_ID, PRIV_SUBNETS (or PRIV_SUB_A, PRIV_SUB_B)
set -x
exec > /var/log/workshop-bootstrap.log 2>&1

HOME=/home/ec2-user
STATUS=$HOME/.workshop-status
REPO="https://github.com/aws-samples/sample-sop-agent-for-telco.git"
BEDROCK_REGION="${BEDROCK_REGION:-us-west-2}"

echo "BOOTSTRAPPING" > $STATUS

# ── Phase 1: Install tools + Python 3.11 ──
dnf install -y python3.11 python3.11-pip git docker unzip jq
systemctl enable docker && systemctl start docker
usermod -aG docker ec2-user

curl -sLO "https://dl.k8s.io/release/v1.31.0/bin/linux/amd64/kubectl"
chmod +x kubectl && mv kubectl /usr/local/bin/

curl -s https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

curl -sLO https://releases.hashicorp.com/terraform/1.9.8/terraform_1.9.8_linux_amd64.zip
unzip -o terraform_1.9.8_linux_amd64.zip -d /usr/local/bin/ && rm -f terraform_1.9.8_linux_amd64.zip

curl -sSL -o /usr/local/bin/argocd https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
chmod +x /usr/local/bin/argocd

echo "TOOLS_INSTALLED" > $STATUS

# ── Phase 2: Clone repo + install deps ──
mkdir -p $HOME/environment && cd $HOME/environment
git clone "$REPO" workshop
python3.11 -m pip install -r workshop/requirements.txt

echo "REPO_CLONED" > $STATUS

# ── Phase 3: Terraform — EKS cluster ──
cd workshop/infra/workshop
PRIV_SUB_A=${PRIV_SUB_A:-$(echo $PRIV_SUBNETS | cut -d, -f1)}
PRIV_SUB_B=${PRIV_SUB_B:-$(echo $PRIV_SUBNETS | cut -d, -f2)}
terraform init
terraform apply -auto-approve \
  -var="cluster_name=$WORKSHOP" \
  -var="region=$REGION" \
  -var="vpc_id=$VPC_ID" \
  -var="private_subnets=[\"$PRIV_SUB_A\",\"$PRIV_SUB_B\"]"

echo "EKS_READY" > $STATUS

# ── Phase 4: Configure kubectl + fix networking ──
aws eks update-kubeconfig --name "$WORKSHOP" --region "$REGION" --kubeconfig $HOME/.kube/config --alias "$WORKSHOP"
export KUBECONFIG=$HOME/.kube/config

# Fix /etc/hosts — VPC resolves EKS endpoint to private IPs
EKS_HOST=$(aws eks describe-cluster --name "$WORKSHOP" --region "$REGION" --query cluster.endpoint --output text | sed 's|https://||')
EKS_PUB_IP=$(nslookup $EKS_HOST 8.8.8.8 2>/dev/null | grep "Address:" | tail -1 | awk '{print $2}')
[ -n "$EKS_PUB_IP" ] && echo "$EKS_PUB_IP $EKS_HOST" >> /etc/hosts

kubectl get nodes

# Fix node SG — allow ALL intra-node traffic (UDP PFCP, GTP-U, ICMP, SCTP)
NODE_ID=$(kubectl get nodes -o jsonpath='{.items[0].spec.providerID}' | awk -F/ '{print $NF}')
NODE_SG=$(aws ec2 describe-instances --instance-ids $NODE_ID --region $REGION --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id $NODE_SG --protocol all --source-group $NODE_SG --region $REGION 2>/dev/null || true

echo "NETWORK_FIXED" > $STATUS

# ── Phase 5: Install ArgoCD ──
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml || true
kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=300s || true

echo "ARGOCD_READY" > $STATUS

# ── Phase 6: Create namespaces ──
for ns in open5gs srsran anra; do
  kubectl create namespace $ns --dry-run=client -o yaml | kubectl apply -f -
done

# ── Phase 7: Setup ec2-user environment ──
cat >> $HOME/.bashrc <<'BASHEOF'
export KUBECONFIG=$HOME/.kube/config
export PYTHONPATH=$HOME/environment/workshop/agent
alias sop="python3.11 -m agent.sop_executor --fix --yes"
alias k=kubectl
cd ~/environment/workshop
BASHEOF

chown -R ec2-user:ec2-user $HOME/environment $HOME/.kube $HOME/.bashrc $HOME/.workshop-status

echo "COMPLETE" > $STATUS
echo "Bootstrap complete!"
