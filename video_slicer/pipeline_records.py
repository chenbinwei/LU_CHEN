"""Optional project/version/job recording for the CLI pipeline."""

from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path

from video_slicer.project_models import (
    AspectRatio,
    AudioMode,
    JobStage,
    JobStatus,
    SubtitleLanguage,
    VersionSettings,
)
from video_slicer.project_store import LocalProjectStore


def settings_from_pipeline_args(args: Namespace) -> VersionSettings:
    if getattr(args, "tts_mode", "") == "fish":
        voice_clone_id = str(getattr(args, "fish_reference_id", "") or "")
        voiceover_speed = float(getattr(args, "fish_tts_speed", 1.0))
    elif getattr(args, "tts_mode", "") == "ocool":
        voice_clone_id = str(getattr(args, "ocool_tts_voice", "") or "")
        voiceover_speed = float(getattr(args, "ocool_tts_speed", 1.0))
    else:
        voice_clone_id = ""
        voiceover_speed = 1.0

    return VersionSettings(
        target_duration_seconds=float(getattr(args, "target_duration", 120.0)),
        audio_mode=AudioMode.PURE_COMMENTARY,
        voice_clone_id=voice_clone_id,
        bgm_path=str(getattr(args, "bgm_audio", "") or ""),
        voiceover_speed=voiceover_speed,
        voiceover_volume=float(getattr(args, "voiceover_volume", 1.0)),
        bgm_volume=float(getattr(args, "bgm_volume", 0.16)),
        subtitle_language=SubtitleLanguage.ZH,
        aspect_ratio=AspectRatio.ORIGINAL,
    )


@dataclass
class PipelineRecordSession:
    enabled: bool
    store: LocalProjectStore | None = None
    project_id: str = ""
    version_id: str = ""
    job_id: str = ""

    @classmethod
    def disabled(cls) -> "PipelineRecordSession":
        return cls(enabled=False)

    def mark_success(self, *, final_video_path: str, duration_seconds: float | None) -> None:
        if not self.enabled or self.store is None:
            return
        self.store.record_export(
            project_id=self.project_id,
            version_id=self.version_id,
            job_id=self.job_id,
            export_kind="final_video",
            export_path=final_video_path,
            duration_seconds=duration_seconds,
        )
        self.store.update_job_status(
            project_id=self.project_id,
            job_id=self.job_id,
            status=JobStatus.DONE,
            stage=JobStage.EXPORT,
        )

    def mark_failed(self, exc: BaseException) -> None:
        if not self.enabled or self.store is None:
            return
        self.store.update_job_status(
            project_id=self.project_id,
            job_id=self.job_id,
            status=JobStatus.FAILED,
            stage=JobStage.EXPORT,
            error_message=str(exc),
        )


def begin_pipeline_record_session(args: Namespace, *, video_duration: float) -> PipelineRecordSession:
    if not getattr(args, "record_project", False):
        return PipelineRecordSession.disabled()

    store = LocalProjectStore(Path(getattr(args, "project_root", "") or "projects.local"))
    project_id = str(getattr(args, "project_id", "") or "")
    version_id = str(getattr(args, "version_id", "") or "")

    if project_id:
        try:
            project = store.get_project(project_id)
        except FileNotFoundError:
            project = store.create_project(
                source_video_path=str(getattr(args, "input", "")),
                source_duration_seconds=video_duration,
                project_id=project_id,
            )
    else:
        project = store.create_project(
            source_video_path=str(getattr(args, "input", "")),
            source_duration_seconds=video_duration,
        )

    settings = settings_from_pipeline_args(args)
    if version_id:
        try:
            version = store.get_version(project.project_id, version_id)
        except FileNotFoundError:
            version = store.create_version(
                project_id=project.project_id,
                version_id=version_id,
                settings=settings,
            )
    else:
        version = store.create_version(project_id=project.project_id, settings=settings)

    job = store.create_job(
        project_id=project.project_id,
        version_id=version.version_id,
        initial_stage=JobStage.EXTRACT_AUDIO,
    )
    store.update_job_status(
        project_id=project.project_id,
        job_id=job.job_id,
        status=JobStatus.RUNNING,
        stage=JobStage.EXTRACT_AUDIO,
    )

    return PipelineRecordSession(
        enabled=True,
        store=store,
        project_id=project.project_id,
        version_id=version.version_id,
        job_id=job.job_id,
    )
