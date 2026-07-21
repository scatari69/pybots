# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

simcbots is a locally-hosted alternative to Raidbots: a small FastAPI app that wraps a local
SimulationCraft (`simc`) install behind a web UI. Users paste a simc profile/APL, the app shells
out to `simc`, and serves back the generated HTML report — no data leaves the machine.

## Commands

Local development (requires `simc` on `PATH`, or set `SIMC_BINARY` to its path):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload          # dev server at http://localhost:8000
```

Tests:

```bash
pytest                                  # full suite
pytest tests/test_simc_runner.py        # single file
pytest tests/test_api.py::test_simulate_then_poll_until_done  # single test
```

Lint:

```bash
ruff check .
```

Docker (uses the official `simulationcraftorg/simc` nightly build — no local `simc` install needed):

```bash
docker compose up --build               # http://localhost:8000
```

## Architecture

**Job model — no queue, in-memory state.** `JobStore` (`app/jobs.py`) is a plain in-memory
`dict[str, Job]` guarded by an `asyncio.Lock`. There is no Redis/Celery/RQ — each simulation is
fired off as a bare `asyncio.create_task` from the request handler in `app/main.py`. This is a
deliberate simplicity trade-off for a single-user, locally-hosted tool: job state (and any
in-flight sim) is lost on process restart. Background tasks are kept in a module-level
`_background_tasks` set in `main.py` solely to prevent asyncio from garbage-collecting them
mid-run — `asyncio` only holds a weak reference to tasks otherwise.

**Request flow:**
1. `POST /api/simulate` creates a `Job`, schedules `run_simulation()` (`app/simc_runner.py`) as a
   background task, and returns immediately with `{job_id, status: "queued"}`.
2. The frontend (`app/static/app.js`) polls `GET /api/simulate/{job_id}` every second. While the
   sim runs, the response carries `progress` (percent) and `elapsed` (seconds); progress is scraped
   on each GET from the tail of `log.txt` by `read_progress()` — simc rewrites its progress line
   with `\r` (`Generating Baseline: 1/1 [===>...] 59484/100000 ...`), and all those rewrites land
   in the redirected log, so the last `N/M` or `X%` match in the tail is current.
3. `run_simulation()` writes the submitted profile to `data/jobs/<job_id>/input.simc`, then runs
   simc via `asyncio.create_subprocess_exec` with args from `build_args()`. Sim options placed
   after the input file on the CLI override anything the profile set — this is how the UI toggles
   work: `desired_targets=N`, `max_time=S`, `optimal_raid=0` (raid buffs off),
   `override.bloodlust=0`, and `flask=disabled food=disabled potion=disabled ...` (consumables
   off; `disabled` is simc's magic value for these). Exit code 0 → `JobStatus.DONE`; nonzero →
   `JobStatus.ERROR` with the tail of the log captured as `job.error`.
4. `POST /api/simulate/{job_id}/cancel` sets `JobStatus.CANCELLED` *before* calling
   `job.process.terminate()` — `run_simulation()` re-checks the status after the process exits and
   skips the error path for cancelled jobs, so ordering matters.
5. Once done, the frontend redirects to `GET /report/{job_id}` — a Jinja2-rendered summary page
   (DPS, damage breakdown, buff uptimes) built by `app/report_parser.py` from simc's
   `json2=results.json` output. It links to the raw simc report at
   `/reports/<job_id>/report.html`, a `StaticFiles` mount pointed directly at the jobs directory.
   The parser only reads the first player: simcbots targets single-character quick sims.

**Top Gear (`app/gear_parser.py` + `app/topgear.py`).** The `/simc` addon export embeds
non-equipped gear as `#`-commented blocks under `### Gear from Bags` and
`### Weekly Reward Choices` sections (format verified against the addon source: separator `#`,
optional `# Name (ilvl)` line, optional `# upgrade_levels=...` line, then the commented item
string). `gear_parser.parse_candidates()` extracts those; `topgear.build_input()` appends one
simc *profileset* per candidate slot-variant to the otherwise-unmodified export (simc ignores the
comments, so the pasted text is the base profile as-is). Rings/trinkets get two profilesets — one
per slot position — and the report shows only the better variant. Profileset names are synthetic
(`TG<index>_<slot>`) to avoid quoting issues; `topgear.json` in the job dir maps them back to
display names. One simc invocation runs all profilesets against a shared baseline
(`sim.profilesets.results` in the JSON; baseline is `sim.players[0]`), which is what makes Top
Gear a single combined run. Flow: `POST /api/topgear/preview` parses candidates for the selection
UI → `POST /api/topgear` runs (job `kind="topgear"` selects the ranked-list template in
`/report/{job_id}`).

