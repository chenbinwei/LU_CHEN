"""Diagnose OCool model availability without printing secrets."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from video_slicer.pipeline import DEFAULT_OCOOL_BASE_URL, DEFAULT_OCOOL_MODEL, load_dotenv


DEFAULT_CANDIDATES = [
    "qwen-plus-latest",
    "qwen-plus",
    "qwen-turbo-latest",
    "qwen-turbo",
    "qwen-max-latest",
    "deepseek-v3",
    "gpt-5.4-2026-03-05",
    "gpt-5.2-2025-12-11",
    "abab5.5-chat",
]


def _safe_text(value: Any, limit: int = 500) -> str:
    text = str(value)
    return text.encode("ascii", "backslashreplace").decode("ascii")[:limit]


def _chat_once(client: Any, model: str, timeout_label: str) -> tuple[bool, str, float]:
    started_at = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a concise connectivity test assistant."},
                {"role": "user", "content": "Reply with exactly this JSON: {\"ok\":true}"},
            ],
            max_tokens=40,
        )
        elapsed = time.monotonic() - started_at
        return True, str(response.choices[0].message.content or ""), elapsed
    except Exception as exc:
        elapsed = time.monotonic() - started_at
        status = getattr(exc, "status_code", "")
        request_id = getattr(exc, "request_id", "")
        detail = f"{type(exc).__name__}"
        if status:
            detail += f" status={status}"
        if request_id:
            detail += f" request_id={request_id}"
        detail += f" {timeout_label}: {_safe_text(exc)}"
        return False, detail, elapsed


def main() -> None:
    load_dotenv(Path(".env"))
    parser = argparse.ArgumentParser(description="Diagnose OCool model availability.")
    parser.add_argument("--base-url", default=os.environ.get("OCOOL_BASE_URL", DEFAULT_OCOOL_BASE_URL))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("OCOOL_TIMEOUT", "30")))
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--model", action="append", default=[], help="Model to test. Can be passed multiple times.")
    args = parser.parse_args()

    api_key = os.environ.get("OCOOL_API_KEY", "").strip()
    print(f"OCOOL_BASE_URL={args.base_url}")
    print(f"OCOOL_API_KEY={'SET length=' + str(len(api_key)) if api_key else 'MISSING'}")
    if not api_key:
        raise SystemExit("OCOOL_API_KEY is missing.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit("OpenAI SDK is required. Run pip install -r requirements.txt") from exc

    client = OpenAI(api_key=api_key, base_url=args.base_url, timeout=args.timeout)

    if args.list_models:
        try:
            models = client.models.list()
            ids = sorted(
                model.id
                for model in models.data
                if getattr(model, "id", "")
            )
            print(f"models.list OK count={len(ids)}")
            for model_id in ids:
                print(model_id)
        except Exception as exc:
            print(f"models.list FAIL {type(exc).__name__}: {_safe_text(exc)}")

    candidates = args.model or DEFAULT_CANDIDATES
    seen: set[str] = set()
    print("chat.completions smoke tests:")
    for model in candidates:
        if model in seen:
            continue
        seen.add(model)
        ok, text, elapsed = _chat_once(client, model, f"timeout={args.timeout:.1f}s")
        label = "OK" if ok else "FAIL"
        parsed = ""
        if ok:
            try:
                parsed = f" parsed={json.loads(text).get('ok')}"
            except Exception:
                parsed = " parsed=false"
        print(f"[{label}] {model} elapsed={elapsed:.1f}s{parsed} text={_safe_text(text, 300)}")

    default_model = os.environ.get("OCOOL_MODEL", DEFAULT_OCOOL_MODEL)
    print(f"default_model={default_model}")


if __name__ == "__main__":
    main()
