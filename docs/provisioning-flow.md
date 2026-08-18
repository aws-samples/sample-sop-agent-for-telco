# Provisioning Flow — ANPA Bare-Metal Lifecycle

> How ANO provisions a bare-metal server from "rack and cable" to "EKS node running workloads."

## Overview

```
ProvisioningRequest CR
        │
        ▼
┌──────────────────────────────────────────────────────────────────────┐
│  ANPA State Machine                                                   │
│                                                                       │
│  Pending ──► Validating ──► Provisioning ──► WaitingForNodes ──► Ready│
│                                                         │             │
│                                                    (timeout 30m)      │
│                                                         ▼             │
│                                                      Failed           │
│                                                  (AI diagnosis)       │
└──────────────────────────────────────────────────────────────────────┘
```

## State Machine Details

### Phase 1: Pending → Validating

**Trigger:** New `ProvisioningRequest` CR detected with empty/Pending phase.

**Preflight checks (`_run_preflight`):**

| Check | How | Failure Mode |
|-------|-----|-------------|
| Required fields present | Validate `osArchive`, `gateway`, `netmaskCIDR`, `ip` per node | Missing field → error message |
| HardwareInventory CR exists | `kubectl get hardwareinventory/<hostname>` | Not found → "run Redfish discovery first" |
| BMC reachable | `curl https://<bmc_ip>/redfish/v1` (accepts 200 or 401) | Timeout → "BMC unreachable" |
| Cross-validate (optional) | Compare BMC CPU count vs `nproc` via SSM | Mismatch → warning (non-fatal) |

### Phase 2: Validating → Provisioning

**Actions:**
1. Emit `BareMetalInventory` CR (hardware details for kro)
2. Emit `BareMetalProvision` CR (triggers Tinkerbell workflow via kro ResourceGroup)

The kro ResourceGroup Definition (RGD) translates these CRs into:
- Tinkerbell `Hardware` resource (BMC MAC, IP assignment)
- Tinkerbell `Template` (action sequence: stream OS image → install → configure → reboot)
- Tinkerbell `Workflow` (binds template to hardware)

### Phase 3: Provisioning → WaitingForNodes

**Monitoring:** ANPA polls Tinkerbell workflow status every 30s:
```
kubectl get workflow/<hostname> -n <tink_ns> -o jsonpath='{.status.state}'
```

Transitions when all workflows reach `STATE_SUCCESS`.

### Phase 4: WaitingForNodes → Ready

**Verification:** Checks EKS node registration:
```
kubectl get node/<hostname> -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
```

Must return `True` for all nodes in the request.

### Failure Handling

After 5 retries (configurable via `_MAX_RETRIES`):
1. Transitions to `Failed` state
2. Invokes `handle_provisioning_failure()` — Bedrock-powered diagnosis
3. AI examines workflow logs, pod events, network state
4. Diagnosis (max 500 chars) stored in `status.message`

## Tinkerbell Workflow Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Tinkerbell Stack (runs on management cluster)           │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ tink-    │  │ image-   │  │ action-registry      │  │
│  │ server   │  │ server   │  │ (OCI actions)        │  │
│  │ :42113   │  │ :80      │  │ :5000                │  │
│  └─────┬────┘  └────┬─────┘  └──────────┬───────────┘  │
│        │             │                    │              │
└────────┼─────────────┼────────────────────┼──────────────┘
         │ gRPC        │ HTTP              │ OCI pull
         │             │                    │
    ┌────┼─────────────┼────────────────────┼────┐
    │    ▼             ▼                    ▼    │
    │  ┌────────────────────────────────────┐   │
    │  │  tink-agent (inside HookOS)        │   │
    │  │  - Connects to tink-server:42113   │   │
    │  │  - Pulls actions from registry     │   │
    │  │  - Streams OS image from server    │   │
    │  │  - Reports progress back           │   │
    │  └────────────────────────────────────┘   │
    │                                            │
    │  Target Server (booting from ISO)          │
    └────────────────────────────────────────────┘
```

## Boot Flow (VirtualMedia)

For servers without PXE/DHCP (like remote edge sites):

```
1. ANPA sets Dell OEM boot attributes via Redfish:
   - ServerBoot.1.FirstBootDevice = VCD-DVD
   - VirtualMedia.1.BootOnce = Enabled
   - VirtualMedia.1.Enable = Enabled

2. ANPA inserts ISO via VirtualMedia:
   POST /redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/CD/Actions/VirtualMedia.InsertMedia
   { "Image": "http://<proxy>:7080/iso/<mac>/hook.iso" }

3. ANPA reboots server:
   POST /redfish/v1/Systems/System.Embedded.1/Actions/ComputerSystem.Reset
   { "ResetType": "ForceRestart" }

