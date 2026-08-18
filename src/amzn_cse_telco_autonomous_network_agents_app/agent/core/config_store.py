# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Thread-safe singleton config store for hot-reload support.

Usage:
    from amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store import (
        get_config,
        set_config,
    )

    cfg = get_config()  # Returns None before first set_config() call
    set_config(new_cfg)  # Atomically replaces the active config
"""

import threading
from typing import Optional

from amzn_cse_telco_autonomous_network_agents_app.agent.config import SiteConfig

_lock = threading.RLock()
_config: Optional[SiteConfig] = None


def get_config() -> Optional[SiteConfig]:
    """Return the current SiteConfig, or None if not yet initialized."""
    with _lock:
        return _config


def set_config(new: SiteConfig) -> None:
    """Atomically replace the active SiteConfig."""
    global _config
    with _lock:
        _config = new
