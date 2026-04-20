# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#!/usr/bin/env python3
"""FastAPI backend for SOP Executor with WebSocket support."""
import os
import sys
import io
import asyncio
import json
import time as _time
import threading
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess
import re
import logging

class _RunIdFilter(logging.Filter):
    """Injects run_id into every log record for correlation."""
    run_id = "-"
    def filter(self, record):
        record.run_id = self.run_id
        return True

_run_id_filter = _RunIdFilter()
_log_fmt = "%(asctime)s [%(levelname)s] [%(run_id)s] %(message)s"
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format=_log_fmt)
logging.getLogger().addFilter(_run_id_filter)

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import execution state management
from execution_state import execution_state, AgentStatus, ExecutionHistory
from dataclasses import asdict

from config import SOP_REPO, BEDROCK_PROFILE, BEDROCK_REGION, BEDROCK_MODEL, API_KEY, CORS_ORIGINS, AMP_WORKSPACE_URL, LOG_LEVEL, APP_NAMESPACE, APP_SERVICE_LABEL, SLACK_EXECUTION_WEBHOOK

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    # Recover interrupted executions from previous container lifecycle
    try:
        recent = list_executions(limit=1)
        if recent and recent[0].get("status") == "running":
            run_id = recent[0]["run_id"]
            full = get_execution(run_id)
            if full:
                full["status"] = "interrupted"
                full["end_time"] = datetime.now().isoformat()
                import json
                log_path = Path(os.environ.get("SOP_REPO", "/app")) / "logs" / f"execution_{run_id}.json"
                log_path.write_text(json.dumps(full, indent=2, default=str))
                logging.info(f"Marked interrupted execution: {run_id}")
    except Exception as e:
        logging.warning(f"Startup recovery check failed: {e}")
    yield
    for ws in manager.active_connections[:]:
        try:
            await ws.close()
        except Exception:
            pass
    logging.info("Backend shutdown complete")

app = FastAPI(title="SOP Executor API", lifespan=lifespan)

ALLOWED_ORIGINS = CORS_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi import Request, Depends
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(key: str = Depends(_api_key_header)):
    if API_KEY and key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


class SOPFile(BaseModel):
    name: str
    path: str
    size: int
    modified: str

class SOPContent(BaseModel):
    path: str
    content: str

class ExecuteRequest(BaseModel):
    sop_path: str
    fix_mode: bool = False
    model: str = "haiku"

class EventBuffer:
    """Ring buffer for execution events. Allows WebSocket reconnect + replay."""

    def __init__(self, maxlen: int = 2000):
        from collections import deque
        self._events: deque[dict] = deque(maxlen=maxlen)
        self._seq = 0  # monotonic sequence number

    def append(self, event: dict) -> int:
        self._seq += 1
        event["_seq"] = self._seq
        self._events.append(event)
        return self._seq

    def since(self, seq: int) -> list[dict]:
        """Return events after the given sequence number."""
        return [e for e in self._events if e.get("_seq", 0) > seq]

    def clear(self):
        self._events.clear()
        self._seq = 0

    @property
    def last_seq(self) -> int:
        return self._seq


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()
event_buffer = EventBuffer()
_graph_task: Optional[asyncio.Task] = None

from execution_state import execution_state, AgentStatus
from execution_logger import ExecutionLogger, list_executions, get_execution, get_eval_history

# Import graph orchestrator (sop-agent directory)
_graph_agent_dir = str(Path(__file__).parent.parent.parent / "sop-agent")
if _graph_agent_dir not in sys.path:
    sys.path.insert(0, _graph_agent_dir)
try:
    from sop_graph import build_sop_graph, build_eval_loop
except ImportError:
    logging.warning("sop_graph not available — graph execution disabled")
    build_sop_graph = build_eval_loop = None
_sop_lock = asyncio.Lock()

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/api/status")
async def get_agent_status():
    """Get current agent execution status."""
    return execution_state.to_dict()

@app.get("/api/sop/{sop_name}/history")
async def get_sop_history(sop_name: str):
    """Get last execution history for a specific SOP."""
    # Try exact match first, then try with .md extension
    history = execution_state.get_sop_history(sop_name)
    if not history and not sop_name.endswith('.md'):
        history = execution_state.get_sop_history(f"{sop_name}.md")
    
    if history:
        result = asdict(history)
        result['status'] = history.status.value
        return result
    else:
        return {"status": "never_run", "message": "This SOP has not been executed yet"}

@app.get("/api/executions")
async def api_list_executions():
    """List saved execution records (most recent first)."""
    return list_executions()

