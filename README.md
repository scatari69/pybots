# simcbots

A locally-hosted alternative to [Raidbots](https://www.raidbots.com/): a small
FastAPI web UI that wraps your own [SimulationCraft](https://www.simulationcraft.org/)
install. Paste a simc profile/APL, run a sim, and view the report — **nothing
leaves your machine**.

## Features

- **Quick Sim** — paste a profile, run it, and get a rendered summary (DPS, damage
  breakdown, buff uptimes) plus a link to simc's full HTML report. Live progress and
  elapsed time while it runs, with a cancel button.
- **Top Gear** — paste a `/simc` addon export and the app sims every unequipped piece
  from your bags and weekly reward choices in one combined run, then ranks them by DPS
  gain over your current gear.
- **Droptimizer** — sims *everything that can drop this season* (raids + dungeons)
  against your baseline in a single run, ranked by upgrade value. Detects your class
  from the export and filters the catalog to gear you can actually equip. Narrow a run
  to specific source categories from the UI.

All three run as a single simc invocation and never send your data anywhere.

## Quick start (Docker)

The recommended way — no local `simc` install needed. The image copies the compiled
binary from the official `simulationcraftorg/simc` nightly.

```bash
docker compose up --build
```

Then open http://localhost:8000, paste a simc profile, and submit.

## Local development (without Docker)

Requires a `simc` binary on your `PATH` (or set `SIMC_BINARY` to its path).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload          # dev server at http://localhost:8000
```

## How it works

- **No queue, in-memory state.** Each sim is fired off as an `asyncio` background task;
  job state lives in a plain in-memory dict. Simple by design for a single-user, local
  tool — job state is lost on process restart.
- The frontend polls for status once a second, scraping progress from the tail of
  simc's log while it runs, then redirects to a Jinja2-rendered report parsed from
  simc's JSON output.
- Top Gear and Droptimizer both work by appending one simc **profileset** per gear
  candidate to a shared baseline, so a whole ranked list comes out of one run.
- Item level is resolved via real Blizzard `bonus_id`s (the same mechanism a real
  `/simc` export uses), not an `ilevel=` override.

See [`CLAUDE.md`](CLAUDE.md) for the full architecture write-up.

## Building the Droptimizer catalog

The Droptimizer catalog (`app/data/droptimizer_catalog.json`) is generated from
[wago.tools](https://wago.tools/) DB2 data. Season scope (raids/dungeons) is hardcoded
as constants at the top of the build script — update those each season.

```bash
python scripts/build_droptimizer_catalog.py --build
```

## Tests

```bash
pytest                                  # full suite
pytest tests/test_simc_runner.py        # single file
```

The subprocess layer is tested against a fake `simc` stand-in, so no real
SimulationCraft install is needed to run the suite.

## Lint

```bash
ruff check .
```
