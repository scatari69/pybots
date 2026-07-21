"""Build app/data/droptimizer_catalog.json from real Wago DB2 data.

Scope (Season 1 only, per project decision -- update the constants below each
new season): the 4 currently-available raids (The Dreamrift, March on
Quel'Danas, Sporefall, The Voidspire) and the 8 Season 1 Mythic+ dungeons
(4 new + 4 returning). Great Vault, world bosses and delves are not covered
yet -- out of scope for this pass.

How item level actually gets resolved (see CLAUDE.md "Droptimizer" section
for the full writeup): rather than computing a numeric ilvl ourselves --
which requires resolving a Blizzard curve system we could not fully validate
without a live client -- this importer resolves the *bonus_id combination*
Blizzard's own client would apply for a given difficulty/rank, via:

    ItemXBonusTree (item -> its bonus tree)
      -> ItemBonusTreeNode, recursively walked, node.ItemContext == 0 (always)
         or == the target context (RaidLFR=4/RaidNormal=3/RaidHeroic=5/
         RaidMythic=6, DungeonHeroic=2/DungeonMythic=23)
           -> ChildItemBonusListID: a bonus_id directly (leaf)
           -> ChildItemBonusListGroupID: an upgrade-track group; look up
              ItemBonusListGroupEntry rows for that group, sorted by
              SequenceValue -- first entry is the "as it drops" rank, last is
              the fully-upgraded rank
           -> ChildItemBonusTreeID: recurse into a nested subtree

This was validated against the one real example available (item 249277 in
tests/fixtures/sample_export.simc, whose real bonus_id is "12806/13335"):
this exact walk reproduces both numbers -- 13335 from the difficulty-context
branch (context 6 = RaidMythic) and 12806 from the upgrade-track branch
(group 612, rank 6 of 9). Passing simc a real bonus_id combination instead of
an "ilevel=" override also sidesteps the segfault found earlier when
overriding a weapon's item level directly (see droptimizer_catalog.json's
_readme and CLAUDE.md).

"Voidcore" is the Ascendant Voidcore / Voidforge system (patch 12.0.5): a
currency that pushes an already fully-upgraded Hero/Myth-track weapon or
trinket beyond its normal ceiling. It turned out to be visible in the same
upgrade-track groups used above: every raid-difficulty group (609/610/611/
612) has a run of ranks with a real crest cost (Flags == 2) followed by a
tail of Flags == 3, zero-cost ranks -- rank 6 of 9 is the crest ceiling
(matching item 249277's real, live bonus_id 12806) and ranks 7-9 are the
Voidcore-gated extension. See _group_rank_bonus_id(). The extension is only
emitted for Heroic/Mythic sources (bonus_ids_voidcore_max), matching the
documented "Hero or Myth track" restriction, even though the raw data
technically carries the same Flags==3 tail for LFR/Normal too.

Mythic+ dungeon loot is NOT included: the same walk was tried against all 8
Season 1 dungeons and is demonstrably broken there rather than merely
imprecise. It resolved 229 "valid" items for Skyreach alone (vs. 19-58 for
every other dungeon and 8-58 for every raid) -- a check for any tree node
with a real MinMythicPlusLevel/MaxMythicPlusLevel range across every item in
that pool came back with zero matches, meaning key-level ilvl scaling isn't
reachable through an item's own bonus tree the way raid difficulty is.
Whatever mechanism actually drives Mythic+ reward scaling in this build
(likely something ContentTuning/ItemLevelSelector-based, resolved
server-side rather than baked into static per-item tree data) was not found
during this research. Left for a follow-up rather than shipping wrong data.

A handful of item names may render with mangled special characters (e.g.
"Gaze of the All-Seer" came back as "Gaze of the Alnseer") -- this reproduces
in wago.tools' own CSV export of ItemSparse, not in this script's parsing;
spot-check any name that looks garbled against Wowhead/in-game.

Armor-type restriction is not populated (always null) -- that requires the
Item/ItemSubClass tables, not fetched in this pass; class restriction (from
ItemSparse.AllowableClass) is populated and does the bulk of the filtering
work in practice.

Usage:
    python scripts/build_droptimizer_catalog.py [--build BUILD] [--out PATH]
"""

import argparse
import json
from pathlib import Path

