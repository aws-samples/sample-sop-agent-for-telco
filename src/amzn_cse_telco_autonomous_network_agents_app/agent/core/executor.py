# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Shared command execution primitives for ANRA agents.

Provides: CmdResult, run_cmd, display helpers, and all reusable @tool functions
that can be imported by multiple agents (SOP executor, correlation, remediation, etc.)
"""

import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from strands import tool

# -- Configuration via environment variables ----------------------------------
_script_dir = os.path.dirname(os.path.abspath(__file__))
SOP_REPO = os.getenv("SOP_REPO", os.path.join(_script_dir, "../.."))
DEFAULT_TIMEOUT = int(os.getenv("CMD_TIMEOUT", "120"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ============== ANSI Colors ==============
@dataclass
class Colors:
    HEADER: str = "\033[95m"
    BLUE: str = "\033[94m"
    CYAN: str = "\033[96m"
    GREEN: str = "\033[92m"
    YELLOW: str = "\033[93m"
    RED: str = "\033[91m"
    MAGENTA: str = "\033[35m"
    ORANGE: str = "\033[38;5;208m"
    PINK: str = "\033[38;5;213m"
    LIME: str = "\033[38;5;118m"
    BOLD: str = "\033[1m"
    END: str = "\033[0m"


C = Colors()
TOOL_COLORS = [C.CYAN, C.YELLOW, C.MAGENTA, C.ORANGE, C.PINK, C.LIME, C.GREEN, C.BLUE]


@dataclass
class ToolColorManager:
    """Thread-safe color rotation for tool calls."""

    _idx: int = field(default=0, repr=False)

    def next_color(self) -> str:
        color = TOOL_COLORS[self._idx % len(TOOL_COLORS)]
        self._idx += 1
        return color

    def current_color(self) -> str:
        return TOOL_COLORS[(self._idx - 1) % len(TOOL_COLORS)]


_color_mgr = ToolColorManager()


# ============== Output Helpers ==============
def banner(text: str, color: str = C.CYAN) -> None:
    print(f"\n{color}{C.BOLD}{'=' * 60}\n  {text}\n{'=' * 60}{C.END}\n")


def tool_call(name: str, args: str = "") -> None:
    color = _color_mgr.next_color()
    print(f"{color}🔧 TOOL: {C.BOLD}{name}{C.END}{color}({args}){C.END}")
    logger.debug(f"Tool call: {name}({args})")


def tool_result(summary: str, success: bool = True) -> None:
    color = _color_mgr.current_color()
    status_color = C.GREEN if success else C.RED
    print(f"{color}   |- {status_color}{summary}{C.END}")
    logger.debug(f"Tool result: {summary}")


# ============== Command Execution ==============
@dataclass
class CmdResult:
    stdout: str
    stderr: str
    returncode: int

    @property
    def success(self) -> bool:
        return self.returncode == 0

    MAX_OUTPUT = int(os.getenv("TOOL_OUTPUT_MAX_CHARS", "4000"))

    @property
    def output(self) -> str:
        out = self.stdout
        if self.stderr:
            out += f"\nSTDERR: {self.stderr}"
        if not self.success:
            out += f"\nEXIT_CODE: {self.returncode}"
        out = out or "No output"
        if len(out) > self.MAX_OUTPUT:
            out = f"... (truncated {len(out) - self.MAX_OUTPUT} chars)\n" + out[-self.MAX_OUTPUT :]
        return out


def run_cmd(cmd: str, timeout: int = DEFAULT_TIMEOUT, shell: bool = True) -> CmdResult:
    """Execute command with proper error handling.

    Security Note: shell=True is used by default for SOP command execution.
    SOPs may contain shell features (pipes, redirects, etc.) that require shell interpretation.
    The agent runs in a controlled environment with limited ServiceAccount permissions.
    """
    try:
        result = subprocess.run(
            cmd if shell else shlex.split(cmd),
            shell=shell,  # nosec B602 - trusted SOP commands from validated sources
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CmdResult(result.stdout, result.stderr, result.returncode)
    except subprocess.TimeoutExpired:
        logger.warning(f"Command timed out: {cmd[:50]}...")
        return CmdResult("", "Command timed out", -1)
    except Exception as e:
        logger.error(f"Command failed: {e}")
        return CmdResult("", str(e), -1)


# ============== Lazy Config Loaders ==============
def _get_site_config():
    """Lazy-load site configuration to avoid import-time failures."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config
    return load_config()


