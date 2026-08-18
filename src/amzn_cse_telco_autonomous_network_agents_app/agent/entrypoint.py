# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ANO Platform entrypoint — starts the appropriate agent based on AGENT_ROLE."""

import logging
import os
import sys
import threading

from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import AgentRole

# Mirrors uvicorn.config.LOGGING_CONFIG keys.
_VALID_LOG_LEVELS = frozenset({"critical", "error", "warning", "info", "debug", "trace"})
_DEFAULT_LOG_LEVEL = "info"
# Valid roles come from the AgentRole enum (single source of truth).
_VALID_ROLES = AgentRole.values()
_MIN_PORT = 1
_MAX_PORT = 65535

log = logging.getLogger("entrypoint")


def _parse_port(raw: str) -> int:
    try:
        port = int(raw.strip())
    except ValueError as exc:
        msg = f"PORT must be an integer between {_MIN_PORT} and {_MAX_PORT}, got {raw!r}"
        raise SystemExit(msg) from exc
    if not _MIN_PORT <= port <= _MAX_PORT:
        msg = f"PORT must be between {_MIN_PORT} and {_MAX_PORT}, got {port}"
        raise SystemExit(msg)
    return port


def _parse_log_level(raw: str) -> str:
    normalized = raw.strip().lower()
    if normalized not in _VALID_LOG_LEVELS:
        # Stderr write rather than logging.warning: this runs before uvicorn
        # configures logging, so logging.warning would fall through to the
        # lastResort handler with no formatting and bypass the user's LOG_LEVEL.
        print(  # noqa: T201 - intentional pre-logging stderr write
            f"LOG_LEVEL={raw!r} not recognized (valid: {sorted(_VALID_LOG_LEVELS)}); falling back to {_DEFAULT_LOG_LEVEL}",
            file=sys.stderr,
        )
        return _DEFAULT_LOG_LEVEL
    return normalized


def _parse_role(raw: str) -> str:
    normalized = raw.strip().lower()
    if normalized not in _VALID_ROLES:
        msg = f"AGENT_ROLE must be one of {sorted(_VALID_ROLES)}, got {raw!r}"
        raise SystemExit(msg)
    return normalized


def _check_dependencies(role: str, cfg) -> None:
    """Non-fatal connectivity checks for external dependencies at startup."""
    import subprocess  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    checks: list[tuple[str, str, str]] = []  # (name, url_or_cmd, impact)

    if role == "anra":
        if cfg.influxdb_url:
            checks.append(("InfluxDB", f"{cfg.influxdb_url}/health", "metric monitoring disabled"))
        if cfg.alertmanager_url:
            checks.append(
                (
                    "Alertmanager",
                    f"{cfg.alertmanager_url}/-/healthy",
                    "Prometheus alerts disabled",
                )
            )
    elif role == "anpa":
        checks.append(
            (
                "Tinkerbell namespace",
                f"kubectl get ns {cfg.tinkerbell_namespace}",
                "provisioning workflows will fail",
            )
        )
    elif role == "anda":
        if cfg.argocd_url:
            checks.append(("ArgoCD", f"{cfg.argocd_url}/healthz", "GitOps deployments disabled"))

    # kubectl API check (all agents)
    checks.append(("Kubernetes API", "kubectl cluster-info", "all agent operations will fail"))

    log.info("Dependency check:")
    for name, endpoint, impact in checks:
        try:
            if endpoint.startswith("kubectl"):
                result = subprocess.run(endpoint.split(), capture_output=True, timeout=5)
                ok = result.returncode == 0
            else:
                resp = urllib.request.urlopen(endpoint, timeout=5)  # nosec B310 — endpoints are http:// from validated config
                ok = resp.status == 200
            if ok:
                log.info("  ✓ %s reachable", name)
            else:
                log.warning("  ✗ %s returned non-200 — %s", name, impact)
        except Exception as e:
            log.warning("  ✗ %s unreachable: %s — %s", name, e, impact)


def _check_aws_credentials(cfg) -> None:
    """Non-fatal check: warn if AWS/Bedrock credentials are unavailable."""
    try:
        import boto3  # type: ignore[import-untyped]  # noqa: PLC0415

        session = boto3.Session()
        creds = session.get_credentials()
        if creds is None:
            log.warning(
                "No AWS credentials detected — Bedrock calls will fail. "
                "Ensure IRSA is configured: set serviceAccount.annotations."
                "'eks.amazonaws.com/role-arn' in Helm values, or add "
                "aws.bedrockRoleArn to your site descriptor."
            )
            return
        region = cfg.bedrock_region or os.getenv("BEDROCK_REGION", "us-west-2")
        client = boto3.client("bedrock", region_name=region)
        client.list_inference_profiles(maxResults=1)
        log.info("AWS Bedrock credentials verified (%s)", region)
    except ImportError:
        log.debug("boto3 not available — skipping credential check")
    except Exception as e:
        log.warning(
            "AWS credential check failed: %s — Bedrock features will be unavailable. Ensure IRSA is configured for this service account.",
            e,
        )


