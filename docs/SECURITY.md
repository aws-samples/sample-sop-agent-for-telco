# Security Considerations

This document explains the security model of the SOP Agent and addresses findings from security scanners.

## Accepted Risks

### Shell Command Execution (subprocess with shell=True)

**Finding:** `python.lang.security.audit.subprocess-shell-true`, `dangerous-subprocess-use-audit`

**Explanation:** The SOP Agent is designed to execute shell commands as part of Standard Operating Procedures. This is core functionality, not a vulnerability.

**Mitigations:**
1. **Source validation** - SOPs are loaded only from the local `sops/` directory, not from user input
2. **No user-supplied commands** - Commands come from pre-written SOP files, not API parameters
3. **RBAC controls** - Kubernetes RBAC limits what the agent can do in the cluster
4. **Network isolation** - Agent runs in a controlled EKS environment

**Files with accepted subprocess usage:**
- `sop-agent/sop_executor.py` - Core SOP execution engine
- `webui/backend/api.py` - kubectl commands for status checks
- `bootstrap.py` - Deployment automation
- `day2-monitor/monitor.py` - Monitoring commands

All instances are marked with `# nosec B602` or `# nosec B603` comments.

### Container Base Images

**Finding:** `bosco/non-ecr-docker-image`

**Resolution:** Dockerfile updated to use `public.ecr.aws/docker/library/` base images.

### Binding to 0.0.0.0 (B104)

**Finding:** `hardcoded_bind_all_interfaces`

**Explanation:** Required for container networking. The service runs inside a Kubernetes pod and needs to accept connections from the cluster network.

**Mitigation:** Access is controlled via Kubernetes NetworkPolicy and AWS Security Groups.

## Security Best Practices

1. **Deploy in isolated namespace** - Don't run in `kube-system` or with cluster-admin
2. **Use IRSA** - Service account uses IAM Roles for Service Accounts, not static credentials
3. **Limit Bedrock access** - IAM policy restricts to specific model ARNs
4. **Review SOPs** - Audit SOP files before deploying to production
5. **Enable CloudTrail** - Monitor Bedrock API calls

## Rubric Findings (Content Quality)

The following are documentation quality suggestions, not security issues:
- "Content Flow and Completeness" - Documentation structure
- "External Resources and Licensing" - Link validation
- "URL Validation" - Checking URLs are accessible

These are informational and do not block release.
