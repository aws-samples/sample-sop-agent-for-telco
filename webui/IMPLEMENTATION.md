# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# SOP Agent - Implementation Summary

## Overview
A full-stack web application for managing and executing Standard Operating Procedures (SOPs) for Kubernetes deployments, with real-time monitoring and AI-powered assistance.

## Architecture

### Backend (FastAPI - Python)
**File:** `backend/api.py`

#### Core Components

1. **SOP Management**
   - List, view, create, and edit SOPs stored as Markdown files
   - File-based storage in configurable SOP repository
   - REST endpoints: `/api/sops`, `/api/sop/{name}`

2. **Metrics Collection** (`/api/metrics`)
   - Supports AWS Managed Prometheus (AMP) or in-cluster Prometheus
   - Authentication: SigV4 signing with IAM role
   - Configurable metrics queries

3. **Alarm Management** (`/api/alarms`)
   - Integration with Alertmanager
   - Priority-based filtering

4. **AI Chat Integration** (`/api/chat`, `/ws/chat`)
   - WebSocket-based communication
   - Integrates with Amazon Bedrock for AI assistance

5. **SOP Execution** (`/ws/execute`)
   - WebSocket streaming of execution logs
   - Real-time progress updates
   - Supports multiple execution modes

### Frontend (React + Vite)
**File:** `frontend/src/App.jsx`

#### Key Features

1. **Dashboard Layout**
   - Three-column responsive design
   - SOP list and execution controls
   - Live metrics and alarms

2. **Real-Time Metrics Visualization**
   - Configurable metric graphs
   - Auto-refresh capability
   - Rolling time window display

3. **SOP Management**
   - Markdown editor with syntax highlighting
   - View/Edit mode toggle
   - Create new SOPs

4. **AI Chat Assistant**
   - WebSocket-based streaming responses
   - Context-aware about SOPs and system status

#### Technology Stack
- React 18 with Hooks
- Recharts for data visualization
- Lucide React for icons
- Tailwind CSS for styling
- WebSocket for real-time communication

## Data Flow

### Metrics Pipeline
```
Application Pods → Prometheus → AMP (optional) → Backend API → Frontend
```

### SOP Execution Flow
```
User → Frontend → WebSocket → Backend → sop_executor.py → Kubernetes
                                ↓
                         Real-time logs streamed back
```

## Security Considerations
- ServiceAccount-based RBAC for Kubernetes access
- IAM role-based credentials for AWS services
- Input validation on all API endpoints
- Read-only kubectl commands in chat interface

## Deployment
- **Backend:** Python FastAPI on port 8000
- **Frontend:** Vite dev server (production: static build served by FastAPI)
- **Container:** Single Docker image with both frontend and backend

## Configuration
See `config.py` for environment variables:
- `SOP_REPO`: Path to SOP repository
- `BEDROCK_MODEL`: Amazon Bedrock model ID
- `AMP_WORKSPACE_URL`: AWS Managed Prometheus endpoint (optional)
