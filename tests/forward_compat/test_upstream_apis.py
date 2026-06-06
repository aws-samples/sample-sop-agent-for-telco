# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Sentinel tests for upstream API stability (Task 3.6).

These only run in the weekly forward-compat workflow, NOT in the default test suite.
"""

import inspect


def test_strands_agent_signature_stable():
    """Agent constructor accepts (model, tools, system_prompt)."""
    from strands import Agent

    params = inspect.signature(Agent.__init__).parameters
    for required in ["model", "tools", "system_prompt"]:
        assert required in params, f"Strands Agent removed param: {required}"


def test_strands_tool_decorator_exists():
    """@tool decorator is importable from strands."""
    from strands import tool

    assert callable(tool)


def test_bedrock_model_importable():
    """BedrockModel is importable from strands.models.bedrock."""
    from strands.models.bedrock import BedrockModel

    assert callable(BedrockModel)
