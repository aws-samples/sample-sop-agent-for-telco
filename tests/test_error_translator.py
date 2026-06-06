# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for error_translator module (Task 2.3)."""

from error_translator import translate


class TestErrorTranslator:
    """Tests for friendly error translation."""

    def test_translate_access_denied_bedrock(self):
        result = translate("AccessDeniedException: not authorized to perform: bedrock:InvokeModel")
        assert result["matched"] is True
        assert "Bedrock model access" in result["friendly"]

    def test_translate_throttling(self):
        result = translate("ThrottlingException: Rate exceeded")
        assert result["matched"] is True
        assert "rate-limiting" in result["friendly"]

    def test_translate_oom_killed(self):
        result = translate("container was OOMKilled")
        assert result["matched"] is True
        assert "memory" in result["friendly"]

    def test_translate_unknown_error(self):
        result = translate("some completely unknown error xyz123")
        assert result["matched"] is False
        assert "unexpected" in result["friendly"]

    def test_translate_long_error_truncated(self):
        long_error = "x" * 1000
        result = translate(long_error)
        assert len(result["raw"]) == 500