def _validate_config(role: str) -> None:
    """Load, validate, store config and start the hot-reload watcher."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.config import (  # noqa: PLC0415
        load_config,
        validate_or_die,
    )
    from amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store import (  # noqa: PLC0415
        set_config,
    )
    from amzn_cse_telco_autonomous_network_agents_app.agent.core.config_watcher import (  # noqa: PLC0415
        ConfigWatcher,
    )
    from amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver import (  # noqa: PLC0415
        invalidate_cache,
    )

    cfg = load_config()
    validate_or_die(cfg, role=role)
    set_config(cfg)
    log.info("Config validated successfully for role=%s", role)

    # Import any configured extension plugins so their @register_* decorators
    # run before the background loop / API assemble tools and adapters. Loaded
    # once at startup; a listed module that fails to import is fatal (the pod
    # CrashLoops with the offending module named, rather than starting
    # half-configured). Empty plugins list is a no-op.
    from amzn_cse_telco_autonomous_network_agents_app.agent.framework.plugin_loader import (  # noqa: PLC0415
        load_plugins,
    )

    load_plugins(cfg.plugins)

    _check_aws_credentials(cfg)
    _check_dependencies(role, cfg)

    # Determine the config file path for the watcher
    config_path = os.getenv("AGENT_CONFIG", "") or os.getenv("ANRA_CONFIG", "")
    if not config_path:
        # Try default paths
        from pathlib import Path  # noqa: PLC0415

        for candidate in [
            "agent-config.yaml",
            "/app/config/agent-config.yaml",
            "/app/anra-config.yaml",
        ]:
            if Path(candidate).exists():
                config_path = candidate
                break

    if config_path:

        def _on_reload(new_cfg):
            set_config(new_cfg)
            invalidate_cache()
            log.info("Config hot-reloaded and model cache invalidated")

        watcher = ConfigWatcher(path=config_path, role=role, on_reload=_on_reload)
        watcher.start()


def run_api(role: str, port: int, log_level: str) -> None:
    # Lazy imports: uvicorn + agent.api are only needed when the entrypoint
    # actually starts the API server. Top-level import would force the agent
    # subtree to load on every entrypoint inspection (e.g. tests that only
    # exercise _parse_*), and api.py's create_app() pulls in the full router
    # graph including bedrock/strands.
    import uvicorn  # noqa: PLC0415

    from amzn_cse_telco_autonomous_network_agents_app.agent.api import (
        create_app,  # noqa: PLC0415
    )

    app = create_app(role=role)
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 - container service intentionally binds all interfaces
        port=port,
        log_level=log_level,
    )


def run_background(role: str) -> None:
    """Start the role-specific background loop.

    Crashes here are unrecoverable: the monitor / orchestrator / reconciler is
    the agent's actual job. Without this trap a daemon-thread crash would leave
    /health returning 200 while the agent is dead — k8s sees a healthy pod and
    customers see nothing happening. Force pod restart on any exception.
    """
    # Lazy imports per role: top-level imports would force every role's deps
    # (monitor, orchestrator, reconciler) to load on every boot regardless of
    # AGENT_ROLE. Keeping each behind its branch isolates failure modes.
    try:
        if role == "anra":
            os.environ.setdefault("REDFISH_WEBHOOK_PORT", "8081")
            from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import (
                run_loop,
            )  # noqa: PLC0415

            log.info("Starting ANRA monitor loop")
            run_loop()
        elif role == "anda":
            log.info("Starting ANDA deployment orchestrator")
            from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import (  # noqa: PLC0415
                run_orchestrator,
            )

            run_orchestrator()
        elif role == "anpa":
            log.info("Starting ANPA provisioning reconciler")
            from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.reconciler import (  # noqa: PLC0415
                run_reconciler,
            )

            run_reconciler()
    except Exception:
        log.exception("Background loop crashed for role=%s; exiting to trigger pod restart", role)
        os._exit(1)


def main() -> None:
    role = _parse_role(os.getenv("AGENT_ROLE", "anra"))
    port = _parse_port(os.getenv("PORT", "8080"))
    log_level = _parse_log_level(os.getenv("LOG_LEVEL", _DEFAULT_LOG_LEVEL))

    logging.basicConfig(
        level=log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    log.info("Starting ANO Platform — role=%s, port=%d", role, port)

    _validate_config(role)

    bg_thread = threading.Thread(target=run_background, args=(role,), daemon=True)
    bg_thread.start()
    run_api(role=role, port=port, log_level=log_level)


if __name__ == "__main__":
    main()
