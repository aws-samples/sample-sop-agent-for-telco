# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ANO Swarm — multi-agent collaboration for complex cross-domain failures.

Uses the Strands Swarm pattern to enable handoffs between ANPA, ANDA, and ANRA
when a failure spans multiple domains (hardware + deployment + runtime).
"""

import logging

from strands import Agent

from amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver import get_model
from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import ModelTier

logger = logging.getLogger(__name__)

# Handoff instructions appended to each agent's system prompt
_HANDOFF_SUFFIX = """

## CROSS-DOMAIN HANDOFF

If the issue is outside your domain, hand off to the appropriate agent:
- ANPA: hardware failures, BMC issues, provisioning problems, firmware
- ANDA: deployment failures, Helm/ArgoCD issues, NF upgrades, rollbacks
- ANRA: runtime alarms, KPI degradation, SOP execution, correlation

To hand off, clearly state: "Handing off to [AGENT_NAME] because [reason]"
"""


def create_ano_swarm():
    """Create a 3-agent swarm for complex cross-domain diagnosis.

    Returns:
        Configured Swarm instance with ANPA, ANDA, and ANRA agents.
    """
    from strands.multiagent import Swarm

    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import PROVISION_TOOLS, SYSTEM_PROMPT_PROVISION
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools_cross_agent import ANPA_CROSS_AGENT_TOOLS
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda import DEPLOY_TOOLS, SYSTEM_PROMPT_DEPLOY
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.tools_cross_agent import ANDA_CROSS_AGENT_TOOLS
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent import CROSS_AGENT_TOOLS

    model_id = get_model(ModelTier.SMART)

    anpa = Agent(
        name="ANPA-provisioner",
        model=model_id,
        system_prompt=SYSTEM_PROMPT_PROVISION + _HANDOFF_SUFFIX,
        tools=PROVISION_TOOLS + ANPA_CROSS_AGENT_TOOLS,
    )
    anda = Agent(
        name="ANDA-deployer",
        model=model_id,
        system_prompt=SYSTEM_PROMPT_DEPLOY + _HANDOFF_SUFFIX,
        tools=DEPLOY_TOOLS + ANDA_CROSS_AGENT_TOOLS,
    )
    anra = Agent(
        name="ANRA-remediator",
        model=model_id,
        system_prompt=(
            "You are ANRA, the Autonomous Network Remediation Agent. "
            "You monitor 5G KPIs, correlate alarms across layers, and execute SOPs. "
            "You can query ANPA and ANDA for cross-domain context."
            + _HANDOFF_SUFFIX
        ),
        tools=CROSS_AGENT_TOOLS,
    )

    return Swarm(nodes=[anpa, anda, anra], execution_timeout=120.0, node_timeout=60.0)


def is_complex_query(message: str) -> bool:
    """Heuristic to detect queries that need multi-agent collaboration.

    A query is complex if it mentions multiple domains or asks about
    cross-cutting concerns.

    Args:
        message: User's chat message.

    Returns:
        True if the query likely needs the swarm.
    """
    msg_lower = message.lower()

    # Domain keywords
    provisioning_terms = {"provision", "bmc", "firmware", "hardware", "bare-metal", "tinkerbell"}
    deployment_terms = {"deploy", "upgrade", "rollback", "helm", "argocd", "version"}
    remediation_terms = {"alarm", "incident", "remediat", "sop", "correlat", "kpi"}

    domains_hit = sum([
        any(t in msg_lower for t in provisioning_terms),
        any(t in msg_lower for t in deployment_terms),
        any(t in msg_lower for t in remediation_terms),
    ])

    # Complex if 2+ domains mentioned, or explicit cross-domain phrases
    if domains_hit >= 2:
        return True

    cross_phrases = [
        "root cause",
        "why did",
        "what caused",
        "investigate",
        "end to end",
        "full picture",
    ]
    return any(p in msg_lower for p in cross_phrases)
