# 项目版本任务数据结构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立项目、版本、任务三层本地数据结构，让后续 pipeline、FastAPI 和前端都能围绕同一套记录工作。

**Architecture:** 新增纯数据模型模块和本地 JSON 存储模块，先不改现有 `video_slicer.pipeline`。模型层只负责结构、枚举、序列化和校验；存储层只负责读写本地文件。

**Tech Stack:** Python 3.11 标准库、`dataclasses`、`enum`、`json`、`unittest`、本地 JSON 文件。

---

## 范围

本计划只实现“项目 / 版本 / 任务数据结构”。

包括：

- 项目记录：一个原视频素材。
- 版本记录：同一个素材的一套成片方案。
- 任务记录：一次生成或渲染动作。
- 用户补充信息结构。
- 版本参数结构。
- 隐私和数据合规预留字段。
- 本地 JSON 存储。
- 单元测试。
- README 中的使用说明。

不包括：

- 修改现有剪辑 pipeline。
- 前端。
- FastAPI。
- 文案生成、TTS、字幕、画幅处理。
- 登录、支付、订阅额度。

## 文件结构

新增：

- `video_slicer/project_models.py`
  - 数据模型、枚举、序列化、反序列化、基础校验。

- `video_slicer/project_store.py`
  - 本地 JSON 存储。
  - 默认目录：`projects.local/`。

- `tests/test_project_models.py`
  - 模型测试。

- `tests/test_project_store.py`
  - 存储测试。

修改：

- `.gitignore`
  - 忽略 `projects.local/`。

- `README.md`
  - 补充项目、版本、任务说明。

暂不修改：

- `1.py`
- `video_slicer/pipeline.py`
- `scripts/run_pipeline.py`

## 隐私和数据合规预留

订阅制商业产品会处理用户账号、上传视频、原始音频、转写字幕、生成文案、TTS 音频、成片以及声音克隆相关信息。第一阶段不做完整合规系统，但数据模型需要预留后续能力。

本计划在项目层预留这些字段：

- `user_id`：未来账号系统的用户归属。本地模式先使用 `local_user`。
- `data_region`：未来云端部署时的数据区域。本地模式先使用 `local`。
- `privacy_flags`：标记素材是否涉及声音克隆、人物音频、敏感内容等。
- `retention_until`：未来自动清理素材和中间产物的保留期限。
- `deleted_at`：软删除时间，未来用于异步清理原视频、音频、字幕、TTS、成片和任务记录。

执行 Task 1 时，`ProjectRecord` 的测试需要断言这些默认值：

```python
self.assertEqual(restored.data_region, "local")
self.assertEqual(restored.privacy_flags["contains_voice_clone"], False)
self.assertEqual(restored.retention_until, "")
self.assertEqual(restored.deleted_at, "")
```

执行 Task 1 时，`project_models.py` 需要加入默认隐私标记：

```python
def default_privacy_flags() -> dict[str, bool]:
    return {
        "contains_voice_clone": False,
        "contains_person_audio": True,
        "contains_sensitive_content": False,
    }
```

并在 `ProjectRecord` 中加入：

```python
data_region: str = "local"
privacy_flags: dict[str, bool] = field(default_factory=default_privacy_flags)
retention_until: str = ""
deleted_at: str = ""
```

这些字段需要进入 `to_dict()` 和 `from_dict()`，并在读取旧数据时使用安全默认值。

第一阶段只做字段预留，不做登录、权限、自动清理和支付合规。后续做 FastAPI 或 SaaS 时，所有项目、版本、任务查询都必须通过 `user_id` 做归属过滤。

声音克隆需要单独的数据治理计划，至少应记录 `owner_user_id`、`reference_id`、授权确认、来源音频路径、创建时间和删除时间。本计划不实现声音资产表，只保证项目记录可以标记 `privacy_flags.contains_voice_clone`。

---

## Task 1: 新增项目、版本、任务模型

**Files:**

- Create: `video_slicer/project_models.py`
- Create: `tests/test_project_models.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_project_models.py`：

