"""reattach-ue.sh against a stub kubectl: the retry must get a fresh window."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "free5gc" / "reattach-ue.sh"

# State machine: each scale-up creates pod N. Pod FAIL_POD gets no address and
# the AMF logs "Duplicated" for it; any other pod gets 10.63.0.N. Scaling a pod
# to 0 also logs a teardown line the next attempt must not count as its own.
STUB = r"""#!/usr/bin/env bash
d="$STUB_DIR"; n=$(cat "$d/n" 2>/dev/null || echo 0); a="$*"; now=$(date +%s)
case "$a" in
  *"--replicas=0"*) [ "$n" -ge 1 ] && echo "$now" > "$d/teardown" ;;
  *"--replicas=1"*) echo $((n+1)) > "$d/n"; echo "$now" > "$d/up" ;;
  *"wait --for=delete"*) sleep 2 ;;
  *"get pods"*) [ "$n" -ge 1 ] && printf 'pr-%s' "$n" ;;
  *"logs -n"*" pr-"*)
     p=${a##*pr-}; p=${p%% *}
     # The PDU session takes a few seconds after the pod starts.
     [ $((now - $(cat "$d/up"))) -ge 3 ] || exit 0
     [ "$p" = "$FAIL_POD" ] || echo "PDU address received: 10.63.0.$p" ;;
  *"logs deploy/"*)
     since=${a##*--since=}; since=${since%%s*}
     # The rejected attempt's own failure.
     [ "$n" = "$FAIL_POD" ] && echo "Duplicated PDU session ID[1]"
     # The previous pod's teardown, logged when it was scaled to 0. It belongs
     # to the previous attempt, so a fresh window must not see it.
     t=$(cat "$d/teardown" 2>/dev/null || echo 0)
     [ "$t" -ge $((now - since)) ] && echo "Release SmContext Failed; Duplicated PDU session ID[1]" ;;
esac
exit 0
"""


def _run(tmp_path: Path, fail_pod: str) -> subprocess.CompletedProcess:
    stub = tmp_path / "kubectl"
    stub.write_text(STUB)
    stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "STUB_DIR": str(tmp_path), "FAIL_POD": fail_pod, "DEADLINE_SECONDS": "40"}
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=60)


def test_first_attempt_succeeds(tmp_path):
    r = _run(tmp_path, "0")
    assert r.returncode == 0, r.stdout
    assert "UE re-attached: 10.63.0.1 (attempt 1)" in r.stdout


def test_retry_after_stale_session_succeeds(tmp_path):
    r = _run(tmp_path, "1")
    assert r.returncode == 0, r.stdout
    assert "stale session" in r.stdout
    assert "UE re-attached: 10.63.0.2 (attempt 2)" in r.stdout
