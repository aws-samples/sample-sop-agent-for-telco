# SOP Executor Agent - Code Documentation

## Overview

The SOP Executor Agent is an AI-powered automation system built for the Demo demo that reads Standard Operating Procedures (SOPs) from markdown files and executes them autonomously. It uses AWS Bedrock's Claude models via the Strands agent framework to intelligently parse, execute, validate, and remediate 5G App (User Plane Function) deployment procedures.

## Architecture

### Core Components

1. **Agent Framework**: Built on Strands agent library with AWS Bedrock integration
2. **Tool System**: 15+ specialized tools for Kubernetes, SSH, and system operations
3. **Execution Modes**: Report-only (validation) and Fix mode (autonomous remediation)
4. **SOP Parser**: Markdown parser that extracts structured sections from SOPs
5. **Command Executor**: Safe subprocess wrapper with timeout and error handling

## Configuration

### Environment Variables

```python
SOP_REPO = os.getenv("SOP_REPO", "../app-deployment-sops")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DEFAULT_TIMEOUT = int(os.getenv("CMD_TIMEOUT", "120"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
```

- **SOP_REPO**: Path to the repository containing SOP markdown files
- **AWS_REGION**: AWS region for Bedrock API calls
- **DEFAULT_TIMEOUT**: Default command execution timeout (120 seconds)
- **LOG_LEVEL**: Python logging level (INFO, DEBUG, etc.)

### Supported Models

```python
MODELS = {
    "haiku": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    "sonnet": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "sonnet4.5": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "sonnet3.5": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "opus": "us.anthropic.claude-opus-4-20250514-v1:0",
}
```

## Visual Output System

### Color-Coded Terminal Output

The system uses ANSI color codes for enhanced readability:

- **CYAN**: Headers and system messages
- **GREEN**: Success indicators
- **RED**: Failures and errors
- **YELLOW**: Warnings
- **MAGENTA/ORANGE/PINK/LIME**: Tool call rotation for visual distinction

### ToolColorManager

```python
@dataclass
class ToolColorManager:
    """Thread-safe color rotation for tool calls."""
```

Rotates through 8 colors to visually distinguish consecutive tool calls, making it easier to track execution flow in the terminal.

### Output Functions

- **`banner(text, color)`**: Prints section headers with decorative borders
- **`tool_call(name, args)`**: Displays tool invocation with colored formatting
- **`tool_result(summary, success)`**: Shows tool execution result with status indicator

## Command Execution

### CmdResult Dataclass

```python
@dataclass
class CmdResult:
    stdout: str
    stderr: str
    returncode: int
```

Encapsulates command execution results with:
- **`success`** property: Returns `True` if returncode == 0
- **`output`** property: Combines stdout, stderr, and exit code into formatted string

### run_cmd Function

```python
def run_cmd(cmd: str, timeout: int = DEFAULT_TIMEOUT, shell: bool = True) -> CmdResult
```

Safe command executor with:
- Timeout protection (default 120s)
- Exception handling for subprocess errors
- Automatic stderr/stdout capture
- Timeout detection and reporting

## Tool System

### Tool Categories

#### 1. SOP Management Tools

**`list_sops(repo_path)`**
- Lists all `.md` files in the SOP repository
- Filters out archived SOPs
- Returns newline-separated list of SOP filenames

**`read_sop(sop_path)`**
- Reads raw markdown content from SOP file
- Returns file content as string
- Handles file not found errors

**`parse_sop(content)`**
- Extracts structured sections from markdown:
  - **Prerequisites**: Bullet-pointed requirements
  - **Steps**: Bash code blocks (```bash...```)
  - **Success Criteria**: Expected outcomes
  - **Troubleshooting**: Remediation procedures
- Uses regex patterns to identify sections
- Returns dictionary with parsed sections

#### 2. Command Execution Tools

**`run_command(command, timeout)`**
- Executes arbitrary shell commands
- Displays truncated command in logs (60 chars)
- Returns stdout/stderr/exit code
- Default timeout: 120 seconds

#### 3. Kubernetes Tools

**`kubectl(args)`**
- Wrapper for kubectl commands
- 60-second timeout
- Returns command output with status

**`kubectl_exec(namespace, pod, command)`**
- Executes commands inside Kubernetes pods
- Format: `kubectl exec -n <namespace> <pod> -- <command>`

