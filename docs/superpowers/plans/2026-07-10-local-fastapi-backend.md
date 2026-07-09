# Local FastAPI Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local FastAPI backend that lets a future frontend create video projects, edit context packets, create render versions, start pipeline render jobs, and poll job status without shelling out to CLI scripts.

**Architecture:** Add a thin API layer under `video_slicer/api/` that reuses `LocalProjectStore`, `ProjectRecord`, `VersionRecord`, `JobRecord`, and the existing `video_slicer.pipeline.run_cli()` orchestration. The API owns request/response schemas and background job scheduling; media processing, script generation, alignment, rendering, quality reporting, and provider calls remain in their existing modules.

**Tech Stack:** Python 3, FastAPI, Pydantic, Uvicorn, standard-library `threading`, `argparse.Namespace`, existing local JSON project store, existing pipeline modules, `unittest`, FastAPI `TestClient`.

**Execution Status:** Implemented and verified locally.

---

## Scope

This plan builds the backend MVP only. It does not build the frontend UI, cloud authentication, payment, remote storage, multi-user permissions, distributed queues, or a public API product. The backend is intended for a local web product where the frontend calls `http://127.0.0.1:8000`.

The first API supports local video paths. Browser file upload can be added after the local project and render API is stable; this keeps the first backend version small and testable.

## File Structure

Create:

- `video_slicer/api/__init__.py`
  - Marks the API package.
- `video_slicer/api/schemas.py`
  - Pydantic request models for project creation, context editing, version creation, and render job creation.
  - Small response helpers that return existing dataclass `.to_dict()` payloads.
- `video_slicer/api/project_service.py`
  - Project and version service functions around `LocalProjectStore`.
  - Converts API settings into `VersionSettings`.
  - Writes per-project context packets to disk for pipeline execution.
- `video_slicer/api/job_runner.py`
  - Creates render job records.
  - Builds an `argparse.Namespace` compatible with `video_slicer.pipeline.run_cli()`.
  - Runs one local render job at a time in a background task.
- `video_slicer/api/app.py`
  - FastAPI app factory and routes.
  - Dependency injection for tests: custom store and custom job runner.
- `scripts/run_api.py`
  - Local development entrypoint for Uvicorn.
- `tests/test_api_app.py`
  - Health and context schema route tests.
- `tests/test_api_projects.py`
  - Project creation, context update, and version creation API tests.
- `tests/test_api_jobs.py`
  - Job creation, runner argument mapping, success/failure status tests.

Modify:

- `requirements.txt`
  - Add FastAPI runtime and test dependencies.
- `video_slicer/project_models.py`
  - Add `context_packet` to `ProjectRecord` so the backend can store the full editable context packet, not only the reduced `UserContext`.
- `video_slicer/pipeline.py`
  - Add `--job-id` parser argument for API-triggered runs.
- `video_slicer/pipeline_records.py`
  - Reuse an existing API-created `JobRecord` when `args.job_id` is provided.
- `docs/README.zh-CN.md`
  - Add API package ownership.
- `docs/code-map.zh-CN.md`
  - Add API module section.
- `docs/development-rules.zh-CN.md`
  - Add API placement and test rules.
- `README.md`
  - Add local API startup command.

Do not modify:

- `llm_providers/`
- `tts_providers/`
- `video_slicer/alignment.py`
- `video_slicer/rendering.py`
- `video_slicer/script_generation.py`
- `video_slicer/quality_report.py`
- `.env`
- `context.example.json`

---

### Task 1: Add FastAPI Skeleton, Health Route, and Context Schema Route

**Files:**
- Modify: `requirements.txt`
- Create: `video_slicer/api/__init__.py`
- Create: `video_slicer/api/schemas.py`
- Create: `video_slicer/api/app.py`
- Create: `scripts/run_api.py`
- Create: `tests/test_api_app.py`

**Interfaces:**
- Consumes:
  - `video_slicer.context_packet.frontend_context_schema() -> dict[str, Any]`
- Produces:
  - `video_slicer.api.app.create_app(project_root: Path | str | None = None, store: LocalProjectStore | None = None, job_runner: Any | None = None) -> FastAPI`
  - `GET /api/health`
  - `GET /api/context/schema`

- [ ] **Step 1: Write failing API skeleton tests**

Create `tests/test_api_app.py`:

```python
import unittest

from fastapi.testclient import TestClient

from video_slicer.api.app import create_app


class ApiAppTest(unittest.TestCase):
    def test_health_route_returns_local_backend_status(self):
        client = TestClient(create_app())

        response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["service"], "video-slicer-local-api")

    def test_context_schema_route_exposes_editable_fields(self):
        client = TestClient(create_app())

        response = client.get("/api/context/schema")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["version"], 1)
        field_keys = [field["key"] for field in body["fields"]]
        self.assertIn("correct_synopsis", field_keys)
        self.assertIn("characters", field_keys)
        self.assertIn("tts_unfriendly_terms", field_keys)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_api_app
```

Expected:

```text
ModuleNotFoundError: No module named 'fastapi'
```

If FastAPI is already installed, the expected failure is:

```text
ModuleNotFoundError: No module named 'video_slicer.api'
```

- [ ] **Step 3: Add API dependencies**

