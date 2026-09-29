# ═══════════════════════════════════════════════════════════════════════════════
# ANO Platform — Top-Level Makefile
#
# Workshop-v3 deploys one image as ANDA and ANRA; CloudFormation replaces ANPA.
# This Makefile handles platform lifecycle; platform/Makefile handles 5G NF workloads.
#
# Usage:
#   make demo                          # Full deploy on one cluster (PoC mode)
#   make deploy-mgmt                   # ANPA + ANDA on management cluster
#   make deploy-workload               # ANRA + monitoring on workload cluster
#   make build                         # Build + push container image
#   make status                        # Show all agent pods
#   make clean                         # Tear down agents + workloads
#
# Override variables:
#   make demo CLUSTER=my-cluster REGION=us-west-2 PROFILE=my-profile
# ═══════════════════════════════════════════════════════════════════════════════

PROFILE        ?= cse-dev-test
REGION         ?= us-west-1
ACCOUNT        ?= $(shell aws sts get-caller-identity --profile $(PROFILE) --query Account --output text 2>/dev/null)
ECR            ?= $(ACCOUNT).dkr.ecr.$(REGION).amazonaws.com
IMAGE          ?= $(ECR)/anra
TAG            ?= 0.2.0
CLUSTER        ?= arn:aws:eks:$(REGION):$(ACCOUNT):cluster/site-002-workload
K              ?= kubectl --context $(CLUSTER)
HELM           ?= helm --kube-context $(CLUSTER)

MGMT_CLUSTER   ?= $(CLUSTER)
WORK_CLUSTER   ?= $(CLUSTER)

NS_ANRA        ?= anra-system
NS_ANDA        ?= anda-system
NS_ANPA        ?= anpa-system

ARGOCD_ENABLED ?= false

CHART_ANRA     ?= helm-charts/anra
CHART_ANDA     ?= helm-charts/anda
CHART_ANPA     ?= helm-charts/anpa
CHART_COMMON   ?= helm-charts/anra-common

.PHONY: demo deploy-mgmt deploy-workload deploy-anra deploy-anda deploy-anpa \
        platform deploy-common monitoring build ecr-login status clean verify help \
        workshop-v3 workshop-v3-validate

demo: build platform deploy-common deploy-anda workload deploy-anra verify
deploy-mgmt: HELM = helm --kube-context $(MGMT_CLUSTER)
deploy-mgmt: K = kubectl --context $(MGMT_CLUSTER)
deploy-mgmt: platform deploy-common deploy-anda

deploy-workload: HELM = helm --kube-context $(WORK_CLUSTER)
deploy-workload: K = kubectl --context $(WORK_CLUSTER)
deploy-workload: platform deploy-common monitoring workload deploy-anra verify-anra

## Install shared platform (CRDs + namespace + config)
deploy-common:
	@echo "▶ Installing anra-common (shared platform)..."
	@$(HELM) upgrade --install anra-common $(CHART_COMMON) \
		--namespace $(NS_ANRA) --create-namespace \
		--wait --timeout 60s
	@echo "  ✅ anra-common installed"

platform: deploy-common

deploy-anra:
	$(HELM) upgrade --install anra $(CHART_ANRA) \
		--namespace $(NS_ANRA) --create-namespace \
		--set image.repository=$(IMAGE) --set image.tag=$(TAG) \
		--set agentRole=anra --set config.cluster.name=$(CLUSTER) \
		--set config.cluster.region=$(REGION) \
		--set monitoring.influxdbUrl=http://influxdb.$(NS_ANRA).svc:8086 \
		--set monitoring.alertmanagerUrl=http://alertmanager.$(NS_ANRA).svc:9093 \
		--wait --timeout 120s

deploy-anda:
	$(HELM) upgrade --install anda $(CHART_ANDA) \
		--namespace $(NS_ANDA) --create-namespace \
		--set image.repository=$(IMAGE) --set image.tag=$(TAG) \
		--set agentRole=anda --set argocd.enabled=$(ARGOCD_ENABLED) \
		--set validation.preflight.enabled=false \
		--wait --timeout 120s

