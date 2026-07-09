"""DashScope official SDK text generation provider."""

from __future__ import annotations

import os
import time
from typing import Any


DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/api/v1"
DEFAULT_MODEL = "qwen-plus-latest"
DEFAULT_MAX_TOKENS = 3000
DEFAULT_RETRIES = 2
DEFAULT_TIMEOUT = 90.0


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def text_completion(
    *,
    model: str,
    instructions: str,
    input_text: str,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
    max_tokens: int | None = None,
    retries: int | None = None,
    enable_thinking: bool | None = None,
    temperature: float | None = None,
    stream: bool | None = None,
) -> str:
    api_key = api_key or os.environ.get("DASHSCOPE_API_KEY")
    if not api_key or api_key == "put_your_dashscope_api_key_here":
        raise SystemExit("DASHSCOPE_API_KEY is required for DashScope text generation.")

    try:
        import dashscope
        from dashscope import Generation
    except ImportError as exc:
        raise SystemExit(
            "DashScope SDK is required. Run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from exc

    base_url = (base_url or os.environ.get("DASHSCOPE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    dashscope.base_http_api_url = base_url
    model = model or os.environ.get("DASHSCOPE_MODEL", DEFAULT_MODEL)
    max_tokens = max_tokens or int(os.environ.get("DASHSCOPE_MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))
    retries = DEFAULT_RETRIES if retries is None else retries
    retries = int(os.environ.get("DASHSCOPE_RETRIES", str(retries)))
    timeout = float(timeout if timeout is not None else os.environ.get("DASHSCOPE_TIMEOUT", DEFAULT_TIMEOUT))
    enable_thinking = _env_bool("DASHSCOPE_ENABLE_THINKING", True) if enable_thinking is None else enable_thinking
    stream = _env_bool("DASHSCOPE_STREAM", True) if stream is None else stream
    if enable_thinking and not stream:
        print("DashScope enable_thinking requires stream=True; forcing stream mode.")
        stream = True
    temperature = float(temperature if temperature is not None else os.environ.get("DASHSCOPE_TEMPERATURE", "0.3"))

    messages = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": input_text},
    ]
    for attempt in range(retries + 1):
        started_at = time.monotonic()
        try:
            print(
                "DashScope request "
                f"model={model} stream={stream} thinking={enable_thinking} "
                f"input_chars={len(input_text)} instruction_chars={len(instructions)} "
                f"max_tokens={max_tokens} timeout={timeout:.1f}s "
                f"attempt={attempt + 1}/{retries + 1}"
            )
            response = Generation.call(
                api_key=api_key,
                model=model,
                messages=messages,
                result_format="message",
                stream=stream,
                incremental_output=True if stream else None,
                enable_thinking=enable_thinking,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            content, reasoning = _collect_response(response, stream=stream)
            if reasoning:
                print(f"DashScope reasoning chars={len(reasoning)}")
            elapsed = time.monotonic() - started_at
            print(f"DashScope response received in {elapsed:.1f}s, output_chars={len(content)}")
            return content
        except Exception as exc:
            elapsed = time.monotonic() - started_at
            if attempt >= retries or not is_retryable_error(exc):
                raise
            wait_seconds = min(2 * (attempt + 1), 8)
            print(f"DashScope request failed after {elapsed:.1f}s, retrying {attempt + 1}/{retries} after {wait_seconds}s: {exc}")
            time.sleep(wait_seconds)

    raise RuntimeError("DashScope request failed without an exception.")


class DashScopeError(RuntimeError):
    def __init__(self, *, status_code: Any, code: Any, message: Any) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"DashScope failed status={status_code} code={code} message={message}")


def _collect_response(response: Any, *, stream: bool) -> tuple[str, str]:
    if not stream:
        _raise_if_failed(response)
        message = _response_message(response)
        return _message_value(message, "content"), _message_value(message, "reasoning_content")

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    for chunk in response:
        _raise_if_failed(chunk)
        message = _response_message(chunk)
        content = _message_value(message, "content")
        reasoning = _message_value(message, "reasoning_content")
        if content:
            content_parts.append(content)
        if reasoning:
            reasoning_parts.append(reasoning)
    return "".join(content_parts), "".join(reasoning_parts)


def _raise_if_failed(response: Any) -> None:
    if int(getattr(response, "status_code", 0) or 0) != 200:
        raise DashScopeError(
            status_code=getattr(response, "status_code", None),
            code=getattr(response, "code", ""),
            message=getattr(response, "message", ""),
        )


def _response_message(response: Any) -> Any:
    choices = response.output.choices
    if not choices:
        raise RuntimeError("DashScope returned no choices.")
    return choices[0].message


def _message_value(message: Any, key: str) -> str:
    if isinstance(message, dict):
        return str(message.get(key) or "")
    return str(getattr(message, key, "") or "")


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
