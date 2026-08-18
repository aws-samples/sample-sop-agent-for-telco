# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Config file watcher with debounced reload.

Polls file stat() every 1 second (works reliably with K8s ConfigMap symlink
swaps, unlike inotify which misses atomic renames on the parent directory).

On change detection, waits a 2-second debounce window before reloading to
coalesce the multiple filesystem events that K8s ConfigMap updates generate.
"""

import logging
import os
import threading
import time
from typing import Callable, Optional

from amzn_cse_telco_autonomous_network_agents_app.agent.config import (
    SiteConfig,
    load_config,
    validate,
)

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 1.0  # seconds between stat() checks
_DEBOUNCE_WINDOW = 2.0  # seconds to wait after last change before reload


class ConfigWatcher:
    """Watches a config file path and triggers reload on changes."""

    def __init__(
        self,
        path: str,
        role: str,
        on_reload: Callable[[SiteConfig], None],
    ) -> None:
        self._path = path
        self._role = role
        self._on_reload = on_reload
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_mtime: float = 0.0

    def start(self) -> None:
        """Start the background polling thread."""
        self._last_mtime = self._get_mtime()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, name="config-watcher", daemon=True
        )
        self._thread.start()
        logger.info("ConfigWatcher started for %s", self._path)

    def stop(self) -> None:
        """Signal the polling thread to stop and wait for it to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("ConfigWatcher stopped")

    def _get_mtime(self) -> float:
        """Get the mtime of the watched file, resolving symlinks."""
        try:
            # os.stat follows symlinks by default, which is what we want
            # for ConfigMap symlink chains
            return os.stat(self._path).st_mtime
        except OSError:
            return 0.0

    def _poll_loop(self) -> None:
        """Main polling loop: detect changes, debounce, reload."""
        while not self._stop_event.is_set():
            self._stop_event.wait(_POLL_INTERVAL)
            if self._stop_event.is_set():
                break

            current_mtime = self._get_mtime()
            if current_mtime != self._last_mtime and current_mtime != 0.0:
                # File changed — debounce before reloading
                logger.debug(
                    "Config file change detected (mtime %s -> %s), debouncing...",
                    self._last_mtime,
                    current_mtime,
                )
                self._debounce_and_reload()

    def _debounce_and_reload(self) -> None:
        """Wait for changes to settle, then reload config."""
        # Wait the debounce window, checking for further changes
        deadline = time.monotonic() + _DEBOUNCE_WINDOW
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return
            self._stop_event.wait(0.2)

        # Capture final mtime after debounce
        final_mtime = self._get_mtime()
        self._last_mtime = final_mtime

        # Attempt reload
        try:
            new_cfg = load_config(self._path)
            errors = validate(new_cfg, role=self._role)
            if errors:
                logger.error(
                    "Hot-reload config validation failed (keeping old config): %s",
                    "; ".join(errors),
                )
                return

            logger.info("Config hot-reloaded successfully from %s", self._path)
            self._on_reload(new_cfg)
        except Exception:
            logger.exception(
                "Failed to hot-reload config from %s (keeping old config)", self._path
            )
