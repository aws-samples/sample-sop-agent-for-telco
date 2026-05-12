# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ANRA Backend API — FastAPI application wiring + static SPA."""

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).parent))

from routers import alarms, approvals, chat, health, metrics, nodes, sops, timeline, webhooks

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger(__name__)

app = FastAPI(title="ANRA", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Basic Auth middleware — required for public-facing deployments
_AUTH_USER = os.getenv("AUTH_USERNAME", "")
_AUTH_PASS = os.getenv("AUTH_PASSWORD", "")

if _AUTH_USER and _AUTH_PASS:
    import base64
    import secrets
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    class _BasicAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.url.path in ("/health", "/healthz"):
                return await call_next(request)
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Basic "):
                try:
                    decoded = base64.b64decode(auth.split(" ", 1)[1]).decode()
                    u, p = decoded.split(":", 1)
                    if secrets.compare_digest(u, _AUTH_USER) and secrets.compare_digest(p, _AUTH_PASS):
                        return await call_next(request)
                except Exception:
                    pass
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="ANRA"'}, content="Unauthorized")

    app.add_middleware(_BasicAuthMiddleware)
    log.info("Basic Auth enabled (user: %s)", _AUTH_USER)

app.include_router(health.router)
app.include_router(alarms.router)
app.include_router(nodes.router)
app.include_router(metrics.router)
app.include_router(sops.router)
app.include_router(timeline.router)
app.include_router(approvals.router)
app.include_router(webhooks.router)
app.include_router(chat.router)

# ── Serve React Frontend (must be AFTER all API routes) ──
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_static_dir / "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(str(_static_dir / "index.html"))

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_spa(path: str):
        file = _static_dir / path
        if file.exists() and file.is_file():
            return FileResponse(str(file))
        return FileResponse(str(_static_dir / "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
