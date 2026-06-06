# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Auto-shutdown when the dashboard has been idle for too long."""

import asyncio
import logging
import os
import signal
import time

log = logging.getLogger("idle_shutdown")

IDLE_TIMEOUT_SECONDS = int(os.getenv("ANRA_IDLE_TIMEOUT", str(4 * 3600)))  # 4 hours
CHECK_INTERVAL_SECONDS = 300  # 5 minutes

_last_activity = time.time()


def record_activity():
    """Called by middleware on every API request."""
    global _last_activity
    _last_activity = time.time()


async def idle_watcher():
    """Background task: shut down if idle for too long."""
    if IDLE_TIMEOUT_SECONDS <= 0:
        return  # disabled
    while True:
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        idle = time.time() - _last_activity
        if idle > IDLE_TIMEOUT_SECONDS:
            log.warning(f"Dashboard idle for {idle / 3600:.1f}h — initiating shutdown")
            os.kill(os.getpid(), signal.SIGTERM)
            return
