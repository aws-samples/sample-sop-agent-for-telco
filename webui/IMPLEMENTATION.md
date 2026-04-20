# App SOP Agent - Implementation Summary

## Overview
A full-stack web application for managing and executing Standard Operating Procedures (SOPs) for User Plane Function (App) infrastructure, with real-time monitoring and AI-powered assistance.

## Architecture

### Backend (FastAPI - Python)
**File:** `backend/api.py` (404 lines)

#### Core Components

1. **SOP Management**
   - List, view, create, and edit SOPs stored as Markdown files
   - File-based storage in `/home/ec2-user/nec-mwc-2026/sops/`
   - REST endpoints: `/api/sops`, `/api/sop/{name}`

2. **Metrics Collection** (`/api/metrics`)
   - **Primary Source:** AWS Managed Prometheus (AMP)
     - Workspace: `ws-f718c38e-e61a-4b81-beb8-3e57cfe86f7c` (us-east-1)
     - Authentication: SigV4 signing with EC2 instance role
     - Queries executed with proper URL encoding
   - **Fallback:** In-cluster Prometheus via kubectl
   - **Metrics Tracked:**
     - `rxGbps`: RX throughput (system_upf_uldl_throughput_receive_rate/1e9)
     - `txGbps`: TX throughput (system_upf_uldl_throughput_send_rate/1e9)
     - `avgCpu`: Average CPU usage across App pods
     - `maxCpu`: Maximum CPU usage
     - `activeSessions`: Active PDU sessions (pfcp_upf_current_pdu_session_count_total)
     - `combined`: Total throughput (RX + TX)

3. **Alarm Management** (`/api/alarms`)
   - Mock alarm data for critical/warning/info events
   - Designed for integration with Alertmanager

4. **AI Chat Integration** (`/api/chat`, `/ws/chat`)
   - WebSocket-based non-blocking communication
   - Integrates with Kiro CLI AI assistant
   - Executes: `kiro-cli chat --no-interactive --trust-all-tools <message>`
   - Strips ANSI formatting for clean responses

5. **SOP Execution** (`/ws/execute`)
   - WebSocket streaming of execution logs
   - Runs `sop_executor.py` with Python 3.11
   - Supports fix mode and model selection (haiku/sonnet)
   - Real-time progress updates

#### IAM Requirements
- **BastionInstanceRole-nec-vpc-outposts:**
  - `aps:QueryMetrics`, `aps:GetSeries`, `aps:GetLabels`, `aps:GetMetricMetadata`
  - Resource: AMP workspace ARN
  
- **WorkerNodeInstanceRole-nec-worker-outposts:**
  - `aps:RemoteWrite` (for Prometheus)
  - Same AMP workspace resource

### Frontend (React + Vite)
**File:** `frontend/src/App.jsx` (1,179 lines)

#### Key Features

1. **Dashboard Layout**
   - Three-column responsive design
   - Left: SOP list and execution controls
   - Center: SOP content viewer/editor
   - Right: Live metrics and alarms

2. **Real-Time Metrics Visualization**
   - **Combined Throughput Graph:** RX + TX Gbps over time
   - **CPU Usage Graph:** Average and max CPU percentage
   - **Active UE Sessions:** Line chart of PDU sessions
   - Auto-refresh every 5 seconds
   - Maintains 5-minute rolling window (150 data points)
   - Expandable full-screen graphs

3. **KPI Cards**
   - Combined Throughput (Gbps)
   - Active UE Sessions
   - Performance Summary (RX/TX breakdown)
   - CPU Usage (Avg/Max)

4. **SOP Management**
   - List view with file metadata
   - Markdown editor with syntax highlighting
   - View/Edit mode toggle
   - Create new SOPs

5. **AI Chat Assistant**
   - Collapsible chat panel
   - WebSocket-based streaming responses
   - Context-aware about SOPs and system status
   - Filters out tool execution noise

6. **Presentation Mode**
   - Embedded PDF slides viewer
   - Full-screen support
   - Keyboard navigation (arrow keys)
   - 9 slides total

7. **Alarm Dashboard**
   - Priority-based filtering (all/critical/warning/info)
   - Color-coded severity indicators
   - Timestamp display

#### Technology Stack
- **React 18** with Hooks
- **Recharts** for data visualization
- **Lucide React** for icons
- **Tailwind CSS** for styling
- **WebSocket** for real-time communication

## Data Flow

### Metrics Pipeline
```
App Pods → Prometheus (in-cluster) → AMP (us-east-1) → Backend API → Frontend
         ↓                                              ↑
    ServiceMonitor                              SigV4 Auth (EC2 Role)
```

### Prometheus Configuration
- **Remote Write URL:** `https://aps-workspaces.us-east-1.amazonaws.com/workspaces/ws-f718c38e-e61a-4b81-beb8-3e57cfe86f7c/api/v1/remote_write`
- **Region:** us-east-1
- **Authentication:** SigV4 with worker node IAM role
- **Queue Config:** 2500 capacity, 1000 samples/send, 200 max shards

### SOP Execution Flow
```
User → Frontend → WebSocket → Backend → sop_executor.py → Kiro CLI → AWS Resources
                                ↓
                         Real-time logs streamed back
```

## Key Metrics
- **Throughput:** ~192 Gbps combined (97 Gbps RX + 95 Gbps TX)
- **CPU Usage:** ~63% average, 68% max
- **Active Sessions:** 10,000 PDU sessions
- **Prometheus Samples:** 70,591+ sent to AMP, 0 failures

## Security Considerations
- No cross-account IAM role assumptions (resolved Palisade security finding)
- SigV4 request signing for AMP authentication
- EC2 instance role-based credentials
- CORS enabled for local development

## Deployment
- **Backend:** Python FastAPI on port 8000
- **Frontend:** Vite dev server (production: static build)
- **Prometheus:** StatefulSet in `monitoring` namespace
- **AMP Workspace:** Same AWS account as EKS cluster

## Future Enhancements
- Replace mock alarms with real Alertmanager integration
- Add metric alerting thresholds
- Implement SOP versioning
- Add user authentication
- Export metrics to CloudWatch
