# SOP Executor Web UI

Modern web interface for AI-driven 5G App deployment automation.

## Architecture

- **Backend**: FastAPI with WebSocket for real-time execution streaming
- **Frontend**: React + Vite + TailwindCSS
- **Agent**: Strands + Amazon Bedrock

## Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
python api.py
```

Backend runs on `http://localhost:8000`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:3000`

## Features

✅ **SOP Management**
- List all available SOPs
- View SOP content
- Edit and save SOPs

✅ **Execution**
- Select model (Haiku, Sonnet 3.5, Sonnet 4)
- Toggle auto-fix mode
- Real-time execution logs with color-coded output
- WebSocket streaming for live progress

✅ **Modern UI**
- Gradient background
- Responsive design
- Color-coded logs (✅ green, ❌ red, 🔧 cyan)
- Auto-scrolling logs

## Usage

1. Start backend: `python backend/api.py`
2. Start frontend: `cd frontend && npm run dev`
3. Open browser: `http://localhost:3000`
4. Select an SOP from the list
5. Configure execution settings
6. Click "Execute SOP" and watch real-time progress

## API Endpoints

- `GET /api/sops` - List all SOPs
- `GET /api/sop/{name}` - Get SOP content
- `POST /api/sop/{name}` - Save SOP content
- `WS /ws/execute` - Execute SOP with real-time streaming
