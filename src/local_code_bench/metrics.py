"""Streaming response measurement."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import perf_counter


@dataclass(frozen=True)
class StreamEvent:
    content: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class CompletionMeasurement:
    response: str
    ttft_seconds: float | None
    latency_seconds: float
    prompt_tokens: int
    completion_tokens: int
    prefill_tokens_per_second: float | None
    decode_tokens_per_second: float | None
    token_counts_estimated: bool


def estimate_tokens(text: str) -> int:
    """Cheap deterministic fallback when an endpoint omits token usage."""

    return len(text.split())


def capture_stream_metrics(
    events: Iterable[StreamEvent],
    prompt: str,
    *,
    clock: Callable[[], float] = perf_counter,
    token_counter: Callable[[str], int] = estimate_tokens,
) -> CompletionMeasurement:
    """Consume streaming events and measure first-token and completion timings."""

    started_at = clock()
    first_token_at: float | None = None
    finished_at = started_at
    parts: list[str] = []
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    for event in events:
        now = clock()
        finished_at = now
        if event.content and first_token_at is None:
            first_token_at = now
        if event.content:
            parts.append(event.content)
        if event.prompt_tokens is not None:
            prompt_tokens = event.prompt_tokens
        if event.completion_tokens is not None:
            completion_tokens = event.completion_tokens

    response = "".join(parts)
    latency = max(finished_at - started_at, 0.0)
    estimated = prompt_tokens is None or completion_tokens is None
    resolved_prompt_tokens = prompt_tokens if prompt_tokens is not None else token_counter(prompt)
    resolved_completion_tokens = (
        completion_tokens if completion_tokens is not None else token_counter(response)
    )

    ttft = first_token_at - started_at if first_token_at is not None else None
    prefill_tps = _rate(resolved_prompt_tokens, ttft)
    decode_seconds = None if ttft is None else latency - ttft
    decode_tps = _rate(resolved_completion_tokens, decode_seconds)

    return CompletionMeasurement(
        response=response,
        ttft_seconds=ttft,
        latency_seconds=latency,
        prompt_tokens=resolved_prompt_tokens,
        completion_tokens=resolved_completion_tokens,
        prefill_tokens_per_second=prefill_tps,
        decode_tokens_per_second=decode_tps,
        token_counts_estimated=estimated,
    )


def _rate(tokens: int, seconds: float | None) -> float | None:
    if seconds is None or seconds <= 0:
        return None
    return tokens / seconds
