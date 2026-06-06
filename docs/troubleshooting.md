# Workshop Troubleshooting Decision Tree

Find your symptom, follow the branch.

## "Nothing is working"

1. Is the bootstrap log saying COMPLETED?
   - **No** → Wait. Check progress: `sudo tail -f /var/log/anra-bootstrap.log`
   - **Yes** → Continue to step 2
2. Can you reach kubectl?
   - Run `kubectl get nodes`
   - **"No resources found"** → Cluster create failed → contact organizer
   - **Some Ready, some NotReady** → Node pressure. Run `kubectl describe nodes | grep -A5 Conditions`
   - **All Ready** → Cluster is fine, problem is elsewhere → continue below

## "Dashboard not loading"

1. Can you reach the public IP? (`curl http://<jump_host_ip>:8080`)
   - **Connection refused** → ANRA pod not running
     - SSH in: `kubectl get pods -n anra`
     - If pod is CrashLoopBackOff: `kubectl logs deployment/anra -n anra --tail=50`
   - **Timeout** → Security group blocking your IP
     - Check EC2 console → Security Groups → port 8080 inbound rule
   - **401 Unauthorized** → Use credentials from Workshop Studio outputs
   - **502/503** → Pod restarting, wait 30s and retry

## "Agent gives wrong answer"

1. Is the question about live state (pod counts, names, status)?
   - **Yes** → Ask: "Use kubectl to count all pods in all namespaces"
   - **No** → Is it about an alarm or SOP?
     - **Alarm** → Check dashboard alarm panel matches what agent says
     - **SOP** → Ask agent to `read_sop("<sop-name>.md")` and compare

## "Alarm not firing"

1. Is it a missing-NF alarm (e.g., `smf_missing`)?
   - **Yes** → Wait 60-90 seconds after scaling to 0. The `absent_for` operator has a grace period.
   - **No** → Is the metric being reported?
     - Check InfluxDB: `kubectl exec -n srsran deploy/influxdb -- influx query 'from(bucket:"srsran") |> range(start:-1m) |> last()'`
     - **No data** → Telegraf not scraping. Check `kubectl logs -n srsran deploy/telegraf`
     - **Data exists** → Check the condition in `anra-config.yaml` matches reality

## "SOP execution failed"

1. Check the execution log in the dashboard timeline
2. What step failed?
   - **kubectl command** → Run it manually to see the error
   - **helm command** → Check if the release exists: `helm list -A`
   - **Agent crashed mid-SOP** → Check for ThrottlingException in logs
     - If throttled: wait 60s, retry
     - If token budget exceeded: increase `ANRA_SESSION_TOKEN_BUDGET`

## "Bedrock errors"

1. **AccessDeniedException** → Enable model access in Bedrock console
2. **ThrottlingException** → Wait 30-60s, agent will auto-retry (up to 5 times)
3. **ModelNotReadyException** → Model is cold-starting, retry in 10s
4. **Token budget exceeded** → Set `ANRA_SESSION_TOKEN_BUDGET=200000`

## "Pods stuck in Pending/Error"

1. Run `kubectl describe pod <pod-name> -n <ns>` → read Events section
2. Common causes:
   - **Insufficient CPU/memory** → Node is full. Check `kubectl top nodes`
   - **ImagePullBackOff** → ECR permission or image tag wrong
   - **PVC Pending** → No StorageClass or EBS CSI driver missing
3. If stuck and can't recover: run `reset-cluster.md` SOP

## "I want to start over"

- **Soft reset** (keeps cluster): Run `reset-cluster.md` SOP
- **Hard reset** (new environment): Restart the Workshop Studio event
