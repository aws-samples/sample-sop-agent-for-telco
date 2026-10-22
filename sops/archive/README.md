# Archived SOPs

SOPs retired from the active set when the workshop moved to Free5GC + PacketRusher on
EKS (workshop-v3). They target Open5GS / srsRAN / UERANSIM, bare-metal nodes
(ANPA, Tinkerbell, PTP, hugepages, RT kernel), NEC UPF on Outposts, or the
Telegraf → InfluxDB monitoring stack — none of which exist in the workshop
environment.

They are kept for reference and as source material (e.g. `core/remediate-upf-pfcp-loss.md`
for a future SMF↔UPF PFCP SOP, `infra/remediate-os-memory-pressure.md` for node
diagnostics). They are excluded from `/api/sops`, from `list_sops`, and from
SOPBridge resolution, and no alarm binds to them.

Active SOPs live in `sops/day{0,1,2}-*/`; see `docs/workshop-v3.md`.
