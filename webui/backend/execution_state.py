# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Agent execution state management
"""
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running" 
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class LogEntry:
    timestamp: str
    message: str
    type: str = "stdout"

@dataclass 
class ExecutionStep:
    name: str
    status: str  # 'success', 'failed', 'running'
    timestamp: str

@dataclass 
class ExecutionHistory:
    sop_path: str
    status: AgentStatus
    start_time: str
    end_time: Optional[str] = None
    logs: List[LogEntry] = None
    last_output: Optional[str] = None
    exit_code: Optional[int] = None
    steps: List[ExecutionStep] = None
    
    def __post_init__(self):
        if self.logs is None:
            self.logs = []
        if self.steps is None:
            self.steps = []

@dataclass 
class ExecutionState:
    status: AgentStatus = AgentStatus.IDLE
    current_sop: Optional[str] = None
    current_tool: Optional[str] = None
    _tool_timestamp: float = 0
    _tools_used: List[str] = None
    _pending_eval_name: Optional[str] = None
    _pending_eval_node: Optional[str] = None
    _eval_scores: Dict[str, float] = None
    fix_mode: bool = False
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    logs: List[LogEntry] = None
    last_output: Optional[str] = None
    progress: int = 0
    total_steps: int = 0
    history: Dict[str, ExecutionHistory] = None  # SOP name -> last execution
    steps: List[ExecutionStep] = None  # Current execution steps
    
    def __post_init__(self):
        if self.logs is None:
            self.logs = []
        if self.history is None:
            self.history = {}
        if self.steps is None:
            self.steps = []
        self._restore_history()
    
    def start_execution(self, sop_path: str) -> None:
        """Start a new execution"""
        self.status = AgentStatus.RUNNING
        self.current_sop = sop_path
        self.start_time = datetime.now().isoformat()
        self.end_time = None
        self.logs = []
        self.steps = []
        self.progress = 0
        self.total_steps = 0
        self.last_output = None
        self.current_tool = None
        self._tools_used = []
    
    def complete_execution(self, success: bool = True, exit_code: int = 0) -> None:
        """Complete the current execution"""
        self.status = AgentStatus.COMPLETED if success else AgentStatus.FAILED
        self.end_time = datetime.now().isoformat()
        
        # Save to history using SOP name as key
        if self.current_sop:
            sop_name = self.current_sop.split('/')[-1] if '/' in self.current_sop else self.current_sop
            self.history[sop_name] = ExecutionHistory(
                sop_path=self.current_sop,
                status=self.status,
                start_time=self.start_time,
                end_time=self.end_time,
                logs=self.logs.copy(),
                last_output=self.last_output,
                exit_code=exit_code,
                steps=self.steps.copy()
            )
        self._persist_history()
    
    def add_step(self, name: str, status: str) -> None:
        """Add or update an execution step"""
        step = ExecutionStep(
            name=name,
            status=status,
            timestamp=datetime.now().isoformat()
        )
        self.steps.append(step)
    
    def add_log(self, message: str, log_type: str = "stdout") -> None:
        """Add a log entry"""
        log_entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            message=message,
            type=log_type
        )
        self.logs.append(log_entry)
        self.last_output = message
        
        # Keep only last 100 log entries to prevent memory bloat
        if len(self.logs) > 100:
            self.logs = self.logs[-100:]
    
    def get_sop_history(self, sop_name: str) -> Optional[ExecutionHistory]:
        """Get last execution history for a specific SOP"""
        return self.history.get(sop_name)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        import time
        # Clear stale tool after 10s of no new tool call
        if self.current_tool and self._tool_timestamp and (time.time() - self._tool_timestamp > 10):
            self.current_tool = None
        result = asdict(self)
        # Remove internal fields, expose clean versions
        for key in ('_tool_timestamp', '_tools_used', '_pending_eval_name', '_pending_eval_node', '_eval_scores'):
            result.pop(key, None)
        result['tools_used'] = list(set(self._tools_used or []))
        result['eval_scores'] = self._eval_scores or {}
        result['status'] = self.status.value
        result['history'] = {
            name: {**asdict(hist), 'status': hist.status.value if hasattr(hist.status, 'value') else str(hist.status)}
            for name, hist in self.history.items()
        }
        return result

    _HISTORY_FILE = os.path.join(os.environ.get("SOP_REPO", "/app"), "logs", "history.json")

    def _persist_history(self) -> None:
        """Save history + graph node states to disk for survival across restarts."""
        import json
        try:
            os.makedirs(os.path.dirname(self._HISTORY_FILE), exist_ok=True)
            data = {
                name: {
                    'sop_path': h.sop_path, 'status': h.status.value if hasattr(h.status, 'value') else str(h.status),
                    'start_time': h.start_time, 'end_time': h.end_time, 'exit_code': h.exit_code,
                }
                for name, h in self.history.items()
            }
            with open(self._HISTORY_FILE, 'w') as f:
                json.dump(data, f)
        except Exception:
            pass

    def _restore_history(self) -> None:
        """Load persisted history on startup."""
        import json
        try:
            with open(self._HISTORY_FILE) as f:
                data = json.load(f)
            for name, h in data.items():
                status_str = h.get('status', 'completed')
                status = AgentStatus.COMPLETED if status_str == 'completed' else AgentStatus.FAILED
                self.history[name] = ExecutionHistory(
                    sop_path=h.get('sop_path', name), status=status,
                    start_time=h.get('start_time'), end_time=h.get('end_time'),
                    exit_code=h.get('exit_code'),
                )
        except Exception:
            pass

# Global execution state instance
execution_state = ExecutionState()
