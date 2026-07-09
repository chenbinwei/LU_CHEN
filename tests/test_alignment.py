import unittest

from video_slicer.alignment import (
    align_voiceover_to_transcript,
    apply_estimated_voiceover_timeline,
    build_clips_from_alignment,
    limit_alignment_to_target_duration,
    score_source_evidence,
    simple_text_score,
)


def sample_segments():
    return [
        {"id": 1, "start": 0.0, "end": 2.0, "text": "刘华强走进房间"},
        {"id": 2, "start": 2.0, "end": 4.0, "text": "给我跪下"},
        {"id": 3, "start": 4.0, "end": 7.0, "text": "叫一声爷 我就放过你"},
        {"id": 4, "start": 7.0, "end": 10.0, "text": "封彪低头服软"},
    ]


def ordered_segments():
    return [
        {"id": 1, "start": 0.0, "end": 2.0, "text": "Alpha opening"},
        {"id": 2, "start": 2.0, "end": 4.0, "text": "Beta middle confrontation"},
        {"id": 3, "start": 4.0, "end": 6.0, "text": "Zzzz qqqq"},
        {"id": 4, "start": 6.0, "end": 8.0, "text": "Delta closing pressure"},
    ]


class AlignmentTest(unittest.TestCase):
    def test_simple_text_score_prefers_overlapping_text(self):
        good = simple_text_score("刘华强让封彪跪下", "给我跪下")
        bad = simple_text_score("刘华强让封彪跪下", "天气很好")

        self.assertGreater(good, bad)

    def test_score_source_evidence_does_not_auto_trust_ids(self):
        good = score_source_evidence("刘华强让封彪跪下", "给我跪下")
        bad = score_source_evidence("刘华强让封彪跪下", "天气很好")

        self.assertGreater(good, bad)
        self.assertLess(good, 1.0)

    def test_align_uses_source_segment_ids_when_available(self):
        voiceover_doc = {
            "voiceover": [
                {
                    "text": "他冷冷地命令封彪当场跪下。",
                    "source_segment_ids": [2],
                    "story_role": "turning_point",
                    "visual_note": "跪下台词画面",
                }
            ]
        }

        alignment = align_voiceover_to_transcript(voiceover_doc, sample_segments(), target_duration=5.0)

        self.assertEqual(len(alignment), 1)
        self.assertEqual(alignment[0]["source_segment_ids"], [2])
        self.assertEqual(alignment[0]["source_start"], 2.0)
        self.assertEqual(alignment[0]["source_end"], 4.0)
        self.assertLess(alignment[0]["match_score"], 1.0)
        self.assertGreater(alignment[0]["match_score"], 0.0)
        self.assertEqual(alignment[0]["source_id_trust"], "llm_provided")
        self.assertEqual(alignment[0]["story_role"], "turning_point")
        self.assertEqual(alignment[0]["source_order_policy"], "monotonic")

    def test_align_downgrades_low_evidence_llm_source_ids_without_better_match(self):
        voiceover_doc = {
            "voiceover": [
                {
                    "text": "天气突然变得很好。",
                    "source_segment_ids": [2],
                }
            ]
        }

        alignment = align_voiceover_to_transcript(voiceover_doc, sample_segments(), target_duration=5.0)

        self.assertEqual(alignment[0]["source_id_trust"], "continuity_visual_support")
        self.assertEqual(alignment[0]["original_source_segment_ids"], [2])
        self.assertLess(alignment[0]["match_score"], 0.08)
        self.assertEqual(alignment[0]["evidence_warning"], "low_evidence_continuity_visual_support")

    def test_align_falls_back_to_text_similarity_without_source_ids(self):
        voiceover_doc = {
            "voiceover": [
                {
                    "text": "刘华强逼对方跪下。",
                    "source_segment_ids": [],
                }
            ]
        }

        alignment = align_voiceover_to_transcript(voiceover_doc, sample_segments(), target_duration=5.0)

        self.assertEqual(len(alignment), 1)
        self.assertIn(2, alignment[0]["source_segment_ids"])
        self.assertGreaterEqual(alignment[0]["match_score"], 0.0)
        self.assertEqual(alignment[0]["source_id_trust"], "fallback_matched")

    def test_align_replaces_backward_llm_ids_with_ordered_fallback(self):
        voiceover_doc = {
            "voiceover": [
                {"text": "Delta closing pressure.", "source_segment_ids": [4]},
                {"text": "Beta middle confrontation.", "source_segment_ids": [2]},
            ]
        }

        alignment = align_voiceover_to_transcript(voiceover_doc, ordered_segments(), target_duration=8.0)

        self.assertEqual(alignment[0]["source_segment_ids"], [4])
        self.assertEqual(alignment[0]["source_id_trust"], "llm_provided")
        self.assertEqual(alignment[1]["source_id_trust"], "llm_replaced_by_ordered_fallback")
        self.assertEqual(alignment[1]["original_source_segment_ids"], [2])
        self.assertNotEqual(alignment[1]["source_segment_ids"], [2])
        self.assertGreaterEqual(alignment[1]["source_start"], alignment[0]["source_start"])
        self.assertEqual(alignment[1]["evidence_warning"], "replaced_to_preserve_source_order")
        self.assertEqual(alignment[1]["source_order_policy"], "monotonic")

    def test_align_replaces_low_evidence_llm_ids_with_ordered_fallback(self):
        voiceover_doc = {
            "voiceover": [
                {"text": "Zzzz qqqq.", "source_segment_ids": [1]},
            ]
        }

        alignment = align_voiceover_to_transcript(voiceover_doc, ordered_segments(), target_duration=4.0)

        self.assertEqual(alignment[0]["source_segment_ids"], [3])
        self.assertEqual(alignment[0]["source_id_trust"], "llm_replaced_by_ordered_fallback")
        self.assertEqual(alignment[0]["original_source_segment_ids"], [1])
        self.assertEqual(alignment[0]["evidence_warning"], "llm_source_ids_replaced_low_score")
        self.assertEqual(alignment[0]["source_order_policy"], "monotonic")

    def test_align_marks_low_evidence_llm_ids_as_continuity_when_no_better_match_exists(self):
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Alpha opening"},
            {"id": 2, "start": 2.0, "end": 4.0, "text": "Beta reaction"},
            {"id": 3, "start": 4.0, "end": 6.0, "text": "Gamma ending"},
        ]
        voiceover_doc = {
            "voiceover": [
                {"text": "这一句需要顺序画面支撑，但字幕没有直接证据。", "source_segment_ids": [2]},
            ]
        }

        alignment = align_voiceover_to_transcript(voiceover_doc, segments, target_duration=4.0)

        self.assertEqual(alignment[0]["source_segment_ids"], [2])
        self.assertEqual(alignment[0]["source_id_trust"], "continuity_visual_support")
        self.assertEqual(alignment[0]["original_source_segment_ids"], [2])
        self.assertEqual(alignment[0]["evidence_warning"], "low_evidence_continuity_visual_support")
        self.assertLess(alignment[0]["match_score"], 0.08)

    def test_apply_estimated_voiceover_timeline_adds_voiceover_fields(self):
        alignment = [
            {"sentence_id": 1, "text": "刘华强走进来。", "estimated_voiceover_duration": 2.0},
            {"sentence_id": 2, "text": "封彪开始慌了。", "estimated_voiceover_duration": 3.0},
        ]

        result = apply_estimated_voiceover_timeline(alignment)

        self.assertEqual(result[0]["voiceover_start"], 0.0)
        self.assertEqual(result[0]["voiceover_end"], 2.0)
        self.assertEqual(result[1]["voiceover_start"], 2.0)
        self.assertEqual(result[1]["voiceover_end"], 5.0)
        self.assertIsNone(result[0]["voiceover_audio_path"])

    def test_limit_alignment_to_target_duration_trims_extra_rows(self):
        alignment = [
            {"sentence_id": 1, "text": "一", "voiceover_duration": 3.0},
            {"sentence_id": 2, "text": "二", "voiceover_duration": 4.0},
            {"sentence_id": 3, "text": "三", "voiceover_duration": 5.0},
        ]

        result = limit_alignment_to_target_duration(alignment, target_duration=5.0, tolerance=1.0)

        self.assertEqual([row["sentence_id"] for row in result], [1])
        self.assertEqual(result[0]["voiceover_start"], 0.0)
        self.assertEqual(result[0]["voiceover_end"], 3.0)

    def test_build_clips_from_alignment_keeps_ranges_inside_video(self):
        alignment = [
            {
                "sentence_id": 1,
                "text": "结尾收束。",
                "source_segment_ids": [4],
                "source_start": 8.0,
                "source_end": 10.0,
                "voiceover_start": 0.0,
                "voiceover_end": 4.0,
                "voiceover_duration": 4.0,
                "voiceover_audio_path": "voice.mp3",
            }
        ]

        clips = build_clips_from_alignment(alignment, video_duration=10.0, padding=0.25)

        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["id"], 1)
        self.assertGreaterEqual(clips[0]["source_start"], 0.0)
        self.assertLessEqual(clips[0]["source_end"], 10.0)
        self.assertEqual(clips[0]["duration"], 4.0)
        self.assertEqual(clips[0]["voiceover_audio_path"], "voice.mp3")

    def test_build_clips_from_alignment_anchors_long_setup_span_near_start(self):
        alignment = [
            {
                "sentence_id": 1,
                "text": "Generic setup line.",
                "source_segment_ids": [1, 2, 3],
                "source_start": 10.0,
                "source_end": 70.0,
                "voiceover_start": 0.0,
                "voiceover_end": 5.0,
                "voiceover_duration": 5.0,
                "story_role": "setup",
            }
        ]

        clips = build_clips_from_alignment(alignment, video_duration=100.0, padding=0.0)

        self.assertEqual(clips[0]["source_start"], 10.0)
        self.assertEqual(clips[0]["source_end"], 15.0)
        self.assertEqual(clips[0]["visual_selection_reason"], "anchored_to_source_span_start")

    def test_build_clips_from_alignment_anchors_long_turning_point_span_near_end(self):
        alignment = [
            {
                "sentence_id": 1,
                "text": "Generic turning point line.",
                "source_segment_ids": [1, 2, 3],
                "source_start": 10.0,
                "source_end": 70.0,
                "voiceover_start": 0.0,
                "voiceover_end": 5.0,
                "voiceover_duration": 5.0,
                "story_role": "turning_point",
            }
        ]

        clips = build_clips_from_alignment(alignment, video_duration=100.0, padding=0.0)

        self.assertEqual(clips[0]["source_start"], 65.0)
        self.assertEqual(clips[0]["source_end"], 70.0)
        self.assertEqual(clips[0]["visual_selection_reason"], "anchored_to_source_span_end")

    def test_build_clips_from_alignment_keeps_source_starts_monotonic(self):
        alignment = [
            {
                "sentence_id": 1,
                "text": "First beat.",
                "source_segment_ids": [1],
                "source_start": 10.0,
                "source_end": 11.0,
                "voiceover_start": 0.0,
                "voiceover_end": 1.0,
                "voiceover_duration": 1.0,
            },
            {
                "sentence_id": 2,
                "text": "Second beat runs longer.",
                "source_segment_ids": [2],
                "source_start": 11.0,
                "source_end": 12.0,
                "voiceover_start": 1.0,
                "voiceover_end": 7.0,
                "voiceover_duration": 6.0,
            },
        ]

        clips = build_clips_from_alignment(alignment, video_duration=30.0, padding=0.0)

        self.assertEqual(len(clips), 2)
        self.assertGreaterEqual(clips[1]["source_start"], clips[0]["source_start"])
        self.assertEqual(clips[1]["duration"], 6.0)

    def test_build_clips_from_alignment_shifts_later_clip_to_reduce_overlap(self):
        alignment = [
            {
                "sentence_id": 1,
                "text": "First repeated evidence.",
                "source_segment_ids": [1],
                "source_start": 10.0,
                "source_end": 12.0,
                "voiceover_start": 0.0,
                "voiceover_end": 6.0,
                "voiceover_duration": 6.0,
            },
            {
                "sentence_id": 2,
                "text": "Second repeated evidence.",
                "source_segment_ids": [1],
                "source_start": 10.0,
                "source_end": 12.0,
                "voiceover_start": 6.0,
                "voiceover_end": 12.0,
                "voiceover_duration": 6.0,
            },
        ]

        clips = build_clips_from_alignment(alignment, video_duration=40.0, padding=0.0)

        self.assertEqual(len(clips), 2)
        overlap = clips[0]["source_end"] - clips[1]["source_start"]
        self.assertLessEqual(overlap, 2.0)
        self.assertEqual(clips[1]["duration"], 6.0)
        self.assertEqual(clips[1]["visual_selection_reason"], "shifted_to_reduce_overlap")

    def test_build_clips_from_alignment_looks_ahead_to_fit_remaining_clips(self):
        alignment = []
        for sentence_id in range(1, 4):
            alignment.append({
                "sentence_id": sentence_id,
                "text": f"Late evidence {sentence_id}.",
                "source_segment_ids": [9],
                "source_start": 30.0,
                "source_end": 31.0,
                "voiceover_start": float((sentence_id - 1) * 10),
                "voiceover_end": float(sentence_id * 10),
                "voiceover_duration": 10.0,
            })

        clips = build_clips_from_alignment(alignment, video_duration=40.0, padding=0.0)

        self.assertEqual(len(clips), 3)
        self.assertEqual(clips[0]["visual_selection_reason"], "shifted_earlier_to_fit_remaining_duration")
        self.assertEqual([clip["duration"] for clip in clips], [10.0, 10.0, 10.0])
        for previous, current in zip(clips, clips[1:]):
            self.assertLessEqual(previous["source_end"] - current["source_start"], 2.0)
        self.assertEqual(clips[-1]["source_end"], 40.0)

    def test_build_clips_from_alignment_preserves_duration_when_late_evidence_clusters(self):
        durations = [6.996, 5.122, 8.152, 4.499, 7.122, 6.996, 6.683, 7.527, 8.464, 7.527, 5.03, 7.216, 5.122]
        evidence_starts = [
            281.61,
            290.99,
            290.99,
            290.99,
            290.99,
            313.36,
            321.37,
            321.37,
            321.37,
            321.37,
            321.37,
            321.37,
            321.37,
        ]
        alignment = [
            {
                "sentence_id": index,
                "text": f"Generic line {index}.",
                "source_segment_ids": [index],
                "source_start": evidence_start,
                "source_end": evidence_start + 1.0,
                "voiceover_start": 0.0,
                "voiceover_end": duration,
                "voiceover_duration": duration,
            }
            for index, (duration, evidence_start) in enumerate(zip(durations, evidence_starts), start=1)
        ]

        video_duration = 336.450703

        clips = build_clips_from_alignment(alignment, video_duration=video_duration, padding=0.0)

        self.assertEqual(len(clips), len(alignment))
        self.assertAlmostEqual(sum(clip["duration"] for clip in clips), sum(durations), places=3)
        self.assertLessEqual(clips[-1]["source_end"], video_duration + 0.001)
        self.assertIn(
            "shifted_earlier_to_fit_remaining_duration",
            {clip["visual_selection_reason"] for clip in clips},
        )
        for previous, current in zip(clips, clips[1:]):
            self.assertLessEqual(previous["source_end"] - current["source_start"], 2.0)


if __name__ == "__main__":
    unittest.main()
