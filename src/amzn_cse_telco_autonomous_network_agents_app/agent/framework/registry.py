# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Extension registry — one mechanism, two read modes.

A factory and a tool list are the same thing at different cardinalities: SELECT
picks one of N by a config-driven key (the ``topology.get_provider()`` shape),
COLLECT gathers all registered implementations (the ``BASE_TOOLS`` shape). The
registry unifies both.

Extension *kinds* are declared once via :func:`Registry.define_kind` with a
resolution mode and (optionally) a contract ABC. Implementations are then
registered against a kind; registration validates the object against the kind's
contract, so a malformed adapter fails loudly at boot rather than at first use.

Failure posture (customer-operated framework): misconfiguration the customer can
fix fails loud — unknown kind, duplicate name, contract violation, and an unknown
SELECT key all raise. Runtime/environmental fallbacks (e.g. a model missing from
a Bedrock account) are handled by the consumer, not here.

A module-global :data:`registry` instance mirrors the cached module-global idiom
already used by ``topology._provider``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Optional

from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import (
    ExtensionKind,
    ResolutionMode,
)


class _KindSpec:
    """Internal: the declaration of one extension kind."""

    def __init__(
        self, kind: ExtensionKind, mode: ResolutionMode, contract: Optional[type]
    ) -> None:
        self.kind = kind
        self.mode = mode
        self.contract = contract
        self.items: dict[str, Any] = {}


