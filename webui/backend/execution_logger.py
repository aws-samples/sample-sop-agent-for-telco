# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Persistent execution logger — captures full trace for debugging and eval history.

Writes one JSON file per graph execution to $SOP_REPO/logs/.
Tracks per-node: tool calls (name, args, result, duration), token usage,
eval scores with reasons, errors, and graph flow (batches, handoffs).
"""
import json
import os
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

def _log_dir() -> Path:
    return Path(os.environ.get("SOP_REPO", "/app")) / "logs"


class ExecutionLogger:
    """Accumulates execution data during a graph run, then persists to JSON."""

    def __init__(self, sop_paths: list[str], eval_mode: bool = False, auto_correct: bool = False):
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.sop_paths = sop_paths
        self.start_time = time.time()
        self.record: dict[str, Any] = {
            "run_id": self.run_id,
            "sop_paths": sop_paths,
            "eval_mode": eval_mode,
            "auto_correct": auto_correct,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "status": "running",
            "nodes": {},       # node_id -> node trace
            "graph_flow": [],  # batch transitions / handoffs
            "errors": [],
        }

    def node_start(self, node_id: str):
        self.record["nodes"].setdefault(node_id, {
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "status": None,
            "execution_time_ms": 0,
            "tool_calls": [],
            "token_usage": None,
            "eval_scores": [],
            "error": None,
            "output_summary": None,
        })

    def tool_call(self, node_id: str, tool_name: str, tool_input: Optional[str] = None):
        node = self.record["nodes"].get(node_id)
        if not node:
            return
        node["tool_calls"].append({
            "tool": tool_name,
            "input": (tool_input or "")[:500],
            "result": None,
            "error": None,
            "start_time": time.time(),
            "duration_ms": None,
        })

    def tool_result(self, node_id: str, tool_use_id: str, result_content: str, is_error: bool = False):
        node = self.record["nodes"].get(node_id)
        if not node or not node["tool_calls"]:
            return
        # Update the last tool call for this node
        tc = node["tool_calls"][-1]
        if tc["result"] is None:
            tc["result"] = result_content[:1000]
            tc["error"] = result_content[:500] if is_error else None
            tc["duration_ms"] = int((time.time() - tc["start_time"]) * 1000)

    def node_complete(self, node_id: str, status: str, execution_time_ms: int = 0,
                      token_usage: Optional[dict] = None, output_summary: Optional[str] = None):
        node = self.record["nodes"].get(node_id)
        if not node:
            return
        node["end_time"] = datetime.now().isoformat()
        node["status"] = status
        node["execution_time_ms"] = execution_time_ms
        node["token_usage"] = token_usage
        node["output_summary"] = (output_summary or "")[:2000]

    def eval_score(self, node_id: str, evaluator: str, score: float, passed: bool,
                   reason: str, budget: Optional[dict] = None):
        node = self.record["nodes"].get(node_id)
        if not node:
            return
        node["eval_scores"].append({
            "evaluator": evaluator,
            "score": score,
            "passed": passed,
            "reason": reason,
            "budget": budget,
        })

    def graph_handoff(self, from_nodes: list[str], to_nodes: list[str]):
        self.record["graph_flow"].append({
            "type": "handoff",
            "timestamp": datetime.now().isoformat(),
            "from": from_nodes,
            "to": to_nodes,
        })

    def and_join_check(self, target: str, terminals: list[str], satisfied: list[str], result: bool):
        self.record["graph_flow"].append({
            "type": "and_join",
            "timestamp": datetime.now().isoformat(),
            "target": target,
            "required": terminals,
            "satisfied": satisfied,
            "result": result,
        })

    def add_error(self, error: str, node_id: Optional[str] = None):
        self.record["errors"].append({
            "timestamp": datetime.now().isoformat(),
            "node_id": node_id,
            "error": error[:2000],
        })
        if node_id and node_id in self.record["nodes"]:
            self.record["nodes"][node_id]["error"] = error[:2000]

    def corrector_snapshot(self, node_id: str, sop_path: str, original_content: str,
                           failures: list[dict]):
        """Record SOP state before correction for audit trail."""
        node = self.record["nodes"].get(node_id)
        if not node:
            return
        node["corrector_audit"] = {
            "sop_path": sop_path,
            "original_hash": hex(hash(original_content)),
            "original_lines": len(original_content.split("\n")),
            "failures_addressed": [f.get("reason", "")[:200] for f in failures],
        }

    def complete(self, status: str, node_states: Optional[dict] = None):
        self.record["end_time"] = datetime.now().isoformat()
        self.record["status"] = status
        self.record["duration_s"] = round(time.time() - self.start_time, 1)
        if node_states:
            self.record["node_states_summary"] = node_states

        # Compute aggregates
        nodes = self.record["nodes"]
        total_tools = sum(len(n["tool_calls"]) for n in nodes.values())
        total_tokens = sum(
            (n.get("token_usage") or {}).get("totalTokens", 0) for n in nodes.values()
        )
        self.record["summary"] = {
            "total_nodes": len(nodes),
            "completed": sum(1 for n in nodes.values() if n["status"] in ("completed", "success")),
            "failed": sum(1 for n in nodes.values() if n["status"] not in ("completed", "success", None)),
            "total_tool_calls": total_tools,
            "total_tokens": total_tokens,
            "duration_s": self.record["duration_s"],
        }

        self._save()

    def _save(self):
        try:
            _log_dir().mkdir(parents=True, exist_ok=True)
            path = _log_dir() / f"execution_{self.run_id}.json"
            # Remove start_time floats from tool_calls before saving
            for node in self.record["nodes"].values():
                for tc in node.get("tool_calls", []):
                    tc.pop("start_time", None)
            with open(path, "w") as f:
                json.dump(self.record, f, indent=2, default=str)
            logger.info(f"Execution log saved: {path}")
        except Exception as e:
            logger.error(f"Failed to save execution log: {e}")


def list_executions(limit: int = 50) -> list[dict]:
    """List saved execution records, most recent first."""
    if not _log_dir().exists():
        return []
    records = []
    for f in sorted(_log_dir().glob("execution_*.json"), reverse=True)[:limit]:
        try:
            data = json.loads(f.read_text())
            # Return summary only for listing
            records.append({
                "run_id": data.get("run_id"),
                "sop_paths": data.get("sop_paths"),
                "status": data.get("status"),
                "start_time": data.get("start_time"),
                "duration_s": data.get("duration_s"),
                "summary": data.get("summary"),
            })
        except Exception:
            pass
    return records


def get_execution(run_id: str) -> Optional[dict]:
    """Get full execution record by run_id."""
    path = _log_dir() / f"execution_{run_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def get_eval_history(sop_stem: str, limit: int = 20) -> list[dict]:
    """Get eval score history for a specific SOP across runs."""
    if not _log_dir().exists():
        return []
    history = []
    for f in sorted(_log_dir().glob("execution_*.json"), reverse=True)[:100]:
        try:
            data = json.loads(f.read_text())
            for nid, node in data.get("nodes", {}).items():
                if nid == f"eval-{sop_stem}" and node.get("eval_scores"):
                    history.append({
                        "run_id": data.get("run_id"),
                        "timestamp": data.get("start_time"),
                        "scores": node["eval_scores"],
                        "avg_score": sum(s["score"] for s in node["eval_scores"]) / len(node["eval_scores"]),
                    })
                    break
        except Exception:
            pass
        if len(history) >= limit:
            break
    return history
