"""Model-list parsing for the OpenCode engine/mode sweep (Story 10.5-001).

``run-bench.sh --sweep models.txt`` benchmarks every model named in a file and
folds the results into one consolidated scorecard, so engine and mode effects can
be isolated across whatever is installed (the GPT-OSS default-vs-thinking lesson).
This module owns the one piece of that flow worth isolating and unit-testing: the
file format. The iteration, scoring, and scorecard rendering live in the CLI,
reusing the existing single-run path so a sweep is just "the single run, looped".
"""

from __future__ import annotations

from pathlib import Path

from local_code_bench.config import ConfigError


def read_model_list(path: str | Path) -> list[str]:
    """Read a sweep model list: one configured model name per line.

    Blank lines and ``#`` comments (whole-line or trailing) are ignored, so the
    file can be annotated. Raises :class:`ConfigError` when the file is missing or
    contains no model names, matching the rest of the CLI's error contract.
    """

    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"sweep model list not found: {file_path}") from exc

    names: list[str] = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            names.append(stripped)

    if not names:
        raise ConfigError(f"sweep model list is empty: {file_path}")
    return names
