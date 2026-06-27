"""Tests for sharing detection across inferencers (Story 11.3-001).

Covers grouping normalized :class:`LocalModel` records into logical models by
``(store_format, content identity)`` so two engines pointing at the same on-disk
artifact are reported as sharing one model, while incompatible formats and
single-owner models are never falsely merged or flagged.
"""

from __future__ import annotations

from local_code_bench.inferencers.inventory import (
    LocalModel,
    SharedModel,
    group_models,
    shared_models,
)


def _model(
    inferencer: str,
    identity: str,
    *,
    store_format="gguf",
    name: str = "model",
    path: str = "/store/model.gguf",
    size_bytes: int = 100,
    quant: str | None = None,
    provider: str | None = None,
) -> LocalModel:
    return LocalModel(
        inferencer=inferencer,
        store_format=store_format,
        name=name,
        path=path,
        size_bytes=size_bytes,
        quant=quant,
        provider=provider,
        identity=identity,
    )


# --- Shared logical models -------------------------------------------------


def test_two_engines_same_gguf_file_share_one_model() -> None:
    # llama.cpp and LM Studio both point at the same .gguf realpath.
    models = [
        _model("llama.cpp", "/models/qwen.gguf", path="/a/qwen.gguf"),
        _model("lmstudio", "/models/qwen.gguf", path="/b/qwen.gguf"),
    ]

    groups = group_models(models)

    assert len(groups) == 1
    group = groups[0]
    assert group.is_shared
    assert group.inferencers == ("llama.cpp", "lmstudio")
    assert group.identity == "/models/qwen.gguf"
    assert len(group.models) == 2


def test_two_engines_same_hf_cache_share_one_model() -> None:
    # Two MLX/safetensors engines pointing at one HuggingFace cache entry.
    models = [
        _model("mlx", "/hf/models--org--repo", store_format="hf-safetensors"),
        _model("vllm", "/hf/models--org--repo", store_format="hf-safetensors"),
    ]

    groups = group_models(models)

    assert len(groups) == 1
    assert groups[0].inferencers == ("mlx", "vllm")
    assert groups[0].is_shared


def test_shared_models_returns_only_multi_owner_groups() -> None:
    models = [
        _model("llama.cpp", "/models/shared.gguf"),
        _model("lmstudio", "/models/shared.gguf"),
        _model("gpt4all", "/models/solo.gguf", path="/c/solo.gguf"),
    ]

    shared = shared_models(models)

    assert len(shared) == 1
    assert shared[0].identity == "/models/shared.gguf"
    assert shared[0].inferencers == ("llama.cpp", "lmstudio")


# --- Single-owner models ---------------------------------------------------


def test_single_owner_model_is_not_flagged_shared() -> None:
    models = [_model("llama.cpp", "/models/solo.gguf")]

    groups = group_models(models)

    assert len(groups) == 1
    assert groups[0].inferencers == ("llama.cpp",)
    assert not groups[0].is_shared


def test_same_inferencer_twice_is_one_owner_not_shared() -> None:
    # A scan that surfaces one artifact twice for the same engine de-dupes the
    # owner — it is not spuriously shared with itself.
    models = [
        _model("ollama", "sha256:abc", store_format="ollama"),
        _model("ollama", "sha256:abc", store_format="ollama"),
    ]

    groups = group_models(models)

    assert len(groups) == 1
    assert groups[0].inferencers == ("ollama",)
    assert not groups[0].is_shared
    assert len(groups[0].models) == 2


# --- No false merges -------------------------------------------------------


def test_incompatible_formats_same_identity_are_not_merged() -> None:
    # Even with a colliding identity, differing formats stay separate.
    models = [
        _model("llama.cpp", "/shared/path", store_format="gguf"),
        _model("mlx", "/shared/path", store_format="mlx"),
    ]

    groups = group_models(models)

    assert len(groups) == 2
    assert all(not g.is_shared for g in groups)
    formats = {g.store_format for g in groups}
    assert formats == {"gguf", "mlx"}


def test_different_identities_same_format_are_not_merged() -> None:
    models = [
        _model("llama.cpp", "/models/a.gguf", path="/a.gguf"),
        _model("lmstudio", "/models/b.gguf", path="/b.gguf"),
    ]

    groups = group_models(models)

    assert len(groups) == 2
    assert all(not g.is_shared for g in groups)


# --- Ordering and stability ------------------------------------------------


def test_groups_preserve_first_seen_order() -> None:
    models = [
        _model("e1", "/z.gguf", path="/z.gguf"),
        _model("e2", "/a.gguf", path="/a.gguf"),
        _model("e3", "/z.gguf", path="/z2.gguf"),
    ]

    groups = group_models(models)

    assert [g.identity for g in groups] == ["/z.gguf", "/a.gguf"]
    assert groups[0].inferencers == ("e1", "e3")


def test_empty_input_yields_no_groups() -> None:
    assert group_models([]) == []
    assert shared_models([]) == []


def test_shared_model_is_frozen() -> None:
    import dataclasses

    import pytest

    group = group_models([_model("e1", "/x.gguf")])[0]
    assert isinstance(group, SharedModel)
    with pytest.raises(dataclasses.FrozenInstanceError):
        group.identity = "mutated"  # type: ignore[misc]
