# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for util.aws.aws_session — the shared boto3 session helper."""
from unittest.mock import patch

from amzn_cse_telco_autonomous_network_agents_app.agent.util import aws


class TestAwsSession:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.aws.boto3.Session")
    def test_profile_and_region_passed_through(self, mock_session):
        result = aws.aws_session("my-profile", "us-east-1")
        mock_session.assert_called_once_with(profile_name="my-profile", region_name="us-east-1")
        # the constructed session must be returned straight through
        assert result is mock_session.return_value

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.aws.boto3.Session")
    def test_empty_profile_becomes_none(self, mock_session):
        # Empty string profile must collapse to None (default credential chain),
        # matching the `profile or None` idiom the call sites used inline.
        aws.aws_session("", "us-west-2")
        mock_session.assert_called_once_with(profile_name=None, region_name="us-west-2")

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.aws.boto3.Session")
    def test_defaults_are_none(self, mock_session):
        aws.aws_session()
        mock_session.assert_called_once_with(profile_name=None, region_name=None)
