"""FastAPI app factory for the local video slicing backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from video_slicer.api.job_runner import PipelineJobRunner
from video_slicer.api.project_service import create_project, create_version, update_project_context
from video_slicer.api.schemas import (
    CreateProjectRequest,
    CreateRenderJobRequest,
    CreateVersionRequest,
    HealthResponse,
    UpdateProjectContextRequest,
)
from video_slicer.context_packet import frontend_context_schema
from video_slicer.project_store import LocalProjectStore


def default_frontend_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend"


def create_app(
    *,
    project_root: Path | str | None = None,
    store: LocalProjectStore | None = None,
    job_runner: Any | None = None,
    frontend_dir: Path | str | None = None,
) -> FastAPI:
    app = FastAPI(title="Video Slicer Local API", version="0.1.0")
    app.state.store = store or LocalProjectStore(project_root or "projects.local")
    app.state.job_runner = job_runner or PipelineJobRunner(store=app.state.store)

    static_dir = Path(frontend_dir) if frontend_dir is not None else default_frontend_dir()
    if static_dir.exists():
        app.mount("/assets", StaticFiles(directory=static_dir), name="assets")

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def frontend_index() -> str:
            return (static_dir / "index.html").read_text(encoding="utf-8")

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/api/context/schema")
    def get_context_schema() -> dict[str, Any]:
        return frontend_context_schema()

    @app.post("/api/projects")
    def post_project(request: CreateProjectRequest) -> dict[str, Any]:
        return create_project(app.state.store, request).to_dict()

    @app.get("/api/projects")
    def list_projects() -> list[dict[str, Any]]:
        return [project.to_dict() for project in app.state.store.list_projects()]

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        try:
            return app.state.store.get_project(project_id).to_dict()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc

    @app.put("/api/projects/{project_id}/context")
    def put_project_context(project_id: str, request: UpdateProjectContextRequest) -> dict[str, Any]:
        try:
            return update_project_context(
                app.state.store,
                project_id=project_id,
                context_packet=request.context_packet,
            ).to_dict()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc

    @app.post("/api/projects/{project_id}/versions")
    def post_version(project_id: str, request: CreateVersionRequest) -> dict[str, Any]:
        try:
            return create_version(app.state.store, project_id=project_id, request=request).to_dict()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/versions")
    def list_versions(project_id: str) -> list[dict[str, Any]]:
        try:
            return [version.to_dict() for version in app.state.store.list_versions(project_id)]
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc

    @app.get("/api/projects/{project_id}/versions/{version_id}")
    def get_version(project_id: str, version_id: str) -> dict[str, Any]:
        try:
            return app.state.store.get_version(project_id, version_id).to_dict()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Version not found") from exc

    @app.post("/api/projects/{project_id}/versions/{version_id}/render")
    def post_render_job(
        project_id: str,
        version_id: str,
        request: CreateRenderJobRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        try:
            job = app.state.store.create_job(project_id, version_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Version not found") from exc
        background_tasks.add_task(
            app.state.job_runner.run_job,
            project_id=project_id,
            version_id=version_id,
            job_id=job.job_id,
            request=request,
        )
        return job.to_dict()

    @app.get("/api/projects/{project_id}/jobs")
    def list_jobs(project_id: str, version_id: str | None = None) -> list[dict[str, Any]]:
        try:
            return [job.to_dict() for job in app.state.store.list_jobs(project_id, version_id=version_id)]
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc

    @app.get("/api/projects/{project_id}/jobs/{job_id}")
    def get_job(project_id: str, job_id: str) -> dict[str, Any]:
        try:
            return app.state.store.get_job(project_id, job_id).to_dict()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    return app
