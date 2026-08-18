# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Plugin discovery — import customer-listed modules so they self-register.

Discovery is explicit and auditable: the customer lists dotted module paths under
``plugins:`` in agent-config.yaml. At boot we import each one; the module's
``@register_tool`` / ``@register`` decorators fire on import and populate the
registry. This works identically on EKS (module on a mounted volume / PYTHONPATH)
and on Bedrock AgentCore (module baked into the image) — no wheel build required,
which is why config-listed paths are used instead of Python entry-points.

Failure posture: a listed plugin that fails to import is fatal. The customer
asked for it explicitly; silently dropping it would yield an agent that "can't do
X" with no error. We re-raise with the offending module named, so the pod
CrashLoops with an actionable message rather than starting half-configured.

Plugin loading is applied once at startup. A later change to the ``plugins`` list
(via config hot-reload) does not load or unload modules — Python cannot safely
unload a module whose tools an in-flight loop is holding — so such a change takes
effect only on pod restart.
"""

from __future__ import annotations

import importlib
import logging

logger = logging.getLogger(__name__)


class PluginLoadError(RuntimeError):
    """Raised when a configured plugin module cannot be imported."""


def load_plugins(paths: list[str]) -> list[str]:
    """Import each plugin module so its registrations take effect.

    Args:
        paths: dotted module paths from ``cfg.plugins``. Empty/falsy entries are
            skipped; an empty list is a no-op (the default — no plugins).

    Returns:
        The list of module paths successfully imported, in order.

    Raises:
        PluginLoadError: if any listed module fails to import. Failing loud at
            boot is intentional (see module docstring).
    """
    loaded: list[str] = []
    for path in paths:
        name = path.strip() if isinstance(path, str) else ""
        if not name:
            continue
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 — re-raised below with context
            msg = f"Failed to load plugin module {name!r}: {exc}"
            raise PluginLoadError(msg) from exc
        loaded.append(name)
        logger.info("Loaded plugin module: %s", name)

    if loaded:
        logger.info("Loaded %d plugin module(s): %s", len(loaded), ", ".join(loaded))
    return loaded
