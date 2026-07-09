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
                work_title="作品A",
                main_characters=["角色甲", "角色乙"],
                synopsis="角色甲和角色乙发生关键冲突。",
                must_mentions=["关键转折"],
                forbidden_content=["无关剧情"],
            ),
        )

        restored = ProjectRecord.from_dict(project.to_dict())

        self.assertEqual(restored.project_id, "project_demo")
        self.assertEqual(restored.user_context.work_title, "作品A")
        self.assertEqual(restored.user_context.main_characters, ["角色甲", "角色乙"])
        self.assertEqual(restored.user_context.forbidden_content, ["无关剧情"])
        self.assertEqual(restored.data_region, "local")
        self.assertEqual(restored.privacy_flags["contains_voice_clone"], False)
        self.assertEqual(restored.retention_until, "")
        self.assertEqual(restored.deleted_at, "")

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
