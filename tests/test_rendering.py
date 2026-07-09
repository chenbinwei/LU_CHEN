import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from video_slicer.rendering import (
    ensure_ffmpeg,
    ffprobe_duration,
    ffprobe_duration_media,
    run,
    run_capture,
)


class RenderingCommandTest(unittest.TestCase):
    def test_run_calls_subprocess_with_optional_cwd(self):
        with patch("video_slicer.rendering.subprocess.run") as mocked_run:
            run(["ffmpeg", "-version"], cwd=Path("outputs"))

        mocked_run.assert_called_once_with(["ffmpeg", "-version"], cwd=Path("outputs"), check=True)

    def test_run_capture_returns_stripped_stdout(self):
        completed = subprocess.CompletedProcess(args=["ffprobe"], returncode=0, stdout="12.345\n", stderr="")
        with patch("video_slicer.rendering.subprocess.run", return_value=completed) as mocked_run:
            result = run_capture(["ffprobe"])

        self.assertEqual(result, "12.345")
        mocked_run.assert_called_once_with(["ffprobe"], check=True, capture_output=True, text=True)

    def test_run_capture_includes_process_detail_on_failure(self):
        error = subprocess.CalledProcessError(
            returncode=2,
            cmd=["ffprobe", "missing.mp4"],
            stderr="missing file",
        )
        with patch("video_slicer.rendering.subprocess.run", side_effect=error):
            with self.assertRaises(SystemExit) as ctx:
                run_capture(["ffprobe", "missing.mp4"])

        self.assertIn("missing file", str(ctx.exception))
        self.assertIn("ffprobe missing.mp4", str(ctx.exception))

    def test_ensure_ffmpeg_checks_ffmpeg_and_ffprobe(self):
        with patch("video_slicer.rendering.subprocess.run") as mocked_run:
            ensure_ffmpeg()

        self.assertEqual(mocked_run.call_count, 2)
        self.assertEqual(mocked_run.call_args_list[0].args[0], ["ffmpeg", "-version"])
        self.assertEqual(mocked_run.call_args_list[1].args[0], ["ffprobe", "-version"])

    def test_ffprobe_duration_media_parses_duration(self):
        media_path = Path("outputs/output.mp4")
        with patch("video_slicer.rendering.run_capture", return_value="90.004") as mocked_capture:
            duration = ffprobe_duration_media(media_path)

        self.assertEqual(duration, 90.004)
        mocked_capture.assert_called_once_with([
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ])

    def test_ffprobe_duration_delegates_to_media_duration(self):
        video_path = Path("videos/input.mp4")
        with patch("video_slicer.rendering.ffprobe_duration_media", return_value=12.5) as mocked_duration:
            duration = ffprobe_duration(video_path)

        self.assertEqual(duration, 12.5)
        mocked_duration.assert_called_once_with(video_path)

    def test_clip_video_silent_writes_concat_list_and_runs_expected_commands(self):
        from tempfile import TemporaryDirectory

        from video_slicer.rendering import clip_video_silent

        clips = [
            {"id": 1, "source_start": 10.0, "duration": 3.5},
            {"id": 2, "source_start": 20.25, "duration": 4.0},
        ]
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with patch("video_slicer.rendering.run") as mocked_run:
                output_path = clip_video_silent(Path("videos/input.mp4"), output_dir, clips)

            self.assertEqual(output_path, output_dir / "output.mp4")
            self.assertEqual(mocked_run.call_count, 3)
            first_cmd = mocked_run.call_args_list[0].args[0]
            self.assertEqual(
                first_cmd[:8],
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    "10.000",
                    "-i",
                    str(Path("videos/input.mp4")),
                    "-t",
                    "3.500",
                ],
            )
            self.assertIn("-an", first_cmd)
            concat_list = output_dir / "concat_list.txt"
            concat_text = concat_list.read_text(encoding="utf-8")
            self.assertIn("clip_001.mp4", concat_text)
            self.assertIn("clip_002.mp4", concat_text)

    def test_write_visual_time_mapping_writes_new_timeline(self):
        from tempfile import TemporaryDirectory

        from video_slicer.rendering import write_visual_time_mapping

        clips = [
            {
                "id": 1,
                "sentence_ids": [1],
                "source_segment_ids": [10],
                "source_start": 5.0,
                "source_end": 8.0,
                "duration": 3.0,
            },
            {
                "id": 2,
                "sentence_ids": [2],
                "source_segment_ids": [11],
                "source_start": 12.0,
                "source_end": 16.0,
                "duration": 4.0,
            },
        ]
        with TemporaryDirectory() as tmp:
            mapping_path = Path(tmp) / "time_mapping.json"
            write_visual_time_mapping(clips, mapping_path)

            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))

        self.assertEqual(mapping[0]["new_start"], 0.0)
        self.assertEqual(mapping[0]["new_end"], 3.0)
        self.assertEqual(mapping[1]["new_start"], 3.0)
        self.assertEqual(mapping[1]["new_end"], 7.0)
        self.assertEqual(mapping[1]["source_segment_ids"], [11])

    def test_render_clips_with_voiceover_requires_audio_path(self):
        from tempfile import TemporaryDirectory

        from video_slicer.rendering import render_clips_with_voiceover

        with TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                render_clips_with_voiceover(
                    Path("videos/input.mp4"),
                    Path(tmp),
                    [{"id": 1, "source_start": 0.0, "duration": 2.0}],
                )

        self.assertIn("missing voiceover_audio_path", str(ctx.exception))

    def test_render_clips_with_voiceover_writes_final_concat(self):
        from tempfile import TemporaryDirectory

        from video_slicer.rendering import render_clips_with_voiceover

        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            audio_path = output_dir / "voice_001.mp3"
            audio_path.write_bytes(b"fake audio")
            clips = [{"id": 1, "source_start": 2.0, "duration": 3.0, "voiceover_audio_path": str(audio_path)}]
            with patch("video_slicer.rendering.run") as mocked_run:
                output_path = render_clips_with_voiceover(Path("videos/input.mp4"), output_dir, clips)

            self.assertEqual(output_path, output_dir / "final_with_voiceover.mp4")
            self.assertEqual(mocked_run.call_count, 2)
            first_cmd = mocked_run.call_args_list[0].args[0]
            self.assertIn(str(audio_path), first_cmd)
            self.assertIn("-shortest", first_cmd)
            concat_text = (output_dir / "final_concat_list.txt").read_text(encoding="utf-8")
            self.assertIn("part_001.mp4", concat_text)

    def test_mux_voiceover_audio_checks_audio_exists_and_runs_mux(self):
        from tempfile import TemporaryDirectory

        from video_slicer.rendering import mux_voiceover_audio

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio_path = root / "voiceover.mp3"
            audio_path.write_bytes(b"fake audio")
            output_path = root / "final.mp4"
            with patch("video_slicer.rendering.run") as mocked_run:
                mux_voiceover_audio(Path("output.mp4"), audio_path, output_path)

        cmd = mocked_run.call_args.args[0]
        self.assertEqual(cmd[:4], ["ffmpeg", "-y", "-i", "output.mp4"])
        self.assertIn(str(audio_path), cmd)
        self.assertIn(str(output_path), cmd)

    def test_validate_final_duration_rejects_target_drift(self):
        from video_slicer.rendering import validate_final_duration

        with patch("video_slicer.rendering.ffprobe_duration_media", return_value=104.0):
            with self.assertRaises(SystemExit) as ctx:
                validate_final_duration(Path("final.mp4"), target_duration=120.0, tolerance=3.0, label="Final")

        self.assertIn("outside tolerance", str(ctx.exception))

    def test_validate_final_duration_returns_duration_when_inside_tolerance(self):
        from video_slicer.rendering import validate_final_duration

        with patch("video_slicer.rendering.ffprobe_duration_media", return_value=119.5):
            duration = validate_final_duration(Path("final.mp4"), target_duration=120.0, tolerance=3.0, label="Final")

        self.assertEqual(duration, 119.5)

    def test_burn_subtitles_escapes_subtitle_path_for_filter(self):
        from video_slicer.rendering import burn_subtitles

        with patch("video_slicer.rendering.run") as mocked_run:
            burn_subtitles(Path("input.mp4"), Path("outputs/subtitle's.srt"), Path("burned.mp4"))

        cmd = mocked_run.call_args.args[0]
        self.assertEqual(cmd[:4], ["ffmpeg", "-y", "-i", "input.mp4"])
        self.assertIn("subtitles='outputs/subtitle\\'s.srt'", cmd)

    def test_add_background_music_validates_non_negative_values(self):
        from tempfile import TemporaryDirectory

        from video_slicer.rendering import add_background_music

        with TemporaryDirectory() as tmp:
            bgm_path = Path(tmp) / "bgm.mp3"
            bgm_path.write_bytes(b"fake bgm")
            with self.assertRaises(SystemExit) as ctx:
                add_background_music(
                    video_path=Path("final.mp4"),
                    bgm_audio=bgm_path,
                    output_path=Path("mixed.mp4"),
                    bgm_volume=-0.1,
                    voiceover_volume=1.0,
                    bgm_start=0.0,
                    bgm_fade_in=0.0,
                    bgm_fade_out=2.5,
                )

        self.assertIn("--bgm-volume", str(ctx.exception))

    def test_add_background_music_builds_filter_with_loop_and_fades(self):
        from tempfile import TemporaryDirectory

        from video_slicer.rendering import add_background_music

        with TemporaryDirectory() as tmp:
            bgm_path = Path(tmp) / "bgm.mp3"
            bgm_path.write_bytes(b"fake bgm")
            with patch("video_slicer.rendering.ffprobe_duration_media", return_value=90.0):
                with patch("video_slicer.rendering.run") as mocked_run:
                    add_background_music(
                        video_path=Path("final_with_voiceover.mp4"),
                        bgm_audio=bgm_path,
                        output_path=Path("final_with_bgm.mp4"),
                        bgm_volume=0.25,
                        voiceover_volume=1.0,
                        bgm_start=1.5,
                        bgm_fade_in=0.8,
                        bgm_fade_out=2.5,
                    )

        cmd = mocked_run.call_args.args[0]
        self.assertIn("-stream_loop", cmd)
        self.assertIn("-1", cmd)
        self.assertIn("1.500", cmd)
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("volume=1.000[voice]", filter_complex)
        self.assertIn("atrim=0:90.000", filter_complex)
        self.assertIn("afade=t=in:st=0:d=0.800", filter_complex)
        self.assertIn("afade=t=out:st=87.500:d=2.500", filter_complex)
        self.assertIn("volume=0.250", filter_complex)


if __name__ == "__main__":
    unittest.main()