Modify `requirements.txt` so it contains exactly these existing dependencies plus the API additions:

```text
faster-whisper==1.2.1
openai>=1.0.0
requests
dashscope
fastapi
uvicorn
httpx
```

Install dependencies locally:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Expected:

```text
Successfully installed
```

The exact package list printed by pip can differ.

- [ ] **Step 4: Create API package marker**

Create `video_slicer/api/__init__.py`:

```python
"""Local FastAPI backend for the video slicing product."""
```

- [ ] **Step 5: Create initial schema module**

Create `video_slicer/api/schemas.py`:

```python
"""Pydantic schemas for the local API layer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "video-slicer-local-api"


class CreateProjectRequest(BaseModel):
    source_video_path: str = Field(min_length=1)
    source_duration_seconds: float | None = Field(default=None, gt=0)
    user_id: str = "local_user"


class UpdateProjectContextRequest(BaseModel):
    context_packet: dict[str, Any] = Field(default_factory=dict)


class CreateVersionRequest(BaseModel):
    target_duration_seconds: float = Field(gt=0)
    audio_mode: Literal["pure_commentary", "key_original_audio"] = "pure_commentary"
    voice_clone_id: str = ""
    bgm_path: str = ""
    voiceover_speed: float = Field(default=1.0, ge=0.5, le=1.5)
    voiceover_volume: float = Field(default=1.0, ge=0)
    bgm_volume: float = Field(default=0.16, ge=0)
    subtitle_language: Literal["zh", "en", "zh_en"] = "zh"
    aspect_ratio: Literal["original", "vertical_9_16_blur"] = "original"
    variant_goal: str = "manual"
    parent_version_id: str = ""
    generation_group_id: str = ""


class CreateRenderJobRequest(BaseModel):
    tts_mode: Literal["fish", "ocool", "none"] = "fish"
    require_llm: bool = True
    force_script: bool = False
    force_review: bool = False
    force_humanize: bool = False
    force_tts: bool = False
    no_fit_duration: bool = False
```

- [ ] **Step 6: Create app factory and health/schema routes**

Create `video_slicer/api/app.py`:

```python
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
```

- [ ] **Step 7: Create local API runner**

Create `scripts/run_api.py`:

```python
"""Run the local FastAPI backend."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run("video_slicer.api.app:create_app", host=host, port=port, factory=True, reload=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run Task 1 tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_api_app
```

Expected:

```text
Ran 2 tests
OK
```

- [ ] **Step 9: Commit Task 1**

Run:

```powershell
git add requirements.txt video_slicer/api/__init__.py video_slicer/api/schemas.py video_slicer/api/app.py scripts/run_api.py tests/test_api_app.py
git commit -m "feat: add local api skeleton"
```

---

### Task 2: Add Project and Context API

**Files:**
- Modify: `video_slicer/project_models.py`
- Create: `video_slicer/api/project_service.py`
- Modify: `video_slicer/api/app.py`
- Create: `tests/test_api_projects.py`
- Modify: `tests/test_project_store.py`

**Interfaces:**
- Consumes:
  - `LocalProjectStore.create_project()`
  - `LocalProjectStore.save_project()`
  - `LocalProjectStore.get_project()`
  - `LocalProjectStore.list_projects()`
  - `video_slicer.context_packet.normalize_context_packet()`
- Produces:
  - `ProjectRecord.context_packet`
  - `POST /api/projects`
  - `GET /api/projects`
  - `GET /api/projects/{project_id}`
  - `PUT /api/projects/{project_id}/context`

- [ ] **Step 1: Write failing project model persistence test**

Append to `tests/test_project_store.py` inside `LocalProjectStoreTest`:

```python
    def test_project_context_packet_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProjectStore(Path(tmp))
            project = store.create_project("videos/demo.mp4", source_duration_seconds=300.0)
            project.context_packet = {
                "title": "测试项目",
                "correct_synopsis": "主角进入房间，冲突开始。",
                "story_focus": ["压迫感", "人物关系"],
            }
            store.save_project(project)

            reloaded = LocalProjectStore(Path(tmp)).get_project(project.project_id)

            self.assertEqual(reloaded.context_packet["title"], "测试项目")
            self.assertEqual(reloaded.context_packet["story_focus"], ["压迫感", "人物关系"])
```

- [ ] **Step 2: Run the failing project model test**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_project_store.LocalProjectStoreTest.test_project_context_packet_survives_reload
```

Expected:

```text
AttributeError: 'ProjectRecord' object has no attribute 'context_packet'
```

- [ ] **Step 3: Add `context_packet` to `ProjectRecord`**

Modify `video_slicer/project_models.py`.

Add this field to `ProjectRecord` after `user_context`:

```python
    context_packet: dict[str, Any] = field(default_factory=dict)
```

Add this key to `ProjectRecord.to_dict()` after `"user_context": self.user_context.to_dict(),`:

```python
            "context_packet": self.context_packet,
```

Add this argument to `ProjectRecord.from_dict()` after `user_context=UserContext.from_dict(data.get("user_context")),`:

```python
            context_packet=dict(data.get("context_packet", {})),
```

- [ ] **Step 4: Run project store tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_project_store
```

Expected:

```text
OK
```

- [ ] **Step 5: Write failing project API tests**

