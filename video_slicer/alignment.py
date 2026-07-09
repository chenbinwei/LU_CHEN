"""Voiceover-to-transcript alignment and visual clip selection."""

from __future__ import annotations

import re
from typing import Any


LOW_EVIDENCE_SCORE_THRESHOLD = 0.08
MAX_ADJACENT_SOURCE_OVERLAP_SECONDS = 2.0
LONG_SOURCE_SPAN_MIN_SECONDS = 12.0
LONG_SOURCE_SPAN_DURATION_MULTIPLIER = 3.0
SOURCE_ORDER_POLICY = "monotonic"
TRUST_LLM_PROVIDED = "llm_provided"
TRUST_FALLBACK_MATCHED = "fallback_matched"
TRUST_ORDERED_FALLBACK = "llm_replaced_by_ordered_fallback"
TRUST_CONTINUITY_VISUAL_SUPPORT = "continuity_visual_support"
WARNING_REPLACED_FOR_ORDER = "replaced_to_preserve_source_order"
WARNING_REPLACED_LOW_SCORE = "llm_source_ids_replaced_low_score"
WARNING_LOW_EVIDENCE_CONTINUITY = "low_evidence_continuity_visual_support"
SOURCE_SPAN_START_ANCHOR_ROLES = {"hook", "setup"}
SOURCE_SPAN_END_ANCHOR_ROLES = {"escalation", "turning_point", "payoff"}


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


def score_source_evidence(text: str, source_text: str) -> float:
    return round(simple_text_score(text, source_text), 3)


def evidence_warning_for_score(score: float) -> str:
    if score < LOW_EVIDENCE_SCORE_THRESHOLD:
        return "low_text_evidence_overlap"
    return ""


def find_best_ordered_match(
    text: str,
    segments: list[dict[str, Any]],
    start_index: int,
    window_limit: int = 4,
) -> list[dict[str, Any]]:
    if not segments:
        return []

    safe_start_index = min(max(0, start_index), len(segments) - 1)
    best_score = -1.0
    best_range = (safe_start_index, min(safe_start_index + 1, len(segments)))
    for current_start in range(safe_start_index, len(segments)):
        for window in range(1, window_limit + 1):
            end_index = min(len(segments), current_start + window)
            if end_index <= current_start:
                continue
            source_text = " ".join(seg["text"] for seg in segments[current_start:end_index])
            score = simple_text_score(text, source_text)
            if score > best_score:
                best_score = score
                best_range = (current_start, end_index)
    return segments[best_range[0]:best_range[1]]


def minimum_timeline_span_for_durations(durations: list[float]) -> float:
    if not durations:
        return 0.0
    reusable_overlap = MAX_ADJACENT_SOURCE_OVERLAP_SECONDS * max(0, len(durations) - 1)
    return max(0.0, sum(durations) - reusable_overlap)


def latest_start_bounds_for_durations(durations: list[float], video_duration: float) -> list[float]:
    latest_starts = [0.0 for _ in durations]
    for index in range(len(durations) - 1, -1, -1):
        duration = durations[index]
        latest_from_video_end = max(0.0, video_duration - duration)
        if index == len(durations) - 1:
            latest_start = latest_from_video_end
        else:
            latest_from_next_clip = latest_starts[index + 1] - duration + MAX_ADJACENT_SOURCE_OVERLAP_SECONDS
            latest_start = min(latest_from_video_end, latest_from_next_clip)
        latest_starts[index] = max(0.0, latest_start)
    return latest_starts


