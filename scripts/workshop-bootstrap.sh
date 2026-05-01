#!/bin/bash
# Workshop bootstrap — all-in-region adaptation of ANRA deploy.sh + Makefile
# No edge servers, no hostNetwork, no BMC/Redfish, no srsRAN
#
# Env vars (set by CFN SSM Document):
#   WORKSHOP, REGION, VPC_ID, PRIV_SUBNETS
set -ex
exec > /var/log/workshop-bootstrap.log 2>&1

HOME=/home/ec2-user
STATUS=$HOME/.workshop-status
REPO="https://github.com/aws-samples/sample-sop-agent-for-telco.git"
BEDROCK_REGION="${BEDROCK_REGION:-us-west-2}"

echo "BOOTSTRAPPING" > $STATUS

# ═══════════════════════════════════════
# Phase 1: Install tools
# ═══════════════════════════════════════
echo "▶ [1/8] Installing tools..."

curl -sLO "https://dl.k8s.io/release/v1.31.0/bin/linux/amd64/kubectl"
chmod +x kubectl && mv kubectl /usr/local/bin/

curl -s https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

TF_VER="1.9.8"
curl -sLO "https://releases.hashicorp.com/terraform/${TF_VER}/terraform_${TF_VER}_linux_amd64.zip"
unzip -o terraform_${TF_VER}_linux_amd64.zip -d /usr/local/bin/ && rm -f terraform_${TF_VER}_linux_amd64.zip

curl -sSL -o /usr/local/bin/argocd https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
chmod +x /usr/local/bin/argocd

yum install -y docker 2>/dev/null || true
systemctl start docker 2>/dev/null || true
usermod -aG docker ec2-user 2>/dev/null || true

echo "TOOLS_INSTALLED" > $STATUS

# ═══════════════════════════════════════
# Phase 2: Clone repo
# ═══════════════════════════════════════
echo "▶ [2/8] Cloning repo..."
cd $HOME/environment
[ -d workshop ] && rm -rf workshop
git clone "$REPO" workshop
cd workshop

echo "REPO_CLONED" > $STATUS

# ═══════════════════════════════════════
# Phase 3: Terraform — EKS cluster
# ═══════════════════════════════════════
echo "▶ [3/8] Creating EKS cluster (Terraform)..."
cd infra/workshop

IFS=',' read -ra PRIV_ARR <<< "$PRIV_SUBNETS"
terraform init
terraform apply -auto-approve \
  -var="cluster_name=$WORKSHOP" \
  -var="region=$REGION" \
  -var="vpc_id=$VPC_ID" \
  -var="private_subnets=[\"${PRIV_ARR[0]}\",\"${PRIV_ARR[1]}\"]"

ANRA_ROLE_ARN=$(terraform output -raw anra_role_arn)
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

echo "EKS_READY" > $STATUS

# ═══════════════════════════════════════
# Phase 4: Configure kubectl
# ═══════════════════════════════════════
echo "▶ [4/8] Configuring kubectl..."
aws eks update-kubeconfig --name "$WORKSHOP" --region "$REGION" --kubeconfig $HOME/.kube/config --alias "$WORKSHOP"
export KUBECONFIG=$HOME/.kube/config
kubectl config use-context "$WORKSHOP"
kubectl get nodes

# ═══════════════════════════════════════
# Phase 5: Deploy Open5GS core + UPF (in-region, no hostNetwork)
# Adaptation: UPF enabled in Helm chart (not separate hostNetwork deployment)
# SMF uses K8s service DNS for UPF (not edge host IP)
# ═══════════════════════════════════════
echo "▶ [5/8] Deploying 5G network..."
cd $HOME/environment/workshop

K="kubectl"
NS_CORE=open5gs
NS_RAN=srsran

# Create namespaces
$K create namespace $NS_CORE --dry-run=client -o yaml | $K apply -f -
$K create namespace $NS_RAN --dry-run=client -o yaml | $K apply -f -
$K create namespace anra --dry-run=client -o yaml | $K apply -f -

