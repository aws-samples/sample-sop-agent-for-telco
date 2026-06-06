# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for Bedrock retry with exponential backoff (Task 2.1)."""

from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from sop_executor import BedrockRetryConfig, invoke_with_retry


def _make_client_error(code):
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "InvokeModel")


class TestInvokeWithRetry:
    """Tests for invoke_with_retry."""

    def test_retry_succeeds_on_first_try(self):
        """No retries needed when call succeeds immediately."""
        agent = MagicMock(return_value="success")
        result = invoke_with_retry(agent, "hello")
        assert result == "success"
        assert agent.call_count == 1

    @patch("sop_executor._time.sleep")
    def test_retry_recovers_from_throttling(self, mock_sleep):
        """First 2 calls throttle, third succeeds."""
        agent = MagicMock(
            side_effect=[
                _make_client_error("ThrottlingException"),
                _make_client_error("ThrottlingException"),
                "recovered",
            ]
        )
        result = invoke_with_retry(agent, "hello")
        assert result == "recovered"
        assert agent.call_count == 3

    @patch("sop_executor._time.sleep")
    def test_retry_exhausts_after_max(self, mock_sleep):
        """All attempts throttle → raises RuntimeError."""
        agent = MagicMock(
            side_effect=[_make_client_error("ThrottlingException")] * BedrockRetryConfig.MAX_RETRIES
        )
        try:
            invoke_with_retry(agent, "hello")
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "retries exhausted" in str(e)

    def test_retry_passes_through_non_retryable(self):
        """AccessDeniedException raises immediately."""
        agent = MagicMock(side_effect=_make_client_error("AccessDeniedException"))
        try:
            invoke_with_retry(agent, "hello")
            assert False, "Should have raised"
        except ClientError as e:
            assert e.response["Error"]["Code"] == "AccessDeniedException"
        assert agent.call_count == 1

    @patch("sop_executor._time.sleep")
    def test_retry_backoff_doubles(self, mock_sleep):
        """Sleep durations double: 1, 2, 4, 8."""
        agent = MagicMock(
            side_effect=[
                _make_client_error("ThrottlingException"),
                _make_client_error("ThrottlingException"),
                _make_client_error("ThrottlingException"),
                _make_client_error("ThrottlingException"),
                "ok",
            ]
        )
        invoke_with_retry(agent, "hello")
        sleeps = [call[0][0] for call in mock_sleep.call_args_list]
        assert sleeps == [1, 2, 4, 8]
