# Epic 9: Unified Dashboard

## Epic Overview
**Epic ID**: Epic-09
**Description**: Bring the three benchmark surfaces — inferencer control (Epic-08), results exploration (Epic-07), and the CLI benchmark runner — together into one localhost web dashboard. From a single page FX can manage local inference engines, browse benchmark results, and launch a new benchmark, where a benchmark is composed as **model + inferencer + a chosen set of test suites** (HumanEval, canary, MBPP, the EvalPlus variants, and config-registered custom suites). Epic-09 does not reinvent the results or inferencer surfaces — it composes Epic-07's live results endpoints and Epic-08's inferencer control panel under one shell and adds the genuinely new pieces: the benchmark launcher and live run monitoring, with the one-active mutual-exclusion invariant enforced for every launched run.
**Business Value**: Today a benchmark run is a multi-step manual ritual — edit `models.yaml`, remember which inferencer the model needs, start exactly that server with nothing else running, invoke the right CLI command, then hand-read JSONL or regenerate tables to see how it went. Each step is a place to get it wrong and silently invalidate a run (a stray server skews timing; the wrong suite scores the wrong thing). A single "pick a model, pick an inferencer, pick suites, go — then watch it and read the results" surface turns that ritual into one guided flow, with timing integrity guaranteed by reusing Epic-08's exclusive start rather than FX's memory.
**Success Metrics**: From one `bench dashboard` command FX can, in one browser tab, see which engines are installed/running/healthy and control them, compose and launch a benchmark by choosing a model, an inferencer, and one or more available suites, watch that run's live progress (passed/failed/remaining, speed, cost), and see the completed run appear in the results views — without editing config by hand, without manually juggling servers, and with exactly one inference server ever active during a run.

## Epic Scope
**Total Stories**: 6 | **Total Points**: 24 | **MVP Stories**: 0 (Should Have / v1.x)

## Decisions Locked With FX
- **Deliverable for this pass**: epic + stories only (no code), consistent with how Epic-08 was authored.
- **Relation to existing epics**: a **new Epic-09** that depends on and composes Epic-07 (results) and Epic-08 (inferencers); both remain intact as building blocks. Epic-09 owns only the unifying shell, the benchmark launcher, run monitoring, the suite catalog, and cross-section cohesion/safety.
- **Carried-over timing rules** (from Epic-08): full lifecycle for headless servers, detect-only for GUI apps, and a hard one-active mutual-exclusion rule enforced through `start_exclusive` — every benchmark launched from the dashboard goes through it.

## Features in This Epic

### Feature 9.1: Unified Dashboard Shell

#### Stories

##### Story 09.1-001: Single-page unified dashboard with Inferencers / Results / Run sections
**User Story**: As FX, I want one localhost page with Inferencers, Results, and Run sections so that I can manage engines, read results, and launch benchmarks without juggling separate tools.
**Priority**: Should Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** the `bench dashboard` command **When** I run it **Then** a single stdlib HTTP server starts bound to `127.0.0.1`, prints its URL, and serves one page with navigable Inferencers, Results, and Run sections.
- **Given** the dashboard page **When** I switch between sections **Then** navigation works without a frontend build step and without reloading the whole app.
- **Given** the Inferencers section **When** it loads **Then** it reuses the Epic-08 inferencer control panel behavior, and the Results section reuses Epic-07's live results data — no duplicated business logic.
- **Given** any response from the unified server **When** rendered **Then** it contains no API keys, `.env` contents, or host-sensitive paths, and the server binds to localhost only.

**Technical Notes**: New `src/local_code_bench/dashboard/app.py` (or extend the Epic-08 `inferencers/dashboard.py` server) using the stdlib `http.server`, reusing Epic-08's `manager`/status JSON and Epic-07's results aggregates (07.1-001/07.3-001) rather than re-querying. Serve one self-contained page (inlined CSS/JS, no CDN). Expose via a single `bench dashboard [--port 8765]` entry that supersedes the per-epic `bench inferencer dashboard` once this lands. Keep section panels as thin clients over the existing JSON endpoints.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] Documentation updated

