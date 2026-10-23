# Fault-injection scenarios

Participant-run scripts that break the Free5GC network in a controlled, reversible way so
the agents can be watched detecting and remediating a real fault. Each `inject-*.sh`
explains what it simulates and what to expect before asking for confirmation (`--yes`
skips the prompt); each `restore-*.sh` is the manual fallback that does what the SOP would
do, without the agents.

| # | Script | Simulates | Alarm | SOP |
|---|---|---|---|---|
| 1 | `inject-amf-unavailable.sh` | AMF gone — total outage, UEs lose registration | `free5gc_nf_unavailable` (+ `free5gc_registration_unavailable` as side-effect) | `core/free5gc-nf-unavailable.md` |
| 2 | `inject-smf-crashloop.sh` | SMF flapping (OOM / node pressure) — data sessions drop | `free5gc_pod_restarting` | `core/free5gc-pod-crashloop.md` |
| 3 | `inject-registration-unavailable.sh` | Radio site lost — core healthy, no UE registered | `free5gc_registration_unavailable` | `core/free5gc-registration-unavailable.md` |

Rules the scripts enforce: only the `free5gc` namespace is touched; the baseline must be
healthy (all deployments 1/1) before injecting; one scenario at a time. Expected timing
with the workshop tuning: alarm → pending approval in about a minute, approve → recovered
in about two, alerts clear on their own shortly after.

Scripts live in the agent image under `/app/scripts/free5gc/scenarios/` and on the
bastion under `~/environment/workshop/scripts/free5gc/scenarios/`.
