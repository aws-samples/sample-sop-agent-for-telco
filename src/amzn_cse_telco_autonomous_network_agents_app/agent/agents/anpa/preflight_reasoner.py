# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Hardware preflight reasoner — answers "is this server ready for NF X?".

Two-tier design (matches "deterministic plumbing + AI reasoning" principle):

  Tier 1 — deterministic checker (this module): compares Redfish-discovered
  hardware against an NF profile and emits a structured ``ReadinessReport``.
  No AI needed; results are fully reproducible.

  Tier 2 — AI explainer (optional, behind ``ENABLE_PREFLIGHT_AI``):
  given the deterministic report, asks a Strands agent to produce a
  human-readable diagnosis with remediation pointers. Falls back to a
  template-rendered explanation when the AI tier is disabled or fails.

The reasoner is read-only. It never mutates BIOS, BMC, or cluster state.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, asdict
from itertools import zip_longest
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Profiles ship under platform/configs/nf-profiles/<nf>.yaml. Override with
# NF_PROFILES_DIR for tests or for an operator-supplied catalogue.
_DEFAULT_PROFILES_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "configs" / "nf-profiles"
)


@dataclass
class ReadinessGap:
    severity: str           # "required" | "recommended"
    category: str           # "bios" | "cpu" | "memory" | "network" | "firmware" | "placement"
    field: str
    expected: Any
    actual: Any
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReadinessReport:
    nf: str
    hostname: str
    ready: bool
    gaps: list[ReadinessGap] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "nf": self.nf,
            "hostname": self.hostname,
            "ready": self.ready,
            "gaps": [g.to_dict() for g in self.gaps],
            "summary": self.summary,
        }


def load_profile(nf: str, profiles_dir: Path | None = None) -> dict:
    """Load <profiles_dir>/<nf>.yaml. Raises FileNotFoundError if absent."""
    base = profiles_dir or Path(os.environ.get("NF_PROFILES_DIR", _DEFAULT_PROFILES_DIR))
    path = base / f"{nf}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"NF profile not found: {path}")
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


# ---------------------------------------------------------------------------
# Deterministic check helpers
# ---------------------------------------------------------------------------


def _check_bios(profile: dict, bios: dict, gaps: list[ReadinessGap]) -> None:
    bios_req = (profile.get("bios") or {}).get("required") or {}
    bios_rec = (profile.get("bios") or {}).get("recommended") or {}
    for severity, block in (("required", bios_req), ("recommended", bios_rec)):
        for key, expected in block.items():
            actual = bios.get(key)
            if actual is None:
                gaps.append(ReadinessGap(
                    severity, "bios", key, expected, None,
                    "BIOS attribute not exposed by BMC",
                ))
                continue
            if str(actual) != str(expected):
                gaps.append(ReadinessGap(
                    severity, "bios", key, expected, actual,
                    f"BIOS attribute is '{actual}', expected '{expected}'",
                ))


def _check_cpu(profile: dict, hwi: dict, gaps: list[ReadinessGap]) -> None:
    cpu_req = profile.get("cpu") or {}
    actual_cores = int((hwi.get("cpu") or {}).get("cores") or hwi.get("cpu_cores") or 0)
    min_cores = int(cpu_req.get("min_cores") or 0)
    if min_cores and actual_cores < min_cores:
        gaps.append(ReadinessGap(
            "required", "cpu", "cores", min_cores, actual_cores,
            f"only {actual_cores} cores; NF needs ≥ {min_cores}",
        ))


def _check_memory(profile: dict, hwi: dict, gaps: list[ReadinessGap]) -> None:
    mem_req = profile.get("memory") or {}
    actual_gib = int((hwi.get("memory") or {}).get("totalGiB") or hwi.get("memory_gib") or 0)
    min_gib = int(mem_req.get("min_total_gib") or 0)
    if min_gib and actual_gib < min_gib:
        gaps.append(ReadinessGap(
            "required", "memory", "totalGiB", min_gib, actual_gib,
            f"only {actual_gib} GiB; NF needs ≥ {min_gib} GiB",
        ))


def _version_lt(a: str, b: str) -> bool:
    """Return True if version *a* is less than *b* component-wise.

    Lexicographic compare is wrong for multi-digit segments — '2.10' < '2.9'
    is True under str compare ('1' < '9'), but semantically 2.10 > 2.9.
    Numeric segments are compared as ints; non-numeric segments fall back to
    string compare so pre-release tags like '4.30-rc1' don't crash.
    Missing segments are treated as 0 ('4.30' vs '4' → 4.30 > 4).

    Empty inputs: an empty actual is treated as < any non-empty minimum
    (BMC reported no version → flag the gap). An empty minimum is treated
    as >= any actual (no minimum specified → never flag). This avoids the
    `int("")` ValueError that would otherwise fall through to a misleading
    lex compare.
    """
    if not a:
        return bool(b)
    if not b:
        return False
    for x, y in zip_longest(a.split("."), b.split("."), fillvalue="0"):
        try:
            xi, yi = int(x), int(y)
        except ValueError:
            xi, yi = x, y
        if xi != yi:
            return xi < yi
    return False


