# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""FastAPI router for ANPA provisioning management API.

Exposes CRUD operations over ``ProvisioningRequest`` custom resources and
provides a retry/cancel workflow for failed requests.
"""

import json
import os
import tempfile
import textwrap
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

router = APIRouter(tags=["provisioning"])

# Default namespace for ProvisioningRequest CRs
_DEFAULT_NAMESPACE = "anpa-system"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ProvisioningRequestCreate(BaseModel):
    """Payload for creating a new ProvisioningRequest CR."""

    hostname: str
    bmcAddress: str = ""
    osImage: str = "ubuntu-2204-eks-hybrid"
    nodeRole: str = "worker"
    namespace: str = _DEFAULT_NAMESPACE


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/provisioning/requests")
def list_provisioning_requests():
    """List all ProvisioningRequest CRs across all namespaces.

    Returns a compact summary of each request (name, namespace, hostname,
    phase, message, lastUpdated).
    """
    result = run_cmd("kubectl get provisioningrequests -A -o json", timeout=30)
    if not result.success:
        raise HTTPException(
            status_code=502,
            detail=f"kubectl failed: {result.stderr}",
        )
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to parse kubectl output: {exc}")

    items: list = data.get("items", [])
    requests = [_summarise_request(item) for item in items]
    return {"requests": requests, "count": len(requests)}


@router.post("/api/provisioning/requests", status_code=201)
def create_provisioning_request(req: ProvisioningRequestCreate):
    """Create a new ProvisioningRequest CR in the target namespace.

    The CR is applied via ``kubectl apply`` and initialised in the ``Pending``
    phase so that the ANPA reconciler will pick it up on its next pass.
    """
    cr_name = req.hostname.lower().replace("_", "-").replace(".", "-")
    namespace = req.namespace or _DEFAULT_NAMESPACE
    timestamp = datetime.now(timezone.utc).isoformat()

    yaml_doc = textwrap.dedent(f"""\
        apiVersion: provisioning.anpa.aws.io/v1alpha1
        kind: ProvisioningRequest
        metadata:
          name: {cr_name}
          namespace: {namespace}
          labels:
            provisioning.anpa.aws.io/managed: "true"
          annotations:
            provisioning.anpa.aws.io/created-at: "{timestamp}"
        spec:
          hostname: {req.hostname}
          bmcAddress: {req.bmcAddress}
          osImage: {req.osImage}
          nodeRole: {req.nodeRole}
        status:
          phase: Pending
    """)

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".yaml", prefix="anpa-pr-")
    try:
        with os.fdopen(tmp_fd, "w") as fh:
            fh.write(yaml_doc)
        result = run_cmd(f"kubectl apply -f {tmp_path}", timeout=30)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not result.success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create ProvisioningRequest: {result.stderr}",
        )

    return {
        "name": cr_name,
        "namespace": namespace,
        "hostname": req.hostname,
        "phase": "Pending",
        "created_at": timestamp,
    }


@router.get("/api/provisioning/requests/{name}")
def get_provisioning_request(name: str, namespace: str = _DEFAULT_NAMESPACE):
    """Get the full ProvisioningRequest CR for *name*.

    Query parameter ``namespace`` selects the Kubernetes namespace
    (default: ``anpa-system``).
    """
    result = run_cmd(
        f"kubectl get provisioningrequest {name} -n {namespace} -o json",
        timeout=15,
    )
    if not result.success:
        stderr = result.stderr or ""
        if "not found" in stderr.lower():
            raise HTTPException(
                status_code=404,
                detail=f"ProvisioningRequest '{name}' not found in namespace '{namespace}'",
            )
        raise HTTPException(status_code=502, detail=f"kubectl failed: {stderr}")

    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to parse kubectl output: {exc}")


@router.get("/api/provisioning/requests/{name}/diagnosis")
def get_provisioning_diagnosis(name: str, namespace: str = _DEFAULT_NAMESPACE):
    """Return the most recent AI-authored diagnosis for *name*, if any.

    The reconciler invokes the failure handler when a ProvisioningRequest
    exhausts retries; the handler persists its structured diagnosis under
    ``ANPA_DIAGNOSIS_DIR`` (default ``/var/lib/anpa/diagnoses``). This
    endpoint reads that record back so operators can review the diagnosis
    without scraping logs.

    Read-only.
    """
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler import get_last_diagnosis  # noqa: WPS433

    payload = get_last_diagnosis(namespace, name)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no diagnosis recorded for {namespace}/{name} — either the "
                f"request hasn't failed, the failure handler hasn't run yet, "
                f"or persistence is disabled"
            ),
        )
    return payload


@router.post("/api/provisioning/requests/{name}/retry")
def retry_provisioning_request(name: str, namespace: str = _DEFAULT_NAMESPACE):
    """Reset a Failed ProvisioningRequest back to Pending.

    The ANPA reconciler will pick it up on its next pass and attempt
    provisioning again.  Only meaningful when the current phase is ``Failed``.
    """
    patch_payload = json.dumps({
        "status": {
            "phase": "Pending",
            "message": "Manually reset to Pending for retry",
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
        }
    })
    result = run_cmd(
        f"kubectl patch provisioningrequest {name} -n {namespace} "
        f"--type merge -p '{patch_payload}'",
        timeout=15,
    )
    if not result.success:
        stderr = result.stderr or ""
        if "not found" in stderr.lower():
            raise HTTPException(
                status_code=404,
                detail=f"ProvisioningRequest '{name}' not found in namespace '{namespace}'",
            )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset ProvisioningRequest: {stderr}",
        )

    return {
        "name": name,
        "namespace": namespace,
        "phase": "Pending",
        "message": "Reset to Pending; reconciler will retry on next pass",
    }


@router.delete("/api/provisioning/requests/{name}", status_code=204)
def delete_provisioning_request(name: str, namespace: str = _DEFAULT_NAMESPACE):
    """Cancel and permanently delete a ProvisioningRequest CR.

    Uses ``--ignore-not-found`` so that calling this endpoint on an already
    deleted request is idempotent.
    """
    result = run_cmd(
        f"kubectl delete provisioningrequest {name} -n {namespace} --ignore-not-found",
        timeout=30,
    )
    if not result.success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete ProvisioningRequest '{name}': {result.stderr}",
        )
    return None  # 204 No Content


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _summarise_request(item: dict) -> dict:
    """Return a compact summary dict from a raw ProvisioningRequest CR."""
    meta = item.get("metadata", {})
    spec = item.get("spec", {})
    status = item.get("status", {})
    nodes_spec = spec.get("nodes", [])
    return {
        "name": meta.get("name"),
        "namespace": meta.get("namespace"),
        "site": spec.get("site"),
        "cluster": spec.get("clusterName"),
        "nodes": len(nodes_spec) if nodes_spec else (1 if spec.get("hostname") else 0),
        "phase": status.get("phase", "Pending"),
        "message": status.get("message", ""),
        "lastUpdated": status.get("lastUpdated") or meta.get("creationTimestamp", ""),
    }