```python
import unittest

from video_slicer.project_models import (
    AspectRatio,
    AudioMode,
    JobStage,
    JobStatus,
    ProjectRecord,
    SubtitleLanguage,
    UserContext,
    VersionSettings,
    validate_version_settings,
)


class ProjectModelsTest(unittest.TestCase):
    def test_project_record_round_trip(self):
        project = ProjectRecord(
            user_id="local_user",
            project_id="project_demo",
            source_video_path="videos/demo.mp4",
            source_duration_seconds=300.0,
            user_context=UserContext(
                work_title="征服",
                main_characters=["刘华强", "封彪"],
                synopsis="刘华强逼封彪低头。",
                must_mentions=["下跪叫爷"],
                forbidden_content=["买瓜剧情"],
            ),
        )

        restored = ProjectRecord.from_dict(project.to_dict())

        self.assertEqual(restored.project_id, "project_demo")
        self.assertEqual(restored.user_context.work_title, "征服")
        self.assertEqual(restored.user_context.main_characters, ["刘华强", "封彪"])
        self.assertEqual(restored.user_context.forbidden_content, ["买瓜剧情"])`r`n        self.assertEqual(restored.data_region, "local")`r`n        self.assertEqual(restored.privacy_flags["contains_voice_clone"], False)`r`n        self.assertEqual(restored.retention_until, "")`r`n        self.assertEqual(restored.deleted_at, "")

    def test_version_settings_defaults(self):
        settings = VersionSettings(target_duration_seconds=120.0)

        self.assertEqual(settings.audio_mode, AudioMode.PURE_COMMENTARY)
        self.assertEqual(settings.subtitle_language, SubtitleLanguage.ZH)
        self.assertEqual(settings.aspect_ratio, AspectRatio.ORIGINAL)
        self.assertEqual(settings.voiceover_speed, 1.0)
        self.assertEqual(settings.voiceover_volume, 1.0)
        self.assertEqual(settings.bgm_volume, 0.16)

    def test_version_settings_round_trip_keeps_enums(self):
        settings = VersionSettings(
            target_duration_seconds=90.0,
            audio_mode=AudioMode.KEY_ORIGINAL_AUDIO,
            subtitle_language=SubtitleLanguage.ZH_EN,
            aspect_ratio=AspectRatio.VERTICAL_9_16_BLUR,
        )

        restored = VersionSettings.from_dict(settings.to_dict())

        self.assertEqual(restored.audio_mode, AudioMode.KEY_ORIGINAL_AUDIO)
        self.assertEqual(restored.subtitle_language, SubtitleLanguage.ZH_EN)
        self.assertEqual(restored.aspect_ratio, AspectRatio.VERTICAL_9_16_BLUR)

    def test_validate_rejects_target_not_shorter_than_source(self):
        settings = VersionSettings(target_duration_seconds=300.0)

        with self.assertRaisesRegex(ValueError, "shorter than source"):
            validate_version_settings(settings, source_duration_seconds=300.0)

    def test_validate_rejects_invalid_audio_numbers(self):
        settings = VersionSettings(
            target_duration_seconds=120.0,
            voiceover_speed=0.1,
            voiceover_volume=-1.0,
            bgm_volume=-0.1,
        )

        with self.assertRaisesRegex(ValueError, "voiceover_speed"):
            validate_version_settings(settings, source_duration_seconds=300.0)

    def test_job_enums_parse_product_values(self):
        self.assertEqual(JobStatus("pending"), JobStatus.PENDING)
        self.assertEqual(JobStage("generate_script"), JobStage.GENERATE_SCRIPT)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_project_models -v
```

Expected:

```text
ModuleNotFoundError: No module named 'video_slicer.project_models'
```

- [ ] **Step 3: 写模型实现**

创建 `video_slicer/project_models.py`：

