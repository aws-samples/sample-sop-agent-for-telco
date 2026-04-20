# App SOP Executor Agent

Generic Strands Agent that reads, parses, and executes SOPs with automatic remediation.

## Features

- **SOP Discovery**: Lists available SOPs from any git repo
- **Markdown Parsing**: Extracts Prerequisites, Steps, Success Criteria, Troubleshooting
- **Sequential Execution**: Runs bash commands from SOPs
- **Validation**: Compares output against success criteria
- **Auto-Remediation**: Matches failures to troubleshooting section and applies fixes
- **Retry Logic**: Retries failed steps after remediation (max 2 attempts)

## Usage

```bash
# Install dependencies
pip install strands-agents boto3

# Run specific SOP
python sop_executor.py 03-validation.md

# Interactive mode (lists SOPs and prompts)
python sop_executor.py
```

## Supported SOP Structure

SOPs must have these markdown sections:

```markdown
# SOP Title

## Prerequisites
- Requirement 1
- Requirement 2

## Procedure

### 1. Step Title
```bash
command here
```

### 2. Another Step
```bash
another command
```

## Success Criteria
- Expected outcome 1
- Expected outcome 2

## Troubleshooting

**Problem description:**
```bash
fix command
```
```

## Available Tools

| Tool | Description |
|------|-------------|
| `list_sops` | List SOPs in repository |
| `read_sop` | Read SOP file content |
| `parse_sop` | Extract structured sections |
| `run_command` | Execute shell command |
| `kubectl` | Run kubectl commands |
| `kubectl_exec` | Execute command in pod |
| `get_pod_name` | Get pod name by label |
| `check_pod_status` | Get pod status in namespace |
| `get_pod_events` | Get events for pod |
| `get_pod_logs` | Get pod logs |
| `describe_node` | Get node resources |

## Example Output

```
=== SOP: 03-validation.md ===
Prerequisites: PASS
Step 1: Check Pods - PASS
Step 2: Check gRPC - PASS
Step 3: Check GWU - PASS
Step 4: Check BGP - PASS
Step 5: Check Interfaces - PASS
Step 6: Check CNI - PASS
Step 7: Check SR-IOV - PASS
Overall: PASS

Issues Found: None

Remediations Applied: None
```