def choose_visual_window_for_row(
    row: dict[str, Any],
    desired_duration: float,
    video_duration: float,
    padding: float,
) -> tuple[float, float, str]:
    matched_start = max(0.0, float(row["source_start"]) - padding)
    matched_end = min(video_duration, float(row["source_end"]) + padding)
    if matched_end <= matched_start:
        matched_start = max(0.0, float(row["source_start"]))
        matched_end = min(video_duration, matched_start + desired_duration)

    source_span = matched_end - matched_start
    long_span_threshold = max(LONG_SOURCE_SPAN_MIN_SECONDS, desired_duration * LONG_SOURCE_SPAN_DURATION_MULTIPLIER)
    role = str(row.get("story_role", "")).strip().lower()
    if source_span > long_span_threshold and role in SOURCE_SPAN_START_ANCHOR_ROLES:
        start = matched_start
        end = min(video_duration, start + desired_duration)
        return start, end, "anchored_to_source_span_start"
    if source_span > long_span_threshold and role in SOURCE_SPAN_END_ANCHOR_ROLES:
        end = matched_end
        start = max(0.0, end - desired_duration)
        return start, end, "anchored_to_source_span_end"

    center = (matched_start + matched_end) / 2
    start = max(0.0, center - desired_duration / 2)
    end = start + desired_duration
    if end > video_duration:
        end = video_duration
        start = max(0.0, end - desired_duration)
    return start, end, "centered_on_source_evidence"


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

        original_source_ids = sorted(set(source_ids), key=lambda source_id: id_to_index.get(source_id, 0))
        replacement_warning = ""
        if source_ids:
            matched_segments = [by_id[source_id] for source_id in original_source_ids]
            source_ids = original_source_ids
            source_id_trust = TRUST_LLM_PROVIDED
            source_indexes = [id_to_index[source_id] for source_id in source_ids if source_id in id_to_index]
            source_text = " ".join(seg["text"] for seg in matched_segments)
            match_score = score_source_evidence(text, source_text)
            backtracks_source_order = bool(source_indexes) and min(source_indexes) < last_index
            low_evidence_score = match_score < LOW_EVIDENCE_SCORE_THRESHOLD
            if backtracks_source_order:
                fallback_segments = find_best_ordered_match(text, segments, last_index)
                fallback_source_ids = [int(seg["id"]) for seg in fallback_segments]
                if fallback_segments and fallback_source_ids != source_ids:
                    matched_segments = fallback_segments
                    source_ids = fallback_source_ids
                    source_id_trust = TRUST_ORDERED_FALLBACK
                    replacement_warning = WARNING_REPLACED_FOR_ORDER
            elif low_evidence_score:
                fallback_segments = find_best_ordered_match(text, segments, last_index)
                fallback_source_ids = [int(seg["id"]) for seg in fallback_segments]
                fallback_text = " ".join(seg["text"] for seg in fallback_segments)
                fallback_score = score_source_evidence(text, fallback_text)
                if (
                    fallback_segments
                    and fallback_source_ids != source_ids
                    and fallback_score >= LOW_EVIDENCE_SCORE_THRESHOLD
                ):
                    matched_segments = fallback_segments
                    source_ids = fallback_source_ids
                    source_id_trust = TRUST_ORDERED_FALLBACK
                    replacement_warning = WARNING_REPLACED_LOW_SCORE
                else:
                    source_id_trust = TRUST_CONTINUITY_VISUAL_SUPPORT
                    replacement_warning = WARNING_LOW_EVIDENCE_CONTINUITY
        else:
            matched_segments = find_best_ordered_match(text, segments, last_index)
            source_ids = [int(seg["id"]) for seg in matched_segments]
            source_id_trust = TRUST_FALLBACK_MATCHED

        if not matched_segments:
            continue

        last_index = max(last_index, max(id_to_index.get(source_id, last_index) for source_id in source_ids))
        source_start = min(float(seg["start"]) for seg in matched_segments)
        source_end = max(float(seg["end"]) for seg in matched_segments)
        source_text = " ".join(seg["text"] for seg in matched_segments)
        match_score = score_source_evidence(text, source_text)
        duration = estimate_voiceover_duration(text)
        row = {
            "sentence_id": sentence_id,
            "text": text,
            "source_segment_ids": source_ids,
            "source_start": round(source_start, 3),
            "source_end": round(source_end, 3),
            "source_text": source_text,
            "match_score": match_score,
            "source_id_trust": source_id_trust,
            "source_order_policy": SOURCE_ORDER_POLICY,
            "evidence_warning": replacement_warning or evidence_warning_for_score(match_score),
            "estimated_voiceover_start": round(cursor, 3),
            "estimated_voiceover_end": round(cursor + duration, 3),
            "estimated_voiceover_duration": round(duration, 3),
            "visual_note": item.get("visual_note", ""),
            "context_refs": item.get("context_refs", []),
            "story_role": item.get("story_role", ""),
            "confidence": item.get("confidence"),
            "pre_humanize_text": item.get("pre_humanize_text", ""),
        }
        if source_id_trust in {TRUST_ORDERED_FALLBACK, TRUST_CONTINUITY_VISUAL_SUPPORT}:
            row["original_source_segment_ids"] = original_source_ids
        aligned.append(row)
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
    previous_source_start: float | None = None
    previous_source_end: float | None = None
    desired_durations = [max(0.3, float(row["voiceover_duration"])) for row in alignment]
    latest_start_bounds = latest_start_bounds_for_durations(desired_durations, video_duration)
    for row_index, row in enumerate(alignment):
        desired_duration = desired_durations[row_index]
        start, end, visual_selection_reason = choose_visual_window_for_row(
            row=row,
            desired_duration=desired_duration,
            video_duration=video_duration,
            padding=padding,
        )

        lower_bound = 0.0
        if previous_source_start is not None:
            lower_bound = max(lower_bound, previous_source_start)
        if previous_source_end is not None:
            lower_bound = max(lower_bound, previous_source_end - MAX_ADJACENT_SOURCE_OVERLAP_SECONDS)

        upper_bound = latest_start_bounds[row_index]
        if start > upper_bound and upper_bound >= lower_bound:
            start = upper_bound
            end = start + desired_duration
            visual_selection_reason = "shifted_earlier_to_fit_remaining_duration"

        if previous_source_start is not None and start < previous_source_start:
            visual_selection_reason = "shifted_to_preserve_order"
        elif start < lower_bound:
            visual_selection_reason = "shifted_to_reduce_overlap"
        if start < lower_bound:
            start = lower_bound
            end = start + desired_duration

        if end > video_duration:
            latest_start = max(0.0, video_duration - desired_duration)
            if latest_start >= lower_bound:
                start = latest_start
                end = start + desired_duration
                visual_selection_reason = "shifted_to_reduce_overlap_at_video_end"
            else:
                start = lower_bound
                end = video_duration
                visual_selection_reason = "trimmed_at_video_end"
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
            "source_order_policy": SOURCE_ORDER_POLICY,
            "visual_selection_reason": visual_selection_reason,
        })
        previous_source_start = start
        previous_source_end = end

    for index, clip in enumerate(clips, start=1):
        clip["id"] = index
    return clips
