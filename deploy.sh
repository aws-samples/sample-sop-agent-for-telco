#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# deploy.sh - One-command deployment for Strands SOP Agent
# 
# Usage:
#   ./deploy.sh --cluster my-cluster --region us-west-2
#   ./deploy.sh --cluster my-cluster --profile my-aws-profile
#   ./deploy.sh --cluster my-cluster --dry-run

set -e

# Parse arguments
CLUSTER=""
REGION="us-west-2"
PROFILE=""
DRY_RUN=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --cluster) CLUSTER="$2"; shift 2 ;;
        --region) REGION="$2"; shift 2 ;;
        --profile) PROFILE="$2"; shift 2 ;;
        --dry-run) DRY_RUN="--dry-run"; shift ;;
        -h|--help)
            echo "Usage: ./deploy.sh --cluster CLUSTER_NAME [--region REGION] [--profile AWS_PROFILE] [--dry-run]"
            echo ""
            echo "Deploys the Strands SOP Agent to an EKS cluster."
            echo "The script will install any missing prerequisites automatically."
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ -z "$CLUSTER" ]; then
    echo "Error: --cluster is required"
    echo "Usage: ./deploy.sh --cluster CLUSTER_NAME [--region REGION] [--profile AWS_PROFILE]"
    exit 1
fi

echo "=============================================="
echo "Strands SOP Agent Deployment"
echo "=============================================="
echo "Cluster: $CLUSTER"
echo "Region:  $REGION"
[ -n "$PROFILE" ] && echo "Profile: $PROFILE"
echo ""

# Check Python3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    echo "Install Python 3 and try again."
    exit 1
fi

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install -q strands-agents boto3 2>/dev/null || pip install -q strands-agents boto3

# Build bootstrap args
ARGS="--cluster $CLUSTER --region $REGION"
[ -n "$PROFILE" ] && ARGS="$ARGS --profile $PROFILE"
[ -n "$DRY_RUN" ] && ARGS="$ARGS $DRY_RUN"

# Run bootstrap
echo "Starting deployment agent..."
echo ""
python3 "$(dirname "$0")/bootstrap.py" $ARGS
