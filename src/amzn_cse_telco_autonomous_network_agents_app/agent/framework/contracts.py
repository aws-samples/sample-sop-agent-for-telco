# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Extension-point contracts — the ABCs an implementation must satisfy.

Each SELECT extension kind has a contract here. A plugin (or a core module)
provides a concrete subclass and registers it; the registry validates the
registration against the contract at registration time, so a malformed adapter
fails loudly at boot rather than at first use.

This module declares the contracts only. Concrete implementations live with the
seam they serve (e.g. the telcocli CLI integration lands in core/executor.py in
a later CR), and the COLLECT ``tool`` kind has no ABC because its contract is the
Strands ``@tool`` callable convention.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class CommandResult:
    """Outcome of a CommandIntegration.run call.

    Carries both the human/agent-facing output and a success flag, so the
    caller can report failure to the agent without the framework depending on
    any engine-specific result type.
    """

    output: str
    success: bool


class CommandIntegration(ABC):
    """A site- or vendor-specific command-line integration.

    Generalizes the hardcoded ``telcocli --profile nec --region us-east-1`` call
    so the profile/region (and the CLI itself) become a customer-selectable
    adapter instead of values baked into the engine. The concrete
    ``TelcoCliIntegration`` (reading profile/region from config) is added when
    the executor seam is migrated to ``get_one(ExtensionKind.CLI, ...)``.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier for this integration (its registry key)."""

    @abstractmethod
    def run(self, command: str) -> CommandResult:
        """Execute ``command`` and return its output plus a success flag."""


class TopologyProvider(ABC):
    """Contract for the TOPOLOGY SELECT kind — node/NF topology queries.

    Concrete backends (YamlTopology single-site, NeptuneTopology multi-site) live
    in agent/topology.py and register instances under this contract. Callers use
    topology.get_provider() and get the same interface regardless of backend.
    """

    @abstractmethod
    def get_node(self, node_id: str) -> Optional[dict]:
        """Get node by SSM ID, OAM IP, or name."""

    @abstractmethod
    def get_nodes(self) -> list[dict]:
        """List all nodes."""

    @abstractmethod
    def get_upstream(self, node_id: str) -> list[dict]:
        """Get components upstream of this node (e.g., CU -> Core)."""

    @abstractmethod
    def get_downstream(self, node_id: str) -> list[dict]:
        """Get components downstream (e.g., Core -> DU)."""

    @abstractmethod
    def get_affected_by(self, component_id: str) -> list[dict]:
        """Get all nodes/NFs affected if this component fails."""

    @abstractmethod
    def get_node_by_role(self, role: str) -> list[dict]:
        """Get nodes by role (du, cu, upf, etc.)."""
