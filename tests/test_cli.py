from __future__ import annotations

import subprocess
import sys
from importlib.metadata import version

import pytest

from local_code_bench.cli import main
from local_code_bench.config import AgentConfig
from local_code_bench.results import append_jsonl
from local_code_bench.tasks import BenchmarkTask


def test_main_help_prints_usage(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    assert "usage: bench" in output


def test_bench_help_entrypoint_exits_successfully() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "local_code_bench.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "usage: bench" in result.stdout


def test_main_version_matches_package_metadata(capsys) -> None:
    assert main(["--version"]) == 0

    assert capsys.readouterr().out.strip() == version("local-code-bench")


def test_agent_mode_resume_skips_completed_task(tmp_path, monkeypatch, capsys) -> None:
    result_path = tmp_path / "agent.jsonl"
    append_jsonl(result_path, {"run_mode": "agent", "agent": "codex", "task_id": "suite/1"})
    task = BenchmarkTask("suite/1", "humaneval", "prompt", "assert True", "solution", "v")
    agent = AgentConfig("codex", "codex", "codex", "workspace-write", 10)

    monkeypatch.setattr("local_code_bench.cli.load_agents", lambda _path: {"codex": agent})
    monkeypatch.setattr("local_code_bench.cli.load_suite", lambda _suite, cache_dir: [task])

    def fail_run_codex_task(**_kwargs):
        raise AssertionError("resume should skip completed agent task")

    monkeypatch.setattr("local_code_bench.cli.run_codex_task", fail_run_codex_task)

    exit_code = main(
        [
            "--mode",
            "agent",
            "--agent",
            "codex",
            "--suite",
            "humaneval",
            "--run-file",
            str(result_path),
            "--resume",
        ]
    )

    assert exit_code == 0
    assert "[1/1] codex suite/1: skipped" in capsys.readouterr().out
