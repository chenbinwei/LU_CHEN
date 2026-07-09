"""Run multiple video slicing jobs from a JSON manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from video_slicer.pipeline import main as run_pipeline


FIELD_TO_FLAG = {
    "input": "--input",
    "output_dir": "--output-dir",
    "context": "--context",
    "target_duration": "--target-duration",
    "duration_tolerance": "--duration-tolerance",
    "model_size": "--model-size",
    "device": "--device",
    "compute_type": "--compute-type",
    "language": "--language",
    "tts_mode": "--tts-mode",
    "fish_reference_id": "--fish-reference-id",
    "padding": "--padding",
    "bgm_audio": "--bgm-audio",
    "bgm_volume": "--bgm-volume",
    "voiceover_volume": "--voiceover-volume",
    "bgm_start": "--bgm-start",
    "bgm_fade_in": "--bgm-fade-in",
    "bgm_fade_out": "--bgm-fade-out",
}


BOOLEAN_FLAGS = {
    "require_llm": "--require-llm",
    "force_script": "--force-script",
    "force_review": "--force-review",
    "force_humanize": "--force-humanize",
    "force_tts": "--force-tts",
    "force_transcribe": "--force-transcribe",
    "force_audio": "--force-audio",
    "skip_review": "--skip-review",
    "skip_humanize": "--skip-humanize",
    "no_llm": "--no-llm",
    "no_fit_duration": "--no-fit-duration",
}


def job_to_argv(job: dict[str, Any]) -> list[str]:
    argv: list[str] = []
    for field, flag in FIELD_TO_FLAG.items():
        value = job.get(field)
        if value is not None and value != "":
            argv.extend([flag, str(value)])
    for field, flag in BOOLEAN_FLAGS.items():
        if job.get(field):
            argv.append(flag)
    extra_args = job.get("extra_args", [])
    if extra_args:
        if not isinstance(extra_args, list):
            raise SystemExit("extra_args must be a list of command-line tokens.")
        argv.extend(str(item) for item in extra_args)
    return argv


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multiple pipeline jobs from a JSON manifest.")
    parser.add_argument("--manifest", required=True, help="Path to a JSON file containing a list of jobs.")
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    jobs = json.loads(Path(args.manifest).read_text(encoding="utf-8-sig"))
    if not isinstance(jobs, list):
        raise SystemExit("Batch manifest must be a JSON list.")

    failures: list[tuple[int, BaseException]] = []
    for index, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            raise SystemExit(f"Job {index} must be a JSON object.")
        print(f"\n=== Running job {index}/{len(jobs)}: {job.get('input', '(no input)')} ===")
        try:
            run_pipeline(job_to_argv(job))
        except BaseException as exc:
            failures.append((index, exc))
            print(f"Job {index} failed: {exc}")
            if not args.continue_on_error:
                raise

    if failures:
        failed_indexes = ", ".join(str(index) for index, _ in failures)
        raise SystemExit(f"Batch completed with failed jobs: {failed_indexes}")


if __name__ == "__main__":
    main()
