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
            self.assertEqual(
                reloaded.get_version(project.project_id, version.version_id).settings.audio_mode,
                AudioMode.KEY_ORIGINAL_AUDIO,
            )
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
