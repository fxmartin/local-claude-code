"""Configuration loading for endpoint benchmark targets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

ModelType = Literal["openai", "anthropic"]


class ConfigError(ValueError):
    """Raised when benchmark configuration is invalid."""


@dataclass(frozen=True)
class TokenPrices:
    input: float
    output: float


@dataclass(frozen=True)
class ModelConfig:
    name: str
    type: ModelType
    base_url: str
    model_id: str
    pinned_revision: str
    price_per_1k_tokens: TokenPrices
    api_key_env: str | None = None


def load_models(path: str | Path) -> dict[str, ModelConfig]:
    """Load and validate endpoint model configs from YAML."""

    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"model config not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("models.yaml must contain a top-level mapping")

    entries = raw.get("models")
    if not isinstance(entries, list):
        raise ConfigError("models.yaml field 'models' must be a list")

    models: dict[str, ModelConfig] = {}
    for index, entry in enumerate(entries):
        model = _parse_model(entry, index)
        if model.name in models:
            raise ConfigError(f"models[{index}].name duplicates '{model.name}'")
        models[model.name] = model

    return models


def _parse_model(entry: Any, index: int) -> ModelConfig:
    if not isinstance(entry, dict):
        raise ConfigError(f"models[{index}] must be a mapping")

    name = _required_str(entry, "name", index)
    model_type = _required_str(entry, "type", index)
    if model_type not in {"openai", "anthropic"}:
        raise ConfigError(f"models[{index}].type must be 'openai' or 'anthropic'")

    prices = entry.get("price_per_1k_tokens")
    if not isinstance(prices, dict):
        raise ConfigError(f"models[{index}].price_per_1k_tokens must be a mapping")

    return ModelConfig(
        name=name,
        type=model_type,  # type: ignore[arg-type]
        base_url=_required_str(entry, "base_url", index).rstrip("/"),
        model_id=_required_str(entry, "model_id", index),
        pinned_revision=_required_str(entry, "pinned_revision", index),
        price_per_1k_tokens=TokenPrices(
            input=_required_number(prices, "input", index, "price_per_1k_tokens"),
            output=_required_number(prices, "output", index, "price_per_1k_tokens"),
        ),
        api_key_env=_optional_str(entry, "api_key_env", index),
    )


def _required_str(entry: dict[str, Any], field: str, index: int) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"models[{index}].{field} must be a non-empty string")
    return value


def _optional_str(entry: dict[str, Any], field: str, index: int) -> str | None:
    value = entry.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"models[{index}].{field} must be a non-empty string when set")
    return value


def _required_number(
    entry: dict[str, Any],
    field: str,
    index: int,
    parent: str,
) -> float:
    value = entry.get(field)
    if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"models[{index}].{parent}.{field} must be a non-negative number")
    return float(value)
