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
