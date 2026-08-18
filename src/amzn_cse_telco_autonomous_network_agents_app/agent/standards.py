# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""3GPP TS 28.532 / ITU-T X.733 alarm model constants."""

ALARM_TYPES = {
    "communications-alarm": 1,
    "quality-of-service-alarm": 2,
    "processing-error-alarm": 3,
    "equipment-alarm": 4,
    "environmental-alarm": 5,
}

PROBABLE_CAUSES = {
    "adapter-error": 1,
    "bandwidth-reduced": 5,
    "call-establishment-error": 7,
    "communications-protocol-error": 8,
    "communications-subsystem-failure": 9,
    "congestion": 11,
    "cpu-cycles-limit-exceeded": 13,
    "degraded-signal": 15,
    "equipment-malfunction": 19,
    "excessive-error-rate": 21,
    "heating-ventilation-cooling-system-problem": 25,
    "io-device-error": 28,
    "lan-error": 30,
    "loss-of-frame": 33,
    "loss-of-signal": 34,
    "out-of-memory": 39,
    "performance-degraded": 42,
    "power-problem": 44,
    "processor-problem": 46,
    "queue-size-exceeded": 48,
    "software-error": 54,
    "storage-capacity-problem": 57,
    "temperature-unacceptable": 58,
    "threshold-crossed": 59,
    "timing-problem": 60,
    "transmit-failure": 62,
    "underlying-resource-unavailable": 63,
}

SEVERITIES = ["critical", "major", "minor", "warning", "cleared"]


def build_managed_object_dn(node_name: str, nf_class: str, instance_id: str = "1") -> str:
    """Build 3GPP TS 28.622 Distinguished Name."""
    return f"SubNetwork=ANRA,ManagedElement={node_name},{nf_class}={instance_id}"


# Auto-classification rules for alarms not in config
_CLASSIFY_RULES = [
    # (name pattern, alarm_type, probable_cause_code)
    ("k8s_crashloopbackoff", "processing-error-alarm", 54),  # software-error
    ("k8s_oomkilled", "processing-error-alarm", 39),  # out-of-memory
    ("k8s_unexpectedadmissionerror", "processing-error-alarm", 63),  # underlying-resource-unavailable
    ("k8s_failedscheduling", "processing-error-alarm", 51),  # resource-at-or-nearing-capacity
    ("k8s_backoff", "processing-error-alarm", 54),  # software-error
    ("hw_thermal", "environmental-alarm", 58),  # temperature-unacceptable
    ("hw_power", "equipment-alarm", 44),  # power-problem
    ("transport_link", "communications-alarm", 34),  # loss-of-signal
    ("transport_error", "communications-alarm", 21),  # excessive-error-rate
    ("transport_latency", "quality-of-service-alarm", 52),  # response-time-excessive
]


def classify_alarm(name: str) -> dict:
    """Auto-classify an alarm that's not in config. Returns 3GPP fields or empty defaults."""
    name_lower = name.lower()
    for pattern, alarm_type, cause_code in _CLASSIFY_RULES:
        if pattern in name_lower:
            cause_name = next((k for k, v in PROBABLE_CAUSES.items() if v == cause_code), "")
            return {
                "alarmType": alarm_type,
                "probableCauseCode": cause_code,
                "probableCauseString": cause_name,
                "perceivedSeverity": "major",
                "managedObjectClass": "ManagedElement",
            }
    # Default: threshold-crossed for anything unrecognized
    return {
        "alarmType": "quality-of-service-alarm",
        "probableCauseCode": 59,  # threshold-crossed
        "probableCauseString": "threshold-crossed",
        "perceivedSeverity": "warning",
        "managedObjectClass": "ManagedElement",
    }
