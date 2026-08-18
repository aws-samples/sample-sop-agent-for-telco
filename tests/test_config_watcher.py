# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for config hot-reload: config_store and config_watcher."""

import threading
import time

import pytest
import yaml

from amzn_cse_telco_autonomous_network_agents_app.agent.config import SiteConfig
from amzn_cse_telco_autonomous_network_agents_app.agent.core import config_store
from amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store import (
    get_config,
    set_config,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.core.config_watcher import (
    ConfigWatcher,
)


@pytest.fixture(autouse=True)
def reset_config_store():
    """Reset the global config store between tests."""
    config_store._config = None
    yield
    config_store._config = None


def _make_valid_yaml(cluster_name="test-cluster", extra=None):
    """Generate valid YAML config content."""
    data = {
        "version": "1",
        "cluster": {"name": cluster_name, "region": "us-west-1"},
        "bedrock": {"region": "us-west-2"},
        "monitoring": {"influxdb_url": "http://localhost:8086"},
    }
    if extra:
        data.update(extra)
    return yaml.dump(data)


class TestConfigStore:
    def test_get_config_before_set_returns_none(self):
        assert get_config() is None

    def test_get_config_returns_set_config(self):
        cfg = SiteConfig(cluster_name="my-cluster")
        set_config(cfg)
        result = get_config()
        assert result is not None
        assert result.cluster_name == "my-cluster"

    def test_thread_safety(self):
        """10 concurrent threads all set and get config without data corruption."""
        errors = []
        barrier = threading.Barrier(10)

        def writer(idx):
            try:
                barrier.wait(timeout=5)
                cfg = SiteConfig(cluster_name=f"cluster-{idx}")
                set_config(cfg)
                # Read back — should be a valid SiteConfig (possibly from another thread)
                result = get_config()
                assert result is not None
                assert result.cluster_name.startswith("cluster-")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Thread safety errors: {errors}"


class TestConfigWatcher:
    def test_file_change_triggers_reload(self, tmp_path):
        """Write new config content to file and verify reload fires within 5s."""
        config_file = tmp_path / "agent-config.yaml"
        config_file.write_text(_make_valid_yaml("original-cluster"))

        reloaded = threading.Event()
        reloaded_cfg = {}

        def on_reload(new_cfg):
            reloaded_cfg["cfg"] = new_cfg
            reloaded.set()

        watcher = ConfigWatcher(path=str(config_file), role="anra", on_reload=on_reload)
        watcher.start()

        try:
            # Wait a moment for the watcher to start, then modify the file
            time.sleep(0.5)
            config_file.write_text(_make_valid_yaml("updated-cluster"))

            # Should reload within 5 seconds (1s poll + 2s debounce + margin)
            assert reloaded.wait(timeout=5), "Reload did not trigger within 5s"
            assert reloaded_cfg["cfg"].cluster_name == "updated-cluster"
        finally:
            watcher.stop()

    def test_invalid_config_keeps_old(self, tmp_path):
        """Invalid YAML after change should keep old config (not crash)."""
        config_file = tmp_path / "agent-config.yaml"
        config_file.write_text(_make_valid_yaml("good-cluster"))

        # Set initial config
        initial_cfg = SiteConfig(cluster_name="good-cluster")
        set_config(initial_cfg)

        reload_called = threading.Event()

        def on_reload(new_cfg):
            # This should NOT be called for invalid config
            set_config(new_cfg)
            reload_called.set()

        watcher = ConfigWatcher(path=str(config_file), role="anra", on_reload=on_reload)
        watcher.start()

        try:
            time.sleep(0.5)
            # Write config that will fail validation (missing cluster.name)
            bad_config = {
                "version": "1",
                "cluster": {"name": "", "region": "us-west-1"},
                "bedrock": {"region": "us-west-2"},
                "monitoring": {"influxdb_url": "http://localhost:8086"},
            }
            config_file.write_text(yaml.dump(bad_config))

            # Wait enough time for potential reload
            time.sleep(4)

            # on_reload should NOT have been called
            assert not reload_called.is_set(), "on_reload was called for invalid config"
            # Old config should be preserved
            assert get_config().cluster_name == "good-cluster"
        finally:
            watcher.stop()

    def test_stop_stops_watching(self, tmp_path):
        """After stop(), file changes should not trigger reload."""
        config_file = tmp_path / "agent-config.yaml"
        config_file.write_text(_make_valid_yaml("original"))

        reload_called = threading.Event()

        def on_reload(new_cfg):
            reload_called.set()

        watcher = ConfigWatcher(path=str(config_file), role="anra", on_reload=on_reload)
        watcher.start()
        time.sleep(0.5)

        # Stop the watcher
        watcher.stop()

        # Now modify the file
        config_file.write_text(_make_valid_yaml("after-stop"))

        # Wait and verify no reload happened
        time.sleep(4)
        assert not reload_called.is_set(), "Reload triggered after stop()"
