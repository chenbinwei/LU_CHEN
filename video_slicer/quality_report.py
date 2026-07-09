"""Quality checks for generated script alignment and rendered timelines."""

from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import mean
from typing import Any


Issue = dict[str, Any]
LOW_MATCH_SCORE_THRESHOLD = 0.08


def text_similarity(a: str, b: str) -> float:
    a_chars = set(_meaningful_chars(a))
    b_chars = set(_meaningful_chars(b))
    if not a_chars or not b_chars:
        return 0.0
    overlap = len(a_chars & b_chars)
    union = len(a_chars | b_chars)
    containment = overlap / max(1, min(len(a_chars), len(b_chars)))
    jaccard = overlap / max(1, union)
    return round(jaccard * 0.55 + containment * 0.45, 3)


def build_quality_report(
    *,
    alignment: list[dict[str, Any]],
    clips: list[dict[str, Any]],
    target_duration: float,
    duration_tolerance: float,
    actual_voiceover_duration: float,
    actual_visual_duration: float,
    source_video_duration: float | None = None,
    tts_mode: str = "",
    title: str = "",
) -> dict[str, Any]:
    issues: list[Issue] = []

    _check_basic_counts(alignment, clips, issues)
    _check_duration(
        target_duration=target_duration,
        duration_tolerance=duration_tolerance,
        actual_voiceover_duration=actual_voiceover_duration,
        actual_visual_duration=actual_visual_duration,
        issues=issues,
    )
    _check_alignment_rows(alignment, issues)
    _check_clip_timeline(clips, source_video_duration, issues)

    severities = _severity_counts(issues)
    status = "pass"
    if severities["error"]:
        status = "fail"
    elif severities["warning"]:
        status = "warn"

    return {
        "schema_version": 1,
        "status": status,
        "title": title,
        "tts_mode": tts_mode,
        "summary": {
            "errors": severities["error"],
            "warnings": severities["warning"],
            "info": severities["info"],
        },
        "metrics": _metrics(
            alignment=alignment,
            clips=clips,
            target_duration=target_duration,
            duration_tolerance=duration_tolerance,
            actual_voiceover_duration=actual_voiceover_duration,
            actual_visual_duration=actual_visual_duration,
            source_video_duration=source_video_duration,
        ),
        "issues": issues,
    }


def write_quality_report(report: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _meaningful_chars(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text.lower())


def _cjk_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _english_letter_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]", text))


