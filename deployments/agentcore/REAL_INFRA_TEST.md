# Real-Infra Test Results — AgentCore Runtime Deployment

> **Test date:** 2026-06-05  
> **Account:** 833542146025  
> **Region:** us-west-2  
> **Profile:** cse-dev-test

This document records the end-to-end deployment and live invocation tests of the ANRA agent on Amazon Bedrock AgentCore Runtime.

## Deployment artifacts

| Artifact | Value |
|----------|-------|
| ECR repository | `833542146025.dkr.ecr.us-west-2.amazonaws.com/bedrock-agentcore-anra-agent` |
| Image tag | `v1`, `latest` |
| Image size | 168 MB (ARM64) |
| Image digest | `sha256:17d501745d343309f3bfb317c458b9464f9581d0f066f1b995abbed90395c06f` |
| Agent runtime ID | `anra_agent-nXGVDD4CEc` |
| Agent runtime ARN | `arn:aws:bedrock-agentcore:us-west-2:833542146025:runtime/anra_agent-nXGVDD4CEc` |
| Status | READY |
| Provisioning time | < 60 seconds |
| Network mode | PUBLIC |
| Execution role | `AmazonBedrockAgentCoreSDKRuntime-us-west-2-8d77b0ecc9` |
| Default model | Claude Haiku 4.5 |

## Build and deployment process

```
1. Created ECR repository:  bedrock-agentcore-anra-agent
2. Set up buildx with QEMU: docker buildx create + tonistiigi/binfmt
3. Built ARM64 image:        docker buildx build --platform linux/arm64
4. Pushed to ECR:            (16s push)
5. Created runtime:          bedrock-agentcore-control:CreateAgentRuntime
6. Polled to READY:          < 60s end-to-end
```

## Live test results

### Test 1: Free-form prompt (cold start)

**Payload:**
```json
{"prompt": "List 3 SOPs in this repository, one sentence each."}
```

**Result:** HTTP 200, ~14s
The agent used `list_sops` and returned the available SOP (limitation: top-level glob only finds `TEMPLATE.md`).

### Test 2: process_alarms — correlated Day-2 alarms ✅

**Payload:**
```json
{
  "action": "process_alarms",
  "alarms": [
    {"name": "nf-crashloop", "namespace": "5gc", "severity": "high",
     "details": "AMF pod restarting every 30s with OOMKilled"},
    {"name": "memory-pressure", "node": "node-2", "severity": "warning",
     "details": "Available memory 2%, PSI stalls 30s/60s"}
  ]
}
```

**Result:** HTTP 200, **32.9 seconds**

The agent correctly:
- Identified the **causal chain**: node memory pressure → OOM kill → CrashLoopBackOff
- Recognized the AMF pod is a **victim, not the cause**
- Recommended `remediate-os-memory-pressure.md` as the **primary** SOP
- Recommended `remediate-nf-crashloop.md` as the **conditional secondary** SOP
- Provided a structured causal chain diagram in the response

This is **exactly the triage logic** required for Day-2 autonomous remediation — and it's running on a managed AgentCore Runtime with no infrastructure to operate.

### Test 3: run_sop — execute a real SOP file ✅

**Payload:**
```json
{
  "action": "run_sop",
  "sop": "remediate-nf-crashloop",
  "fix_mode": false,
  "model": "haiku"
}
```

**Result:** HTTP 200, **21.4 seconds**

The agent:
1. Resolved the SOP path: `/app/sops/workshop-remediate/remediate-nf-crashloop.md` ✅
2. Read and parsed the SOP file ✅
3. Attempted to execute each step ✅
4. Correctly reported environment limitations:
   - kubectl not available (exit 127)
   - SSH not available
   - AWS SSM not available
5. Provided a structured failure summary with required-to-proceed items

This is the **expected behavior** for Phase 1 — the agent has no tools wired up yet. The honest failure reporting validates that:
- Path resolution works
- SOP parsing works
- Tool dispatch works (and correctly reports tool unavailability)
- The agent doesn't hallucinate success when tools are missing

This is **exactly the gap Phase 2 (Lambda Gateway target) closes** — those Lambda-backed tools provide kubectl/SSM/InfluxDB.

## What's proven

| Capability | Status |
|------------|--------|
| Container build for ARM64 | ✅ |
| ECR push from local | ✅ |
| AgentCore Runtime provisioning via boto3 | ✅ |
| Container starts, listens on /invocations | ✅ |
| Strands SDK + Bedrock InvokeModel | ✅ |
| Multi-tier model selection (Haiku) | ✅ |
| Alarm correlation reasoning | ✅ |
| SOP file resolution and parsing | ✅ |
| Honest failure reporting when tools missing | ✅ |

## What's next

Phase 1 deployment proven. Remaining work:

- **Phase 2**: Deploy Lambda + Gateway target to wire up kubectl, SSM, InfluxDB tools
- **Phase 3**: Add Cedar Policy for VoNR safety guardrails
- **Phase 4**: EventBridge schedule + API Gateway webhook for closed-loop Day-2
- **Phase 5**: Replace React UI with API Gateway + S3-hosted static UI

## Cleanup

To remove the deployed runtime:

```bash
aws --profile cse-dev-test --region us-west-2 \
  bedrock-agentcore-control delete-agent-runtime \
  --agent-runtime-id anra_agent-nXGVDD4CEc
```