@app.get("/api/executions/{run_id}")
async def api_get_execution(run_id: str):
    """Get full execution record by run_id."""
    record = get_execution(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Execution not found")
    return record

@app.get("/api/eval-history/{sop_stem}")
async def api_eval_history(sop_stem: str):
    """Get eval score history for a specific SOP across runs."""
    return get_eval_history(sop_stem)

@app.get("/api/sops", response_model=List[SOPFile])
async def list_sops():
    """List all available SOPs."""
    sop_dir = Path(SOP_REPO) / "sops"
    if not sop_dir.exists():
        sop_dir = Path(SOP_REPO)
    
    sops = []
    for f in sorted(sop_dir.glob("*.md")):
        if not f.name.startswith("archive"):
            stat = f.stat()
            sops.append(SOPFile(
                name=f.name,
                path=str(f),
                size=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime).isoformat()
            ))
    return sops

@app.get("/api/sop/{sop_name}")
async def get_sop(sop_name: str):
    """Get SOP content."""
    sop_path = Path(SOP_REPO) / "sops" / sop_name
    if not sop_path.exists():
        raise HTTPException(status_code=404, detail="SOP not found")
    return {"path": str(sop_path), "content": sop_path.read_text()}

@app.post("/api/sop/{sop_name}")
async def save_sop(sop_name: str, content: SOPContent, _=Depends(verify_api_key)):
    """Save or update SOP content."""
    sop_path = Path(SOP_REPO) / "sops" / sop_name
    sop_path.parent.mkdir(parents=True, exist_ok=True)
    sop_path.write_text(content.content)
    return {"status": "saved", "path": str(sop_path)}

@app.post("/api/sop")
async def create_sop(name: str, content: str = "# New SOP\n\n## Description\n\nAdd your SOP content here.", _=Depends(verify_api_key)):
    """Create a new SOP."""
    if not name.endswith('.md'):
        name += '.md'
    
    sop_path = Path(SOP_REPO) / "sops" / name
    if sop_path.exists():
        raise HTTPException(status_code=400, detail="SOP already exists")
    
    sop_path.write_text(content)
    return {"status": "created", "path": str(sop_path), "name": name}


@app.delete("/api/sop/{sop_name}")
async def delete_sop(sop_name: str, _=Depends(verify_api_key)):
    """Delete an SOP file."""
    sop_path = Path(SOP_REPO) / "sops" / sop_name
    if not sop_path.exists():
        raise HTTPException(status_code=404, detail="SOP not found")
    sop_path.unlink()
    return {"status": "deleted", "name": sop_name}

@app.delete("/api/sop/{sop_name}")
async def delete_sop(sop_name: str, _=Depends(verify_api_key)):
    """Delete an SOP file."""
    sop_path = Path(SOP_REPO) / "sops" / sop_name
    if not sop_path.exists():
        raise HTTPException(status_code=404, detail="SOP not found")
    sop_path.unlink()
    return {"status": "deleted", "name": sop_name}

