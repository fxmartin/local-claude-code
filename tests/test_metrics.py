from __future__ import annotations

from local_code_bench.metrics import StreamEvent, capture_stream_metrics


def test_capture_stream_metrics_uses_usage_tokens_and_times_first_token() -> None:
    times = iter([0.0, 0.25, 1.0, 1.25])

    measurement = capture_stream_metrics(
        [
            StreamEvent(content="hel"),
            StreamEvent(content="lo", prompt_tokens=10, completion_tokens=2),
        ],
        "ignored prompt",
        clock=lambda: next(times),
    )

    assert measurement.response == "hello"
    assert measurement.ttft_seconds == 0.25
    assert measurement.latency_seconds == 1.0
    assert measurement.prompt_tokens == 10
    assert measurement.completion_tokens == 2
    assert measurement.prefill_tokens_per_second == 40
    assert measurement.decode_tokens_per_second == 2 / 0.75
    assert measurement.token_counts_estimated is False


def test_capture_stream_metrics_estimates_missing_usage() -> None:
    times = iter([0.0, 0.5])

    measurement = capture_stream_metrics(
        [StreamEvent(content="two tokens")],
        "three prompt tokens",
        clock=lambda: next(times),
    )

    assert measurement.prompt_tokens == 3
    assert measurement.completion_tokens == 2
    assert measurement.token_counts_estimated is True
