# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Anonymous opt-in usage telemetry to CloudWatch. Disabled by default."""

import hashlib
import json
import os
import threading
import time
import uuid
from queue import Empty, Full, Queue
from threading import Thread

ENABLED = os.getenv("ANRA_TELEMETRY_ENABLED", "false").lower() == "true"
LOG_GROUP = os.getenv("ANRA_TELEMETRY_LOG_GROUP", "")
SESSION_ID = str(uuid.uuid4())[:8]
PARTICIPANT_HASH = hashlib.sha256(
    (os.getenv("HOSTNAME", "") + os.getenv("EVENT_ID", "")).encode()
).hexdigest()[:12]

_queue: Queue = Queue(maxsize=1000)
_thread_lock = threading.Lock()
_thread: Thread | None = None


def _worker():
    """Background thread that flushes events to CloudWatch."""
    if not ENABLED or not LOG_GROUP:
        return
    import boto3

    client = boto3.client("logs")
    stream_name = f"{SESSION_ID}-{int(time.time())}"
    try:
        client.create_log_stream(logGroupName=LOG_GROUP, logStreamName=stream_name)
    except Exception:
        pass

    while True:
        events = []
        try:
            events.append(_queue.get(timeout=10))
            while len(events) < 50:
                events.append(_queue.get_nowait())
        except Empty:
            pass
        if not events:
            continue
        try:
            client.put_log_events(
                logGroupName=LOG_GROUP,
                logStreamName=stream_name,
                logEvents=[
                    {"timestamp": int(e["timestamp"] * 1000), "message": json.dumps(e)}
                    for e in events
                ],
            )
        except Exception:
            pass


def emit(event_type: str, **kwargs):
    """Record an anonymous event. No-op when disabled."""
    global _thread
    if not ENABLED:
        return
    with _thread_lock:
        if _thread is None:
            _thread = Thread(target=_worker, daemon=True)
            _thread.start()

    # Crude PII filter
    event = {
        "type": event_type,
        "timestamp": time.time(),
        "session_id": SESSION_ID,
        "participant_hash": PARTICIPANT_HASH,
        **{k: v for k, v in kwargs.items() if not any(s in str(v) for s in ["ip:", "i-", "arn:aws", "@"])},
    }
    try:
        _queue.put_nowait(event)
    except Full:
        pass
