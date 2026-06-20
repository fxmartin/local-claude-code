from __future__ import annotations

import pytest

from local_code_bench.config import ModelConfig, TokenPrices
from local_code_bench.provider import OpenAIStreamingProvider, ProviderError, parse_openai_sse_lines


def test_parse_openai_sse_lines_extracts_content_and_usage() -> None:
    events = list(
        parse_openai_sse_lines(
            [
                'data: {"choices":[{"delta":{"content":"hi"}}]}\n',
                'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":1}}\n',
                "data: [DONE]\n",
            ]
        )
    )

    assert [event.content for event in events] == ["hi", ""]
    assert events[-1].prompt_tokens == 4
    assert events[-1].completion_tokens == 1


def test_openai_provider_rejects_non_openai_model() -> None:
    model = ModelConfig(
        name="claude",
        type="anthropic",
        base_url="https://example.com",
        model_id="claude",
        pinned_revision="manual",
        price_per_1k_tokens=TokenPrices(input=1, output=1),
    )

    with pytest.raises(ProviderError, match="not openai"):
        OpenAIStreamingProvider(model)