from wago_client import fetch_table, latest_build

# --- Season 1 scope -- update these each season. ---------------------------

RAID_INSTANCES = {
    1314: "The Dreamrift",
    1308: "March on Quel'Danas",
    1305: "Sporefall",
    1307: "The Voidspire",
}

DUNGEON_INSTANCES = {
    476: "Skyreach",
    945: "Seat of the Triumvirate",
    1201: "Algeth'ar Academy",
    278: "Pit of Saron",
    1299: "Windrunner Spire",
    1300: "Magisters' Terrace",
    1316: "Nexus-Point Xenas",
    1315: "Maisara Caverns",
}

# Enum.ItemCreationContext values relevant here (see CLAUDE.md / warcraft.wiki.gg).
RAID_CONTEXTS = {
    "LFR": 4,
    "Normal": 3,
    "Heroic": 5,
    "Mythic": 6,
}
DUNGEON_CONTEXTS = {
    "Heroic": 2,
    "Mythic": 23,  # Mythic+ (key-level scaling handled via Min/MaxMythicPlusLevel)
}
MPLUS_KEY_LEVEL_SAMPLES = [2, 7, 10]  # representative brackets, not exhaustive

INVENTORY_TYPE_TO_SLOT = {
    1: "head",
    2: "neck",
    3: "shoulder",
    5: "chest",
    20: "chest",
    6: "waist",
    7: "legs",
    8: "feet",
    9: "wrist",
    10: "hands",
    11: "finger1",
    12: "trinket1",
    16: "back",
    # Weapon slots (13/14/17/21/22/23 = one-hand/shield/two-hand/main-hand/
    # off-hand/held-in-off-hand) are deliberately excluded: a profileset
    # "ilevel="/"bonus_id=" override on a weapon segfaults the simc nightly
    # this app currently pulls, reproduced with both mechanisms (see
    # CLAUDE.md). Revisit once that's fixed upstream.
}

# Standard class bitmask order (bit 0 = Warrior); stable since Classic.
CLASS_BITS = [
    "warrior", "paladin", "hunter", "rogue", "priest", "deathknight",
    "shaman", "mage", "warlock", "monk", "druid", "demonhunter", "evoker",
]


def classes_from_mask(mask: int) -> list[str] | None:
    if mask == -1:
        return None
    classes = [name for i, name in enumerate(CLASS_BITS) if mask & (1 << i)]
    return classes or None


class BonusTreeResolver:
    """Recursively resolves an item's bonus tree for a target context (+ optional key level)."""

    def __init__(self, item_x_bonus_tree, bonus_tree_nodes, group_entries):
        self.tree_by_item = {int(r["ItemID"]): int(r["ItemBonusTreeID"]) for r in item_x_bonus_tree}

        self.nodes_by_parent: dict[int, list[dict]] = {}
        for row in bonus_tree_nodes:
            self.nodes_by_parent.setdefault(int(row["ParentItemBonusTreeID"]), []).append(row)

        # (SequenceValue, ItemBonusListID, Flags) per group, sorted by rank.
        self.group_entries: dict[int, list[tuple[int, int, int]]] = {}
        for row in group_entries:
            group_id = int(row["ItemBonusListGroupID"])
            self.group_entries.setdefault(group_id, []).append(
                (int(row["SequenceValue"]), int(row["ItemBonusListID"]), int(row["Flags"]))
            )
        for entries in self.group_entries.values():
            entries.sort()

    def resolve(
        self, item_id: int, context: int, rank: str, key_level: int | None = None
    ) -> list[int]:
        """rank: "base" (as-dropped), "crest_max" (normal upgrade-track ceiling),
        or "voidcore_max" (extended ceiling beyond crest_max -- see
        _group_rank_bonus_id for how that extension is identified).
        """
        tree_id = self.tree_by_item.get(item_id)
        if tree_id is None:
            return []
        return sorted(set(self._walk(tree_id, context, rank, key_level, set())))

    @staticmethod
    def _group_rank_bonus_id(entries: list[tuple[int, int, int]], rank: str) -> int:
        """Pick a rank's bonus_id from a group's (SequenceValue, ID, Flags) ladder.

        Every ladder inspected (across all 4 raid-difficulty upgrade groups)
        has the same shape: an initial run of ranks with a real crest cost
        (Flags == 2) followed by a tail of Flags == 3, zero-cost ranks -- the
        latter matches the "Ascendant Voidcore" currency-gated extension
        beyond the normal upgrade-track ceiling (see CLAUDE.md). crest_max is
        the last Flags != 3 rank; voidcore_max is the very last rank,
        whatever tier it's in.
        """
        if rank == "base":
            return entries[0][1]
        if rank == "voidcore_max":
            return entries[-1][1]
        # crest_max: last rank that isn't in the voidcore-only tail.
        crest_entries = [e for e in entries if e[2] != 3]
        return (crest_entries or entries)[-1][1]

    def _walk(self, tree_id, context, rank, key_level, seen) -> list[int]:
        if tree_id in seen:
            return []
        seen.add(tree_id)

        ids: list[int] = []
        for node in self.nodes_by_parent.get(tree_id, []):
            node_context = int(node["ItemContext"])
            if node_context not in (0, context):
                continue

            if key_level is not None:
                lo, hi = int(node["MinMythicPlusLevel"]), int(node["MaxMythicPlusLevel"])
                if (lo or hi) and not (lo <= key_level <= hi):
                    continue

            child_tree = int(node["ChildItemBonusTreeID"])
            if child_tree:
                ids += self._walk(child_tree, context, rank, key_level, seen)

            child_bonus = int(node["ChildItemBonusListID"])
            if child_bonus:
                ids.append(child_bonus)

            child_group = int(node["ChildItemBonusListGroupID"])
            if child_group:
                entries = self.group_entries.get(child_group)
                if entries:
                    ids.append(self._group_rank_bonus_id(entries, rank))

        return ids


