"""OCool/OpenAI-compatible text generation provider."""

from __future__ import annotations

import os
import time


DEFAULT_TEXT_ENDPOINT = "chat"
DEFAULT_MAX_TOKENS = 3000
DEFAULT_RETRIES = 2
DEFAULT_TIMEOUT = 90.0


def text_completion(
    *,
    model: str,
    instructions: str,
    input_text: str,
    base_url: str,
    api_key: str | None = None,
    endpoint: str | None = None,
    timeout: float | None = None,
    max_tokens: int | None = None,
    retries: int | None = None,
) -> str:
    api_key = api_key or os.environ.get("OCOOL_API_KEY")
    if not api_key:
        raise SystemExit("OCOOL_API_KEY is required for OCool text generation.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit(
            "OpenAI SDK is required for OCool calls. Run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from exc

    endpoint = (endpoint or os.environ.get("OCOOL_TEXT_ENDPOINT") or DEFAULT_TEXT_ENDPOINT).strip().lower()
    max_tokens = max_tokens or int(os.environ.get("OCOOL_MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))
    retries = DEFAULT_RETRIES if retries is None else retries
    retries = int(os.environ.get("OCOOL_RETRIES", str(retries)))
    timeout = float(timeout if timeout is not None else os.environ.get("OCOOL_TIMEOUT", DEFAULT_TIMEOUT))
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    for attempt in range(retries + 1):
        started_at = time.monotonic()
        try:
            print(
                "OCool request "
                f"endpoint={endpoint} model={model} input_chars={len(input_text)} "
                f"instruction_chars={len(instructions)} max_tokens={max_tokens} timeout={timeout:.1f}s "
                f"attempt={attempt + 1}/{retries + 1}"
            )
            result = _text_completion_once(
                client=client,
                endpoint=endpoint,
                model=model,
                instructions=instructions,
                input_text=input_text,
                max_tokens=max_tokens,
            )
            elapsed = time.monotonic() - started_at
            print(f"OCool response received in {elapsed:.1f}s, output_chars={len(result)}")
            return result
        except Exception as exc:
            elapsed = time.monotonic() - started_at
            if attempt >= retries or not is_retryable_error(exc):
                raise
            wait_seconds = min(2 * (attempt + 1), 8)
            print(f"OCool text request failed after {elapsed:.1f}s, retrying {attempt + 1}/{retries} after {wait_seconds}s: {exc}")
            time.sleep(wait_seconds)


def _text_completion_once(
    *,
    client: object,
    endpoint: str,
    model: str,
    instructions: str,
    input_text: str,
    max_tokens: int,
) -> str:

    if endpoint == "responses":
        response = client.responses.create(
            model=model,
            instructions=instructions,
            input=input_text,
            max_output_tokens=max_tokens,
        )
        return extract_response_text(response)

    if endpoint == "chat":
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
            max_tokens=max_tokens,
        )
        return str(response.choices[0].message.content or "")

    raise SystemExit("OCOOL_TEXT_ENDPOINT must be 'chat' or 'responses'.")


def is_retryable_error(exc: BaseException) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {408, 429, 500, 502, 503, 504}:
        return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "connection error",
            "gateway time-out",
            "gateway timeout",
            "temporarily unavailable",
            "timeout",
            "503",
            "504",
        )
    )


def extract_response_text(response: object) -> str:
    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                parts.append(text)
    if parts:
        return "\n".join(parts)
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)
    content = getattr(response, "content", None)
    if content:
        return str(content)
    return str(response)