Create `tests/test_api_projects.py`:

```python
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from video_slicer.api.app import create_app
from video_slicer.project_store import LocalProjectStore


class ApiProjectTest(unittest.TestCase):
    def test_create_list_and_get_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProjectStore(Path(tmp))
            client = TestClient(create_app(store=store))

            created = client.post(
                "/api/projects",
                json={
                    "source_video_path": "videos/input.mp4",
                    "source_duration_seconds": 300.0,
                    "user_id": "local_user",
                },
            )

            self.assertEqual(created.status_code, 200)
            project = created.json()
            self.assertTrue(project["project_id"].startswith("project_"))
            self.assertEqual(project["source_video_path"], "videos/input.mp4")

            listed = client.get("/api/projects")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(len(listed.json()), 1)

            fetched = client.get(f"/api/projects/{project['project_id']}")
            self.assertEqual(fetched.status_code, 200)
            self.assertEqual(fetched.json()["project_id"], project["project_id"])

    def test_update_context_normalizes_narration_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProjectStore(Path(tmp))
            project = store.create_project("videos/input.mp4", source_duration_seconds=300.0)
            client = TestClient(create_app(store=store))

            response = client.put(
                f"/api/projects/{project.project_id}/context",
                json={
                    "context_packet": {
                        "title": "测试项目",
                        "correct_synopsis": "主角走进房间。",
                    }
                },
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["context_packet"]["title"], "测试项目")
            self.assertIn("narration_rules", body["context_packet"])
            self.assertEqual(
                store.get_project(project.project_id).context_packet["correct_synopsis"],
                "主角走进房间。",
            )

    def test_missing_project_returns_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(store=LocalProjectStore(Path(tmp))))

            response = client.get("/api/projects/project_missing")

            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"], "Project not found")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: Run failing project API tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_api_projects
```

Expected:

```text
AssertionError: 404 != 200
```

The health-only app does not have the project routes yet.

- [ ] **Step 7: Create project service**

Create `video_slicer/api/project_service.py`:

```python
"""Service helpers for project, context, and version API routes."""

from __future__ import annotations

import json
from pathlib import Path

from video_slicer.api.schemas import CreateProjectRequest, CreateVersionRequest
from video_slicer.context_packet import normalize_context_packet
from video_slicer.project_models import (
    AspectRatio,
    AudioMode,
    ProjectRecord,
    SubtitleLanguage,
    VersionRecord,
    VersionSettings,
)
from video_slicer.project_store import LocalProjectStore


def create_project(store: LocalProjectStore, request: CreateProjectRequest) -> ProjectRecord:
    return store.create_project(
        source_video_path=request.source_video_path,
        source_duration_seconds=request.source_duration_seconds,
        user_id=request.user_id,
    )


def update_project_context(
    store: LocalProjectStore,
    *,
    project_id: str,
    context_packet: dict,
) -> ProjectRecord:
    project = store.get_project(project_id)
    project.context_packet = normalize_context_packet(context_packet)
    return store.save_project(project)


def version_settings_from_request(request: CreateVersionRequest) -> VersionSettings:
    return VersionSettings(
        target_duration_seconds=request.target_duration_seconds,
        audio_mode=AudioMode(request.audio_mode),
        voice_clone_id=request.voice_clone_id,
        bgm_path=request.bgm_path,
        voiceover_speed=request.voiceover_speed,
        voiceover_volume=request.voiceover_volume,
        bgm_volume=request.bgm_volume,
        subtitle_language=SubtitleLanguage(request.subtitle_language),
        aspect_ratio=AspectRatio(request.aspect_ratio),
    )


def create_version(store: LocalProjectStore, *, project_id: str, request: CreateVersionRequest) -> VersionRecord:
    settings = version_settings_from_request(request)
    return store.create_version(
        project_id=project_id,
        settings=settings,
        parent_version_id=request.parent_version_id,
        generation_group_id=request.generation_group_id,
        variant_goal=request.variant_goal,
    )


def write_project_context_file(store: LocalProjectStore, *, project_id: str, output_dir: Path) -> Path:
    project = store.get_project(project_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "context.json"
    path.write_text(json.dumps(project.context_packet, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
```

- [ ] **Step 8: Add project routes**

Modify `video_slicer/api/app.py`.

Add imports:

```python
from fastapi import FastAPI, HTTPException

from video_slicer.api.project_service import create_project, update_project_context
from video_slicer.api.schemas import (
    CreateProjectRequest,
    HealthResponse,
    UpdateProjectContextRequest,
)
```

Replace the existing `from fastapi import FastAPI` import with the combined FastAPI/HTTPException import.

Inside `create_app()`, before `return app`, add:

```python
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
```