def load_item_sparse(rows) -> dict[int, dict]:
    items = {}
    for row in rows:
        inv_type = int(row["InventoryType"])
        slot = INVENTORY_TYPE_TO_SLOT.get(inv_type)
        if slot is None:
            continue
        items[int(row["ID"])] = {
            "name": row["Display_lang"],
            "slot": slot,
            "base_ilevel": int(row["ItemLevel"]),
            "classes": classes_from_mask(int(row["AllowableClass"])),
        }
    return items


def build_raid_items(encounter_items, item_index, resolver, boss_names) -> list[dict]:
    catalog_items: dict[int, dict] = {}
    for row in encounter_items:
        item_id = int(row["ItemID"])
        info = item_index.get(item_id)
        if info is None:
            continue
        boss_name = boss_names.get(int(row["JournalEncounterID"]))
        if boss_name is None:
            continue

        sources = []
        for label, context in RAID_CONTEXTS.items():
            base = resolver.resolve(item_id, context, "base")
            crest_max = resolver.resolve(item_id, context, "crest_max")
            if not base and not crest_max:
                continue
            source = {
                "category": "raid",
                "label": f"{boss_name} ({label})",
                "difficulty": label,
                "bonus_ids_base": base,
                "bonus_ids_max": crest_max or base,
            }
            # Ascendant Voidcore only extends fully-upgraded Hero/Myth-track
            # gear (see CLAUDE.md) -- restrict the extended tier to Heroic/
            # Mythic even though the raw data technically carries it for
            # LFR/Normal too, since that contradicts the documented scope.
            if label in ("Heroic", "Mythic"):
                voidcore_max = resolver.resolve(item_id, context, "voidcore_max")
                if voidcore_max and voidcore_max != source["bonus_ids_max"]:
                    source["bonus_ids_voidcore_max"] = voidcore_max
            sources.append(source)
        if not sources:
            continue

        entry = catalog_items.setdefault(item_id, {
            "id": item_id,
            "name": info["name"],
            "slot": info["slot"],
            "armor_type": None,
            "classes": info["classes"],
            "sources": [],
        })
        entry["sources"].extend(sources)

    return list(catalog_items.values())


