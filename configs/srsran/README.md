# srsRAN gNB for ANRA

Deploy srsRAN Project as a combined CU/DU on a Dell edge node.

## Quick Start
```bash
kubectl apply -f deployment.yaml -n srsran
```

## Key Decisions
- **hostNetwork: true** — required for fronthaul and GTP-U
- **testmode** — generates synthetic UE traffic at MAC layer (no real RF)
- **WebSocket on :55555** — Telegraf-RAN connects here for metrics
- **Pin to specific edge node** — use `nodeName` to avoid port conflicts with UPF
- **100 MHz channel** — realistic 5G n78 bandwidth

## Scaling
- `nof_ues`: 1-64 per cell (MAC-layer test UEs)
- `cells`: add entries for multi-cell (each needs unique PCI + ARFCN)
