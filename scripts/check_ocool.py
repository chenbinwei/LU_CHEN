"""Diagnose OCool/OpenAI-compatible text endpoints without printing secrets."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from video_slicer.pipeline import DEFAULT_OCOOL_MODEL, load_dotenv


def _response_text(response: Any) -> str:
    if hasattr(response, "output_text"):
        return str(response.output_text)
    if hasattr(response, "content"):
        return str(response.content)
    return str(response)


def _safe_console(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _print_error(label: str, exc: BaseException) -> None:
    print(_safe_console(f"[FAIL] {label}: {type(exc).__name__}: {exc}"))
    status_code = getattr(exc, "status_code", None)
    request_id = getattr(exc, "request_id", None)
    if status_code is not None:
        print(f"       status_code={status_code}")
    if request_id:
        print(f"       request_id={request_id}")
    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", {}) or {}
        for key in ("x-request-id", "request-id", "cf-ray"):
            value = headers.get(key)
            if value:
                print(f"       {key}={value}")


def main() -> None:
    load_dotenv(Path(".env"))
    parser = argparse.ArgumentParser(description="Check OCool text endpoint compatibility.")
    parser.add_argument("--base-url", default=os.environ.get("OCOOL_BASE_URL", "https://one.ocoolai.com/v1"))
    parser.add_argument("--model", default=os.environ.get("OCOOL_MODEL", DEFAULT_OCOOL_MODEL))
    parser.add_argument("--chat-model", default=None, help="Optional different model for chat.completions.")
    parser.add_argument("--skip-responses", action="store_true")
    parser.add_argument("--skip-chat", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("OCOOL_API_KEY", "").strip()
    print(f"OCOOL_BASE_URL={args.base_url}")
    print(f"OCOOL_MODEL={args.model}")
    print(f"OCOOL_API_KEY={'SET length=' + str(len(api_key)) if api_key else 'MISSING'}")
    if not api_key:
        raise SystemExit("OCOOL_API_KEY is missing.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit("OpenAI SDK is required. Run pip install -r requirements.txt") from exc

    client = OpenAI(api_key=api_key, base_url=args.base_url)
    prompt = "Reply with exactly this text: OK"

    if not args.skip_responses:
        try:
            response = client.responses.create(
                model=args.model,
                instructions="You are a connectivity test assistant.",
                input=prompt,
            )
            print("[OK] responses.create")
            print(_safe_console(_response_text(response)[:300]))
        except BaseException as exc:
            _print_error("responses.create", exc)

    if not args.skip_chat:
        try:
            response = client.chat.completions.create(
                model=args.chat_model or args.model,
                messages=[
                    {"role": "system", "content": "You are a connectivity test assistant."},
                    {"role": "user", "content": prompt},
                ],
            )
            print("[OK] chat.completions.create")
            print(_safe_console(str(response.choices[0].message.content)[:300]))
        except BaseException as exc:
            _print_error("chat.completions.create", exc)


if __name__ == "__main__":
    main()
