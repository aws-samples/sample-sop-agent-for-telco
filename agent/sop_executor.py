# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#!/usr/bin/env python3
"""
SOP Executor Agent - Production-grade SOP execution with auto-remediation.
Demo Demo: AI-Driven 5G App Deployment
"""

import logging
import os
import re
import shlex
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from strands import Agent, tool
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookRegistry
from strands.models import BedrockModel

# Configuration via environment variables
_script_dir = os.path.dirname(os.path.abspath(__file__))
SOP_REPO = os.getenv("SOP_REPO", os.path.join(_script_dir, ".."))
AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
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
    print(f"\n{color}{C.BOLD}{'═' * 60}\n  {text}\n{'═' * 60}{C.END}\n")


def tool_call(name: str, args: str = "") -> None:
    color = _color_mgr.next_color()
    print(f"{color}🔧 TOOL: {C.BOLD}{name}{C.END}{color}({args}){C.END}")
    logger.debug(f"Tool call: {name}({args})")


def tool_result(summary: str, success: bool = True) -> None:
    color = _color_mgr.current_color()
    status_color = C.GREEN if success else C.RED
    print(f"{color}   └─ {status_color}{summary}{C.END}")
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


# ============== TOOLS ==============
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


@tool
def run_command(command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Execute a shell command and return output."""
    cmd_display = command[:60] + "..." if len(command) > 60 else command
    tool_call("run_command", f'"{cmd_display}"')
    result = run_cmd(command, timeout)
    tool_result(f"Exit {result.returncode}", result.success)
    return result.output


try:
    from config import load_config as _load_cfg

    _g = _load_cfg().guardrails
    _PROTECTED_NS = set(_g.protected_namespaces)
    _BLOCKED_CMDS = _g.blocked_commands
except Exception:
    _PROTECTED_NS = {"srsran", "open5gs", "anra", "kube-system"}
    _BLOCKED_CMDS = [r"scale.*--replicas.*0", r"delete deployment", r"delete statefulset", r"delete namespace"]


@tool
def kubectl(args: str) -> str:
    """Execute kubectl command."""
    import re

    # Guardrail: block destructive commands on protected namespaces
    for pattern in _BLOCKED_CMDS:
        if re.search(pattern, args, re.IGNORECASE):
            for ns in _PROTECTED_NS:
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
        tool_result(f"Synced — {status.stdout.strip()}", True)
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
def ssh_command(host: str, command: str, user: str = os.getenv("SSH_DEFAULT_USER", "ec2-user"), timeout: int = 30) -> str:
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
    user: str = os.getenv("SSH_DEFAULT_USER", "ec2-user"),
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


from config import SiteConfig, load_config

_site_config: SiteConfig = load_config()


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

    result = run_cmd(
        f"curl -sk -u {node.bmc.username}:calvin https://{bmc_ip}{endpoint}",
        timeout=15,
    )
    if result.success and result.stdout.strip():
        tool_result("OK (direct)", True)
        try:
            import json

            return json.dumps(json.loads(result.stdout), indent=2)[:4000]
        except Exception:
            return result.stdout[:4000]
    tool_result("Failed", False)
    return result.output


@tool
def list_nodes() -> str:
    """List all nodes from the site configuration with their roles, IPs, and BMC addresses."""
    tool_call("list_nodes", "")
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


# ============== SYSTEM PROMPT ==============
SYSTEM_PROMPT_BASE = """You are a strict SOP Executor Agent. You MUST NOT rationalize or explain away failures.

## CRITICAL RULES - VIOLATIONS ARE UNACCEPTABLE

1. **Exit code != 0 means FAILURE** - No exceptions. Do not say "but it might be okay"
2. **grep returning empty means FAILURE** - The thing you searched for is MISSING
3. **Resource count = 0 means FAILURE** - Zero resources is never acceptable
4. **Pod not found means FAILURE** - Missing pods must be reported and fixed

## FORBIDDEN BEHAVIORS

❌ "No SR-IOV plugin running, but pods have interfaces so it's probably fine"
❌ "Command failed but let me check something else instead"
❌ "Exit code 1 but no critical errors"
❌ "Resources show 0 but they may have already been consumed"

## Failure Detection Table

| Check | FAILURE Condition |
|-------|-------------------|
| kubectl exit != 0 | Any non-zero exit |
| grep empty output | Nothing matched |
| SR-IOV = 0 | intel.com resources = 0 |
| Pod not Running | Status != Running |
| ArgoCD OutOfSync | sync.status != Synced |
| GWU sts != act | sts=oos, sts=ini |

## Output Format

For EVERY command result:
- Exit 0 + expected output → "✅ PASS: <description>"
- Exit != 0 OR unexpected → "❌ FAILURE: <description>"

## Tools
list_sops, read_sop, parse_sop, run_command, kubectl, kubectl_exec,
get_pod_name, check_pod_status, get_pod_logs, describe_node, argocd_sync, argocd_status
"""

SYSTEM_PROMPT_REPORT = (
    SYSTEM_PROMPT_BASE
    + """
## MODE: REPORT ONLY

You are in REPORT mode. DO NOT attempt to fix or remediate any failures.
- Execute SOP steps and validate results
- Report all failures with "❌ FAILURE: <description>"
- DO NOT run remediation commands
- Provide a final summary of all issues found

Your job is to FIND and REPORT problems, not fix them."""
)

SYSTEM_PROMPT_FIX = (
    SYSTEM_PROMPT_BASE
    + """
## MODE: AUTONOMOUS FIX

You are in FIX mode. Autonomously remediate all failures found.
- Execute SOP steps and validate results
- On failure: immediately attempt remediation
- Retry validation after remediation
- Continue until all issues resolved or max retries (3) reached

## Remediation Actions

| Failure | Remediation |
|---------|-------------|
| SR-IOV = 0 | Restart sriov-device-plugin daemonset |
| Pod not Running | Check events, delete stuck pod |
| ArgoCD OutOfSync | `argocd_sync()` |
| GWU sts != act | Wait 60s for BGP, then `ins_gwu lgwu001` |
| BGP neighbors down | Wait 30s and retry (convergence time) |

Your job is to FIND and FIX problems autonomously. Do not ask for permission."""
)


@tool
def telcocli(command: str) -> str:
    """Run a telcocli CLI command for AWS Outpost operations. Examples:
    - 'list-outposts' to list all Outposts
    - 'describe-outpost --outpost-id <id> --include-capacity --include-hosts' for details
    - 'health' for system health check
    - 'analyze-dedicated-hosts' for host utilization
    Always include '--profile default --region $AWS_DEFAULT_REGION' in the command."""
    tool_call("telcocli", command)
    result = run_cmd(f"telcocli --profile default --region $AWS_DEFAULT_REGION {command}")
    tool_result(result.stdout[:200] if result.success else "Failed", result.success)
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


# ============== STEERING HOOKS ==============
class SOPSteeringHooks:
    """Just-in-time steering for SOP executor — intercepts tool calls to prevent known failures."""

    TOOL_WARN = 80
    TOOL_STOP = 95
    SSH_HEREDOC_MAX = 500

    def __init__(self, fix_mode: bool = False):
        self.fix_mode = fix_mode
        self.tool_count = 0
        self.ledger: list[dict] = []

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call)
        registry.add_callback(AfterToolCallEvent, self._after_tool_call)

    def _before_tool_call(self, event: BeforeToolCallEvent, **kwargs):
        name = event.tool_use["name"]
        inp = event.tool_use.get("input", {})
        self.tool_count += 1

        # --- Tool call budget ---
        if self.tool_count >= self.TOOL_STOP:
            event.cancel_tool = (
                f"Tool call budget exhausted ({self.tool_count}/{self.TOOL_STOP}). "
                "Summarize progress and stop. Do NOT call more tools."
            )
            return
        if self.tool_count >= self.TOOL_WARN:
            logger.warning(f"Tool call budget warning: {self.tool_count}/{self.TOOL_STOP}")

        # --- SSH heredoc guard ---
        if name == "ssh_command":
            cmd = str(inp.get("command", ""))
            if "<<" in cmd and len(cmd) > self.SSH_HEREDOC_MAX:
                event.cancel_tool = (
                    "Long heredocs fail over SSH. Write the content to a file with "
                    "base64 encoding instead: echo '<base64>' | base64 -d > /path/file"
                )
                return

        # --- Namespace guard ---
        if name in ("kubectl", "kubectl_exec"):
            args = str(inp.get("args", inp.get("command", "")))
            ns = str(inp.get("namespace", ""))
            if ns == "default" or "-n default" in args or "--namespace=default" in args:
                event.cancel_tool = (
                    "Check the SOP for the correct namespace. 'default' is rarely correct for NF deployments."
                )
                return

        # --- Dangerous command guard (REPORT mode) ---
        if not self.fix_mode:
            cmd = str(inp.get("command", inp.get("args", "")))
            dangerous = ["sudo reboot", "kubectl delete namespace", "--force --grace-period=0", "pkill -9"]
            for pattern in dangerous:
                if pattern in cmd:
                    event.cancel_tool = (
                        f"Blocked in REPORT mode: '{pattern}' is destructive. "
                        "Switch to FIX mode to execute destructive commands."
                    )
                    return

        # --- Port-forward hang guard ---
        if name in ("run_command", "kubectl"):
            cmd = str(inp.get("command", inp.get("args", "")))
            if "port-forward" in cmd and "&" not in cmd:
                event.cancel_tool = (
                    "port-forward without '&' will hang the agent. "
                    "Add '&' to run in background, or use 'timeout 10 kubectl port-forward ...'."
                )
                return

    def _after_tool_call(self, event: AfterToolCallEvent, **kwargs):
        name = event.tool_use["name"]
        result_text = ""
        if event.result and event.result.get("content"):
            for block in event.result["content"]:
                if isinstance(block, dict) and "text" in block:
                    result_text += block["text"]
        self.ledger.append({"tool": name, "result_snippet": result_text[:200]})


# ============== EVAL TELEMETRY ==============
def setup_eval_telemetry():
    """Initialize in-memory OTel tracing for post-execution evaluation."""
    from strands_evals.telemetry import StrandsEvalsTelemetry

    telemetry = StrandsEvalsTelemetry().setup_in_memory_exporter()
    logger.info("Eval telemetry enabled (in-memory span exporter)")
    return telemetry


def collect_eval_session(telemetry, session_id: str):
    """Map captured spans into an eval session for evaluators."""
    from strands_evals.mappers import StrandsInMemorySessionMapper

    spans = telemetry.in_memory_exporter.get_finished_spans()
    mapper = StrandsInMemorySessionMapper()
    return mapper.map_to_session(spans, session_id=session_id)


# SOP eval metadata — derived from SOP content, not hardcoded
_TOOL_PATTERNS = {
    "check_pod_status": ["check_pod_status"],
    "kubectl_exec": ["kubectl exec"],
    "kubectl": ["kubectl get", "kubectl apply", "kubectl delete", "kubectl describe", "kubectl patch"],
    "ssh_command": ["ssh ", "ssh_command"],
    "argocd_sync": ["argocd_sync", "argocd app sync"],
    "argocd_status": ["argocd_status", "argocd app get"],
    "telcocli": ["telcocli"],
}


def get_sop_eval_meta(sop_path: str) -> dict:
    """Derive eval metadata from SOP content — detects which tools the SOP references."""
    try:
        content = Path(sop_path).read_text().lower()
    except (FileNotFoundError, OSError):
        return {}

    required = []
    for tool_name, patterns in _TOOL_PATTERNS.items():
        if any(p in content for p in patterns):
            required.append(tool_name)
    return {"required_tools": required} if required else {}


def run_post_eval(eval_ctx: dict, sop_path: str, agent_output: str) -> list:
    """Run post-execution evaluators on captured trace. Returns list of EvaluationReport."""
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "evals"))
    from evaluators import SOPCompletionEvaluator, SteeringEffectivenessEvaluator
    from strands_evals import Case, Experiment

    session = collect_eval_session(eval_ctx["telemetry"], eval_ctx["session_id"])
    meta = get_sop_eval_meta(sop_path)

    case = Case[str, str](
        name=Path(sop_path).stem if sop_path else "interactive",
        input=sop_path,
        metadata=meta,
    )

    evaluators = [SteeringEffectivenessEvaluator(), SOPCompletionEvaluator()]
    experiment = Experiment[str, str](cases=[case], evaluators=evaluators)

    def task_fn(c):
        return {"output": agent_output, "trajectory": session}

    reports = experiment.run_evaluations(task_fn)
    return reports


# ============== AGENT FACTORY ==============
from model_discovery import discover_models, resolve_model_key

# Legacy MODELS dict — kept for backward compatibility with CLI --model flag
# Values are resolved dynamically at runtime via model_discovery
MODELS = {
    "haiku": "fast",
    "sonnet": "balanced",
    "sonnet4.5": "balanced",
    "sonnet4.6": "balanced",
    "opus": "powerful",
    "opus4.5": "powerful",
    "opus4.6": "powerful",
    "opus4.7": "powerful",
}


def create_agent(
    profile: Optional[str] = None,
    region: str = AWS_REGION,
    model_name: str = "sonnet",
    fix_mode: bool = False,
    sop_path: str = "",
    no_steering: bool = False,
    eval_mode: bool = False,
) -> tuple:
    """Create the SOP executor agent with tools scoped to the SOP.

    Returns:
        (agent, eval_context) where eval_context is a dict with telemetry/session_id
        when eval_mode=True, or an empty dict otherwise.
    """
    import boto3

    # Eval telemetry (must init before Agent so OTel provider is global)
    eval_ctx = {}
    if eval_mode:
        telemetry = setup_eval_telemetry()
        session_id = str(uuid.uuid4())
        eval_ctx = {"telemetry": telemetry, "session_id": session_id}
        print(f"{C.CYAN}📊 Eval mode enabled (session: {session_id[:8]}...){C.END}")

    mode_str = "FIX (autonomous)" if fix_mode else "REPORT (read-only)"
    logger.info(f"Initializing agent: profile={profile or 'default'}, region={region}")
    print(f"{C.CYAN}🤖 Initializing Strands Agent with {model_name}{C.END}")
    print(f"{C.CYAN}☁️  AWS Profile: {profile or 'default'} | Region: {region}{C.END}")
    print(f"{C.CYAN}🔧 Mode: {mode_str}{C.END}")

    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        # Verify credentials
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        print(f"{C.CYAN}🔑 Account: {identity['Account']}{C.END}")
    except Exception as e:
        print(f"{C.RED}❌ AWS credentials error: {e}{C.END}")
        raise SystemExit(1)

    # Dynamic model resolution — probes available models and selects best for tier
    model_id = resolve_model_key(model_name, boto_session=session, region=region)
    discovered = discover_models(boto_session=session, region=region)
    print(f"{C.CYAN}🧠 Model: {model_id}{C.END}")
    print(f"{C.CYAN}{discovered.summary()}{C.END}")

    try:
        model = BedrockModel(model_id=model_id, boto_session=session)
    except Exception as e:
        print(f"{C.RED}❌ Bedrock model error: {e}{C.END}")
        raise SystemExit(1)

    system_prompt = SYSTEM_PROMPT_FIX if fix_mode else SYSTEM_PROMPT_REPORT
    tools = get_tools_for_sop(sop_path) if sop_path else BASE_TOOLS

    hooks = [] if no_steering else [SOPSteeringHooks(fix_mode=fix_mode)]
    trace_attrs = {}
    if eval_mode:
        trace_attrs = {
            "session.id": eval_ctx["session_id"],
            "gen_ai.conversation.id": eval_ctx["session_id"],
        }
    agent = Agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        hooks=hooks,
        trace_attributes=trace_attrs or None,
    )
    print(f"{C.GREEN}✅ Agent ready with {len(tools)} tools{C.END}")
    return agent, eval_ctx


# ============== MAIN ==============
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="SOP Executor Agent - Demo")
    parser.add_argument("sop", nargs="+", help="SOP filename(s) to execute")
    parser.add_argument("--profile", "-p", help="AWS profile for Bedrock")
    parser.add_argument("--region", "-r", default=AWS_REGION, help="AWS region")
    parser.add_argument(
        "--model",
        "-m",
        default="haiku",
        choices=list(MODELS.keys()),
        help="Model: haiku (fast), sonnet3.5, sonnet (default: haiku)",
    )
    parser.add_argument(
        "--fix", "-f", action="store_true", help="Autonomous fix mode - remediate failures automatically"
    )
    parser.add_argument("--mode", choices=["sop", "gitops"], default="sop")
    parser.add_argument("--repo", default=SOP_REPO, help="SOP repository path")
    parser.add_argument("--no-steering", action="store_true", help="Disable steering hooks")
    parser.add_argument("--eval", action="store_true", help="Enable post-execution evaluation")
    parser.add_argument(
        "--auto-correct", action="store_true", help="Auto-correct SOP from eval failures (requires --eval)"
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation for auto-correct commits")
    args = parser.parse_args()

    banner("🚀 AI-Driven NF Deployment Agent", C.HEADER)
    print(f"{C.BOLD}Strands Agent + Amazon Bedrock{C.END}\n")

    # Resolve SOP paths
    sop_paths = []
    if args.sop:
        for s in args.sop:
            sop_paths.append(s if "/" in s else f"{args.repo}/sops/{s}")
    sop_path = sop_paths[0] if sop_paths else ""

    agent, eval_ctx = create_agent(
        profile=args.profile,
        region=args.region,
        model_name=args.model,
        fix_mode=args.fix,
        sop_path=sop_path,
        no_steering=args.no_steering,
        eval_mode=args.eval,
    )

    if args.mode == "gitops":
        banner("🔄 GitOps Pre-Commit Gate", C.BLUE)
        prompt = f"""GitOps workflow:
1. Check ArgoCD status with `argocd_status`
2. If OutOfSync: validate SR-IOV/Multus, then `argocd_sync`
3. Run validation SOP: {args.repo}/sops/03-validation.md
4. Remediate failures, report final status"""
    elif len(sop_paths) > 1:
        banner(f"📋 Executing: {len(sop_paths)} SOPs via graph", C.BLUE)
        import asyncio

        from sop_graph import build_sop_graph

        graph = build_sop_graph(
            sop_paths=sop_paths,
            profile=args.profile,
            region=args.region,
            default_model=args.model,
            fix_mode=args.fix,
            eval_mode=args.eval,
            auto_correct=args.auto_correct,
        )
        task = "Execute your assigned SOP. Read it, run each step, and report pass/fail results."
        result = asyncio.run(graph.invoke_async(task))
        print(f"\n{C.GREEN}Graph complete: {result.completed_nodes}/{result.total_nodes} nodes{C.END}")
        sys.exit(0)
    elif sop_paths:
        banner(f"📋 Executing: {sop_paths[0]}", C.BLUE)
        prompt = f"Execute SOP: {sop_paths[0]}\nValidate and remediate as needed."
    else:
        banner("📂 Interactive Mode", C.BLUE)
        prompt = f"List SOPs in {args.repo}/sops/ and ask which to execute."

    print(f"{C.CYAN}{'─' * 60}{C.END}\n")

    try:
        result = agent(prompt)
        banner("📊 Final Report", C.GREEN)
        print(result)

        # Post-execution evaluation
        if args.eval and eval_ctx:
            banner("🧪 Post-Execution Evaluation", C.CYAN)
            try:
                reports = run_post_eval(eval_ctx, sop_path, str(result))
                has_failures = False
                for report in reports:
                    print(f"\n{C.BOLD}{report.evaluator_name}{C.END}")
                    print(f"  Score: {report.overall_score:.2f}")
                    for i, reason in enumerate(report.reasons):
                        status = f"{C.GREEN}✅" if report.test_passes[i] else f"{C.RED}❌"
                        print(f"  {status} {reason}{C.END}")
                        if not report.test_passes[i]:
                            has_failures = True

                # SOP auto-correction
                if args.auto_correct and has_failures and sop_path:
                    banner("🔧 SOP Auto-Correction", C.YELLOW)
                    try:
                        sys.path.insert(0, os.path.join(_script_dir, "..", "evals"))
                        from sop_corrector import correct_sop, extract_failures

                        failures = extract_failures(reports)
                        print(f"{C.YELLOW}Found {len(failures)} failure(s) to correct{C.END}")
                        for f in failures:
                            print(f"  • [{f['evaluator']}] {f['reason']}")

                        if not args.yes:
                            confirm = input(f"\n{C.BOLD}Apply corrections to {sop_path}? [y/N] {C.END}")
                            if confirm.lower() != "y":
                                print(f"{C.YELLOW}Skipped.{C.END}")
                                return

                        corrected = correct_sop(
                            reports,
                            sop_path,
                            profile=args.profile,
                            region=args.region,
                            auto_commit=args.yes,
                        )
                        if corrected:
                            print(f"{C.GREEN}✅ SOP corrected: {sop_path}{C.END}")
                        else:
                            print(f"{C.YELLOW}No corrections applied.{C.END}")
                    except Exception as e:
                        print(f"{C.RED}❌ Auto-correction failed: {e}{C.END}")
                        logger.warning(f"Auto-correction failed: {e}")
            except Exception as e:
                print(f"{C.YELLOW}⚠️  Eval failed: {e}{C.END}")
                logger.warning(f"Eval failed: {e}")
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}⚠️  Interrupted by user{C.END}")
        raise SystemExit(130)
    except Exception as e:
        banner("❌ Agent Error", C.RED)
        print(f"{C.RED}Error type: {type(e).__name__}{C.END}")
        print(f"{C.RED}Error: {e}{C.END}")
        import traceback

        traceback.print_exc()
        logger.exception("Agent execution failed")
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}⚠️  Interrupted{C.END}")
    except SystemExit:
        raise
    except Exception as e:
        print(f"{C.RED}❌ Unexpected error type: {type(e).__name__}{C.END}")
        print(f"{C.RED}❌ Unexpected error: {e}{C.END}")
        import traceback

        traceback.print_exc()
        logger.exception("Unhandled exception")
        raise SystemExit(1)
