# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Hardware event-log monitoring for ANRA.

Polls each node's baseboard management controller (BMC) System Event Log (SEL)
over Redfish (iDRAC/iLO) and emits an alert for each new Warning/Critical entry,
enriched with the vendor's description + suggested resolution from the BMC
message registry.
"""

import json
import logging
import os

log = logging.getLogger(__name__)

_sel_last_id: dict = {}  # bmc_ip -> last seen SEL entry ID
_sel_initialized: bool = False


def poll_redfish_sel():
    """Poll iDRAC/iLO System Event Log for new Warning/Critical entries."""
    global _sel_initialized
    from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config

    cfg = load_config()
    alerts = []
    for node in cfg.nodes:
        if not node.bmc.ip:
            continue
        try:
            bmc_pass = os.getenv("BMC_PASSWORD", "")
            from amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc import curl_bmc

            r = curl_bmc(
                f"https://{node.bmc.ip}/redfish/v1/Managers/iDRAC.Embedded.1/LogServices/Sel/Entries?$top=10",
                node.bmc.username,
                bmc_pass,
                timeout=15,
            )
            if r.returncode != 0:
                continue
            data = json.loads(r.stdout)
            members = data.get("Members", [])
            last_id = _sel_last_id.get(node.bmc.ip, "0")

            if not _sel_initialized:
                if members:
                    _sel_last_id[node.bmc.ip] = max(m.get("Id", "0") for m in members)
                continue

            for entry in members:
                entry_id = entry.get("Id", "0")
                if entry_id <= last_id:
                    continue
                severity = entry.get("Severity", "OK")
                if severity in ("Critical", "Warning"):
                    vendor_desc, vendor_resolution = _get_vendor_resolution(node, entry, bmc_pass)
                    alerts.append(
                        {
                            "name": entry.get("MessageId", "hw_sel_event"),
                            "severity": severity.lower(),
                            "service_impact": entry.get("Message", ""),
                            "probable_cause": entry.get("SensorType", ""),
                            "vendor_description": vendor_desc,
                            "vendor_resolution": vendor_resolution,
                            "source": "redfish-sel",
                            "bmc_ip": node.bmc.ip,
                            "node_name": node.name,
                            "node_roles": node.roles,
                        }
                    )
            if members:
                _sel_last_id[node.bmc.ip] = max(m.get("Id", "0") for m in members)
        except Exception as e:
            log.debug(f"SEL poll failed for {node.bmc.ip}: {e}")

    if not _sel_initialized:
        _sel_initialized = True
        log.info(f"SEL initialized: {len(_sel_last_id)} BMCs seeded")
    return alerts


def _get_vendor_resolution(node, entry, bmc_pass):
    """Fetch vendor resolution from BMC registry for a SEL entry."""
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc import curl_bmc

        reg = json.loads(
            curl_bmc(
                f"https://{node.bmc.ip}/redfish/v1/Registries/Messages/EEMIRegistry",
                node.bmc.username,
                bmc_pass,
                timeout=15,
            ).stdout
        )
        msgs = reg.get("Messages", {})
        msg_id = entry.get("MessageId", "")
        sel_msg = entry.get("Message", "").lower()

        reg_entry = msgs.get(msg_id, {})
        if not reg_entry and sel_msg:
            sensor = entry.get("SensorType", "").lower()
            for k, v in msgs.items():
                desc = v.get("Description", "").lower()
                if sensor and k[:3].lower() in sel_msg[:20].lower():
                    if any(w in desc for w in sel_msg.split()[:5] if len(w) > 4):
                        reg_entry = v
                        break
            if not reg_entry:
                prefix_map = {
                    "power supply": "PSU", "temperature": "TMP",
                    "fan": "FAN", "memory": "MEM", "voltage": "VLT",
                }
                for keyword, prefix in prefix_map.items():
                    if keyword in sensor:
                        candidates = {
                            k: v for k, v in msgs.items()
                            if k.startswith(prefix) and "input" in v.get("Description", "").lower()
                        }
                        if candidates:
                            reg_entry = next(iter(candidates.values()))
                            break
        return reg_entry.get("Description", ""), reg_entry.get("Resolution", "")
    except Exception as e:
        log.debug(f"Non-critical: vendor resolution lookup failed: {e}")
        return "", ""