@app.post("/api/generate-sop")
async def generate_sop(file: UploadFile = File(...)):
    """Accept a document upload (HLD/LLD/run-book) and generate an SOP via Strands Agent."""
    allowed = {".pdf", ".docx", ".doc", ".md", ".txt"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    # Save uploaded file
    uploads_dir = Path(SOP_REPO) / "uploads"
    uploads_dir.mkdir(exist_ok=True)
    upload_path = uploads_dir / file.filename
    data = await file.read()
    upload_path.write_bytes(data)
    logging.info(f"Uploaded document: {file.filename} ({len(data)} bytes)")

    # Generate SOP name from uploaded filename
    stem = Path(file.filename).stem.lower().replace(" ", "-")
    sop_name = f"{stem}.md"
    sop_path = Path(SOP_REPO) / "sops" / sop_name
    # Avoid overwriting existing SOPs
    counter = 1
    while sop_path.exists():
        sop_name = f"{stem}-{counter}.md"
        sop_path = Path(SOP_REPO) / "sops" / sop_name
        counter += 1

    # Extract text from uploaded document
    if ext in {".md", ".txt"}:
        source_text = data.decode("utf-8", errors="replace")
    elif ext == ".docx":
        try:
            import docx
            doc = docx.Document(io.BytesIO(data))
            source_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            source_text = f"(Failed to extract text from {file.filename}: {e})"
    elif ext == ".pdf":
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(io.BytesIO(data))
            source_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            source_text = f"(Failed to extract text from {file.filename}: {e})"
    else:
        source_text = f"(Binary document: {file.filename}, {len(data)} bytes — text extraction not available for {ext})"

    # Generate SOP using Strands Agent with SOP format rule
    try:
        sop_content = await asyncio.get_event_loop().run_in_executor(
            None, _generate_sop_with_agent, source_text, file.filename
        )
    except Exception as e:
        logging.error(f"SOP generation failed: {e}")
        sop_content = f"# SOP: {Path(file.filename).stem}\n\n> Generation failed: {e}\n\n## Procedure\n\n<!-- Add steps manually -->\n"

    sop_path.write_text(sop_content)
    logging.info(f"Generated SOP: {sop_name} from {file.filename}")

    return {"status": "generated", "sop_name": sop_name, "path": str(sop_path), "source": file.filename}


def _generate_sop_with_agent(source_text: str, filename: str) -> str:
    """Use Strands Agent + strands-agents-sops format rule to convert a document into an SOP."""
    try:
        from strands import Agent
        from strands.models.bedrock import BedrockModel
        from strands_agents_sops import get_sop_format
        import boto3

        # Read one existing SOP as a reference for our format
        ref_path = Path(SOP_REPO) / "sops" / "05-validation.md"
        ref_sop = ref_path.read_text()[:2000] if ref_path.exists() else ""

        system_prompt = f"""You are an SOP generator for 5G network operations on AWS.
Your job: convert uploaded documents (HLD, LLD, run-books, vendor guides) into
executable Standard Operating Procedures (SOPs) in markdown format.

{get_sop_format()}

IMPORTANT: Generate SOPs that match this project's format. Here is a reference SOP:

<reference_sop>
{ref_sop}
</reference_sop>

Key format requirements:
- Title with Stage number and Purpose
- Prerequisites section
- Procedure with numbered steps, each containing bash commands in code blocks
- Expected output after each command
- Success Criteria section
- Troubleshooting section
- Use kubectl, ssh_command, argocd commands where appropriate
- Include verification steps after each action
- Output ONLY the SOP markdown, no preamble or explanation."""

        session = boto3.Session(
            profile_name=BEDROCK_PROFILE,
            region_name=BEDROCK_REGION,
        )
        model = BedrockModel(
            boto_session=session,
            model_id=BEDROCK_MODEL,
        )
        agent = Agent(model=model, system_prompt=system_prompt)

        # Truncate very large documents to stay within context
        truncated = source_text[:30000]
        result = agent(
            f"Convert this document into an executable SOP:\n\nFilename: {filename}\n\n{truncated}"
        )
        return str(result)
    except Exception as e:
        logging.error(f"SOP generation agent failed: {e}")
        # Fallback to placeholder
        return f"""# SOP: {Path(filename).stem}

> Auto-generated from: `{filename}`
> Agent generation failed: {e}
> Edit this SOP manually or retry upload.

## Prerequisites

- [ ] Review source document

## Procedure

<!-- Generation failed — add steps manually -->

## Success Criteria

- [ ] All steps completed

## Troubleshooting

- Refer to original document: `{filename}`
"""

_metrics_cache = {"data": {"rxGbps": 0, "txGbps": 0, "avgCpu": 0, "maxCpu": 0, "activeSessions": 0, "combined": 0, "nodeCpuPercent": 0}}

def _fetch_metrics_sync():
    """Blocking metrics fetch — runs in background thread."""
    amp_workspace_url = AMP_WORKSPACE_URL
    try:
        import boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        import requests as req_lib
        from urllib.parse import urlencode

        session = boto3.Session(region_name="us-east-1")
        credentials = session.get_credentials()

        queries = {
            "rxGbps": "system_upf_uldl_throughput_receive_rate/1e9",
            "txGbps": "system_upf_uldl_throughput_send_rate/1e9",
            "avgCpu": "avg(upf_cpu_usage_percent)",
            "maxCpu": "max(upf_cpu_usage_percent)",
            "activeSessions": "pfcp_upf_current_pdu_session_count_total"
        }

        metrics = {}
        for key, query in queries.items():
            params = urlencode({"query": query})
            url = f"{amp_workspace_url}?{params}"
            request = AWSRequest(method='GET', url=url)
            SigV4Auth(credentials, "aps", "us-east-1").add_auth(request)
            response = req_lib.get(url, headers=dict(request.headers), timeout=5)
            if response.ok:
                data = response.json()
                if data.get("data", {}).get("result"):
                    metrics[key] = round(float(data["data"]["result"][0]["value"][1]), 2)
                else:
                    metrics[key] = 0
            else:
                metrics[key] = 0

        metrics["combined"] = round(metrics.get("rxGbps", 0) + metrics.get("txGbps", 0), 2)
        try:
            cmd = "kubectl top node --no-headers"
            result = subprocess.check_output(cmd.split(), text=True, stderr=subprocess.DEVNULL, timeout=5)  # nosec B603
            for line in result.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 3:
                    metrics["nodeCpuPercent"] = int(parts[2].replace("%", ""))
                    break
        except Exception:
            metrics["nodeCpuPercent"] = 0
        _metrics_cache["data"] = metrics
    except Exception as e:
        logging.warning(f"Metrics fetch failed: {e}")

def _metrics_loop():
    """Background thread that refreshes metrics every 3 seconds."""
    while True:
        try:
            _fetch_metrics_sync()
        except Exception as e:
            logging.error(f"Metrics loop error: {e}")
        _time.sleep(3)

threading.Thread(target=_metrics_loop, daemon=True).start()

@app.get("/api/metrics")
async def get_metrics():
    """Return cached metrics (updated by background thread)."""
    return _metrics_cache["data"]

# Placeholder for application-specific stats - customize for your workload
_app_stats_cache = {"data": {"requests": 0, "errors": 0, "latency_ms": 0}}

@app.get("/api/app-stats")
async def get_app_stats():
    """Return application-specific stats. Customize for your workload."""
    return _app_stats_cache["data"]

@app.get("/api/gitlab-issues")
async def get_gitlab_issues():
    """Proxy recent GitLab issues for the Day2 monitor dashboard."""
    import httpx
    project_id = os.getenv("GITLAB_PROJECT_ID", "")
    token = os.getenv("GITLAB_TOKEN", "")
    if not project_id or not token:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://gitlab.com/api/v4/projects/{project_id}/issues",
                params={"state": "opened", "per_page": 10, "order_by": "created_at", "sort": "desc"},
                headers={"PRIVATE-TOKEN": token},
            )
            resp.raise_for_status()
            return [{"iid": i["iid"], "title": i["title"], "state": i["state"],
                      "labels": i.get("labels", []), "web_url": i["web_url"],
                      "created_at": i["created_at"]} for i in resp.json()]
    except Exception as e:
        logger.warning(f"GitLab issues fetch failed: {e}")
        return []