4. Server UEFI boots from VirtualMedia → loads HookOS ISO
5. HookOS kernel boots with patched args:
   grpc_authority=<proxy>:42113 tink_worker_image=<registry>/tink-worker:latest
   ip=<node_ip>::<gateway>:<netmask>::eth0:off

6. tink-agent starts → connects to tink-server → executes workflow actions
```

### ISO Patching

HookOS ISO contains a 1024-character placeholder in grub.cfg kernel command line.
At serve time, the image-server replaces this placeholder with actual values:

```
TINKERBELL_ISO_PATCH_MAGIC_STRING → actual kernel args
TINK_SERVER_ADDR_PORT → <proxy_ip>:<tink_port>
```

## Network Architecture (Remote Sites)

For sites without direct connectivity to the management cluster:

```
┌──────────────────┐     VPN      ┌──────────────────┐
│  AWS VPC         │◄────────────►│  Remote Site     │
│                  │              │                  │
│  ┌────────────┐  │   OpenVPN   │  ┌────────────┐  │
│  │ Tinkerbell │  │◄───────────►│  │ Server     │  │
│  │ NLB        │  │   tunnel    │  │ (iDRAC +   │  │
│  │ :42113     │  │             │  │  data NIC) │  │
│  │ :80        │  │             │  └────────────┘  │
│  │ :5000      │  │             │                  │
│  └─────┬──────┘  │             └──────────────────┘
│        │         │
│  ┌─────┴──────┐  │
│  │ OpenVPN    │  │  DNAT rules:
│  │ Proxy      │  │  10.0.10.48:42113 → 10.0.2.213:42113
│  │ 10.0.10.48 │  │  10.0.10.48:80    → 10.0.2.157:80
│  └────────────┘  │  10.0.10.48:5000  → 10.0.2.50:5000
│                  │
└──────────────────┘
```

**Key constraint:** The server's data NIC must be on a subnet that can route back to the VPN proxy IP. The ISO is patched with a static IP for the data NIC — this IP must be provided by the site operator.

## Workflow Actions (12-step provisioning)

Typical Tinkerbell workflow for EKS Hybrid Node:

| Step | Action | Purpose |
|------|--------|---------|
| 1 | `stream-image` | Download + write Ubuntu image to disk |
| 2 | `grow-partition` | Expand root partition to fill disk |
| 3 | `install-packages` | Install EKS node agent, containerd |
| 4 | `configure-network` | Write netplan config (static IP) |
| 5 | `configure-dns` | Set resolvers |
| 6 | `configure-ntp` | Sync time (critical for certificates) |
| 7 | `configure-kubelet` | Write kubelet config + certs |
| 8 | `install-ssm-agent` | AWS SSM for remote management |
| 9 | `register-hybrid-node` | Call EKS API to register as hybrid node |
| 10 | `configure-hugepages` | DPDK memory allocation |
| 11 | `configure-cpu-isolation` | CPU pinning for RAN workloads |
| 12 | `reboot` | Boot into installed OS |

## Reconcile Loop Timing

| Activity | Interval |
|----------|----------|
| ProvisioningRequest pass | 30s |
| Node health check | 5 minutes |
| Workflow status poll | 30s (within provisioning phase) |
| Timeout per request | 30 minutes (configurable) |
| Max retries before Failed | 5 |

## Troubleshooting

### Common Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Stuck in Validating | BMC unreachable | Check VPN route to iDRAC IP |
| Stuck in Provisioning | tink-agent can't connect | Wrong data NIC IP in ISO; check `tcpdump port 42113` on proxy |
| Stuck in WaitingForNodes | Node not registering | Check SSM agent logs, verify IAM role trust policy |
| Failed with AI diagnosis | Multiple issues | Read `status.message`, check Tinkerbell workflow events |

### Debugging Commands

```bash
# Check workflow status
kubectl get workflow -n tink-system

# Watch tink-agent logs (if HookOS booted successfully)
# From server console:
journalctl -u tink-agent -f

# Check if packets reach proxy
tcpdump -i eth0 port 42113 -n  # on proxy instance

# Verify ISO is accessible
curl -I http://<proxy>:7080/iso/<mac>/hook.iso

# Check VirtualMedia mount status
curl -sk https://<bmc_ip>/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/CD \
  -u root:<pass> | jq '.Inserted, .Image'
```

## Dell iDRAC Workarounds

The Dell XR8720t has firmware quirks that required workarounds:

| Issue | Workaround |
|-------|-----------|
| Standard Redfish `BootSourceOverride` is read-only | Use Dell OEM attributes: `ServerBoot.1.FirstBootDevice` |
| `VirtualMedia.1.Enable` defaults to Disabled | Enable via `PATCH /redfish/v1/Managers/.../Attributes` |
| `AutoOSLockState` blocks boot changes | Disable before setting boot device |
| No internet access on BMC | All images served via VPN proxy |
