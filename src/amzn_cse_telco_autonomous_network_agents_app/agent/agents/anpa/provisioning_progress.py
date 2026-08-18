# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""ANPA provisioning progress checks: Tinkerbell workflow + EKS node readiness.

Extracted from reconciler.py for cohesion. Read-only k8s probes the state
machine polls to decide when to advance a request from
Provisioning -> WaitingForNodes -> Ready.
"""

from __future__ import annotations

import logging

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

logger = logging.getLogger(__name__)


def _check_tinkerbell_workflow(
    name: str, namespace: str, spec: dict | None = None
) -> bool:
    """Return True when ALL Tinkerbell Workflows for this request have succeeded.

    The EKS-H provisioning RGD names each Workflow ``provision-<hostname>-<hash>``
    and labels it ``hardware: <hostname>``, ``server-group: <groupName>``
    (see ``platform/manifests/infrastructure/provision-rgd.yaml``). ANPA
    looks workflows up by the ``hardware`` label per hostname.

    Args:
        name:      ProvisioningRequest name. Used as a fallback hostname when
                   the spec doesn't list explicit nodes.
        namespace: Namespace where Tinkerbell + the proposal land.
        spec:      Optional ProvisioningRequest spec dict. When supplied,
                   every hostname in ``spec.nodes`` (or ``spec.hostname``)
                   is checked.

    Returns:
        ``True`` if all workflows are ``STATE_SUCCESS``.
        ``False`` if any are pending / not yet created.

    Raises:
        RuntimeError: If any workflow is ``STATE_FAILED``.
    """
    if spec:
        nodes = spec.get("nodes") or [{"hostname": spec.get("hostname", name)}]
        hostnames = [n.get("hostname") for n in nodes if n.get("hostname")]
    else:
        hostnames = [name]

    all_success = True
    for hostname in hostnames:
        result = run_cmd(
            f"kubectl get workflow "
            f"-l hardware={hostname} "
            f"-n {namespace} "
            f"-o jsonpath='{{.items[0].status.state}}' --ignore-not-found",
            timeout=20,
        )
        state: str = result.stdout.strip().strip("'")
        if state == "STATE_SUCCESS":
            logger.debug("Tinkerbell workflow succeeded for hardware %s", hostname)
            continue
        if state == "STATE_FAILED":
            raise RuntimeError(f"Tinkerbell workflow failed for hardware '{hostname}'")
        logger.debug(
            "Tinkerbell workflow for %s: %r", hostname, state or "(pending/not found)"
        )
        all_success = False

    if all_success:
        logger.info("All Tinkerbell workflows succeeded for request '%s'", name)
    return all_success


def _check_eks_node_ready(name: str, spec: dict) -> bool:
    """Return ``True`` when ALL nodes in the request are registered and ``Ready``.

    Supports both single-node (spec.hostname) and multi-node (spec.nodes[])
    formats.

    Returns:
        ``True`` if all nodes exist and have ``Ready`` condition ``True``;
        ``False`` if any node is not yet ready.
    """
    nodes_spec = spec.get("nodes", [])
    if nodes_spec:
        hostnames = [n.get("hostname", "") for n in nodes_spec if n.get("hostname")]
    else:
        hostnames = [spec.get("hostname", name)]

    all_ready = True
    for hostname in hostnames:
        result = run_cmd(
            f"kubectl get node {hostname} "
            f"-o jsonpath='{{.status.conditions[?(@.type==\"Ready\")].status}}' "
            f"--ignore-not-found",
            timeout=20,
        )
        status: str = result.stdout.strip().strip("'")
        if status == "True":
            logger.debug("EKS node '%s' is Ready", hostname)
        else:
            logger.debug(
                "EKS node '%s' status: %r", hostname, status or "(not registered)"
            )
            all_ready = False

    if all_ready:
        logger.info("All %d node(s) Ready for request '%s'", len(hostnames), name)
    return all_ready
