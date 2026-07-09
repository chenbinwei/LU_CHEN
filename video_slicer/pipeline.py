import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from video_slicer.alignment import (
    align_voiceover_to_transcript,
    apply_estimated_voiceover_timeline,
    build_clips_from_alignment,
    limit_alignment_to_target_duration,
    refresh_voiceover_timeline,
)
from video_slicer.context_packet import load_context_packet
from video_slicer.pipeline_records import begin_pipeline_record_session
from video_slicer.quality_report import build_quality_report, write_quality_report
from video_slicer.rendering import (
    add_background_music,
    burn_subtitles,
    clip_video_silent,
    ensure_ffmpeg,
    ffprobe_duration,
    ffprobe_duration_media,
    mux_voiceover_audio,
    render_clips_with_voiceover,
    run,
    run_capture,
    validate_final_duration,
    write_visual_time_mapping,
)
from video_slicer.script_generation import (
    fallback_voiceover_script,
    generate_voiceover_with_llm,
    humanize_voiceover_with_llm,
    parse_llm_json_response,
    review_voiceover_with_llm,
    validate_voiceover_doc,
    write_humanize_diff,
    write_srt,
    write_voiceover_outputs,
)

DEFAULT_INPUT = "videos/input.mp4"
DEFAULT_OUTPUT_DIR = "outputs"
DEFAULT_CONTEXT_PATH = "context.json"
DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/api/v1"
DEFAULT_DASHSCOPE_MODEL = "qwen-plus-latest"
DEFAULT_OCOOL_BASE_URL = "https://one.ocoolai.com/v1"
DEFAULT_OCOOL_MODEL = "qwen-plus-latest"
DEFAULT_FISH_BASE_URL = "https://api.fish.audio"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def extract_audio(video_path: Path, audio_path: Path, force: bool) -> None:
    if audio_path.exists() and not force:
        print(f"Audio exists, skip extraction: {audio_path}")
        return
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(audio_path),
    ])


def transcribe_audio(
    audio_path: Path,
    transcript_path: Path,
    srt_path: Path,
    model_size: str,
    device: str,
    compute_type: str,
    language: str | None,
    force: bool,
) -> list[dict[str, Any]]:
    if transcript_path.exists() and not force:
        print(f"Transcript exists, skip transcription: {transcript_path}")
        data = json.loads(transcript_path.read_text(encoding="utf-8"))
        return data["segments"]

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "faster-whisper is not installed. Run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from exc

    print(f"Loading Whisper model: {model_size} ({device}, {compute_type})")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
        word_timestamps=False,
    )

    segments: list[dict[str, Any]] = []
    for idx, segment in enumerate(segments_iter, start=1):
        text = " ".join(segment.text.strip().split())
        if not text:
            continue
        segments.append({
            "id": idx,
            "start": round(float(segment.start), 3),
            "end": round(float(segment.end), 3),
            "speaker": "UNKNOWN",
            "text": text,
        })

    transcript = {
        "source_audio": str(audio_path),
        "language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "segments": segments,
    }
    transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    write_srt(segments, srt_path)
    print(f"Wrote transcript: {transcript_path}")
    print(f"Wrote raw subtitles: {srt_path}")
    return segments


