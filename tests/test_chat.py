# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for agent/routers/chat.py — live tools integration (Task 1.6)."""

from unittest.mock import patch, MagicMock


class TestChatAgent:
    """Tests for the Ask ANRA chat endpoint with live tools."""

    def _get_agent_kwargs(self):
        """Helper: invoke chat and capture Agent() constructor kwargs."""
        import asyncio
        from routers.chat import chat, ChatRequest

        mock_agent_instance = MagicMock(return_value="mock response")

        with (
            patch("boto3.Session"),
            patch("strands.models.bedrock.BedrockModel"),
            patch("strands.Agent", return_value=mock_agent_instance) as mock_agent_cls,
            patch("routers.chat.build_live_topology", return_value={"summary": {}, "k8s_nodes": []}),
            patch("routers.chat.build_monitoring_stats_payload", return_value={}),
            patch("event_store.get_recent", return_value=[]),
        ):
            result = asyncio.run(chat(ChatRequest(message="hi")))
        return mock_agent_cls.call_args[1] if mock_agent_cls.call_args else {}, result

    def test_chat_agent_constructed_with_tools(self):
        """Agent is constructed with a tools list of 5 items."""
        kwargs, _ = self._get_agent_kwargs()
        assert "tools" in kwargs
        assert len(kwargs["tools"]) == 5

    def test_chat_system_prompt_mentions_kubectl(self):
        """System prompt explicitly references kubectl tool."""
        kwargs, _ = self._get_agent_kwargs()
        assert "kubectl" in kwargs["system_prompt"]

    def test_chat_handles_empty_topology_gracefully(self):
        """When topology is empty, doesn't crash."""
        _, result = self._get_agent_kwargs()
        assert "response" in result

    def test_chat_returns_response_field(self):
        """Response shape is {"response": str}."""
        _, result = self._get_agent_kwargs()
        assert isinstance(result["response"], str)
