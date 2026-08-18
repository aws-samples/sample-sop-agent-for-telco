# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ANO Platform Configuration loader.

Reads agent-config.yaml and provides typed access to infrastructure topology.
All tools (ssm_command, redfish_query, kubectl) use this instead of env vars or hardcoded values.

Supports unified config for all 3 agents (ANRA, ANDA, ANPA) with role-specific validation.
"""

import logging
import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import (
    ApprovalMode,
    ModelTier,
    RemediationMode,
    TopologyProviderKind,
)

logger = logging.getLogger(__name__)

_SUPPORTED_SCHEMA_VERSIONS = frozenset({"1"})

_CONFIG_PATHS = [
    os.getenv("AGENT_CONFIG", ""),
    os.getenv("ANRA_CONFIG", ""),
    "agent-config.yaml",
    "anra-config.yaml",
    "/app/config/agent-config.yaml",
    "/app/anra-config.yaml",
    str(Path(__file__).parent.parent / "agent-config.yaml"),
    str(Path(__file__).parent.parent / "anra-config.yaml"),
]


@dataclass
class AlarmRule:
    name: str = ""
    layer: int = -1
    source: str = ""  # ran | core | kubernetes | hardware
    metric_field: str = ""
    condition: str = ""  # "> 500" | "< 1" | "== 0"
    severity: str = "warning"
    depends_on: list = field(default_factory=list)
    nf_scope: str = "site-wide"
    sop: str = ""
    service_impact: str = ""
    probable_cause: str = ""
    # 3GPP TS 28.532 / ITU-T X.733
    alarm_id: str = ""
    alarm_type: str = ""
    probable_cause_code: int = 0
    perceived_severity: str = ""
    managed_object_class: str = ""
    managed_object_instance: str = ""
    specific_problem: str = ""


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
    # --- Schema version ---
    schema_version: str = "1"
    # --- Cluster ---
    cluster_name: str = ""
    cluster_context: str = ""
    cluster_region: str = "us-west-1"
    # --- Bedrock ---
    bedrock_region: str = "us-west-2"
    bedrock_profile: str = ""
    bedrock_model_tier: str = "smart"  # "fast" (haiku) | "smart" (sonnet)
    bedrock_model_override: str = ""  # explicit model ID, bypasses resolver
    # --- Monitoring (ANRA) ---
    influxdb_url: str = ""
    influxdb_token_secret: str = ""
    influxdb_org: str = "srs"
    influxdb_bucket: str = "srsran"
    alertmanager_url: str = ""
    # --- Topology ---
    topology_provider: str = "yaml"  # yaml | neptune
    neptune_endpoint: str = ""
    topology_emit_service_topology: bool = True
    # --- CLI integration (telcocli / vendor CLI) ---
    cli_integration: str = "telcocli"  # registry key of the CommandIntegration
    cli_profile: str = "nec"  # AWS profile passed to the CLI
    cli_region: str = "us-east-1"  # AWS region passed to the CLI
    # --- Approval & remediation ---
    approval_mode: str = "auto"
    remediation_mode: str = "direct"  # direct | gitops
    argocd_url: str = "http://argocd-server.argocd.svc:80"
    # --- Agent role (set via AGENT_ROLE env var) ---
    agent_role: str = field(default_factory=lambda: os.getenv("AGENT_ROLE", "anra"))
    # --- ANPA-specific (provisioning) ---
    tinkerbell_namespace: str = "tink-system"
    redfish_scan_interval: int = 1800
    provision_concurrency: int = 3
    workflow_timeout: int = 1800  # seconds (30 min) before a stuck workflow is marked failed
    # --- ANDA-specific (deployment) ---
    helm_repo: str = ""
    gitops_repo: str = ""
    gitops_branch: str = "main"
    argocd_namespace: str = "argocd"
    nf_catalog_path: str = "/etc/anda/catalog/catalog.yaml"
    alarm_references: list = field(default_factory=list)
    nodes: list = field(default_factory=list)
    alarms: list = field(default_factory=list)
    guardrails: GuardrailsConfig = field(default_factory=GuardrailsConfig)
    anomaly_detection: AnomalyConfig = field(default_factory=AnomalyConfig)
    # --- Extensions ---
    # Dotted module paths imported at boot so their @register_* decorators run
    # (see framework.plugin_loader). Loaded once at startup; changes require a
    # pod restart. Empty by default (no plugins).
    plugins: list = field(default_factory=list)

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


def validate(config: SiteConfig, role: str = "") -> list[str]:
    """Validate config for the given role. Returns list of error messages (empty = valid)."""
    errors: list[str] = []
    resolved_role = role or config.agent_role

    # Schema version check
    if config.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        errors.append(
            f"Unsupported config version '{config.schema_version}', "
            f"expected one of {sorted(_SUPPORTED_SCHEMA_VERSIONS)}"
        )
        return errors  # can't validate further if version is wrong

    # Universal required fields
    if not config.cluster_name:
        errors.append("cluster.name is required")
    if not config.cluster_region:
        errors.append("cluster.region is required")
    if not config.bedrock_region:
        errors.append("bedrock.region is required")

    # Enumerated field values — fail loud at boot on a typo (e.g. topology
    # "neptun") rather than silently falling back at runtime. The enums are the
    # single source of truth; there is no parallel literal list to drift.
    # Match is exact/case-sensitive by design: these values flow to exact-match
    # lookups downstream (e.g. get_provider compares == "neptune"), so a
    # mis-cased value never worked correctly — failing loud beats silent fallback.
    _enum_fields = [
        ("approval.mode", config.approval_mode, ApprovalMode),
        ("remediation.mode", config.remediation_mode, RemediationMode),
        ("topology.provider", config.topology_provider, TopologyProviderKind),
        ("bedrock.model_tier", config.bedrock_model_tier, ModelTier),
    ]
    for name, value, enum in _enum_fields:
        if value not in enum.values():
            errors.append(f"{name} must be one of {sorted(enum.values())}, got {value!r}")

    # Role-specific validation
    if resolved_role == "anra":
        if not config.influxdb_url and not config.alertmanager_url:
            errors.append(
                "ANRA requires at least one of monitoring.influxdb_url "
                "or monitoring.alertmanager_url"
            )
    elif resolved_role == "anpa":
        if not config.tinkerbell_namespace:
            errors.append("ANPA requires provisioning.tinkerbell_namespace")
    elif resolved_role == "anda":
        if not config.helm_repo and not config.gitops_repo:
            errors.append(
                "ANDA requires at least one of deployment.helm_repo "
                "or deployment.gitops_repo"
            )

    return errors


def validate_or_die(config: SiteConfig, role: str = "") -> None:
    """Validate config and exit if invalid. Call from entrypoint at startup."""
    errors = validate(config, role)
    if errors:
        for err in errors:
            logger.error("Config validation failed: %s", err)
        sys.exit(1)


def load_config(path: str = "") -> SiteConfig:
    """Load site config from YAML. AGENT_CONFIG env var takes priority."""
    if path and Path(path).exists():
        return _load_file(path)

    # AGENT_CONFIG is the canonical env var
    agent_config_path = os.getenv("AGENT_CONFIG", "")
    if agent_config_path and Path(agent_config_path).exists():
        return _load_file(agent_config_path)

    # Backward compat: ANRA_CONFIG still works with deprecation warning
    anra_config_path = os.getenv("ANRA_CONFIG", "")
    if anra_config_path and Path(anra_config_path).exists():
        if not agent_config_path:
            warnings.warn(
                "ANRA_CONFIG is deprecated, use AGENT_CONFIG instead",
                DeprecationWarning,
                stacklevel=2,
            )
        return _load_file(anra_config_path)

    for p in _CONFIG_PATHS:
        if p and Path(p).exists():
            return _load_file(p)
    logger.warning("No agent-config.yaml found — using defaults")
    return SiteConfig()


def _load_file(path: str) -> SiteConfig:
    logger.info(f"Loading config from {path}")
    with open(path) as f:
        return _parse(yaml.safe_load(f))


def _parse(raw: dict) -> SiteConfig:
    c = SiteConfig()
    if not raw:
        return c

    # Schema version
    c.schema_version = str(raw.get("version", "1"))

    cluster = raw.get("cluster", {})
    c.cluster_name = cluster.get("name", "")
    c.cluster_context = cluster.get("context", "")
    c.cluster_region = cluster.get("region", "us-west-1")

    bedrock = raw.get("bedrock", {})
    c.bedrock_region = bedrock.get("region", "us-west-2")
    c.bedrock_profile = bedrock.get("profile", "")
    c.bedrock_model_tier = bedrock.get("model_tier", "smart")
    c.bedrock_model_override = bedrock.get("model_override", "")

    mon = raw.get("monitoring", {})
    c.influxdb_url = mon.get("influxdb_url", "")
    c.influxdb_token_secret = mon.get("influxdb_token_secret", "")
    c.influxdb_org = mon.get("influxdb_org", "srs")
    c.influxdb_bucket = mon.get("influxdb_bucket", "srsran")
    c.alertmanager_url = mon.get("alertmanager_url", "")

    topo = raw.get("topology", {})
    c.topology_provider = topo.get("provider", "yaml")
    c.neptune_endpoint = topo.get("endpoint", "")

    cli = raw.get("cli", {})
    c.cli_integration = cli.get("integration", "telcocli")
    c.cli_profile = cli.get("profile", "nec")
    c.cli_region = cli.get("region", "us-east-1")
    c.topology_emit_service_topology = topo.get("emit_service_topology", True)

    c.approval_mode = raw.get("approval", {}).get("mode", "auto")
    remediation = raw.get("remediation", {})
    c.remediation_mode = remediation.get("mode", "direct")
    c.argocd_url = remediation.get("argocd_url", "http://argocd-server.argocd.svc:80")

    # Agent role
    c.agent_role = raw.get("agent_role", os.getenv("AGENT_ROLE", "anra"))

    # ANPA provisioning config
    prov = raw.get("provisioning", {})
    c.tinkerbell_namespace = prov.get("tinkerbell_namespace", "tink-system")
    c.redfish_scan_interval = prov.get("redfish_scan_interval", 1800)
    c.provision_concurrency = prov.get("concurrency", 3)
    c.workflow_timeout = prov.get("workflow_timeout", 1800)

    # ANDA deployment config
    deploy = raw.get("deployment", {})
    c.helm_repo = deploy.get("helm_repo", "")
    c.gitops_repo = deploy.get("gitops_repo", "")
    c.gitops_branch = deploy.get("gitops_branch", "main")
    c.argocd_namespace = deploy.get("argocd_namespace", "argocd")
    c.nf_catalog_path = deploy.get("nf_catalog_path", "/etc/anda/catalog/catalog.yaml")

    c.alarm_references = raw.get("alarm_references", [])

    # Extension plugin module paths (imported at boot to self-register).
    # A bare string here (forgotten YAML list dashes) would otherwise be
    # iterated character-by-character by load_plugins; fail loud and clear.
    plugins = raw.get("plugins", [])
    if not isinstance(plugins, list):
        msg = (
            f"config 'plugins' must be a list of dotted module paths, got "
            f"{type(plugins).__name__}: {plugins!r}"
        )
        raise ValueError(msg)
    c.plugins = plugins

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
