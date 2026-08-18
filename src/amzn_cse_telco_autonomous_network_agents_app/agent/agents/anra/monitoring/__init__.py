# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ANRA monitoring — detection data sources.

Each module owns one detection concern (metrics, thresholds, anomalies,
CloudWatch events, hardware event logs). The ANRA run loop composes them.
"""
