"""FastAPI app factory for the local video slicing backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI

from video_slicer.api.schemas import HealthResponse
from video_slicer.context_packet import frontend_context_schema
from video_slicer.project_store import LocalProjectStore


def create_app(
    *,
    project_root: Path | str | None = None,
    store: LocalProjectStore | None = None,
    job_runner: Any | None = None,
) -> FastAPI:
    app = FastAPI(title="Video Slicer Local API", version="0.1.0")
    app.state.store = store or LocalProjectStore(project_root or "projects.local")
    app.state.job_runner = job_runner

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/api/context/schema")
    def get_context_schema() -> dict[str, Any]:
        return frontend_context_schema()

    return app
