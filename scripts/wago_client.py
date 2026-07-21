"""Fetch and cache DB2 table dumps from wago.tools (community WoW datamining site).

wago.tools exposes each game-data table as CSV at:

    https://wago.tools/db2/{table}/csv?build={build}

and the current live/PTR build list at https://wago.tools/api/builds (or
/api/builds/latest). No auth is required. Verified against the live site in
2026-07; if these routes 404, the site's route names have likely changed and
this module needs a re-check against https://wago.tools/db2 (its Inertia.js
"data-page" attribute embeds the route list under props.ziggy.routes).

Results are cached on disk per (table, build) since a full table can be
several MB and rarely changes within a build.
"""

import csv
import json
import urllib.request
from pathlib import Path

BASE_URL = "https://wago.tools"
CACHE_DIR = Path(__file__).parent / ".wago_cache"

# wago.tools 403s the default urllib User-Agent; a browser-like one works fine.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; simcbots-importer/1.0)"}


def _get(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return resp.read()


def latest_build() -> str:
    data = json.loads(_get(f"{BASE_URL}/api/builds/latest", timeout=30))
    # Keyed by product ("wow" = live realm, "wowt" = PTR); prefer live.
    for product in ("wow", "wowt"):
        if product in data:
            return data[product]["version"]
    raise RuntimeError(f"unexpected /api/builds/latest response shape: {data!r}")


def fetch_table(table: str, build: str, cache_dir: Path = CACHE_DIR) -> list[dict]:
    """Return a table's rows as a list of dicts (CSV header -> value), fetching once per build."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{table}.{build}.csv"

    if not cache_path.exists():
        url = f"{BASE_URL}/db2/{table}/csv?build={build}"
        body = _get(url, timeout=60)
        if body.startswith(b'{"errors"'):
            raise RuntimeError(f"wago.tools rejected table {table!r}: {body.decode()}")
        cache_path.write_bytes(body)

    with cache_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
