"""Tests for Story 10.5-001: sweep model list and engine-version capture."""

from __future__ import annotations

from pathlib import Path

import pytest

from local_code_bench.config import ConfigError
from local_code_bench.opencode.engine_version import capture_engine_version
from local_code_bench.opencode.sweep import read_model_list


# --- read_model_list -------------------------------------------------------


def test_read_model_list_returns_one_name_per_line(tmp_path: Path) -> None:
    path = tmp_path / "models.txt"
    path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    assert read_model_list(path) == ["alpha", "beta", "gamma"]


def test_read_model_list_skips_blanks_and_comments(tmp_path: Path) -> None:
    path = tmp_path / "models.txt"
    path.write_text(
        "# header comment\n"
        "alpha\n"
        "\n"
        "  beta  # trailing comment\n"
        "   \n"
        "gamma\n",
        encoding="utf-8",
    )

    assert read_model_list(path) == ["alpha", "beta", "gamma"]


def test_read_model_list_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="sweep model list not found"):
        read_model_list(tmp_path / "nope.txt")


def test_read_model_list_empty_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "models.txt"
    path.write_text("# only comments\n\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="sweep model list is empty"):
        read_model_list(path)


# --- capture_engine_version ------------------------------------------------


def test_capture_engine_version_none_engine_makes_no_call() -> None:
    def fail(_url: str, _timeout: float) -> str:
        raise AssertionError("must not fetch for an unset engine")

    assert capture_engine_version(None, "http://localhost:9000/v1", fetch=fail) is None


def test_capture_engine_version_unknown_engine_makes_no_call() -> None:
    def fail(_url: str, _timeout: float) -> str:
        raise AssertionError("must not fetch for an engine without a version endpoint")

    assert capture_engine_version("dflash", "http://localhost:8000/v1", fetch=fail) is None


def test_capture_engine_version_ollama_reads_version_off_host_root() -> None:
    seen: dict[str, str] = {}

    def fetch(url: str, _timeout: float) -> str:
        seen["url"] = url
        return '{"version": "0.5.7"}'

    version = capture_engine_version(
        "ollama", "http://127.0.0.1:11434/v1", fetch=fetch
    )

    assert version == "0.5.7"
    # The /v1 suffix is stripped so the version path hangs off the host root.
    assert seen["url"] == "http://127.0.0.1:11434/api/version"


def test_capture_engine_version_swallows_transport_errors() -> None:
    def boom(_url: str, _timeout: float) -> str:
        raise OSError("connection refused")

    assert capture_engine_version("ollama", "http://127.0.0.1:11434/v1", fetch=boom) is None


def test_capture_engine_version_malformed_body_is_none() -> None:
    assert (
        capture_engine_version(
            "ollama", "http://127.0.0.1:11434/v1", fetch=lambda _u, _t: "not json"
        )
        == "not json"
    )


def test_capture_engine_version_missing_key_is_none() -> None:
    assert (
        capture_engine_version(
            "ollama", "http://127.0.0.1:11434/v1", fetch=lambda _u, _t: "{}"
        )
        is None
    )
