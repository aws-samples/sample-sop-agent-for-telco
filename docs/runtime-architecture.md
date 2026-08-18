# Runtime Architecture

> How the ANO platform starts, loads config, resolves models, and runs.

## Boot Sequence

```
┌─────────────────────────────────────────────────────────────────────────┐
│  main()                                                                  │
│                                                                          │
│  1. Parse environment:                                                   │
│     AGENT_ROLE (anra|anda|anpa) → PORT (8080) → LOG_LEVEL (info)        │
│                                                                          │
│  2. _validate_config():                                                  │
│     ┌────────────────────────────────────────────────────────────────┐   │
│     │  load_config()           ← find + parse site descriptor YAML   │   │
│     │  validate_or_die()       ← schema check (role-specific)        │   │
│     │  set_config()            ← store in thread-safe ConfigStore    │   │
│     │  _check_aws_credentials()← non-fatal: verify Bedrock access    │   │
│     │  _check_dependencies()   ← non-fatal: probe external services  │   │
│     │  ConfigWatcher.start()   ← begin hot-reload polling            │   │
│     └────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  3. Thread(run_background).start()  ← agent's autonomous work           │
│                                                                          │
│  4. run_api()                       ← blocks forever (uvicorn :8080)     │
└─────────────────────────────────────────────────────────────────────────┘
```

## Config Loading Priority

The system searches for the site descriptor YAML in order:

| Priority | Source |
|----------|--------|
| 1 | Explicit path argument |
| 2 | `AGENT_CONFIG` env var |
| 3 | `ANRA_CONFIG` env var (legacy) |
| 4 | `./agent-config.yaml` |
| 5 | `/app/config/agent-config.yaml` (K8s ConfigMap mount) |
| 6 | `/app/anra-config.yaml` (legacy) |

## Config Store (`core/config_store.py`)

Thread-safe singleton for runtime config access:

```python
from agent.core.config_store import get_config

cfg = get_config()  # Returns current SiteConfig or None
cfg.monitoring.influxdb_url  # Access nested fields
```

