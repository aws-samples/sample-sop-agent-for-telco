# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Standardized context schemas for inter-agent communication.

These dataclasses define the contract between ANRA agents.
Designed to be serializable to JSON for future MCP/A2A transport.
"""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AlarmContext:
    """Standardized alarm event — output of KPI monitoring agents."""

    name: str
    severity: str  # critical, major, minor, warning
    source: str  # influx, cloudwatch, alertmanager, redfish, dynamic-anomaly
    value: float = 0
    threshold: str = ""
    timestamp: float = field(default_factory=time.time)
    # Topology
    node_name: str = ""
    nf_instance: str = ""
    # Alarm reference enrichment
    layer: int = -1  # 0=hw, 1=os/infra, 2=core, 3=ran, 4=ue
    service_impact: str = ""
    probable_cause: str = ""
    sop: str = ""
    nf_scope: str = "site-wide"  # per-node, per-instance, site-wide
    # 3GPP fields
    alarm_id: str = ""
    alarm_type: str = ""
    probable_cause_code: int = 0
    perceived_severity: str = ""
    managed_object_class: str = ""
    specific_problem: str = ""
    # Redfish enrichment
    vendor_description: str = ""
    vendor_resolution: str = ""
    live_thermal: Optional[dict] = None
    live_power: Optional[dict] = None
    running_pods: str = ""
    node_roles: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dict for backward compatibility with existing code."""
        d = {k: v for k, v in self.__dict__.items() if v or k in ("value", "layer")}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AlarmContext":
        """Create from raw alarm dict (backward compat)."""
        valid_fields = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in valid_fields})


@dataclass
class CorrelationResult:
    """Output of the correlation engine."""

    action: str  # execute, suppress, escalate
    root_cause: str
    symptoms: list = field(default_factory=list)
    confidence: str = "high"  # high, medium, low
    reasoning: str = ""
    reeval: list = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "CorrelationResult":
        valid_fields = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in valid_fields})


@dataclass
class RemediationPlan:
    """Output of SOP resolution — what to execute."""

    alarm_name: str
    sop_path: Optional[str] = None
    generated: bool = False
    enriched: bool = False
    correlation: Optional[CorrelationResult] = None

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        if self.correlation:
            d["correlation"] = self.correlation.to_dict()
        return d


@dataclass
class ExecutionResult:
    """Output of SOP execution."""

    status: str  # completed, error, timeout
    duration_seconds: float = 0
    tool_count: int = 0
    model: str = ""
    output: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v}


@dataclass
class VerificationResult:
    """Output of post-remediation verification."""

    status: str  # pass, fail, timeout
    soak_time_seconds: int = 0
    kpi_delta: dict = field(default_factory=dict)
    new_issues: list = field(default_factory=list)
    recommendation: str = ""  # close, rollback, escalate

    def to_dict(self) -> dict:
        return self.__dict__.copy()
