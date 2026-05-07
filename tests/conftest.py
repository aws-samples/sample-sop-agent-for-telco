# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Shared fixtures for all tests."""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Disable auth for all tests
os.environ["AUTH_PASSWORD"] = ""  # nosec B105 - intentionally empty to disable auth in tests

# Mock strands if not installed (CI environment)
if 'strands' not in sys.modules:
    try:
        import strands
    except ImportError:
        strands_mock = MagicMock()
        sys.modules['strands'] = strands_mock
        sys.modules['strands.models'] = strands_mock.models
        # Make @tool decorator a passthrough
        strands_mock.tool = lambda f: f

# Add project paths
sys.path.insert(0, str(Path(__file__).parent.parent / "sop-agent"))
sys.path.insert(0, str(Path(__file__).parent.parent / "webui" / "backend"))