**Rules:**
- Call `get_config()` fresh each time — don't cache the reference
- Returns `None` before `set_config()` is called (shouldn't happen after boot)
- Protected by `RLock` — safe from any thread

## Config Watcher (`core/config_watcher.py`)

Watches for config file changes and hot-reloads without pod restart:

```
┌─────────────────────────────────────────────────────┐
│  ConfigWatcher (daemon thread)                       │
│                                                      │
│  Every 1s: stat() config file                        │
│    └─ mtime changed?                                 │
│         └─ YES: wait 2s (debounce K8s symlink swap)  │
│              └─ load_config()                         │
│                  └─ validate(new_cfg, role)           │
│                      ├─ PASS: set_config(new_cfg)    │
│                      │        invalidate_cache()     │
│                      └─ FAIL: log warning, keep old  │
└─────────────────────────────────────────────────────┘
```

**Why polling instead of inotify?**
Kubernetes ConfigMap updates use atomic symlink swaps on the parent directory. `inotify` misses these because it watches the file, not the symlink target. Polling `stat()` reliably catches the new mtime.

**Why 2s debounce?**
K8s often does multiple rapid symlink swaps during a ConfigMap update. The debounce coalesces these into a single reload.

## Model Resolver (`core/model_resolver.py`)

Resolves a logical tier name to a concrete Bedrock model ID:

```python
from agent.core.model_resolver import get_model

model_id = get_model("fast")   # → "us.anthropic.claude-haiku-4-5-20250601-v1:0"
model_id = get_model("smart")  # → "us.anthropic.claude-sonnet-4-20250514-v1:0"
```

### Resolution Priority

| Priority | Source | Example |
|----------|--------|---------|
| 1 (highest) | `BEDROCK_MODEL_ID` env | `us.anthropic.claude-sonnet-4-20250514-v1:0` |
| 2 | `config.bedrock_model_override` | Same format |
| 3 | `config.bedrock_model_tier` | `"fast"` or `"smart"` |
| 4 | `BEDROCK_MODEL_TIER` env | `"smart"` |
| 5 (lowest) | Caller's `tier` arg | Default `"fast"` |

### Tier Definitions

| Tier | Model Class | Preference Order |
|------|-------------|-----------------|
| `fast` | Haiku (tool use, fast responses) | claude-haiku-4-5 → claude-3-5-haiku → claude-3-haiku |
| `smart` | Sonnet (complex reasoning) | claude-sonnet-4-6 → claude-sonnet-4-5 → claude-sonnet-4 |

**How it works:**
1. Calls `bedrock.list_inference_profiles()` to discover which models are ACTIVE in the account/region
2. Matches against the preference list for the requested tier
3. Returns the first available match
4. Results cached per-tier until `invalidate_cache()` is called (on config reload)

## Startup Dependency Checks

Non-fatal connectivity probes at boot — agent starts regardless:

| Role | What's Checked | Impact if Unreachable |
|------|---------------|----------------------|
| All | `kubectl cluster-info` | All operations fail |
| `anra` | InfluxDB `/health` | Metric monitoring disabled |
| `anra` | Alertmanager `/-/healthy` | Prometheus alerts disabled |
| `anda` | ArgoCD `/healthz` | GitOps deployments disabled |
| `anpa` | `kubectl get ns <tink_ns>` | Provisioning workflows fail |

Plus AWS credential check (all roles):
- Attempts `bedrock.list_inference_profiles(maxResults=1)`
- Warns if no IRSA configured or credentials expired

## Background Loops

Each role has an autonomous background loop — the agent's "real job":

### ANRA: `monitor.run_loop()`
```
while True:
  evaluate_dynamic_anomalies()    ← InfluxDB ML-style detection
  evaluate_thresholds()           ← Static alarm rules from config
  evaluate_ran_thresholds()       ← srsRAN-specific KPIs
  evaluate_os_thresholds()        ← Host CPU/memory/disk
  poll_cloudwatch_k8s_events()    ← K8s cluster events
  poll_k8s_pod_health()           ← CrashLoopBackOff detection
  poll_redfish_sel()              ← BMC hardware faults
  fetch_alertmanager_alerts()     ← Prometheus alerts

  For each alert:
    resolve_sop(alert)            ← Match to SOP template
    execute_sop(sop, alert)       ← Run with Bedrock agent

  sleep(monitoring_interval)      ← Default 30s
```

### ANDA: `orchestrator.run_orchestrator()`
```
_check_and_bootstrap_infrastructure()  ← one-time: ensure platform components
while True:
  list DeploymentPlan CRDs (phase=Pending)
  for each plan:
    process_deployment_plan(plan)
      _resolve_nf_order(nfs)            ← 3GPP dependency sort
      for each nf:
        if SOP_BRIDGE_ENABLED:
          SOPBridge.execute(nf, plan)   ← classifies tier, routes execution
        else:
          preflight → drain → deploy → wait_rollout → postdeploy
  _urgent_wake.wait(timeout=30s)       ← wakes instantly on POST /api/anda/wake
  _urgent_wake.clear()
```

See [deployment-orchestration.md](./deployment-orchestration.md#sop-bridge--intelligent-execution-routing)
for the 3-tier execution model (FAST/SMART/EMERGENCY) and SOP Bridge details.

#### SOP Bridge Components

| Module | Purpose |
|--------|---------|
| `agents/anda/sop_bridge.py` | Complexity classifier, SOP resolver, tier routing, tool merging |
| `agents/anda/progress_hook.py` | CR status patches + in-memory activity feed for WebUI |
| `routers/deployments.py` | `POST /api/anda/wake` endpoint (sets `threading.Event`) |

### ANPA: `reconciler.run_reconciler()`
```
while True:
  list ProvisioningRequest CRDs
  for each request:
    drive state machine:
      Pending → Validating → Provisioning → WaitingForNodes → Ready

  every 5 min:
    health_check_existing_nodes()  ← verify registered nodes still healthy

  sleep(30s)
```

## API Layer (`api.py`)

FastAPI application factory — `create_app(role)`:

### Router Registration

| Router | Roles | Purpose |
|--------|-------|---------|
| `health` | All | `/health`, `/health/live`, `/health/ready` |
| `nodes` | All | Node inventory + status |
| `chat` | All | Bedrock chat interface |
| `approvals` | All | Human-in-the-loop approval queue |
| `agents` | All | Agent status + activity feed |
| `inventory` | All | Cross-agent: read ANPA inventory CRs |
| `provisioning` | All | Cross-agent: read ProvisioningRequest CRs |
| `deployments` | All | Cross-agent: read DeploymentPlan CRs + `POST /api/anda/wake` |
| `alarms` | anra | Active alarms + history |
| `metrics` | anra, anda | InfluxDB query proxy |
| `sops` | anra, anda | SOP listing + execution status |
| `timeline` | All | Activity timeline feed |
| `webhooks` | anra, anda | Redfish + Alertmanager webhook receivers |

### Security

| Feature | Behavior |
|---------|----------|
| HTTP Basic Auth | Enabled when `ANRA_PASS` env set |
| Auth bypass | `/health/*` only (kubelet probes) |
| CORS | Deny all by default; set `CORS_ALLOW_ORIGINS` |
| Static files | ANRA only serves React SPA from `/static/` |

## Crash Recovery

The background loop runs as a daemon thread. If it throws an unhandled exception:

```python
except Exception:
    log.exception("Background loop crashed for role=%s; exiting to trigger pod restart", role)
    os._exit(1)
```

**Why `os._exit(1)` instead of raising?**
A daemon thread crash is invisible to the main thread (uvicorn). Without this, `/health` would keep returning 200 while the agent is completely dead. The hard exit triggers a pod restart via Kubernetes.

## Extension Points

### Adding a new agent role
1. Add to `_VALID_ROLES` set in `entrypoint.py`
2. Add branch in `run_background()`
3. Add dependency checks in `_check_dependencies()`
4. Add validation rules in `config.validate()`

### Adding a new API router
1. Create `agent/routers/<name>.py` with `router = APIRouter(...)`
2. Add name to `SHARED_ROUTERS` or role-specific list in `ROLE_ROUTERS`

### Adding a new config field
1. Add to `SiteConfig` dataclass in `config.py`
2. Add validation in `validate()` if required for specific roles
3. Access via `get_config().<field>` anywhere in the codebase
