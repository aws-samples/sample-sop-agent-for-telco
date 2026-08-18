# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Backward-compat re-export — canonical location is agent.core.state.

Bare-collection re-exports (`_alarms`, `_executions`, etc.) were intentionally
removed: every caller now goes through a ``push_*`` writer or a ``snapshot_*``
reader, both of which take the module-level lock in ``agent.core.state``.
A direct import of the underscored collections would bypass the lock and
re-introduce the unsafe-iteration class this module just closed. If a future
caller genuinely needs raw access (e.g. a debugger probe), reach into
``agent.core.state`` explicitly with a comment acknowledging the unsafety.
"""
from amzn_cse_telco_autonomous_network_agents_app.agent.core.state import (  # noqa: F401
    clear_alarms,
    pop_pending_approval,
    push_activity,
    push_alarm,
    push_correlation,
    push_execution,
    push_pending_approval,
    snapshot_activity,
    snapshot_active_alarm_names,
    snapshot_alarms,
    snapshot_alarms_with_active_names,
    snapshot_correlations,
    snapshot_executions,
    snapshot_pending_approvals,
)
