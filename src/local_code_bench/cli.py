"""Command-line entrypoint for the benchmark harness."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from local_code_bench.config import ConfigError, load_models
from local_code_bench.metrics import CompletionMeasurement, capture_stream_metrics
from local_code_bench.provider import ChatRequest, OpenAIStreamingProvider, ProviderError
from local_code_bench.results import append_jsonl, new_run_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bench",
        description="Run coding-model benchmark tasks.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the package version and exit",
    )
    parser.add_argument(
        "--config",
        default="configs/models.yaml",
        help="path to endpoint model YAML config",
    )
    parser.add_argument(
        "--model",
        help="configured model name to run",
    )
    parser.add_argument(
        "--prompt",
        help="single prompt to send to the selected model",
    )
    parser.add_argument(
        "--results-dir",
        default="results",
        help="directory for raw JSONL run output",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from local_code_bench import __version__

        print(__version__)
        return 0

    if args.model or args.prompt:
        if not args.model or not args.prompt:
            parser.error("--model and --prompt must be provided together")
        try:
            result_path, measurement = run_single_prompt(
                config_path=Path(args.config),
                model_name=args.model,
                prompt=args.prompt,
                results_dir=Path(args.results_dir),
            )
        except (ConfigError, ProviderError) as exc:
            print(f"bench: error: {exc}", file=sys.stderr)
            return 2

        print(
            "model={model} prompt_tokens={prompt_tokens} completion_tokens={completion_tokens} "
            "ttft={ttft} latency={latency:.3f}s results={path}".format(
                model=args.model,
                prompt_tokens=measurement.prompt_tokens,
                completion_tokens=measurement.completion_tokens,
                ttft=_format_optional_seconds(measurement.ttft_seconds),
                latency=measurement.latency_seconds,
                path=result_path,
            )
        )
        return 0

    parser.print_help()
    return 0


def run_single_prompt(
    *,
    config_path: Path,
    model_name: str,
    prompt: str,
    results_dir: Path,
) -> tuple[Path, CompletionMeasurement]:
    models = load_models(config_path)
    try:
        model = models[model_name]
    except KeyError as exc:
        available = ", ".join(sorted(models)) or "(none)"
        raise ConfigError(f"unknown model '{model_name}'. Available models: {available}") from exc

    provider = OpenAIStreamingProvider(model)
    measurement = capture_stream_metrics(
        provider.stream_chat(ChatRequest(prompt=prompt, temperature=0.0)),
        prompt,
    )
    result_path = new_run_path(results_dir, prefix=model.name)
    append_jsonl(
        result_path,
        {
            "run_mode": "endpoint",
            "model": model.name,
            "provider_type": model.type,
            "model_id": model.model_id,
            "pinned_revision": model.pinned_revision,
            "prompt": prompt,
            "raw_response": measurement.response,
            "metrics": {
                "ttft_seconds": measurement.ttft_seconds,
                "latency_seconds": measurement.latency_seconds,
                "prefill_tokens_per_second": measurement.prefill_tokens_per_second,
                "decode_tokens_per_second": measurement.decode_tokens_per_second,
            },
            "tokens": {
                "prompt": measurement.prompt_tokens,
                "completion": measurement.completion_tokens,
                "estimated": measurement.token_counts_estimated,
            },
        },
    )
    return result_path, measurement


def _format_optional_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    return f"{seconds:.3f}s"


if __name__ == "__main__":
    raise SystemExit(main())
