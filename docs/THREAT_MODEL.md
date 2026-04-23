# Threat Model: sample-sop-agent-for-strands

## 1. System Overview

An AI-powered SOP execution agent that uses Strands Agents SDK and Amazon Bedrock to automate Standard Operating Procedures on EKS clusters. The agent reads SOPs from YAML/markdown files, parses them into DAGs, and executes steps using MCP tools (kubectl, SSH, Shell).

### Components

| Component | Description | Trust Level |
|-----------|-------------|-------------|
| Web UI (React + FastAPI) | User interface for SOP management | Authenticated (HTTP Basic Auth) |
| SOP Executor | Strands SDK agent executing SOP steps | Internal — runs in-cluster |
| MCP Tools (kubectl, SSH, Shell) | Infrastructure interaction tools | Privileged — executes commands |
| Amazon Bedrock (Claude models) | LLM for command generation and reasoning | External service — API calls |
| Day 2 Monitor | Polls Alertmanager, auto-generates remediation SOPs | Internal — automated loop |
| EKS Cluster | Target infrastructure with NF pods | Target environment |

### Data Flow

```
Operator → Web UI → FastAPI → SOP Executor → Bedrock (Claude)
                                    ↓
                              MCP Tools (kubectl/SSH/Shell)
                                    ↓
                              EKS Cluster (NF Pods)

Prometheus → Alertmanager → Day 2 Monitor → SOP Generator (Bedrock) → SOP Executor
```

---

## 2. Threat Analysis

### T1: Prompt Injection via Malicious SOP Content

**Threat:** An attacker with write access to the `sops/` directory could craft a malicious SOP that injects prompt instructions to override the agent's system prompt, causing it to execute unintended commands.

**Severity:** HIGH

**Mitigations:**
- SOPs are loaded only from the local `sops/` directory on disk, not from user HTTP input
- `SOPSteeringHooks` implements a dangerous command blocklist (e.g., `rm -rf /`, `kubectl delete namespace kube-system`)
- Namespace guard restricts operations to allowed namespaces
- Tool budget limits the number of tool calls per SOP execution
- SOP files should be version-controlled and reviewed before deployment

**Residual Risk:** MEDIUM — An insider with repo access could still craft adversarial SOPs. Mitigated by code review process and Git audit trail.

### T2: Command Injection via Agent-Generated Commands

**Threat:** The LLM generates shell commands that are executed via `subprocess`. A compromised or hallucinating model could generate destructive commands.

**Severity:** HIGH

**Mitigations:**
- `_BLOCKED_SHELL` patterns block dangerous shell commands (rm -rf, mkfs, dd, etc.)
- `_BLOCKED_KUBECTL` patterns block destructive kubectl operations (delete namespace, delete node, etc.)
- Read-only kubectl verb allowlist for monitoring endpoints
- `shlex.split()` used instead of `shell=True` where possible
- `bootstrap.py` uses conditional `shell=True` only when metacharacters are detected, otherwise uses `shlex.split`
- Kubernetes RBAC limits the service account's permissions
- Tool budget caps the number of tool invocations per execution

**Residual Risk:** LOW — Multiple layers of defense (blocklists + RBAC + budget) make exploitation difficult.

### T3: SSH Key Exposure

**Threat:** SSH private keys used by the `ssh_command` and `ssh_expect` tools could be exposed through logs, container images, or environment variables.

**Severity:** MEDIUM

**Mitigations:**
- SSH keys should be mounted via Kubernetes Secrets, not baked into container images
- `StrictHostKeyChecking=no` is used for automation (accepted risk for lab/demo environments)
- SSH timeout caps prevent indefinite connections (max 120s)
- Agent logs do not include SSH key material

**Recommendation:** For production, use AWS Secrets Manager or HashiCorp Vault for SSH key management. Document this in deployment guide.

### T4: Day 2 Monitor Auto-Remediation Risks

**Threat:** The Day 2 Monitor automatically generates and executes remediation SOPs based on Alertmanager alerts. A crafted or spoofed alert could trigger unintended remediation actions.

