from __future__ import annotations

from local_code_bench.power import (
    PowerSampler,
    PowerSummary,
    powermetrics_command,
    summarize_powermetrics,
)

# Two sampling intervals of `powermetrics --samplers cpu_power,gpu_power`.
_SAMPLE = """
*** Sampled system activity ***
**** GPU usage ****
GPU Power: 17000 mW

**** Processor usage ****
CPU Power: 4000 mW
ANE Power: 0 mW
Combined Power (CPU + GPU + ANE): 21000 mW

*** Sampled system activity ***
**** GPU usage ****
GPU Power: 15000 mW

**** Processor usage ****
CPU Power: 3000 mW
Combined Power (CPU + GPU + ANE): 18000 mW
"""


def test_summarize_powermetrics_aggregates_watts_and_energy() -> None:
    summary = summarize_powermetrics(_SAMPLE, duration_s=10.0)

    assert summary.available is True
    assert summary.samples == 2
    assert summary.avg_gpu_w == 16.0
    assert summary.max_gpu_w == 17.0
    assert summary.avg_cpu_w == 3.5
    assert summary.avg_combined_w == 19.5
    # energy = avg combined power * duration
    assert summary.energy_j == 195.0


def test_summarize_powermetrics_falls_back_to_cpu_plus_gpu() -> None:
    text = "GPU Power: 10000 mW\nCPU Power: 5000 mW\n"
    summary = summarize_powermetrics(text, duration_s=2.0)

    assert summary.samples == 1
    assert summary.avg_combined_w == 15.0
    assert summary.energy_j == 30.0


def test_summarize_powermetrics_empty_is_unavailable() -> None:
    summary = summarize_powermetrics("no power lines here", duration_s=5.0)

    assert summary.available is False
    assert summary.samples == 0


def test_power_summary_as_record_is_tagged() -> None:
    record = PowerSummary.unavailable().as_record()

    assert record["record_type"] == "power"
    assert record["available"] is False


def test_powermetrics_command_uses_non_interactive_sudo() -> None:
    command = powermetrics_command(1.0)

    assert command[:3] == ["sudo", "-n", "powermetrics"]
    assert "1000" in command  # interval in milliseconds


def test_power_sampler_disabled_is_noop() -> None:
    with PowerSampler(enabled=False) as sampler:
        pass

    assert sampler.result().available is False
