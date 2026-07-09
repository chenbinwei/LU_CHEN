import unittest

from video_slicer.pipeline import (
    validate_requested_target_duration,
    validate_timeline_duration,
)
from video_slicer.script_generation import (
    fallback_voiceover_script,
    forbidden_terms_from_context,
    validate_voiceover_doc,
)


class PipelineTest(unittest.TestCase):
    def test_fallback_voiceover_script_passes_text_validation(self):
        voiceover_doc = fallback_voiceover_script(
            [
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 2.0,
                    "text": "主角走进房间。",
                }
            ],
            target_duration=10.0,
        )

        validate_voiceover_doc(voiceover_doc, context_packet={})

    def test_default_forbidden_terms_do_not_include_project_specific_terms(self):
        terms = forbidden_terms_from_context(context_packet={})

        self.assertIn("VOICEOVER", terms)
        self.assertNotIn("obsolete_term", terms)
        self.assertNotIn("obsolete_terms", terms)

    def test_validate_requested_target_duration_requires_positive_shorter_than_source(self):
        validate_requested_target_duration(target_duration=60.0, video_duration=120.0)

        with self.assertRaises(SystemExit):
            validate_requested_target_duration(target_duration=0.0, video_duration=120.0)
        with self.assertRaises(SystemExit):
            validate_requested_target_duration(target_duration=120.0, video_duration=120.0)
        with self.assertRaises(SystemExit):
            validate_requested_target_duration(target_duration=121.0, video_duration=120.0)

    def test_validate_timeline_duration_rejects_target_drift(self):
        validate_timeline_duration(
            target_duration=120.0,
            tolerance=3.0,
            actual_voiceover_duration=119.5,
            actual_visual_duration=120.2,
        )

        with self.assertRaises(SystemExit):
            validate_timeline_duration(
                target_duration=120.0,
                tolerance=3.0,
                actual_voiceover_duration=120.0,
                actual_visual_duration=100.0,
            )
        with self.assertRaises(SystemExit):
            validate_timeline_duration(
                target_duration=120.0,
                tolerance=3.0,
                actual_voiceover_duration=100.0,
                actual_visual_duration=120.0,
            )
        with self.assertRaises(SystemExit):
            validate_timeline_duration(
                target_duration=120.0,
                tolerance=3.0,
                actual_voiceover_duration=115.0,
                actual_visual_duration=120.0,
            )


if __name__ == "__main__":
    unittest.main()
