"""Voiceover script generation, review, validation, and output helpers."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from video_slicer.context_packet import (
    compact_context_for_prompt,
    narration_rules_for_prompt,
)


def print_safe(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(message.encode(encoding, errors="backslashreplace").decode(encoding))


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
- 每条必须给 source_segment_ids，id 必须来自 transcript，并按原片时间顺序推进；不要为了开头钩子倒跳到后段高能画面。
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
            if len(text) <= 14 and (
                roleplay_pattern.search(text)
                or command_pattern.search(text)
                or text.endswith(("？", "?", "！", "!"))
            )
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
            sentence = sentence[:93].rstrip() + "……"
        voiceover.append({
            "text": sentence,
            "source_segment_ids": [int(seg["id"])],
            "visual_note": "本地回退：使用原字幕作为临时配音文案，接通大模型后会改写成中文解说稿。",
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
        "summary": "大模型不可用时生成的本地占位文案；目标是先把配音时长撑到接近设定值。",
        "voiceover": voiceover,
    }

def transcript_for_prompt(segments: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for seg in segments:
        rows.append(
            f"[{seg['id']}] {seg['start']:.3f}-{seg['end']:.3f} "
            f"{seg.get('speaker', 'UNKNOWN')}: {seg['text']}"
        )
    return "\n".join(rows)

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
- source_segment_ids 必须来自 transcript，尽量连续；整体故事和画面选择都按原视频时序推进，不要为了开头 hook 前置后段高能片段。
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
        print_safe("Rejected unsafe humanized rows: " + "; ".join(rejected_rows))

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

