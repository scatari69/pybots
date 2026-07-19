"""Build a Top Gear profileset run and summarize its results.

Each candidate item becomes one or more simc profilesets appended to the pasted
profile — one per slot the item could occupy (rings and trinkets get both
positions, everything else keeps its exported slot). simc runs all profilesets
in a single invocation against a shared baseline, which is what makes Top Gear
"one combined run" instead of N separate sims.
"""

import json
from pathlib import Path

from app.gear_parser import Candidate

META_FILENAME = "topgear.json"

_PAIRED_SLOTS = {
    "finger1": ["finger1", "finger2"],
    "finger2": ["finger1", "finger2"],
    "trinket1": ["trinket1", "trinket2"],
    "trinket2": ["trinket1", "trinket2"],
}

SLOT_LABELS = {
    "finger1": "Ring 1",
    "finger2": "Ring 2",
    "trinket1": "Trinket 1",
    "trinket2": "Trinket 2",
    "main_hand": "Main Hand",
    "off_hand": "Off Hand",
}


def _variants(slot: str) -> list[str]:
    return _PAIRED_SLOTS.get(slot, [slot])


def build_input(export_text: str, candidates: list[Candidate]) -> tuple[str, dict]:
    """Return (combined simc input, profileset meta).

    The pasted export is used verbatim as the base profile — simc ignores the
    commented bag/vault sections — with profileset lines appended after it.
    Profileset names are synthetic (TG<index>_<slot>) to sidestep quoting issues
    with item names; the meta maps them back for display.
    """
    lines = [export_text, ""]
    meta: dict[str, dict] = {}

    for candidate in candidates:
        item_options = candidate.item_string.split("=", 1)[1]
        for slot in _variants(candidate.slot):
            ps_name = f"TG{candidate.index}_{slot}"
            lines.append(f'profileset."{ps_name}"+={slot}={item_options}')
            meta[ps_name] = {
                "index": candidate.index,
                "name": candidate.name,
                "slot": slot,
                "source": candidate.source,
                "ilevel": candidate.ilevel,
            }

    return "\n".join(lines) + "\n", meta


def save_meta(job_dir: Path, meta: dict) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / META_FILENAME).write_text(json.dumps(meta))


def load_meta(job_dir: Path) -> dict:
    return json.loads((job_dir / META_FILENAME).read_text())


def summarize(results: dict, meta: dict) -> dict:
    """Join simc profileset results with candidate meta into ranked rows.

    Rings/trinkets produce two profilesets per item; only the better variant is
    shown, labeled with the slot it would replace.
    """
    baseline = results["baseline_dps"]

    best_by_item: dict[int, dict] = {}
    for ps_result in results["profilesets"]:
        info = meta.get(ps_result["name"])
        if info is None:
            continue
        row = {
            "name": info["name"],
            "slot": SLOT_LABELS.get(info["slot"], info["slot"].replace("_", " ").title()),
            "source": info["source"],
            "ilevel": info["ilevel"],
            "dps": ps_result["mean"],
            "error": ps_result.get("mean_error", 0.0),
            "delta": ps_result["mean"] - baseline,
        }
        current_best = best_by_item.get(info["index"])
        if current_best is None or row["dps"] > current_best["dps"]:
            best_by_item[info["index"]] = row

    rows = sorted(best_by_item.values(), key=lambda r: r["dps"], reverse=True)

    # Bar widths are scaled across the visible dps range so small deltas stay
    # readable; the baseline is included in the range so its marker fits too.
    all_dps = [r["dps"] for r in rows] + [baseline]
    low, high = min(all_dps), max(all_dps)
    span = (high - low) or 1.0
    for row in rows:
        row["bar_pct"] = max(2.0, (row["dps"] - low) / span * 100)
        row["delta_pct"] = row["delta"] / baseline * 100

    return {
        "baseline_dps": baseline,
        "baseline_bar_pct": max(2.0, (baseline - low) / span * 100),
        "player_name": results["player_name"],
        "rows": rows,
    }
