# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ANRA Site Configuration loader.

Reads anra-config.yaml and provides typed access to infrastructure topology.
All tools (ssm_command, redfish_query, kubectl) use this instead of env vars or hardcoded values.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATHS = [
    os.getenv("ANRA_CONFIG", ""),
    "anra-config.yaml",
    "/app/anra-config.yaml",
    str(Path(__file__).parent.parent / "anra-config.yaml"),
]


@dataclass
class AlarmRule:
    name: str = ""
    layer: int = -1
    source: str = ""  # ran | core | kubernetes | hardware
    metric_field: str = ""
    metric_pattern: str = ""  # glob pattern, e.g. "smf_*"
    metrics: list = field(default_factory=list)  # list of fields for compound rules
    condition: str = ""  # "> 500" | "< 1" | "== 0" | "absent_for 60s"
    severity: str = "warning"
    depends_on: list = field(default_factory=list)
    nf_scope: str = "site-wide"
    sop: str = ""
    service_impact: str = ""
    probable_cause: str = ""


@dataclass
class AnomalyConfig:
    enabled: bool = True
    baseline_samples: int = 10
    sigma_threshold: int = 3
    max_sops_per_hour: int = 3
    testmode: bool = False


@dataclass
class GuardrailsConfig:
    protected_namespaces: list = field(default_factory=lambda: ["srsran", "open5gs", "anra", "kube-system"])
    blocked_commands: list = field(
        default_factory=lambda: [
            r"scale.*--replicas.*0",
            r"delete deployment",
            r"delete statefulset",
            r"delete namespace",
        ]
    )
    approval_mode: str = "auto"


@dataclass
class BMCConfig:
    ip: str = ""
    type: str = "idrac"  # idrac | ilo | generic-redfish
    username: str = "root"
    password_secret: str = ""  # K8s Secret name

    @property
    def redfish_base(self) -> str:
        """Vendor-specific Redfish base paths."""
        if self.type == "ilo":
            return "/redfish/v1/Chassis/1"
        return "/redfish/v1/Chassis/System.Embedded.1"

    @property
    def thermal_path(self) -> str:
        return f"{self.redfish_base}/Thermal"

    @property
    def power_path(self) -> str:
        return f"{self.redfish_base}/Power"


@dataclass
class NodeConfig:
    name: str = ""
    oam_ip: str = ""
    ssm_id: str = ""
    bmc: BMCConfig = field(default_factory=BMCConfig)
    roles: list = field(default_factory=list)
    namespaces: list = field(default_factory=list)


@dataclass
class SiteConfig:
    cluster_name: str = ""
    cluster_context: str = ""
    cluster_region: str = "us-west-1"
    bedrock_region: str = "us-west-2"
    bedrock_profile: str = ""
    influxdb_url: str = ""
    influxdb_token_secret: str = ""
    influxdb_org: str = "srs"
    influxdb_bucket: str = "srsran"
    alertmanager_url: str = ""
    topology_provider: str = "yaml"  # yaml | neptune
    neptune_endpoint: str = ""
    approval_mode: str = "auto"
    remediation_mode: str = "direct"  # direct | gitops
    argocd_url: str = "http://argocd-server.argocd.svc:80"
    alarm_references: list = field(default_factory=list)
    nodes: list = field(default_factory=list)
    alarms: list = field(default_factory=list)
    guardrails: GuardrailsConfig = field(default_factory=GuardrailsConfig)
    anomaly_detection: AnomalyConfig = field(default_factory=AnomalyConfig)

    def get_node_by_ssm(self, ssm_id: str) -> Optional[NodeConfig]:
        return next((n for n in self.nodes if n.ssm_id == ssm_id), None)

    def get_node_by_oam(self, oam_ip: str) -> Optional[NodeConfig]:
        return next((n for n in self.nodes if n.oam_ip == oam_ip), None)

    def get_node_by_bmc(self, bmc_ip: str) -> Optional[NodeConfig]:
        return next((n for n in self.nodes if n.bmc.ip == bmc_ip), None)

    def get_node_by_role(self, role: str) -> Optional[NodeConfig]:
        return next((n for n in self.nodes if role in n.roles), None)

    def get_nodes_by_role(self, role: str) -> list:
        return [n for n in self.nodes if role in n.roles]

    @property
    def all_bmc_ips(self) -> list:
        return [n.bmc.ip for n in self.nodes if n.bmc.ip]

    @property
    def all_ssm_ids(self) -> list:
        return [n.ssm_id for n in self.nodes if n.ssm_id]


