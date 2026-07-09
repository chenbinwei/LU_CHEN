"""Local JSON storage for project, version, and render-job records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_slicer.project_models import (
    JobRecord,
    JobStage,
    JobStatus,
    ProjectRecord,
    VersionRecord,
    VersionSettings,
    validate_version_settings,
)


DEFAULT_PROJECT_ROOT = Path("projects.local")


class LocalProjectStore:
    def __init__(self, root: Path | str = DEFAULT_PROJECT_ROOT) -> None:
        self.root = Path(root)

    def project_dir(self, project_id: str) -> Path:
        return self.root / "projects" / project_id

    def versions_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "versions"

    def jobs_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "jobs"

    def project_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def version_path(self, project_id: str, version_id: str) -> Path:
        return self.versions_dir(project_id) / f"{version_id}.json"

    def job_path(self, project_id: str, job_id: str) -> Path:
        return self.jobs_dir(project_id) / f"{job_id}.json"

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def create_project(
        self,
        source_video_path: str,
        *,
        source_duration_seconds: float | None = None,
        user_id: str = "local_user",
        project_id: str | None = None,
    ) -> ProjectRecord:
        generated = ProjectRecord()
        project = ProjectRecord(
            user_id=user_id,
            project_id=project_id or generated.project_id,
            source_video_path=source_video_path,
            source_duration_seconds=source_duration_seconds,
        )
        self.save_project(project)
        return project

    def save_project(self, project: ProjectRecord) -> ProjectRecord:
        project.touch()
        self._write_json(self.project_path(project.project_id), project.to_dict())
        return project

    def get_project(self, project_id: str) -> ProjectRecord:
        return ProjectRecord.from_dict(self._read_json(self.project_path(project_id)))

    def list_projects(self) -> list[ProjectRecord]:
        projects_root = self.root / "projects"
        if not projects_root.exists():
            return []
        return [
            ProjectRecord.from_dict(self._read_json(path))
            for path in sorted(projects_root.glob("*/project.json"))
        ]

    def create_version(
        self,
        project_id: str,
        settings: VersionSettings,
        *,
        version_id: str | None = None,
        parent_version_id: str = "",
        generation_group_id: str = "",
        variant_goal: str = "manual",
    ) -> VersionRecord:
        project = self.get_project(project_id)
        validate_version_settings(settings, source_duration_seconds=project.source_duration_seconds)
        generated = VersionRecord(project_id=project_id)
        version = VersionRecord(
            project_id=project_id,
            version_id=version_id or generated.version_id,
            parent_version_id=parent_version_id,
            generation_group_id=generation_group_id,
            variant_goal=variant_goal,
            settings=settings,
        )
        self.save_version(version)
        return version

    def save_version(self, version: VersionRecord) -> VersionRecord:
        self.get_project(version.project_id)
        version.touch()
        self._write_json(self.version_path(version.project_id, version.version_id), version.to_dict())
        return version

    def get_version(self, project_id: str, version_id: str) -> VersionRecord:
        return VersionRecord.from_dict(self._read_json(self.version_path(project_id, version_id)))

    def list_versions(self, project_id: str) -> list[VersionRecord]:
        self.get_project(project_id)
        directory = self.versions_dir(project_id)
        if not directory.exists():
            return []
        return [
            VersionRecord.from_dict(self._read_json(path))
            for path in sorted(directory.glob("*.json"))
        ]

    def create_job(
        self,
        project_id: str,
        version_id: str,
        *,
        job_id: str | None = None,
        initial_stage: JobStage = JobStage.EXTRACT_AUDIO,
    ) -> JobRecord:
        self.get_version(project_id, version_id)
        generated = JobRecord(project_id=project_id, version_id=version_id)
        job = JobRecord(
            project_id=project_id,
            version_id=version_id,
            job_id=job_id or generated.job_id,
            current_stage=initial_stage,
        )
        job.add_history(status=job.status, stage=job.current_stage)
        self.save_job(job)
        return job

    def save_job(self, job: JobRecord) -> JobRecord:
        self.get_version(job.project_id, job.version_id)
        job.touch()
        self._write_json(self.job_path(job.project_id, job.job_id), job.to_dict())
        return job

    def get_job(self, project_id: str, job_id: str) -> JobRecord:
        return JobRecord.from_dict(self._read_json(self.job_path(project_id, job_id)))

    def list_jobs(self, project_id: str, version_id: str | None = None) -> list[JobRecord]:
        self.get_project(project_id)
        directory = self.jobs_dir(project_id)
        if not directory.exists():
            return []
        jobs = [
            JobRecord.from_dict(self._read_json(path))
            for path in sorted(directory.glob("*.json"))
        ]
        if version_id is not None:
            jobs = [job for job in jobs if job.version_id == version_id]
        return jobs

    def update_job_status(
        self,
        *,
        project_id: str,
        job_id: str,
        status: JobStatus,
        stage: JobStage | None = None,
        error_message: str = "",
    ) -> JobRecord:
        job = self.get_job(project_id, job_id)
        job.status = status
        if stage is not None:
            job.current_stage = stage
        job.error_message = error_message
        job.add_history(status=job.status, stage=job.current_stage, error_message=error_message)
        return self.save_job(job)

    def record_export(
        self,
        *,
        project_id: str,
        version_id: str,
        job_id: str,
        export_kind: str,
        export_path: str,
        duration_seconds: float | None = None,
    ) -> None:
        version = self.get_version(project_id, version_id)
        job = self.get_job(project_id, job_id)
        version.export_paths[export_kind] = export_path
        job.export_paths[export_kind] = export_path
        if duration_seconds is not None:
            job.duration_seconds = float(duration_seconds)
        self.save_version(version)
        self.save_job(job)
