# UERANSIM for ANRA

Simulated UE + gNB for testing the 5G core network end-to-end.

## Quick Start
```bash
kubectl apply -f deployments.yaml -n srsran
```

## Critical UE Config Fields
These are often missing and cause silent failures:
- `integrity` (IA1/IA2/IA3) — without these, security mode command fails
- `ciphering` (EA1/EA2/EA3) — without these, NAS encryption fails
- `integrityMaxRate` — without this, UE rejects security context
- `opType: 'OPC'` — must be OPC not OP
- `/dev/net/tun` mount + privileged — required for TUN interface

## Known Issues
- **gnbSearchList must match gNB pod IP** — if gNB restarts, update UE config
- **Subscriber must exist in MongoDB** — `PLMN_NOT_ALLOWED` means missing subscriber
