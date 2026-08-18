# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Strategy Engine — select provisioning strategy based on BMCProfile + quirks.

Maps discovered BMC capabilities + known quirks → a ProvisioningStrategy that
tells the Boot Configurer exactly what to do. Deterministic (no AI).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ProvisioningStrategy:
    """What the Boot Configurer should do to provision this server."""

    name: str = "default"
    description: str = ""
    mount_method: str = "virtual_media_cd"  # virtual_media_cd | rfs_network_file
    boot_method: str = "standard_redfish_boot_override"  # standard_redfish_boot_override | dell_oem_first_boot_device
    hookos_variant: str = "standard"  # standard | patched-ice
    pre_steps: list = field(default_factory=list)
    post_steps: list = field(default_factory=list)
    fallback_name: str | None = None


class StrategyEngine:
    """Selects and manages provisioning strategies."""

    def select(self, profile, quirks: dict) -> ProvisioningStrategy:
        """Select the primary provisioning strategy for this BMC.

        Priority:
        1. Quirk file has explicit strategies list → use first as primary
        2. Profile shows boot_override_writable=False → infer Dell OEM
        3. Default standard Redfish strategy

        Args:
            profile: BMCProfile from bmc_profiler.
            quirks: Matched quirk dict from quirks/loader.

        Returns:
            ProvisioningStrategy for this hardware.
        """
        strategies = quirks.get("strategies", [])

        if strategies:
            primary = strategies[0]
            strategy = self._parse_strategy(primary)
            logger.info(
                "Strategy selected from quirk: %s (%s)",
                strategy.name,
                strategy.description,
            )
            return strategy

        # Infer from profile if no quirk strategies
        if not profile.boot_override_writable and profile.oem_namespace == "Dell":
            strategy = ProvisioningStrategy(
                name="inferred_dell_oem",
                description="Inferred: Dell OEM boot (boot override read-only)",
                mount_method="virtual_media_cd",
                boot_method="dell_oem_first_boot_device",
                hookos_variant="patched-ice" if profile.requires_custom_hookos else "standard",
            )
            logger.info("Strategy inferred from profile: %s", strategy.name)
            return strategy

        # Default
        strategy = ProvisioningStrategy(
            name="default",
            description="Standard Redfish boot override + VirtualMedia",
            hookos_variant="patched-ice" if profile.requires_custom_hookos else "standard",
        )
        logger.info("Using default strategy")
        return strategy

    def get_fallback_for_failure(
        self, strategy_name: str, failure_type: str, quirks: dict
    ) -> ProvisioningStrategy | None:
        """Get the next strategy in the fallback chain for a given failure.

        Args:
            strategy_name: The strategy that just failed.
            failure_type: The classified failure (e.g., VIRTUAL_MEDIA_MOUNT_FAILED).
            quirks: The matched quirk dict.

        Returns:
            Next ProvisioningStrategy to try, or None if exhausted.
        """
        strategies = quirks.get("strategies", [])
        strategy_map = {s.get("name"): s for s in strategies}

        current = strategy_map.get(strategy_name)
        if not current:
            return None

        fallback_name = current.get("fallback_name")
        if not fallback_name:
            return None

        fallback_def = strategy_map.get(fallback_name)
        if not fallback_def:
            return None

        strategy = self._parse_strategy(fallback_def)
        logger.info(
            "Fallback strategy for %s after %s: %s",
            strategy_name,
            failure_type,
            strategy.name,
        )
        return strategy

    def _parse_strategy(self, raw: dict) -> ProvisioningStrategy:
        """Parse a strategy dict from YAML into a ProvisioningStrategy."""
        return ProvisioningStrategy(
            name=raw.get("name", "unnamed"),
            description=raw.get("description", ""),
            mount_method=raw.get("mount_method", "virtual_media_cd"),
            boot_method=raw.get("boot_method", "standard_redfish_boot_override"),
            hookos_variant=raw.get("hookos_variant", "standard"),
            pre_steps=raw.get("pre_steps", []),
            post_steps=raw.get("post_steps", []),
            fallback_name=raw.get("fallback_name"),
        )
