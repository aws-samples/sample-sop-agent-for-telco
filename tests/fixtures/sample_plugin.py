# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A sample extension plugin used to prove end-to-end discovery + registration.

Imported by dotted path through ``load_plugins`` in the plugin-loader tests. On
import, the decorator below registers a tool into the global registry — exactly
the path a customer-shipped plugin module follows.
"""

from amzn_cse_telco_autonomous_network_agents_app.agent.framework.registry import (
    register_tool,
)

SAMPLE_PLUGIN_TOOL_NAME = "sample_plugin_echo"


@register_tool(SAMPLE_PLUGIN_TOOL_NAME)
def sample_echo(message: str) -> str:
    """Trivial tool: echo the message back (stands in for a real customer tool)."""
    return f"echo: {message}"