```python
"""Project, version, and render-job records for the local product workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class AudioMode(str, Enum):
    PURE_COMMENTARY = "pure_commentary"
    KEY_ORIGINAL_AUDIO = "key_original_audio"


class SubtitleLanguage(str, Enum):
    ZH = "zh"
    EN = "en"
    ZH_EN = "zh_en"


class AspectRatio(str, Enum):
    ORIGINAL = "original"
    VERTICAL_9_16_BLUR = "vertical_9_16_blur"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    DONE = "done"
    CANCELLED = "cancelled"


class JobStage(str, Enum):
    EXTRACT_AUDIO = "extract_audio"
    TRANSCRIBE = "transcribe"
    GENERATE_SCRIPT = "generate_script"
    SEGMENT_SCRIPT = "segment_script"
    MATCH_VISUALS = "match_visuals"
    GENERATE_TTS = "generate_tts"
    FIT_DURATION = "fit_duration"
    CUT_VIDEO = "cut_video"
    MIX_AUDIO = "mix_audio"
    BURN_SUBTITLES = "burn_subtitles"
    EXPORT = "export"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _coerce_enum(enum_type: type[Enum], value: Any) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{enum_type.__name__} must be one of: {allowed}") from exc


@dataclass
class UserContext:
    work_title: str = ""
    main_characters: list[str] = field(default_factory=list)
    synopsis: str = ""
    must_mentions: list[str] = field(default_factory=list)
    forbidden_content: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_title": self.work_title,
            "main_characters": list(self.main_characters),
            "synopsis": self.synopsis,
            "must_mentions": list(self.must_mentions),
            "forbidden_content": list(self.forbidden_content),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "UserContext":
        data = data or {}
        return cls(
            work_title=str(data.get("work_title", "")),
            main_characters=_string_list(data.get("main_characters")),
            synopsis=str(data.get("synopsis", "")),
            must_mentions=_string_list(data.get("must_mentions")),
            forbidden_content=_string_list(data.get("forbidden_content")),
        )


@dataclass
class VersionSettings:
    target_duration_seconds: float
    audio_mode: AudioMode = AudioMode.PURE_COMMENTARY
    voice_clone_id: str = ""
    bgm_path: str = ""
    voiceover_speed: float = 1.0
    voiceover_volume: float = 1.0
    bgm_volume: float = 0.16
    subtitle_language: SubtitleLanguage = SubtitleLanguage.ZH
    aspect_ratio: AspectRatio = AspectRatio.ORIGINAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_duration_seconds": self.target_duration_seconds,
            "audio_mode": self.audio_mode.value,
            "voice_clone_id": self.voice_clone_id,
            "bgm_path": self.bgm_path,
            "voiceover_speed": self.voiceover_speed,
            "voiceover_volume": self.voiceover_volume,
            "bgm_volume": self.bgm_volume,
            "subtitle_language": self.subtitle_language.value,
            "aspect_ratio": self.aspect_ratio.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VersionSettings":
        return cls(
            target_duration_seconds=float(data["target_duration_seconds"]),
            audio_mode=_coerce_enum(AudioMode, data.get("audio_mode", AudioMode.PURE_COMMENTARY.value)),
            voice_clone_id=str(data.get("voice_clone_id", "")),
            bgm_path=str(data.get("bgm_path", "")),
            voiceover_speed=float(data.get("voiceover_speed", 1.0)),
            voiceover_volume=float(data.get("voiceover_volume", 1.0)),
            bgm_volume=float(data.get("bgm_volume", 0.16)),
            subtitle_language=_coerce_enum(SubtitleLanguage, data.get("subtitle_language", SubtitleLanguage.ZH.value)),
            aspect_ratio=_coerce_enum(AspectRatio, data.get("aspect_ratio", AspectRatio.ORIGINAL.value)),
        )


def validate_version_settings(settings: VersionSettings, *, source_duration_seconds: float | None = None) -> None:
    errors: list[str] = []
    if settings.target_duration_seconds <= 0:
        errors.append("target_duration_seconds must be greater than 0")
    if source_duration_seconds is not None and settings.target_duration_seconds >= source_duration_seconds:
        errors.append("target_duration_seconds must be shorter than source video duration")
    if not 0.5 <= settings.voiceover_speed <= 1.5:
        errors.append("voiceover_speed must be between 0.5 and 1.5")
    if settings.voiceover_volume < 0:
        errors.append("voiceover_volume must be greater than or equal to 0")
    if settings.bgm_volume < 0:
        errors.append("bgm_volume must be greater than or equal to 0")
    if errors:
        raise ValueError("; ".join(errors))


@dataclass
class ProjectRecord:
    user_id: str = "local_user"
    project_id: str = field(default_factory=lambda: new_id("project"))
    source_video_path: str = ""
    source_audio_path: str = ""
    transcript_path: str = ""
    source_duration_seconds: float | None = None
    user_context: UserContext = field(default_factory=UserContext)
    analysis: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "project_id": self.project_id,
            "source_video_path": self.source_video_path,
            "source_audio_path": self.source_audio_path,
            "transcript_path": self.transcript_path,
            "source_duration_seconds": self.source_duration_seconds,
            "user_context": self.user_context.to_dict(),
            "analysis": self.analysis,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectRecord":
        duration = data.get("source_duration_seconds")
        return cls(
            user_id=str(data.get("user_id", "local_user")),
            project_id=str(data["project_id"]),
            source_video_path=str(data.get("source_video_path", "")),
            source_audio_path=str(data.get("source_audio_path", "")),
            transcript_path=str(data.get("transcript_path", "")),
            source_duration_seconds=float(duration) if duration is not None else None,
            user_context=UserContext.from_dict(data.get("user_context")),
            analysis=dict(data.get("analysis", {})),
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
        )


@dataclass
class VersionRecord:
    project_id: str
    version_id: str = field(default_factory=lambda: new_id("version"))
    parent_version_id: str = ""
    generation_group_id: str = ""
    variant_goal: str = "manual"
    settings: VersionSettings = field(default_factory=lambda: VersionSettings(target_duration_seconds=120.0))
    generated_script: str = ""
    final_script: str = ""
    segmented_script: list[dict[str, Any]] = field(default_factory=list)
    visual_matches: list[dict[str, Any]] = field(default_factory=list)
    tts_audio_path: str = ""
    subtitle_paths: dict[str, str] = field(default_factory=dict)
    export_paths: dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "version_id": self.version_id,
            "parent_version_id": self.parent_version_id,
            "generation_group_id": self.generation_group_id,
            "variant_goal": self.variant_goal,
            "settings": self.settings.to_dict(),
            "generated_script": self.generated_script,
            "final_script": self.final_script,
            "segmented_script": self.segmented_script,
            "visual_matches": self.visual_matches,
            "tts_audio_path": self.tts_audio_path,
            "subtitle_paths": self.subtitle_paths,
            "export_paths": self.export_paths,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VersionRecord":
        return cls(
            project_id=str(data["project_id"]),
            version_id=str(data["version_id"]),
            parent_version_id=str(data.get("parent_version_id", "")),
            generation_group_id=str(data.get("generation_group_id", "")),
            variant_goal=str(data.get("variant_goal", "manual")),
            settings=VersionSettings.from_dict(data["settings"]),
            generated_script=str(data.get("generated_script", "")),
            final_script=str(data.get("final_script", "")),
            segmented_script=list(data.get("segmented_script", [])),
            visual_matches=list(data.get("visual_matches", [])),
            tts_audio_path=str(data.get("tts_audio_path", "")),
            subtitle_paths=dict(data.get("subtitle_paths", {})),
            export_paths=dict(data.get("export_paths", {})),
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
        )


@dataclass
class JobRecord:
    project_id: str
    version_id: str
    job_id: str = field(default_factory=lambda: new_id("job"))
    status: JobStatus = JobStatus.PENDING
    current_stage: JobStage = JobStage.EXTRACT_AUDIO
    error_message: str = ""
    duration_seconds: float | None = None
    export_paths: dict[str, str] = field(default_factory=dict)
    stage_history: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def add_history(self, *, status: JobStatus, stage: JobStage, error_message: str = "") -> None:
        self.stage_history.append({
            "status": status.value,
            "stage": stage.value,
            "error_message": error_message,
            "at": utc_now_iso(),
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "version_id": self.version_id,
            "job_id": self.job_id,
            "status": self.status.value,
            "current_stage": self.current_stage.value,
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds,
            "export_paths": self.export_paths,
            "stage_history": self.stage_history,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobRecord":
        duration = data.get("duration_seconds")
        return cls(
            project_id=str(data["project_id"]),
            version_id=str(data["version_id"]),
            job_id=str(data["job_id"]),
            status=_coerce_enum(JobStatus, data.get("status", JobStatus.PENDING.value)),
            current_stage=_coerce_enum(JobStage, data.get("current_stage", JobStage.EXTRACT_AUDIO.value)),
            error_message=str(data.get("error_message", "")),
            duration_seconds=float(duration) if duration is not None else None,
            export_paths=dict(data.get("export_paths", {})),
            stage_history=list(data.get("stage_history", [])),
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_project_models -v
```

