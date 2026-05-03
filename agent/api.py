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