deploy-anpa:
	$(HELM) upgrade --install anpa $(CHART_ANPA) \
		--namespace $(NS_ANPA) --create-namespace \
		--set image.repository=$(IMAGE) --set image.tag=$(TAG) \
		--set agentRole=anpa \
		--wait --timeout 120s

monitoring:
	$(MAKE) -C platform deploy-monitoring CLUSTER=$(CLUSTER) REGION=$(REGION) PROFILE=$(PROFILE)

workload:
	$(MAKE) -C platform deploy-core deploy-upf-and-smf deploy-subscriber deploy-ran deploy-ueransim \
		CLUSTER=$(CLUSTER) REGION=$(REGION) PROFILE=$(PROFILE)

build: ecr-login
	docker build -t ano-platform:$(TAG) .
	docker tag ano-platform:$(TAG) $(IMAGE):$(TAG)
	docker push $(IMAGE):$(TAG)

ecr-login:
	aws ecr get-login-password --region $(REGION) --profile $(PROFILE) | \
		docker login --username AWS --password-stdin $(ECR)

status:
	@for ns in $(NS_ANRA) $(NS_ANDA); do \
		echo "--- $$ns ---"; \
		$(K) get pods -n $$ns -o wide --no-headers 2>/dev/null || echo "  (namespace not found)"; \
	done

verify: verify-anra verify-anda

verify-anra:
	$(K) rollout status deployment/anra -n $(NS_ANRA) --timeout=60s

verify-anda:
	$(K) rollout status deployment/anda -n $(NS_ANDA) --timeout=60s

verify-anpa:
	$(K) rollout status deployment/anpa -n $(NS_ANPA) --timeout=60s

clean:
	@echo "▶ Tearing down ANO platform..."
	@$(HELM) uninstall anra -n $(NS_ANRA) 2>/dev/null || true
	@$(HELM) uninstall anda -n $(NS_ANDA) 2>/dev/null || true
	@$(HELM) uninstall anpa -n $(NS_ANPA) 2>/dev/null || true
	@$(HELM) uninstall anra-common -n $(NS_ANRA) 2>/dev/null || true
	@$(MAKE) -C platform clean CLUSTER=$(CLUSTER) REGION=$(REGION) PROFILE=$(PROFILE) 2>/dev/null || true
	@$(K) delete namespace $(NS_ANRA) $(NS_ANDA) $(NS_ANPA) --ignore-not-found --wait=false
	@echo "  ✅ Cleaned"

workshop-v3:
	@test "$(TAG)" != "latest" || (echo "TAG must be immutable, not latest" >&2; exit 1)
	AGENT_IMAGE_REPOSITORY=$(IMAGE) AGENT_IMAGE_TAG=$(TAG) \
		bash scripts/free5gc/00-run-all.sh

workshop-v3-validate:
	bash -n scripts/free5gc/*.sh tests/free5gc/run-tests.sh
	python -m json.tool configs/free5gc-monitoring/dashboards/free5gc-core-overview.json >/dev/null
	PYTHONPATH=src python -m pytest tests/test_workshop_v3.py tests/test_sops.py -q

help:
	@echo "Workshop-v3 — Free5GC Deployment Targets"
	@echo "  make workshop-v3      CloudFormation + Free5GC + monitoring + ANDA/ANRA"
	@echo "  make workshop-v3-validate  Validate v3 assets without creating AWS resources"
	@echo "  make deploy-workload  ANRA + monitoring + NFs on workload cluster"
	@echo "  make build            Build + push container image"
	@echo "  make status           Show agent pod status"
	@echo "  make clean            Tear down everything"
	@echo "Variables:"
	@echo "  CLUSTER=$(CLUSTER)  REGION=$(REGION)  PROFILE=$(PROFILE)"
	@echo "  IMAGE=$(IMAGE)  TAG=$(TAG)"
	@echo "  ARGOCD_ENABLED=$(ARGOCD_ENABLED)"