Expected:

```text
Ran 6 tests

OK
```

- [ ] **Step 5: 提交**

Run:

```powershell
git add video_slicer/project_models.py tests/test_project_models.py
git commit -m "feat: add project version job models"
```

Expected:

```text
[CHEN <hash>] feat: add project version job models
```

---

## Task 2: 新增本地 JSON 存储

**Files:**

- Create: `video_slicer/project_store.py`
- Create: `tests/test_project_store.py`
- Modify: `.gitignore`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_project_store.py`：

```python
import tempfile
import unittest
from pathlib import Path

from video_slicer.project_models import (
    AudioMode,
    JobStage,
    JobStatus,
    VersionSettings,
)
from video_slicer.project_store import LocalProjectStore


class LocalProjectStoreTest(unittest.TestCase):
    def test_create_project_version_and_job_survive_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = LocalProjectStore(root)

            project = store.create_project(
                source_video_path="videos/demo.mp4",
                source_duration_seconds=300.0,
            )
            version = store.create_version(
                project_id=project.project_id,
                settings=VersionSettings(
                    target_duration_seconds=120.0,
                    audio_mode=AudioMode.KEY_ORIGINAL_AUDIO,
                ),
            )
            job = store.create_job(
                project_id=project.project_id,
                version_id=version.version_id,
                initial_stage=JobStage.GENERATE_SCRIPT,
            )

            reloaded = LocalProjectStore(root)

            self.assertEqual(reloaded.get_project(project.project_id).source_video_path, "videos/demo.mp4")
            self.assertEqual(reloaded.get_version(project.project_id, version.version_id).settings.audio_mode, AudioMode.KEY_ORIGINAL_AUDIO)
            self.assertEqual(reloaded.get_job(project.project_id, job.job_id).current_stage, JobStage.GENERATE_SCRIPT)

    def test_create_version_validates_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProjectStore(Path(tmp))
            project = store.create_project("videos/demo.mp4", source_duration_seconds=100.0)

            with self.assertRaisesRegex(ValueError, "shorter than source"):
                store.create_version(project.project_id, VersionSettings(target_duration_seconds=100.0))

    def test_update_job_status_records_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProjectStore(Path(tmp))
            project = store.create_project("videos/demo.mp4", source_duration_seconds=300.0)
            version = store.create_version(project.project_id, VersionSettings(target_duration_seconds=120.0))
            job = store.create_job(project.project_id, version.version_id)

            updated = store.update_job_status(
                project_id=project.project_id,
                job_id=job.job_id,
                status=JobStatus.RUNNING,
                stage=JobStage.GENERATE_TTS,
            )

            self.assertEqual(updated.status, JobStatus.RUNNING)
            self.assertEqual(updated.current_stage, JobStage.GENERATE_TTS)
            self.assertEqual(updated.stage_history[-1]["stage"], "generate_tts")

    def test_record_export_updates_version_and_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProjectStore(Path(tmp))
            project = store.create_project("videos/demo.mp4", source_duration_seconds=300.0)
            version = store.create_version(project.project_id, VersionSettings(target_duration_seconds=120.0))
            job = store.create_job(project.project_id, version.version_id)

            store.record_export(
                project_id=project.project_id,
                version_id=version.version_id,
                job_id=job.job_id,
                export_kind="final_video",
                export_path="projects.local/project_demo/exports/final.mp4",
                duration_seconds=119.8,
            )

            saved_version = store.get_version(project.project_id, version.version_id)
            saved_job = store.get_job(project.project_id, job.job_id)

            self.assertEqual(saved_version.export_paths["final_video"], "projects.local/project_demo/exports/final.mp4")
            self.assertEqual(saved_job.export_paths["final_video"], "projects.local/project_demo/exports/final.mp4")
            self.assertEqual(saved_job.duration_seconds, 119.8)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_project_store -v