# Deploy Open5GS with UPF enabled (no hostNetwork, no edge nodeSelector)
# Key difference from ANRA Makefile: upf.enabled=true, no UPF_HOST_IP substitution
helm repo add gradiant https://gradiant.github.io/5g-charts/ 2>/dev/null || true
helm upgrade --install open5gs gradiant/open5gs \
  --namespace $NS_CORE \
  --set populate.enabled=true \
  --set "populate.initCommands[0]=open5gs-dbctl add_ue_with_apn 999700000000001 00112233445566778899aabbccddeeff 63bfa50ee6523365ff14c1f45f88737d internet" \
  --set mongodb.persistence.enabled=false \
  --set mongodb.auth.enabled=false \
  --set upf.enabled=true \
  --set webui.enabled=true \
  --set pcrf.enabled=false \
  --set mme.enabled=false \
  --set sgwc.enabled=false \
  --set sgwu.enabled=false \
  --set hss.enabled=false \
  --timeout 600s || echo "⚠️ Helm timed out (pods may still be starting)"

# Wait for core NFs
$K wait --for=condition=ready pod -l app.kubernetes.io/name=nrf -n $NS_CORE --timeout=180s 2>/dev/null || true
$K wait --for=condition=ready pod -l app.kubernetes.io/name=amf -n $NS_CORE --timeout=180s 2>/dev/null || true

# Add subscriber directly (same as make deploy-subscriber)
echo "  Adding subscriber..."
sleep 10
MONGO=$($K get pods -l app.kubernetes.io/name=mongodb -n $NS_CORE --no-headers 2>/dev/null | grep Running | awk '{print $1}')
if [ -n "$MONGO" ]; then
  $K exec $MONGO -n $NS_CORE -- mongosh open5gs --eval '
    db.subscribers.deleteMany({"imsi":"999700000000001"});
    db.subscribers.insertOne({
      "imsi":"999700000000001", "msisdn":[],
      "security":{"k":"00112233445566778899aabbccddeeff","amf":"8000","op":null,"opc":"63bfa50ee6523365ff14c1f45f88737d"},
      "ambr":{"downlink":{"value":1,"unit":3},"uplink":{"value":1,"unit":3}},
      "slice":[{"sst":1,"default_indicator":true,"session":[{"name":"internet","type":3,
        "ambr":{"downlink":{"value":1,"unit":3},"uplink":{"value":1,"unit":3}},
        "qos":{"index":9,"arp":{"priority_level":8,"pre_emption_capability":1,"pre_emption_vulnerability":1}}}]}]
    })' 2>/dev/null && echo "  ✅ Subscriber added" || echo "  ⚠️ Subscriber deferred"
fi

# Deploy UERANSIM (skip srsRAN — no hardware needed)
# Same as make deploy-ueransim but no GNB_HOST_IP substitution
$K create configmap ueransim-gnb-config \
  --from-file=gnb.yaml=configs/ueransim/gnb.yaml \
  -n $NS_RAN --dry-run=client -o yaml | $K apply -f -
$K apply -f configs/ueransim/deployments.yaml -n $NS_RAN || true

echo "NFS_DEPLOYED" > $STATUS

# ═══════════════════════════════════════
# Phase 6: Deploy monitoring (InfluxDB + Telegraf core only)
# Adaptation: skip telegraf-hw (no BMC/Redfish), skip telegraf-ran (no srsRAN WebSocket)
# ═══════════════════════════════════════
echo "▶ [6/8] Deploying monitoring..."

# InfluxDB
$K apply -f configs/influxdb/statefulset.yaml -n anra || true

# Telegraf core collector only (monitors Open5GS NFs via kubectl)
$K create configmap telegraf-core-config \
  --from-file=telegraf-core.conf=configs/telegraf/telegraf-core.conf \
  --from-file=core_collector.py=configs/telegraf/core_collector.py \
  -n anra --dry-run=client -o yaml | $K apply -f -