- [ ] **Step 9: Run Task 2 tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_project_store tests.test_api_projects tests.test_api_app
```

Expected:

```text
OK
```

- [ ] **Step 10: Commit Task 2**

Run:

```powershell
git add video_slicer/project_models.py video_slicer/api/project_service.py video_slicer/api/app.py tests/test_project_store.py tests/test_api_projects.py
git commit -m "feat: add project context api"
```

---

### Task 3: Add Version API

**Files:**
- Modify: `video_slicer/api/app.py`
- Modify: `tests/test_api_projects.py`

**Interfaces:**
- Consumes:
  - `video_slicer.api.project_service.create_version()`
  - `LocalProjectStore.list_versions()`
  - `LocalProjectStore.get_version()`
- Produces:
  - `POST /api/projects/{project_id}/versions`
  - `GET /api/projects/{project_id}/versions`
  - `GET /api/projects/{project_id}/versions/{version_id}`

- [ ] **Step 1: Add failing version API tests**

Append to `tests/test_api_projects.py` inside `ApiProjectTest`:

```python
    def test_create_list_and_get_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProjectStore(Path(tmp))
            project = store.create_project("videos/input.mp4", source_duration_seconds=300.0)
            client = TestClient(create_app(store=store))

            created = client.post(
                f"/api/projects/{project.project_id}/versions",
                json={
                    "target_duration_seconds": 90.0,
                    "audio_mode": "pure_commentary",
                    "voice_clone_id": "fish_voice_demo",
                    "bgm_path": "assets/bgm/demo.mp3",
                    "voiceover_speed": 0.92,
                    "voiceover_volume": 1.0,
                    "bgm_volume": 0.18,
                    "subtitle_language": "zh",
                    "aspect_ratio": "original",
                    "variant_goal": "90s_pure_commentary",
                },
            )

            self.assertEqual(created.status_code, 200)
            version = created.json()
            self.assertTrue(version["version_id"].startswith("version_"))
            self.assertEqual(version["settings"]["target_duration_seconds"], 90.0)
            self.assertEqual(version["settings"]["voice_clone_id"], "fish_voice_demo")

            listed = client.get(f"/api/projects/{project.project_id}/versions")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(len(listed.json()), 1)

            fetched = client.get(f"/api/projects/{project.project_id}/versions/{version['version_id']}")
            self.assertEqual(fetched.status_code, 200)
            self.assertEqual(fetched.json()["variant_goal"], "90s_pure_commentary")

    def test_create_version_rejects_duration_not_shorter_than_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProjectStore(Path(tmp))
            project = store.create_project("videos/input.mp4", source_duration_seconds=100.0)
            client = TestClient(create_app(store=store))

            response = client.post(
                f"/api/projects/{project.project_id}/versions",
                json={"target_duration_seconds": 100.0},
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("shorter than source", response.json()["detail"])
```

- [ ] **Step 2: Run failing version API tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_api_projects
```

Expected:

```text
AssertionError: 404 != 200
```

- [ ] **Step 3: Add version route imports**

Modify `video_slicer/api/app.py` imports.

Change:

```python
from video_slicer.api.project_service import create_project, update_project_context
```

To:

```python
from video_slicer.api.project_service import create_project, create_version, update_project_context
```

Add `CreateVersionRequest` to the schemas import:

```python
from video_slicer.api.schemas import (
    CreateProjectRequest,
    CreateVersionRequest,
    HealthResponse,
    UpdateProjectContextRequest,
)
```

- [ ] **Step 4: Add version routes**

Inside `create_app()`, before `return app`, add:

```python
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
```

- [ ] **Step 5: Run Task 3 tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_api_projects tests.test_project_store tests.test_project_models
```

Expected:

```text
OK
```

- [ ] **Step 6: Commit Task 3**

Run:

```powershell
git add video_slicer/api/app.py tests/test_api_projects.py
git commit -m "feat: add version api"
```

---

### Task 4: Add Render Job API and Pipeline Runner

**Files:**
- Modify: `video_slicer/pipeline.py`
- Modify: `video_slicer/pipeline_records.py`
- Modify: `tests/test_pipeline_records.py`
- Create: `video_slicer/api/job_runner.py`
- Modify: `video_slicer/api/app.py`
- Create: `tests/test_api_jobs.py`

**Interfaces:**
- Consumes:
  - `video_slicer.pipeline.build_parser()`
  - `video_slicer.pipeline.run_cli(args: argparse.Namespace) -> None`
  - `LocalProjectStore.create_job()`
  - `LocalProjectStore.update_job_status()`
  - `LocalProjectStore.record_export()`
  - `write_project_context_file()`
- Produces:
  - `--job-id` CLI parser argument
  - Existing job reuse in `begin_pipeline_record_session()`
  - `PipelineJobRunner.create_job()`
  - `PipelineJobRunner.run_job()`
  - `POST /api/projects/{project_id}/versions/{version_id}/render`
  - `GET /api/projects/{project_id}/jobs`
  - `GET /api/projects/{project_id}/jobs/{job_id}`

- [ ] **Step 1: Write failing `--job-id` pipeline record tests**

Append to `tests/test_pipeline_records.py` inside `PipelineRecordsTest`:

```python
    def test_begin_session_reuses_existing_job_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProjectStore(Path(tmp))
            project = store.create_project("videos/input.mp4", source_duration_seconds=300.0, project_id="project_demo")
            version = store.create_version(
                project.project_id,
                settings_from_pipeline_args(make_args()),
                version_id="version_demo",
            )
            job = store.create_job(project.project_id, version.version_id, job_id="job_demo")

            session = begin_pipeline_record_session(
                make_args(
                    record_project=True,
                    project_root=tmp,
                    project_id=project.project_id,
                    version_id=version.version_id,
                    job_id=job.job_id,
                ),
                video_duration=300.0,
            )

            self.assertEqual(session.job_id, "job_demo")
            self.assertEqual(store.get_job(project.project_id, "job_demo").status, JobStatus.RUNNING)
```

Append to `PipelineParserRecordArgsTest`:

```python
    def test_parser_accepts_job_id(self):
        parser = build_parser()
        args = parser.parse_args(["--record-project", "--job-id", "job_demo"])

        self.assertEqual(args.job_id, "job_demo")
```

Update `make_args()` default values by adding:

```python
        "job_id": "",
```

- [ ] **Step 2: Run failing pipeline record tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_pipeline_records
```

Expected:

```text
AttributeError: 'Namespace' object has no attribute 'job_id'
```

or:

```text
unrecognized arguments: --job-id job_demo
```

- [ ] **Step 3: Add parser support for `--job-id`**

Modify `video_slicer/pipeline.py`.

After:

```python
    parser.add_argument("--version-id", default="", help="Existing or desired version id used with --record-project.")
```

Add:

```python
    parser.add_argument("--job-id", default="", help="Existing or desired job id used with --record-project.")
```

- [ ] **Step 4: Reuse existing job in pipeline records**

Modify `video_slicer/pipeline_records.py`.

Inside `begin_pipeline_record_session()`, after:

```python
    version_id = str(getattr(args, "version_id", "") or "")
```

Add:

```python
    job_id = str(getattr(args, "job_id", "") or "")
```

Replace:

```python
    job = store.create_job(
        project_id=project.project_id,
        version_id=version.version_id,
        initial_stage=JobStage.EXTRACT_AUDIO,
    )
```

With:

```python
    if job_id:
        try:
            job = store.get_job(project.project_id, job_id)
        except FileNotFoundError:
            job = store.create_job(
                project_id=project.project_id,
                version_id=version.version_id,
                job_id=job_id,
                initial_stage=JobStage.EXTRACT_AUDIO,
            )
    else:
        job = store.create_job(
            project_id=project.project_id,
            version_id=version.version_id,
            initial_stage=JobStage.EXTRACT_AUDIO,
        )
```

- [ ] **Step 5: Run pipeline record tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_pipeline_records
```

Expected:

```text
OK
```

- [ ] **Step 6: Write failing job runner tests**

Create `tests/test_api_jobs.py`:

```python
import tempfile
import unittest
from pathlib import Path

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

from video_slicer.api.app import create_app
from video_slicer.api.job_runner import PipelineJobRunner
from video_slicer.api.schemas import CreateRenderJobRequest
from video_slicer.project_models import JobStatus, VersionSettings
from video_slicer.project_store import LocalProjectStore


class RecordingRunner:
    def __init__(self):
        self.calls = []

    def run_job(self, *, project_id, version_id, job_id, request):
        self.calls.append((project_id, version_id, job_id, request.tts_mode))


class ApiJobTest(unittest.TestCase):
    def test_create_render_job_schedules_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProjectStore(Path(tmp))
            project = store.create_project("videos/input.mp4", source_duration_seconds=300.0)
            version = store.create_version(project.project_id, VersionSettings(target_duration_seconds=90.0))
            runner = RecordingRunner()
            client = TestClient(create_app(store=store, job_runner=runner))

            response = client.post(
                f"/api/projects/{project.project_id}/versions/{version.version_id}/render",
                json={"tts_mode": "none", "require_llm": False},
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["job_id"].startswith("job_"))
            self.assertEqual(body["status"], "pending")
            self.assertEqual(runner.calls, [(project.project_id, version.version_id, body["job_id"], "none")])

    def test_list_and_get_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProjectStore(Path(tmp))
            project = store.create_project("videos/input.mp4", source_duration_seconds=300.0)
            version = store.create_version(project.project_id, VersionSettings(target_duration_seconds=90.0))
            job = store.create_job(project.project_id, version.version_id)
            client = TestClient(create_app(store=store, job_runner=RecordingRunner()))

            listed = client.get(f"/api/projects/{project.project_id}/jobs")
            fetched = client.get(f"/api/projects/{project.project_id}/jobs/{job.job_id}")

            self.assertEqual(listed.status_code, 200)
            self.assertEqual(listed.json()[0]["job_id"], job.job_id)
            self.assertEqual(fetched.status_code, 200)
            self.assertEqual(fetched.json()["job_id"], job.job_id)

    def test_build_pipeline_args_maps_version_settings_and_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProjectStore(Path(tmp))
            project = store.create_project("videos/input.mp4", source_duration_seconds=300.0, project_id="project_demo")
            project.context_packet = {"title": "测试", "correct_synopsis": "主角进入房间。"}
            store.save_project(project)
            version = store.create_version(
                project.project_id,
                VersionSettings(
                    target_duration_seconds=90.0,
                    voice_clone_id="fish_voice_demo",
                    bgm_path="assets/bgm/demo.mp3",
                    bgm_volume=0.18,
                    voiceover_volume=1.2,
                    voiceover_speed=0.92,
                ),
                version_id="version_demo",
            )
            job = store.create_job(project.project_id, version.version_id, job_id="job_demo")
            runner = PipelineJobRunner(store=store, pipeline_fn=lambda args: None)

            args = runner.build_pipeline_args(
                project_id=project.project_id,
                version_id=version.version_id,
                job_id=job.job_id,
                request=CreateRenderJobRequest(tts_mode="fish", require_llm=True, force_tts=True),
            )

            self.assertEqual(args.input, "videos/input.mp4")
            self.assertEqual(args.project_id, "project_demo")
            self.assertEqual(args.version_id, "version_demo")
            self.assertEqual(args.job_id, "job_demo")
            self.assertEqual(args.target_duration, 90.0)
            self.assertEqual(args.tts_mode, "fish")
            self.assertEqual(args.fish_reference_id, "fish_voice_demo")
            self.assertEqual(args.bgm_audio, "assets/bgm/demo.mp3")
            self.assertEqual(args.bgm_volume, 0.18)
            self.assertEqual(args.voiceover_volume, 1.2)
            self.assertTrue(args.require_llm)
            self.assertTrue(args.force_tts)
            self.assertTrue(Path(args.context).exists())

    def test_runner_marks_failed_when_pipeline_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProjectStore(Path(tmp))
            project = store.create_project("videos/input.mp4", source_duration_seconds=300.0)
            version = store.create_version(project.project_id, VersionSettings(target_duration_seconds=90.0))
            job = store.create_job(project.project_id, version.version_id)

            def boom(args):
                raise RuntimeError("render failed")

            runner = PipelineJobRunner(store=store, pipeline_fn=boom)
            runner.run_job(
                project_id=project.project_id,
                version_id=version.version_id,
                job_id=job.job_id,
                request=CreateRenderJobRequest(tts_mode="none", require_llm=False),
            )

            saved = store.get_job(project.project_id, job.job_id)
            self.assertEqual(saved.status, JobStatus.FAILED)
            self.assertIn("render failed", saved.error_message)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 7: Run failing job tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_api_jobs
```

Expected:

```text
ModuleNotFoundError: No module named 'video_slicer.api.job_runner'
```

- [ ] **Step 8: Create job runner**

Create `video_slicer/api/job_runner.py`:

```python
"""Background pipeline job runner for the local API."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from video_slicer.api.project_service import write_project_context_file
from video_slicer.api.schemas import CreateRenderJobRequest
from video_slicer.pipeline import build_parser, run_cli
from video_slicer.project_models import JobStage, JobStatus
from video_slicer.project_store import LocalProjectStore


class PipelineJobRunner:
    def __init__(
        self,
        *,
        store: LocalProjectStore,
        pipeline_fn: Callable | None = None,
    ) -> None:
        self.store = store
        self.pipeline_fn = pipeline_fn or run_cli
        self._lock = threading.Lock()

    def build_pipeline_args(
        self,
        *,
        project_id: str,
        version_id: str,
        job_id: str,
        request: CreateRenderJobRequest,
    ):
        project = self.store.get_project(project_id)
        version = self.store.get_version(project_id, version_id)
        output_dir = self.store.project_dir(project_id) / "outputs" / job_id
        context_path = write_project_context_file(self.store, project_id=project_id, output_dir=output_dir)
        settings = version.settings

        argv = [
            "--input", project.source_video_path,
            "--output-dir", str(output_dir),
            "--context", str(context_path),
            "--target-duration", str(settings.target_duration_seconds),
            "--tts-mode", request.tts_mode,
            "--duration-tolerance", "3.0",
            "--record-project",
            "--project-root", str(self.store.root),
            "--project-id", project_id,
            "--version-id", version_id,
            "--job-id", job_id,
            "--bgm-volume", str(settings.bgm_volume),
            "--voiceover-volume", str(settings.voiceover_volume),
        ]

        if request.require_llm:
            argv.append("--require-llm")
        else:
            argv.append("--no-llm")
        if request.force_script:
            argv.append("--force-script")
        if request.force_review:
            argv.append("--force-review")
        if request.force_humanize:
            argv.append("--force-humanize")
        if request.force_tts:
            argv.append("--force-tts")
        if request.no_fit_duration:
            argv.append("--no-fit-duration")
        if settings.voice_clone_id and request.tts_mode == "fish":
            argv.extend(["--fish-reference-id", settings.voice_clone_id])
        if settings.voiceover_speed and request.tts_mode == "fish":
            argv.extend(["--fish-tts-speed", str(settings.voiceover_speed)])
        if settings.voice_clone_id and request.tts_mode == "ocool":
            argv.extend(["--ocool-tts-voice", settings.voice_clone_id])
        if settings.voiceover_speed and request.tts_mode == "ocool":
            argv.extend(["--ocool-tts-speed", str(settings.voiceover_speed)])
        if settings.bgm_path:
            argv.extend(["--bgm-audio", settings.bgm_path])

        return build_parser().parse_args(argv)

    def run_job(
        self,
        *,
        project_id: str,
        version_id: str,
        job_id: str,
        request: CreateRenderJobRequest,
    ) -> None:
        if not self._lock.acquire(blocking=False):
            self.store.update_job_status(
                project_id=project_id,
                job_id=job_id,
                status=JobStatus.FAILED,
                stage=JobStage.EXPORT,
                error_message="Another render job is already running",
            )
            return
        try:
            self.store.update_job_status(
                project_id=project_id,
                job_id=job_id,
                status=JobStatus.RUNNING,
                stage=JobStage.EXTRACT_AUDIO,
            )
            args = self.build_pipeline_args(
                project_id=project_id,
                version_id=version_id,
                job_id=job_id,
                request=request,
            )
            self.pipeline_fn(args)
        except BaseException as exc:
            self.store.update_job_status(
                project_id=project_id,
                job_id=job_id,
                status=JobStatus.FAILED,
                stage=JobStage.EXPORT,
                error_message=str(exc),
            )
        finally:
            self._lock.release()
```

- [ ] **Step 9: Add job routes**

Modify `video_slicer/api/app.py`.

Add imports:

```python
from fastapi import BackgroundTasks, FastAPI, HTTPException

from video_slicer.api.job_runner import PipelineJobRunner
from video_slicer.api.schemas import (
    CreateProjectRequest,
    CreateRenderJobRequest,
    CreateVersionRequest,
    HealthResponse,
    UpdateProjectContextRequest,
)
```

Replace:

```python
    app.state.job_runner = job_runner
```

With:

```python
    app.state.job_runner = job_runner or PipelineJobRunner(store=app.state.store)
```

Inside `create_app()`, before `return app`, add:

```python
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
```

- [ ] **Step 10: Run Task 4 tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_pipeline_records tests.test_api_jobs tests.test_api_projects
```

Expected:

```text
OK
```

- [ ] **Step 11: Commit Task 4**

Run:

```powershell
git add video_slicer/pipeline.py video_slicer/pipeline_records.py tests/test_pipeline_records.py video_slicer/api/job_runner.py video_slicer/api/app.py tests/test_api_jobs.py
git commit -m "feat: add local render job api"
```

---

### Task 5: Update Documentation and Run Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/README.zh-CN.md`
- Modify: `docs/code-map.zh-CN.md`
- Modify: `docs/development-rules.zh-CN.md`
- Modify: `docs/superpowers/plans/2026-07-10-local-fastapi-backend.md`

**Interfaces:**
- Consumes:
  - API files from Tasks 1-4.
- Produces:
  - Documentation for local API startup, API ownership, tests, and next frontend boundary.

- [ ] **Step 1: Update README with local API startup**

In `README.md`, add this section after the CLI run examples:

````markdown
## 启动本地 API

后续前端会调用本地 FastAPI 后端。启动方式：

```powershell
.\.venv\Scripts\python.exe -m scripts.run_api
```

默认地址：

```text
http://127.0.0.1:8000
```

第一版 API 负责项目、上下文包、版本、渲染任务和任务状态查询；视频切片仍然复用现有 `video_slicer.pipeline`，不会从 API 层重写剪辑逻辑。
````

- [ ] **Step 2: Update directory overview**

In `docs/README.zh-CN.md`, add this row to the top-level directory table:

```markdown
| `video_slicer/api/` | 本地 FastAPI 后端：项目、上下文、版本、渲染任务和状态查询 | 提交 |
```

Add this row to the core ownership table:

```markdown
| 本地 API 路由、请求 schema、后台渲染任务调度 | `video_slicer/api/` |
```

Add this placement rule:

```markdown
- 新的本地 HTTP 接口、请求/响应 schema、后台任务调度：放到 `video_slicer/api/`。
```

- [ ] **Step 3: Update code map**

In `docs/code-map.zh-CN.md`, add `video_slicer.api` to the quick architecture diagram:

```text
本地 HTTP API
  -> video_slicer.api
    -> 项目 / 上下文 / 版本 / 渲染任务 / 状态查询
```

Add a section before `## 5. 项目/版本/任务模型`:

```markdown
## 5. 本地 API 模块

### `video_slicer/api/app.py`

职责：

- 创建 FastAPI app。
- 暴露健康检查、上下文 schema、项目、版本、渲染任务和任务状态接口。
- 通过依赖注入支持单元测试传入临时 `LocalProjectStore` 和 fake runner。

### `video_slicer/api/schemas.py`

职责：

- 定义 API 请求体。
- 保持前端字段名和 `VersionSettings`、context packet 字段一致。

### `video_slicer/api/project_service.py`

职责：

- 复用 `LocalProjectStore` 创建项目和版本。
- 保存完整 `context_packet`。
- 为 pipeline 渲染写出项目级 `context.json`。

### `video_slicer/api/job_runner.py`

职责：

- 创建和运行后台渲染任务。
- 把 API version settings 映射成 `pipeline.run_cli()` 所需参数。
- 限制本地同一时间只跑一个渲染任务。

对应测试：

- `tests/test_api_app.py`
- `tests/test_api_projects.py`
- `tests/test_api_jobs.py`

后续规则：

- API 层不能重写剪辑、对齐、文案生成、TTS 或 FFmpeg 逻辑。
- API 层只做请求校验、状态记录和调度。
- 如果前端需要新配置，先加到 `VersionSettings` 或 context packet，再由 API 暴露。
```

Then renumber the existing later top-level sections in `docs/code-map.zh-CN.md`: `## 5. 项目/版本/任务模型` becomes `## 6. 项目/版本/任务模型`, and each following numbered `##` heading increases by 1.

- [ ] **Step 4: Update development rules**

In `docs/development-rules.zh-CN.md`, add this placement table row:

```markdown
| 本地 HTTP API、请求 schema、任务调度 | `video_slicer/api/` |
```

Add these test table rows:

```markdown
| `video_slicer/api/app.py` | `tests/test_api_app.py` |
| `video_slicer/api/project_service.py` | `tests/test_api_projects.py` |
| `video_slicer/api/job_runner.py` | `tests/test_api_jobs.py` |
```

Replace the recommended verification command with:

```powershell
python -m unittest tests.test_api_app tests.test_api_projects tests.test_api_jobs tests.test_script_generation tests.test_rendering tests.test_alignment tests.test_pipeline tests.test_project_models tests.test_project_store tests.test_pipeline_records tests.test_quality_report
python -m compileall video_slicer tests scripts
```

- [ ] **Step 5: Mark plan status**

At the top of this file, after the `**Tech Stack:**` line, add:

```markdown
**Execution Status:** Implemented and verified locally.
```

- [ ] **Step 6: Run full unit tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_api_app tests.test_api_projects tests.test_api_jobs tests.test_script_generation tests.test_rendering tests.test_alignment tests.test_pipeline tests.test_project_models tests.test_project_store tests.test_pipeline_records tests.test_quality_report
```

Expected:

```text
OK
```

- [ ] **Step 7: Run compile check**

Run:

```powershell
.\.venv\Scripts\python.exe -m compileall video_slicer tests scripts
```

Expected: exit code 0.

- [ ] **Step 8: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected: exit code 0. LF/CRLF warnings are acceptable on Windows if there are no whitespace error lines.

- [ ] **Step 9: Run video-specific term scan for common code**

Run:

```powershell
rg "刘华强|封彪|征服|孙红雷|买瓜|瓜摊|西瓜|birds|bird" video_slicer llm_providers tts_providers scripts
```

Expected: exit code 1 with no matches.

- [ ] **Step 10: Confirm Git scope**

Run:

```powershell
git status --short
git ls-files outputs videos .env assets\voice_refs assets\bgm projects.local
```

Expected tracked local asset dirs only:

```text
assets/bgm/.gitkeep
assets/voice_refs/.gitkeep
videos/.gitkeep
```

`projects.local` should not appear.

- [ ] **Step 11: Commit Task 5**

Run:

```powershell
git add README.md docs/README.zh-CN.md docs/code-map.zh-CN.md docs/development-rules.zh-CN.md docs/superpowers/plans/2026-07-10-local-fastapi-backend.md
git commit -m "docs: document local api backend"
```

---

## API Contract After This Plan

The backend will expose:

```text
GET  /api/health
GET  /api/context/schema
POST /api/projects
GET  /api/projects
GET  /api/projects/{project_id}
PUT  /api/projects/{project_id}/context
POST /api/projects/{project_id}/versions
GET  /api/projects/{project_id}/versions
GET  /api/projects/{project_id}/versions/{version_id}
POST /api/projects/{project_id}/versions/{version_id}/render
GET  /api/projects/{project_id}/jobs
GET  /api/projects/{project_id}/jobs/{job_id}
```

Example render flow:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_api
```

Create project:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/projects `
  -ContentType "application/json" `
  -Body '{"source_video_path":"videos/input.mp4","source_duration_seconds":300}'
```

Create version:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/projects/project_demo/versions `
  -ContentType "application/json" `
  -Body '{"target_duration_seconds":90,"voice_clone_id":"fish_voice_demo","bgm_path":"assets/bgm/demo.mp3"}'
```

Start render:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/projects/project_demo/versions/version_demo/render `
  -ContentType "application/json" `
  -Body '{"tts_mode":"fish","require_llm":true}'
```

Poll job:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/projects/project_demo/jobs/job_demo
```

## Post-Plan Roadmap

After this local API MVP is implemented and verified, continue in this order:

1. **Script preview/edit API**
   - Split the full render pipeline into “generate script only” and “render edited script” endpoints.
   - Store `generated_script` and `final_script` on `VersionRecord`.

2. **Frontend MVP**
   - Build a local creator workspace that calls this API.
   - First screen: project list, create project, context editor, version settings, render button, job status.

3. **Video upload/import**
   - Add multipart upload only after local path projects are stable.
   - Save uploaded videos under `projects.local/uploads/`.

4. **Job queue hardening**
   - Replace the single-process lock with a persistent local queue if users need multiple pending jobs.

5. **Quality gate controls**
   - Expose `quality_report.json` in the API response.
   - Let users decide which warnings block export.

## Self-Review

**Spec coverage:** This plan covers the next backend step needed before frontend work: local API routes for project, context, version, render job, and job status. It intentionally leaves frontend UI and multipart upload for later because the backend record and job model must stabilize first.

**Placeholder scan:** The plan names exact files, exact routes, exact models, exact test cases, exact commands, expected failures, expected pass conditions, and commit messages. It does not use placeholder tokens or unspecified implementation steps.

**Type consistency:** API models use the same enum values as `AudioMode`, `SubtitleLanguage`, `AspectRatio`, and CLI `tts_mode`. Job records reuse existing `JobStatus` and `JobStage`. The render runner maps `CreateRenderJobRequest` plus `VersionSettings` into `build_parser().parse_args(...)`, then calls `run_cli(args)` directly.
