"""Story 10.4-001: comparable scorecard with provenance note.

One *scored* OpenCode run — Task A coding ability and Task B rule-following for a
single model/quant/provider/mode — collapses into one :class:`ScorecardRow`.
Rows are appended to ``results/scorecard.csv`` (re-scorable, machine-readable) and
rendered as a Markdown table sorted *passing rows first, then by Task B error rate
ascending* — the article's ordering.

The headline lesson of the source article is that quant **source** matters as much
as bit-width: Unsloth's IQ3_XXS scored 5.0% error where Bartowski's quant of the
*same model at the same bit level* scored 100%. :func:`provenance_note` makes that
detector first-class — it groups rows by base model + bit-width parsed from the
quant string and surfaces provider-only pairs together with their score delta.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from re import search
from statistics import mean, pstdev

from local_code_bench.opencode.blackbox import TaskAResult
from local_code_bench.opencode.taskb import TaskBScore
from local_code_bench.results import append_jsonl

#: CSV column order — also the JSONL/Markdown field set. Stable so stored files
#: stay re-scorable across runs.
SCORECARD_COLUMNS: tuple[str, ...] = (
    "model",
    "quant",
    "provider",
    "mode",
    "compiled",
    "tests_passed",
    "tests_total",
    "task_a_flag",
    "error_rate",
    "coverage",
    "collisions",
    "task_b_flag",
    "tokens_per_second",
    "wall_clock_seconds",
    "engine_version",
)

#: Rendered in place of an absent value (no quant/provider, or unmeasured speed).
_EMPTY = "-"


@dataclass(frozen=True)
class ScorecardRow:
    """One scored run: provenance plus both task outcomes and run speed."""

    model: str
    quant: str | None
    provider: str | None
    mode: str
    compiled: bool
    tests_passed: int
    tests_total: int
    task_a_flag: str | None
    error_rate: float
    coverage: float
    collisions: int
    task_b_flag: str | None
    tokens_per_second: float | None
    wall_clock_seconds: float | None
    engine_version: str | None = None


def build_row(
    *,
    model_name: str,
    quant: str | None,
    provider: str | None,
    mode: str,
    task_a: TaskAResult,
    task_b: TaskBScore,
    tokens_per_second: float | None,
    wall_clock_seconds: float | None,
    engine_version: str | None = None,
) -> ScorecardRow:
    """Collapse the two task scores plus provenance into one scorecard row."""

    return ScorecardRow(
        model=model_name,
        quant=quant,
        provider=provider,
        mode=mode,
        compiled=task_a.compiled,
        tests_passed=task_a.tests_passed,
        tests_total=task_a.tests_total,
        task_a_flag=task_a.flag,
        error_rate=task_b.error_rate,
        coverage=task_b.coverage,
        collisions=task_b.collisions,
        task_b_flag=task_b.flag,
        tokens_per_second=tokens_per_second,
        wall_clock_seconds=wall_clock_seconds,
        engine_version=engine_version,
    )


def row_passed(row: ScorecardRow) -> bool:
    """True when Task A compiled and the whole black-box suite passed.

    This is the article's "passed all CLI unit tests" bar — the signal used to
    float passing models to the top of the rendered table.
    """

    return row.compiled and row.tests_total > 0 and row.tests_passed == row.tests_total


def parse_bit_width(quant: str | None) -> str | None:
    """Parse the numeric bit-width from a quant string (``IQ3_XXS`` -> ``"3"``).

    Returns ``None`` when the string is empty or carries no digits, so such rows
    are excluded from same-bit-width provenance comparisons.
    """

    if not quant:
        return None
    match = search(r"\d+", quant)
    return match.group(0) if match else None


# --- Persistence -----------------------------------------------------------


def _to_csv_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _row_to_dict(row: ScorecardRow) -> dict[str, object]:
    return {column: getattr(row, column) for column in SCORECARD_COLUMNS}


def append_run(
    csv_path: str | Path,
    row: ScorecardRow,
    *,
    jsonl_path: str | Path | None = None,
) -> None:
    """Append one scored run to the scorecard CSV (writing the header if new).

    When ``jsonl_path`` is given, the same row is also appended as a JSONL
    provenance record (reusing ``results.append_jsonl``) so the scorecard stays
    re-scorable offline alongside the human-readable CSV.
    """

    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if write_header:
            writer.writerow(SCORECARD_COLUMNS)
        writer.writerow([_to_csv_value(getattr(row, column)) for column in SCORECARD_COLUMNS])

    if jsonl_path is not None:
        append_jsonl(jsonl_path, _row_to_dict(row))


def _from_csv(record: dict[str, str]) -> ScorecardRow:
    def text(name: str) -> str | None:
        value = record.get(name, "")
        return value if value != "" else None

    def number(name: str) -> float | None:
        value = record.get(name, "")
        return float(value) if value != "" else None

    return ScorecardRow(
        model=record["model"],
        quant=text("quant"),
        provider=text("provider"),
        mode=record["mode"],
        compiled=record["compiled"] == "true",
        tests_passed=int(record["tests_passed"]),
        tests_total=int(record["tests_total"]),
        task_a_flag=text("task_a_flag"),
        error_rate=float(record["error_rate"]),
        coverage=float(record["coverage"]),
        collisions=int(record["collisions"]),
        task_b_flag=text("task_b_flag"),
        tokens_per_second=number("tokens_per_second"),
        wall_clock_seconds=number("wall_clock_seconds"),
        engine_version=text("engine_version"),
    )


def read_runs(csv_path: str | Path) -> list[ScorecardRow]:
    """Read every stored scorecard row back from the CSV (empty if absent)."""

    path = Path(csv_path)
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return [_from_csv(record) for record in csv.DictReader(handle)]


# --- Rendering -------------------------------------------------------------

_HEADERS: tuple[str, ...] = (
    "Model",
    "Quant",
    "Provider",
    "Mode",
    "Task A",
    "Task B err%",
    "Coverage%",
    "Collisions",
    "tok/s",
    "Wall (s)",
    "Engine ver",
)


def _sort_key(row: ScorecardRow) -> tuple[int, float]:
    # Passing rows first (group 0), then by Task B error rate ascending.
    return (0 if row_passed(row) else 1, row.error_rate)


def _task_a_cell(row: ScorecardRow) -> str:
    mark = "PASS" if row.compiled else "FAIL"
    cell = f"{mark} {row.tests_passed}/{row.tests_total}"
    if row.task_a_flag:
        cell += f" {row.task_a_flag}"
    return cell


def _task_b_cell(row: ScorecardRow) -> str:
    cell = f"{row.error_rate * 100:.1f}%"
    if row.task_b_flag:
        cell += f" {row.task_b_flag}"
    return cell


def _ratio_cell(value: float) -> str:
    return f"{value * 100:.1f}%"


def _float_cell(value: float | None, *, precision: int) -> str:
    return _EMPTY if value is None else f"{value:.{precision}f}"


def render_markdown(rows: list[ScorecardRow]) -> str:
    """Render the comparable scorecard as a Markdown table.

    Rows are ordered passing-first, then by Task B error rate ascending. Columns
    cover model/quant/provider/mode, Task A (build + tests n/total), Task B
    (error %, coverage %, collisions), tokens/sec, and wall-clock.
    """

    lines = [
        "| " + " | ".join(_HEADERS) + " |",
        "|" + "|".join(["---"] * len(_HEADERS)) + "|",
    ]
    for row in sorted(rows, key=_sort_key):
        cells = (
            row.model,
            row.quant or _EMPTY,
            row.provider or _EMPTY,
            row.mode,
            _task_a_cell(row),
            _task_b_cell(row),
            _ratio_cell(row.coverage),
            str(row.collisions),
            _float_cell(row.tokens_per_second, precision=1),
            _float_cell(row.wall_clock_seconds, precision=2),
            row.engine_version or _EMPTY,
        )
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def provenance_note(rows: list[ScorecardRow]) -> str:
    """Surface same-model, same-bit-width rows that differ only by quant provider.

    This is the Unsloth-vs-Bartowski detector made first-class: rows are grouped
    by ``(model, bit-width)`` parsed from the quant string, and any group spanning
    two or more distinct providers is reported with the Task B error-rate delta
    between its best and worst provider.
    """

    groups: dict[tuple[str, str], list[ScorecardRow]] = {}
    for row in rows:
        bit_width = parse_bit_width(row.quant)
        if bit_width is None or row.provider is None:
            continue
        groups.setdefault((row.model, bit_width), []).append(row)

    bullets: list[str] = []
    for (model, bit_width), members in groups.items():
        # Best (lowest) Task B error rate per provider, sorted worst delta first.
        best_by_provider: dict[str, ScorecardRow] = {}
        for member in members:
            current = best_by_provider.get(member.provider)  # type: ignore[arg-type]
            if current is None or member.error_rate < current.error_rate:
                best_by_provider[member.provider] = member  # type: ignore[index]
        if len(best_by_provider) < 2:
            continue

        ranked = sorted(best_by_provider.values(), key=lambda member: member.error_rate)
        delta = (ranked[-1].error_rate - ranked[0].error_rate) * 100
        providers = " vs ".join(
            f"{member.provider} ({member.quant}) {member.error_rate * 100:.1f}% error"
            for member in ranked
        )
        bullets.append(
            f"- **{model}** at bit-width {bit_width}: {providers} "
            f"— Δ {delta:.1f}pp on Task B error"
        )

    heading = "## Provenance note"
    if not bullets:
        return (
            f"{heading}\n\nNo same-model, same-bit-width provider pairs to compare "
            "(the Unsloth-vs-Bartowski detector found nothing yet)."
        )
    intro = (
        "Same base model at the same bit-width from different quant providers "
        "(the Unsloth-vs-Bartowski lesson):"
    )
    return "\n".join([heading, "", intro, "", *bullets])


def variance_note(rows: list[ScorecardRow]) -> str:
    """Surface run-to-run spread across repeated runs of one config.

    Rows are grouped by the full run identity ``(model, quant, provider, mode)``;
    only groups with two or more runs — i.e. ``--repeat N`` or a sweep that names a
    config twice — are reported. The article saw real run-to-run swings on the 35B,
    so the spread is *shown* (mean, min, max, and a σ in percentage points for Task
    B error, plus the tok/s range and the Task A pass count) rather than averaged
    away into a single misleading number.
    """

    groups: dict[tuple[str, str | None, str | None, str], list[ScorecardRow]] = {}
    for row in rows:
        groups.setdefault((row.model, row.quant, row.provider, row.mode), []).append(row)

    bullets: list[str] = []
    for (model, quant, provider, mode), members in groups.items():
        if len(members) < 2:
            continue
        count = len(members)
        errors = [member.error_rate for member in members]
        speeds = [m.tokens_per_second for m in members if m.tokens_per_second is not None]
        passes = sum(1 for member in members if row_passed(member))
        tag = "/".join(part for part in (quant, provider) if part) or _EMPTY
        spread = (
            f"Task B err mean {mean(errors) * 100:.1f}% "
            f"(min {min(errors) * 100:.1f}%, max {max(errors) * 100:.1f}%, "
            f"σ {pstdev(errors) * 100:.1f}pp); Task A passed {passes}/{count} runs"
        )
        if speeds:
            spread += f"; tok/s {min(speeds):.1f}–{max(speeds):.1f}"
        bullets.append(f"- **{model}** ({tag}, {mode}): {count} runs — {spread}")

    heading = "## Variance"
    if not bullets:
        return (
            f"{heading}\n\nNo repeated runs to compare "
            "(use --repeat N, or a sweep that names a config more than once)."
        )
    intro = "Run-to-run spread across repeated runs (variance is surfaced, not averaged away):"
    return "\n".join([heading, "", intro, "", *bullets])