**`get_pod_name(namespace, label)`**
- Retrieves pod name by label selector
- Uses jsonpath to extract first matching pod
- Returns pod name string

**`check_pod_status(namespace)`**
- Lists all pods in namespace with wide output
- Returns formatted pod status table
- Counts number of pods found

**`get_pod_logs(namespace, pod, tail)`**
- Retrieves last N lines of pod logs
- Default tail: 50 lines
- Useful for debugging pod issues

**`describe_node()`**
- Checks node resource allocations
- Specifically filters for SR-IOV resources (`intel.com`)
- Checks hugepages allocation
- Critical for validating hardware resource availability

#### 4. SSH Tools

**`ssh_command(host, command, user, timeout)`**
- Executes commands on remote hosts via SSH
- Default user: `nec`
- Disables strict host key checking for automation
- 10-second connection timeout

**`ssh_expect(host, start_cmd, prompt, commands, user, timeout)`**
- Runs interactive commands using `expect`
- Handles interactive CLI sessions (e.g., network device CLIs)
- Sends semicolon-separated commands
- Waits for specific prompts between commands
- Example use case: BGP router configuration

#### 5. ArgoCD Tools

**`argocd_sync(app_name)`**
- Triggers ArgoCD application sync
- Uses kubectl patch to initiate sync operation
- Default app: `nec-app`

**`argocd_status(app_name)`**
- Retrieves ArgoCD sync and health status
- Returns: `<sync_status> <health_status>`
- Example: `Synced Healthy`

### Tool Selection Strategy

```python
SOP_TOOLS = {
    "07-argocd": BASE_TOOLS + ARGOCD_TOOLS,
}

def get_tools_for_sop(sop_path: str) -> list:
    """Select tools based on SOP."""
```

The agent dynamically selects tools based on the SOP being executed:
- **Base tools**: Always available (kubectl, ssh, command execution)
- **ArgoCD tools**: Added for GitOps-related SOPs (07-argocd)
- Reduces token usage by only providing relevant tools to the LLM

## Agent System Prompts

### Critical Rules (Both Modes)

The agent is programmed with strict failure detection rules:

```
1. Exit code != 0 means FAILURE - No exceptions
2. grep returning empty means FAILURE - Missing resources
3. Resource count = 0 means FAILURE - Zero resources unacceptable
4. Pod not found means FAILURE - Must be reported and fixed
```

### Forbidden Behaviors

The agent is explicitly instructed NOT to rationalize failures:
- ❌ "No SR-IOV plugin running, but pods have interfaces so it's probably fine"
- ❌ "Command failed but let me check something else instead"
- ❌ "Exit code 1 but no critical errors"

### Failure Detection Table

| Check | FAILURE Condition |
|-------|-------------------|
| kubectl exit != 0 | Any non-zero exit |
| grep empty output | Nothing matched |
| SR-IOV = 0 | intel.com resources = 0 |
| Pod not Running | Status != Running |
| ArgoCD OutOfSync | sync.status != Synced |
| GWU sts != act | sts=oos, sts=ini |

### Mode 1: REPORT Mode (Default)

```python
SYSTEM_PROMPT_REPORT
```

**Behavior**:
- Execute SOP steps sequentially
- Validate each step's output
- Report failures with "❌ FAILURE: <description>"
- **DO NOT** attempt remediation
- Provide final summary of all issues

**Use Case**: Pre-deployment validation, auditing, compliance checks

### Mode 2: FIX Mode (--fix flag)

```python
SYSTEM_PROMPT_FIX
```

**Behavior**:
- Execute SOP steps sequentially
- Validate each step's output
- **Immediately remediate failures**
- Retry validation after remediation
- Continue until resolved or max retries (3)

**Remediation Actions**:

| Failure | Remediation |
|---------|-------------|
| SR-IOV = 0 | Restart sriov-device-plugin daemonset |
| Pod not Running | Check events, delete stuck pod |
| ArgoCD OutOfSync | `argocd_sync()` |
| GWU sts != act | Wait 60s for BGP, then `ins_gwu lgwu001` |
| BGP neighbors down | Wait 30s and retry (convergence) |

**Use Case**: Autonomous deployment, self-healing systems, CI/CD pipelines

## Agent Creation

### create_agent Function

