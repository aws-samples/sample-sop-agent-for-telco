# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ANO Platform API — role-aware FastAPI application factory."""

import base64
import logging
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger(__name__)

# ── HTTP Basic Auth ──
ANRA_USER = os.getenv("ANRA_USER", "admin")
ANRA_PASS = os.getenv("ANRA_PASS", "")  # empty = no auth (TODO: fail-closed)


# ── CORS allowlist ──
# Default: deny all cross-origin requests. The ANRA control plane drives
# kubectl / SSM / Redfish; combining `allow_origins=["*"]` with credentialed
# requests would let any browser tab on any origin replay a cached Basic-auth
# session against the API. Operators set CORS_ALLOW_ORIGINS to a comma-
# separated list of dashboard origins at deploy time. CORS_DEV=1 opens to "*"
# only for local dev — never set in production.
_CORS_DEV_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _parse_cors_origins() -> list[str]:
    cors_dev = os.getenv("CORS_DEV", "").strip().lower()
    if cors_dev in _CORS_DEV_TRUTHY:
        log.warning(
            "CORS_DEV=%s set; allow_origins=['*']. Never use this in production.",
            cors_dev,
        )
        return ["*"]
    if cors_dev:
        log.warning(
            "CORS_DEV=%r not recognized (valid: %s); ignoring",
            cors_dev,
            sorted(_CORS_DEV_TRUTHY),
        )
    raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if not raw:
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]


# Closed allowlist of paths that bypass auth. These are the kubelet
# liveness/readiness probe paths and nothing else — a prefix-match approach
# would let `/health/<anything>` slip through, which combined with the SPA
# catch-all at the bottom of create_app() would serve index.html
# unauthenticated for any URL under /health/. Add new paths here only when a
# real probe contract requires it. Trailing slashes are normalized via
# .rstrip("/") on the request path before the comparison; case-sensitive
# match (kubelet probes use lowercase paths exclusively).
_AUTH_BYPASS_PATHS = frozenset({"/health", "/health/live", "/health/ready"})


def _is_auth_bypass(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    return normalized in _AUTH_BYPASS_PATHS


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not ANRA_PASS:
            return await call_next(request)
        if _is_auth_bypass(request.url.path):
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode()
                user, password = decoded.split(":", 1)
                if secrets.compare_digest(user, ANRA_USER) and secrets.compare_digest(password, ANRA_PASS):
                    return await call_next(request)
            except Exception:  # noqa: BLE001, S110 - any decode/split failure → 401, not 500
                pass
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="ANRA"'},
            content="Unauthorized",
        )


# ── Router registry per role ──
SHARED_ROUTERS = ["health", "nodes", "chat", "approvals", "agents"]

ROLE_ROUTERS = {
    "anra": ["alarms", "metrics", "sops", "timeline", "webhooks"],
    "anda": ["metrics", "sops", "timeline", "webhooks"],
    "anpa": ["timeline"],
}

_ROLE_TITLES = {
    "anra": "ANRA — Autonomous Network Remediation Agent",
    "anda": "ANDA — Autonomous Network Deployment Agent",
    "anpa": "ANPA — Autonomous Network Provisioning Agent",
}


def create_app(role: str = "anra") -> FastAPI:
    """Create role-aware FastAPI application."""
    title = _ROLE_TITLES.get(role, f"ANO Platform ({role})")
    app = FastAPI(title=title, version="0.2.0")
    app.add_middleware(BasicAuthMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_parse_cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Import and register routers. Lazy import: routers are looked up by
    # name from the registry, so a top-level import would either need a
    # static manifest (and lose the role-aware lazy-load fallback below) or
    # eager-load every role's deps.
    import importlib  # noqa: PLC0415

    all_router_names = SHARED_ROUTERS + ROLE_ROUTERS.get(role, [])
    for name in all_router_names:
        try:
            module = importlib.import_module(f"amzn_cse_telco_autonomous_network_agents_app.agent.routers.{name}")
            if hasattr(module, "router"):
                app.include_router(module.router)
                log.debug("Registered router: %s", name)
        except ImportError:
            log.warning("Router module not found: %s", name)

    # Cross-agent routers: all roles expose read-only inventory/provisioning/deployment
    # data since they just query K8s CRs via kubectl (no agent-specific state needed).
    # This allows the ANRA dashboard to show ANPA and ANDA activity.
    for cross_module in ["inventory", "provisioning", "deployments"]:
        try:
            mod = importlib.import_module(f"amzn_cse_telco_autonomous_network_agents_app.agent.routers.{cross_module}")
            if hasattr(mod, "router"):
                app.include_router(mod.router)
                log.debug("Registered cross-agent router: %s", cross_module)
        except ImportError:
            log.debug("Cross-agent router not available: %s", cross_module)

    # Serve React Frontend (only for ANRA — the dashboard agent).
    # Resolve the static dir robustly across image layouts so a change to the
    # runtime/install path can't silently drop the UI: an explicit STATIC_DIR
    # override, then the Docker image's /app/static (where the frontend build is
    # copied), then the in-package location (when bundled into the wheel). The
    # frontend is rebuilt every pipeline run, so once served, UI changes flow
    # through automatically.
    _static_dir = next(
        (
            Path(c)
            for c in (
                os.getenv("STATIC_DIR"),
                "/app/static",
                str(Path(__file__).parent.parent / "static"),
            )
            if c and Path(c).is_dir()
        ),
        None,
    )
    if role == "anra" and _static_dir is not None:
        app.mount("/assets", StaticFiles(directory=str(_static_dir / "assets")), name="assets")

        @app.get("/", include_in_schema=False)
        async def serve_index():
            return FileResponse(str(_static_dir / "index.html"))

        _static_root = _static_dir.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        async def serve_spa(path: str):
            # Reject traversal attempts: resolve the candidate and require it
            # to live under _static_root. Without this guard,
            # `_static_dir / "../../proc/self/environ"` resolves outside
            # the static dir and FileResponse exfiltrates process secrets
            # (IRSA creds, ANRA_PASS, INFLUX_TOKEN).
            try:
                candidate = (_static_dir / path).resolve()
            except (OSError, RuntimeError):
                return FileResponse(str(_static_dir / "index.html"))
            if not candidate.is_relative_to(_static_root) or not candidate.is_file():
                return FileResponse(str(_static_dir / "index.html"))
            return FileResponse(str(candidate))

    log.info("API initialized — role=%s, routers=%s", role, all_router_names)
    return app


# Backward compat: module-level `app` for existing imports
app = create_app(role=os.getenv("AGENT_ROLE", "anra"))
