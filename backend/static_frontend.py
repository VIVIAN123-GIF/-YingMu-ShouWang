"""Serve the production Vue build from FastAPI when it is available."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles


def frontend_directory() -> Path | None:
    configured = os.getenv("YINGMU_FRONTEND_DIR", "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "frontend_dist")
    candidates.append(Path(__file__).resolve().parents[1] / "frontend" / "dist")
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate.resolve()
    return None


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or path.startswith("api/"):
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and not path.startswith("api/"):
            return await super().get_response("index.html", scope)
        return response


def mount_frontend(app: FastAPI) -> Path | None:
    directory = frontend_directory()
    if directory is not None:
        app.mount("/", SPAStaticFiles(directory=directory, html=True), name="frontend")
    return directory