```python
def create_agent(
    profile: Optional[str] = None,
    region: str = AWS_REGION,
    model_name: str = "sonnet",
    fix_mode: bool = False,
    sop_path: str = ""
) -> Agent
```

**Process**:

1. **AWS Session Setup**
   - Creates boto3 session with specified profile/region
   - Verifies credentials via STS GetCallerIdentity
   - Displays account ID for confirmation

2. **Bedrock Model Initialization**
   - Resolves model name to full model ID
   - Creates BedrockModel instance with boto session
   - Handles initialization errors gracefully

3. **System Prompt Selection**
   - Chooses REPORT or FIX mode prompt based on `fix_mode` flag
   - Embeds strict validation rules and remediation logic

4. **Tool Selection**
   - Calls `get_tools_for_sop()` to select relevant tools
   - Reduces context size by excluding unnecessary tools

5. **Agent Instantiation**
   - Creates Strands Agent with model, tools, and system prompt
   - Returns ready-to-use agent instance

## Main Execution Flow

### Command-Line Interface

```bash
python sop_executor.py [sop] [options]
```

**Arguments**:
- `sop`: SOP filename to execute (optional)
- `--profile, -p`: AWS profile for Bedrock
- `--region, -r`: AWS region (default: us-east-1)
- `--model, -m`: Model choice (haiku, sonnet, opus, etc.)
- `--fix, -f`: Enable autonomous fix mode
- `--mode`: Execution mode (sop, gitops)
- `--repo`: SOP repository path

### Execution Modes

#### 1. Direct SOP Execution

```bash
python sop_executor.py 03-validation.md --fix
```

**Flow**:
1. Resolves SOP path (adds repo prefix if needed)
2. Creates agent with tools for that SOP
3. Sends prompt: "Execute SOP: {path}\nValidate and remediate as needed."
4. Agent reads, parses, executes, validates, and remediates

#### 2. GitOps Mode

```bash
python sop_executor.py --mode gitops --fix
```

**Flow**:
1. Loads ArgoCD tools
2. Sends multi-step prompt:
   - Check ArgoCD status
   - If OutOfSync: validate SR-IOV/Multus, then sync
   - Run validation SOP
   - Remediate failures
3. Agent orchestrates entire GitOps workflow

#### 3. Interactive Mode

```bash
python sop_executor.py
```

**Flow**:
1. Agent lists available SOPs
2. Asks user which SOP to execute
3. Waits for user selection
4. Executes selected SOP

### Error Handling

```python
try:
    result = agent(prompt)
    banner("📊 Final Report", C.GREEN)
    print(result)
except KeyboardInterrupt:
    print(f"\n{C.YELLOW}⚠️  Interrupted by user{C.END}")
    raise SystemExit(130)
except Exception as e:
    banner("❌ Agent Error", C.RED)
    print(f"{C.RED}Error type: {type(e).__name__}{C.END}")
    print(f"{C.RED}Error: {e}{C.END}")
    traceback.print_exc()
    logger.exception("Agent execution failed")
    raise SystemExit(1)
```

**Handled Scenarios**:
- **KeyboardInterrupt**: Graceful exit with status 130
- **AWS Credential Errors**: Early detection during agent creation
- **Bedrock API Errors**: Caught during model initialization
- **General Exceptions**: Full traceback logged for debugging

## Key Design Patterns

### 1. Strict Validation Philosophy

The agent is designed to be **unforgiving** in validation:
- No rationalization of failures
- Binary pass/fail decisions
- Explicit failure conditions in system prompt
- Forces proper remediation rather than workarounds

### 2. Tool-Based Architecture

All operations are exposed as `@tool` decorated functions:
- LLM decides which tools to call and when
- Tools provide structured output for LLM reasoning
- Enables autonomous decision-making

### 3. Dynamic Tool Selection

Tools are scoped to the SOP being executed:
- Reduces token usage
- Prevents irrelevant tool calls
- Improves agent focus and performance

### 4. Colored Output for Observability

Every tool call is visually distinct:
- Rotating colors for tool calls
- Status indicators (✅/❌)
- Hierarchical indentation (└─)
- Makes debugging and monitoring easier

### 5. Separation of Concerns

