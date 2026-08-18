# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
ANDA configuration loader.

Reads NF catalog and upgrade-strategy ConfigMap mounts, returning
typed dataclass instances.  Missing files are handled gracefully so
the agent can start even when a mount is not yet available.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default mount paths (overridable via environment variables)
# ---------------------------------------------------------------------------
DEFAULT_CATALOG_PATH = os.environ.get(
    "ANDA_CATALOG_PATH", "/etc/anda/catalog/catalog.yaml"
)
DEFAULT_UPGRADE_STRATEGY_PATH = os.environ.get(
    "ANDA_UPGRADE_STRATEGY_PATH", "/etc/anda/upgrade/upgrade-strategy.yaml"
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NFCatalogEntry:
    """Describes a single Network Function entry in the NF catalog.

    Attributes:
        name:       Human-readable NF name (e.g. ``amf``, ``smf``).
        chart:      Helm chart reference (e.g. ``oci://registry/charts/amf``).
        version:    Chart version string (e.g. ``1.4.2``).
        namespace:  Target Kubernetes namespace for the NF.
    """

    name: str
    chart: str
    version: str
    namespace: str


@dataclass
class UpgradeStrategy:
    """Describes how a particular NF type should be upgraded.

    Attributes:
        name:        Strategy name (e.g. ``rolling``, ``blue-green``).
        applies_to:  List of NF types this strategy applies to.
        steps:       Ordered list of step descriptors (plain dicts so that
                     callers can interpret them without schema coupling).
    """

    name: str
    applies_to: List[str] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_nf_catalog(
    path: str = DEFAULT_CATALOG_PATH,
) -> List[NFCatalogEntry]:
    """Load the NF catalog from a YAML file (typically a ConfigMap mount).

    The YAML is expected to contain a top-level ``nfs`` key whose value is a
    list of mappings with at minimum ``name``, ``chart``, ``version``, and
    ``namespace`` keys.

    Example YAML structure::

        nfs:
          - name: amf
            chart: oci://example.registry/charts/amf
            version: "1.4.2"
            namespace: telco-core
          - name: smf
            chart: oci://example.registry/charts/smf
            version: "1.3.1"
            namespace: telco-core

    Args:
        path: Filesystem path to the catalog YAML.  Defaults to
              ``/etc/anda/catalog/catalog.yaml`` (or the value of
              ``ANDA_CATALOG_PATH`` env-var).

    Returns:
        List of :class:`NFCatalogEntry` objects.  Returns an empty list when
        the file does not exist or cannot be parsed, so that the agent can
        degrade gracefully.
    """
    if not os.path.exists(path):
        log.warning("NF catalog not found at %s; returning empty catalog", path)
        return []

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw: Dict[str, Any] = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        log.error("Failed to load NF catalog from %s: %s", path, exc)
        return []

    entries: List[NFCatalogEntry] = []
    # Support both "nfs" and "networkFunctions" keys (ConfigMap variants)
    nf_list = raw.get("nfs", raw.get("networkFunctions", []))
    for item in nf_list:
        try:
            entries.append(
                NFCatalogEntry(
                    name=item["name"],
                    chart=item["chart"],
                    version=str(item["version"]),
                    namespace=item.get("namespace", "default"),
                )
            )
        except (KeyError, TypeError) as exc:
            log.warning("Skipping malformed NF catalog entry (%s): %s", exc, item)

    log.info("Loaded %d NF catalog entries from %s", len(entries), path)
    return entries


def load_upgrade_strategy(
    path: str = DEFAULT_UPGRADE_STRATEGY_PATH,
) -> List[UpgradeStrategy]:
    """Load upgrade strategies from a YAML file (typically a ConfigMap mount).

    The YAML is expected to contain a top-level ``strategies`` key whose value
    is a list of strategy definitions.

    Example YAML structure::

        strategies:
          - name: rolling
            appliesTo:
              - amf
              - smf
            steps:
              - action: drain
                selector: "app=amf"
              - action: deploy
                waitSeconds: 120

    Args:
        path: Filesystem path to the upgrade-strategy YAML.  Defaults to
              ``/etc/anda/upgrade/upgrade-strategy.yaml`` (or the value of
              ``ANDA_UPGRADE_STRATEGY_PATH`` env-var).

    Returns:
        List of :class:`UpgradeStrategy` objects.  Returns an empty list when
        the file does not exist or cannot be parsed.
    """
    if not os.path.exists(path):
        log.warning(
            "Upgrade strategy file not found at %s; returning empty strategies", path
        )
        return []

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw: Dict[str, Any] = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        log.error("Failed to load upgrade strategies from %s: %s", path, exc)
        return []

    strategies: List[UpgradeStrategy] = []
    raw_strategies = raw.get("strategies", [])

    # Handle both list format [{name: ..., appliesTo: ...}] and
    # dict format {strategy_name: {appliesTo: ...}} (ConfigMap variants)
    if isinstance(raw_strategies, dict):
        # Convert dict format to list format
        items = [
            {"name": k, **v} if isinstance(v, dict) else {"name": k}
            for k, v in raw_strategies.items()
        ]
    elif isinstance(raw_strategies, list):
        items = raw_strategies
    else:
        log.warning("Unexpected strategies format (%s); returning empty", type(raw_strategies))
        return []

    for item in items:
        try:
            strategies.append(
                UpgradeStrategy(
                    name=item["name"],
                    applies_to=list(item.get("appliesTo", item.get("applies_to", []))),
                    steps=list(item.get("steps", [])),
                )
            )
        except (KeyError, TypeError) as exc:
            log.warning(
                "Skipping malformed upgrade strategy entry (%s): %s", exc, item
            )

    log.info("Loaded %d upgrade strategies from %s", len(strategies), path)
    return strategies


def get_catalog_entry(
    catalog: List[NFCatalogEntry], nf_name: str
) -> Optional[NFCatalogEntry]:
    """Return the first :class:`NFCatalogEntry` whose ``name`` matches *nf_name*.

    Args:
        catalog:  List returned by :func:`load_nf_catalog`.
        nf_name:  NF name to look up (case-insensitive).

    Returns:
        Matching entry or ``None``.
    """
    nf_lower = nf_name.lower()
    for entry in catalog:
        if entry.name.lower() == nf_lower:
            return entry
    return None


def get_strategy_for_nf(
    strategies: List[UpgradeStrategy], nf_name: str
) -> Optional[UpgradeStrategy]:
    """Return the first :class:`UpgradeStrategy` that applies to *nf_name*.

    Args:
        strategies: List returned by :func:`load_upgrade_strategy`.
        nf_name:    NF type name to match against ``applies_to`` lists.

    Returns:
        Matching strategy or ``None``.
    """
    nf_lower = nf_name.lower()
    for strategy in strategies:
        if nf_lower in [s.lower() for s in strategy.applies_to]:
            return strategy
    return None


# ---------------------------------------------------------------------------
# Infrastructure Catalog (built-in — no ConfigMap needed)
# ---------------------------------------------------------------------------

@dataclass
class InfraComponent:
    """Describes an infrastructure component ANDA can deploy during bootstrap."""

    name: str
    type: str  # "infrastructure" | "platform"
    install_method: str  # "helm" | "kubectl_apply"
    source: str  # chart ref or manifest path
    namespace: str
    wave: int
    depends_on: List[str] = field(default_factory=list)
    health_check: str = ""
    values: Dict[str, Any] = field(default_factory=dict)


INFRASTRUCTURE_CATALOG: List[InfraComponent] = [
    InfraComponent(
        name="kro",
        type="infrastructure",
        install_method="helm",
        source="oci://public.ecr.aws/kro/kro",
        namespace="kro-system",
        wave=1,
        depends_on=[],
        health_check="kubectl get deploy kro-controller -n kro-system -o jsonpath='{.status.readyReplicas}'",
    ),
    InfraComponent(
        name="tinkerbell-stack",
        type="infrastructure",
        install_method="helm",
        source="oci://ghcr.io/tinkerbell/charts/tinkerbell",
        namespace="tink-system",
        wave=2,
        depends_on=["kro"],
        health_check="kubectl get pods -n tink-system -l app.kubernetes.io/name=tink-server --no-headers | grep Running",
    ),
    InfraComponent(
        name="image-server",
        type="infrastructure",
        install_method="kubectl_apply",
        source="/app/manifests/infrastructure/image-server.yaml",
        namespace="tink-system",
        wave=3,
        depends_on=["tinkerbell-stack"],
        health_check="kubectl get pods -n tink-system -l app=image-server --no-headers | grep Running",
    ),
    InfraComponent(
        name="bare-metal-rgd",
        type="infrastructure",
        install_method="kubectl_apply",
        source="/app/manifests/infrastructure/provision-rgd.yaml",
        namespace="kro-system",
        wave=4,
        depends_on=["kro", "tinkerbell-stack"],
        health_check="kubectl get resourcegraphdefinitions baremetalserver",
    ),
    InfraComponent(
        name="cse-telegraf",
        type="platform",
        install_method="kubectl_apply",
        source="/app/manifests/infrastructure/cse-telegraf.yaml",
        namespace="kube-system",
        wave=1,
        depends_on=[],
        health_check="kubectl get ds aws-cse-hybrid-bundle-telegraf -n kube-system -o jsonpath='{.status.numberReady}'",
    ),
    InfraComponent(
        name="influxdb",
        type="platform",
        install_method="kubectl_apply",
        source="/app/manifests/infrastructure/influxdb.yaml",
        namespace="anra",
        wave=2,
        depends_on=[],
        health_check="kubectl get pods -n anra -l app=influxdb --no-headers | grep Running",
    ),
]


def get_missing_infrastructure() -> List[InfraComponent]:
    """Check which infrastructure components are not yet healthy."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

    missing = []
    for component in INFRASTRUCTURE_CATALOG:
        if not component.health_check:
            continue
        result = run_cmd(component.health_check)
        if not result.success or not result.output.strip():
            missing.append(component)
    return missing


def get_infra_component(name: str) -> Optional[InfraComponent]:
    """Look up an infrastructure component by name."""
    for c in INFRASTRUCTURE_CATALOG:
        if c.name == name:
            return c
    return None
