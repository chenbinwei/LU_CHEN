"""FFmpeg rendering, muxing, and media probing helpers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("$ " + " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=cwd, check=True)
    except FileNotFoundError as exc:
        raise SystemExit(f"Command not found: {cmd[0]}. Install it and try again.") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Command failed with exit code {exc.returncode}: {' '.join(cmd)}") from exc


def run_capture(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise SystemExit(f"Command not found: {cmd[0]}. Install it and try again.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise SystemExit(f"Command failed with exit code {exc.returncode}: {' '.join(cmd)}\n{detail}") from exc
    return result.stdout.strip()


def ensure_ffmpeg() -> None:
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        subprocess.run(["ffprobe", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception as exc:
        raise SystemExit("FFmpeg/ffprobe is required. Install FFmpeg and make sure it is in PATH.") from exc


def ffprobe_duration_media(media_path: Path) -> float:
    value = run_capture([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ])
    if not value or value == "N/A":
        raise SystemExit(f"Could not read media duration: {media_path}")
    return float(value)


def ffprobe_duration(video_path: Path) -> float:
    return ffprobe_duration_media(video_path)


def clip_video_silent(video_path: Path, output_dir: Path, clips: list[dict[str, Any]]) -> Path:
    clips_dir = output_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clip_files: list[Path] = []

    for clip in clips:
        clip_path = clips_dir / f"clip_{clip['id']:03}.mp4"
        run([
            "ffmpeg",
            "-y",
            "-ss",
            f"{clip['source_start']:.3f}",
            "-i",
            str(video_path),
            "-t",
            f"{clip['duration']:.3f}",
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(clip_path),
        ])
        clip_files.append(clip_path)

    concat_list = output_dir / "concat_list.txt"
    concat_list.write_text("\n".join(f"file '{path.resolve().as_posix()}'" for path in clip_files), encoding="utf-8")

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


def write_visual_time_mapping(clips: list[dict[str, Any]], mapping_path: Path) -> None:
    mapping: list[dict[str, Any]] = []
    cursor = 0.0
    for clip in clips:
        new_start = cursor
        new_end = cursor + float(clip["duration"])
        mapping.append({
            "clip_id": clip["id"],
            "sentence_ids": clip.get("sentence_ids", []),
            "source_segment_ids": clip.get("source_segment_ids", []),
            "source_start": round(float(clip["source_start"]), 3),
            "source_end": round(float(clip["source_end"]), 3),
            "new_start": round(new_start, 3),
            "new_end": round(new_end, 3),
        })
        cursor = new_end
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")


def render_clips_with_voiceover(video_path: Path, output_dir: Path, clips: list[dict[str, Any]]) -> Path:
    clips_dir = output_dir / "final_clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clip_files: list[Path] = []

    for clip in clips:
        audio_value = clip.get("voiceover_audio_path")
        if not audio_value:
            raise SystemExit("Cannot render final voiceover video: a clip is missing voiceover_audio_path.")
        audio_path = Path(str(audio_value))
        if not audio_path.exists():
            raise SystemExit(f"Voiceover audio not found: {audio_path}")

        clip_path = clips_dir / f"part_{clip['id']:03}.mp4"
        run([
            "ffmpeg",
            "-y",
            "-ss",
            f"{clip['source_start']:.3f}",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-t",
            f"{clip['duration']:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
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
            "-shortest",
            "-movflags",
            "+faststart",
            str(clip_path),
        ])
        clip_files.append(clip_path)

    concat_list = output_dir / "final_concat_list.txt"
    concat_list.write_text("\n".join(f"file '{path.resolve().as_posix()}'" for path in clip_files), encoding="utf-8")

    output_path = output_dir / "final_with_voiceover.mp4"
    run([
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
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
        str(output_path),
    ])
    return output_path


def mux_voiceover_audio(video_path: Path, voiceover_audio: Path, output_path: Path) -> None:
    if not voiceover_audio.exists():
        raise SystemExit(f"Voiceover audio not found: {voiceover_audio}")
    run([
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(voiceover_audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        str(output_path),
    ])


def burn_subtitles(video_path: Path, subtitle_path: Path, output_path: Path) -> None:
    subtitle_arg = subtitle_path.as_posix().replace("'", "\\'")
    run([
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"subtitles='{subtitle_arg}'",
        "-c:a",
        "copy",
        str(output_path),
    ])


def validate_final_duration(media_path: Path, target_duration: float, tolerance: float, label: str) -> float:
    if target_duration <= 0:
        return ffprobe_duration_media(media_path)
    duration = ffprobe_duration_media(media_path)
    delta = abs(duration - target_duration)
    print(f"{label} duration check: {duration:.2f}s target={target_duration:.2f}s delta={delta:.2f}s")
    if delta > tolerance:
        raise SystemExit(
            f"{label} duration is outside tolerance: {duration:.2f}s vs "
            f"{target_duration:.2f}s target (tolerance {tolerance:.2f}s)."
        )
    return duration


def add_background_music(
    video_path: Path,
    bgm_audio: Path,
    output_path: Path,
    *,
    bgm_volume: float,
    voiceover_volume: float,
    bgm_start: float,
    bgm_fade_in: float,
    bgm_fade_out: float,
) -> None:
    if not bgm_audio.exists():
        raise SystemExit(f"BGM audio not found: {bgm_audio}")
    if bgm_volume < 0:
        raise SystemExit("--bgm-volume must be greater than or equal to 0.")
    if voiceover_volume < 0:
        raise SystemExit("--voiceover-volume must be greater than or equal to 0.")
    if bgm_start < 0:
        raise SystemExit("--bgm-start must be greater than or equal to 0.")
    if bgm_fade_in < 0:
        raise SystemExit("--bgm-fade-in must be greater than or equal to 0.")
    if bgm_fade_out < 0:
        raise SystemExit("--bgm-fade-out must be greater than or equal to 0.")

    video_duration = ffprobe_duration_media(video_path)
    fade_in = min(bgm_fade_in, max(0.0, video_duration / 2))
    fade_out = min(bgm_fade_out, max(0.0, video_duration / 2))
    fade_out_start = max(0.0, video_duration - fade_out)
    bgm_filters = [
        f"atrim=0:{video_duration:.3f}",
        "asetpts=PTS-STARTPTS",
    ]
    if fade_in > 0:
        bgm_filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0:
        bgm_filters.append(f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}")
    bgm_filters.append(f"volume={bgm_volume:.3f}")
    filter_complex = (
        f"[0:a]volume={voiceover_volume:.3f}[voice];"
        f"[1:a]{','.join(bgm_filters)}[bgm];"
        "[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )
    run([
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-stream_loop",
        "-1",
        "-ss",
        f"{bgm_start:.3f}",
        "-i",
        str(bgm_audio),
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ])
