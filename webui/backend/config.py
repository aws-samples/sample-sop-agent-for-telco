# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Centralized configuration — all env vars in one place."""
import os

SOP_REPO = os.getenv("SOP_REPO", "/app")
BEDROCK_PROFILE = os.getenv("BEDROCK_PROFILE") or None  # None = use default credential chain
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-west-2")
BEDROCK_MODEL = os.getenv("BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-20250514-v1:0")
API_KEY = os.getenv("API_KEY", "")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
AMP_WORKSPACE_URL = os.getenv("AMP_WORKSPACE_URL", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SLACK_EXECUTION_WEBHOOK = os.getenv("SLACK_EXECUTION_WEBHOOK", "")
APP_NAMESPACE = os.getenv("APP_NAMESPACE", "default")
APP_SERVICE_LABEL = os.getenv("APP_SERVICE_LABEL", "app=demo")

# Basic Auth credentials (set via env vars for security)
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")  # Must be set in production