@app.get("/api/corrections")
async def get_corrections():
    """Return all corrections from historical execution logs."""
    import glob as g
    results = []
    for logfile in sorted(g.glob(str(Path(SOP_REPO) / "logs" / "execution_*.json"))):
        try:
            with open(logfile, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, dict) or not data.get("nodes"):
            continue
        run_id = data.get("run_id", "")
        for name, node in data["nodes"].items():
            if name.startswith("correct-") and node:
                results.append({
                    "run_id": run_id,
                    "sop": name.replace("correct-", ""),
                    "status": node.get("status", ""),
                    "output": str(node.get("output_summary", "")),
                    "time": node.get("end_time", ""),
                })
    return results

@app.get("/api/alarms")
async def get_alarms():
    """Get alarms from Alertmanager."""
    from datetime import timezone
    import shlex
    try:
        cmd = ["kubectl", "exec", "-n", "monitoring", "prometheus-kube-prometheus-stack-prometheus-0", "--",
               "wget", "-qO-", "http://kube-prometheus-stack-alertmanager.monitoring.svc.cluster.local:9093/api/v2/alerts"]
        result = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=5)
        data = json.loads(result)
        
        alarms = []
        for idx, alert in enumerate(data, 1):
            if alert.get("status", {}).get("state") != "active":
                continue
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})
            severity = labels.get("severity", "info").lower()
            alertname = labels.get("alertname", "Unknown Alert")
            summary = annotations.get("summary", annotations.get("description", "")[:100])
            message = f"{alertname}: {summary}" if summary else alertname
            
            time_str = "now"
            starts_at = alert.get("startsAt", "")
            if starts_at:
                try:
                    start_time = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
                    minutes = int((datetime.now(timezone.utc) - start_time).total_seconds() / 60)
                    if minutes > 1440:  # skip alarms older than 24h
                        continue
                    time_str = f"{minutes}m ago" if minutes < 60 else f"{minutes // 60}h ago"
                except:
                    pass
            
            alarms.append({"id": idx, "priority": severity, "message": message, "time": time_str})
        return alarms
    except Exception as e:
        print(f"Failed to fetch alarms: {e}")
        return []

async def _emit(event: dict):
    """Append event to buffer and broadcast to all connected WebSockets."""
    event_buffer.append(event)
    await manager.broadcast(event)


async def _flush_text(execution_state, node_id, buf, exec_log=None):
    """Flush buffered text for a node, parsing eval scores and tool results."""
    text = buf.pop(node_id, "")
    if not text.strip():
        return
    execution_state.add_log(f"[{node_id}] {text}")
    step_data = {
        "type": "output", "node_id": node_id,
        "stream": "stdout",
        "message": f"[{node_id}] {text}",
    }
    _clean = re.sub(r'\x1b\[[0-9;]*m', '', text).strip()
    if "└─" in _clean:
        step_data["tool_result"] = _clean
    # Parse eval scores
    if _clean.endswith("Evaluator"):
        execution_state._pending_eval_name = _clean
        execution_state._pending_eval_node = node_id
    elif _clean.startswith("Score:") and execution_state._pending_eval_name:
        score_match = re.search(r'Score:\s*([\d.]+)', _clean)
        if score_match:
            score_val = float(score_match.group(1))
            step_data["eval_score"] = {
                "name": execution_state._pending_eval_name,
                "score": score_val,
                "node_id": getattr(execution_state, '_pending_eval_node', node_id),
            }
            execution_state._pending_eval_name = None
    # Parse PASS/FAIL reasons for execution logger
    elif (_clean.startswith("PASS:") or _clean.startswith("FAIL:")) and exec_log:
        passed = _clean.startswith("PASS:")
        reason = _clean[5:].strip()
        exec_log.eval_score(node_id, execution_state._pending_eval_name or "unknown",
                            1.0 if passed else 0.0, passed, reason)
    # Detect tool failures in text output (SSH errors, timeouts, etc.)
    _FAILURE_PATTERNS = ("Connection refused", "Permission denied", "timed out",
                         "No route to host", "Connection reset", "command not found")
    if exec_log and any(p in _clean for p in _FAILURE_PATTERNS):
        node_data = exec_log.record["nodes"].get(node_id)
        if node_data and node_data["tool_calls"]:
            last_tc = node_data["tool_calls"][-1]
            if last_tc.get("error") is None:
                last_tc["error"] = _clean[:500]
    await _emit(step_data)


