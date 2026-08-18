# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ANDA deployment tools - Helm, rollout, and NF verification."""

import logging

from strands import tool

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd, tool_call, tool_result

log = logging.getLogger(__name__)


@tool
def helm_install(release: str, chart: str, namespace: str, values: str = "", set_args: str = "") -> str:
    """Install a Helm chart as a new release.

    Args:
        release: Helm release name (e.g., 'open5gs-amf')
        chart: Chart reference (e.g., 'oci://public.ecr.aws/eks-hybrid-telco/helm/open5gs')
        namespace: Target Kubernetes namespace
        values: Path to values YAML file (optional)
        set_args: Comma-separated --set overrides (optional, e.g., 'image.tag=2.7.1,replicas=2')
    """
    tool_call("helm_install", f"release={release} chart={chart} ns={namespace}")
    cmd = f"helm install {release} {chart} -n {namespace} --create-namespace --wait --timeout 5m"
    if values:
        cmd += f" -f {values}"
    if set_args:
        for s in set_args.split(","):
            cmd += f" --set {s.strip()}"
    result = run_cmd(cmd, timeout=360)
    tool_result("Installed" if result.success else "Failed", result.success)
    return result.output


@tool
def helm_upgrade(release: str, chart: str, namespace: str, values: str = "", set_args: str = "") -> str:
    """Upgrade an existing Helm release to a new chart version.

    Args:
        release: Helm release name
        chart: Chart reference (with version, e.g., 'oci://.../open5gs --version 2.7.1')
        namespace: Target Kubernetes namespace
        values: Path to values YAML file (optional)
        set_args: Comma-separated --set overrides (optional)
    """
    tool_call("helm_upgrade", f"release={release} chart={chart} ns={namespace}")
    cmd = f"helm upgrade {release} {chart} -n {namespace} --wait --timeout 5m"
    if values:
        cmd += f" -f {values}"
    if set_args:
        for s in set_args.split(","):
            cmd += f" --set {s.strip()}"
    result = run_cmd(cmd, timeout=360)
    tool_result("Upgraded" if result.success else "Failed", result.success)
    return result.output


@tool
def helm_rollback(release: str, namespace: str, revision: int = 0) -> str:
    """Rollback a Helm release to a previous revision.

    Args:
        release: Helm release name
        namespace: Kubernetes namespace
        revision: Target revision number (0 = previous revision)
    """
    tool_call("helm_rollback", f"release={release} ns={namespace} rev={revision}")
    cmd = f"helm rollback {release} {revision} -n {namespace} --wait --timeout 5m"
    result = run_cmd(cmd, timeout=360)
    tool_result("Rolled back" if result.success else "Failed", result.success)
    return result.output


@tool
def helm_status(release: str, namespace: str) -> str:
    """Get the current status of a Helm release.

    Args:
        release: Helm release name
        namespace: Kubernetes namespace
    """
    tool_call("helm_status", f"release={release} ns={namespace}")
    result = run_cmd(f"helm status {release} -n {namespace} --show-resources", timeout=30)
    tool_result("OK" if result.success else "Not found", result.success)
    return result.output


@tool
def wait_rollout(resource: str, namespace: str, timeout: int = 300) -> str:
    """Wait for a Kubernetes deployment/statefulset rollout to complete.

    Args:
        resource: Resource type/name (e.g., 'deployment/open5gs-amf' or 'statefulset/open5gs-udr')
        namespace: Kubernetes namespace
        timeout: Timeout in seconds (default 300)
    """
    tool_call("wait_rollout", f"resource={resource} ns={namespace} timeout={timeout}s")
    result = run_cmd(
        f"kubectl rollout status {resource} -n {namespace} --timeout={timeout}s",
        timeout=timeout + 30,
    )
    tool_result("Ready" if result.success else "Timed out", result.success)
    return result.output


@tool
def kubectl_apply(manifest_path: str, namespace: str = "") -> str:
    """Apply a Kubernetes YAML manifest file.

    Args:
        manifest_path: Path to YAML file or directory
        namespace: Target namespace (optional, uses manifest metadata if not set)
    """
    tool_call("kubectl_apply", f"path={manifest_path}")
    ns_flag = f"-n {namespace}" if namespace else ""
    result = run_cmd(f"kubectl apply -f {manifest_path} {ns_flag}", timeout=60)
    tool_result("Applied" if result.success else "Failed", result.success)
    return result.output


@tool
def verify_nf_registration(nf_type: str, namespace: str = "core") -> str:
    """Verify a 5G network function is registered with the NRF.

    Checks the NRF's registered NF list via its SBI API. This confirms the NF
    has successfully started and announced itself to the service registry.

    Args:
        nf_type: 3GPP NF type (e.g., 'AMF', 'SMF', 'UPF', 'AUSF', 'UDM')
        namespace: Namespace where NRF is running (default 'core')
    """
    tool_call("verify_nf_registration", f"nf_type={nf_type} ns={namespace}")
    # Query NRF's NFInstances endpoint via kubectl port-forward or ClusterIP
    nrf_svc = run_cmd(
        f"kubectl get svc -n {namespace} -l app.kubernetes.io/name=nrf "
        f"-o jsonpath='{{.items[0].metadata.name}}'",
        timeout=10,
    )
    nrf_name = nrf_svc.stdout.strip().strip("'")
    if not nrf_name:
        tool_result(f"NRF service not found in {namespace}", False)
        return f"Error: NRF service not found in namespace {namespace}"

    result = run_cmd(
        f"kubectl exec -n {namespace} deploy/{nrf_name} -- "
        f"curl -sf http://localhost:7777/nnrf-nfm/v1/nf-instances?nf-type={nf_type}",
        timeout=15,
    )
    if result.success and nf_type.upper() in result.stdout.upper():
        tool_result(f"{nf_type} registered with NRF", True)
        return f"{nf_type} is registered with NRF. Response: {result.stdout[:500]}"
    elif result.success:
        tool_result(f"{nf_type} NOT found in NRF", False)
        return f"{nf_type} NOT registered with NRF. NRF returned: {result.stdout[:500]}"
    tool_result("NRF query failed", False)
    return f"Failed to query NRF: {result.output}"


@tool
def check_endpoints(service: str, namespace: str) -> str:
    """Check if a Kubernetes service has ready endpoints.

    Args:
        service: Service name (e.g., 'open5gs-amf')
        namespace: Kubernetes namespace
    """
    tool_call("check_endpoints", f"svc={service} ns={namespace}")
    result = run_cmd(
        f"kubectl get endpoints {service} -n {namespace} "
        f"-o jsonpath='{{.subsets[*].addresses[*].ip}}'",
        timeout=10,
    )
    ips = result.stdout.strip().strip("'")
    if ips:
        count = len(ips.split())
        tool_result(f"{count} endpoint(s): {ips}", True)
        return f"Service {service} has {count} ready endpoint(s): {ips}"
    tool_result("No ready endpoints", False)
    return f"Service {service} has no ready endpoints in namespace {namespace}"


# Tool set for ANDA
DEPLOY_TOOLS = [
    helm_install,
    helm_upgrade,
    helm_rollback,
    helm_status,
    wait_rollout,
    kubectl_apply,
    verify_nf_registration,
    check_endpoints,
]
