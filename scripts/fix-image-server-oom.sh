#!/bin/bash
# fix-image-server-oom.sh
# Patches the Tinkerbell image-server StatefulSet to increase memory limits
# for the s3-sync init container which OOMs on files >128Mi (OS images are ~1.3GB).
#
# This is a temporary workaround until the EKS-H team fixes the upstream chart.
#
# Usage: ./fix-image-server-oom.sh [namespace]

set -euo pipefail

NAMESPACE="${1:-tinkerbell}"
STATEFULSET="image-server"

echo "Patching ${STATEFULSET} in namespace ${NAMESPACE}..."
echo "  - Bumping s3-sync init container memory: 128Mi → 2Gi"
echo "  - Bumping s3-sync init container CPU: 100m → 500m"

# Patch the init container resource limits
# The s3-sync container downloads OS images from S3 into the shared PVC.
# Default 128Mi can't handle 1.3GB files — OOMKilled.
kubectl patch statefulset "${STATEFULSET}" -n "${NAMESPACE}" --type=json -p='[
  {
    "op": "replace",
    "path": "/spec/template/spec/initContainers/0/resources",
    "value": {
      "requests": {
        "cpu": "250m",
        "memory": "512Mi"
      },
      "limits": {
        "cpu": "500m",
        "memory": "2Gi"
      }
    }
  }
]'

echo "Patch applied. Restarting StatefulSet to pick up new limits..."
kubectl rollout restart statefulset "${STATEFULSET}" -n "${NAMESPACE}"
kubectl rollout status statefulset "${STATEFULSET}" -n "${NAMESPACE}" --timeout=300s

echo "Done. Image server pods will re-sync from S3 with adequate memory."
