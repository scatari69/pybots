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
`bonus_ids_voidcore_max`). `detect_class()` reads the class token off the export's `class="Name"` line
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
simc resolves stats/ilvl itself. `resolve_bonus_ids()` picks `bonus_ids_max` (assume full crest
upgrade) unless `use_max_upgrade=False`, and swaps in `bonus_ids_voidcore_max` instead when
`voidcore=True` and the source has one. **Weapon slots (`main_hand`/`off_hand`) are excluded from
the catalog entirely** — the segfault reproduces regardless of override mechanism, so it's a simc
bug in this specific nightly build, not something fixable app-side; revisit once upstream fixes it.

**"Voidcore" is the Ascendant Voidcore / Voidforge system** (patch 12.0.5): a currency that pushes
an already fully-upgraded Hero/Myth-track weapon or trinket beyond its normal crest ceiling (armor
is excluded from the mechanic entirely). It isn't a separate branch in the bonus tree — a trinket
and a weapon from the same source turned out to share the *exact same* tree structure, so it had to
be hiding inside the upgrade-track groups already being walked. It was found there: every
raid-difficulty group (`609`/`610`/`611`/`612` = LFR/Normal/Heroic/Mythic) has a run of ranks with a
real crest cost (`Flags == 2`) followed by a tail of `Flags == 3`, zero-cost ranks — rank 6 of 9 is
the crest ceiling (this is the rank that produced the validated example's real bonus_id, 12806) and
ranks 7-9 are the Voidcore-gated extension. `_group_rank_bonus_id()` in the build script picks
between `"base"`/`"crest_max"`/`"voidcore_max"` using this `Flags` discontinuity, and
`build_raid_items()` only emits `bonus_ids_voidcore_max` for Heroic/Mythic sources, matching the
documented "Hero or Myth track" restriction — even though the raw data technically carries the same
tail for LFR/Normal too, using it there would contradict the documented scope.

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
upgraded), or recurses into a nested subtree (`ChildItemBonusTreeID`).

**Mythic+ dungeons resolve through the same walk**, using `ItemContext` `16` (`ChallengeMode_1`,
legacy Timewalking Challenge Mode terminology reused here — end-of-run reward) and `35`
(`ChallengeModeJackpot` — a second, higher-floor channel; "pick your best key of the week" fits the
Great Vault). A first attempt at this checked `DungeonMythic` (23) instead, which only ever yields
a flat non-scaling flag, and separately had an off-by-one treating a node's `MaxMythicPlusLevel ==
0` as "cap at 0" rather than "no cap" — between the two bugs, every open-ended "N and up" bracket
under the wrong context looked like it didn't exist. Both were found by comparing a *new* Season 1
dungeon's tree (Windrunner Spire) against the raid tree shape rather than a returning one — which
turned out to matter: `discover_mplus_brackets()` finds real key-level brackets (e.g. "0-5"/"6 and
up") pointing at the *same* upgrade-track groups (`609`-`612`) raid difficulties use for the 4 new
Season 1 dungeons, but **the 4 returning dungeons' items (Skyreach, Seat of the Triumvirate,
Algeth'ar Academy, Pit of Saron) have zero such brackets in their trees at all** — whatever
mechanism scales their M+ rewards, it isn't carried on the item the way it is for new dungeons, and
wasn't found in this pass. `build_dungeon_items()` covers the 4 new dungeons only; the 4 returning
ones are a distinct, still-open gap, not just an oversight.

Season scope (4 raids: The Dreamrift, March on Quel'Danas, Sporefall, The Voidspire; 8 dungeons) is
hardcoded as constants at the top of the script — update those each season along with `--build`.
Great Vault raid rewards, world bosses, and delves aren't covered yet. A handful of item names
carry mangled special characters (e.g. "Gaze of the All-Seer" → "Gaze of the Alnseer") — an
upstream issue in wago.tools' own CSV export of `ItemSparse`, reproduces outside this script;
spot-check anything that looks garbled. `armor_type` is not populated from real data (always
`null` in the generated catalog) — `classes` (from `ItemSparse.AllowableClass`) does the real
eligibility filtering instead.

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
