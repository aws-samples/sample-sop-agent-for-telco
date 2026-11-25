"""workshop-check.sh: the facilitator pin override turns a FAIL into a WARN only
for the exact approved commit."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts" / "workshop-check.sh").read_text()


def _functions() -> str:
    """check_source_pin, PIN_OVERRIDE_FILE and pin_override, without running main."""
    start = SCRIPT.index("check_source_pin() {")
    end = SCRIPT.index("check_cluster() {")
    return SCRIPT[start:end]


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x"],
        check=True,
    )
    sha = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return tmp_path, sha


def _run(repo_dir: Path, pinned: str, override: str | None, tmp_path: Path) -> str:
    override_file = tmp_path / "override"
    if override is not None:
        override_file.write_text(override)
    stack = json.dumps({"Stacks": [{"Outputs": [{"OutputKey": "WorkshopSourceCommit", "OutputValue": pinned}]}]})
    script = f"""
set -uo pipefail
report() {{ echo "$1|$2|${{3:-}}"; }}
run() {{ "$@"; }}
FACILITATOR="ask"
WORKSHOP_DIR={repo_dir}
STACK_JSON='{stack}'
PIN_OVERRIDE_FILE={override_file}
{_functions()}
check_source_pin
"""
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout.strip()


def test_matching_pin_is_ok(repo, tmp_path):
    d, sha = repo
    assert _run(d, sha, None, tmp_path).startswith("OK|Source pin|")


def test_mismatch_without_override_fails(repo, tmp_path):
    d, _ = repo
    assert _run(d, "a" * 40, None, tmp_path).startswith("FAIL|Source pin|")


def test_override_for_the_checkout_warns_with_the_reason(repo, tmp_path):
    d, sha = repo
    out = _run(d, "a" * 40, f"{sha[:7]} emergency fix for scenario 2\n", tmp_path)
    assert out.startswith("WARN|Source pin|")
    assert "facilitator override: emergency fix for scenario 2" in out


def test_override_for_another_commit_still_fails(repo, tmp_path):
    d, _ = repo
    assert _run(d, "a" * 40, "b" * 40 + " some other build\n", tmp_path).startswith("FAIL|")


def test_short_or_empty_override_is_ignored(repo, tmp_path):
    d, sha = repo
    assert _run(d, "a" * 40, f"{sha[:4]} too short\n", tmp_path).startswith("FAIL|")
    assert _run(d, "a" * 40, "", tmp_path).startswith("FAIL|")


def test_override_file_name_is_documented():
    assert re.search(r'PIN_OVERRIDE_FILE="\$\{PIN_OVERRIDE_FILE:-\$HOME/\.workshop-pin-override\}"', SCRIPT)