# Cached guardrail state (populated on first use)
_PROTECTED_NS: Optional[set] = None
_BLOCKED_CMDS: Optional[list] = None


def _get_guardrails() -> tuple:
    """Lazy-load kubectl guardrails from site config."""
    global _PROTECTED_NS, _BLOCKED_CMDS
    if _PROTECTED_NS is None:
        try:
            from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config
            _g = load_config().guardrails
            _PROTECTED_NS = set(_g.protected_namespaces)
            _BLOCKED_CMDS = _g.blocked_commands
        except Exception:
            _PROTECTED_NS = {"srsran", "open5gs", "anra", "kube-system"}
            _BLOCKED_CMDS = [
                r"scale.*--replicas.*0",
                r"delete deployment",
                r"delete statefulset",
                r"delete namespace",
            ]
    return _PROTECTED_NS, _BLOCKED_CMDS


# ============== SOP Reading Tools ==============
@tool
def list_sops(repo_path: str = SOP_REPO) -> str:
    """List all SOPs in a repository directory."""
    tool_call("list_sops", f"repo={repo_path}")
    sop_dir = Path(repo_path) / "sops"
    if not sop_dir.exists():
        sop_dir = Path(repo_path)

    sops = [f.name for f in sorted(sop_dir.glob("*.md")) if not f.name.startswith("archive")]
    tool_result(f"Found {len(sops)} SOPs")
    return "\n".join(sops) if sops else "No SOPs found"


@tool
def read_sop(sop_path: str) -> str:
    """Read raw SOP content from file."""
    tool_call("read_sop", f"path={Path(sop_path).name}")
    try:
        path = Path(sop_path)
        if not path.exists():
            tool_result(f"File not found: {sop_path}", success=False)
            return f"Error: File not found: {sop_path}"
        content = path.read_text()
        tool_result(f"Read {len(content)} bytes")
        return content
    except Exception as e:
        tool_result(f"Error: {e}", success=False)
        return f"Error: {e}"


@tool
def parse_sop(content: str) -> str:
    """Parse SOP markdown into structured sections."""
    tool_call("parse_sop", "extracting sections")
    sections = {"prerequisites": [], "steps": [], "success_criteria": [], "troubleshooting": ""}

    for section, pattern in [
        ("prerequisites", r"## Prerequisites?\s*\n(.*?)(?=\n##|\Z)"),
        ("success_criteria", r"## Success Criteria\s*\n(.*?)(?=\n##|\Z)"),
        ("troubleshooting", r"## Troubleshooting\s*\n(.*?)(?=\n##|\Z)"),
    ]:
        match = re.search(pattern, content, re.DOTALL)
        if match:
            text = match.group(1).strip()
            if section == "troubleshooting":
                sections[section] = text
            else:
                lines = text.split("\n")
                sections[section] = [ln.strip("- ").strip() for ln in lines if ln.strip().startswith("-") or ln.strip()]

    sections["steps"] = re.findall(r"```bash\n(.*?)```", content, re.DOTALL)
    tool_result(f"{len(sections['steps'])} steps, {len(sections['success_criteria'])} criteria")
    return str(sections)


