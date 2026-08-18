"""Regression tests for the firmware version comparison fix.

Lexicographic compare on dotted version strings is wrong: '2.10' < '2.9' is
True under str compare ('1' < '9'), and '4.9' < '4.30' is False ('9' > '3').
The split-and-compare-integers helper must reverse both.
"""

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.preflight_reasoner import (
    ReadinessGap,
    _check_firmware,
    _version_lt,
)


def test_version_lt_handles_multi_digit_segments() -> None:
    # The two cases the bug actually mishandled.
    assert _version_lt("2.9", "2.10") is True  # 2.9 < 2.10
    assert _version_lt("2.10", "2.9") is False  # 2.10 NOT < 2.9
    assert _version_lt("4.9", "4.30") is True  # 4.9 < 4.30
    assert _version_lt("4.30", "4.9") is False


def test_version_lt_basic() -> None:
    assert _version_lt("1.0.0", "1.0.1") is True
    assert _version_lt("1.0.1", "1.0.0") is False
    assert _version_lt("1.0.0", "1.0.0") is False  # equal is not less


def test_version_lt_unequal_segment_counts() -> None:
    # Missing segments treated as 0.
    assert _version_lt("4", "4.30") is True  # 4.0 < 4.30
    assert _version_lt("4.30", "4") is False
    assert _version_lt("1.2.3.4", "1.2.3") is False  # extra segments don't drop the comparison
    assert _version_lt("1.2.3", "1.2.3.4") is True


def test_version_lt_empty_strings() -> None:
    # Empty actual = BMC reported no version → flag the gap.
    assert _version_lt("", "4.30") is True
    # Empty minimum = no minimum specified → never flag.
    assert _version_lt("4.30", "") is False
    # Both empty: equal, not less than.
    assert _version_lt("", "") is False


def test_version_lt_non_numeric_segments_fall_back_to_string() -> None:
    # Pre-release tags don't crash; they fall back to lex compare on that segment.
    assert _version_lt("4.30-rc1", "4.30-rc2") is True
    # Non-numeric vs numeric on the same segment: int() raises on "0a", so we
    # fall back to lex compare ("0" < "0a"). Pinned so a future regression
    # that changes the fallback behavior surfaces.
    assert _version_lt("1.0", "1.0a") is True


def test_check_firmware_flags_below_minimum_with_multi_digit() -> None:
    """The end-to-end path that was broken: firmware 4.9 vs minimum 4.30 must be flagged."""
    profile = {"firmware": {"recommended_minimum": {"BIOS": "4.30"}}}
    firmware = [{"name": "BIOS", "version": "4.9"}]
    gaps: list[ReadinessGap] = []
    _check_firmware(profile, firmware, gaps)
    assert len(gaps) == 1
    assert gaps[0].category == "firmware"
    assert gaps[0].field == "BIOS"
    assert gaps[0].actual == "4.9"
    assert gaps[0].expected == "4.30"


def test_check_firmware_does_not_flag_above_minimum_with_multi_digit() -> None:
    """Firmware 2.10 must NOT be flagged below minimum 2.9 (the inverse bug)."""
    profile = {"firmware": {"recommended_minimum": {"iDRAC": "2.9"}}}
    firmware = [{"name": "iDRAC", "version": "2.10"}]
    gaps: list[ReadinessGap] = []
    _check_firmware(profile, firmware, gaps)
    assert gaps == []


def test_check_firmware_no_minimum_returns_early() -> None:
    """No recommended_minimum block means no gaps regardless of firmware versions."""
    profile: dict = {"firmware": {}}
    gaps: list[ReadinessGap] = []
    _check_firmware(profile, [{"name": "BIOS", "version": "1.0"}], gaps)
    assert gaps == []


def test_check_firmware_missing_component_flagged() -> None:
    """Component named in profile but absent from inventory still gets a gap."""
    profile = {"firmware": {"recommended_minimum": {"NIC": "1.0"}}}
    gaps: list[ReadinessGap] = []
    _check_firmware(profile, [{"name": "BIOS", "version": "4.30"}], gaps)
    assert len(gaps) == 1
    assert gaps[0].field == "NIC"
    assert gaps[0].actual is None
