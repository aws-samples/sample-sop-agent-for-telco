#!/usr/bin/env python3
"""ANRA entrypoint — runs monitor + API server in parallel."""
import threading
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "agent"))


def run_api():
    import uvicorn
    from api import app
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")), log_level="info")


def run_monitor():
    os.environ["REDFISH_WEBHOOK_PORT"] = "8081"  # avoid conflict with API on 8080
    from monitor import run_loop
    run_loop()


if __name__ == "__main__":
    # API in main thread, monitor in background
    monitor_thread = threading.Thread(target=run_monitor, daemon=True)
    monitor_thread.start()
    run_api()
