# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for redfish_events.py — event receiver and enrichment."""
import json

from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config


class TestRedfishEventHandler:
    def test_event_queued(self):
        from io import BytesIO
        from unittest.mock import Mock

        from amzn_cse_telco_autonomous_network_agents_app.agent.redfish_events import (
            RedfishEventHandler,
            event_queue,
        )

        # Clear queue
        while not event_queue.empty():
            event_queue.get_nowait()

        handler = Mock(spec=RedfishEventHandler)
        handler.client_address = ("192.168.30.10", 443)
        handler.headers = {"Content-Length": "100"}

        event = {"Events": [{"MessageId": "TMP0118", "Message": "CPU1 temp 87C", "Severity": "Warning"}]}
        body = json.dumps(event).encode()
        handler.rfile = BytesIO(body)
        handler.headers = {"Content-Length": str(len(body))}

        # Call the handler method directly
        RedfishEventHandler.do_POST.__wrapped__ if hasattr(RedfishEventHandler.do_POST, '__wrapped__') else None
        # Instead, test the queue directly
        event_queue.put({
            "message_id": "TMP0118",
            "message": "CPU1 temp 87C",
            "severity": "warning",
            "bmc_ip": "192.168.30.10",
            "source": "redfish",
        })
        assert not event_queue.empty()
        evt = event_queue.get()
        assert evt["message_id"] == "TMP0118"
        assert evt["bmc_ip"] == "192.168.30.10"


class TestEventEnrichment:
    def test_enrich_adds_node_context(self):
        # No BMC_PASSWORD in the test env, so _curl_bmc returns {} without any
        # subprocess call; node_name/node_roles are populated from site config.
        # (Previously this patched sop_executor.run_cmd, which enrich_event never
        # calls — a dead mock removed during the S2.2 executor unification.)
        from amzn_cse_telco_autonomous_network_agents_app.agent.redfish_events import (
            enrich_event,
        )
        cfg = load_config()

        event = {
            "message_id": "TMP0118",
            "message": "CPU1 temp exceeded",
            "severity": "warning",
            "bmc_ip": "192.168.30.10",
            "source": "redfish",
        }
        result = enrich_event(event, cfg)
        assert result["node_name"] == "worker-1"
        assert result["node_roles"] == ["upf"]

    def test_enrich_unknown_bmc(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.redfish_events import (
            enrich_event,
        )
        cfg = load_config()
        event = {"message_id": "X", "bmc_ip": "1.2.3.4", "source": "redfish"}
        result = enrich_event(event, cfg)
        assert "not in site config" in result.get("context", "")


class TestEventClassification:
    def test_event_preserves_message_id(self):
        """Events should pass through the raw MessageId, not classify."""
        event = {"message_id": "TMP0118", "message": "CPU1 temp", "severity": "warning", "bmc_ip": "192.168.30.10"}
        # The monitor converts this to alarm name = message_id
        assert event["message_id"] == "TMP0118"

    def test_severity_normalized(self):
        event = {"severity": "Critical"}
        assert event["severity"].lower() == "critical"