def _check_firmware(
    profile: dict,
    firmware: list[dict],
    gaps: list[ReadinessGap],
) -> None:
    minimums = (profile.get("firmware") or {}).get("recommended_minimum") or {}
    if not minimums:
        return
    by_name = {(item.get("name") or "").lower(): item.get("version", "") for item in firmware}
    for component, min_ver in minimums.items():
        actual = next(
            (v for n, v in by_name.items() if component.lower() in n),
            None,
        )
        if actual is None:
            gaps.append(ReadinessGap(
                "recommended", "firmware", component, min_ver, None,
                f"component '{component}' not in firmware inventory",
            ))
        elif _version_lt(str(actual), str(min_ver)):
            gaps.append(ReadinessGap(
                "recommended", "firmware", component, min_ver, actual,
                f"firmware {actual} < recommended minimum {min_ver}",
            ))


# ---------------------------------------------------------------------------
# Tier 1 — deterministic assessment
# ---------------------------------------------------------------------------


def assess_readiness(
    nf: str,
    hostname: str,
    hardware_inventory: dict,
    bios_attributes: dict,
    firmware_inventory: list[dict] | None = None,
    profile: dict | None = None,
) -> ReadinessReport:
    """Compare discovered hardware against the NF profile and report gaps.

    Args:
        nf:                  Profile name to load (e.g. ``"upf"``).
        hostname:            For report attribution.
        hardware_inventory:  HardwareInventory ``.spec`` dict (or compatible).
        bios_attributes:     Output of :func:`bios_inspector.get_bios_attributes`.
        firmware_inventory:  Output of :func:`bios_inspector.get_firmware_inventory`.
        profile:             Pre-loaded profile dict (for tests). When ``None``
                             the profile is loaded by name.

    Returns:
        :class:`ReadinessReport`.
    """
    if profile is None:
        profile = load_profile(nf)
    gaps: list[ReadinessGap] = []
    _check_bios(profile, bios_attributes or {}, gaps)
    _check_cpu(profile, hardware_inventory or {}, gaps)
    _check_memory(profile, hardware_inventory or {}, gaps)
    _check_firmware(profile, firmware_inventory or [], gaps)

    required_gaps = [g for g in gaps if g.severity == "required"]
    ready = len(required_gaps) == 0
    summary = _render_summary(nf, hostname, ready, gaps)
    return ReadinessReport(nf=nf, hostname=hostname, ready=ready, gaps=gaps, summary=summary)


def _render_summary(nf: str, hostname: str, ready: bool, gaps: list[ReadinessGap]) -> str:
    if not gaps:
        return f"{hostname} is READY for {nf.upper()}: all checks passed."
    req = [g for g in gaps if g.severity == "required"]
    rec = [g for g in gaps if g.severity == "recommended"]
    lines = []
    if ready:
        lines.append(f"{hostname} is READY for {nf.upper()} with {len(rec)} recommendation(s).")
    else:
        lines.append(
            f"{hostname} is NOT READY for {nf.upper()}: {len(req)} required gap(s), "
            f"{len(rec)} recommendation(s)."
        )
    for g in gaps:
        prefix = "  ✗" if g.severity == "required" else "  ~"
        lines.append(f"{prefix} {g.category}.{g.field}: {g.detail}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tier 2 — optional AI explanation (off by default; deterministic still wins)
# ---------------------------------------------------------------------------


def ai_explain(report: ReadinessReport) -> str:
    """Return a human-readable explanation. Uses Strands when available."""
    if not os.environ.get("ENABLE_PREFLIGHT_AI"):
        return report.summary
    try:
        from strands import Agent  # noqa: WPS433
        from amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver import get_model
        from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import (
            ModelTier,
        )
    except ImportError:
        return report.summary

    prompt = (
        f"You are a telco infrastructure engineer. A bare-metal server's "
        f"readiness for the {report.nf.upper()} network function was assessed:\n\n"
        f"{report.summary}\n\n"
        f"For each gap, briefly explain why it matters for this NF and "
        f"recommend a single concrete remediation step. Be terse."
    )
    try:
        agent = Agent(model=get_model(ModelTier.SMART), tools=[])
        return str(agent(prompt))
    except Exception as exc:  # pragma: no cover
        logger.warning("AI explainer failed; falling back to deterministic summary: %s", exc)
        return report.summary
