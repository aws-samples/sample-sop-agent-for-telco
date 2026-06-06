# Known Issues — ANRA Workshop

Last updated: 2026-06-06

This page lists issues participants have hit and the recommended fix.
If you hit something not listed here, click "Report this issue" in the
dashboard or open a GitHub issue.

## Workflow issues

### Bootstrap takes longer than 20 minutes

**Symptom**: Setup page says "Wait ~15-20 minutes" but it's still going at 25 min.

**Cause**: EKS create time varies by AWS region/account. Some accounts hit
service quotas that cause retries.

**Fix**: Tail the bootstrap log to see current phase:
```bash
ssm-tail() { aws ssm start-session --target $JUMPHOST_INSTANCE_ID \
    --document-name AWS-StartInteractiveCommand \
    --parameters command="sudo tail -f /var/log/anra-bootstrap.log"; }
ssm-tail
```
If stuck at "Creating EKS cluster" for >25 min, it may have failed silently.
Check `/var/log/anra-bootstrap.log` on the jump host for `EXIT CODE` messages.

### Re-running validate-e2e fails with HTTP 400 from AUSF

**Symptom**: Day-1 SOPs ran successfully, but running `validate-e2e.md`
a second time produces "Authentication failed" from AUSF.

**Cause**: AUSF maintains subscriber state between runs. Re-running with the
same subscriber triggers a known Open5GS bug.

**Fix**: Run the new `reset-cluster.md` SOP, then redeploy.

### Ask ANRA chat says "21 NF pods" but kubectl shows more

**Symptom**: Chat reports a smaller pod count than `kubectl get pods -A`.

**Cause**: Before workshop v2, the chat agent answered from a topology snapshot,
which only counted 5G NFs (not system pods). Fixed in v2.0+.

**Fix**: If you're on v1.x of the workshop, the difference is intentional —
the snapshot only counts 5G NFs. To get total cluster pod count, ask the agent
"Use kubectl to count all pods" or run the command yourself.

## Bedrock issues

### "AccessDeniedException" when invoking models

**Symptom**: Agent logs show `AccessDeniedException: User: ... is not authorized to perform: bedrock:InvokeModel`

**Cause**: Bedrock model access not enabled in your account, or the IAM role
doesn't have permissions.

**Fix**:
1. Go to the Bedrock console → Model access
2. Click "Enable specific models"
3. Enable at least one Anthropic Claude model
4. Wait 2-3 minutes for the change to propagate
5. Retry the agent invocation

### "ThrottlingException" or session aborted with "Token budget exceeded"

**Symptom**: Agent halts mid-execution.

**Cause**: Either Bedrock account-level throttling or our token budget
(default 100k tokens per session).

**Fix**:
- If throttling: wait 30-60s and retry. The agent has exponential backoff.
- If token budget: increase via `ANRA_SESSION_TOKEN_BUDGET=200000` env var
  (only do this in environments where you trust the agent's behavior).

## Workshop dashboard issues

### Dashboard not accessible at the public IP:8080

**Symptom**: Connection refused or timeout.

**Cause**: ANRA pod isn't ready, or security group rule blocks your IP.

**Fix**:
1. SSH to jump host via SSM
2. Run `kubectl get pods -n anra` — pod should be `1/1 Running`
3. If not, `kubectl logs deployment/anra -n anra | tail -30` to see why
4. Check the EC2 security group for the jump host has port 8080 open to your IP

### Scaling SMF to 0 doesn't trigger an alarm

**Symptom**: `kubectl scale deploy/smf --replicas=0` doesn't fire an alarm
in the dashboard.

**Cause**: Before workshop v2, alarms only fired on threshold violations of
*active* metrics. When SMF was scaled to 0, no metrics were emitted.

**Fix**: In v2.0+, the `smf_missing` alarm uses `absent_for 60s` to detect
this. Wait 60-90 seconds after scaling. If still no alarm, check the monitor
logs for `_metric_last_seen` state.

## Recovery procedures

### "I broke everything"

Run `reset-cluster.md`. It tears down the 5G workloads and redeploys cleanly
without rebuilding the EKS cluster.

### "I lost my SSM session"

The session can be re-established. Find the jump host instance ID in the
Workshop Studio dashboard outputs, then:
```bash
aws ssm start-session --target i-xxxxxxxxxx
```

### "I want to start over completely"

Restart the workshop event from the Workshop Studio dashboard. This deletes
all account resources and provisions a fresh environment.