def _notify_slack(exec_log: ExecutionLogger):
    """POST execution failure summary to Slack webhook (if configured)."""
    if not SLACK_EXECUTION_WEBHOOK:
        return
    try:
        s = exec_log.record.get("summary", {})
        import requests as _req
        _req.post(SLACK_EXECUTION_WEBHOOK, json={"attachments": [{
            "color": "#dc3545",
            "title": f"❌ Execution Failed — {exec_log.run_id}",
            "text": f"SOPs: {', '.join(exec_log.sop_paths)}\n"
                    f"Nodes: {s.get('completed',0)} completed, {s.get('failed',0)} failed\n"
                    f"Duration: {s.get('duration_s','?')}s | Tools: {s.get('total_tool_calls',0)}",
            "footer": "SOP Orchestrator",
        }]}, timeout=5)
    except Exception as e:
        logging.warning(f"Slack notification failed: {e}")


async def _run_graph(sop_paths, fix_mode, model, eval_mode, auto_correct):
    """Background task: runs the graph, emits events to buffer + broadcast."""
    global _graph_task
    exec_log = ExecutionLogger(sop_paths, eval_mode=eval_mode, auto_correct=auto_correct)

    try:
        execution_state.start_execution(",".join(sop_paths))
        event_buffer.clear()
        _run_id_filter.run_id = exec_log.run_id
        await _emit({"type": "status", "message": "Building SOP graph..."})
        logging.info(f"Building graph: sop_paths={sop_paths}, eval_mode={eval_mode}, auto_correct={auto_correct}")

        if build_sop_graph is None:
            raise RuntimeError("sop_graph module not available")

        if len(sop_paths) == 1 and eval_mode:
            graph = build_eval_loop(
                sop_paths[0], profile=BEDROCK_PROFILE, region=BEDROCK_REGION,
                model_name=model, fix_mode=fix_mode,
                max_corrections=2 if auto_correct else 0,
            )
        else:
            graph = build_sop_graph(
                sop_paths, profile=BEDROCK_PROFILE, region=BEDROCK_REGION,
                default_model=model, fix_mode=fix_mode, eval_mode=eval_mode,
                auto_correct=auto_correct,
            )

        await _emit({
            "type": "graph_ready",
            "nodes": len(graph.nodes),
            "node_ids": list(graph.nodes.keys()),
        })

        task = "Execute your assigned SOP. Read it, run each step, and report pass/fail results."
        last_event = {}
        _text_buf: dict[str, str] = {}  # node_id -> buffered text

        async def _stream_with_retry(g, t, max_retries=1):
            """Wrap graph.stream_async with retry on Bedrock stream errors."""
            for attempt in range(max_retries + 1):
                try:
                    async for event in g.stream_async(t):
                        yield event
                    return  # completed successfully
                except Exception as e:
                    err = str(e)
                    retryable = any(k in err for k in ("ended prematurely", "ReadTimeout", "ConnectionError", "ThrottlingException"))
                    if attempt < max_retries and retryable:
                        wait = 5 * (attempt + 1)
                        logging.warning(f"Bedrock stream error (attempt {attempt+1}): {err}. Retrying in {wait}s...")
                        exec_log.add_error(f"Stream retry {attempt+1}: {err}")
                        await asyncio.sleep(wait)
                    else:
                        raise

        async for event in _stream_with_retry(graph, task, int(os.getenv("GRAPH_MAX_RETRIES", "1"))):
            last_event = event
            etype = event.get("type", "")

            if etype == "multiagent_node_start":
                node_id = event.get("node_id", "")
                execution_state.current_tool = node_id
                exec_log.node_start(node_id)
                await _emit({
                    "type": "node_start", "node_id": node_id,
                    "message": f"▶ Starting: {node_id}",
                })

            elif etype == "multiagent_node_stream":
                node_id = event.get("node_id", "")
                inner = event.get("event", {})
                # Detect tool calls from current_tool_use in agent event
                tool_use = inner.get("current_tool_use", {})
                if tool_use and tool_use.get("name"):
                    tool_name = tool_use["name"]
                    if not hasattr(execution_state, '_last_tool') or execution_state._last_tool != (node_id, tool_name):
                        # Flush text buffer before tool call
                        if node_id in _text_buf and _text_buf[node_id].strip():
                            await _flush_text(execution_state, node_id, _text_buf, exec_log)
                        execution_state._last_tool = (node_id, tool_name)
                        execution_state.current_tool = tool_name
                        execution_state._tool_timestamp = _time.time()
                        exec_log.tool_call(node_id, tool_name, str(tool_use.get("input", ""))[:500])
                        await _emit({
                            "type": "output", "node_id": node_id,
                            "stream": "stdout",
                            "message": f"[{node_id}] 🔧 TOOL: {tool_name}",
                            "tool_call": {"node_id": node_id, "tool": tool_name},
                        })
                # Capture tool results — SDK yields {message: {content: [{toolResult: {...}}]}}
                msg = inner.get("message")
                if msg and isinstance(msg, dict):
                    for block in msg.get("content", []):
                        tr = block.get("toolResult") if isinstance(block, dict) else None
                        if tr:
                            content = ""
                            for c in tr.get("content", []):
                                if isinstance(c, dict) and "text" in c:
                                    content += c["text"]
                            is_err = tr.get("status") == "error"
                            exec_log.tool_result(node_id, tr.get("toolUseId", ""), content[:1000], is_err)
                if "data" in inner:
                    text = str(inner["data"])
                    if text.strip():
                        _text_buf[node_id] = _text_buf.get(node_id, "") + text
                        buf = _text_buf[node_id]
                        # Flush on sentence boundaries
                        if any(buf.rstrip().endswith(c) for c in (".", "!", "|", "**", "---")) or "\n" in text or len(buf) > 200:
                            await _flush_text(execution_state, node_id, _text_buf, exec_log)
                # Structured eval scores from EvalNode (no regex parsing needed)
                if "eval_score" in inner:
                    es = inner["eval_score"]
                    exec_log.eval_score(node_id, es["evaluator"], es["score"], es["passed"],
                                        "; ".join(r["reason"] for r in es.get("reasons", [])))
                    await _emit({
                        "type": "output", "node_id": node_id,
                        "stream": "stdout",
                        "message": f"[{node_id}] {es['evaluator']}: {es['score']:.2f}",
                        "eval_score": {
                            "name": es["evaluator"],
                            "score": es["score"],
                            "node_id": node_id,
                        },
                    })

            elif etype == "multiagent_node_stop":
                node_id = event.get("node_id", "")
                # Flush any remaining buffered text
                if node_id in _text_buf and _text_buf[node_id].strip():
                    await _flush_text(execution_state, node_id, _text_buf, exec_log)
                node_result = event.get("node_result")
                status = "completed"
                if node_result and hasattr(node_result, "status"):
                    status = node_result.status.value if hasattr(node_result.status, "value") else str(node_result.status)

                # Detect agent-reported failures: node "completed" but agent output says CRITICAL FAILURE / CANNOT EXECUTE
                if status == "completed" and node_result:
                    try:
                        results = node_result.get_agent_results() if hasattr(node_result, "get_agent_results") else []
                        for ar in results:
                            if ar.message:
                                txt = str(ar.message.get("content", "")) if isinstance(ar.message, dict) else str(ar.message)
                                if any(m in txt for m in ("CRITICAL FAILURE", "CANNOT EXECUTE", "COMPLETELY FAILED", "Cannot fork")):
                                    status = "failed"
                                    break
                    except Exception:
                        pass

                exec_time = getattr(node_result, "execution_time", 0) if node_result else 0
                # Extract token usage from NodeResult
                token_usage = None
                if node_result:
                    usage = getattr(node_result, "accumulated_usage", None)
                    if usage:
                        token_usage = {k: usage.get(k, 0) for k in ("inputTokens", "outputTokens", "totalTokens")}
                # Extract output summary
                output_summary = None
                if node_result:
                    try:
                        for ar in (node_result.get_agent_results() if hasattr(node_result, "get_agent_results") else []):
                            if ar.message:
                                content = ar.message.get("content", "") if isinstance(ar.message, dict) else str(ar.message)
                                output_summary = str(content)[:2000]
                                break
                    except Exception:
                        pass
                exec_log.node_complete(node_id, "success" if status == "completed" else "failed",
                                       exec_time, token_usage, output_summary)
                execution_state.add_step(node_id, "success" if status == "completed" else "failed")
                # Save per-SOP history (skip eval/correct nodes)
                if not node_id.startswith("eval") and not node_id.startswith("correct"):
                    sop_name = f"{node_id}.md"
                    node_status = AgentStatus.COMPLETED if status == "completed" else AgentStatus.FAILED
                    now = datetime.now()
                    start = datetime.fromtimestamp(now.timestamp() - exec_time / 1000) if exec_time else now
                    execution_state.history[sop_name] = ExecutionHistory(
                        sop_path=sop_name, status=node_status,
                        start_time=start.isoformat(), end_time=now.isoformat(),
                        exit_code=0 if status == "completed" else 1,
                    )
                    execution_state._persist_history()
                await _emit({
                    "type": "node_complete", "node_id": node_id,
                    "status": status, "execution_time_ms": exec_time,
                    "token_usage": token_usage,
                    "message": f"{'✅' if status == 'completed' else '❌'} {node_id} ({exec_time}ms)",
                })

            elif etype == "multiagent_handoff":
                from_ids = event.get("from_node_ids", [])
                to_ids = event.get("to_node_ids", [])
                exec_log.graph_handoff(from_ids, to_ids)
                logging.info(f"Graph handoff: {from_ids} → {to_ids}")

            elif etype == "multiagent_result":
                result = event.get("result")
                # Collect per-node states
                node_states = {}
                if result and hasattr(result, "results"):
                    for nid, nr in result.results.items():
                        node_states[nid] = nr.status.value if hasattr(nr.status, "value") else str(nr.status)
                # Derive status from actual node outcomes, not the graph's
                # aggregate (which marks "failed" if any node was skipped)
                completed = [s for s in node_states.values() if s == "completed"]
                failed = [s for s in node_states.values() if s not in ("completed", "skipped")]
                final_status = "failed" if failed else "completed"
                logging.info(f"Graph complete: {len(completed)} completed, {len(failed)} failed, {len(node_states) - len(completed) - len(failed)} skipped")
                await _emit({
                    "type": "graph_complete", "status": final_status,
                    "execution_time_ms": getattr(result, "execution_time", 0) if result else 0,
                    "completed_nodes": len(completed),
                    "failed_nodes": len(failed),
                    "node_states": node_states,
                })

        success = True
        if last_event.get("type") == "multiagent_result":
            result = last_event.get("result")
            if result and hasattr(result, "results"):
                success = not any(
                    nr.status.value not in ("completed", "skipped")
                    for nr in result.results.values()
                    if hasattr(nr.status, "value")
                )

        execution_state.complete_execution(success, 0 if success else 1)
        exec_log.complete("completed" if success else "failed")
        await _emit({"type": "complete", "exit_code": 0 if success else 1})
        if not success:
            _notify_slack(exec_log)

    except Exception as e:
        logging.exception("Graph execution failed")
        exec_log.add_error(str(e))
        exec_log.complete("error")
        execution_state.complete_execution(False)
        await _emit({"type": "error", "message": str(e)})
        _notify_slack(exec_log)
    finally:
        _run_id_filter.run_id = "-"
        _sop_lock.release()
        _graph_task = None


