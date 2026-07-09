import json
import unittest
from pathlib import Path
from unittest.mock import patch

from video_slicer.script_generation import (
    fallback_voiceover_script,
    forbidden_terms_from_context,
    parse_json_response,
    parse_llm_json_response,
    validate_voiceover_doc,
    voiceover_length_requirements,
)


class ScriptGenerationPureHelperTest(unittest.TestCase):
    def test_voiceover_length_requirements_scale_with_target_duration(self):
        result = voiceover_length_requirements(120.0)

        self.assertEqual(result["target_duration_seconds"], 120)
        self.assertGreaterEqual(result["min_voiceover_items"], 8)
        self.assertGreater(result["max_voiceover_items"], result["min_voiceover_items"])
        self.assertGreater(result["ideal_total_cjk_chars"], result["min_total_cjk_chars"])
        self.assertLess(result["ideal_total_cjk_chars"], result["max_total_cjk_chars"])

    def test_parse_json_response_accepts_markdown_wrapped_json(self):
        result = parse_json_response('```json\n{"voiceover": [{"text": "你好"}]}\n```')

        self.assertEqual(result["voiceover"][0]["text"], "你好")

    def test_parse_llm_json_response_repairs_invalid_json_once(self):
        broken = '{"voiceover": [{"text": "你好"}'
        fixed = '{"voiceover": [{"text": "你好"}]}'

        with patch("llm_providers.dashscope.text_completion", return_value=fixed) as mocked_completion:
            result = parse_llm_json_response(
                broken,
                model="qwen-plus-latest",
                base_url="https://example.test",
                api_key="sk-test",
            )

        self.assertEqual(result["voiceover"][0]["text"], "你好")
        mocked_completion.assert_called_once()

    def test_fallback_voiceover_script_passes_text_validation(self):
        voiceover_doc = fallback_voiceover_script(
            [{"id": 1, "start": 0.0, "end": 2.0, "text": "主角走进房间。"}],
            target_duration=10.0,
        )

        validate_voiceover_doc(voiceover_doc, context_packet={})

    def test_default_forbidden_terms_do_not_include_project_specific_terms(self):
        terms = forbidden_terms_from_context(context_packet={})

        self.assertIn("VOICEOVER", terms)
        self.assertNotIn("obsolete_term", terms)
        self.assertNotIn("obsolete_terms", terms)

    def test_validate_voiceover_doc_rejects_tts_unfriendly_terms(self):
        voiceover_doc = {
            "title": "测试",
            "summary": "测试",
            "voiceover": [{"text": "他说得平，但意思很清楚。"}],
        }

        with self.assertRaises(SystemExit) as ctx:
            validate_voiceover_doc(voiceover_doc, context_packet={})

        self.assertIn("TTS-unfriendly", str(ctx.exception))

    def test_generate_voiceover_with_llm_returns_none_without_api_key(self):
        from video_slicer.script_generation import generate_voiceover_with_llm

        with patch.dict("os.environ", {"DASHSCOPE_API_KEY": ""}, clear=False):
            result = generate_voiceover_with_llm(
                segments=[{"id": 1, "start": 0.0, "end": 1.0, "text": "一句字幕"}],
                target_duration=30.0,
                model="qwen-plus-latest",
                base_url="https://example.test",
                context_packet={},
            )

        self.assertIsNone(result)

    def test_generate_voiceover_with_llm_calls_dashscope_provider(self):
        from video_slicer.script_generation import generate_voiceover_with_llm

        response_json = json.dumps({
            "title": "标题",
            "summary": "概括",
            "story_plan": [],
            "voiceover": [
                {
                    "text": "主角走进房间，冲突已经开始。",
                    "source_segment_ids": [1],
                    "context_refs": [],
                    "story_role": "hook",
                    "confidence": 0.8,
                    "visual_note": "进门画面",
                }
            ],
            "evidence_notes": [],
        }, ensure_ascii=False)
        with patch.dict("os.environ", {"DASHSCOPE_API_KEY": "sk-test"}, clear=False):
            with patch("llm_providers.dashscope.text_completion", return_value=response_json) as mocked_completion:
                result = generate_voiceover_with_llm(
                    segments=[{"id": 1, "start": 0.0, "end": 1.0, "speaker": "UNKNOWN", "text": "一句字幕"}],
                    target_duration=30.0,
                    model="qwen-plus-latest",
                    base_url="https://example.test",
                    context_packet={"correct_synopsis": "只允许使用已知剧情。"},
                )

        self.assertEqual(result["voiceover"][0]["source_segment_ids"], [1])
        mocked_completion.assert_called_once()
        kwargs = mocked_completion.call_args.kwargs
        self.assertEqual(kwargs["model"], "qwen-plus-latest")
        self.assertEqual(kwargs["base_url"], "https://example.test")
        self.assertEqual(kwargs["api_key"], "sk-test")

    def test_review_voiceover_with_llm_marks_reviewed(self):
        from video_slicer.script_generation import review_voiceover_with_llm

        response_json = json.dumps({
            "title": "标题",
            "summary": "概括",
            "voiceover": [{"text": "主角语气平静。", "source_segment_ids": [1]}],
            "review_notes": ["修正口播"],
            "read_aloud_checks": ["无英文"],
        }, ensure_ascii=False)
        with patch.dict("os.environ", {"DASHSCOPE_API_KEY": "sk-test"}, clear=False):
            with patch("llm_providers.dashscope.text_completion", return_value=response_json):
                result = review_voiceover_with_llm(
                    voiceover_doc={"voiceover": [{"text": "主角说得平。", "source_segment_ids": [1]}]},
                    segments=[{"id": 1, "start": 0.0, "end": 1.0, "speaker": "UNKNOWN", "text": "字幕"}],
                    target_duration=30.0,
                    model="qwen-plus-latest",
                    base_url="https://example.test",
                    context_packet={},
                )

        self.assertTrue(result["reviewed"])
        self.assertEqual(result["review_model"], "qwen-plus-latest")

    def test_humanize_voiceover_rejects_unsafe_rows_and_keeps_original(self):
        from video_slicer.script_generation import humanize_voiceover_with_llm

        response_json = json.dumps({
            "humanize_notes": ["尝试润色"],
            "humanized_voiceover": [{"index": 1, "text": "他说得平，但意思很清楚。"}],
        }, ensure_ascii=False)
        original = {
            "title": "标题",
            "summary": "概括",
            "voiceover": [{"text": "他语气平静，意思很清楚。", "source_segment_ids": [1]}],
        }
        with patch.dict("os.environ", {"DASHSCOPE_API_KEY": "sk-test"}, clear=False):
            with patch("llm_providers.dashscope.text_completion", return_value=response_json):
                result = humanize_voiceover_with_llm(
                    voiceover_doc=original,
                    target_duration=30.0,
                    model="qwen-plus-latest",
                    base_url="https://example.test",
                    context_packet={},
                )

        self.assertEqual(result["voiceover"][0]["text"], "他语气平静，意思很清楚。")
        self.assertTrue(result["humanized"])
        self.assertIn("自动丢弃不可靠润色句", result["humanize_notes"][-1])

    def test_write_humanize_diff_writes_changed_lines(self):
        from tempfile import TemporaryDirectory

        from video_slicer.script_generation import write_humanize_diff

        before = {"voiceover": [{"text": "原句。"}]}
        after = {"voiceover": [{"text": "润色句。"}]}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "voiceover_humanize_diff.txt"
            write_humanize_diff(before, after, path)
            text = path.read_text(encoding="utf-8")

        self.assertIn("原文：原句。", text)
        self.assertIn("润色：润色句。", text)

    def test_write_voiceover_outputs_writes_json_text_and_srt(self):
        from tempfile import TemporaryDirectory

        from video_slicer.script_generation import write_voiceover_outputs

        voiceover_doc = {"title": "标题", "summary": "概括", "voiceover": []}
        alignment = [
            {
                "text": "第一句。",
                "estimated_voiceover_start": 0.0,
                "estimated_voiceover_end": 1.2,
            },
            {
                "text": "第二句。",
                "voiceover_start": 1.2,
                "voiceover_end": 2.5,
                "estimated_voiceover_start": 1.2,
                "estimated_voiceover_end": 2.5,
            },
        ]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            script_json_path = root / "voiceover_script.json"
            script_txt_path = root / "voiceover_script.txt"
            voiceover_srt_path = root / "voiceover.srt"
            write_voiceover_outputs(
                voiceover_doc,
                alignment,
                script_json_path,
                script_txt_path,
                voiceover_srt_path,
            )

            script_json = json.loads(script_json_path.read_text(encoding="utf-8"))
            script_txt = script_txt_path.read_text(encoding="utf-8")
            srt_text = voiceover_srt_path.read_text(encoding="utf-8")

        self.assertEqual(script_json["voiceover"][1]["text"], "第二句。")
        self.assertIn("# 标题", script_txt)
        self.assertIn("第一句。", script_txt)
        self.assertIn("00:00:01,200 --> 00:00:02,500", srt_text)


if __name__ == "__main__":
    unittest.main()