**Severity:** HIGH

**Mitigations:**
- Monitor polls Alertmanager via internal cluster networking (not exposed externally)
- Generated SOPs go through the same `SOPSteeringHooks` guardrails as manual SOPs
- Human approval gate for high-risk operations (namespace deletion, scaling to zero)
- Feedback loop evaluates remediation results and prevents repeated failed actions
- Adaptive steering learns from failures to prevent cascading issues

**Residual Risk:** MEDIUM — Automated remediation inherently carries risk. Human-in-the-loop for destructive operations is the primary control.

### T5: SOP Tampering

**Threat:** An attacker modifies SOP files on disk to inject malicious steps that execute during the next agent run.

**Severity:** MEDIUM

**Mitigations:**
- SOP files are stored in a Git repository with audit trail
- File system permissions restrict write access to the `sops/` directory
- Container runs as non-root user (`appuser`) with read-only filesystem where possible
- SOP upload API requires authentication (`verify_credentials`)

**Residual Risk:** LOW — Git-based workflow provides change tracking and review.

### T6: Privilege Escalation via ClusterRole

**Threat:** The agent's ClusterRole grants create/update/patch on deployments, services, and configmaps cluster-wide, which could be abused to deploy malicious workloads.

**Severity:** MEDIUM

**Mitigations:**
- ClusterRole is intentional for multi-namespace SOP execution (documented in `clusterrole.yaml`)
- Read-only access for most resources (get, list, watch)
- Write access limited to deployments, services, configmaps only
- No access to secrets, roles, rolebindings, or cluster-admin resources
- IRSA scopes IAM permissions to Bedrock API calls only

**Recommendation:** For production, replace ClusterRole with namespaced Roles scoped to specific target namespaces.

### T7: Data Exfiltration via Bedrock API

**Threat:** The agent sends SOP content and command outputs to Amazon Bedrock. Sensitive infrastructure data could be exposed.

**Severity:** LOW

**Mitigations:**
- Amazon Bedrock does not store or log customer prompts/completions (per AWS data privacy policy)
- IRSA IAM policy restricts Bedrock access to specific model ARNs
- No customer data is processed — only infrastructure commands and outputs
- CloudTrail logs all Bedrock API calls for audit

**Residual Risk:** LOW — AWS Bedrock data handling policies apply.

---

## 3. Risk Summary

| Threat | Severity | Residual Risk | Status |
|--------|----------|---------------|--------|
| T1: Prompt Injection via SOP | HIGH | MEDIUM | Mitigated (blocklists, namespace guard, tool budget) |
| T2: Command Injection | HIGH | LOW | Mitigated (multi-layer blocklists, RBAC, shlex) |
| T3: SSH Key Exposure | MEDIUM | LOW | Mitigated (K8s Secrets, no logging of keys) |
| T4: Day 2 Auto-Remediation | HIGH | MEDIUM | Mitigated (guardrails, human approval gate) |
| T5: SOP Tampering | MEDIUM | LOW | Mitigated (Git audit trail, auth required) |
| T6: Privilege Escalation | MEDIUM | LOW | Mitigated (scoped RBAC, documented) |
| T7: Data Exfiltration | LOW | LOW | Mitigated (Bedrock privacy, IRSA) |

---

## 4. Assumptions

1. This is **sample code** intended for workshops and demos, not production deployment
2. The EKS cluster is in a controlled environment with network isolation
3. SOP files are reviewed before deployment via Git workflow
4. Operators have appropriate AWS IAM permissions
5. Amazon Bedrock data privacy policies are in effect

## 5. References

- [PCSR Required Steps](https://console.harmony.a2z.com/engsec-docs/SA/SMGS-security-reviews/public-content-security-reviews#1-required-steps)
- [Strands Agents SDK](https://github.com/strands-agents/sdk-python)
- [Amazon Bedrock Security](https://docs.aws.amazon.com/bedrock/latest/userguide/security.html)
