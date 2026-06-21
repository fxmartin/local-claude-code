"""Optional power/energy sampling via macOS `powermetrics`.

`powermetrics` is macOS-only and requires root, so this module is best-effort: if
it is unavailable or sudo is not permitted, sampling is skipped and the run
continues with an `unavailable` summary. The parsing logic is pure and unit
tested; only the live subprocess spawn needs an Apple Silicon host to exercise.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from shutil import which

_GPU_W = re.compile(r"GPU Power:\s*([\d.]+)\s*mW")
_CPU_W = re.compile(r"CPU Power:\s*([\d.]+)\s*mW")
_COMBINED_W = re.compile(r"Combined Power[^:]*:\s*([\d.]+)\s*mW")


@dataclass(frozen=True)
class PowerSummary:
    available: bool
    samples: int
    duration_s: float
    avg_gpu_w: float
    max_gpu_w: float
    avg_cpu_w: float
    avg_combined_w: float
    energy_j: float

    @classmethod
    def unavailable(cls) -> PowerSummary:
        return cls(False, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    def as_record(self) -> dict[str, object]:
        record: dict[str, object] = {"record_type": "power"}
        record.update(asdict(self))
        return record


def powermetrics_available() -> bool:
    return sys.platform == "darwin" and which("powermetrics") is not None


def powermetrics_command(interval_s: float) -> list[str]:
    # `sudo -n` fails fast instead of hanging for a password; the harness never
    # blocks on an interactive prompt.
    return [
        "sudo",
        "-n",
        "powermetrics",
        "--samplers",
        "cpu_power,gpu_power",
        "-i",
        str(int(interval_s * 1000)),
    ]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize_powermetrics(text: str, duration_s: float) -> PowerSummary:
    """Aggregate raw `powermetrics` output into a PowerSummary (watts, joules)."""

    gpu = [float(v) / 1000.0 for v in _GPU_W.findall(text)]
    cpu = [float(v) / 1000.0 for v in _CPU_W.findall(text)]
    combined = [float(v) / 1000.0 for v in _COMBINED_W.findall(text)]
    if not combined and (cpu or gpu):
        # Some layouts omit the combined line; approximate from the parts.
        combined = [c + g for c, g in zip(cpu, gpu)]
    samples = len(combined) or len(gpu)
    if samples == 0:
        return PowerSummary.unavailable()
    avg_combined = _mean(combined)
    return PowerSummary(
        available=True,
        samples=samples,
        duration_s=round(duration_s, 3),
        avg_gpu_w=round(_mean(gpu), 3),
        max_gpu_w=round(max(gpu), 3) if gpu else 0.0,
        avg_cpu_w=round(_mean(cpu), 3),
        avg_combined_w=round(avg_combined, 3),
        energy_j=round(avg_combined * duration_s, 3),
    )


class PowerSampler:
    """Context manager that samples power for the duration of a run.

    Usage:
        with PowerSampler(enabled=True) as sampler:
            ...run work...
        summary = sampler.result()
    """

    def __init__(self, *, enabled: bool, interval_s: float = 1.0) -> None:
        self._enabled = enabled and powermetrics_available()
        self._interval_s = interval_s
        self._proc: subprocess.Popen[str] | None = None
        self._start: float | None = None
        self._result = PowerSummary.unavailable()

    def __enter__(self) -> PowerSampler:
        if not self._enabled:
            return self
        try:
            self._proc = subprocess.Popen(
                powermetrics_command(self._interval_s),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            self._start = time.monotonic()
        except Exception:
            self._proc = None
        return self

    def __exit__(self, *_exc: object) -> bool:
        if self._proc is None or self._start is None:
            return False
        duration = time.monotonic() - self._start
        out = ""
        try:
            self._proc.terminate()
            out, _ = self._proc.communicate(timeout=5)
        except Exception:
            try:
                self._proc.kill()
                out, _ = self._proc.communicate(timeout=5)
            except Exception:
                out = ""
        self._result = summarize_powermetrics(out or "", duration)
        return False

    def result(self) -> PowerSummary:
        return self._result