# ============== Core Execution Tools ==============
@tool
def run_command(command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Execute a shell command and return output."""
    cmd_display = command[:60] + "..." if len(command) > 60 else command
    tool_call("run_command", f'"{cmd_display}"')
    result = run_cmd(command, timeout)
    tool_result(f"Exit {result.returncode}", result.success)
    return result.output


@tool
def kubectl(args: str) -> str:
    """Execute kubectl command."""
    protected_ns, blocked_cmds = _get_guardrails()

    # Guardrail: block destructive commands on protected namespaces
    for pattern in blocked_cmds:
        if re.search(pattern, args, re.IGNORECASE):
            for ns in protected_ns:
                if ns in args or f"-n {ns}" in args:
                    msg = f"BLOCKED: destructive operation on protected namespace '{ns}'. Escalate to human operator."
                    tool_call("kubectl", args)
                    tool_result(msg, False)
                    return msg
    tool_call("kubectl", args)
    result = run_cmd(f"kubectl {args}", timeout=60)
    tool_result("OK" if result.success else f"Failed ({result.returncode})", result.success)
    return result.output


@tool
def argocd_sync(app_name: str) -> str:
    """Trigger ArgoCD sync to restore workload to Git-declared state. Use this instead of kubectl scale/restart when remediation_mode is gitops."""
    tool_call("argocd_sync", app_name)
    # Trigger sync by patching the Application CRD directly (no CLI auth needed)
    patch = '{"operation":{"initiatedBy":{"username":"anra"},"sync":{"revision":"main"}}}'
    result = run_cmd(f"kubectl patch application {app_name} -n argocd --type merge -p '{patch}'", timeout=30)
    if result.success:
        # Wait and check status
        import time
        time.sleep(10)
        status = run_cmd(f"kubectl get application {app_name} -n argocd -o jsonpath='{{.status.sync.status}} {{.status.health.status}}'")
        tool_result(f"Synced - {status.stdout.strip()}", True)
        return f"ArgoCD sync triggered for {app_name}. Status: {status.stdout.strip()}"
    tool_result("Sync failed", False)
    return result.output


@tool
def kubectl_exec(namespace: str, pod: str, command: str) -> str:
    """Execute command inside a Kubernetes pod."""
    tool_call("kubectl_exec", f"ns={namespace} pod={pod[:20]}...")
    result = run_cmd(f"kubectl exec -n {namespace} {pod} -- {command}")
    tool_result("OK" if result.success else "Failed", result.success)
    return result.output


@tool
def get_pod_name(namespace: str, label: str) -> str:
    """Get pod name by label selector."""
    tool_call("get_pod_name", f"ns={namespace} label={label}")
    result = run_cmd(f"kubectl get pod -n {namespace} -l {label} -o jsonpath='{{.items[0].metadata.name}}'")
    pod = result.stdout.strip().strip("'")
    tool_result(f"Pod: {pod}", bool(pod))
    return pod


@tool
def check_pod_status(namespace: str) -> str:
    """Get status of all pods in namespace."""
    tool_call("check_pod_status", f"ns={namespace}")
    result = run_cmd(f"kubectl get pods -n {namespace} -o wide")
    if result.stdout:
        lines = len(result.stdout.strip().split("\n")) - 1
    else:
        lines = 0
    tool_result(f"Found {lines} pods")
    return result.output


@tool
def get_pod_logs(namespace: str, pod: str, tail: int = 50) -> str:
    """Get logs from a pod."""
    tool_call("get_pod_logs", f"ns={namespace} pod={pod} tail={tail}")
    result = run_cmd(f"kubectl logs -n {namespace} {pod} --tail={tail}")
    tool_result(f"Retrieved {tail} lines")
    return result.output


@tool
def describe_node() -> str:
    """Get node resource allocations including SR-IOV."""
    tool_call("describe_node", "checking SR-IOV resources")
    result = run_cmd("kubectl describe node | grep -A5 'Allocatable:' | grep -E 'intel.com|hugepages'")
    tool_result("Resources retrieved")
    return result.output


@tool
def ssh_command(host: str, command: str, user: str = os.getenv("SSH_DEFAULT_USER", "nec"), timeout: int = 30) -> str:
    """Execute a command on remote host via SSH.

    Args:
        host: Remote host IP/hostname (e.g., '10.10.4.238')
        command: Command to execute
        user: SSH user (default: 'ec2-user')
        timeout: Timeout in seconds (max 120)
    """
    timeout = min(timeout, 120)  # Cap to prevent indefinite hangs
    ssh_target = host if "@" in host else f"{user}@{host}"
    tool_call("ssh_command", f"host={ssh_target} cmd={command[:40]}...")
    ssh_opts = "-o StrictHostKeyChecking=no -o ConnectTimeout=10"
    result = run_cmd(f"ssh {ssh_opts} {ssh_target} '{command}'", timeout=timeout)
    tool_result("OK" if result.success else f"Failed ({result.returncode})", result.success)
    return result.output


@tool
def ssh_expect(
    host: str,
    start_cmd: str,
    prompt: str,
    commands: str,
    user: str = os.getenv("SSH_DEFAULT_USER", "nec"),
    timeout: int = 120,
) -> str:
    """Run interactive commands on remote host using expect.

    Args:
        host: Remote host IP/hostname (e.g., '10.10.4.238')
        start_cmd: Command to start interactive session (e.g., './run.sh')
        prompt: The prompt to wait for (e.g., 'cmd :')
        commands: Semicolon-separated commands to send
        user: SSH user (default: 'ec2-user')
        timeout: Timeout in seconds (max 120)
    """
    timeout = min(timeout, 120)  # Cap to prevent indefinite hangs
    ssh_target = host if "@" in host else f"{user}@{host}"
    tool_call("ssh_expect", f"host={ssh_target} cmds={commands[:50]}...")

    # Build expect script dynamically
    cmd_list = [c.strip() for c in commands.split(";") if c.strip()]
    expect_sends = "\n".join([f'expect "{prompt}"\nsend "{c}\\r"' for c in cmd_list])

    expect_script = f'''expect -c '
set timeout {timeout}
spawn {start_cmd}
{expect_sends}
expect "{prompt}"
send "exit\\r"
expect eof
' 2>&1'''

    ssh_opts = "-o StrictHostKeyChecking=no -o ConnectTimeout=10"
    result = run_cmd(f"ssh {ssh_opts} {ssh_target} '{expect_script}'", timeout=timeout + 30)
    tool_result("OK" if result.success else "Failed", result.success)
    return result.output


@tool
def ssm_command(instance_id: str, command: str, timeout: int = 30) -> str:
    """Execute a command on a remote host via AWS SSM (Systems Manager).
    Use this instead of ssh_command for EKS Hybrid edge nodes and bare-metal servers.

    Args:
        instance_id: SSM managed instance ID (e.g., 'mi-026bd2d584e205efb')
        command: Shell command to execute on the remote host
        timeout: Timeout in seconds (max 120)
    """
    timeout = min(timeout, 120)
    tool_call("ssm_command", f"instance={instance_id} cmd={command[:40]}...")
    _site_config = _get_site_config()
    region = _site_config.cluster_region
    profile = _site_config.bedrock_profile
    profile_arg = f"--profile {profile}" if profile else ""
    send = run_cmd(
        f"aws ssm send-command --instance-ids {instance_id} "
        f"--document-name AWS-RunShellScript "
        f"--parameters 'commands=[\"{command}\"]' "
        f"{profile_arg} --region {region} "
        f"--query Command.CommandId --output text",
        timeout=30,
    )
    if not send.success:
        tool_result(f"Send failed: {send.stderr}", False)
        return send.output
    cmd_id = send.stdout.strip()
    import time as _t

    for _ in range(timeout // 3):
        _t.sleep(3)
        get = run_cmd(
            f"aws ssm get-command-invocation --command-id {cmd_id} "
            f"--instance-id {instance_id} {profile_arg} --region {region} "
            f"--query '[Status,StandardOutputContent,StandardErrorContent]' --output text",
            timeout=15,
        )
        if "Success" in get.stdout or "Failed" in get.stdout:
            parts = get.stdout.split("\t", 2)
            status = parts[0] if parts else "Unknown"
            output = parts[1].strip() if len(parts) > 1 else ""
            stderr = parts[2].strip() if len(parts) > 2 else ""
            ok = status == "Success"
            tool_result(f"{status}", ok)
            return (output + ("\nSTDERR: " + stderr if stderr else "")) or "(no output)"
    tool_result("Timeout waiting for SSM result", False)
    return "(SSM command timed out)"


@tool
def redfish_query(bmc_ip: str, endpoint: str = "") -> str:
    """Query Dell iDRAC or HPE iLO via Redfish API directly over HTTPS.
    Uses site config for BMC credentials and vendor-specific paths.

    Common endpoints:
    - /Thermal (temperatures + fans)
    - /Power (PSU + wattage)
    - /redfish/v1/Systems/System.Embedded.1/Storage (disk health)
    - /redfish/v1/Managers/iDRAC.Embedded.1/LogServices/Sel/Entries (SEL log)

    Args:
        bmc_ip: BMC/iDRAC IP address (e.g., '192.168.30.10')
        endpoint: Redfish API path (auto-detected from BMC type if short path given)
    """
    tool_call("redfish_query", f"bmc={bmc_ip} path={endpoint or 'summary'}")
    _site_config = _get_site_config()
    node = _site_config.get_node_by_bmc(bmc_ip)
    if not node:
        tool_result(f"BMC {bmc_ip} not in anra-config.yaml", False)
        return f"Error: BMC IP {bmc_ip} not found in site config. Known BMCs: {_site_config.all_bmc_ips}"

    if not endpoint or endpoint in ("/Thermal", "Thermal", "thermal"):
        endpoint = node.bmc.thermal_path
    elif endpoint in ("/Power", "Power", "power"):
        endpoint = node.bmc.power_path
    elif not endpoint.startswith("/redfish"):
        endpoint = f"{node.bmc.redfish_base}/{endpoint}"

    bmc_password = os.getenv("BMC_PASSWORD", "")
    if not bmc_password:
        tool_result("BMC_PASSWORD env var not set", False)
        return (
            "Error: BMC_PASSWORD env var not set. The pod must be deployed "
            "with BMC_PASSWORD wired from a k8s Secret (see node.bmc.password_secret)."
        )

    # Credentials go via curl's stdin config (never shell string / argv / proc).
    from amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc import curl_bmc

    proc = curl_bmc(
        f"https://{bmc_ip}{endpoint}",
        node.bmc.username,
        bmc_password,
        timeout=15,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        tool_result("OK (direct)", True)
        try:
            import json

            return json.dumps(json.loads(proc.stdout), indent=2)[:4000]
        except Exception:
            return proc.stdout[:4000]
    tool_result("Failed", False)
    return proc.stdout or proc.stderr or "No output"


@tool
def list_nodes() -> str:
    """List all nodes from the site configuration with their roles, IPs, and BMC addresses."""
    tool_call("list_nodes", "")
    _site_config = _get_site_config()
    lines = []
    for n in _site_config.nodes:
        lines.append(f"{n.name}: oam={n.oam_ip} ssm={n.ssm_id} bmc={n.bmc.ip} roles={n.roles}")
    result = "\n".join(lines) if lines else "No nodes configured in anra-config.yaml"
    tool_result(f"{len(_site_config.nodes)} nodes")
    return result


@tool
def argocd_status(app_name: str = os.getenv("ARGOCD_APP", "anra")) -> str:
    """Get ArgoCD application sync status."""
    tool_call("argocd_status", f"app={app_name}")
    jsonpath = "'{.status.sync.status} {.status.health.status}'"
    result = run_cmd(f"kubectl get application {app_name} -n argocd -o jsonpath={jsonpath}")
    tool_result(f"Status: {result.stdout.strip()}")
    return result.stdout


from amzn_cse_telco_autonomous_network_agents_app.agent.framework.contracts import (
    CommandIntegration,
    CommandResult,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import ExtensionKind
from amzn_cse_telco_autonomous_network_agents_app.agent.framework.registry import registry


class TelcoCliIntegration(CommandIntegration):
    """Site CLI integration for AWS Outpost operations via the ``telcocli`` binary.

    The AWS profile and region are read from config (cli.profile / cli.region) at
    call time, defaulting to the values this project historically hardcoded
    ("nec" / "us-east-1"), so customers point telcocli at their own account
    without editing engine code.
    """

    @property
    def name(self) -> str:
        return "telcocli"

    def run(self, command: str) -> CommandResult:
        cfg = _get_site_config()
        profile = cfg.cli_profile or "nec"
        region = cfg.cli_region or "us-east-1"
        result = run_cmd(f"telcocli --profile {profile} --region {region} {command}")
        return CommandResult(output=result.output, success=result.success)


# Register the built-in CLI integration so config `cli.integration` can select it
# (and a customer plugin can register + select an alternative without edits here).
# Idempotent (override) so a module reload does not trip the duplicate guard.
registry.register(
    ExtensionKind.CLI, "telcocli", TelcoCliIntegration(), override=True
)


@tool
def telcocli(command: str) -> str:
    """Run a telcocli CLI command for AWS Outpost operations. Examples:
    - 'list-outposts' to list all Outposts
    - 'describe-outpost --outpost-id <id> --include-capacity --include-hosts' for details
    - 'health' for system health check
    - 'analyze-dedicated-hosts' for host utilization
    Do NOT include --profile or --region; the configured CLI integration adds them."""
    tool_call("telcocli", command)
    cfg = _get_site_config()
    integration = registry.get_one(ExtensionKind.CLI, cfg.cli_integration)
    result = integration.run(command)
    tool_result(result.output[:200] if result.success else "Failed", result.success)
    return result.output


# ============== TOOL SETS ==============
BASE_TOOLS = [
    list_sops,
    read_sop,
    parse_sop,
    run_command,
    kubectl,
    kubectl_exec,
    get_pod_name,
    check_pod_status,
    get_pod_logs,
    describe_node,
    ssh_command,
    ssh_expect,
    ssm_command,
    redfish_query,
    list_nodes,
    telcocli,
]

ARGOCD_TOOLS = [argocd_sync, argocd_status]

SOP_TOOLS = {
    "argocd": BASE_TOOLS + ARGOCD_TOOLS,
}


def get_tools_for_sop(sop_path: str) -> list:
    """Select tools based on SOP."""
    sop_name = Path(sop_path).stem.lower()
    for key, tools in SOP_TOOLS.items():
        if key in sop_name:
            return tools
    return BASE_TOOLS
