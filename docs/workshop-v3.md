# Workshop-v3 Free5GC Delivery Profile

`workshop-v3` is based on `origin/workshop-v2` commit `e938040ba0042156e2811d10b9fb097a73268393` and changes the attendee path to:

```text
CloudFormation → EKS + Multus + gtp5g
                         │
                         ▼
              Free5GC + PacketRusher
                         │
                         ▼
       Prometheus + Alertmanager + Grafana
                         │
                         ▼
                   ANDA + ANRA
```

ANPA source and its Helm chart remain in the repository for compatibility, but the workshop-v3 umbrella values disable ANPA and the workshop scripts never install it. CloudFormation is the only Day-0 provisioning mechanism for this profile.

## Source assets

The initial infrastructure, deployment scripts, Free5GC/PacketRusher charts, dashboard, and E2E tests are adapted from:

```text
/workplace/dlupescu/reInvent/ind321-autonomous-networks-lcm-ops
```

Workshop-v3 preserves the following validated version and address contracts:

- EKS `1.33`
- AWS VPC CNI `v1.20.4-eksbuild.1`
- Multus `v4.0.2-eksbuild.1`
- gtp5g `v0.9.15`
- Free5GC `v4.2.3` in `free5gc-0.0.2.tgz`
- kube-prometheus-stack `91.5.0`
- N2/N3/N4/N6 networks `10.100.4.0/24` through `10.100.7.0/24`

The Multus CIDRs, launch-template ENI order, and static chart addresses are one coupled contract. Do not change only one layer.

## Ordered workshop path

1. `provision-free5gc-cloudformation.sop.md` creates the infrastructure.
2. `deploy-free5gc-core.sop.md` configures Multus/gtp5g and installs Free5GC plus PacketRusher.
3. `validate-free5gc-e2e.sop.md` proves registration, PDU session, DNS, traffic, and throughput.
4. `deploy-free5gc-monitoring-anra.sop.md` installs Prometheus, Alertmanager, Grafana, ANDA, and ANRA.

The one-shot equivalent is:

```bash
export STACK_NAME=telco-dryrun-01
export AWS_DEFAULT_REGION=us-west-2
export BASTION_KEY=<existing-key-pair>
export AGENT_IMAGE_TAG=<immutable-workshop-v3-tag>
bash scripts/free5gc/00-run-all.sh
```

## Security posture

This is disposable workshop infrastructure, not a production baseline. Compared with the IND321 source template, workshop-v3:

- Defaults public SSH/dashboard ingress to `127.0.0.1/32`; use SSM port forwarding.
- Scopes the Multus security group to the workshop VPC.
- Removes worker-node `AWSCloudFormationFullAccess` and `ElasticLoadBalancingFullAccess`.
- Requires generated or supplied Grafana and ANRA passwords rather than checked-in passwords.
- Keeps IMDSv2 required.
- Disables the public EKS API endpoint; kubectl access runs through the bastion and private endpoint.

The EKS node role currently receives Bedrock invocation permissions because the workshop does not create EKS Pod Identity associations. A production adaptation should replace this with least-privilege Pod Identity roles for ANDA and ANRA.

## Day-2 alarms, SOP bindings, and fault injection

ANRA receives the workshop alarms from Alertmanager (`configs/free5gc-monitoring/free5gc-alert-rules.yaml`). Each alert is bound to a remediation SOP in three places that must stay in sync; the first one found wins at runtime (`monitor.resolve_sop_reference()`):

1. the rule's `annotations.sop` (path relative to `sops/`),
2. `config.alarms[].sop` in `configs/free5gc-monitoring/anra-values.yaml`,
3. `alarms.<name>.sop` in `alarm-references/free5gc.yaml` (vendor catalog).

If the bound file does not exist, `resolve_sop()` falls back to generating a SOP with Bedrock, so a binding can be added before its SOP is written.

| Alert | `for:` | Participant injection (own account, reversible) | SOP |
|---|---|---|---|
| `free5gc_nf_unavailable` | 30s | `kubectl scale deploy/free5gc-amf-deployment -n free5gc --replicas=0` | `day2-remediate/core/free5gc-nf-unavailable.md` |
| `free5gc_pod_restarting` | 30s | kill PID 1 in the SMF container three times, 20s apart | `day2-remediate/core/free5gc-pod-crashloop.md` |
| `free5gc_registration_unavailable` | 30s | `kubectl scale deploy/packetrusher-packetrusher -n free5gc --replicas=0` | `day2-remediate/core/free5gc-registration-unavailable.md` |
| `free5gc_node_not_ready` | 1m | stage demo only (stop kubelet via SSM); not in the participant script | `day2-remediate/infra/free5gc-node-not-ready.md` |
| `free5gc_metrics_missing` | 2m | none — hygiene rule, not part of the storyline | (Bedrock-generated) |

**Workshop timing tuning.** Detection latency is the sum of: kube-state-metrics scrape (≤30s), rule evaluation (`interval: 15s`), the `for:` window, Alertmanager `group_wait: 5s`, and ANRA's poll of Alertmanager (`monitoring.pollIntervalSeconds: 15`). With the values above an injected fault typically reaches ANRA as a pending approval in 45–75 seconds (worst case ≈2 minutes, measured ~90s before the tuning). Production rules should debounce for several minutes to avoid paging on transient blips; every tuned value carries a `WORKSHOP TUNING` comment.

**Guardrails.** `free5gc` is a `protected_namespace` in `anra-values.yaml`; remediation SOPs must stay within what that guardrail permits. Do not use MongoDB as a fault target: `free5gc-mongodb` uses `emptyDir`, so deleting the pod loses the single provisioned subscriber and PacketRusher cannot re-register until `sub-prov-job` is re-run (follow-up: make Mongo resilient).

## Remaining limitations

- The CloudFormation template attaches secondary ENIs and builds gtp5g in launch-template user data; these steps are imperative and depend on external repositories being reachable.
- The inherited IND321 IP plan does not yet create subnet CIDR reservations for the static `.36/.37` Multus addresses.
- Live AWS/Free5GC validation requires a disposable account and was not performed while assembling the branch.
- Day-2 PLMN fault injection and remediation are separate follow-up work; SOP 3 validates alarm transport with a deliberately non-remediating test alert.