def _severity_counts(issues: list[Issue]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        severity = str(issue.get("severity", "info"))
        if severity in counts:
            counts[severity] += 1
    return counts


def _add_issue(
    issues: list[Issue],
    *,
    issue_id: str,
    severity: str,
    message: str,
    **details: Any,
) -> None:
    issue: Issue = {
        "id": issue_id,
        "severity": severity,
        "message": message,
    }
    issue.update(details)
    issues.append(issue)


def _check_basic_counts(
    alignment: list[dict[str, Any]],
    clips: list[dict[str, Any]],
    issues: list[Issue],
) -> None:
    if not alignment:
        _add_issue(
            issues,
            issue_id="alignment_empty",
            severity="error",
            message="No voiceover alignment rows were generated.",
        )
    if not clips:
        _add_issue(
            issues,
            issue_id="clips_empty",
            severity="error",
            message="No visual clips were generated.",
        )
    if alignment and clips and len(alignment) != len(clips):
        _add_issue(
            issues,
            issue_id="alignment_clip_count_mismatch",
            severity="warning",
            message="Voiceover rows and visual clips have different counts.",
            alignment_count=len(alignment),
            clip_count=len(clips),
        )


def _check_duration(
    *,
    target_duration: float,
    duration_tolerance: float,
    actual_voiceover_duration: float,
    actual_visual_duration: float,
    issues: list[Issue],
) -> None:
    if target_duration <= 0:
        _add_issue(
            issues,
            issue_id="target_duration_invalid",
            severity="error",
            message="Target duration must be greater than 0.",
            target_duration=target_duration,
        )
        return

    visual_delta = round(abs(actual_visual_duration - target_duration), 3)
    if visual_delta > duration_tolerance:
        _add_issue(
            issues,
            issue_id="visual_duration_outside_tolerance",
            severity="error",
            message="Visual timeline duration is outside target tolerance.",
            target_duration=target_duration,
            actual_visual_duration=actual_visual_duration,
            duration_tolerance=duration_tolerance,
            delta=visual_delta,
        )

    voice_visual_delta = round(abs(actual_voiceover_duration - actual_visual_duration), 3)
    if voice_visual_delta > max(0.5, duration_tolerance):
        _add_issue(
            issues,
            issue_id="voiceover_visual_duration_mismatch",
            severity="warning",
            message="Voiceover and visual durations differ more than expected.",
            actual_voiceover_duration=actual_voiceover_duration,
            actual_visual_duration=actual_visual_duration,
            delta=voice_visual_delta,
        )


def _check_alignment_rows(alignment: list[dict[str, Any]], issues: list[Issue]) -> None:
    for row in alignment:
        sentence_id = int(row.get("sentence_id", 0) or 0)
        text = str(row.get("text", ""))
        source_text = str(row.get("source_text", ""))
        source_start = _float(row.get("source_start"))
        source_end = _float(row.get("source_end"))
        voiceover_duration = _float(row.get("voiceover_duration") or row.get("estimated_voiceover_duration"))

        if _english_letter_count(text):
            _add_issue(
                issues,
                issue_id="voiceover_contains_english",
                severity="warning",
                message="Voiceover line contains English letters.",
                sentence_id=sentence_id,
                text=text,
            )

        if source_end <= source_start:
            _add_issue(
                issues,
                issue_id="invalid_source_range",
                severity="error",
                message="Alignment row has an invalid source range.",
                sentence_id=sentence_id,
                source_start=source_start,
                source_end=source_end,
            )
            continue

        source_span = round(source_end - source_start, 3)
        if voiceover_duration > 0 and source_span > max(12.0, voiceover_duration * 3.0):
            _add_issue(
                issues,
                issue_id="source_evidence_span_too_long",
                severity="warning",
                message="Source evidence span is much longer than the narration line; visual centering may miss the intended moment.",
                sentence_id=sentence_id,
                source_start=source_start,
                source_end=source_end,
                source_span=source_span,
                voiceover_duration=voiceover_duration,
                text=text,
                source_text=source_text,
            )

        similarity = text_similarity(text, source_text)
        match_score = _optional_float(row.get("match_score"))
        source_id_trust = str(row.get("source_id_trust", ""))
        if source_id_trust == "llm_replaced_by_ordered_fallback":
            _add_issue(
                issues,
                issue_id="llm_source_ids_replaced_by_ordered_fallback",
                severity="warning",
                message="LLM-provided source_segment_ids were replaced by ordered fallback to preserve source timeline order.",
                sentence_id=sentence_id,
                original_source_segment_ids=row.get("original_source_segment_ids", []),
                source_segment_ids=row.get("source_segment_ids", []),
                evidence_warning=row.get("evidence_warning", ""),
                text=text,
                source_text=source_text,
            )
        if source_id_trust == "continuity_visual_support":
            _add_issue(
                issues,
                issue_id="continuity_visual_support_low_evidence",
                severity="info",
                message="Low-evidence source_segment_ids are used only as continuity visual support, not as trusted subtitle evidence.",
                sentence_id=sentence_id,
                source_segment_ids=row.get("source_segment_ids", []),
                evidence_warning=row.get("evidence_warning", ""),
                match_score=match_score,
                text=text,
                source_text=source_text,
            )
        if (
            source_text
            and source_id_trust == "llm_provided"
            and match_score is not None
            and match_score < LOW_MATCH_SCORE_THRESHOLD
        ):
            _add_issue(
                issues,
                issue_id="llm_source_ids_low_evidence_score",
                severity="warning",
                message="LLM-provided source_segment_ids have a low evidence score.",
                sentence_id=sentence_id,
                match_score=match_score,
                text=text,
                source_text=source_text,
            )
        if source_text and similarity < LOW_MATCH_SCORE_THRESHOLD:
            _add_issue(
                issues,
                issue_id="low_text_evidence_overlap",
                severity="info",
                message="Voiceover line has very low lexical overlap with its source subtitle text; this may be normal for commentary but should be reviewed.",
                sentence_id=sentence_id,
                similarity=similarity,
                text=text,
                source_text=source_text,
            )


def _check_clip_timeline(
    clips: list[dict[str, Any]],
    source_video_duration: float | None,
    issues: list[Issue],
) -> None:
    previous: dict[str, Any] | None = None
    for clip in clips:
        clip_id = int(clip.get("id", 0) or 0)
        source_start = _float(clip.get("source_start"))
        source_end = _float(clip.get("source_end"))
        duration = _float(clip.get("duration"))

        if duration <= 0:
            _add_issue(
                issues,
                issue_id="clip_non_positive_duration",
                severity="error",
                message="Visual clip duration must be greater than 0.",
                clip_id=clip_id,
                duration=duration,
            )

        if source_start < 0 or source_end <= source_start:
            _add_issue(
                issues,
                issue_id="clip_invalid_source_range",
                severity="error",
                message="Visual clip source range is invalid.",
                clip_id=clip_id,
                source_start=source_start,
                source_end=source_end,
            )

        if source_video_duration is not None and source_end > source_video_duration + 0.05:
            _add_issue(
                issues,
                issue_id="clip_exceeds_source_duration",
                severity="error",
                message="Visual clip exceeds source video duration.",
                clip_id=clip_id,
                source_end=source_end,
                source_video_duration=source_video_duration,
            )

        if previous is not None:
            prev_id = int(previous.get("id", 0) or 0)
            prev_start = _float(previous.get("source_start"))
            prev_end = _float(previous.get("source_end"))
            if source_start < prev_start - 0.1:
                _add_issue(
                    issues,
                    issue_id="source_timeline_backtrack",
                    severity="warning",
                    message="Visual timeline jumps backward in the source video.",
                    clip_id=clip_id,
                    previous_clip_id=prev_id,
                    source_start=source_start,
                    previous_source_start=prev_start,
                    sentence_text=clip.get("sentence_text", ""),
                )
            overlap = round(prev_end - source_start, 3)
            if overlap > 2.0:
                _add_issue(
                    issues,
                    issue_id="source_timeline_major_overlap",
                    severity="warning",
                    message="Adjacent visual clips reuse overlapping source footage.",
                    clip_id=clip_id,
                    previous_clip_id=prev_id,
                    overlap_seconds=overlap,
                    sentence_text=clip.get("sentence_text", ""),
                )

        previous = clip


def _metrics(
    *,
    alignment: list[dict[str, Any]],
    clips: list[dict[str, Any]],
    target_duration: float,
    duration_tolerance: float,
    actual_voiceover_duration: float,
    actual_visual_duration: float,
    source_video_duration: float | None,
) -> dict[str, Any]:
    all_text = "\n".join(str(row.get("text", "")) for row in alignment)
    clip_durations = [_float(clip.get("duration")) for clip in clips]
    source_starts = [_float(clip.get("source_start")) for clip in clips]
    source_ends = [_float(clip.get("source_end")) for clip in clips]
    major_overlaps = [
        round(source_ends[index - 1] - source_starts[index], 3)
        for index in range(1, len(clips))
        if source_ends[index - 1] - source_starts[index] > 2.0
    ]
    match_scores = [
        score
        for score in (_optional_float(row.get("match_score")) for row in alignment)
        if score is not None
    ]
    return {
        "target_duration": target_duration,
        "duration_tolerance": duration_tolerance,
        "actual_voiceover_duration": actual_voiceover_duration,
        "actual_visual_duration": actual_visual_duration,
        "duration_delta": round(abs(actual_visual_duration - target_duration), 3) if target_duration > 0 else None,
        "source_video_duration": source_video_duration,
        "alignment_count": len(alignment),
        "clip_count": len(clips),
        "script_cjk_chars": _cjk_count(all_text),
        "script_english_letters": _english_letter_count(all_text),
        "match_score_min": round(min(match_scores), 3) if match_scores else None,
        "match_score_avg": round(mean(match_scores), 3) if match_scores else None,
        "low_match_score_count": sum(1 for score in match_scores if score < LOW_MATCH_SCORE_THRESHOLD),
        "source_order_repair_count": sum(
            1
            for row in alignment
            if str(row.get("source_id_trust", "")) == "llm_replaced_by_ordered_fallback"
        ),
        "continuity_visual_support_count": sum(
            1
            for row in alignment
            if str(row.get("source_id_trust", "")) == "continuity_visual_support"
        ),
        "clip_duration_min": round(min(clip_durations), 3) if clip_durations else None,
        "clip_duration_max": round(max(clip_durations), 3) if clip_durations else None,
        "clip_duration_avg": round(mean(clip_durations), 3) if clip_durations else None,
        "source_backtrack_count": sum(
            1
            for index in range(1, len(source_starts))
            if source_starts[index] < source_starts[index - 1] - 0.1
        ),
        "source_major_overlap_count": len(major_overlaps),
        "source_major_overlap_max": round(max(major_overlaps), 3) if major_overlaps else 0.0,
    }


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