**Dependencies**: 07.3-001, 08.6-001
**Risk Level**: Medium

### Feature 9.2: Benchmark Launcher

#### Stories

##### Story 09.2-001: Compose a benchmark from model + inferencer + suites
**User Story**: As FX, I want to pick a model, an inferencer, and one or more test suites in the Run section so that I can launch a benchmark without editing config files by hand.
**Priority**: Should Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** the Run section **When** it loads **Then** the model selector is populated from `models.yaml`, the inferencer selector from `inferencers.yaml`, and the suite selector from the available-suites catalog (09.5-001).
- **Given** I select a model, an inferencer, and one or more suites **When** I review the composition **Then** the form validates the combo and warns when the chosen inferencer differs from the model's declared `inferencer`, before anything is launched.
- **Given** a valid composition **When** I submit it **Then** a launch request carrying the model, inferencer, and suite list is sent to the launch endpoint and I see the run accepted.
- **Given** an invalid or empty composition **When** I submit **Then** the form rejects it with an actionable message and launches nothing.

**Technical Notes**: Pure dashboard UI + a small read endpoint that returns the current model/inferencer/suite catalogs as JSON (reusing `load_models`, `load_inferencers`, and the suite catalog from 09.5-001). Validation mirrors the harness's existing config-validation tone. Multi-suite selection maps to running the chosen suites in sequence for the selected model. Keep the form a thin client; all authority lives in the launch endpoint (09.3-001).

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] Documentation updated

**Dependencies**: 09.1-001, 09.3-001, 09.5-001
**Risk Level**: Medium

##### Story 09.3-001: Launch orchestration endpoint
**User Story**: As FX, I want submitting a composition to exclusively start the right inferencer and run the chosen suites in the background so that launching a benchmark is one click instead of a manual sequence.
**Priority**: Should Have
**Story Points**: 5

**Acceptance Criteria**:
- **Given** a launch request **When** it is received **Then** the endpoint validates the model+inferencer+suite combo and rejects unknown or incompatible selections with a clear error.
- **Given** a valid request **When** the run starts **Then** the inferencer is started exclusively via Epic-08's `start_exclusive` (same confirmation contract) so exactly one inference server is active.
- **Given** the inferencer is up **When** the benchmark runs **Then** the chosen suites are executed in the background through the existing `run_endpoint_suite`, writing JSONL to `results/`, and the endpoint returns a run id.
- **Given** generated code from a run **When** it is scored **Then** it executes only in the existing sandbox.
- **Given** a run is already in flight **When** another launch is submitted **Then** it is serialized or rejected so the one-active-server invariant is never violated.

**Technical Notes**: New `POST /api/run` handler that composes existing pieces: `start_exclusive` (08.3-001) for the inferencer, then `run_endpoint_suite` (Epic-01 runner) per selected suite, writing to a fresh `results/<run>.jsonl` via `new_run_path`. Run the suite work on a background thread; track run state (id, status, counts) in memory plus the JSONL file as source of truth. Reject concurrent launches while one is active (single-run lock). No new scoring path — reuse the sandbox. Test by patching `start_exclusive` and `run_endpoint_suite` and asserting orchestration order, the single-run lock, and run-id return.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] Documentation updated

**Dependencies**: 08.3-001, 01.2-003 (runner + JSONL), 02.1-001 (suite loaders)
**Risk Level**: High

##### Story 09.4-001: Live run progress and auto-refreshed results
**User Story**: As FX, I want to watch a launched run's progress and have results refresh when it finishes so that I can follow a benchmark from launch to verdict in one place.
**Priority**: Should Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** a run launched from the dashboard **When** it is in flight **Then** I can see live progress: passed/failed/remaining counts, the current task, and speed/cost accumulated so far.
- **Given** a run reaches a terminal state **When** it completes **Then** the dashboard shows the terminal status and the Results section reflects the new JSONL through Epic-07's live aggregates without restarting the server.
- **Given** a run fails or is aborted **When** I view it **Then** a clear reason is surfaced rather than a silent stop.

