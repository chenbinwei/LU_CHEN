import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_INPUT = "videos/demo_lhq.mp4"
DEFAULT_OUTPUT_DIR = "outputs"
DEFAULT_CONTEXT_PATH = "context.json"
DEFAULT_OCOOL_BASE_URL = "https://one.ocoolai.com/v1"
DEFAULT_OCOOL_MODEL = "gpt-5.4-2026-03-05"


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




def load_context_packet(path: Path | None) -> dict[str, Any]:
    if path is None or not str(path).strip():
        return {}
    if not path.exists():
        print(f"Context packet not found, continue without it: {path}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid context packet JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Context packet must be a JSON object: {path}")
    data = dict(data)
    data["_context_path"] = str(path)
    print(f"Loaded context packet: {path}")
    return data


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




def forbidden_terms_from_context(context_packet: dict[str, Any] | None) -> list[str]:
    context_packet = context_packet or {}
    terms = ["birds", "bird", "VOICEOVER"]
    for key in ("forbidden_terms", "forbidden_story_facts", "must_not_include"):
        value = context_packet.get(key)
        if isinstance(value, list):
            terms.extend(str(item) for item in value if str(item).strip())
        elif isinstance(value, str) and value.strip():
            terms.append(value)
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

    lowered = text.lower()
    blocked = [term for term in forbidden_terms_from_context(context_packet) if term and term.lower() in lowered]
    if blocked:
        raise SystemExit("Voiceover text contains forbidden terms: " + ", ".join(blocked))
