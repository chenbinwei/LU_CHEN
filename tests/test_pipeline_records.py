import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from video_slicer.pipeline_records import (
    PipelineRecordSession,
    begin_pipeline_record_session,
    settings_from_pipeline_args,
)
from video_slicer.pipeline import build_parser
from video_slicer.project_models import AudioMode, JobStatus
from video_slicer.project_store import LocalProjectStore


def make_args(**overrides):
    values = {
        "record_project": False,
        "project_root": "",
        "project_id": "",
        "version_id": "",
        "input": "videos/input.mp4",
        "target_duration": 120.0,
        "tts_mode": "fish",
        "fish_reference_id": "fish_voice_demo",
        "fish_tts_speed": 0.92,
        "ocool_tts_voice": "echo",
        "ocool_tts_speed": 1.0,
        "bgm_audio": "assets/bgm/demo.mp3",
        "bgm_volume": 0.18,
        "voiceover_volume": 1.1,
    }
    values.update(overrides)
    return Namespace(**values)


class PipelineRecordsTest(unittest.TestCase):
    def test_settings_from_fish_args(self):
        settings = settings_from_pipeline_args(make_args())

        self.assertEqual(settings.target_duration_seconds, 120.0)
        self.assertEqual(settings.audio_mode, AudioMode.PURE_COMMENTARY)
        self.assertEqual(settings.voice_clone_id, "fish_voice_demo")
        self.assertEqual(settings.voiceover_speed, 0.92)
        self.assertEqual(settings.voiceover_volume, 1.1)
        self.assertEqual(settings.bgm_path, "assets/bgm/demo.mp3")
        self.assertEqual(settings.bgm_volume, 0.18)

    def test_settings_from_ocool_args_uses_voice_name(self):
        settings = settings_from_pipeline_args(
            make_args(tts_mode="ocool", fish_reference_id="", ocool_tts_voice="nova")
        )

        self.assertEqual(settings.voice_clone_id, "nova")
        self.assertEqual(settings.voiceover_speed, 1.0)

    def test_begin_session_disabled(self):
        session = begin_pipeline_record_session(make_args(record_project=False), video_duration=300.0)

        self.assertFalse(session.enabled)
        self.assertIsNone(session.store)
        self.assertEqual(session.project_id, "")

    def test_begin_session_enabled_creates_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(record_project=True, project_root=tmp, project_id="project_demo")

            session = begin_pipeline_record_session(args, video_duration=300.0)

            self.assertTrue(session.enabled)
            self.assertEqual(session.project_id, "project_demo")
            self.assertTrue(session.version_id.startswith("version_"))
            self.assertTrue(session.job_id.startswith("job_"))

            store = LocalProjectStore(Path(tmp))
            project = store.get_project(session.project_id)
            version = store.get_version(session.project_id, session.version_id)
            job = store.get_job(session.project_id, session.job_id)

            self.assertEqual(project.source_video_path, "videos/input.mp4")
            self.assertEqual(project.source_duration_seconds, 300.0)
            self.assertEqual(version.settings.target_duration_seconds, 120.0)
            self.assertEqual(job.status, JobStatus.RUNNING)

    def test_record_success_and_failure_are_noops_when_disabled(self):
        session = PipelineRecordSession.disabled()

        session.mark_success(final_video_path="outputs/final.mp4", duration_seconds=119.8)
        session.mark_failed(RuntimeError("boom"))

        self.assertFalse(session.enabled)

    def test_record_success_updates_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = begin_pipeline_record_session(
                make_args(record_project=True, project_root=tmp, project_id="project_demo"),
                video_duration=300.0,
            )

            session.mark_success(final_video_path="outputs/final_with_bgm.mp4", duration_seconds=119.8)

            store = LocalProjectStore(Path(tmp))
            version = store.get_version(session.project_id, session.version_id)
            job = store.get_job(session.project_id, session.job_id)

            self.assertEqual(version.export_paths["final_video"], "outputs/final_with_bgm.mp4")
            self.assertEqual(job.export_paths["final_video"], "outputs/final_with_bgm.mp4")
            self.assertEqual(job.duration_seconds, 119.8)
            self.assertEqual(job.status, JobStatus.DONE)

    def test_record_failure_updates_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = begin_pipeline_record_session(
                make_args(record_project=True, project_root=tmp, project_id="project_demo"),
                video_duration=300.0,
            )

            session.mark_failed(ValueError("bad duration"))

            store = LocalProjectStore(Path(tmp))
            job = store.get_job(session.project_id, session.job_id)

            self.assertEqual(job.status, JobStatus.FAILED)
            self.assertIn("bad duration", job.error_message)



class PipelineParserRecordArgsTest(unittest.TestCase):
    def test_parser_accepts_project_record_args(self):
        parser = build_parser()
        args = parser.parse_args([
            "--record-project",
            "--project-root",
            "projects.local",
            "--project-id",
            "project_demo",
            "--version-id",
            "version_demo",
        ])

        self.assertTrue(args.record_project)
        self.assertEqual(args.project_root, "projects.local")
        self.assertEqual(args.project_id, "project_demo")
        self.assertEqual(args.version_id, "version_demo")

if __name__ == "__main__":
    unittest.main()
