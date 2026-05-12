FROM node:18-alpine AS frontend
WORKDIR /app/webui/frontend
COPY webui/frontend/package.json .
RUN npm install
COPY webui/frontend/ .
RUN npm run build

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip && \
    curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && mv kubectl /usr/local/bin/ && \
    curl -sSL -o /usr/local/bin/argocd https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64 && \
    chmod +x /usr/local/bin/argocd && \
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscli.zip && \
    unzip -q awscli.zip && ./aws/install && rm -rf awscli.zip aws && \
    apt-get purge -y unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY entrypoint.py .
COPY agent/ ./agent/
COPY sops/ ./sops/
COPY alarm-references/ ./alarm-references/
COPY evals/ ./evals/

# Copy built frontend
COPY --from=frontend /app/webui/frontend/dist ./static/

EXPOSE 8080

CMD ["python3", "entrypoint.py"]