def load_config(path: str = "") -> SiteConfig:
    """Load site config from YAML. ANRA_CONFIG env var takes priority."""
    if path and Path(path).exists():
        return _load_file(path)
    env_path = os.getenv("ANRA_CONFIG", "")
    if env_path and Path(env_path).exists():
        return _load_file(env_path)
    for p in _CONFIG_PATHS:
        if p and Path(p).exists():
            return _load_file(p)
    logger.warning("No anra-config.yaml found — using defaults")
    return SiteConfig()


def _load_file(path: str) -> SiteConfig:
    logger.info(f"Loading config from {path}")
    with open(path) as f:
        return _parse(yaml.safe_load(f))


def _parse(raw: dict) -> SiteConfig:
    c = SiteConfig()
    cluster = raw.get("cluster", {})
    c.cluster_name = cluster.get("name", "")
    c.cluster_context = cluster.get("context", "")
    c.cluster_region = cluster.get("region", "us-west-1")

    bedrock = raw.get("bedrock", {})
    c.bedrock_region = bedrock.get("region", "us-west-2")
    c.bedrock_profile = bedrock.get("profile", "")

    mon = raw.get("monitoring", {})
    c.influxdb_url = mon.get("influxdb_url", "")
    c.influxdb_token_secret = mon.get("influxdb_token_secret", "")
    c.influxdb_org = mon.get("influxdb_org", "srs")
    c.influxdb_bucket = mon.get("influxdb_bucket", "srsran")
    c.alertmanager_url = mon.get("alertmanager_url", "")

    topo = raw.get("topology", {})
    c.topology_provider = topo.get("provider", "yaml")
    c.neptune_endpoint = topo.get("endpoint", "")

    c.approval_mode = raw.get("approval", {}).get("mode", "auto")
    remediation = raw.get("remediation", {})
    c.remediation_mode = remediation.get("mode", "direct")
    c.argocd_url = remediation.get("argocd_url", "http://argocd-server.argocd.svc:80")
    c.alarm_references = raw.get("alarm_references", [])

    for n in raw.get("nodes", []):
        bmc_raw = n.get("bmc", {})
        bmc = BMCConfig(
            ip=bmc_raw.get("ip", ""),
            type=bmc_raw.get("type", "idrac"),
            username=bmc_raw.get("username", "root"),
            password_secret=bmc_raw.get("password_secret", ""),
        )
        node = NodeConfig(
            name=n.get("name", ""),
            oam_ip=n.get("oam_ip", ""),
            ssm_id=n.get("ssm_id", ""),
            bmc=bmc,
            roles=n.get("roles", []),
            namespaces=n.get("namespaces", []),
        )
        c.nodes.append(node)

    # Parse alarms
    _alarm_fields = set(AlarmRule.__dataclass_fields__)
    for a in raw.get("alarms", []):
        mapped = {k: v for k, v in a.items() if k in _alarm_fields}
        if "field" in a and "metric_field" not in a:
            mapped["metric_field"] = a["field"]
        if "pattern" in a and "metric_pattern" not in a:
            mapped["metric_pattern"] = a["pattern"]
        c.alarms.append(AlarmRule(**mapped))

    # Parse guardrails
    g = raw.get("guardrails", {})
    if g:
        _g_fields = set(GuardrailsConfig.__dataclass_fields__)
        c.guardrails = GuardrailsConfig(**{k: v for k, v in g.items() if k in _g_fields})

    # Parse anomaly detection
    ad = raw.get("anomaly_detection", {})
    if ad:
        _ad_fields = set(AnomalyConfig.__dataclass_fields__)
        c.anomaly_detection = AnomalyConfig(**{k: v for k, v in ad.items() if k in _ad_fields})

    return c