**Technical Notes**: A `GET /api/run/<id>` (or `/api/runs`) status endpoint the page polls, fed by the in-memory run state from 09.3-001 and/or by tailing the run's JSONL. On completion, the Results section re-fetches Epic-07's live aggregates (07.3-001) pointed at the new file. Keep polling simple (interval refresh); no websockets needed. Test with a fake run-state source asserting progress, terminal, and failure rendering.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] Documentation updated

**Dependencies**: 09.3-001, 07.3-001
**Risk Level**: Medium

### Feature 9.3: Test-Suite Catalog

#### Stories

##### Story 09.5-001: Available-suites catalog and custom-suite registration
**User Story**: As FX, I want the launcher to list every available test suite — built-in and custom — so that I can benchmark against new suites without editing code.
**Priority**: Should Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** the built-in suites (humaneval, mbpp, canary, humaneval-plus, mbpp-plus) **When** the catalog is requested **Then** each is listed with its identity and task count where known.
- **Given** a config-registered custom suite **When** the catalog is requested **Then** the new suite appears in the launcher without any code change.
- **Given** a suite that is currently unavailable (e.g. a missing EvalPlus cache file) **When** the catalog is rendered **Then** it is shown disabled with the reason, rather than offered and failing at launch.

**Technical Notes**: A `suite_catalog()` helper that enumerates the existing `SuiteName` suites plus any entries from an optional `configs/suites.yaml` (id, loader hint, source path), reusing the Epic-02 `load_suite`/dataset-cache logic to compute availability and counts. Surface it as a JSON endpoint consumed by 09.2-001. Keep "custom suite" definition minimal — point at a loadable dataset; do not build a full plugin system. Test the catalog with built-ins present, a registered custom suite, and an unavailable (missing-cache) suite.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] Documentation updated

**Dependencies**: 02.1-001 (suite loaders), 09.2-001
**Risk Level**: Medium

### Feature 9.4: Cohesion & Safety

#### Stories

##### Story 09.6-001: Cross-section flow and localhost-only safety
**User Story**: As FX, I want the sections to flow into one another and the whole surface to stay safe-by-default so that launching, watching, and reviewing a run feels like one tool I can trust on my machine.
**Priority**: Should Have
**Story Points**: 3

**Acceptance Criteria**:
- **Given** I launch a benchmark **When** it starts **Then** the dashboard moves me from launch to live progress to the completed results, and the Inferencers section reflects which engine the run brought up.
- **Given** the unified server **When** it runs **Then** it binds to localhost only with no auth beyond that (documented as a single-user benchmark-box tool), and no endpoint leaks API keys, `.env` contents, or host paths.
- **Given** a GUI app inferencer **When** a launch or control action touches it **Then** it is never force-quit (Epic-08 warn-and-refuse rule holds), and all generated code runs only in the sandbox.

**Technical Notes**: Cross-link the sections (launch → `GET /api/run/<id>` → results pointed at the run's JSONL; Inferencers panel reads the same `status_all`). Centralize a response-sanitization pass so no secrets reach the browser. Re-assert the Epic-08 safety rules at the unified layer rather than re-implementing them. This story is the integration/security seam — its tests assert the launch→watch→results path end-to-end (with backend pieces faked) and that security ACs hold across endpoints.

**Definition of Done**:
- [ ] Code implemented and peer reviewed
- [ ] Tests written and passing
- [ ] Documentation updated

**Dependencies**: 09.1-001, 09.4-001
**Risk Level**: Medium

## Epic Progress
**Completed**: 0 / 6 stories · 0 / 24 points
