# simcbots

A locally-hosted alternative to Raidbots: a small web UI that wraps your own
SimulationCraft install so you can paste a profile/APL, run a sim, and view
the report — without sending anything to a third-party server.

## Quick start (Docker)

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
uvicorn app.main:app --reload
```

## Tests

```bash
pytest
```

## Lint

```bash
ruff check .
```