@app.websocket("/ws/execute-graph")
async def execute_graph(websocket: WebSocket):
    """Start graph execution (if idle) or attach to running execution.

    First message from client is the config JSON. If a graph is already running,
    the client receives a replay of buffered events then live events going forward.
    WebSocket disconnect does NOT cancel execution.
    """
    global _graph_task
    await manager.connect(websocket)

    try:
        data = await websocket.receive_json()
        sop_paths = data.get("sop_paths", [])
        fix_mode = data.get("fix_mode", False)
        model = data.get("model", "haiku")
        eval_mode = data.get("eval_mode", False)
        auto_correct = data.get("auto_correct", False)

        if not sop_paths:
            await websocket.send_json({"type": "error", "message": "No SOPs provided"})
            return

        if _sop_lock.locked():
            # Execution already running — replay buffered events then stream live
            await websocket.send_json({"type": "status", "message": "Attaching to running execution..."})
            for evt in event_buffer.since(0):
                try:
                    await websocket.send_json(evt)
                except Exception:
                    break
        else:
            # Start new execution in background
            await _sop_lock.acquire()
            _graph_task = asyncio.create_task(
                _run_graph(sop_paths, fix_mode, model, eval_mode, auto_correct)
            )

        # Keep WebSocket alive until client disconnects or execution ends.
        # Events are delivered via broadcast from _emit().
        while True:
            try:
                # Wait for client messages (ping/close). Timeout keeps us checking task status.
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            except asyncio.TimeoutError:
                # Check if execution finished while we were waiting
                if _graph_task is None or _graph_task.done():
                    break
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        manager.disconnect(websocket)