- **Command Execution**: `run_cmd()` handles all subprocess logic
- **Tool Functions**: Thin wrappers that call `run_cmd()` and format output
- **Agent Logic**: LLM decides orchestration and remediation strategy
- **System Prompts**: Encode domain knowledge and validation rules

## Use Cases

### 1. Pre-Deployment Validation

```bash
python sop_executor.py 03-validation.md
```

Validates 5G App deployment without making changes:
- Checks pod status
- Validates SR-IOV resources
- Tests gRPC connectivity
- Verifies BGP sessions
- Reports all issues

### 2. Autonomous Deployment

```bash
python sop_executor.py 02-deployment.md --fix
```

Deploys and self-heals:
- Executes deployment steps
- Detects failures automatically
- Applies remediations
- Retries until success

### 3. GitOps Pre-Commit Gate

```bash
python sop_executor.py --mode gitops --fix
```

CI/CD integration:
- Checks ArgoCD sync status
- Validates infrastructure prerequisites
- Syncs application if ready
- Runs post-sync validation
- Blocks merge if validation fails

### 4. Interactive Troubleshooting

```bash
python sop_executor.py
```

Guided troubleshooting:
- Lists available SOPs
- User selects relevant procedure
- Agent executes and reports findings
- Useful for on-call engineers

## Integration Points

### AWS Bedrock

- Uses boto3 session for authentication
- Supports multiple AWS profiles
- Regional endpoint configuration
- Supports all Claude model variants

### Kubernetes

- Requires kubectl configured with cluster access
- Uses default kubeconfig context
- Supports namespace-scoped operations
- Integrates with ArgoCD for GitOps

### SSH/Remote Execution

- Requires SSH key-based authentication
- Disables strict host key checking for automation
- Supports interactive sessions via expect
- Used for network device configuration

## Security Considerations

### 1. Command Injection Protection

```python
result = subprocess.run(
    cmd if shell else shlex.split(cmd),
    shell=shell,
    ...
)
```

Uses `shlex.split()` for non-shell commands to prevent injection.

### 2. Timeout Protection

All commands have configurable timeouts:
- Prevents hung processes
- Default 120s for general commands
- 60s for kubectl operations
- 30s for SSH commands

### 3. Credential Management

- Uses AWS profiles (no hardcoded credentials)
- SSH key-based authentication
- Verifies AWS identity before execution
- Logs account ID for audit trail

### 4. Error Exposure

- Full error messages logged
- Stderr captured and displayed
- Exit codes always checked
- Prevents silent failures

## Performance Characteristics

### Token Efficiency

- Dynamic tool selection reduces context size
- Structured output from tools (not raw logs)
- Truncated command display in logs
- Typical SOP execution: 5,000-15,000 tokens

### Execution Speed

- Haiku model: ~2-5 seconds per tool call
- Sonnet model: ~5-10 seconds per tool call
- Opus model: ~10-20 seconds per tool call
- Parallel tool calls not supported (sequential execution)

### Reliability

- Automatic retry logic (max 3 attempts)
- Timeout protection on all commands
- Graceful degradation on tool failures
- Comprehensive error logging

## Limitations

1. **Sequential Execution**: Tools are called one at a time (no parallelization)
2. **No State Persistence**: Each run is independent (no memory between executions)
3. **Single SOP Focus**: Cannot execute multiple SOPs simultaneously
4. **LLM Dependency**: Requires Bedrock API availability
5. **Kubernetes Context**: Uses default kubectl context (no multi-cluster support)

## Future Enhancements

Potential improvements mentioned in code structure:

1. **Parallel Tool Execution**: Strands framework supports concurrent tool calls
2. **State Persistence**: Save execution history for trend analysis
3. **Multi-Cluster Support**: Dynamic kubeconfig context switching
4. **Webhook Integration**: Trigger executions via API
5. **Metrics Export**: Prometheus/CloudWatch integration
6. **SOP Versioning**: Track SOP changes and execution history

## Conclusion

The SOP Executor Agent is a production-grade automation system that combines:
- **AI reasoning** (Claude via Bedrock)
- **Structured procedures** (Markdown SOPs)
- **Infrastructure operations** (Kubernetes, SSH, ArgoCD)
- **Autonomous remediation** (Self-healing capabilities)

It demonstrates how LLMs can be used for operational automation beyond simple chatbots, providing intelligent orchestration of complex deployment and validation workflows.
