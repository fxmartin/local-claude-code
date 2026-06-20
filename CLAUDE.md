# local-claude-code — Benchmarking local & cloud coding models for Claude Code

## Project Context

A CLI benchmark harness for driving and measuring agentic coding models. It runs
**local MLX-served models** on an Apple Silicon Mac against each other through
Claude Code, then against cloud models (GLM, Kimi K2, …) via **OpenRouter** — with
Claude Code itself as the baseline. The goal is to find the fastest, most capable
local coding setup and quantify the gap to the frontier. For FX's own
experimentation and (being public) reproducible by others.

## Tech Stack

- **Language**: Python (CPython, managed with `uv`)
- **Framework**: None — CLI-oriented
- **Runtime**: CPython 3.x via `uv`

## Architecture

A CLI harness that talks to any **OpenAI-compatible `/v1/chat/completions`
endpoint**, so the *same* code measures a local MLX server (e.g. `dflash serve`,
`turboquant-serve`, `mlx_lm.server`) and a remote provider (OpenRouter) by swapping
only the base URL and API key. Following the source articles' method, it measures
per-turn **time-to-first-token (prefill tok/s), decode tok/s, and total latency** —
because local agentic coding is **prefill-bound, not decode-bound**.

## Hardware (fixed benchmark machine)

- **MacBook Pro M3 Max, 48 GB** unified memory. The reference articles used an M4
  64 GB; 48 GB constrains which quantized models fit (target + draft + KV cache).

## Repository Structure

```
local-claude-code/
├── src/                  # harness package (runner, providers, metrics)
├── configs/              # model + provider definitions (local MLX, OpenRouter)
├── prompts/              # task-mode sub-prompts + sweep-mode preambles
├── results/              # raw benchmark output (gitignored)
├── articles/             # reference research (Medium series, PDFs)
├── tests/
├── CLAUDE.md
├── PROJECT-SEED.md
└── .gitignore
```

## Preferred CLI Tools

Use these instead of their traditional counterparts. They're installed and expected.

| Instead of | Use | Why |
|------------|-----|-----|
| `find` | `fd` | Faster, respects `.gitignore` |
| `grep` (via Bash) | `rg` | ripgrep — faster, better defaults |
| `cat` | `bat` | Syntax highlighting, line numbers |
| `cd` | `zoxide` (`z`) | Jump to frecent directories |
| `jq` for JSON | `jq` | Installed for JSON processing |

## GitHub Operations — Use `gh` CLI (NOT MCP)

Always use `gh` CLI for all GitHub operations (issues, PRs, releases, API calls).

## Key Docs

<!-- Populated after /brainstorm and /generate-epics -->
- `PROJECT-SEED.md` — Project seed data for downstream skills
- `articles/` — The two-part Medium series this project is modeled on (local Claude
  Code setup; MoE vs speculative decoding benchmark methodology)
