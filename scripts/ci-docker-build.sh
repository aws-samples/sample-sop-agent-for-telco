#!/bin/bash
# CI Step: Build Docker image and push to ECR
# Runs in Pipeline account (187692046528); CSE Dev nodes pull cross-account.
set -euo pipefail

ECR_REGISTRY="187692046528.dkr.ecr.us-west-1.amazonaws.com"
ECR_REPO="telco-ana"
IMAGE_TAG="${CODEBUILD_RESOLVED_SOURCE_VERSION:0:8}"
IMAGE_URI="${ECR_REGISTRY}/${ECR_REPO}"

echo "▶ Logging in to ECR..."
aws ecr get-login-password --region us-west-1 | docker login --username AWS --password-stdin "$ECR_REGISTRY"

echo "▶ Building image: ${IMAGE_URI}:${IMAGE_TAG}"
docker build -t "${IMAGE_URI}:${IMAGE_TAG}" -f Dockerfile .

echo "▶ Pushing to ECR..."
docker push "${IMAGE_URI}:${IMAGE_TAG}"

echo "✅ Image pushed: ${IMAGE_URI}:${IMAGE_TAG}"
