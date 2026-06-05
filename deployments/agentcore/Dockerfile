# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# ARM64 container image for ANRA agent deployment to Amazon Bedrock AgentCore Runtime.
#
# Build:
#   docker buildx build --platform linux/arm64 \
#     -f deployments/agentcore/Dockerfile \
#     -t <ecr-uri>/bedrock-agentcore-anra-agent:latest \
#     --push .
#
# AgentCore Runtime requirement: ARM64 only.

FROM --platform=linux/arm64 python:3.11-slim-bookworm

# Build-time arg with a default for cache busting if needed
ARG BUILDKIT_INLINE_CACHE=1

# Install minimal OS dependencies. AgentCore tools (kubectl, AWS CLI, etc.)
# can be added here if the agent runs them in-process. For Phase 2+ we'd push
# tools out to Lambda Gateway targets and skip these.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install dependencies first (better Docker layer caching)
COPY deployments/agentcore/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        bedrock-agentcore \
        "strands-agents>=1.36.0" \
        "strands-agents-evals>=0.1.15" \
        "boto3>=1.34.0" \
        pyyaml \
        networkx \
        requests \
        aiofiles \
        pydantic \
        fastapi \
        uvicorn[standard]

# Copy the agent source. AgentCore expects entrypoint at /app/main.py per the
# direct-code spec; we mirror that for container deployment.
COPY deployments/agentcore/main.py /app/main.py
COPY agent/ /app/agent/
COPY sops/ /app/sops/
COPY alarm-references/ /app/alarm-references/
COPY anra-config.yaml /app/anra-config.yaml

# Make sure agent/ is importable from main.py without sys.path tricks
ENV PYTHONPATH=/app:/app/agent
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO
ENV SOP_REPO=/app

# AgentCore Runtime invokes the app on port 8080 with /invocations and /ping endpoints
EXPOSE 8080

# main.py exposes `app` (BedrockAgentCoreApp) which handles /invocations and /ping
CMD ["python3", "main.py"]
