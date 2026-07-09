import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from video_slicer.context_packet import (
    compact_context_for_prompt,
    load_context_packet,
    narration_rules_for_prompt,
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


def seconds_to_srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def write_srt(segments: list[dict[str, Any]], path: Path) -> None:
    lines: list[str] = []
    for idx, seg in enumerate(segments, start=1):
        speaker = seg.get("speaker")
        text = seg["text"]
        if speaker and speaker != "UNKNOWN":
            text = f"{speaker}: {text}"
        lines.extend([
            str(idx),
            f"{seconds_to_srt_time(float(seg['start']))} --> {seconds_to_srt_time(float(seg['end']))}",
            text,
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def transcript_for_prompt(segments: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for seg in segments:
        rows.append(
            f"[{seg['id']}] {seg['start']:.3f}-{seg['end']:.3f} "
            f"{seg.get('speaker', 'UNKNOWN')}: {seg['text']}"
        )
    return "\n".join(rows)


def compact_voiceover_generation_instructions() -> str:
    return """
你是专业中文影视解说剪辑师。根据字幕和人工上下文包，生成约两分钟的故事型配音文案。

硬规则：
- 只输出严格合法 JSON，不要 Markdown，不要解释。所有对象和数组元素之间必须有逗号，禁止尾逗号，禁止省略引号。
- 只能使用 transcript 和 context_packet 中的信息；没有证据就保守表达。
- 可以使用 context_packet 中明确给出的人名、剧情背景和禁用规则。
- 严禁出现英文字母、英文单词、错别字、错词、禁用词和上下文包禁止的剧情。
- 文案要像真人影视解说，不要像字幕摘要；要有开头钩子、人物关系、冲突升级、转折和收束。
- voiceover 输出 20 到 28 条短句；每条 12 到 36 个中文字符，适合直接配音。
- 每条必须给 source_segment_ids，id 必须来自 transcript，尽量按原片时间顺序。
- 如果一句用了上下文包信息，context_refs 必须标明字段名。
- 不要写“说得平”“意思很明白”；用“语气平静”“意思很清楚”等自然表达。

JSON schema:
{
  "title": "短标题",
  "summary": "一句话概括",
  "story_plan": [
    {
      "role": "hook/setup/conflict/escalation/turning_point/payoff",
      "description": "这一段讲什么",
      "source_segment_ids": [1, 2],
      "context_refs": ["correct_synopsis"]
    }
  ],
  "voiceover": [
    {
      "text": "一句中文解说文案",
      "source_segment_ids": [1, 2],
      "context_refs": ["correct_synopsis"],
      "story_role": "hook/setup/conflict/escalation/turning_point/payoff",
      "confidence": 0.8,
      "visual_note": "对应画面"
    }
  ],
  "evidence_notes": ["说明哪些信息来自字幕或上下文包"]
}
""".strip()


def compact_voiceover_review_instructions() -> str:
    return """
你是中文影视解说终审编辑。检查候选脚本是否像完整故事，是否符合字幕和上下文包证据，是否适合 TTS 直接念。

必须修正：
- 编造事实、错别字、错词、不自然口播、英文、禁用词。
- 不符合 context_packet.correct_synopsis、forbidden_terms、forbidden_story_facts、must_not_include 的内容。
- source_segment_ids 不存在或明显错位的问题。

保持候选脚本结构，输出严格合法 JSON，不要 Markdown，不要解释。所有对象和数组元素之间必须有逗号，禁止尾逗号。voiceover 仍保持 20 到 28 条短句，不能合成长段。
额外包含 reviewed=true、review_notes、read_aloud_checks。
""".strip()


def voiceover_length_requirements(target_duration: float) -> dict[str, int]:
    seconds = max(15.0, float(target_duration or 120.0))
    min_items = max(8, min(60, round(seconds / 4.2)))
    max_items = max(min_items + 4, min(75, round(seconds / 3.0)))
    min_cjk_chars = max(120, round(seconds * 5.6))
    max_cjk_chars = max(min_cjk_chars + 80, round(seconds * 7.2))
    ideal_cjk_chars = round((min_cjk_chars + max_cjk_chars) / 2)
    return {
        "target_duration_seconds": round(seconds),
        "min_voiceover_items": min_items,
        "max_voiceover_items": max_items,
        "min_total_cjk_chars": min_cjk_chars,
        "max_total_cjk_chars": max_cjk_chars,
        "ideal_total_cjk_chars": ideal_cjk_chars,
    }


def extract_response_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return text
    try:
        data = response.model_dump()
    except Exception:
        data = None
    if data:
        parts: list[str] = []
        for item in data.get("output", []) or []:
            for content in item.get("content", []) or []:
                value = content.get("text") or content.get("content")
                if value:
                    parts.append(str(value))
        if parts:
            return "\n".join(parts)
    return str(response)


def parse_json_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def parse_llm_json_response(text: str, *, model: str, base_url: str, api_key: str) -> dict[str, Any]:
    try:
        return parse_json_response(text)
    except json.JSONDecodeError as exc:
        print(f"LLM returned invalid JSON, trying one repair pass: {exc}")
        from llm_providers.dashscope import text_completion

        repair_instructions = """
你是 JSON 修复器。输入是一段接近 JSON 的模型输出，可能缺少逗号、含有 Markdown 包裹、尾逗号或字符串引号错误。
只修复为严格合法 JSON，不要改写含义，不要增删字段，不要输出解释，不要输出 Markdown。
""".strip()
        repaired = text_completion(
            model=model,
            instructions=repair_instructions,
            input_text=text,
            base_url=base_url,
            api_key=api_key,
            max_tokens=int(os.environ.get("DASHSCOPE_REPAIR_MAX_TOKENS", "5000")),
        )
        return parse_json_response(repaired)


DEFAULT_FORBIDDEN_TERMS = [
    "birds",
    "bird",
    "VOICEOVER",
]


DEFAULT_TTS_UNFRIENDLY_TERMS = [
    "说得平",
    "意思很明白",
]


def find_terms_in_text(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term and term.lower() in lowered]


def terms_from_context(context_packet: dict[str, Any] | None, keys: tuple[str, ...]) -> list[str]:
    context_packet = context_packet or {}
    terms: list[str] = []
    for key in keys:
        value = context_packet.get(key)
        if isinstance(value, list):
            terms.extend(str(item) for item in value if str(item).strip())
        elif isinstance(value, str) and value.strip():
            terms.append(value)
    return terms


def humanize_unsafe_terms_from_context(context_packet: dict[str, Any] | None) -> list[str]:
    return sorted(set(terms_from_context(
        context_packet,
        (
            "humanize_unsafe_detail_terms",
            "forbidden_visual_details",
            "unsafe_detail_terms",
        ),
    )), key=lambda item: item.lower())


def tts_unfriendly_terms_from_context(context_packet: dict[str, Any] | None) -> list[str]:
    terms = list(DEFAULT_TTS_UNFRIENDLY_TERMS)
    terms.extend(terms_from_context(
        context_packet,
        (
            "tts_unfriendly_terms",
            "bad_tts_terms",
        ),
    ))
    return sorted(set(terms), key=lambda item: item.lower())


def blocked_humanize_terms(text: str, context_packet: dict[str, Any] | None) -> list[str]:
    blocked: list[str] = []
    if re.search(r"[A-Za-z]", text):
        blocked.append("English letters")
    blocked.extend(find_terms_in_text(text, forbidden_terms_from_context(context_packet)))
    blocked.extend(find_terms_in_text(text, humanize_unsafe_terms_from_context(context_packet)))
    blocked.extend(find_terms_in_text(text, tts_unfriendly_terms_from_context(context_packet)))
    return sorted(set(blocked), key=lambda item: item.lower())


def narration_style_violations(voiceover_doc: dict[str, Any], context_packet: dict[str, Any] | None) -> list[str]:
    rules = (context_packet or {}).get("narration_rules", {})
    if not isinstance(rules, dict):
        return []

    items = [
        str(item.get("text", "")).strip()
        for item in voiceover_doc.get("voiceover", [])
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]
    if not items:
        return []

    violations: list[str] = []
    roleplay_pattern = re.compile(r"(?:^|[，。！？、\s])(?:我|我们|咱们|你|你们)(?:$|[，。！？、\s]|[^的])")
    command_pattern = re.compile(r"^(?:看|注意|听|别|不要|来|给|听着|记住|都|谁|怎么|现在|今天)")
    direct_quote_pattern = re.compile(r"[“”‘’\"']")

    if rules.get("forbid_first_person_roleplay", True):
        roleplay_lines = [text for text in items if roleplay_pattern.search(text)]
        limit = max(3, int(len(items) * 0.2))
        if len(roleplay_lines) > limit:
            examples = " / ".join(roleplay_lines[:5])
            violations.append(
                f"too many first/second-person roleplay lines ({len(roleplay_lines)}/{len(items)}): {examples}"
            )

    if rules.get("forbid_dialogue_reenactment", True) or rules.get("forbid_direct_dialogue_as_voiceover", True):
        direct_quote_lines = [text for text in items if direct_quote_pattern.search(text)]
        quote_limit = max(1, int(len(items) * 0.05))
        if len(direct_quote_lines) > quote_limit:
            examples = " / ".join(direct_quote_lines[:5])
            violations.append(
                f"too many direct quote/dialogue lines ({len(direct_quote_lines)}/{len(items)}): {examples}"
            )

        dialogue_like_lines = [
            text
            for text in items
            if len(text) <= 14 and (roleplay_pattern.search(text) or command_pattern.search(text) or text.endswith(("？", "?", "！", "!")))
        ]
        limit = max(4, int(len(items) * 0.25))
        if len(dialogue_like_lines) > limit:
            examples = " / ".join(dialogue_like_lines[:6])
            violations.append(
                f"too many dialogue-like short lines ({len(dialogue_like_lines)}/{len(items)}): {examples}"
            )

    return violations


def forbidden_terms_from_context(context_packet: dict[str, Any] | None) -> list[str]:
    terms = list(DEFAULT_FORBIDDEN_TERMS)
    terms.extend(terms_from_context(context_packet, (
        "forbidden_terms",
        "forbidden_story_facts",
        "must_not_include",
    )))
    return sorted(set(terms), key=lambda item: item.lower())


def validate_voiceover_doc(voiceover_doc: dict[str, Any], context_packet: dict[str, Any] | None) -> None:
    text_parts: list[str] = []
    for key in ("title", "summary"):
        value = voiceover_doc.get(key)
        if isinstance(value, str):
            text_parts.append(value)
    for item in voiceover_doc.get("voiceover", []) or []:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            text_parts.append(item["text"])

    text = "\n".join(text_parts)
    if re.search(r"[A-Za-z]", text):
        raise SystemExit("Voiceover text contains English letters. Regenerate or review the script before TTS.")

    blocked = find_terms_in_text(text, forbidden_terms_from_context(context_packet))
    if blocked:
        raise SystemExit("Voiceover text contains forbidden terms: " + ", ".join(blocked))
    tts_blocked = find_terms_in_text(text, tts_unfriendly_terms_from_context(context_packet))
    if tts_blocked:
        raise SystemExit("Voiceover text contains TTS-unfriendly terms: " + ", ".join(tts_blocked))
    style_blocked = narration_style_violations(voiceover_doc, context_packet)
    if style_blocked:
        raise SystemExit("Voiceover violates narration rules: " + "; ".join(style_blocked))


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



def generate_voiceover_with_llm(
    segments: list[dict[str, Any]],
    target_duration: float,
    model: str,
    base_url: str,
    context_packet: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key or api_key == "put_your_dashscope_api_key_here":
        print("DASHSCOPE_API_KEY is empty. Using local fallback voiceover draft.")
        return None

    transcript = [
        {
            "id": int(seg["id"]),
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "speaker": seg.get("speaker", "UNKNOWN"),
            "text": seg["text"],
        }
        for seg in segments
    ]
    context_packet = context_packet or {}
    instructions = """
你是一个“故事型短视频剪辑师”，不是字幕摘要工具。你的任务是把原视频重构成一个约 2 分钟的中文解说故事。

可信信息来源只有三类：
1. transcript：原视频字幕和时间戳。
2. context_packet：用户人工提供的视频标题、人物、背景、风格要求。
3. context_packet.allowed_external_knowledge：用户明确允许使用的外部背景。

创作目标：
- 不是压缩字幕，而是从字幕里提炼事件推进，把信息组织成“观众愿意看完”的切片。
- 信息量要比普通摘要更丰富：保留关键动作、话术变化、人物动机、冲突升级、反转点和结果。
- 每段都要服务故事，不要平均覆盖所有字幕；优先选择能推动剧情的证据片段。

故事结构建议：
1. hook：开头 5-10 秒给出冲突或反常点。
2. setup：交代人物身份、场景和双方关系，只使用有证据的信息。
3. conflict：讲清楚矛盾如何开始。
4. escalation：用 2-4 个细节说明冲突怎样升级。
5. turning_point：指出局势发生变化的瞬间。
6. payoff：用一句有力度的结尾收住故事。

严格规则：
- 可以使用 context_packet 中明确给出的名字、人物关系、背景。
- 如果字幕和 context_packet 都没有提供某个事实，不能编造；宁可写“这个男人”“对方”“主角”。
- 不要把外部常识当作视频事实，除非 allowed_external_knowledge 明确提供。
- 每句配音必须绑定 source_segment_ids，后续程序会按这些片段反查原视频画面。
- 每句配音如果使用了上下文包的信息，必须在 context_refs 中写明引用的字段或实体名。
- source_segment_ids 必须来自 transcript，尽量连续；整体故事按原视频时序推进，除非开头 hook 需要短暂前置高能片段。
- 文案要适合配音，短句为主，有节奏，有口语感，不要复述字幕，不要写成影评论文。
- 不要把角色台词原样放进配音，不要用引号模拟对话；把台词改写成第三人称影视解说，例如“他冷声质问对方是否认识自己”。
- 避免 TTS 容易读错或听起来别扭的省略表达，例如“说得平”“意思很明白”；这类句子应改成“语气平静”“意思很清楚”。
- 严禁出现英文字母或英文单词；如果候选里有英文，必须改成纯中文。
- 必须遵守 context_packet.correct_synopsis、forbidden_terms、forbidden_story_facts、must_not_include；上下文包禁止的错误剧情和词语绝不能出现。
- 如果 context_packet.forbidden_terms 中的任何词出现在候选文案里，必须改写到完全不出现。
- 必须严格按 length_requirements 控制 voiceover 条数和总中文字符数；不要靠放慢 TTS 凑时长。
- 每条对应一个可剪辑画面，不要写成长段落；每句 14 到 46 个中文字符为宜。
- 总字数要落在 length_requirements.min_total_cjk_chars 到 length_requirements.max_total_cjk_chars 之间，优先接近 ideal_total_cjk_chars。
- 不要为了凑时长硬写废话，宁可让每句更有信息密度。

只输出严格合法 JSON，不要输出 Markdown，不要输出解释。所有对象和数组元素之间必须有逗号，禁止尾逗号，禁止省略引号。
JSON schema:
{
  "title": "短标题",
  "summary": "一句话概括这个切片故事",
  "story_plan": [
    {
      "role": "hook/setup/conflict/escalation/turning_point/payoff",
      "description": "这一段讲什么、为什么要放进切片",
      "source_segment_ids": [1, 2, 3],
      "context_refs": ["video_title", "characters.人物名"]
    }
  ],
  "voiceover": [
    {
      "text": "一句适合配音的故事化文案",
      "source_segment_ids": [1, 2, 3],
      "context_refs": ["video_title"],
      "story_role": "hook/setup/conflict/escalation/turning_point/payoff",
      "confidence": 0.0,
      "visual_note": "这一句适合使用的画面"
    }
  ],
  "evidence_notes": [
    "说明哪些信息来自字幕，哪些来自上下文包；如果没有外部证据，明确不要补全。"
  ]
}
""".strip()
    context_for_prompt = compact_context_for_prompt(context_packet)
    length_requirements = voiceover_length_requirements(target_duration)
    instructions = instructions + "\n\n" + narration_rules_for_prompt(context_for_prompt)
    prompt = json.dumps(
        {
            "target_duration_seconds": target_duration,
            "length_requirements": length_requirements,
            "context_packet": context_for_prompt,
            "transcript": transcript_for_prompt(segments),
        },
        ensure_ascii=False,
    )

    print(f"Calling DashScope for voiceover script: {model}")
    from llm_providers.dashscope import text_completion

    text = text_completion(
        model=model,
        instructions=instructions,
        input_text=prompt,
        base_url=base_url,
        api_key=api_key,
    )
    return parse_llm_json_response(text, model=model, base_url=base_url, api_key=api_key)




def review_voiceover_with_llm(
    voiceover_doc: dict[str, Any],
    segments: list[dict[str, Any]],
    target_duration: float,
    model: str,
    base_url: str,
    context_packet: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key or api_key == "put_your_dashscope_api_key_here":
        print("DASHSCOPE_API_KEY is empty. Skip semantic review.")
        return None

    transcript = [
        {
            "id": int(seg["id"]),
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "speaker": seg.get("speaker", "UNKNOWN"),
            "text": seg["text"],
        }
        for seg in segments
    ]
    instructions = """
你是专业影视解说的终审编辑和配音审稿人。你不是重新摘要，而是在候选脚本基础上做“可播出级”语义审查与润色。

你的目标：让脚本听起来像专业影视解说：故事完整、信息更丰富、逻辑连贯、节奏紧凑、没有错别字、没有错词、没有 TTS 念起来奇怪的句子。

必须检查并修正：
1. 故事完整性：是否有开头钩子、人物/场景交代、冲突升级、转折、结尾落点。
2. 证据约束：每句信息是否来自 transcript、context_packet 或 allowed_external_knowledge；没有证据就改成更保守的说法。
3. 口播质量：句子是否像人讲故事，而不是字幕摘要；删除生硬、重复、空泛的表达。
4. 错别字错词：修正同音错词、错称谓、标点造成的断句问题。
5. TTS 可读性：避免生僻符号、英文缩写、过长句和不自然省略表达；数字和称谓要适合直接念出来。不要使用“说得平”“意思很明白”，应改成“语气平静”“意思很清楚”。所有最终文案必须是纯中文和中文标点，不允许出现英文字母。
6. 画面想象：每句文案都要能对应到原片画面，visual_note 要说明用什么画面支撑这句话。
7. 解说身份：不得用引号复述角色台词，不得写成角色对话或命令口吻；把台词信息转述成第三人称解说。

严格规则：
- 不要编造 transcript 和 context_packet 都没有的信息。
- 可以补充 context_packet.allowed_external_knowledge 明确允许的背景，但必须在 context_refs 中标注。
- 不要输出“本片讲了”“视频中可以看到”这类空泛话术，要直接讲故事。
- 不要出现“看”“听”“注意”这类对观众下指令的开头。
- 必须检查 context_packet.correct_synopsis、forbidden_terms、forbidden_story_facts、must_not_include，违反则重写。
- 每句 source_segment_ids 必须来自 transcript；如调整文案，也要保留或修正对应来源。
- 保持总时长接近 target_duration_seconds；必须按 length_requirements 检查条数和总中文字符数，不要合并成长段。
- 优先保证故事质量和信息密度。
- 输出必须是严格合法 JSON，不要 Markdown，不要解释。所有对象和数组元素之间必须有逗号，禁止尾逗号。

返回 JSON schema 与候选脚本一致，但必须额外包含：
{
  "reviewed": true,
  "review_notes": ["你做了哪些重要修正"],
  "read_aloud_checks": ["说明口播/TTS 层面已检查的点"]
}
""".strip()
    context_for_prompt = compact_context_for_prompt(context_packet)
    length_requirements = voiceover_length_requirements(target_duration)
    instructions = instructions + "\n\n" + narration_rules_for_prompt(context_for_prompt)
    prompt = json.dumps(
        {
            "target_duration_seconds": target_duration,
            "length_requirements": length_requirements,
            "context_packet": context_for_prompt,
            "transcript": transcript_for_prompt(segments),
            "candidate_script": voiceover_doc,
        },
        ensure_ascii=False,
    )

    print(f"Calling DashScope for semantic script review: {model}")
    from llm_providers.dashscope import text_completion

    text = text_completion(
        model=model,
        instructions=instructions,
        input_text=prompt,
        base_url=base_url,
        api_key=api_key,
    )
    reviewed = parse_llm_json_response(text, model=model, base_url=base_url, api_key=api_key)
    if not isinstance(reviewed.get("voiceover"), list) or not reviewed["voiceover"]:
        raise ValueError("Semantic review did not return a non-empty voiceover list.")
    reviewed["reviewed"] = True
    reviewed["review_model"] = model
    return reviewed


def humanize_voiceover_with_llm(
    voiceover_doc: dict[str, Any],
    target_duration: float,
    model: str,
    base_url: str,
    context_packet: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key or api_key == "put_your_dashscope_api_key_here":
        print("DASHSCOPE_API_KEY is empty. Skip voiceover humanization.")
        return None

    voiceover_items = [
        {
            "index": idx,
            "text": str(item.get("text", "")).strip(),
            "source_segment_ids": item.get("source_segment_ids", []),
            "story_role": item.get("story_role", ""),
            "visual_note": item.get("visual_note", ""),
        }
        for idx, item in enumerate(voiceover_doc.get("voiceover", []), start=1)
        if str(item.get("text", "")).strip()
    ]
    if not voiceover_items:
        return None

    instructions = """
你是中文影视解说的“真人口播润色师”。你的任务不是重写剧情，而是在完全保留事实和时间戳绑定的前提下，把候选文案改得更像真人会说的话。

你只能改每条 voiceover 的 text，不允许改变条数、顺序、source_segment_ids、story_role 或 visual_note。
每个 index 的润色必须只对应同一个 index 的原句，不能把上一句或下一句的内容挪过来。

润色目标：
- 去掉 AI 腔、说明书感、字幕摘要感。
- 增强真人口播的停顿、语气和推进感。
- 句子要适合 TTS 直接念出来，短句优先，听起来像影视解说。
- 可以让表达更有口语感，但不能新增没有证据的画面细节。
- 不要明显缩短文案；每句通常保留原句 80% 到 120% 的字数和信息量，只改口播感。
- 不要让总字数明显低于 length_requirements.min_total_cjk_chars；如果原句信息充足，优先保留细节。
- 保持紧张、有压迫感、克制，不要变成夸张营销号。

硬规则：
- 不得出现英文字母或英文单词。
- 不得出现 context_packet.forbidden_terms、forbidden_story_facts 或 must_not_include 里禁止的内容。
- 不得写上下文包明确禁止的错误剧情、错误人物、错误地点或错误物件。
- 不得改动人物关系、事件结果和每句对应的 source_segment_ids。
- 不得移动、合并、拆分或错位任何一句的核心语义；如果某句不好润色，就原样返回。
- 不得新增候选文案里没有的可见动作、生理反应或听觉细节；如果 context_packet.humanize_unsafe_detail_terms、forbidden_visual_details 或 unsafe_detail_terms 列出短语，一律禁止。
- 如果 context_packet.tts_unfriendly_terms 或 bad_tts_terms 列出短语，一律禁止；默认也不要使用“说得平”“意思很明白”。
- 不得把“语气平静”这类正常说法改成“说得平”。
- 不得把保守表达改成更严重的威胁或结果；可以更口语，但不能升级事实。
- 不得新增引号来复述角色台词；如果原文有台词感，要改成第三人称解说。
- 每句尽量控制在 12 到 42 个中文字符；不要为了炫技写长句，也不要为了显得利落而丢信息。
- 输出必须是严格合法 JSON，不要 Markdown，不要解释。所有对象和数组元素之间必须有逗号，禁止尾逗号。

JSON schema:
{
  "humanize_notes": ["你主要做了哪些口播层面的改动"],
  "humanized_voiceover": [
    {
      "index": 1,
      "text": "润色后的纯中文口播句子"
    }
  ]
}
""".strip()
    context_for_prompt = compact_context_for_prompt(context_packet)
    length_requirements = voiceover_length_requirements(target_duration)
    instructions = instructions + "\n\n" + narration_rules_for_prompt(context_for_prompt)
    prompt = json.dumps(
        {
            "target_duration_seconds": target_duration,
            "length_requirements": length_requirements,
            "expected_voiceover_count": len(voiceover_items),
            "required_indexes": list(range(1, len(voiceover_items) + 1)),
            "context_packet": context_for_prompt,
            "title": voiceover_doc.get("title", ""),
            "summary": voiceover_doc.get("summary", ""),
            "voiceover": voiceover_items,
        },
        ensure_ascii=False,
    )

    print(f"Calling DashScope for humanized voiceover polish: {model}")
    from llm_providers.dashscope import text_completion

    text = text_completion(
        model=model,
        instructions=instructions,
        input_text=prompt,
        base_url=base_url,
        api_key=api_key,
    )
    result = parse_llm_json_response(text, model=model, base_url=base_url, api_key=api_key)
    rows = result.get("humanized_voiceover")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Humanize model did not return any voiceover lines.")

    by_index: dict[int, str] = {}
    rejected_rows: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Humanize model returned an invalid row.")
        index = int(row.get("index", 0))
        text = str(row.get("text", "")).strip()
        if index < 1 or index > len(voiceover_items) or not text:
            raise ValueError("Humanize model returned an invalid index or empty text.")
        if index in by_index:
            raise ValueError("Humanize model returned duplicate indexes.")
        blocked_terms = blocked_humanize_terms(text, context_packet)
        if blocked_terms:
            rejected_rows.append(f"{index}: {', '.join(blocked_terms)}")
            continue
        original_text = str(voiceover_items[index - 1].get("text", "")).strip()
        minimum_length = max(8, int(len(original_text) * 0.8))
        if len(text) < minimum_length:
            rejected_rows.append(f"{index}: too short")
            continue
        by_index[index] = text
    if rejected_rows:
        print("Rejected unsafe humanized rows: " + "; ".join(rejected_rows))

    humanized = dict(voiceover_doc)
    humanized_items: list[dict[str, Any]] = []
    for idx, item in enumerate(voiceover_doc.get("voiceover", []), start=1):
        new_item = dict(item)
        if idx in by_index:
            new_item["pre_humanize_text"] = str(item.get("text", "")).strip()
            new_item["text"] = by_index[idx]
        humanized_items.append(new_item)
    humanized["voiceover"] = humanized_items
    humanized["humanized"] = True
    humanized["humanize_model"] = model
    humanize_notes = result.get("humanize_notes", [])
    if not isinstance(humanize_notes, list):
        humanize_notes = []
    if rejected_rows:
        humanize_notes.append("自动丢弃不可靠润色句：" + "; ".join(rejected_rows))
    humanized["humanize_notes"] = humanize_notes
    return humanized


def write_humanize_diff(before_doc: dict[str, Any], after_doc: dict[str, Any], path: Path) -> None:
    before_items = before_doc.get("voiceover", []) or []
    after_items = after_doc.get("voiceover", []) or []
    lines = ["# 真人口播润色对比", ""]
    for idx, (before, after) in enumerate(zip(before_items, after_items), start=1):
        before_text = str(before.get("text", "")).strip()
        after_text = str(after.get("text", "")).strip()
        if before_text == after_text:
            continue
        lines.extend([
            f"## {idx:02d}",
            f"原文：{before_text}",
            f"润色：{after_text}",
            "",
        ])
    if len(lines) == 2:
        lines.append("本次润色没有改变文案。")
    path.write_text("\n".join(lines), encoding="utf-8")


def fallback_voiceover_script(segments: list[dict[str, Any]], target_duration: float) -> dict[str, Any]:
    target_words = max(80, int(target_duration * 2.4))
    target_cjk = max(180, int(target_duration * 4.4))
    voiceover: list[dict[str, Any]] = []
    used_words = 0
    used_cjk = 0

    for seg in segments:
        text = str(seg["text"]).strip()
        if not text:
            continue
        sentence = text
        if len(sentence) > 95:
            sentence = sentence[:93].rstrip() + "..."
        voiceover.append({
            "text": sentence,
            "source_segment_ids": [int(seg["id"])],
            "visual_note": "本地回退：使用原字幕作为临时配音文案，接通 LLM 后会改写成中文解说稿。",
        })
        used_words += len(re.findall(r"[A-Za-z0-9]+", sentence))
        used_cjk += len(re.findall(r"[\u4e00-\u9fff]", sentence))
        if used_cjk >= target_cjk or (used_words >= target_words and used_cjk == 0):
            break

    if not voiceover and segments:
        voiceover.append({
            "text": str(segments[0]["text"]),
            "source_segment_ids": [int(segments[0]["id"])],
            "visual_note": "本地回退：使用第一条字幕。",
        })

    return {
        "title": "临时配音文案",
        "summary": "OCool 不可用时生成的本地占位文案；目标是先把配音时长撑到接近设定值。",
        "voiceover": voiceover,
    }


def estimate_voiceover_duration(text: str) -> float:
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9]+", text))
    pauses = len(re.findall(r"[，。！？；,.!?;]", text)) * 0.16
    if cjk_chars:
        base = cjk_chars / 4.4
    else:
        base = latin_words / 2.4
    return max(1.3, base + pauses)


def apply_estimated_voiceover_timeline(alignment: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cursor = 0.0
    for row in alignment:
        duration = float(row.get("estimated_voiceover_duration") or estimate_voiceover_duration(row["text"]))
        row["voiceover_duration"] = round(duration, 3)
        row["voiceover_start"] = round(cursor, 3)
        row["voiceover_end"] = round(cursor + duration, 3)
        row["voiceover_audio_path"] = None
        cursor += duration
    return alignment



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


def refresh_voiceover_timeline(alignment: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cursor = 0.0
    for row in alignment:
        duration = float(row["voiceover_duration"])
        row["voiceover_start"] = round(cursor, 3)
        row["voiceover_end"] = round(cursor + duration, 3)
        cursor += duration
    return alignment


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


def limit_alignment_to_target_duration(
    alignment: list[dict[str, Any]],
    target_duration: float,
    tolerance: float = 8.0,
) -> list[dict[str, Any]]:
    if not alignment or target_duration <= 0:
        return refresh_voiceover_timeline(alignment)

    total = sum(float(row["voiceover_duration"]) for row in alignment)
    duration_limit = target_duration + tolerance
    if total <= duration_limit:
        return refresh_voiceover_timeline(alignment)

    kept: list[dict[str, Any]] = []
    cursor = 0.0
    for row in alignment:
        duration = float(row["voiceover_duration"])
        if not kept or cursor + duration <= duration_limit:
            kept.append(row)
            cursor += duration
            continue
        break

    kept_total = sum(float(row["voiceover_duration"]) for row in kept)
    print(
        f"Trimmed voiceover sentences from {len(alignment)} to {len(kept)} "
        f"to keep final duration near {target_duration:.2f}s ({kept_total:.2f}s real TTS)."
    )
    return refresh_voiceover_timeline(kept)


def simple_text_score(a: str, b: str) -> float:
    a_norm = re.sub(r"[\W_]+", "", a.lower(), flags=re.UNICODE)
    b_norm = re.sub(r"[\W_]+", "", b.lower(), flags=re.UNICODE)
    if not a_norm or not b_norm:
        return 0.0
    a_set = set(a_norm)
    b_set = set(b_norm)
    overlap = len(a_set & b_set) / max(1, len(a_set | b_set))
    containment = len(a_set & b_set) / max(1, min(len(a_set), len(b_set)))
    return overlap * 0.6 + containment * 0.4


def align_voiceover_to_transcript(
    voiceover_doc: dict[str, Any],
    segments: list[dict[str, Any]],
    target_duration: float,
) -> list[dict[str, Any]]:
    by_id = {int(seg["id"]): seg for seg in segments}
    voiceover_items = voiceover_doc.get("voiceover", [])
    aligned: list[dict[str, Any]] = []
    cursor = 0.0
    last_index = 0
    id_to_index = {int(seg["id"]): index for index, seg in enumerate(segments)}

    for sentence_id, item in enumerate(voiceover_items, start=1):
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        source_ids = []
        for raw_id in item.get("source_segment_ids", []):
            try:
                source_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if source_id in by_id:
                source_ids.append(source_id)

        if source_ids:
            matched_segments = [by_id[source_id] for source_id in sorted(set(source_ids))]
            match_score = 1.0
        else:
            best_score = -1.0
            best_range = (last_index, min(last_index + 1, len(segments)))
            for start_index in range(last_index, len(segments)):
                for window in range(1, 5):
                    end_index = min(len(segments), start_index + window)
                    if end_index <= start_index:
                        continue
                    source_text = " ".join(seg["text"] for seg in segments[start_index:end_index])
                    score = simple_text_score(text, source_text)
                    if score > best_score:
                        best_score = score
                        best_range = (start_index, end_index)
            matched_segments = segments[best_range[0]:best_range[1]]
            source_ids = [int(seg["id"]) for seg in matched_segments]
            match_score = max(0.0, best_score)

        if not matched_segments:
            continue

        last_index = max(last_index, max(id_to_index.get(source_id, last_index) for source_id in source_ids))
        source_start = min(float(seg["start"]) for seg in matched_segments)
        source_end = max(float(seg["end"]) for seg in matched_segments)
        duration = estimate_voiceover_duration(text)
        aligned.append({
            "sentence_id": sentence_id,
            "text": text,
            "source_segment_ids": source_ids,
            "source_start": round(source_start, 3),
            "source_end": round(source_end, 3),
            "source_text": " ".join(seg["text"] for seg in matched_segments),
            "match_score": round(match_score, 3),
            "estimated_voiceover_start": round(cursor, 3),
            "estimated_voiceover_end": round(cursor + duration, 3),
            "estimated_voiceover_duration": round(duration, 3),
            "visual_note": item.get("visual_note", ""),
            "context_refs": item.get("context_refs", []),
            "story_role": item.get("story_role", ""),
            "confidence": item.get("confidence"),
            "pre_humanize_text": item.get("pre_humanize_text", ""),
        })
        cursor += duration

    if not aligned:
        raise SystemExit("No voiceover sentences could be aligned to transcript.")

    estimated_total = aligned[-1]["estimated_voiceover_end"]
    if estimated_total > 0 and abs(estimated_total - target_duration) > 0.5:
        scale = target_duration / estimated_total
        cursor = 0.0
        for row in aligned:
            duration = max(1.2, row["estimated_voiceover_duration"] * scale)
            row["estimated_voiceover_start"] = round(cursor, 3)
            row["estimated_voiceover_end"] = round(cursor + duration, 3)
            row["estimated_voiceover_duration"] = round(duration, 3)
            cursor += duration

    return aligned


def build_clips_from_alignment(
    alignment: list[dict[str, Any]],
    video_duration: float,
    padding: float,
) -> list[dict[str, Any]]:
    clips: list[dict[str, Any]] = []
    for row in alignment:
        desired_duration = max(0.3, float(row["voiceover_duration"]))
        matched_start = max(0.0, float(row["source_start"]) - padding)
        matched_end = min(video_duration, float(row["source_end"]) + padding)
        if matched_end <= matched_start:
            matched_start = max(0.0, float(row["source_start"]))
            matched_end = min(video_duration, matched_start + desired_duration)

        center = (matched_start + matched_end) / 2
        start = max(0.0, center - desired_duration / 2)
        end = start + desired_duration
        if end > video_duration:
            end = video_duration
            start = max(0.0, end - desired_duration)
        duration = max(0.0, end - start)
        if duration <= 0.05:
            continue

        clips.append({
            "sentence_ids": [row["sentence_id"]],
            "sentence_text": row["text"],
            "source_segment_ids": row["source_segment_ids"],
            "source_start": round(start, 3),
            "source_end": round(end, 3),
            "duration": round(duration, 3),
            "voiceover_start": row["voiceover_start"],
            "voiceover_end": row["voiceover_end"],
            "voiceover_duration": row["voiceover_duration"],
            "voiceover_audio_path": row.get("voiceover_audio_path"),
        })

    for index, clip in enumerate(clips, start=1):
        clip["id"] = index
    return clips


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


def write_voiceover_outputs(
    voiceover_doc: dict[str, Any],
    alignment: list[dict[str, Any]],
    script_json_path: Path,
    script_txt_path: Path,
    voiceover_srt_path: Path,
) -> None:
    doc = dict(voiceover_doc)
    doc["voiceover"] = alignment
    script_json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = []
    if voiceover_doc.get("title"):
        lines.append(f"# {voiceover_doc['title']}")
    if voiceover_doc.get("summary"):
        lines.append(str(voiceover_doc["summary"]))
    if lines:
        lines.append("")
    lines.extend(row["text"] for row in alignment)
    script_txt_path.write_text("\n".join(lines), encoding="utf-8")

    srt_segments = [
        {
            "start": row.get("voiceover_start", row["estimated_voiceover_start"]),
            "end": row.get("voiceover_end", row["estimated_voiceover_end"]),
            "speaker": "",
            "text": row["text"],
        }
        for row in alignment
    ]
    write_srt(srt_segments, voiceover_srt_path)


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Voiceover-first video slicing demo: script -> transcript alignment -> real TTS duration -> final narrated cut.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Input video path.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory.")
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

    video_duration = ffprobe_duration(video_path)
    print(f"Input video duration: {video_duration:.2f}s")

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
    print(f"Wrote time mapping: {mapping_path}")
    print(f"Visual duration: {actual_visual_duration:.2f}s")
    print(f"Real voiceover duration: {actual_voiceover_duration:.2f}s")


def main(argv: list[str] | None = None) -> None:
    load_dotenv(Path(".env"))
    parser = build_parser()
    args = parser.parse_args(argv)
    run_cli(args)


if __name__ == "__main__":
    main()
