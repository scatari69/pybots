"""Sim every item that can drop this season against one baseline, in one run.

Unlike Top Gear (candidates come from the player's own /simc export), the
Droptimizer candidate list comes from a data-driven catalog of the current
season's loot -- raid bosses per difficulty, M+ dungeons per key-level
bracket (+ vault), world bosses, and delves. See app/data/droptimizer_catalog.json
for the schema and its "_readme" note: the shipped catalog is placeholder data
to exercise this module end-to-end, not real current-tier loot.

Mechanically this follows Top Gear's playbook: each (item, source) pair
becomes one or more simc profilesets (rings/trinkets get both slot
positions), appended to the pasted export and run in a single simc
invocation against a shared baseline. The only new piece is resolving each
source's item level from the catalog instead of trusting a bonus_id string,
via simc's "ilevel=" item option:

  - "use_max_upgrade" picks a source's ilevel_max (assume fully upgraded via
    crests/catalyst within that upgrade track) instead of ilevel_base (item
    as it drops, unupgraded).
  - "voidcore" adds a source's voidcore_bonus on top, where the source
    defines one.
  - "categories" restricts which source categories (raid/mythicplus/vault/
    world_boss/delve/...) are included, so a run can be scoped down instead
    of always simming the entire catalog.
"""

import json
import re
from pathlib import Path

from app.simc_slots import SLOT_LABELS, slot_variants

META_FILENAME = "droptimizer.json"

DEFAULT_CATALOG_PATH = Path(__file__).parent / "data" / "droptimizer_catalog.json"

# Armor proficiency by class -- fixed WoW class design, not seasonal content,
# so unlike the item catalog this doesn't need to be data-driven.
ARMOR_BY_CLASS = {
    "warrior": "plate",
    "paladin": "plate",
    "deathknight": "plate",
    "hunter": "mail",
    "shaman": "mail",
    "evoker": "mail",
    "rogue": "leather",
    "druid": "leather",
    "monk": "leather",
    "demonhunter": "leather",
    "mage": "cloth",
    "priest": "cloth",
    "warlock": "cloth",
}

# A simc export's class line looks like `warrior="Vexatra"` -- the token
# before "=" is the class.
_CLASS_LINE_RE = re.compile(r'^([a-z]+)="')


def load_catalog(path: Path | None = None) -> dict:
    return json.loads(Path(path or DEFAULT_CATALOG_PATH).read_text())


def detect_class(export_text: str) -> str | None:
    for raw_line in export_text.splitlines():
        match = _CLASS_LINE_RE.match(raw_line.strip())
        if match and match.group(1) in ARMOR_BY_CLASS:
            return match.group(1)
    return None


def armor_type_for_class(wow_class: str | None) -> str | None:
    return ARMOR_BY_CLASS.get(wow_class) if wow_class else None


def eligible_items(catalog: dict, wow_class: str | None) -> list[dict]:
    """Items usable by this class, by armor type and any explicit class list.

    If the class couldn't be detected from the export, filtering is skipped
    entirely (better to sim some irrelevant items than silently drop
    everything).
    """
    if wow_class is None:
        return list(catalog["items"])

    armor_type = armor_type_for_class(wow_class)
    items = []
    for item in catalog["items"]:
        item_armor = item.get("armor_type")
        if item_armor is not None and item_armor != armor_type:
            continue
        classes = item.get("classes")
        if classes is not None and wow_class not in classes:
            continue
        items.append(item)
    return items


def resolve_ilevel(source: dict, use_max_upgrade: bool, voidcore: bool) -> int:
    ilevel = source["ilevel_max"] if use_max_upgrade else source["ilevel_base"]
    if voidcore:
        ilevel += source.get("voidcore_bonus", 0)
    return ilevel


def build_input(
    export_text: str,
    items: list[dict],
    *,
    use_max_upgrade: bool = True,
    voidcore: bool = False,
    categories: list[str] | None = None,
) -> tuple[str, dict]:
    """Return (combined simc input, profileset meta) -- see module docstring.

    Profileset names are synthetic (DT<item_index>_<source_index>_<slot>) to
    sidestep quoting issues with item names; meta maps them back for display.
    """
    wanted_categories = set(categories) if categories is not None else None
    lines = [export_text, ""]
    meta: dict[str, dict] = {}

    for item_index, item in enumerate(items):
        for source_index, source in enumerate(item["sources"]):
            if wanted_categories is not None and source["category"] not in wanted_categories:
                continue

            ilevel = resolve_ilevel(source, use_max_upgrade, voidcore)
            item_options = f"id={item['id']},ilevel={ilevel}"

            for slot in slot_variants(item["slot"]):
                ps_name = f"DT{item_index}_{source_index}_{slot}"
                lines.append(f'profileset."{ps_name}"+={slot}={item_options}')
                meta[ps_name] = {
                    "item_index": item_index,
                    "source_index": source_index,
                    "name": item["name"],
                    "slot": slot,
                    "category": source["category"],
                    "label": source["label"],
                    "ilevel": ilevel,
                }

    return "\n".join(lines) + "\n", meta


def save_meta(job_dir: Path, meta: dict) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / META_FILENAME).write_text(json.dumps(meta))


def load_meta(job_dir: Path) -> dict:
    return json.loads((job_dir / META_FILENAME).read_text())


def summarize(results: dict, meta: dict) -> dict:
    """Join simc profileset results with catalog meta into ranked rows.

    Rings/trinkets produce one profileset per slot position; only the better
    variant is kept per (item, source) pair, same as Top Gear.
    """
    baseline = results["baseline_dps"]

    best_by_key: dict[tuple[int, int], dict] = {}
    for ps_result in results["profilesets"]:
        info = meta.get(ps_result["name"])
        if info is None:
            continue
        row = {
            "name": info["name"],
            "slot": SLOT_LABELS.get(info["slot"], info["slot"].replace("_", " ").title()),
            "category": info["category"],
            "label": info["label"],
            "ilevel": info["ilevel"],
            "dps": ps_result["mean"],
            "error": ps_result.get("mean_error", 0.0),
            "delta": ps_result["mean"] - baseline,
        }
        key = (info["item_index"], info["source_index"])
        current_best = best_by_key.get(key)
        if current_best is None or row["dps"] > current_best["dps"]:
            best_by_key[key] = row

    rows = sorted(best_by_key.values(), key=lambda r: r["dps"], reverse=True)

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
        "categories": sorted({row["category"] for row in rows}),
    }
