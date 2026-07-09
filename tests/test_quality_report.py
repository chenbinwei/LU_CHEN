import tempfile
import unittest
from pathlib import Path

from video_slicer.quality_report import build_quality_report, text_similarity, write_quality_report


def sample_alignment(**overrides):
    row = {
        "sentence_id": 1,
        "text": "主角逼对手当众低头。",
        "source_text": "给我跪下 叫一声爷",
        "source_start": 10.0,
        "source_end": 14.0,
        "voiceover_duration": 4.0,
    }
    row.update(overrides)
    return row


def sample_clip(**overrides):
    row = {
        "id": 1,
        "sentence_text": "主角逼对手当众低头。",
        "source_start": 10.0,
        "source_end": 14.0,
        "duration": 4.0,
    }
    row.update(overrides)
    return row


class QualityReportTest(unittest.TestCase):
    def test_text_similarity_uses_chinese_overlap(self):
        self.assertGreater(text_similarity("主角逼对手下跪", "主角 叫对手 跪下"), 0.2)
        self.assertEqual(text_similarity("", "主角"), 0.0)

    def test_clean_report_passes(self):
        report = build_quality_report(
            alignment=[sample_alignment()],
            clips=[sample_clip()],
            target_duration=4.0,
            duration_tolerance=0.5,
            actual_voiceover_duration=4.0,
            actual_visual_duration=4.0,
            source_video_duration=30.0,
            tts_mode="fish",
            title="demo",
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(report["metrics"]["alignment_count"], 1)

    def test_duration_outside_tolerance_is_error(self):
        report = build_quality_report(
            alignment=[sample_alignment()],
            clips=[sample_clip(duration=3.0)],
            target_duration=4.0,
            duration_tolerance=0.25,
            actual_voiceover_duration=4.0,
            actual_visual_duration=3.0,
        )

        self.assertEqual(report["status"], "fail")
        self.assertIn("visual_duration_outside_tolerance", {item["id"] for item in report["issues"]})

    def test_flags_long_source_span_and_english_letters(self):
        report = build_quality_report(
            alignment=[
                sample_alignment(
                    text="主角说出 final warning。",
                    source_start=10.0,
                    source_end=80.0,
                    voiceover_duration=4.0,
                )
            ],
            clips=[sample_clip()],
            target_duration=4.0,
            duration_tolerance=0.5,
            actual_voiceover_duration=4.0,
            actual_visual_duration=4.0,
        )

        issue_ids = {item["id"] for item in report["issues"]}
        self.assertEqual(report["status"], "warn")
        self.assertIn("source_evidence_span_too_long", issue_ids)
        self.assertIn("voiceover_contains_english", issue_ids)

    def test_flags_visual_backtrack_and_major_overlap(self):
        report = build_quality_report(
            alignment=[sample_alignment(), sample_alignment(sentence_id=2)],
            clips=[
                sample_clip(id=1, source_start=20.0, source_end=30.0),
                sample_clip(id=2, source_start=18.0, source_end=22.0),
            ],
            target_duration=8.0,
            duration_tolerance=0.5,
            actual_voiceover_duration=8.0,
            actual_visual_duration=8.0,
        )

        issue_ids = {item["id"] for item in report["issues"]}
        self.assertEqual(report["status"], "warn")
        self.assertIn("source_timeline_backtrack", issue_ids)
        self.assertIn("source_timeline_major_overlap", issue_ids)
        self.assertEqual(report["metrics"]["source_major_overlap_count"], 1)
        self.assertEqual(report["metrics"]["source_major_overlap_max"], 12.0)

    def test_flags_low_evidence_score_from_llm_source_ids(self):
        report = build_quality_report(
            alignment=[
                sample_alignment(
                    text="天气突然变得很好。",
                    source_text="给我跪下",
                    source_id_trust="llm_provided",
                    match_score=0.0,
                )
            ],
            clips=[sample_clip()],
            target_duration=4.0,
            duration_tolerance=0.5,
            actual_voiceover_duration=4.0,
            actual_visual_duration=4.0,
        )

        issue_ids = {item["id"] for item in report["issues"]}
        self.assertEqual(report["status"], "warn")
        self.assertIn("llm_source_ids_low_evidence_score", issue_ids)
        self.assertEqual(report["metrics"]["low_match_score_count"], 1)

    def test_counts_llm_source_ids_replaced_by_ordered_fallback(self):
        report = build_quality_report(
            alignment=[
                sample_alignment(
                    source_segment_ids=[4],
                    original_source_segment_ids=[2],
                    source_id_trust="llm_replaced_by_ordered_fallback",
                    evidence_warning="replaced_to_preserve_source_order",
                    match_score=0.3,
                )
            ],
            clips=[sample_clip()],
            target_duration=4.0,
            duration_tolerance=0.5,
            actual_voiceover_duration=4.0,
            actual_visual_duration=4.0,
        )

        issue_ids = {item["id"] for item in report["issues"]}
        self.assertEqual(report["status"], "warn")
        self.assertIn("llm_source_ids_replaced_by_ordered_fallback", issue_ids)
        self.assertEqual(report["metrics"]["source_order_repair_count"], 1)

    def test_counts_continuity_visual_support_as_info(self):
        report = build_quality_report(
            alignment=[
                sample_alignment(
                    text="这一句需要画面连续支撑。",
                    source_text="Alpha beta",
                    source_segment_ids=[2],
                    original_source_segment_ids=[2],
                    source_id_trust="continuity_visual_support",
                    evidence_warning="low_evidence_continuity_visual_support",
                    match_score=0.0,
                )
            ],
            clips=[sample_clip()],
            target_duration=4.0,
            duration_tolerance=0.5,
            actual_voiceover_duration=4.0,
            actual_visual_duration=4.0,
        )

        issue_ids = {item["id"] for item in report["issues"]}
        self.assertEqual(report["status"], "pass")
        self.assertIn("continuity_visual_support_low_evidence", issue_ids)
        self.assertNotIn("llm_source_ids_low_evidence_score", issue_ids)
        self.assertEqual(report["metrics"]["continuity_visual_support_count"], 1)

    def test_write_quality_report(self):
        report = build_quality_report(
            alignment=[sample_alignment()],
            clips=[sample_clip()],
            target_duration=4.0,
            duration_tolerance=0.5,
            actual_voiceover_duration=4.0,
            actual_visual_duration=4.0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quality_report.json"
            write_quality_report(report, path)

            self.assertIn('"schema_version": 1', path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