def build_dungeon_items(
    encounter_items, item_index, resolver, boss_names, dungeon_name
) -> list[dict]:
    catalog_items: dict[int, dict] = {}
    for row in encounter_items:
        item_id = int(row["ItemID"])
        info = item_index.get(item_id)
        if info is None:
            continue
        boss_name = boss_names.get(int(row["JournalEncounterID"]))
        if boss_name is None:
            continue

        sources = []
        for key_level in MPLUS_KEY_LEVEL_SAMPLES:
            context = DUNGEON_CONTEXTS["Mythic"]
            base = resolver.resolve(item_id, context, "base", key_level=key_level)
            maxed = resolver.resolve(item_id, context, "max", key_level=key_level)
            if not base and not maxed:
                continue
            sources.append({
                "category": "mythicplus",
                "label": f"{dungeon_name} — {boss_name} (+{key_level})",
                "difficulty": f"Mythic+{key_level}",
                "bonus_ids_base": base,
                "bonus_ids_max": maxed or base,
            })
        if not sources:
            continue

        entry = catalog_items.setdefault(item_id, {
            "id": item_id,
            "name": info["name"],
            "slot": info["slot"],
            "armor_type": None,
            "classes": info["classes"],
            "sources": [],
        })
        entry["sources"].extend(sources)

    return list(catalog_items.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", default=None, help="wago.tools build, defaults to latest live")
    parser.add_argument(
        "--out",
        default=Path(__file__).parent.parent / "app" / "data" / "droptimizer_catalog.json",
        type=Path,
    )
    args = parser.parse_args()
    build = args.build or latest_build()
    print(f"Using build {build}")

    journal_encounter = fetch_table("JournalEncounter", build)
    journal_encounter_item = fetch_table("JournalEncounterItem", build)
    item_sparse = fetch_table("ItemSparse", build)
    item_x_bonus_tree = fetch_table("ItemXBonusTree", build)
    bonus_tree_nodes = fetch_table("ItemBonusTreeNode", build)
    group_entries = fetch_table("ItemBonusListGroupEntry", build)

    item_index = load_item_sparse(item_sparse)
    resolver = BonusTreeResolver(item_x_bonus_tree, bonus_tree_nodes, group_entries)

    boss_names_all = {int(r["ID"]): r["Name_lang"] for r in journal_encounter}

    items: list[dict] = []

    for instance_id, instance_name in RAID_INSTANCES.items():
        encounter_ids = {
            int(r["ID"]) for r in journal_encounter if int(r["JournalInstanceID"]) == instance_id
        }
        rows = [r for r in journal_encounter_item if int(r["JournalEncounterID"]) in encounter_ids]
        raid_items = build_raid_items(rows, item_index, resolver, boss_names_all)
        print(f"{instance_name}: {len(raid_items)} item(s)")
        items.extend(raid_items)

    # Mythic+ dungeon loot is intentionally NOT imported yet -- build_dungeon_items()
    # is kept below for whoever picks this up next, but see the module docstring:
    # key-level ilvl scaling isn't reachable through this item-tree walk, and calling
    # it produced demonstrably wrong data (229 "valid" items for Skyreach alone).
    print("Skipping Mythic+ dungeons: key-level scaling resolver is broken, see docstring.")

    catalog = {
        "_readme": (
            "Real data imported via scripts/build_droptimizer_catalog.py from wago.tools "
            f"(build {build}), scoped to Season 1 raids: The Dreamrift, March on Quel'Danas, "
            "Sporefall, The Voidspire. Mythic+ dungeons, Great Vault, world bosses and delves "
            "are not covered yet (see the script's docstring for why dungeons specifically were "
            "dropped after producing wrong data). Each source's bonus_ids_base/bonus_ids_max are "
            "resolved from real ItemBonusTree data, validated against a known example (item "
            "249277 in tests/fixtures/sample_export.simc, bonus_id=12806/13335 reproduced "
            "exactly). armor_type is not populated (always null) -- classes (from "
            "ItemSparse.AllowableClass) does the eligibility filtering instead. Heroic/Mythic "
            "sources carry bonus_ids_voidcore_max, the Ascendant Voidcore-gated tier beyond the "
            "normal crest ceiling (bonus_ids_max) -- see the script's docstring for how that was "
            "identified. A handful of item names may have mangled special characters "
            "(upstream wago.tools CSV export issue, e.g. 'Gaze of the All-Seer' came back as "
            "'Gaze of the Alnseer') -- spot-check anything that looks garbled."
        ),
        "season": "Season 1",
        "items": items,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(items)} item(s) to {args.out}")


if __name__ == "__main__":
    main()
