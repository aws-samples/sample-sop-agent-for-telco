# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Hardened BMC/Redfish curl helper.

Single place to invoke ``curl`` against a BMC Redfish endpoint with credentials.
The username/password are passed to curl via a config file on **stdin**
(``curl --config -``), so the credential is never:

  * interpolated into a shell string (a ``$``/backtick/quote in a rotated
    password could break the command or inject shell), or
  * placed on the argv (visible to any local process via
    ``/proc/<pid>/cmdline``).

Everything else (URL, method, data, flags) goes on argv with ``shell=False``.
This replaces the several ad-hoc ``f"curl ... -u {user}:{pw} ..."`` call sites
that each hardcoded the credential into a command string.
"""

from __future__ import annotations

import subprocess  # noqa: S404 - argv form, shell=False, no cred on argv
from typing import Optional

# Seconds the subprocess kill timeout is allowed to exceed curl's own --max-time.
# curl should hit --max-time and exit cleanly with code 28 first; the buffer
# absorbs process startup/teardown so subprocess.run doesn't kill curl before it
# can. Mirrors the old ``run_cmd(cmd, timeout=timeout + 5)`` convention.
_KILL_BUFFER_S = 5


class CredentialError(ValueError):
    """Raised when a BMC credential contains characters unsafe for the curl config."""


def _curl_config(username: str, password: str) -> str:
    """Build the ``--config`` payload carrying the credential.

    curl's config parser is line-oriented: a raw newline terminates the current
    directive, so a credential containing ``\\n``/``\\r`` could inject arbitrary
    curl directives (e.g. ``output = /etc/passwd``). Control characters are never
    legitimate in a BMC username/password, so we reject them outright rather than
    try to escape them. Inside the quoted value, ``\\`` and ``"`` are then
    backslash-escaped per curl's config syntax. The payload is fed on stdin,
    never written to disk.
    """
    # Tolerate surrounding whitespace: a secret read from a k8s Secret/file often
    # carries a trailing newline, which is benign. Strip it, then reject any
    # REMAINING control char (an embedded newline/CR is the injection vector and
    # is never legitimate in a BMC credential).
    username = username.strip()
    password = password.strip()
    cred = f"{username}:{password}"
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in cred):
        # No line/position info: never echo the credential itself.
        msg = "BMC credential contains control characters (embedded newline/CR/etc.), refusing to build curl config"
        raise CredentialError(msg)
    cred = cred.replace("\\", "\\\\").replace('"', '\\"')
    # Invariant: exactly one newline (the terminator); none inside the value.
    assert "\n" not in cred and "\r" not in cred  # noqa: S101 - guarded above
    return f'user = "{cred}"\n'


def curl_bmc(
    url: str,
    username: str,
    password: str,
    *,
    method: Optional[str] = None,
    data: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
    timeout: int = 15,
    max_time: Optional[int] = None,
    insecure: bool = True,
) -> subprocess.CompletedProcess:
    """Run a curl request to ``url`` with credentials passed via stdin config.

    Args:
        url: full request URL (e.g. ``https://10.0.0.1/redfish/v1/...``).
        username / password: BMC credentials. Sent via ``curl --config -``.
        method: HTTP method for -X (e.g. "PATCH"); None uses curl's default GET.
        data: request body for --data (e.g. a JSON PATCH payload).
        extra_args: additional non-credential curl args (e.g. ["-H", "...",
            "-w", "%{http_code}", "-o", "/dev/null"]). Never put credentials here.
        timeout: curl's request budget (``--max-time``). The subprocess is given
            ``timeout + _KILL_BUFFER_S`` so curl times out cleanly (exit 28)
            before the subprocess is force-killed.
        max_time: overrides curl's ``--max-time`` when set (defaults to
            ``timeout``); the subprocess kill still gets the buffer on top.
        insecure: pass -k (BMC certs are typically self-signed).

    Returns:
        The completed subprocess (returncode / stdout / stderr). On a hard
        subprocess timeout, returns a synthetic result with returncode 28
        (curl's "operation timed out") so callers keying on ``returncode`` see a
        failure rather than an unhandled ``TimeoutExpired``.
    """
    curl_max_time = max_time if max_time is not None else timeout
    args = ["curl", "--config", "-", "--silent"]
    if insecure:
        args.append("--insecure")
    args += ["--max-time", str(curl_max_time)]
    if method:
        args += ["-X", method]
    if data is not None:
        args += ["--data", data]
    if extra_args:
        args += extra_args
    args.append(url)

    try:
        return subprocess.run(  # noqa: S603 - argv form, shell=False, creds on stdin
            args,
            input=_curl_config(username, password),
            capture_output=True,
            text=True,
            timeout=curl_max_time + _KILL_BUFFER_S,
        )
    except subprocess.TimeoutExpired:
        # curl didn't self-terminate within its budget + buffer. Surface a
        # curl-28-shaped result so callers checking returncode degrade gracefully
        # (the old run_cmd path returned a failure result rather than raising).
        return subprocess.CompletedProcess(args, 28, stdout="", stderr="operation timed out")