@app.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    """WebSocket endpoint for AI chat powered by Amazon Bedrock with tool use."""
    await websocket.accept()
    import boto3, json as _json, subprocess as _sp
    session = boto3.Session(profile_name=BEDROCK_PROFILE, region_name=BEDROCK_REGION)
    bedrock = session.client('bedrock-runtime')
    system_prompt = (
        "You are an AI assistant for a 5G App (User Plane Function) deployment on AWS Outposts with EKS. "
        "You help engineers with Vendor App operations, Kubernetes troubleshooting, ArgoCD, SR-IOV networking, "
        "BGP peering, Helm deployments, and SOP execution. Keep answers concise and technical. "
        "This is the Vendor Demo demo environment. "
        "You have tools to run kubectl and shell commands on the cluster. Use them when users ask about cluster state, pods, logs, etc. "
        "For kubectl, the App namespace is 'nec-app'. Monitoring is in 'monitoring'. ArgoCD is in 'argocd'."
    )
    tools = [
        {"toolSpec": {"name": "kubectl", "description": "Run a kubectl command against the EKS cluster. Example: 'get pods -n nec-app'", "inputSchema": {"json": {"type": "object", "properties": {"command": {"type": "string", "description": "kubectl arguments (without 'kubectl' prefix)"}}, "required": ["command"]}}}},
        {"toolSpec": {"name": "shell", "description": "Run a shell command. Use for non-kubectl tasks like checking logs, files, system info.", "inputSchema": {"json": {"type": "object", "properties": {"command": {"type": "string", "description": "Shell command to execute"}}, "required": ["command"]}}}}
    ]

    # Blocked patterns for safety
    _BLOCKED_SHELL = re.compile(r'rm\s+-rf\s+/($|\s|[a-z])|mkfs|dd\s+if=|>\s*/dev/sd|chmod\s+-R\s+777\s+/', re.I)
    _BLOCKED_KUBECTL = re.compile(r'^(delete|drain|cordon|replace|patch|edit|apply|create)\b', re.I)
    _ALLOWED_KUBECTL = re.compile(r'^(get|describe|logs|top|explain|api-resources|version)\b', re.I)

    def run_tool(name, inp):
        import shlex
        try:
            if name == "kubectl":
                args = inp['command'].strip()
                if not _ALLOWED_KUBECTL.match(args):
                    return f"Blocked: only read-only kubectl commands allowed (get, describe, logs, top). Got: {args.split()[0]}"
                cmd = ["kubectl"] + shlex.split(args)
            else:
                cmd_str = inp["command"]
                if _BLOCKED_SHELL.search(cmd_str):
                    return "Blocked: potentially destructive command"
                cmd = shlex.split(cmd_str)
            r = _sp.run(cmd, capture_output=True, text=True, timeout=30)
            output = (r.stdout + r.stderr).strip()
            return output[:4000] if output else "(no output)"
        except _sp.TimeoutExpired:
            return "Command timed out (30s)"
        except Exception as e:
            return f"Error: {e}"

    messages = []
    try:
        while True:
            data = await websocket.receive_json()
            query = data.get("message", data.get("query", ""))
            if not query:
                continue
            messages.append({"role": "user", "content": [{"text": query}]})

            # Conversation loop to handle tool use
            while True:
                resp = bedrock.converse_stream(
                    modelId=BEDROCK_MODEL,
                    system=[{"text": system_prompt}],
                    messages=messages,
                    toolConfig={"tools": tools},
                    inferenceConfig={"maxTokens": 2048, "temperature": 0.3}
                )

                full_text = []
                tool_uses = []
                current_tool = {"id": "", "name": "", "input_json": ""}
                stop_reason = "end_turn"

                for event in resp["stream"]:
                    if "contentBlockStart" in event:
                        start = event["contentBlockStart"].get("start", {})
                        if "toolUse" in start:
                            current_tool = {"id": start["toolUse"]["toolUseId"], "name": start["toolUse"]["name"], "input_json": ""}
                    elif "contentBlockDelta" in event:
                        delta = event["contentBlockDelta"]["delta"]
                        if "text" in delta:
                            full_text.append(delta["text"])
                            await websocket.send_json({"response": delta["text"], "done": False})
                        elif "toolUse" in delta:
                            current_tool["input_json"] += delta["toolUse"].get("input", "")
                    elif "contentBlockStop" in event:
                        if current_tool["id"]:
                            tool_uses.append(dict(current_tool))
                            current_tool = {"id": "", "name": "", "input_json": ""}
                    elif "messageStop" in event:
                        stop_reason = event["messageStop"].get("stopReason", "end_turn")

                # Build assistant message content
                assistant_content = []
                if full_text:
                    assistant_content.append({"text": "".join(full_text)})
                for tu in tool_uses:
                    assistant_content.append({"toolUse": {"toolUseId": tu["id"], "name": tu["name"], "input": _json.loads(tu["input_json"])}})

                if assistant_content:
                    messages.append({"role": "assistant", "content": assistant_content})

                if stop_reason == "tool_use" and tool_uses:
                    # Execute tools and send status to frontend
                    tool_results = []
                    for tu in tool_uses:
                        inp = _json.loads(tu["input_json"])
                        await websocket.send_json({"response": f"\n🔧 Running: `{tu['name']} {inp.get('command','')}`\n", "done": False})
                        result = run_tool(tu["name"], inp)
                        await websocket.send_json({"response": f"```\n{result[:1000]}\n```\n", "done": False})
                        tool_results.append({"toolResult": {"toolUseId": tu["id"], "content": [{"text": result}]}})
                    messages.append({"role": "user", "content": tool_results})
                    # Loop back for model to process tool results
                else:
                    break

            if len(messages) > 40:
                messages = messages[-40:]
            await websocket.send_json({"response": "", "done": True})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logging.error(f"Chat error: {e}")

# Serve frontend static files (for Docker deployment)
_dist_dir = Path(__file__).parent.parent / "frontend" / "dist"
if _dist_dir.exists():
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    app.mount("/assets", StaticFiles(directory=str(_dist_dir / "assets")), name="assets")
    # Serve static files from dist root (images, slides, etc.)
    for _f in _dist_dir.iterdir():
        if _f.is_file() and _f.name != "index.html":
            pass  # handled by catch-all below
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path.startswith(("api/", "ws/", "health")):
            raise HTTPException(status_code=404)
        file_path = _dist_dir / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_dist_dir / "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
