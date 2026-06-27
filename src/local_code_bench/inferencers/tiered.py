"""Two-tier unified model inventory (Epic-12, Story 12.2-001).

Epic-11 scans the *local* model store on the internal disk. Epic-12 adds an
*external* tier on an attached SSD (see :mod:`.external`). This module joins the
two into one view: for every logical model it reports which tiers hold it
(``local``, ``external``, or both), its size/format/provenance, and the
inferencers that could serve it — so FX always knows where a model lives.

Design:

* The external tier mirrors the local per-format store layout, so the Epic-11
  scan strategies run unchanged against the external root's subdirectories
  (:func:`scan_external_tier`).
* Tiers are merged over a tier-independent join key: an Ollama blob ``sha`` is
  the same on either drive, while file/dir stores join on ``(store_format,
  name)`` because their realpath identity differs between drives. The same model
  on both tiers is therefore reported once as :attr:`TieredModel.present_in_both`
  — a redundant-storage candidate the disk report can flag.
* A lightweight external catalog is persisted whenever the drive is mounted, so
  the offline view is non-empty. The catalog is a *cache*: it is never consulted
  while the drive is mounted (the live scan is the truth), only when offline.

Everything here is filesystem-only and pure given its inputs, so it is testable
without a real external drive (inject ``home``/``state_dir`` at a temp tree).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from ..config import ExternalRepoConfig, InferencerConfig, StoreFormat
from .external import TierAvailability, check_availability, format_dir
from .inventory import (
    LocalModel,
    Tier,
    group_models,
    normalize,
    scan_store,
)

__all__ = [
    "TieredModel",
    "TieredInventory",
    "scan_external_tier",
    "merge_tiers",
    "build_tiered_inventory",
    "external_catalog_path",
    "write_external_catalog",
    "read_external_catalog",
    "EXTERNAL_CATALOG_FILENAME",
]

#: Filename of the persisted external catalog under the state directory.
EXTERNAL_CATALOG_FILENAME = "external-catalog.json"

#: Version stamp written into the catalog so a future schema change can be
#: detected and an incompatible cache ignored rather than mis-parsed.
_CATALOG_VERSION = 1


@dataclass(frozen=True)
class TieredModel:
    """One logical model and the tiers that hold it.

    Built by :func:`merge_tiers`, this collapses the same model across tiers (and
    across the engines that can serve it) into a single row. ``tiers`` is the
    sorted set of storage tiers the model is present on; ``inferencers`` is the
    sorted, de-duplicated set of engines that could serve it. ``size_bytes`` and
    provenance are taken from a representative copy (the local one when present,
    since it is the live-scanned truth).
    """

    store_format: StoreFormat
    name: str
    size_bytes: int
    quant: str | None
    provider: str | None
    identity: str
    inferencers: tuple[str, ...]
    tiers: tuple[Tier, ...]

    @property
    def present_in_both(self) -> bool:
        """True when the same model is held on both the local and external tier."""

        return "local" in self.tiers and "external" in self.tiers


@dataclass(frozen=True)
class TieredInventory:
    """The unified two-tier inventory plus the external tier's current state.

    ``external_availability`` is ``MOUNTED`` or ``OFFLINE``. ``external_cached``
    is ``True`` when the external rows in :attr:`models` came from the persisted
    catalog (the drive is offline) rather than a live scan — so a caller can mark
    those rows ``external (offline)`` and disable move actions.
    """

    models: tuple[TieredModel, ...]
    external_availability: TierAvailability
    external_cached: bool


def scan_external_tier(
    cfg: ExternalRepoConfig,
    inferencers: Sequence[InferencerConfig],
    *,
    home: Path | None = None,
) -> list[LocalModel]:
    """Scan the external root's per-format subdirectories into external-tier models.

    Reuses the Epic-11 strategies against the external layout. Each format is
    scanned once, then fanned out to every configured inferencer that uses that
    format, so the merged view lists all engines that could serve the model
    (mirroring how a shared local store surfaces multiple engines). A format with
    no compatible inferencer is skipped — nothing on the machine could serve it.

    Assumes the tier is mounted (the caller checks availability first); a missing
    subdirectory simply yields nothing.
    """

    by_format: dict[StoreFormat, list[InferencerConfig]] = {}
    for inf in inferencers:
        if inf.store_format is not None:
            by_format.setdefault(inf.store_format, []).append(inf)

    models: list[LocalModel] = []
    for store_format, compatible in by_format.items():
        subdir = format_dir(cfg, store_format, home=home)
        found = scan_store(subdir, store_format, inferencer="", home=home)
        for stored in found:
            for inf in compatible:
                models.append(normalize(replace(stored, inferencer=inf.name), tier="external"))
    return models


def _cross_tier_key(model: LocalModel) -> tuple[str, str, str]:
    """Tier-independent join key for a logical model.

    An Ollama blob ``sha`` is identical on either drive, so it joins copies
    across tiers directly. File/dir stores cannot use their realpath identity
    (it differs per drive), so they join on ``(store_format, name)`` — a
    byte-faithful move keeps both, so the copies line up.
    """

    if model.identity.startswith("sha256:"):
        return ("id", model.store_format, model.identity)
    return ("name", model.store_format, model.name)


def merge_tiers(models: Iterable[LocalModel]) -> list[TieredModel]:
    """Merge local + external models into one row per logical model.

    Within a tier, the Epic-11 ``(store_format, identity)`` grouping de-duplicates
    a shared artifact and collects its serving engines; across tiers, those
    groups are joined on :func:`_cross_tier_key`. Provenance and size are taken
    from the local copy when present (the live-scanned truth), otherwise the
    external copy. Rows are returned in first-seen order.
    """

    order: list[tuple[str, str, str]] = []
    buckets: dict[tuple[str, str, str], dict] = {}
    for group in group_models(models):
        rep = group.models[0]
        key = _cross_tier_key(rep)
        bucket = buckets.get(key)
        if bucket is None:
            buckets[key] = bucket = {
                "tiers": set(),
                "inferencers": set(),
                "rep": None,
            }
            order.append(key)
        for member in group.models:
            bucket["tiers"].add(member.tier)
        bucket["inferencers"].update(name for name in group.inferencers if name)
        # Prefer a local representative for metadata; otherwise take the first.
        if bucket["rep"] is None or (rep.tier == "local" and bucket["rep"].tier != "local"):
            bucket["rep"] = rep

    merged: list[TieredModel] = []
    for key in order:
        bucket = buckets[key]
        rep: LocalModel = bucket["rep"]
        merged.append(
            TieredModel(
                store_format=rep.store_format,
                name=rep.name,
                size_bytes=rep.size_bytes,
                quant=rep.quant,
                provider=rep.provider,
                identity=rep.identity,
                inferencers=tuple(sorted(bucket["inferencers"])),
                tiers=tuple(sorted(bucket["tiers"])),
            )
        )
    return merged


def build_tiered_inventory(
    local_models: Iterable[LocalModel],
    external_cfg: ExternalRepoConfig | None,
    inferencers: Sequence[InferencerConfig],
    *,
    home: Path | None = None,
    state_dir: str | Path | None = None,
) -> TieredInventory:
    """Build the unified two-tier inventory, degrading gracefully when offline.

    ``local_models`` is the live Epic-11 local scan (already normalized). When an
    external tier is configured and mounted, it is scanned live and the result is
    persisted as the catalog (so the next offline run is non-empty). When it is
    offline, the external rows come from that catalog instead — flagged via
    :attr:`TieredInventory.external_cached` — and the local scan is unaffected. A
    missing or unreadable catalog simply yields no external rows (no error).
    """

    local = list(local_models)

    if external_cfg is None:
        return TieredInventory(
            models=tuple(merge_tiers(local)),
            external_availability=TierAvailability.OFFLINE,
            external_cached=False,
        )

    status = check_availability(external_cfg, home=home)
    if status.is_mounted:
        external = scan_external_tier(external_cfg, inferencers, home=home)
        if state_dir is not None:
            write_external_catalog(state_dir, external)
        cached = False
    else:
        external = read_external_catalog(state_dir) if state_dir is not None else []
        cached = bool(external)

    return TieredInventory(
        models=tuple(merge_tiers(local + external)),
        external_availability=status.availability,
        external_cached=cached,
    )


# --- Offline external catalog (a cache, never truth when mounted) ----------


def external_catalog_path(state_dir: str | Path) -> Path:
    """Path of the persisted external catalog under ``state_dir``."""

    return Path(state_dir) / EXTERNAL_CATALOG_FILENAME


def write_external_catalog(state_dir: str | Path, models: Iterable[LocalModel]) -> None:
    """Persist the live external scan so the offline view is non-empty.

    Stores only the lightweight provenance needed to render an offline row; the
    tier is implied (always ``external``) and not serialised.
    """

    path = external_catalog_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _CATALOG_VERSION,
        "models": [_model_to_dict(model) for model in models],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_external_catalog(state_dir: str | Path) -> list[LocalModel]:
    """Load the persisted external catalog, or ``[]`` if absent/unreadable.

    Returns external-tier :class:`LocalModel` records. A missing file, malformed
    JSON, or a version mismatch degrades to an empty list rather than raising —
    the offline view is then simply empty, never an error.
    """

    path = external_catalog_path(state_dir)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(doc, dict) or doc.get("version") != _CATALOG_VERSION:
        return []
    entries = doc.get("models")
    if not isinstance(entries, list):
        return []
    models: list[LocalModel] = []
    for entry in entries:
        model = _model_from_dict(entry)
        if model is not None:
            models.append(model)
    return models


def _model_to_dict(model: LocalModel) -> dict:
    return {
        "inferencer": model.inferencer,
        "store_format": model.store_format,
        "name": model.name,
        "path": model.path,
        "size_bytes": model.size_bytes,
        "quant": model.quant,
        "provider": model.provider,
        "identity": model.identity,
    }


def _model_from_dict(entry: object) -> LocalModel | None:
    if not isinstance(entry, dict):
        return None
    try:
        return LocalModel(
            inferencer=str(entry["inferencer"]),
            store_format=entry["store_format"],
            name=str(entry["name"]),
            path=str(entry["path"]),
            size_bytes=int(entry["size_bytes"]),
            quant=entry.get("quant"),
            provider=entry.get("provider"),
            identity=str(entry["identity"]),
            tier="external",
        )
    except (KeyError, TypeError, ValueError):
        return None