class Registry:
    """Thread-safe registry of extension implementations keyed by kind and name."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._kinds: dict[ExtensionKind, _KindSpec] = {}

    # ── Declaration ──

    def define_kind(
        self,
        kind: ExtensionKind,
        *,
        mode: ResolutionMode,
        contract: Optional[type] = None,
    ) -> None:
        """Declare an extension kind.

        Idempotent only for an identical re-declaration (same mode + contract);
        a conflicting re-declaration raises, since two callers disagreeing on a
        kind's shape is a bug.
        """
        with self._lock:
            existing = self._kinds.get(kind)
            if existing is not None:
                if existing.mode != mode or existing.contract is not contract:
                    msg = (
                        f"Extension kind {kind!r} already declared with a "
                        f"different mode/contract; refusing to redeclare."
                    )
                    raise ValueError(msg)
                return
            self._kinds[kind] = _KindSpec(kind, mode, contract)

    # ── Registration ──

    def register(
        self, kind: ExtensionKind, name: str, obj: Any, *, override: bool = False
    ) -> None:
        """Register ``obj`` under ``(kind, name)``.

        Raises if the kind is undeclared, the name is already taken (unless
        ``override=True``), or ``obj`` violates the kind's contract.

        ``override`` is an internal capability (replacing a core-supplied
        default; tests). The public ``@register`` / ``@register_tool``
        decorators deliberately do not expose it — a duplicate name at the
        plugin boundary is a bug, and the duplicate-raise is the right default.
        """
        with self._lock:
            spec = self._kinds.get(kind)
            if spec is None:
                msg = f"Cannot register {name!r}: extension kind {kind!r} is not declared."
                raise KeyError(msg)
            if not name:
                msg = f"Cannot register an empty name under kind {kind!r}."
                raise ValueError(msg)
            if name in spec.items and not override:
                msg = (
                    f"Duplicate registration for {kind.value}:{name!r}. Pass "
                    f"override=True to intentionally replace it."
                )
                raise ValueError(msg)
            self._validate_contract(spec, name, obj)
            spec.items[name] = obj

    @staticmethod
    def _validate_contract(spec: _KindSpec, name: str, obj: Any) -> None:
        """Enforce the kind's contract on ``obj`` (no-op when no contract is set).

        Instances only. Accepting the class itself would let ``get_one(...)``
        return an uninstantiated type whose methods mis-bind on first call
        (``run(cmd)`` would bind ``cmd`` to ``self``) — failing at first use,
        the exact failure this boot-time check exists to prevent. A lazily
        instantiated "factory kind" is a separate notion, deferred until a seam
        actually needs it.
        """
        contract = spec.contract
        if contract is None:
            return
        if not isinstance(obj, contract):
            msg = (
                f"{spec.kind.value}:{name!r} must be an INSTANCE of "
                f"{contract.__name__}, got {obj!r}."
            )
            raise TypeError(msg)

    # ── Resolution ──

    def get_one(self, kind: ExtensionKind, name: str) -> Any:
        """Resolve a single implementation by name (SELECT kinds).

        Unknown name raises — no silent fallback. The error lists the known names
        so a config typo is fixable from the message alone.
        """
        with self._lock:
            spec = self._require_kind(kind)
            if spec.mode is not ResolutionMode.SELECT:
                msg = (
                    f"get_one is only valid for SELECT kinds; {kind!r} is "
                    f"{spec.mode.value}. Use get_all."
                )
                raise ValueError(msg)
            obj = spec.items.get(name)
            if obj is None:
                known = sorted(spec.items)
                msg = (
                    f"No {kind.value} registered under {name!r}. "
                    f"Known: {known or '(none)'}."
                )
                raise KeyError(msg)
            return obj

    def get_all(self, kind: ExtensionKind) -> list[Any]:
        """Return all registered implementations for a kind (COLLECT kinds).

        Ordered by first registration; an ``override=True`` re-registration
        replaces in place and does not re-sequence. Empty when nothing is
        registered — callers must tolerate an empty extension set.
        """
        with self._lock:
            spec = self._require_kind(kind)
            if spec.mode is not ResolutionMode.COLLECT:
                msg = (
                    f"get_all is only valid for COLLECT kinds; {kind!r} is "
                    f"{spec.mode.value}. Use get_one."
                )
                raise ValueError(msg)
            return list(spec.items.values())

    # ── Introspection (for /about and tests) ──

    def kinds(self) -> list[ExtensionKind]:
        """Return the declared extension kinds."""
        with self._lock:
            return list(self._kinds)

    def names(self, kind: ExtensionKind) -> list[str]:
        """Return the registered names for a kind."""
        with self._lock:
            return list(self._require_kind(kind).items)

    def _require_kind(self, kind: ExtensionKind) -> _KindSpec:
        spec = self._kinds.get(kind)
        if spec is None:
            msg = f"Extension kind {kind!r} is not declared."
            raise KeyError(msg)
        return spec


# ── Module-global instance + the standard kinds ──

registry = Registry()

# Declare the extension points the framework ships with. Declaring them here (at
# import) means the seams exist before any plugin or core module registers into
# them. SELECT kinds carry their contract; COLLECT kinds (tool, agent_role) bind
# to convention rather than an ABC.
registry.define_kind(ExtensionKind.TOOL, mode=ResolutionMode.COLLECT)
registry.define_kind(ExtensionKind.AGENT_ROLE, mode=ResolutionMode.COLLECT)


def _declare_select_kinds() -> None:
    """Declare SELECT kinds with their contracts.

    The contracts import is kept inside the function (not at module top) so the
    registry module stays import-light and import-order-independent as concrete
    SELECT implementations — which will import this registry — migrate in later
    CRs. (No cycle exists today; contracts depends only on ``abc``.)
    """
    from amzn_cse_telco_autonomous_network_agents_app.agent.framework.contracts import (
        CommandIntegration,
        TopologyProvider,
    )

    registry.define_kind(
        ExtensionKind.CLI, mode=ResolutionMode.SELECT, contract=CommandIntegration
    )
    registry.define_kind(
        ExtensionKind.TOPOLOGY, mode=ResolutionMode.SELECT, contract=TopologyProvider
    )
    # METRIC_SOURCE / MODEL contracts are declared as their seams are migrated
    # onto the registry in later CRs.


_declare_select_kinds()


# ── Decorators ──


def register_tool(name: str) -> Callable[[Any], Any]:
    """Decorator: register a Strands ``@tool`` callable under the TOOL kind.

    Usage::

        @register_tool("query_grafana")
        @tool
        def query_grafana(panel: str) -> str: ...
    """

    def _decorator(obj: Any) -> Any:
        registry.register(ExtensionKind.TOOL, name, obj)
        return obj

    return _decorator


def register(kind: ExtensionKind, name: str) -> Callable[[Any], Any]:
    """Decorator: register the decorated object under an arbitrary kind.

    The decorated object is registered as-is. For a contract (SELECT) kind the
    registry requires an *instance*, so decorate at the point an instance is
    produced, or register imperatively::

        registry.register(ExtensionKind.CLI, "telcocli", TelcoCliIntegration())

    The decorator form fits objects that are themselves the registrable value
    (e.g. a factory callable under a COLLECT kind).
    """

    def _decorator(obj: Any) -> Any:
        registry.register(kind, name, obj)
        return obj

    return _decorator
