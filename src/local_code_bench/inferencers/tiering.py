"""Promote a model from the external tier to local disk (Epic-12, Story 12.3-001).

Epic-12 keeps models on two tiers: the fast internal disk (``local``) and an
attached SSD (``external``, see :mod:`.external`). *Promoting* copies a model from
the external SSD into the correct per-format local store so it can be served from
fast storage — without ever risking a corrupt or half-copied model.

The operation is **copy → verify → atomically publish**, never a move:

* The external source is only ever *read* — promote never deletes it, so a
  successful promote leaves the model present on both tiers (a redundancy the disk
  report can later flag). There is therefore no path to data loss on the source.
* The copy lands in a hidden staging path beside the destination and is verified
  (byte size **and** a content hash) against the source before it is published
  with a single atomic :func:`os.replace`. A reader of the local store never sees
  a partial model: the destination either does not exist or is the complete,
  verified copy.
* Any failure mid-copy — an I/O error or an integrity mismatch — cleans up the
  staging path and raises, leaving both tiers exactly as they were.

Promote refuses up front, moving no bytes, when the external tier is offline, when
an inferencer that could serve the model is currently running (reusing the Epic-08
active-engine state), when the model is already present locally, or when local
free space is insufficient (the error suggests how much to free).

Every side effect is injectable (``free_bytes``, ``status_fn``, ``copy_fn``) so
the whole flow is testable against a temp tree with no real SSD, processes, or
disk-full condition.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ..config import ExternalRepoConfig, InferencerConfig
from . import manager
from .external import check_availability
from .inventory import LocalModel, expand_store_path

__all__ = [
    "PromoteError",
    "PromotePlan",
    "PromoteResult",
    "plan_promotion",
    "promote_model",
    "serving_blockers",
]

#: Suffix of the hidden staging path a promote copies into before publishing.
_STAGING_SUFFIX = ".promote-tmp"


class PromoteError(RuntimeError):
    """Raised when a promote cannot proceed or must abort.

    Carrying this distinct type lets a caller (CLI/web) distinguish an expected,
    explained refusal — offline tier, in-use model, no space, integrity mismatch —
    from an unexpected crash, and surface the message verbatim.
    """


@dataclass(frozen=True)
class PromotePlan:
    """The resolved source/destination of a promote, before any bytes move.

    Pure to compute from the model and its destination engine, so a caller can show
    *what would happen* (a dry run) without touching the disk.
    """

    name: str
    store_format: str
    source: Path
    destination: Path
    size_bytes: int


@dataclass(frozen=True)
class PromoteResult:
    """Outcome of a completed promote: the plan plus the verified published copy."""

    plan: PromotePlan
    destination: Path
    bytes_copied: int
    verified: bool


def plan_promotion(
    source: LocalModel,
    inferencer: InferencerConfig,
    *,
    home: Path | None = None,
) -> PromotePlan:
    """Resolve where an external model would land in ``inferencer``'s local store.

    The destination mirrors the source's on-disk basename under the engine's first
    configured ``model_store`` directory. Raises :class:`PromoteError` when the
    source is not an external-tier record or the engine declares no local store —
    the two preconditions that make a promote meaningless.
    """

    if source.tier != "external":
        raise PromoteError(
            f"{source.name} is on the {source.tier} tier, not external — nothing to promote"
        )
    if not inferencer.model_store:
        raise PromoteError(
            f"inferencer {inferencer.name} declares no local model store to promote into"
        )

    source_path = Path(source.path)
    store_dir = expand_store_path(inferencer.model_store[0], home=home)
    destination = store_dir / source_path.name
    return PromotePlan(
        name=source.name,
        store_format=source.store_format,
        source=source_path,
        destination=destination,
        size_bytes=source.size_bytes,
    )


def serving_blockers(
    source: LocalModel,
    configs: Mapping[str, InferencerConfig],
    state_dir: str | Path,
    *,
    status_fn: Callable[[InferencerConfig, str | Path], manager.InferencerStatus] = manager.status,
) -> list[str]:
    """Names of running engines that could be serving ``source`` right now.

    An engine could serve the model when it stores the same on-disk format; moving
    the bytes out from under a live server risks a torn read, so a running match
    blocks the promote. Reuses the Epic-08 per-engine state via ``status_fn``
    (injected so the in-use check is testable without real processes).
    """

    blockers: list[str] = []
    for name, cfg in configs.items():
        if cfg.store_format != source.store_format:
            continue
        if status_fn(cfg, state_dir).running:
            blockers.append(name)
    return blockers


def promote_model(
    source: LocalModel,
    inferencer: InferencerConfig,
    external_cfg: ExternalRepoConfig,
    configs: Mapping[str, InferencerConfig],
    state_dir: str | Path,
    *,
    home: Path | None = None,
    free_bytes: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free,
    status_fn: Callable[[InferencerConfig, str | Path], manager.InferencerStatus] = manager.status,
    copy_fn: Callable[[Path, Path], None] | None = None,
) -> PromoteResult:
    """Promote ``source`` from the external tier into ``inferencer``'s local store.

    Copies the external model into a staging path, verifies it (size + content
    hash) against the source, and only then publishes it atomically as a local
    copy. Refuses up front — moving no bytes — when the external tier is offline,
    a serving engine is running, the model already exists locally, or local free
    space is insufficient; aborts and cleans up the partial copy on any I/O error
    or integrity mismatch, always leaving the external source intact.

    Raises :class:`PromoteError` for every refusal and abort.
    """

    plan = plan_promotion(source, inferencer, home=home)

    if not check_availability(external_cfg, home=home).is_mounted:
        raise PromoteError(
            f"external tier is offline — plug in the SSD before promoting {plan.name}"
        )

    if not plan.source.exists():
        raise PromoteError(f"external source for {plan.name} is missing: {plan.source}")

    blockers = serving_blockers(source, configs, state_dir, status_fn=status_fn)
    if blockers:
        joined = ", ".join(sorted(blockers))
        raise PromoteError(
            f"{joined} is running and could be serving {plan.name} — "
            "stop it before promoting so no bytes are moved under a live engine"
        )

    if plan.destination.exists():
        raise PromoteError(
            f"{plan.name} is already present locally at {plan.destination} — nothing to promote"
        )

    free = free_bytes(_existing_ancestor(plan.destination.parent))
    if free < plan.size_bytes:
        shortfall = plan.size_bytes - free
        raise PromoteError(
            f"insufficient local free space to promote {plan.name}: need "
            f"{_human_bytes(plan.size_bytes)}, have {_human_bytes(free)} — "
            f"free at least {_human_bytes(shortfall)} first (both tiers left untouched)"
        )

    source_hash = _content_hash(plan.source)
    staging = plan.destination.with_name(plan.destination.name + _STAGING_SUFFIX)
    copy = copy_fn or _copy_path
    plan.destination.parent.mkdir(parents=True, exist_ok=True)
    _remove_path(staging)

    try:
        copy(plan.source, staging)
        copied = _path_size(staging)
        if copied != plan.size_bytes or _content_hash(staging) != source_hash:
            raise PromoteError(
                f"integrity check failed promoting {plan.name}: the local copy does "
                "not match the external source — aborting, source left intact"
            )
        os.replace(staging, plan.destination)
    except PromoteError:
        _remove_path(staging)
        raise
    except OSError as exc:
        _remove_path(staging)
        raise PromoteError(
            f"failed to promote {plan.name}: {exc} — partial copy removed, source intact"
        ) from exc

    return PromoteResult(
        plan=plan,
        destination=plan.destination,
        bytes_copied=plan.size_bytes,
        verified=True,
    )


# --- Filesystem helpers (pure given their inputs) --------------------------


def _copy_path(source: Path, destination: Path) -> None:
    """Copy a file or directory tree, preserving metadata."""

    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _remove_path(path: Path) -> None:
    """Delete a file or directory tree if present; never raise."""

    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def _existing_ancestor(path: Path) -> Path:
    """Nearest existing directory at or above ``path`` (for a free-space probe)."""

    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            break
        current = parent
    return current


def _path_size(path: Path) -> int:
    """Total on-disk size of a file or directory tree (symlinks not followed)."""

    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file() and not child.is_symlink():
            total += child.stat().st_size
    return total


def _content_hash(path: Path) -> str:
    """Order-stable SHA-256 over a file's bytes or a tree's relative path + bytes.

    For a directory the digest folds in each file's path-relative-to-root and its
    contents in sorted order, so a byte-faithful copy hashes identically while a
    missing, extra, or altered file changes the digest.
    """

    digest = hashlib.sha256()
    if path.is_file():
        _absorb_file(digest, path)
        return digest.hexdigest()
    for child in sorted(path.rglob("*")):
        if child.is_file() and not child.is_symlink():
            digest.update(str(child.relative_to(path)).encode("utf-8"))
            digest.update(b"\0")
            _absorb_file(digest, child)
    return digest.hexdigest()


def _absorb_file(digest: "hashlib._Hash", path: Path) -> None:
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)


_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")


def _human_bytes(count: int) -> str:
    """Render a byte count as a compact human-readable string (e.g. ``1.5 GiB``)."""

    size = float(count)
    for unit in _UNITS:
        if size < 1024 or unit == _UNITS[-1]:
            precision = 0 if unit == "B" else 1
            return f"{size:.{precision}f} {unit}"
        size /= 1024
    return f"{count} B"
