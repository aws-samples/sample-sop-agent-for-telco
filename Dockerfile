# Use ECR public images to comply with AWS samples requirements
FROM public.ecr.aws/docker/library/node:20-slim AS frontend-build
WORKDIR /app/webui/frontend
COPY webui/frontend/package*.json ./
RUN npm ci
COPY webui/frontend/ ./
RUN npx vite build

FROM public.ecr.aws/docker/library/python:3.11-slim
WORKDIR /app

# System deps + tini (reaps zombie child processes)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl openssh-client git tini && rm -rf /var/lib/apt/lists/*

# Install kubectl + AWS CLI
RUN curl -LO "https://dl.k8s.io/release/v1.32.0/bin/linux/amd64/kubectl" \
    && chmod +x kubectl && mv kubectl /usr/local/bin/ \
    && curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip \
    && apt-get update && apt-get install -y --no-install-recommends unzip \
    && unzip awscliv2.zip && ./aws/install && rm -rf awscliv2.zip aws \
    && apt-get remove -y unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY webui/backend/ webui/backend/
COPY sop-agent/ sop-agent/
COPY evals/ evals/
COPY sops/ sops/
COPY scripts/ scripts/
COPY day2-monitor/ day2-monitor/
COPY --from=frontend-build /app/webui/frontend/dist webui/frontend/dist

# Serve frontend static files from FastAPI
RUN pip install --no-cache-dir aiofiles

EXPOSE 8000

WORKDIR /app/webui/backend
ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
