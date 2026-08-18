# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Correlation agent — re-exports from existing correlator module."""

from amzn_cse_telco_autonomous_network_agents_app.agent.correlator import build_graph, correlate, correlate_batch, get_graph, rca_investigate

__all__ = ["build_graph", "correlate", "correlate_batch", "get_graph", "rca_investigate"]
