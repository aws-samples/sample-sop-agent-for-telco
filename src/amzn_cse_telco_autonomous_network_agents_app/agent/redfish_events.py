# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Redfish Event Receiver + Enrichment — direct HTTPS to BMC.

Receives push events from iDRAC/iLO webhook, enriches with live context
by querying the BMC's own message registry + thermal/power state directly.
"""

import json
import logging
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from queue import Queue

log = logging.getLogger(__name__)
event_queue: Queue = Queue()


def _curl_bmc(bmc_ip, path, username="root", password=None, timeout=10):
    if password is None:
        password = os.getenv("BMC_PASSWORD", "")
    if not password:
        log.error(
            "_curl_bmc skipped for %s%s: BMC_PASSWORD env not set "
            "(wire from k8s Secret matching node.bmc.password_secret)",
            bmc_ip,
            path,
        )
        return {}
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc import curl_bmc

        r = curl_bmc(f"https://{bmc_ip}{path}", username, password, timeout=timeout)
        return json.loads(r.stdout) if r.returncode == 0 else {}
    except Exception:
        return {}


class RedfishEventHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
            for evt in data.get("Events", [data]):
                event_queue.put(
                    {
                        "message_id": evt.get("MessageId", ""),
                        "message": evt.get("Message", ""),
                        "severity": evt.get("Severity", "Warning").lower(),
                        "bmc_ip": self.client_address[0],
                        "source": "redfish",
                        "raw": evt,
                    }
                )
                log.info(f"Event: {evt.get('MessageId')} from {self.client_address[0]}")
        except json.JSONDecodeError:
            log.warning(f"Invalid JSON from {self.client_address[0]}")
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def start_receiver(port=8080):
    server = HTTPServer(("0.0.0.0", port), RedfishEventHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    log.info(f"Redfish event receiver on :{port}")
    return t


def enrich_event(event, config):
    """Enrich a Redfish event with vendor resolution + live state via direct HTTPS."""
    node = config.get_node_by_bmc(event["bmc_ip"])
    if not node:
        event["context"] = "BMC not in site config"
        return event

    bmc_ip = event["bmc_ip"]
    username = node.bmc.username

    # 1. Lookup vendor resolution from BMC registry
    registry = _curl_bmc(bmc_ip, "/redfish/v1/Registries/Messages/EEMIRegistry", username)
    entry = registry.get("Messages", {}).get(event["message_id"], {})
    event["vendor_description"] = entry.get("Description", "")
    event["vendor_resolution"] = entry.get("Resolution", "")
    event["vendor_severity"] = entry.get("Severity", "")

    # 2. Live thermal
    thermal = _curl_bmc(bmc_ip, node.bmc.thermal_path, username)
    if thermal:
        event["live_thermal"] = {
            "temperatures": {
                t["Name"]: t["ReadingCelsius"] for t in thermal.get("Temperatures", []) if t.get("ReadingCelsius")
            },
            "fans": {
                f["FanName"]: f"{f['Reading']} RPM ({f.get('Status', {}).get('Health', '?')})"
                for f in thermal.get("Fans", [])
                if f.get("Reading")
            },
        }

    # 3. Live power
    power = _curl_bmc(bmc_ip, node.bmc.power_path, username)
    if power:
        event["live_power"] = [
            {"name": p.get("Name"), "watts": p.get("PowerConsumedWatts"), "health": p.get("Status", {}).get("Health")}
            for p in power.get("PowerControl", [])
        ]

    # 4. Running pods on affected node
    try:
        r = subprocess.run(
            [
                "kubectl",
                "get",
                "pods",
                "--all-namespaces",
                f"--field-selector=spec.nodeName={node.ssm_id}",
                "--no-headers",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        event["running_pods"] = r.stdout.strip()
    except Exception:
        pass

    event["node_name"] = node.name
    event["node_roles"] = node.roles
    return event


def subscribe_bmc(node, webhook_url):
    """Create Redfish EventSubscription on a BMC via direct HTTPS."""
    bmc_password = os.getenv("BMC_PASSWORD", "")
    if not bmc_password:
        log.error(
            "subscribe_bmc skipped for %s: BMC_PASSWORD env not set "
            "(wire from k8s Secret matching node.bmc.password_secret)",
            node.name,
        )
        return None
    payload = json.dumps({"Destination": webhook_url, "EventTypes": ["Alert"], "Protocol": "Redfish"})
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc import curl_bmc

        r = curl_bmc(
            f"https://{node.bmc.ip}/redfish/v1/EventService/Subscriptions",
            node.bmc.username,
            bmc_password,
            method="POST",
            data=payload,
            extra_args=["-H", "Content-Type: application/json"],
            timeout=10,
        )
        ok = r.returncode == 0 and "error" not in r.stdout.lower()
        log.info(f"Subscribe {node.bmc.ip}: {'OK' if ok else 'FAILED'}")
    except Exception as e:
        log.info(f"Subscribe {node.bmc.ip}: FAILED ({e})")