def select_clips_with_llm(
    segments: list[dict[str, Any]],
    target_duration: float,
    video_duration: float,
    model: str,
    base_url: str,
) -> dict[str, Any] | None:
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("DASHSCOPE_API_KEY is empty. Using rule-based clip selection.")
        return None

    payload = {
        "target_duration_seconds": target_duration,
        "video_duration_seconds": video_duration,
        "segments": segments,
    }
    instructions = """
You are a video editing assistant. Select the most valuable source transcript segments for a concise highlight video.
Return JSON only. Do not invent timestamps. Use only segment ids and boundaries from the transcript.
The total selected duration should be close to but not greater than the target duration when possible.
Prefer coherent consecutive ranges, remove filler/repetition, and keep chronological order.
JSON schema:
{
  "summary": "short summary of the selected story",
  "clips": [
    {
      "segment_ids": [1, 2, 3],
      "source_start": 12.34,
      "source_end": 45.67,
      "reason": "why this range is kept"
    }
  ]
}
""".strip()
    prompt = (
        "Select clips from this transcript. The transcript is JSON. "
        "Return only the JSON object described in the instructions.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )

    print(f"Calling DashScope model: {model}")
    from llm_providers.dashscope import text_completion

    text = text_completion(
        model=model,
        instructions=instructions,
        input_text=prompt,
        base_url=base_url,
        api_key=api_key,
    )
    return parse_llm_json_response(text, model=model, base_url=base_url, api_key=api_key)


def select_clips_rule_based(segments: list[dict[str, Any]], target_duration: float) -> dict[str, Any]:
    clips: list[dict[str, Any]] = []
    current_ids: list[int] = []
    current_start: float | None = None
    current_end: float | None = None
    total = 0.0

    for seg in segments:
        start = float(seg["start"])
        end = float(seg["end"])
        if end <= start:
            continue
        if total >= target_duration:
            break
        if current_start is None:
            current_start = start
        gap = 0.0 if current_end is None else start - current_end
        would_split = gap > 1.8 or (current_end is not None and end - current_start > 45.0)
        if would_split and current_ids:
            clips.append({
                "segment_ids": current_ids,
                "source_start": current_start,
                "source_end": current_end,
                "reason": "Rule-based selection: keep informative transcript in chronological order.",
            })
            total += float(current_end) - float(current_start)
            current_ids = []
            current_start = start
        current_ids.append(int(seg["id"]))
        current_end = end

    if current_ids and current_start is not None and current_end is not None and total < target_duration:
        clips.append({
            "segment_ids": current_ids,
            "source_start": current_start,
            "source_end": current_end,
            "reason": "Rule-based selection: keep informative transcript in chronological order.",
        })

    return {
        "summary": "Rule-based fallback selection. Add DASHSCOPE_API_KEY for semantic clip selection.",
        "clips": clips,
    }


def normalize_clips(selection: dict[str, Any], video_duration: float, padding: float) -> list[dict[str, Any]]:
    raw_clips = selection.get("clips", [])
    clips: list[dict[str, Any]] = []
    for idx, clip in enumerate(raw_clips, start=1):
        start = max(0.0, float(clip["source_start"]) - padding)
        end = min(video_duration, float(clip["source_end"]) + padding)
        if end - start < 0.25:
            continue
        clips.append({
            "id": idx,
            "segment_ids": clip.get("segment_ids", []),
            "source_start": round(start, 3),
            "source_end": round(end, 3),
            "reason": clip.get("reason", ""),
        })

    clips.sort(key=lambda item: item["source_start"])
    merged: list[dict[str, Any]] = []
    for clip in clips:
        if not merged or clip["source_start"] > merged[-1]["source_end"] + 0.4:
            merged.append(clip)
            continue
        merged[-1]["source_end"] = max(merged[-1]["source_end"], clip["source_end"])
        merged[-1]["segment_ids"] = sorted(set(merged[-1].get("segment_ids", []) + clip.get("segment_ids", [])))
        if clip.get("reason"):
            merged[-1]["reason"] = (merged[-1].get("reason", "") + " " + clip["reason"]).strip()

    for idx, clip in enumerate(merged, start=1):
        clip["id"] = idx
        clip["duration"] = round(float(clip["source_end"]) - float(clip["source_start"]), 3)
    return merged


def clip_video(video_path: Path, output_dir: Path, clips: list[dict[str, Any]]) -> Path:
    clips_dir = output_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clip_files: list[Path] = []

    for clip in clips:
        clip_path = clips_dir / f"clip_{clip['id']:03}.mp4"
        start = f"{clip['source_start']:.3f}"
        duration = f"{clip['duration']:.3f}"
        run([
            "ffmpeg",
            "-y",
            "-ss",
            start,
            "-i",
            str(video_path),
            "-t",
            duration,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(clip_path),
        ])
        clip_files.append(clip_path)

    concat_list = output_dir / "concat_list.txt"
    concat_lines = [f"file '{path.resolve().as_posix()}'" for path in clip_files]
    concat_list.write_text("\n".join(concat_lines), encoding="utf-8")

    output_path = output_dir / "output.mp4"
    run([
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-c",
        "copy",
        str(output_path),
    ])
    return output_path


def remap_subtitles(
    segments: list[dict[str, Any]],
    clips: list[dict[str, Any]],
    subtitle_path: Path,
    mapping_path: Path,
) -> None:
    new_segments: list[dict[str, Any]] = []
    mapping: list[dict[str, Any]] = []
    cursor = 0.0
    next_id = 1

    for clip in clips:
        source_start = float(clip["source_start"])
        source_end = float(clip["source_end"])
        new_start = cursor
        new_end = cursor + source_end - source_start
        mapping.append({
            "clip_id": clip["id"],
            "source_start": round(source_start, 3),
            "source_end": round(source_end, 3),
            "new_start": round(new_start, 3),
            "new_end": round(new_end, 3),
        })
        for seg in segments:
            seg_start = float(seg["start"])
            seg_end = float(seg["end"])
            overlap_start = max(seg_start, source_start)
            overlap_end = min(seg_end, source_end)
            if overlap_end - overlap_start < 0.15:
                continue
            new_segments.append({
                "id": next_id,
                "start": round(cursor + overlap_start - source_start, 3),
                "end": round(cursor + overlap_end - source_start, 3),
                "speaker": seg.get("speaker", "UNKNOWN"),
                "text": seg["text"],
                "source_segment_id": seg["id"],
            })
            next_id += 1
        cursor = new_end

    write_srt(new_segments, subtitle_path)
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_sentence_audio(
    alignment: list[dict[str, Any]],
    output_dir: Path,
    tts_mode: str,
    ocool_tts_model: str,
    ocool_tts_voice: str,
    ocool_tts_speed: float,
    fish_tts_model: str,
    fish_reference_id: str,
    fish_base_url: str,
    fish_tts_speed: float,
    fish_tts_volume: float,
    fish_tts_latency: str,
    force: bool,
    base_url: str,
) -> list[dict[str, Any]]:
    if tts_mode not in {"ocool", "fish"}:
        raise SystemExit(f"Unsupported TTS mode for sentence audio: {tts_mode}")

    audio_dir = output_dir / "voiceover_clips"
    audio_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = audio_dir / "tts_manifest.json"
    suffix = ".mp3"

    previous_items: list[dict[str, Any]] = []
    if metadata_path.exists() and not force:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
            previous_items = metadata.get("items", [])
        except Exception:
            previous_items = []
    previous_by_id = {int(item.get("sentence_id", -1)): item for item in previous_items if isinstance(item, dict)}

    expected_items: list[dict[str, Any]] = []
    batch_items: list[dict[str, Any]] = []
    for row in alignment:
        sentence_id = int(row["sentence_id"])
        audio_path = audio_dir / f"voice_{sentence_id:03d}{suffix}"
        if tts_mode == "fish":
            model_value = fish_tts_model
            voice_value = fish_reference_id
            speed_value = fish_tts_speed
        else:
            model_value = ocool_tts_model
            voice_value = ocool_tts_voice
            speed_value = ocool_tts_speed

        item = {
            "sentence_id": sentence_id,
            "text": row["text"],
            "audio_path": str(audio_path),
            "engine": tts_mode,
            "model": model_value,
            "voice": voice_value,
            "speed": speed_value,
        }
        expected_items.append(item)
        previous = previous_by_id.get(sentence_id)
        needs_generation = (
            force
            or not audio_path.exists()
            or not previous
            or previous.get("text") != item["text"]
            or previous.get("audio_path") != item["audio_path"]
            or previous.get("engine") != item["engine"]
            or previous.get("model") != item["model"]
            or previous.get("voice") != item["voice"]
            or previous.get("speed") != item["speed"]
        )
        if needs_generation:
            batch_items.append(item)

    if batch_items:
        if tts_mode == "ocool":
            from tts_providers.ocool import synthesize_batch

            print(f"Generating {len(batch_items)} sentence voiceover files with OCool TTS.")
            synthesize_batch(
                batch_items,
                model=ocool_tts_model,
                voice=ocool_tts_voice,
                base_url=base_url,
                speed=ocool_tts_speed,
            )
        else:
            from tts_providers.fish import synthesize_batch

            print(f"Generating {len(batch_items)} sentence voiceover files with Fish Audio TTS.")
            synthesize_batch(
                batch_items,
                reference_id=fish_reference_id,
                model=fish_tts_model,
                base_url=fish_base_url,
                speed=fish_tts_speed,
                volume=fish_tts_volume,
                latency=fish_tts_latency,
            )
    else:
        print("Sentence voiceover files exist, skip TTS generation.")

    metadata_path.write_text(
        json.dumps({"engine": tts_mode, "items": expected_items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for row in alignment:
        expected = next(item for item in expected_items if int(item["sentence_id"]) == int(row["sentence_id"]))
        audio_path = Path(expected["audio_path"])
        if not audio_path.exists():
            raise SystemExit(f"TTS audio file was not generated: {audio_path}")
        duration = ffprobe_duration_media(audio_path)
        row["voiceover_audio_path"] = str(audio_path)
        row["voiceover_duration"] = round(duration, 3)
        row["voiceover_start"] = 0.0
        row["voiceover_end"] = 0.0
        row["tts_mode"] = tts_mode

    return refresh_voiceover_timeline(alignment)


def atempo_filter_for_ratio(tempo: float) -> str:
    if tempo <= 0:
        raise SystemExit("Audio tempo ratio must be greater than 0.")
    parts: list[float] = []
    remaining = float(tempo)
    while remaining < 0.5:
        parts.append(0.5)
        remaining /= 0.5
    while remaining > 2.0:
        parts.append(2.0)
        remaining /= 2.0
    parts.append(remaining)
    return ",".join(f"atempo={part:.6g}" for part in parts)


def fit_alignment_audio_to_target_duration(
    alignment: list[dict[str, Any]],
    output_dir: Path,
    target_duration: float,
    tolerance: float,
    force: bool,
) -> list[dict[str, Any]]:
    if not alignment or target_duration <= 0:
        return refresh_voiceover_timeline(alignment)

    current_total = sum(float(row["voiceover_duration"]) for row in alignment)
    delta = current_total - target_duration
    if abs(delta) <= tolerance:
        print(
            f"Voiceover duration already near target: "
            f"{current_total:.2f}s vs {target_duration:.2f}s."
        )
        return refresh_voiceover_timeline(alignment)

    if current_total <= 0:
        raise SystemExit("Cannot fit duration: total voiceover duration is zero.")
    tempo = current_total / target_duration
    filter_value = atempo_filter_for_ratio(tempo)
    fitted_dir = output_dir / "voiceover_fitted"
    fitted_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = fitted_dir / "fit_manifest.json"

    print(
        f"Fitting voiceover duration from {current_total:.2f}s to "
        f"{target_duration:.2f}s with tempo ratio {tempo:.3f}."
    )
    if tempo < 0.65 or tempo > 1.25:
        print(
            "Warning: large duration adjustment may make narration sound less natural. "
            "Consider generating a longer/shorter script for production quality."
        )

    fitted_items: list[dict[str, Any]] = []
    for row in alignment:
        source_value = row.get("voiceover_audio_path")
        if not source_value:
            raise SystemExit("Cannot fit duration: a voiceover row is missing voiceover_audio_path.")
        source_path = Path(str(source_value))
        if not source_path.exists():
            raise SystemExit(f"Voiceover audio not found: {source_path}")

        sentence_id = int(row["sentence_id"])
        fitted_path = fitted_dir / f"voice_{sentence_id:03d}.mp3"
        source_duration = ffprobe_duration_media(source_path)
        needs_fit = force or not fitted_path.exists()
        if not needs_fit and fitted_path.stat().st_mtime < source_path.stat().st_mtime:
            needs_fit = True
        if not needs_fit:
            try:
                fitted_duration = ffprobe_duration_media(fitted_path)
                expected_duration = source_duration / tempo
                needs_fit = abs(fitted_duration - expected_duration) > 0.35
            except Exception:
                needs_fit = True

        if needs_fit:
            run([
                "ffmpeg",
                "-y",
                "-i",
                str(source_path),
                "-vn",
                "-filter:a",
                filter_value,
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "2",
                str(fitted_path),
            ])

        fitted_duration = ffprobe_duration_media(fitted_path)
        row["original_voiceover_audio_path"] = str(source_path)
        row["original_voiceover_duration"] = round(source_duration, 3)
        row["voiceover_audio_path"] = str(fitted_path)
        row["voiceover_duration"] = round(fitted_duration, 3)
        row["duration_fit_tempo"] = round(tempo, 6)
        fitted_items.append({
            "sentence_id": sentence_id,
            "source_audio_path": str(source_path),
            "fitted_audio_path": str(fitted_path),
            "source_duration": round(source_duration, 3),
            "fitted_duration": round(fitted_duration, 3),
        })

    fitted_total = sum(float(row["voiceover_duration"]) for row in alignment)
    manifest_path.write_text(
        json.dumps(
            {
                "target_duration": target_duration,
                "tolerance": tolerance,
                "source_total_duration": round(current_total, 3),
                "fitted_total_duration": round(fitted_total, 3),
                "tempo": round(tempo, 6),
                "filter": filter_value,
                "items": fitted_items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Fitted voiceover duration: {fitted_total:.2f}s.")
    return refresh_voiceover_timeline(alignment)


def validate_requested_target_duration(target_duration: float, video_duration: float) -> None:
    if target_duration <= 0:
        raise SystemExit("Target duration must be greater than 0 seconds.")
    if video_duration <= 0:
        raise SystemExit("Source video duration must be greater than 0 seconds.")
    if target_duration >= video_duration:
        raise SystemExit(
            f"Target duration must be shorter than source video duration: "
            f"{target_duration:.2f}s target vs {video_duration:.2f}s source."
        )


def validate_timeline_duration(
    *,
    target_duration: float,
    tolerance: float,
    actual_voiceover_duration: float,
    actual_visual_duration: float,
) -> None:
    if target_duration <= 0:
        raise SystemExit("Target duration must be greater than 0 seconds.")
    safe_tolerance = max(0.0, tolerance)
    visual_delta = abs(actual_visual_duration - target_duration)
    if visual_delta > safe_tolerance:
        raise SystemExit(
            f"Visual timeline duration is outside tolerance: "
            f"{actual_visual_duration:.2f}s vs {target_duration:.2f}s target "
            f"(tolerance {safe_tolerance:.2f}s)."
        )
    voiceover_delta = abs(actual_voiceover_duration - target_duration)
    if voiceover_delta > safe_tolerance:
        raise SystemExit(
            f"Voiceover duration is outside tolerance: "
            f"{actual_voiceover_duration:.2f}s vs {target_duration:.2f}s target "
            f"(tolerance {safe_tolerance:.2f}s)."
        )
    voice_visual_delta = abs(actual_voiceover_duration - actual_visual_duration)
    mismatch_tolerance = max(0.5, safe_tolerance)
    if voice_visual_delta > mismatch_tolerance:
        raise SystemExit(
            f"Voiceover and visual timeline durations do not match: "
            f"{actual_voiceover_duration:.2f}s voiceover vs {actual_visual_duration:.2f}s visual "
            f"(tolerance {mismatch_tolerance:.2f}s)."
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Voiceover-first video slicing demo: script -> transcript alignment -> real TTS duration -> final narrated cut.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Input video path.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory.")
    parser.add_argument("--record-project", action="store_true", help="Write local project/version/job records under --project-root.")
    parser.add_argument("--project-root", default=os.environ.get("PROJECT_ROOT", "projects.local"), help="Local project data root used with --record-project.")
    parser.add_argument("--project-id", default="", help="Existing or desired project id used with --record-project.")
    parser.add_argument("--version-id", default="", help="Existing or desired version id used with --record-project.")
    parser.add_argument("--context", default=DEFAULT_CONTEXT_PATH, help="Optional context packet JSON path. Use this to provide title, people, background, and story constraints.")
    parser.add_argument("--target-duration", type=float, default=120.0, help="Target voiceover/video duration in seconds.")
    parser.add_argument("--duration-tolerance", type=float, default=float(os.environ.get("DURATION_TOLERANCE", "3.0")), help="Allowed final duration drift in seconds.")
    parser.add_argument("--no-fit-duration", action="store_true", help="Disable automatic audio time-stretching to match --target-duration.")
    parser.add_argument("--model-size", default="small", help="faster-whisper model size: tiny/base/small/medium/large-v3.")
    parser.add_argument("--device", default="cpu", help="Whisper device: cpu or cuda.")
    parser.add_argument("--compute-type", default="int8", help="Whisper compute type, e.g. int8, float16.")
    parser.add_argument("--language", default=None, help="Optional speech language, e.g. zh, en. Default: auto detect.")
    parser.add_argument("--dashscope-base-url", default=os.environ.get("DASHSCOPE_BASE_URL", DEFAULT_DASHSCOPE_BASE_URL), help="DashScope official API base URL for script generation.")
    parser.add_argument("--dashscope-model", "--ocool-model", dest="dashscope_model", default=os.environ.get("DASHSCOPE_MODEL", DEFAULT_DASHSCOPE_MODEL), help="DashScope model used for script generation. --ocool-model is kept as a legacy alias.")
    parser.add_argument("--dashscope-humanize-model", "--ocool-humanize-model", dest="dashscope_humanize_model", default=os.environ.get("DASHSCOPE_HUMANIZE_MODEL", DEFAULT_DASHSCOPE_MODEL), help="DashScope model used only for human-style voiceover polish. --ocool-humanize-model is kept as a legacy alias.")
    parser.add_argument("--ocool-base-url", default=os.environ.get("OCOOL_BASE_URL", DEFAULT_OCOOL_BASE_URL), help="OCool/OpenAI-compatible base URL used only when --tts-mode ocool.")
    parser.add_argument("--padding", type=float, default=0.25, help="Seconds to pad matched source visual clips.")
    parser.add_argument("--tts-mode", choices=["ocool", "fish", "none"], default=os.environ.get("TTS_MODE", "ocool"), help="Generate per-sentence voiceover. Use 'ocool' or 'fish' for API TTS, or 'none' for script/silent preview only.")
    parser.add_argument("--ocool-tts-model", default=os.environ.get("OCOOL_TTS_MODEL", "tts-1-hd"), help="OpenAI-compatible TTS model for --tts-mode ocool.")
    parser.add_argument("--ocool-tts-voice", default=os.environ.get("OCOOL_TTS_VOICE", "echo"), help="OpenAI-compatible TTS voice for --tts-mode ocool.")
    parser.add_argument("--fish-base-url", default=os.environ.get("FISH_BASE_URL", DEFAULT_FISH_BASE_URL), help="Fish Audio API base URL.")
    parser.add_argument("--fish-tts-model", default=os.environ.get("FISH_TTS_MODEL", "s2.1-pro-free"), help="Fish Audio TTS model.")
    parser.add_argument("--fish-reference-id", default=os.environ.get("FISH_REFERENCE_ID", ""), help="Fish Audio voice model id for cloned voice.")
    parser.add_argument("--fish-tts-speed", type=float, default=float(os.environ.get("FISH_TTS_SPEED", "1.0")), help="Fish Audio prosody speed.")
    parser.add_argument("--fish-tts-volume", type=float, default=float(os.environ.get("FISH_TTS_VOLUME", "0")), help="Fish Audio prosody volume.")
    parser.add_argument("--fish-tts-latency", default=os.environ.get("FISH_TTS_LATENCY", "normal"), choices=["normal", "balanced", "low"], help="Fish Audio latency-quality mode.")
    parser.add_argument("--fish-create-model", action="store_true", help="Create a Fish Audio private voice model from reference audio and exit.")
    parser.add_argument("--fish-reference-audio", action="append", default=[], help="Reference audio path for --fish-create-model. Can be passed multiple times.")
    parser.add_argument("--fish-model-title", default=os.environ.get("FISH_MODEL_TITLE", "video-slicer-voice"), help="Fish Audio voice model title.")
    parser.add_argument("--fish-model-description", default=os.environ.get("FISH_MODEL_DESCRIPTION", "Voice model for video slicing narration."), help="Fish Audio voice model description.")
    parser.add_argument("--fish-model-visibility", default=os.environ.get("FISH_MODEL_VISIBILITY", "private"), choices=["private", "unlist", "public"], help="Fish Audio voice model visibility.")
    parser.add_argument("--ocool-tts-speed", type=float, default=float(os.environ.get("OCOOL_TTS_SPEED", "1.0")), help="OpenAI-compatible TTS speed. Use around 0.75 when tts-1-hd reads too fast for a 120s target.")
    parser.add_argument("--tts-preview-text", default=None, help="Generate one standalone TTS preview audio file and exit.")
    parser.add_argument("--tts-preview-output", default="outputs/tts_preview.mp3", help="Output path for --tts-preview-text.")
    parser.add_argument("--force-tts", action="store_true", help="Regenerate per-sentence TTS audio files even if they already exist.")
    parser.add_argument("--force-transcribe", action="store_true", help="Re-run Whisper even if transcript exists.")
    parser.add_argument("--force-audio", action="store_true", help="Re-extract audio even if audio.wav exists.")
    parser.add_argument("--force-script", action="store_true", help="Regenerate voiceover script even if voiceover_script.json exists.")
    parser.add_argument("--no-llm", action="store_true", help="Do not call DashScope, use local fallback voiceover draft.")
    parser.add_argument("--require-llm", action="store_true", help="Fail instead of using fallback when DashScope script generation fails.")
    parser.add_argument("--skip-review", action="store_true", help="Skip the second LLM semantic/read-aloud review pass before TTS.")
    parser.add_argument("--force-review", action="store_true", help="Review the script again even if voiceover_script.json is already marked reviewed.")
    parser.add_argument("--skip-humanize", action="store_true", help="Skip the human-style voiceover polish pass.")
    parser.add_argument("--force-humanize", action="store_true", help="Run the human-style polish pass again even if voiceover_script.json is already marked humanized.")
    parser.add_argument("--voiceover-audio", default=None, help="Optional narration audio path to mux into final_with_voiceover.mp4.")
    parser.add_argument("--bgm-audio", default=os.environ.get("BGM_AUDIO", ""), help="Optional background music audio path. When set, writes final_with_bgm.mp4.")
    parser.add_argument("--bgm-volume", type=float, default=float(os.environ.get("BGM_VOLUME", "0.16")), help="Background music volume multiplier. Keep it low under narration, e.g. 0.10-0.25.")
    parser.add_argument("--voiceover-volume", type=float, default=float(os.environ.get("VOICEOVER_VOLUME", "1.0")), help="Narration volume multiplier used when mixing BGM.")
    parser.add_argument("--bgm-start", type=float, default=float(os.environ.get("BGM_START", "0")), help="Seconds to skip from the BGM before mixing. Useful for landing on a stronger music section.")
    parser.add_argument("--bgm-fade-in", type=float, default=float(os.environ.get("BGM_FADE_IN", "0.8")), help="BGM fade-in duration in seconds.")
    parser.add_argument("--bgm-fade-out", type=float, default=float(os.environ.get("BGM_FADE_OUT", "2.5")), help="BGM fade-out duration in seconds, aligned to the final video ending.")
    return parser


def run_cli(args: argparse.Namespace) -> None:

    if args.no_llm and args.require_llm:
        raise SystemExit("--no-llm and --require-llm cannot be used together.")

    if args.tts_preview_text:
        preview_path = Path(args.tts_preview_output)
        item = {
            "sentence_id": 1,
            "text": args.tts_preview_text,
            "audio_path": str(preview_path),
        }
        if args.tts_mode == "fish":
            from tts_providers.fish import synthesize_batch

            synthesize_batch(
                [item],
                reference_id=args.fish_reference_id,
                model=args.fish_tts_model,
                base_url=args.fish_base_url,
                speed=args.fish_tts_speed,
                volume=args.fish_tts_volume,
                latency=args.fish_tts_latency,
            )
        elif args.tts_mode == "ocool":
            from tts_providers.ocool import synthesize_batch

            synthesize_batch(
                [item],
                model=args.ocool_tts_model,
                voice=args.ocool_tts_voice,
                base_url=args.ocool_base_url,
                speed=args.ocool_tts_speed,
            )
        else:
            raise SystemExit("--tts-preview-text requires --tts-mode fish or --tts-mode ocool.")
        print(f"Wrote TTS preview: {preview_path}")
        return

    if args.fish_create_model:
        from tts_providers.fish import create_voice_model

        audio_paths = [Path(path) for path in args.fish_reference_audio]
        result = create_voice_model(
            audio_paths=audio_paths,
            title=args.fish_model_title,
            description=args.fish_model_description,
            base_url=args.fish_base_url,
            visibility=args.fish_model_visibility,
        )
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        fish_model_path = output_dir / "fish_voice_model.json"
        fish_model_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote Fish Audio voice model response: {fish_model_path}")
        model_id = result.get("_id") or result.get("id") or result.get("model_id") or ""
        print(f"FISH_REFERENCE_ID={model_id}")
        return

    ensure_ffmpeg()
    video_path = Path(args.input)
    if not video_path.exists():
        raise SystemExit(f"Input video not found: {video_path}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    context_packet = load_context_packet(Path(args.context)) if args.context else {}
    audio_path = output_dir / "audio.wav"
    transcript_path = output_dir / "transcript.json"
    raw_srt_path = output_dir / "raw_subtitles.srt"
    script_json_path = output_dir / "voiceover_script.json"
    script_txt_path = output_dir / "voiceover_script.txt"
    voiceover_srt_path = output_dir / "voiceover.srt"
    humanize_diff_path = output_dir / "voiceover_humanize_diff.txt"
    alignment_path = output_dir / "alignment.json"
    selected_path = output_dir / "selected_clips.json"
    mapping_path = output_dir / "time_mapping.json"
    quality_report_path = output_dir / "quality_report.json"

    video_duration = ffprobe_duration(video_path)
    print(f"Input video duration: {video_duration:.2f}s")
    validate_requested_target_duration(args.target_duration, video_duration)

    record_session = begin_pipeline_record_session(args, video_duration=video_duration)

    try:

        extract_audio(video_path, audio_path, force=args.force_audio)
        segments = transcribe_audio(
            audio_path=audio_path,
            transcript_path=transcript_path,
            srt_path=raw_srt_path,
            model_size=args.model_size,
            device=args.device,
            compute_type=args.compute_type,
            language=args.language,
            force=args.force_transcribe,
        )
        if not segments:
            raise SystemExit("No transcript segments were generated. Check whether the video contains clear speech.")

        voiceover_doc: dict[str, Any] | None = None
        if script_json_path.exists() and not args.force_script:
            print(f"Voiceover script exists, reuse: {script_json_path}")
            saved = json.loads(script_json_path.read_text(encoding="utf-8-sig"))
            voiceover_doc = dict(saved)
            voiceover_doc["voiceover"] = [
                {
                    "text": item["text"],
                    "source_segment_ids": item.get("source_segment_ids", []),
                    "context_refs": item.get("context_refs", []),
                    "story_role": item.get("story_role", ""),
                    "confidence": item.get("confidence"),
                    "visual_note": item.get("visual_note", ""),
                    "pre_humanize_text": item.get("pre_humanize_text", ""),
                }
                for item in saved.get("voiceover", [])
                if item.get("text")
            ]

        if voiceover_doc is None:
            if args.no_llm:
                voiceover_doc = fallback_voiceover_script(segments, args.target_duration)
            else:
                try:
                    voiceover_doc = generate_voiceover_with_llm(
                        segments=segments,
                        target_duration=args.target_duration,
                        model=args.dashscope_model,
                        base_url=args.dashscope_base_url,
                        context_packet=context_packet,
                    )
                except Exception as exc:
                    if args.require_llm:
                        raise SystemExit(f"Voiceover LLM failed and --require-llm is set: {exc}") from exc
                    print(f"Voiceover LLM failed: {exc}")
                    print("Using local fallback voiceover draft instead. Add --require-llm to fail fast.")
                    voiceover_doc = None
                if voiceover_doc is None:
                    if args.require_llm:
                        raise SystemExit("Voiceover LLM did not return a script and --require-llm is set.")
                    voiceover_doc = fallback_voiceover_script(segments, args.target_duration)

        should_review = (
            not args.no_llm
            and not args.skip_review
            and (args.force_review or not voiceover_doc.get("reviewed"))
        )
        if should_review:
            try:
                reviewed_doc = review_voiceover_with_llm(
                    voiceover_doc=voiceover_doc,
                    segments=segments,
                    target_duration=args.target_duration,
                    model=args.dashscope_model,
                    base_url=args.dashscope_base_url,
                    context_packet=context_packet,
                )
            except Exception as exc:
                if args.require_llm:
                    raise SystemExit(f"Semantic review failed and --require-llm is set: {exc}") from exc
                print(f"Semantic review failed: {exc}")
                print("Continue with unreviewed script. Add --require-llm to fail fast.")
                reviewed_doc = None
            if reviewed_doc is not None:
                voiceover_doc = reviewed_doc

        should_humanize = (
            not args.no_llm
            and not args.skip_humanize
            and (args.force_humanize or not voiceover_doc.get("humanized"))
        )
        if should_humanize:
            if args.force_humanize and voiceover_doc.get("humanized"):
                reset_items: list[dict[str, Any]] = []
                for item in voiceover_doc.get("voiceover", []):
                    reset_item = dict(item)
                    original_text = str(reset_item.get("pre_humanize_text", "")).strip()
                    if original_text:
                        reset_item["text"] = original_text
                    reset_items.append(reset_item)
                voiceover_doc = dict(voiceover_doc)
                voiceover_doc["voiceover"] = reset_items
                voiceover_doc["humanized"] = False
            before_humanize_doc = json.loads(json.dumps(voiceover_doc, ensure_ascii=False))
            try:
                humanized_doc = humanize_voiceover_with_llm(
                    voiceover_doc=voiceover_doc,
                    target_duration=args.target_duration,
                    model=args.dashscope_humanize_model,
                    base_url=args.dashscope_base_url,
                    context_packet=context_packet,
                )
            except Exception as exc:
                if args.require_llm:
                    raise SystemExit(f"Voiceover humanize failed and --require-llm is set: {exc}") from exc
                print(f"Voiceover humanize failed: {exc}")
                print("Continue with reviewed script. Add --require-llm to fail fast.")
                humanized_doc = None
            if humanized_doc is not None:
                voiceover_doc = humanized_doc
                write_humanize_diff(before_humanize_doc, voiceover_doc, humanize_diff_path)
                print(f"Wrote humanize diff: {humanize_diff_path}")

        validate_voiceover_doc(voiceover_doc, context_packet)

        script_json_path.write_text(json.dumps(voiceover_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        script_txt_lines: list[str] = []
        if voiceover_doc.get("title"):
            script_txt_lines.append(f"# {voiceover_doc['title']}")
        if voiceover_doc.get("summary"):
            script_txt_lines.append(str(voiceover_doc["summary"]))
        if script_txt_lines:
            script_txt_lines.append("")
        script_txt_lines.extend(str(item.get("text", "")).strip() for item in voiceover_doc.get("voiceover", []) if item.get("text"))
        script_txt_path.write_text("\n".join(script_txt_lines), encoding="utf-8")
        print(f"Wrote reviewed voiceover script checkpoint: {script_json_path}")

        alignment = align_voiceover_to_transcript(voiceover_doc, segments, args.target_duration)
        if args.tts_mode in {"ocool", "fish"}:
            alignment = prepare_sentence_audio(
                alignment=alignment,
                output_dir=output_dir,
                tts_mode=args.tts_mode,
                base_url=args.ocool_base_url,
                ocool_tts_model=args.ocool_tts_model,
                ocool_tts_voice=args.ocool_tts_voice,
                ocool_tts_speed=args.ocool_tts_speed,
                fish_tts_model=args.fish_tts_model,
                fish_reference_id=args.fish_reference_id,
                fish_base_url=args.fish_base_url,
                fish_tts_speed=args.fish_tts_speed,
                fish_tts_volume=args.fish_tts_volume,
                fish_tts_latency=args.fish_tts_latency,
                force=args.force_tts,
            )
            if not args.no_fit_duration:
                alignment = fit_alignment_audio_to_target_duration(
                    alignment=alignment,
                    output_dir=output_dir,
                    target_duration=args.target_duration,
                    tolerance=args.duration_tolerance,
                    force=args.force_tts,
                )
        else:
            print("TTS disabled. The final narrated video will not be rendered unless --voiceover-audio is provided.")
            alignment = apply_estimated_voiceover_timeline(alignment)

        alignment = limit_alignment_to_target_duration(alignment, args.target_duration, tolerance=args.duration_tolerance)
        clips = build_clips_from_alignment(
            alignment=alignment,
            video_duration=video_duration,
            padding=args.padding,
        )
        if not clips:
            raise SystemExit("No valid visual clips selected from voiceover alignment.")

        write_voiceover_outputs(voiceover_doc, alignment, script_json_path, script_txt_path, voiceover_srt_path)
        alignment_path.write_text(json.dumps(alignment, ensure_ascii=False, indent=2), encoding="utf-8")

        actual_voiceover_duration = round(sum(float(row["voiceover_duration"]) for row in alignment), 3)
        actual_visual_duration = round(sum(float(clip["duration"]) for clip in clips), 3)
        selected_doc = {
            "mode": "voiceover_first_real_tts_cut" if args.tts_mode in {"ocool", "fish"} else "voiceover_first_silent_cut",
            "tts_mode": args.tts_mode,
            "target_duration": args.target_duration,
            "actual_visual_duration": actual_visual_duration,
            "actual_voiceover_duration": actual_voiceover_duration,
            "estimated_voiceover_duration": alignment[-1].get("estimated_voiceover_end"),
            "title": voiceover_doc.get("title", ""),
            "summary": voiceover_doc.get("summary", ""),
            "context_packet": context_packet,
            "bgm": {
                "audio": args.bgm_audio,
                "volume": args.bgm_volume,
                "voiceover_volume": args.voiceover_volume,
                "start": args.bgm_start,
                "fade_in": args.bgm_fade_in,
                "fade_out": args.bgm_fade_out,
            } if args.bgm_audio else None,
            "clips": clips,
        }
        selected_path.write_text(json.dumps(selected_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        quality_report = build_quality_report(
            alignment=alignment,
            clips=clips,
            target_duration=args.target_duration,
            duration_tolerance=args.duration_tolerance,
            actual_voiceover_duration=actual_voiceover_duration,
            actual_visual_duration=actual_visual_duration,
            source_video_duration=video_duration,
            tts_mode=args.tts_mode,
            title=str(voiceover_doc.get("title", "")),
        )
        write_quality_report(quality_report, quality_report_path)
        validate_timeline_duration(
            target_duration=args.target_duration,
            tolerance=args.duration_tolerance,
            actual_voiceover_duration=actual_voiceover_duration,
            actual_visual_duration=actual_visual_duration,
        )

        output_video = clip_video_silent(video_path, output_dir, clips)
        write_visual_time_mapping(clips, mapping_path)

        final_path: Path | None = None
        if args.tts_mode in {"ocool", "fish"}:
            final_path = render_clips_with_voiceover(video_path, output_dir, clips)
        elif args.voiceover_audio:
            final_path = output_dir / "final_with_voiceover.mp4"
            mux_voiceover_audio(output_video, Path(args.voiceover_audio), final_path)
        if final_path:
            validate_final_duration(final_path, args.target_duration, args.duration_tolerance, "Final narrated video")

        final_with_bgm_path: Path | None = None
        if args.bgm_audio:
            if final_path is None:
                print("BGM skipped because no narrated final video was rendered. Use --tts-mode fish/ocool or --voiceover-audio to mix BGM.")
            else:
                final_with_bgm_path = output_dir / "final_with_bgm.mp4"
                add_background_music(
                    video_path=final_path,
                    bgm_audio=Path(args.bgm_audio),
                    output_path=final_with_bgm_path,
                    bgm_volume=args.bgm_volume,
                    voiceover_volume=args.voiceover_volume,
                    bgm_start=args.bgm_start,
                    bgm_fade_in=args.bgm_fade_in,
                    bgm_fade_out=args.bgm_fade_out,
                )
                validate_final_duration(final_with_bgm_path, args.target_duration, args.duration_tolerance, "Final narrated video with BGM")

        print(f"Wrote silent preview video: {output_video}")
        if final_path:
            print(f"Wrote final narrated video: {final_path}")
        if final_with_bgm_path:
            print(f"Wrote final narrated video with BGM: {final_with_bgm_path}")
        print(f"Wrote voiceover script: {script_txt_path}")
        print(f"Wrote voiceover JSON: {script_json_path}")
        print(f"Wrote voiceover subtitles: {voiceover_srt_path}")
        print(f"Wrote alignment: {alignment_path}")
        print(f"Wrote quality report: {quality_report_path}")
        print(f"Wrote time mapping: {mapping_path}")
        print(f"Visual duration: {actual_visual_duration:.2f}s")
        print(f"Real voiceover duration: {actual_voiceover_duration:.2f}s")



        record_output_path = final_with_bgm_path or final_path or output_video
        record_duration = ffprobe_duration_media(record_output_path) if record_output_path.exists() else None
        record_session.mark_success(
            final_video_path=str(record_output_path),
            duration_seconds=record_duration,
        )
    except BaseException as exc:
        record_session.mark_failed(exc)
        raise


def main(argv: list[str] | None = None) -> None:
    load_dotenv(Path(".env"))
    parser = build_parser()
    args = parser.parse_args(argv)
    run_cli(args)


if __name__ == "__main__":
    main()
