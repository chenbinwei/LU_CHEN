"""Context packet loading, validation, and prompt shaping.

The context packet is project data: facts, constraints, and creative direction
that can later be edited from a frontend.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


DEFAULT_NARRATION_RULES: dict[str, Any] = {
    "point_of_view": "third_person_commentary",
    "narrator_role": "professional_film_commentator",
    "forbid_first_person_roleplay": True,
    "forbid_dialogue_reenactment": True,
    "forbid_direct_dialogue_as_voiceover": True,
    "dialogue_quote_policy": "Only mention very short iconic lines as reported facts; do not perform the character's dialogue.",
    "must_tell_story_not_subtitles": True,
    "story_requirements": [
        "开头先抛出冲突和悬念",
        "用第三人称交代人物关系和场景",
        "按冲突升级讲清楚人物心理变化",
        "用画面和表演细节支撑判断",
        "结尾落在片段的名场面意义上",
    ],
    "voiceover_must_not": [
        "让配音演员扮演角色说话",
        "连续复述原片台词",
        "把角色台词改写成第一人称旁白",
        "用大段问句和命令句冒充解说",
    ],
}


FRONTEND_CONTEXT_FIELDS: list[dict[str, Any]] = [
    {"key": "title", "label": "视频标题", "type": "text", "required": True},
    {"key": "source_type", "label": "素材类型", "type": "select"},
    {"key": "characters", "label": "人物列表", "type": "character_list"},
    {"key": "correct_synopsis", "label": "正确剧情梗概", "type": "textarea", "required": True},
    {"key": "story_focus", "label": "切片重点", "type": "string_list"},
    {"key": "style", "label": "解说风格", "type": "object"},
    {"key": "narration_rules", "label": "叙事规则", "type": "object"},
    {"key": "allowed_external_knowledge", "label": "允许使用的外部背景", "type": "string_list"},
    {"key": "forbidden_terms", "label": "禁用词", "type": "string_list"},
    {"key": "forbidden_story_facts", "label": "禁止剧情", "type": "string_list"},
    {"key": "must_not_include", "label": "其他禁止内容", "type": "string_list"},
    {"key": "humanize_unsafe_detail_terms", "label": "禁止脑补画面细节", "type": "string_list"},
    {"key": "tts_unfriendly_terms", "label": "TTS 易读错表达", "type": "string_list"},
]


def load_context_packet(path: Path | None) -> dict[str, Any]:
    if path is None or not str(path).strip():
        return normalize_context_packet({})
    if not path.exists():
        print(f"Context packet not found, continue without it: {path}")
        return normalize_context_packet({})
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid context packet JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Context packet must be a JSON object: {path}")
    packet = normalize_context_packet(data)
    packet["_context_path"] = str(path)
    print(f"Loaded context packet: {path}")
    return packet


def normalize_context_packet(packet: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(packet or {})
    rules = copy.deepcopy(DEFAULT_NARRATION_RULES)
    custom_rules = source.get("narration_rules")
    if isinstance(custom_rules, dict):
        rules = merge_dicts(rules, custom_rules)
    source["narration_rules"] = rules
    return source


def merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def compact_context_for_prompt(packet: dict[str, Any] | None) -> dict[str, Any]:
    normalized = normalize_context_packet(packet or {})
    keep_keys = (
        "_context_path",
        "title",
        "source_type",
        "series",
        "characters",
        "correct_synopsis",
        "story_focus",
        "style",
        "narration_rules",
        "allowed_external_knowledge",
        "forbidden_terms",
        "forbidden_story_facts",
        "must_not_include",
        "humanize_unsafe_detail_terms",
        "forbidden_visual_details",
        "unsafe_detail_terms",
        "tts_unfriendly_terms",
        "bad_tts_terms",
    )
    return {key: normalized[key] for key in keep_keys if key in normalized}


def narration_rules_for_prompt(packet: dict[str, Any] | None) -> str:
    rules = normalize_context_packet(packet or {}).get("narration_rules", {})
    story_requirements = rules.get("story_requirements") or []
    must_not = rules.get("voiceover_must_not") or []

    lines = [
        "叙事规则：",
        f"- 叙事视角：{rules.get('point_of_view', 'third_person_commentary')}，必须是第三人称影视解说旁白。",
        f"- 旁白身份：{rules.get('narrator_role', 'professional_film_commentator')}，不要扮演片中角色。",
    ]
    if rules.get("forbid_first_person_roleplay", True):
        lines.append("- 禁止第一人称角色扮演；配音不能像片中角色本人在说话。")
    if rules.get("forbid_dialogue_reenactment", True):
        lines.append("- 禁止把原片台词连续改写成配音稿；要讲发生了什么、为什么有压迫感。")
    if rules.get("forbid_direct_dialogue_as_voiceover", True):
        lines.append("- 禁止大量使用第一人称、第二人称、命令句或问答句作为 voiceover。")
    quote_policy = str(rules.get("dialogue_quote_policy", "")).strip()
    if quote_policy:
        lines.append(f"- 台词引用规则：{quote_policy}")
    if story_requirements:
        lines.append("- 故事必须覆盖：" + "；".join(str(item) for item in story_requirements if str(item).strip()))
    if must_not:
        lines.append("- 旁白禁止：" + "；".join(str(item) for item in must_not if str(item).strip()))
    return "\n".join(lines)


def frontend_context_schema() -> dict[str, Any]:
    return {
        "version": 1,
        "fields": FRONTEND_CONTEXT_FIELDS,
        "default_narration_rules": DEFAULT_NARRATION_RULES,
    }
