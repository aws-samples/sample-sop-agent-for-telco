# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Use ECR public images to comply with AWS samples requirements
FROM public.ecr.aws/docker/library/node:20-slim AS frontend-build
WORKDIR /app/webui/frontend
COPY webui/frontend/package*.json ./
RUN npm ci
COPY webui/frontend/ ./
RUN npx vite build

FROM public.ecr.aws/docker/library/python:3.11-slim
WORKDIR /app

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

# System deps + tini (reaps zombie child processes)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl openssh-client git tini \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install kubectl + AWS CLI
RUN curl -LO "https://dl.k8s.io/release/v1.32.0/bin/linux/amd64/kubectl" \
    && chmod +x kubectl && mv kubectl /usr/local/bin/ \
    && curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip \
    && apt-get update && apt-get install -y --no-install-recommends unzip \
    && unzip awscliv2.zip && ./aws/install && rm -rf awscliv2.zip aws \
    && apt-get remove -y unzip && apt-get autoremove -y \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY --chown=appuser:appuser webui/backend/ webui/backend/
COPY --chown=appuser:appuser sop-agent/ sop-agent/
COPY --chown=appuser:appuser evals/ evals/
COPY --chown=appuser:appuser sops/ sops/
COPY --chown=appuser:appuser scripts/ scripts/
COPY --chown=appuser:appuser day2-monitor/ day2-monitor/
COPY --from=frontend-build --chown=appuser:appuser /app/webui/frontend/dist webui/frontend/dist

# Serve frontend static files from FastAPI
RUN pip install --no-cache-dir aiofiles

# Create logs directory with proper permissions
RUN mkdir -p /app/logs && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

WORKDIR /app/webui/backend
ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
