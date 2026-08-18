# ─────────────────────────────────────────────────────────────────────────────
# ANO Platform — Multi-arch Container Image
# ─────────────────────────────────────────────────────────────────────────────
# Supports: linux/amd64 (EKS on EC2 / Hybrid Nodes) + linux/arm64 (Graviton / AgentCore)
# Build:    docker buildx build --platform linux/amd64,linux/arm64 -t $ECR/anra:$TAG --push .
# Default:  amd64 (set by TARGETARCH when --platform is omitted)
# ─────────────────────────────────────────────────────────────────────────────

# ─── Stage 1: Frontend build (architecture-independent) ───────────────────────
# Uses the SAME amazonlinux public-ECR base as the runtime stage. The pipeline's
# BATS DockerImage transform only accepts base images from ECR registries it can
# authenticate to (private ECR, or verified public namespaces like
# public.ecr.aws/amazonlinux) — it rejects the Docker Hub mirror
# (public.ecr.aws/docker/library/*) with UnsupportedDockerRegistryError.
# Node is installed from the AL2023 repos (nodejs20) instead of a node base image.
FROM public.ecr.aws/amazonlinux/amazonlinux:2023@sha256:df9ca26898d7c01be79e7c84bd008d5c8c867ace2c736421d150179f0aa87c33 AS frontend
RUN dnf install -y nodejs20 npm && dnf clean all
WORKDIR /app/webui/frontend
COPY webui/frontend/package.json webui/frontend/package-lock.json ./
RUN npm ci --prefer-offline
COPY webui/frontend/ ./
RUN npm run build

# ─── Stage 2: Runtime image ──────────────────────────────────────────────────
# Pinned by manifest-list digest for reproducibility (buildx resolves the
# per-arch image from the list). Refresh:
#   TOKEN=$(curl -s "https://public.ecr.aws/token/?scope=repository:amazonlinux/amazonlinux:pull" | jq -r .token)
#   curl -sI -H "Authorization: Bearer $TOKEN" \
#     -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json" \
#     https://public.ecr.aws/v2/amazonlinux/amazonlinux/manifests/2023 | grep -i docker-content-digest
FROM public.ecr.aws/amazonlinux/amazonlinux:2023@sha256:df9ca26898d7c01be79e7c84bd008d5c8c867ace2c736421d150179f0aa87c33

# Multi-arch: TARGETARCH is set automatically by docker buildx (amd64 or arm64)
ARG TARGETARCH=amd64

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System packages: Python 3.11, shadow-utils (useradd), curl, jq, tar, awscli v2
# awscli-2: vended by AL2023 dnf (signed RPM from Amazon repos) — not a third-party download.
RUN dnf install -y \
        python3.11 python3.11-pip shadow-utils \
        jq tar gzip \
        awscli-2 \
    && dnf clean all \
    && ln -s /usr/bin/python3.11 /usr/local/bin/python

# ─── Runtime tools (kubectl, helm, aws CLI) ───────────────────────────────────
# These are required by the agent's subprocess calls (reconciler, orchestrator, tools)

# kubectl — arch-aware binary, verified against the official published SHA256
ARG KUBECTL_VERSION=v1.31.4
RUN curl -sLo /usr/local/bin/kubectl \
        "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl" \
    && curl -sL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl.sha256" -o /tmp/kubectl.sha256 \
    && echo "$(cat /tmp/kubectl.sha256)  /usr/local/bin/kubectl" | sha256sum --check - \
    && chmod +x /usr/local/bin/kubectl \
    && rm -f /tmp/kubectl.sha256

# helm — pinned binary download (arch-aware)
# @secure_recommendation: helm 3.16.4 is required for the OCI Chart.lock semantics this
# codebase uses; the closest Brazil third-party package (Go3p-Github-Helm-Helm-V3) is
# Go-source-only and version-locked at 3.5.x. Migration to Brazil-vended tooling
# requires multi-stage Dockerfile + Go3p version-uplift contribution and is tracked
# under SIM https://t.corp.amazon.com/P452595207. This change strictly improves the
# previously-merged unpinned `curl … | bash` GitHub-raw pattern by pinning HELM_VERSION
# and downloading from the official helm distribution endpoint.
ARG HELM_VERSION=3.16.4
# crux-ignore: External3PDownload
RUN curl -fsSL https://get.helm.sh/helm-v${HELM_VERSION}-linux-${TARGETARCH}.tar.gz | tar xz -C /tmp \
    && mv /tmp/linux-${TARGETARCH}/helm /usr/local/bin/helm \
    && rm -rf /tmp/linux-${TARGETARCH}

# aws CLI v2 — installed via AL2023 dnf above (`awscli-2` package). The CLI
# binary is at /usr/bin/aws — no third-party download needed.

# ─── Python application ──────────────────────────────────────────────────────
# Install the package via pyproject.toml [project].dependencies
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN python -m pip install --quiet /app

# ─── Runtime assets ──────────────────────────────────────────────────────────
# The agent reads these at /app/<dir>/ relative to WORKDIR.
# configs/influxdb and configs/telegraf are EXCLUDED — they contain lab
# credentials and belong in Helm chart values, not baked into the image.
COPY configs/alertmanager /app/configs/alertmanager
COPY configs/nf-profiles /app/configs/nf-profiles
COPY configs/open5gs /app/configs/open5gs
COPY configs/site-descriptors /app/configs/site-descriptors
COPY configs/srsran /app/configs/srsran
COPY configs/ueransim /app/configs/ueransim
COPY sops /app/sops
COPY alarm-references /app/alarm-references
COPY evals /app/evals
COPY examples /app/examples
COPY gitops /app/gitops
COPY infra /app/infra

# ─── Frontend static files (from Stage 1) ────────────────────────────────────
COPY --from=frontend /app/webui/frontend/dist /app/static
# Tell the app exactly where the built WebUI lives (see agent/api.py static
# resolution). Keeps serving independent of the Python/install layout.
ENV STATIC_DIR=/app/static

# ─── Security: Non-root runtime ──────────────────────────────────────────────
RUN useradd --system --uid 10001 --no-create-home --shell /sbin/nologin app \
    && chown -R app:app /app
USER app

# ─── Runtime configuration ───────────────────────────────────────────────────
# Default role; overridden per Helm deployment (ANPA/ANDA/ANRA).
ENV AGENT_ROLE=anra

EXPOSE 8080
CMD ["python", "-m", "amzn_cse_telco_autonomous_network_agents_app.agent.entrypoint"]
