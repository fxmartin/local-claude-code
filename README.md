# local-code-bench

Benchmark harness for local, cloud, and agentic coding models on Apple Silicon.

## Development

Install the project and development tools:

```bash
uv sync
```

Run the test suite:

```bash
uv run pytest
```

Show the current benchmark CLI stub:

```bash
uv run bench --help
```

## Endpoint Mode

Endpoint models are configured in `configs/models.yaml`. Add a new OpenAI-compatible
backend by adding another `models` entry with a unique `name`, endpoint `base_url`,
`model_id`, pinned revision label, and input/output prices per 1k tokens.

Run one prompt against a configured model:

```bash
uv run bench --model local-example --prompt "Write a Python function that adds two numbers."
```

The command streams `/v1/chat/completions`, measures TTFT, latency, token counts,
prefill tok/s, and decode tok/s, then writes one raw JSONL record under `results/`.
If an endpoint omits usage data, token counts are estimated locally and flagged in
the record.