def select_clips_with_llm(
    segments: list[dict[str, Any]],
    target_duration: float,
    video_duration: float,
    model: str,
    base_url: str,
) -> dict[str, Any] | None:
    api_key = os.environ.get("OCOOL_API_KEY")
    if not api_key:
        print("OCOOL_API_KEY is empty. Using rule-based clip selection.")
        return None

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit(
            "OpenAI SDK is required for OCool calls. Run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from exc

    client = OpenAI(api_key=api_key, base_url=base_url)
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

    print(f"Calling OCool model: {model}")
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=prompt,
    )
    text = extract_response_text(response)
    return parse_json_response(text)


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
        "summary": "Rule-based fallback selection. Add OCOOL_API_KEY for semantic clip selection.",
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
    api_key = os.environ.get("OCOOL_API_KEY")
    if not api_key or api_key == "put_your_ocool_api_key_here":
        print("OCOOL_API_KEY is empty. Using local fallback voiceover draft.")
        return None

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit(
            "OpenAI SDK is required for OCool calls. Run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from exc

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
- 可以使用 context_packet 中明确给出的名字、人物关系、背景，例如“刘华强”。
- 如果字幕和 context_packet 都没有提供某个事实，不能编造；宁可写“这个男人”“对方”“主角”。
- 不要把外部常识当作视频事实，除非 allowed_external_knowledge 明确提供。
- 每句配音必须绑定 source_segment_ids，后续程序会按这些片段反查原视频画面。
- 每句配音如果使用了上下文包的信息，必须在 context_refs 中写明引用的字段或实体名。
- source_segment_ids 必须来自 transcript，尽量连续；整体故事按原视频时序推进，除非开头 hook 需要短暂前置高能片段。
- 文案要适合配音，短句为主，有节奏，有口语感，不要复述字幕，不要写成影评论文。
- 严禁出现英文字母或英文单词；如果候选里有英文，必须改成纯中文。
- 必须遵守 context_packet.correct_synopsis、forbidden_terms、forbidden_story_facts；如果用户说明没有买瓜剧情，绝不能写买瓜、瓜摊、瓜摊老板、西瓜、保熟等内容。
- 如果 context_packet.forbidden_terms 中的任何词出现在候选文案里，必须改写到完全不出现。
- voiceover 必须输出 20 到 35 条短句；每条对应一个可剪辑画面，不要写成长段落。
- 每句 10 到 32 个中文字符为宜；总字数按 target_duration_seconds 控制。
- 不要为了凑时长硬写废话，宁可让每句更有信息密度。

只输出 JSON，不要输出 Markdown，不要输出解释。
JSON schema:
{
  "title": "短标题",
  "summary": "一句话概括这个切片故事",
  "story_plan": [
    {
      "role": "hook/setup/conflict/escalation/turning_point/payoff",
      "description": "这一段讲什么、为什么要放进切片",
      "source_segment_ids": [1, 2, 3],
      "context_refs": ["video_title", "known_people.刘华强"]
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
    prompt = json.dumps(
        {
            "target_duration_seconds": target_duration,
            "context_packet": context_packet,
            "transcript": transcript,
        },
        ensure_ascii=False,
    )

    print(f"Calling OCool for voiceover script: {model}")
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=prompt,
    )
    return parse_json_response(extract_response_text(response))




def review_voiceover_with_llm(
    voiceover_doc: dict[str, Any],
    segments: list[dict[str, Any]],
    target_duration: float,
    model: str,
    base_url: str,
    context_packet: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    api_key = os.environ.get("OCOOL_API_KEY")
    if not api_key or api_key == "put_your_ocool_api_key_here":
        print("OCOOL_API_KEY is empty. Skip semantic review.")
        return None

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit(
            "OpenAI SDK is required for OCool calls. Run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from exc

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
5. TTS 可读性：避免生僻符号、英文缩写、过长句；数字和称谓要适合直接念出来。所有最终文案必须是纯中文和中文标点，不允许出现英文字母。
6. 画面想象：每句文案都要能对应到原片画面，visual_note 要说明用什么画面支撑这句话。

严格规则：
- 不要编造 transcript 和 context_packet 都没有的信息。
- 可以补充 context_packet.allowed_external_knowledge 明确允许的背景，但必须在 context_refs 中标注。
- 不要输出“本片讲了”“视频中可以看到”这类空泛话术，要直接讲故事。
- 必须检查 context_packet.correct_synopsis、forbidden_terms、forbidden_story_facts，违反则重写。
- 每句 source_segment_ids 必须来自 transcript；如调整文案，也要保留或修正对应来源。
- 保持总时长接近 target_duration_seconds；120 秒目标通常需要 20 到 35 条短句，不要合并成长段。
- 优先保证故事质量和信息密度。
- 输出必须是完整 JSON，不要 Markdown，不要解释。

返回 JSON schema 与候选脚本一致，但必须额外包含：
{
  "reviewed": true,
  "review_notes": ["你做了哪些重要修正"],
  "read_aloud_checks": ["说明口播/TTS 层面已检查的点"]
}
""".strip()
    prompt = json.dumps(
        {
            "target_duration_seconds": target_duration,
            "context_packet": context_packet or {},
            "transcript": transcript,
            "candidate_script": voiceover_doc,
        },
        ensure_ascii=False,
    )

    print(f"Calling OCool for semantic script review: {model}")
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=prompt,
    )
    reviewed = parse_json_response(extract_response_text(response))
    if not isinstance(reviewed.get("voiceover"), list) or not reviewed["voiceover"]:
        raise ValueError("Semantic review did not return a non-empty voiceover list.")
    reviewed["reviewed"] = True
    reviewed["review_model"] = model
    return reviewed


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


def windows_powershell_path() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if candidate.exists():
        return str(candidate)
    return "powershell"


def generate_windows_tts_batch(
    items: list[dict[str, Any]],
    manifest_path: Path,
    voice_name: str,
    rate: int,
    volume: int,
) -> None:
    if not items:
        return

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    script_path = manifest_path.with_name("synthesize_windows_tts.ps1")
    script_path.write_text(
        r'''
param(
    [Parameter(Mandatory=$true)][string]$ManifestPath,
    [string]$VoiceName = "",
    [int]$Rate = 0,
    [int]$Volume = 100
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$items = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $selected = $false
    if (-not [string]::IsNullOrWhiteSpace($VoiceName)) {
        try {
            $synth.SelectVoice($VoiceName)
            $selected = $true
        } catch {
            Write-Warning ("Requested voice not available: " + $VoiceName)
        }
    }
    if (-not $selected) {
        $zhVoice = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like "zh*" } | Select-Object -First 1
        if ($zhVoice -ne $null) {
            $synth.SelectVoice($zhVoice.VoiceInfo.Name)
        }
    }
    $synth.Rate = [Math]::Max(-10, [Math]::Min(10, $Rate))
    $synth.Volume = [Math]::Max(0, [Math]::Min(100, $Volume))
    foreach ($item in $items) {
        $outPath = [string]$item.path
        $outDir = Split-Path -Parent $outPath
        if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
            New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        }
        $synth.SetOutputToWaveFile($outPath)
        try {
            [void]$synth.Speak([string]$item.text)
        } finally {
            $synth.SetOutputToNull()
        }
    }
} finally {
    $synth.Dispose()
}
'''.strip() + "\n",
        encoding="utf-8",
    )
    run([
        windows_powershell_path(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-ManifestPath",
        str(manifest_path.resolve()),
        "-VoiceName",
        voice_name,
        "-Rate",
        str(max(-10, min(10, int(rate)))),
        "-Volume",
        str(max(0, min(100, int(volume)))),
    ])


def generate_ocool_tts_batch(
    items: list[dict[str, Any]],
    model: str,
    voice: str,
    base_url: str,
    speed: float,
) -> None:
    if not items:
        return
    api_key = os.environ.get("OCOOL_API_KEY")
    if not api_key or api_key == "put_your_ocool_api_key_here":
        raise SystemExit("OCOOL_API_KEY is required for --tts-mode ocool.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit(
            "OpenAI SDK is required for OCool TTS. Run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from exc

    client = OpenAI(api_key=api_key, base_url=base_url)
    for item in items:
        out_path = Path(str(item["path"]))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        text = str(item["text"]).strip()
        print(f"Calling OCool TTS: sentence {item.get('sentence_id')} -> {out_path.name}")
        try:
            with client.audio.speech.with_streaming_response.create(
                model=model,
                voice=voice,
                input=text,
                response_format="mp3",
                speed=max(0.25, min(4.0, float(speed))),
            ) as response:
                response.stream_to_file(out_path)
        except AttributeError:
            response = client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                response_format="mp3",
                speed=max(0.25, min(4.0, float(speed))),
            )
            response.write_to_file(out_path)


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
    base_url: str,
    ocool_tts_model: str,
    ocool_tts_voice: str,
    ocool_tts_speed: float,
    windows_voice_name: str,
    rate: int,
    volume: int,
    force: bool,
) -> list[dict[str, Any]]:
    if tts_mode not in {"ocool", "windows"}:
        raise SystemExit(f"Unsupported TTS mode for sentence audio: {tts_mode}")

    audio_dir = output_dir / "voiceover_clips"
    audio_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = audio_dir / "tts_manifest.json"
    batch_manifest_path = audio_dir / "tts_batch.json"
    suffix = ".mp3" if tts_mode == "ocool" else ".wav"

    previous_by_sentence: dict[int, dict[str, Any]] = {}
    if metadata_path.exists():
        try:
            previous = json.loads(metadata_path.read_text(encoding="utf-8"))
            previous_by_sentence = {int(item["sentence_id"]): item for item in previous.get("items", [])}
        except Exception:
            previous_by_sentence = {}

    expected_items: list[dict[str, Any]] = []
    batch_items: list[dict[str, Any]] = []
    for row in alignment:
        sentence_id = int(row["sentence_id"])
        text = str(row["text"]).strip()
        audio_path = audio_dir / f"voice_{sentence_id:03}{suffix}"
        expected = {
            "sentence_id": sentence_id,
            "text": text,
            "path": str(audio_path),
            "engine": tts_mode,
            "model": ocool_tts_model if tts_mode == "ocool" else "windows_system_speech",
            "voice": ocool_tts_voice if tts_mode == "ocool" else windows_voice_name,
            "speed": ocool_tts_speed if tts_mode == "ocool" else 1.0,
        }
        expected_items.append(expected)
        previous = previous_by_sentence.get(sentence_id)
        needs_render = (
            force
            or not audio_path.exists()
            or previous is None
            or previous.get("text") != text
            or previous.get("path") != str(audio_path)
            or previous.get("engine") != tts_mode
            or previous.get("model") != expected["model"]
            or previous.get("voice") != expected["voice"]
            or float(previous.get("speed", 1.0)) != float(expected["speed"])
        )
        if needs_render:
            batch_items.append({
                "sentence_id": sentence_id,
                "text": text,
                "path": str(audio_path.resolve()),
            })

    if batch_items:
        if tts_mode == "ocool":
            print(f"Generating {len(batch_items)} sentence voiceover files with OCool TTS.")
            generate_ocool_tts_batch(batch_items, ocool_tts_model, ocool_tts_voice, base_url, ocool_tts_speed)
        else:
            print(f"Generating {len(batch_items)} sentence voiceover wav files with Windows TTS.")
            generate_windows_tts_batch(batch_items, batch_manifest_path, windows_voice_name, rate, volume)
    else:
        print("Sentence voiceover files exist, skip TTS generation.")

    metadata_path.write_text(
        json.dumps({"engine": tts_mode, "items": expected_items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    cursor = 0.0
    for row in alignment:
        sentence_id = int(row["sentence_id"])
        audio_path = audio_dir / f"voice_{sentence_id:03}{suffix}"
        if not audio_path.exists():
            raise SystemExit(f"Voiceover audio was not generated: {audio_path}")
        duration = ffprobe_duration_media(audio_path)
        if duration <= 0:
            raise SystemExit(f"Voiceover audio has invalid duration: {audio_path}")
        row["voiceover_audio_path"] = str(audio_path)
        row["voiceover_duration"] = round(duration, 3)
        row["voiceover_start"] = round(cursor, 3)
        row["voiceover_end"] = round(cursor + duration, 3)
        row["tts_mode"] = tts_mode
        cursor += duration
    return alignment


def refresh_voiceover_timeline(alignment: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cursor = 0.0
    for row in alignment:
        duration = float(row["voiceover_duration"])
        row["voiceover_start"] = round(cursor, 3)
        row["voiceover_end"] = round(cursor + duration, 3)
        cursor += duration
    return alignment


def limit_alignment_to_target_duration(
    alignment: list[dict[str, Any]],
    target_duration: float,
    tolerance: float = 3.0,
) -> list[dict[str, Any]]:
    if not alignment or target_duration <= 0:
        return refresh_voiceover_timeline(alignment)

    total = sum(float(row["voiceover_duration"]) for row in alignment)
    if total <= target_duration + tolerance:
        return refresh_voiceover_timeline(alignment)

    kept: list[dict[str, Any]] = []
    cursor = 0.0
    for row in alignment:
        duration = float(row["voiceover_duration"])
        if not kept or cursor + duration <= target_duration + tolerance:
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
def main() -> None:
    load_dotenv(Path(".env"))
    parser = argparse.ArgumentParser(description="Voiceover-first video slicing demo: script -> transcript alignment -> real TTS duration -> final narrated cut.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Input video path.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory.")
    parser.add_argument("--context", default=DEFAULT_CONTEXT_PATH, help="Optional context packet JSON path. Use this to provide title, people, background, and story constraints.")
    parser.add_argument("--target-duration", type=float, default=120.0, help="Target voiceover/video duration in seconds.")
    parser.add_argument("--model-size", default="small", help="faster-whisper model size: tiny/base/small/medium/large-v3.")
    parser.add_argument("--device", default="cpu", help="Whisper device: cpu or cuda.")
    parser.add_argument("--compute-type", default="int8", help="Whisper compute type, e.g. int8, float16.")
    parser.add_argument("--language", default=None, help="Optional speech language, e.g. zh, en. Default: auto detect.")
    parser.add_argument("--ocool-base-url", default=os.environ.get("OCOOL_BASE_URL", DEFAULT_OCOOL_BASE_URL))
    parser.add_argument("--ocool-model", default=os.environ.get("OCOOL_MODEL", DEFAULT_OCOOL_MODEL))
    parser.add_argument("--padding", type=float, default=0.25, help="Seconds to pad matched source visual clips.")
    parser.add_argument("--tts-mode", choices=["ocool", "windows", "none"], default=os.environ.get("TTS_MODE", "ocool"), help="Generate per-sentence voiceover. Use 'ocool' for API TTS, 'windows' for local fallback, or 'none' for script/silent preview only.")
    parser.add_argument("--tts-voice", default=os.environ.get("WINDOWS_TTS_VOICE", "Microsoft Huihui Desktop"), help="Windows TTS voice name. If unavailable, a Chinese installed voice or system default is used.")
    parser.add_argument("--tts-rate", type=int, default=int(os.environ.get("WINDOWS_TTS_RATE", "0")), help="Windows TTS rate from -10 to 10.")
    parser.add_argument("--tts-volume", type=int, default=int(os.environ.get("WINDOWS_TTS_VOLUME", "100")), help="Windows TTS volume from 0 to 100.")
    parser.add_argument("--ocool-tts-model", default=os.environ.get("OCOOL_TTS_MODEL", "tts-1-hd"), help="OpenAI-compatible TTS model for --tts-mode ocool.")
    parser.add_argument("--ocool-tts-voice", default=os.environ.get("OCOOL_TTS_VOICE", "echo"), help="OpenAI-compatible TTS voice for --tts-mode ocool.")
    parser.add_argument("--ocool-tts-speed", type=float, default=float(os.environ.get("OCOOL_TTS_SPEED", "1.0")), help="OpenAI-compatible TTS speed. Use around 0.75 when tts-1-hd reads too fast for a 120s target.")
    parser.add_argument("--force-tts", action="store_true", help="Regenerate per-sentence TTS wav files even if they already exist.")
    parser.add_argument("--force-transcribe", action="store_true", help="Re-run Whisper even if transcript exists.")
    parser.add_argument("--force-audio", action="store_true", help="Re-extract audio even if audio.wav exists.")
    parser.add_argument("--force-script", action="store_true", help="Regenerate voiceover script even if voiceover_script.json exists.")
    parser.add_argument("--no-llm", action="store_true", help="Do not call OCool, use local fallback voiceover draft.")
    parser.add_argument("--require-llm", action="store_true", help="Fail instead of using fallback when OCool script generation fails.")
    parser.add_argument("--skip-review", action="store_true", help="Skip the second LLM semantic/read-aloud review pass before TTS.")
    parser.add_argument("--force-review", action="store_true", help="Review the script again even if voiceover_script.json is already marked reviewed.")
    parser.add_argument("--voiceover-audio", default=None, help="Optional narration audio path to mux into final_with_voiceover.mp4.")
    args = parser.parse_args()

    if args.no_llm and args.require_llm:
        raise SystemExit("--no-llm and --require-llm cannot be used together.")

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
        saved = json.loads(script_json_path.read_text(encoding="utf-8"))
        voiceover_doc = dict(saved)
        voiceover_doc["voiceover"] = [
            {
                "text": item["text"],
                "source_segment_ids": item.get("source_segment_ids", []),
                "context_refs": item.get("context_refs", []),
                "story_role": item.get("story_role", ""),
                "confidence": item.get("confidence"),
                "visual_note": item.get("visual_note", ""),
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
                    model=args.ocool_model,
                    base_url=args.ocool_base_url,
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
                model=args.ocool_model,
                base_url=args.ocool_base_url,
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
    if args.tts_mode in {"ocool", "windows"}:
        alignment = prepare_sentence_audio(
            alignment=alignment,
            output_dir=output_dir,
            tts_mode=args.tts_mode,
            base_url=args.ocool_base_url,
            ocool_tts_model=args.ocool_tts_model,
            ocool_tts_voice=args.ocool_tts_voice,
            ocool_tts_speed=args.ocool_tts_speed,
            windows_voice_name=args.tts_voice,
            rate=args.tts_rate,
            volume=args.tts_volume,
            force=args.force_tts,
        )
    else:
        print("TTS disabled. The final narrated video will not be rendered unless --voiceover-audio is provided.")
        alignment = apply_estimated_voiceover_timeline(alignment)

    alignment = limit_alignment_to_target_duration(alignment, args.target_duration)
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
        "mode": "voiceover_first_real_tts_cut" if args.tts_mode in {"ocool", "windows"} else "voiceover_first_silent_cut",
        "tts_mode": args.tts_mode,
        "target_duration": args.target_duration,
        "actual_visual_duration": actual_visual_duration,
        "actual_voiceover_duration": actual_voiceover_duration,
        "estimated_voiceover_duration": alignment[-1].get("estimated_voiceover_end"),
        "title": voiceover_doc.get("title", ""),
        "summary": voiceover_doc.get("summary", ""),
        "context_packet": context_packet,
        "clips": clips,
    }
    selected_path.write_text(json.dumps(selected_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    output_video = clip_video_silent(video_path, output_dir, clips)
    write_visual_time_mapping(clips, mapping_path)

    final_path: Path | None = None
    if args.tts_mode in {"ocool", "windows"}:
        final_path = render_clips_with_voiceover(video_path, output_dir, clips)
    elif args.voiceover_audio:
        final_path = output_dir / "final_with_voiceover.mp4"
        mux_voiceover_audio(output_video, Path(args.voiceover_audio), final_path)

    print(f"Wrote silent preview video: {output_video}")
    if final_path:
        print(f"Wrote final narrated video: {final_path}")
    print(f"Wrote voiceover script: {script_txt_path}")
    print(f"Wrote voiceover JSON: {script_json_path}")
    print(f"Wrote voiceover subtitles: {voiceover_srt_path}")
    print(f"Wrote alignment: {alignment_path}")
    print(f"Wrote time mapping: {mapping_path}")
    print(f"Visual duration: {actual_visual_duration:.2f}s")
    print(f"Real voiceover duration: {actual_voiceover_duration:.2f}s")


if __name__ == "__main__":
    main()







