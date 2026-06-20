from __future__ import annotations

import json

from local_code_bench.results import append_jsonl, new_run_path


def test_new_run_path_is_unique_and_jsonl(tmp_path) -> None:
    first = new_run_path(tmp_path, prefix="model")
    second = new_run_path(tmp_path, prefix="model")

    assert first != second
    assert first.suffix == ".jsonl"
    assert first.parent == tmp_path


def test_append_jsonl_writes_one_record_per_line(tmp_path) -> None:
    path = tmp_path / "run.jsonl"

    append_jsonl(path, {"model": "a", "tokens": 3})
    append_jsonl(path, {"model": "b", "tokens": 4})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["model"] for line in lines] == ["a", "b"]
