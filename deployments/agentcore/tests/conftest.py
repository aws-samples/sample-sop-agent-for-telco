"""Pytest fixtures for AgentCore tests."""

import sys
from pathlib import Path

# Stub the bedrock_agentcore module if it's not installed (keeps tests working
# in environments without the SDK). The real SDK is only required at runtime.
try:
    import bedrock_agentcore  # noqa: F401
except ImportError:
    import types

    fake_runtime = types.ModuleType("bedrock_agentcore.runtime")

    class _FakeApp:
        def entrypoint(self, fn):  # decorator no-op
            return fn

        def run(self):  # noqa: D401
            """Stand-in for the real local server."""
            print("FakeApp.run() — no-op (real bedrock_agentcore SDK not installed)")

    fake_runtime.BedrockAgentCoreApp = _FakeApp
    fake_pkg = types.ModuleType("bedrock_agentcore")
    fake_pkg.runtime = fake_runtime
    sys.modules["bedrock_agentcore"] = fake_pkg
    sys.modules["bedrock_agentcore.runtime"] = fake_runtime

# Add the parent agent/ directory to sys.path so imports inside main.py resolve
_repo_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_repo_root / "agent"))