```

Expected:

```text
ModuleNotFoundError: No module named 'video_slicer.project_store'
```

- [ ] **Step 3: 写存储实现**

创建 `video_slicer/project_store.py`：

```python
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
```

- [ ] **Step 4: 更新 `.gitignore`**

在 `.gitignore` 末尾追加：

```gitignore

# Local product data
projects.local/
```

- [ ] **Step 5: 运行存储测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_project_store -v
```

Expected:

```text
Ran 4 tests

OK
```

- [ ] **Step 6: 运行全部数据层测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_project_models tests.test_project_store -v
```

Expected:

```text
Ran 10 tests

OK
```

- [ ] **Step 7: 提交**

Run:

```powershell
git add .gitignore video_slicer/project_store.py tests/test_project_store.py
git commit -m "feat: add local project store"
```

Expected:

```text
[CHEN <hash>] feat: add local project store
```

---

## Task 3: 补充 README 和验收说明

**Files:**

- Modify: `README.md`

- [ ] **Step 1: 在 README 增加说明**

在 `README.md` 中加入：

```markdown
## 本地项目数据结构

项目正在从单个 demo pipeline 演进为“一个素材，多版本成片”的产品结构。

本地数据默认写入：

```text
projects.local/
  projects/
    <project_id>/
      project.json
      versions/
        <version_id>.json
      jobs/
        <job_id>.json
```

