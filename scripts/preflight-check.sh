#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# Pre-flight check for ANRA workshop.

set +e
PASS="✅"
FAIL="❌"
WARN="⚠️ "
ERRORS=0
WARNINGS=0

echo "════════════════════════════════════════════════"
echo "  ANRA Workshop — Pre-flight Check"
echo "  $(date)"
echo "════════════════════════════════════════════════"

check() {
    local name="$1"; shift
    if eval "$*" >/dev/null 2>&1; then
        echo "$PASS $name"
    else
        echo "$FAIL $name"
        ERRORS=$((ERRORS + 1))
    fi
}

warn_check() {
    local name="$1"; shift
    if eval "$*" >/dev/null 2>&1; then
        echo "$PASS $name"
    else
        echo "$WARN $name"
        WARNINGS=$((WARNINGS + 1))
    fi
}

# AWS credentials
check "AWS credentials configured" "aws sts get-caller-identity"
check "Region us-west-2 reachable" "aws ec2 describe-regions --region us-west-2"

# Bedrock model access
check "Bedrock available in us-west-2" "aws bedrock list-foundation-models --region us-west-2"

# EKS cluster ready
if kubectl config current-context >/dev/null 2>&1; then
    check "EKS cluster Ready" "kubectl get nodes | grep -q Ready"
    check "All system pods Running" "! kubectl get pods -A | grep -E 'Pending|CrashLoopBackOff'"
else
    echo "$FAIL kubectl context not set"
    ERRORS=$((ERRORS + 1))
fi

# Required tools
check "kubectl installed" "command -v kubectl"
check "helm installed" "command -v helm"

# Network reachability
warn_check "ECR Public reachable" "curl -sI --max-time 5 https://public.ecr.aws | head -1 | grep -q HTTP"
warn_check "Bedrock endpoint reachable" "curl -sI --max-time 5 https://bedrock-runtime.us-west-2.amazonaws.com | head -1 | grep -q HTTP"

echo ""
echo "════════════════════════════════════════════════"
if [[ $ERRORS -eq 0 && $WARNINGS -eq 0 ]]; then
    echo "$PASS All checks passed — you're ready to start"
    exit 0
elif [[ $ERRORS -eq 0 ]]; then
    echo "$WARN $WARNINGS warnings — workshop may work but watch for issues"
    exit 0
else
    echo "$FAIL $ERRORS errors — STOP and fix these before starting"
    exit 1
fi