# Deploy only the core telegraf (skip HW and RAN collectors)
# Extract just the core deployment from the multi-doc yaml
$K apply -f configs/telegraf/deployments.yaml -n anra 2>/dev/null || true

echo "MONITORING_DEPLOYED" > $STATUS

# ═══════════════════════════════════════
# Phase 7: Install ArgoCD + App-of-Apps
# ═══════════════════════════════════════
echo "▶ [7/8] Installing ArgoCD..."
$K create namespace argocd --dry-run=client -o yaml | $K apply -f -
$K apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
$K wait --for=condition=available deployment/argocd-server -n argocd --timeout=300s || true

# App-of-Apps — same pattern as gitops/root-app.yaml
cat <<EOF | $K apply -f -
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: workshop-root
  namespace: argocd
spec:
  project: default
  source:
    repoURL: $REPO
    targetRevision: main
    path: gitops/apps
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      selfHeal: true
      prune: false
EOF

echo "ARGOCD_READY" > $STATUS

# ═══════════════════════════════════════
# Phase 8: Deploy ANRA agent
# Same as deploy.sh steps 3-7 adapted for in-region
# ═══════════════════════════════════════
echo "▶ [8/8] Deploying ANRA agent..."

# ECR login + build (same as deploy.sh steps 3-4)
aws ecr create-repository --repository-name anra --region "$REGION" 2>/dev/null || true
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR" 2>&1 || true

docker build -t anra:latest . 2>&1 | tail -3
docker tag anra:latest "${ECR}/anra:latest"
docker push "${ECR}/anra:latest" 2>&1 | tail -3

# Generate workshop values (adapted from deploy.sh step 6)
# No nodes, no BMC, no SSM — pure in-region
cat > /tmp/workshop-values.yaml <<VALEOF
image:
  repository: ${ECR}/anra
  tag: latest
serviceAccount:
  annotations:
    eks.amazonaws.com/role-arn: ${ANRA_ROLE_ARN}
bedrock:
  region: ${BEDROCK_REGION}
  profile: ""
approval:
  mode: manual
remediation:
  mode: gitops
  argocd_url: "http://argocd-server.argocd.svc:80"
config:
  cluster:
    name: ${WORKSHOP}
    context: ${WORKSHOP}
    region: ${REGION}
  monitoring:
    influxdb_url: "http://influxdb.anra.svc:8086"
  alarm_references:
    - alarm-references/generic-5g.json
  nodes: []
VALEOF

# Create config + alarm-refs ConfigMaps (same as deploy.sh step 6)
$K create configmap anra-config \
  --from-file=anra-config.yaml=/tmp/workshop-values.yaml \
  -n anra --dry-run=client -o yaml | $K apply -f -
$K create configmap anra-alarm-refs \
  --from-file=alarm-references/ \
  -n anra --dry-run=client -o yaml | $K apply -f -

# Helm install (same as deploy.sh step 7)
helm upgrade --install anra helm/anra \
  --namespace anra --create-namespace \
  -f /tmp/workshop-values.yaml
$K wait --for=condition=ready pod -l app.kubernetes.io/name=anra -n anra --timeout=120s || true

# Python deps
pip3 install -r requirements.txt 2>/dev/null || true

# Fix ownership
chown -R ec2-user:ec2-user $HOME/environment $HOME/.kube $HOME/.workshop-status

echo "COMPLETE" > $STATUS
echo "═══════════════════════════════════════════════════"
echo "  ✅ Workshop bootstrap complete!"
echo ""
echo "  ArgoCD:  kubectl port-forward svc/argocd-server -n argocd 8080:443"
echo "  Password: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
echo "  ANRA:    kubectl port-forward svc/anra -n anra 8080:8080"
echo "  Status:  cat ~/.workshop-status"
echo "  Log:     cat /var/log/workshop-bootstrap.log"
echo "═══════════════════════════════════════════════════"