这类数据是本地运行产物，不应该提交到 Git。
项目记录会预留隐私和数据治理字段：

- `user_id`：本地模式为 `local_user`，未来用于账号归属。
- `data_region`：本地模式为 `local`，未来用于云端数据区域。
- `privacy_flags`：标记是否包含声音克隆、人物音频、敏感内容。
- `retention_until`：未来用于自动清理。
- `deleted_at`：未来用于软删除和异步物理删除。


### 概念

- 项目：一个原视频素材。
- 版本：同一个素材的一套成片方案，例如 60 秒纯解说版、120 秒关键原声版。
- 任务：一次生成或渲染动作，记录当前阶段、状态、导出路径和最终成片时长。
```

- [ ] **Step 2: 运行全部测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_project_models tests.test_project_store -v
```

Expected:

```text
Ran 10 tests

OK
```

- [ ] **Step 3: 确认本地数据目录被忽略**

Run:

```powershell
git status --short projects.local
```

Expected:

```text

```

输出为空表示 `projects.local/` 不会进入 Git。

- [ ] **Step 4: 提交文档**

Run:

```powershell
git add README.md
git commit -m "docs: describe local project data model"
```

Expected:

```text
[CHEN <hash>] docs: describe local project data model
```

---

## 自检

Spec 覆盖：

- 覆盖了 `user_id`、`project_id`、`version_id`、`job_id`。
- 覆盖了一个项目对应一个原视频。
- 覆盖了一个项目多个版本。
- 覆盖了版本参数：目标时长、音频模式、声音、BGM、字幕语言、画幅。
- 覆盖了任务状态、任务阶段、最终成片时长和导出路径。
- 覆盖了本地单人模式和未来商业化字段预留。
- 覆盖了项目层隐私和数据治理预留字段：`data_region`、`privacy_flags`、`retention_until`、`deleted_at`。

类型一致性：

- 测试、模型、存储统一使用 `ProjectRecord`、`VersionRecord`、`JobRecord`、`VersionSettings`、`UserContext`。
- 枚举统一使用 `AudioMode`、`SubtitleLanguage`、`AspectRatio`、`JobStatus`、`JobStage`。
- 存储入口统一使用 `LocalProjectStore`。

执行注意：

- 当前仓库已有未提交改动，执行时每个 Task 只 `git add` 本 Task 的文件。
- 本计划不碰 `.env`，不读取或提交任何 API Key。
- 本计划不提交 `videos/`、`outputs/`、`projects.local/`。

## 执行选择

Plan complete and saved to `docs/superpowers/plans/2026-07-09-project-version-job-data-model.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