**Droptimizer (`app/droptimizer.py` + `app/data/droptimizer_catalog.json`).** Sims every item that
can drop this season — raid per difficulty, M+ dungeons per key-level bracket + vault, world
bosses, delves — against one baseline, in one combined run. Same profileset mechanism as Top Gear
(`DT<item_index>_<source_index>_<slot>` names, rings/trinkets get both slot positions, best variant
kept per `(item_index, source_index)`), but the candidate list comes from a data catalog instead of
parsing the player's own export, since "everything that can drop" isn't present in a `/simc` export
at all. Each catalog item lists `armor_type`/`classes` restrictions and one or more `sources`
(`category`, display `label`, `ilevel_base`, `ilevel_max`, optional `voidcore_bonus`).
`detect_class()` reads the class token off the export's `class="Name"` line (e.g. `warrior=`) and
`eligible_items()` filters the catalog to what that class can equip — if the class can't be
detected, filtering is skipped rather than silently dropping every candidate. `build_input()`
resolves each source's simc item level via the `ilevel=` item-string option (no bonus_id
arithmetic needed): `ilevel_max` unless `use_max_upgrade=False` picks `ilevel_base`, plus
`voidcore_bonus` when `voidcore=True`. `categories` narrows a run to specific source types instead
of always simming the whole catalog. Flow mirrors Top Gear: `POST /api/droptimizer/preview` returns
the detected class and a per-category item count for the UI's category checkboxes → `POST
/api/droptimizer` runs (job `kind="droptimizer"`, meta persisted to `droptimizer.json`) → the
ranked report (`droptimizer.html`) adds client-side filter chips (by `category`) that the roadmap's
"per-source filters" call for, on top of Top Gear's ranked bar-table layout.
**The shipped catalog is placeholder data** (see its `_readme` field) to exercise the engine
end-to-end — source labels/categories/ilvls are made up, not this season's real loot tables, but
the item ids are deliberately real ones reused from `tests/fixtures/sample_export.simc` rather than
invented, so the catalog is actually simulatable as shipped: simc segfaults on some malformed item
ids instead of failing that one profileset cleanly, which would otherwise take down the whole
combined run. Swap in real current-tier data by editing the JSON; the engine code doesn't need to
change. Known gaps: no weapon-type (dagger/sword/etc.) eligibility filtering, only armor-type/class;
and no weapon-slot (`main_hand`/`off_hand`) example is shipped at all — verified against the simc
nightly this app currently pulls, an `id=...,ilevel=...` profileset override on a weapon segfaults
simc even reusing the exact item/bonus_id the baseline profile already equips, so any weapon-slot
catalog entries should be tested against your own simc build before trusting them.

**Why the binary comes from Docker Hub, not compiled here.** The `Dockerfile` copies the compiled
`simc` binary and bundled `profiles/` out of `simulationcraftorg/simc:latest` in a multi-stage
build rather than compiling SimulationCraft from source. That upstream image is Alpine-based, so
the app stage is pinned to `python:3.12-alpine` to keep the same musl libc the binary was linked
against — swapping to a glibc base (e.g. `python:3.12-slim`) would break the binary. `SIMC_BINARY`
env var controls which executable `app/simc_runner.py` invokes, defaulting to `simc` on `PATH` for
non-Docker local dev.

**Testing the subprocess layer without a real simc install.** `tests/fixtures/fake_simc.py` is a
minimal stand-in binary: it reads the input profile file and fails if the text contains the
literal string `FAIL`, otherwise writes a stub `report.html`. `test_simc_runner.py` points
`run_simulation`'s `binary=` param at this fixture directly, so the runner's process-handling logic
(exit code → status, log capture, report file placement) is exercised without needing
SimulationCraft installed in the test environment. `test_api.py` instead monkeypatches
`main.run_simulation` wholesale, since those tests care about the HTTP/job-polling contract, not
subprocess behavior.
