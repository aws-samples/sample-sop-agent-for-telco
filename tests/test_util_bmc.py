# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for util.bmc.curl_bmc — the hardened BMC curl helper (S2.9).

The security contract: the credential is passed on curl's stdin config, never on
argv (so it can't leak via /proc/<pid>/cmdline) and never through a shell (so a
special char in a rotated password can't break or inject).
"""

from unittest.mock import MagicMock, patch

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.util import bmc


class TestCurlBmc:
    def _run(self, **kwargs):
        captured = {}

        def fake_run(args, **kw):
            captured["args"] = args
            captured["input"] = kw.get("input")
            captured["shell"] = kw.get("shell", False)
            return MagicMock(returncode=0, stdout="{}", stderr="")

        with patch.object(bmc.subprocess, "run", side_effect=fake_run):
            bmc.curl_bmc("https://10.0.0.1/redfish/v1", "root", "s3cr3t", **kwargs)
        return captured

    def test_credential_never_on_argv(self):
        c = self._run()
        joined = " ".join(c["args"])
        assert "s3cr3t" not in joined
        assert "root:s3cr3t" not in joined

    def test_credential_passed_via_stdin_config(self):
        c = self._run()
        assert 'user = "root:s3cr3t"' in c["input"]
        assert c["args"][:3] == ["curl", "--config", "-"]

    def test_never_uses_shell(self):
        c = self._run()
        assert c["shell"] is False

    def test_special_chars_in_password_escaped_not_shell_broken(self):
        # A password with a shell metachar and a quote must not break anything:
        # it rides in the stdin config with " and \ escaped, never on argv.
        captured = {}

        def fake_run(args, **kw):
            captured["args"] = args
            captured["input"] = kw.get("input")
            return MagicMock(returncode=0, stdout="{}", stderr="")

        with patch.object(bmc.subprocess, "run", side_effect=fake_run):
            bmc.curl_bmc("https://h/x", "root", 'p$`"\\w', timeout=5)

        assert 'p$`' not in " ".join(captured["args"])  # not on argv
        # quote and backslash are escaped in the config payload
        assert '\\"' in captured["input"] and "\\\\" in captured["input"]

    def test_patch_method_and_data_on_argv(self):
        c = self._run(method="PATCH", data='{"x":1}')
        assert "-X" in c["args"] and "PATCH" in c["args"]
        assert "--data" in c["args"] and '{"x":1}' in c["args"]

    def test_max_time_defaults_to_timeout(self):
        c = self._run(timeout=7)
        i = c["args"].index("--max-time")
        assert c["args"][i + 1] == "7"

    def test_subprocess_timeout_exceeds_curl_max_time(self):
        # The subprocess kill budget must be larger than curl's --max-time so
        # curl exits cleanly (code 28) before the process is force-killed.
        captured = {}

        def fake_run(args, **kw):
            captured["args"] = args
            captured["subprocess_timeout"] = kw.get("timeout")
            return MagicMock(returncode=0, stdout="{}", stderr="")

        with patch.object(bmc.subprocess, "run", side_effect=fake_run):
            bmc.curl_bmc("https://h/x", "root", "pw", timeout=10)

        i = captured["args"].index("--max-time")
        assert captured["args"][i + 1] == "10"  # curl budget
        assert captured["subprocess_timeout"] == 10 + bmc._KILL_BUFFER_S  # kill budget > curl

    def test_hard_timeout_returns_code_28_not_raise(self):
        # A subprocess TimeoutExpired must degrade to a curl-28-shaped result,
        # not propagate as an unhandled exception (matches the old run_cmd path).
        def raise_timeout(*a, **kw):
            raise bmc.subprocess.TimeoutExpired(cmd="curl", timeout=kw.get("timeout", 0))

        with patch.object(bmc.subprocess, "run", side_effect=raise_timeout):
            result = bmc.curl_bmc("https://h/x", "root", "pw", timeout=3)

        assert result.returncode == 28
        assert result.stdout == ""


class TestConfigInjection:
    """curl --config is line-oriented: a newline in the credential must NOT be
    able to start a new curl directive (config injection)."""

    def test_newline_in_password_rejected(self):
        # A password with an embedded newline + a curl directive must be refused,
        # not silently turned into `output = /etc/passwd` on its own config line.
        with pytest.raises(bmc.CredentialError):
            bmc._curl_config("root", "cal\nvin\noutput = /etc/passwd")

    def test_carriage_return_rejected(self):
        with pytest.raises(bmc.CredentialError):
            bmc._curl_config("root", "pass\rword")

    def test_control_char_rejected(self):
        with pytest.raises(bmc.CredentialError):
            bmc._curl_config("ro\x00ot", "pass")

    def test_curl_bmc_propagates_rejection(self):
        # The rejection surfaces from the public entry point too (no curl spawned).
        with patch.object(bmc.subprocess, "run") as mock_run:
            with pytest.raises(bmc.CredentialError):
                bmc.curl_bmc("https://h/x", "root", "a\nurl = http://evil")
        mock_run.assert_not_called()

    def test_clean_credential_payload_has_single_trailing_newline(self):
        payload = bmc._curl_config("root", "s3cr3t")
        assert payload == 'user = "root:s3cr3t"\n'
        assert payload.count("\n") == 1

    def test_printable_specials_stay_on_one_line(self):
        # A `#` and a quote in the password must stay inside the single quoted
        # value (# is literal inside quotes; " is escaped), not start a new line.
        payload = bmc._curl_config("root", 'p#a"ss')
        assert payload.count("\n") == 1  # only the terminator
        assert '\\"' in payload  # the quote was escaped, not left to close early

    def test_trailing_newline_from_secret_file_tolerated(self):
        # A secret read from a k8s Secret/file often has a trailing newline; that
        # is benign and must NOT be rejected (only EMBEDDED control chars are).
        payload = bmc._curl_config("root", "s3cr3t\n")
        assert payload == 'user = "root:s3cr3t"\n'
