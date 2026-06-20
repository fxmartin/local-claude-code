"""Endpoint provider adapters."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from local_code_bench.config import ModelConfig
from local_code_bench.metrics import StreamEvent


class ProviderError(RuntimeError):
    """Raised when an endpoint request cannot be completed."""


@dataclass(frozen=True)
class ChatRequest:
    prompt: str
    temperature: float = 0.0


class OpenAIStreamingProvider:
    """Minimal OpenAI-compatible streaming `/v1/chat/completions` adapter."""

    def __init__(self, model: ModelConfig, *, timeout_seconds: float = 120.0) -> None:
        if model.type != "openai":
            raise ProviderError(f"model '{model.name}' is type '{model.type}', not openai")
        self._model = model
        self._timeout_seconds = timeout_seconds

    def stream_chat(self, request: ChatRequest) -> Iterable[StreamEvent]:
        api_key = _api_key(self._model)
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        body = {
            "model": self._model.model_id,
            "messages": [{"role": "user", "content": request.prompt}],
            "temperature": request.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        endpoint = f"{self._model.base_url}/chat/completions"
        http_request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                yield from parse_openai_sse_lines(_decode_lines(response))
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"{self._model.name} HTTP {exc.code}: {_redact(message, api_key)}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"{self._model.name} request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ProviderError(f"{self._model.name} request timed out") from exc


def parse_openai_sse_lines(lines: Iterable[str]) -> Iterable[StreamEvent]:
    """Parse OpenAI-compatible SSE chunks into normalized stream events."""

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(":"):
            continue
        if not stripped.startswith("data:"):
            continue

        payload = stripped.removeprefix("data:").strip()
        if payload == "[DONE]":
            break

        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"malformed stream JSON: {payload}") from exc

        content = _content_delta(chunk)
        usage = chunk.get("usage") if isinstance(chunk, dict) else None
        prompt_tokens, completion_tokens = _usage_tokens(usage)
        if content or prompt_tokens is not None or completion_tokens is not None:
            yield StreamEvent(
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )


def _decode_lines(response: Any) -> Iterable[str]:
    for raw_line in response:
        if isinstance(raw_line, bytes):
            yield raw_line.decode("utf-8", errors="replace")
        else:
            yield str(raw_line)


def _content_delta(chunk: Any) -> str:
    if not isinstance(chunk, dict):
        return ""
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        return content if isinstance(content, str) else ""
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _usage_tokens(usage: Any) -> tuple[int | None, int | None]:
    if not isinstance(usage, dict):
        return None, None
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    return (
        prompt_tokens if isinstance(prompt_tokens, int) else None,
        completion_tokens if isinstance(completion_tokens, int) else None,
    )


def _api_key(model: ModelConfig) -> str | None:
    if model.api_key_env is None:
        return None
    api_key = os.environ.get(model.api_key_env)
    if not api_key:
        raise ProviderError(f"{model.name} requires environment variable {model.api_key_env}")
    return api_key


def _redact(message: str, secret: str | None) -> str:
    if not secret:
        return message
    return message.replace(secret, "[REDACTED]")
