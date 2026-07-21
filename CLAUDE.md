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
can drop this season against one baseline, in one combined run. Same profileset mechanism as Top
Gear (`DT<item_index>_<source_index>_<slot>` names, rings/trinkets get both slot positions, best
variant kept per `(item_index, source_index)`), but the candidate list comes from a data catalog
instead of parsing the player's own export, since "everything that can drop" isn't present in a
`/simc` export at all. Each catalog item lists `armor_type`/`classes` restrictions and one or more
`sources` (`category`, display `label`, `bonus_ids_base`, `bonus_ids_max`, optional
`bonus_ids_voidcore`). `detect_class()` reads the class token off the export's `class="Name"` line
(e.g. `warrior=`) and `eligible_items()` filters the catalog to what that class can equip — if the
class can't be detected, filtering is skipped rather than silently dropping every candidate.
`categories` narrows a run to specific source types instead of always simming the whole catalog.
Flow mirrors Top Gear: `POST /api/droptimizer/preview` returns the detected class and a
per-category item count for the UI's category checkboxes → `POST /api/droptimizer` runs (job
`kind="droptimizer"`, meta persisted to `droptimizer.json`) → the ranked report
(`droptimizer.html`) adds client-side filter chips (by `category`) on top of Top Gear's ranked
bar-table layout.

**Item level is resolved via real `bonus_id`s, not an `ilevel=` override.** An early version set
`ilevel=` directly on profileset items; that segfaults this project's simc nightly on weapon items
even with the item's own real bonus_id alongside it (reproduced with a hand-built minimal profile,
not just the catalog). Every source instead carries the actual `bonus_id` combination Blizzard's
client would apply for that difficulty/rank — the same mechanism a real `/simc` export uses — so
simc resolves stats/ilvl itself. `resolve_bonus_ids()` picks `bonus_ids_max` (assume full
crest/catalyst upgrade) unless `use_max_upgrade=False`, plus `bonus_ids_voidcore` when
`voidcore=True` (currently always empty — no mechanic by that name was found anywhere in the
~186-entry `Enum.ItemCreationContext` list or any DB2 table researched; needs clarification of what
it refers to before it can be populated). **Weapon slots (`main_hand`/`off_hand`) are excluded from
the catalog entirely** — the segfault reproduces regardless of override mechanism, so it's a simc
bug in this specific nightly build, not something fixable app-side; revisit once upstream fixes it.

**`scripts/build_droptimizer_catalog.py` generates the real catalog from wago.tools DB2 data**
(`scripts/wago_client.py` fetches+caches CSV tables from `https://wago.tools/db2/{table}/csv`, no
auth needed but a browser-like `User-Agent` header — the default `urllib` one gets a 403). The
join chain, reverse-engineered and validated against one known-real example (item 249277 in
`tests/fixtures/sample_export.simc`, real `bonus_id=12806/13335`, exactly reproduced):
`ItemXBonusTree` (item → its bonus tree) → `ItemBonusTreeNode`, walked recursively, keeping any
node whose `ItemContext` is `0` (unconditional) or matches the target context (`Enum.
ItemCreationContext`: `RaidLFR=4/RaidNormal=3/RaidHeroic=5/RaidMythic=6`) — a node yields a bonus_id
directly (`ChildItemBonusListID`), or via an upgrade-track group (`ChildItemBonusListGroupID` →
`ItemBonusListGroupEntry` rows sorted by `SequenceValue`; first = base/undropped rank, last = fully
upgraded), or recurses into a nested subtree (`ChildItemBonusTreeID`). **This is validated for
raid difficulties only.** The same walk was tried against Mythic+ dungeons and is not just
imprecise there but wrong: no item in any Season 1 dungeon's loot pool has a tree node with a real
`MinMythicPlusLevel`/`MaxMythicPlusLevel` range, meaning key-level ilvl scaling isn't reachable
this way at all — whatever mechanism actually drives it (likely `ContentTuning`/`ItemLevelSelector`
resolved server-side) wasn't found. `build_dungeon_items()` exists in the script but main() doesn't
call it; picking this up means finding that mechanism first, not just cleaning up the existing code.
Season scope (4 raids: The Dreamrift, March on Quel'Danas, Sporefall, The Voidspire) is hardcoded
as constants at the top of the script — update those each season along with `--build`. Great
Vault, world bosses, and delves aren't covered yet either. A handful of item names carry mangled
special characters (e.g. "Gaze of the All-Seer" → "Gaze of the Alnseer") — an upstream issue in
wago.tools' own CSV export of `ItemSparse`, reproduces outside this script; spot-check anything
that looks garbled. `armor_type` is not populated from real data (always `null` in the generated
catalog) — `classes` (from `ItemSparse.AllowableClass`) does the real eligibility filtering instead.

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
