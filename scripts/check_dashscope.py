"""Check DashScope OpenAI-compatible chat without printing secrets."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from llm_providers.dashscope import DEFAULT_BASE_URL, DEFAULT_MODEL, text_completion
from video_slicer.pipeline import load_dotenv


def main() -> None:
    load_dotenv(Path(".env"))
    parser = argparse.ArgumentParser(description="Check DashScope text generation.")
    parser.add_argument("--base-url", default=os.environ.get("DASHSCOPE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--model", default=os.environ.get("DASHSCOPE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--no-thinking", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    print(f"DASHSCOPE_BASE_URL={args.base_url}")
    print(f"DASHSCOPE_MODEL={args.model}")
    print(f"DASHSCOPE_API_KEY={'SET length=' + str(len(api_key)) if api_key else 'MISSING'}")
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY is missing.")

    text = text_completion(
        model=args.model,
        instructions="You are a connectivity test assistant. Return only the requested text.",
        input_text='Reply with exactly this JSON: {"ok":true}',
        base_url=args.base_url,
        api_key=api_key,
        max_tokens=80,
        enable_thinking=not args.no_thinking,
    )
    print(text[:500])


if __name__ == "__main__":
    main()
