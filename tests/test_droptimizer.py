from pathlib import Path

from app.droptimizer import (
    armor_type_for_class,
    build_input,
    detect_class,
    eligible_items,
    load_catalog,
    load_meta,
    resolve_bonus_ids,
    save_meta,
    summarize,
)

CATALOG_PATH = Path(__file__).parent / "fixtures" / "sample_droptimizer_catalog.json"
EXPORT = (Path(__file__).parent / "fixtures" / "sample_export.simc").read_text()


def test_load_catalog_reads_given_path():
    catalog = load_catalog(CATALOG_PATH)
    assert catalog["season"] == "Test Season"
    assert len(catalog["items"]) == 4


def test_detect_class_from_export():
    assert detect_class(EXPORT) == "warrior"


def test_detect_class_returns_none_when_absent():
    assert detect_class("level=80\nrace=orc\n") is None


def test_armor_type_for_class():
    assert armor_type_for_class("warrior") == "plate"
    assert armor_type_for_class("mage") == "cloth"
    assert armor_type_for_class(None) is None
    assert armor_type_for_class("not_a_class") is None


def test_eligible_items_filters_by_armor_type_and_class():
    catalog = load_catalog(CATALOG_PATH)
    items = eligible_items(catalog, "warrior")
    names = {item["name"] for item in items}

    # plate chest (matches), accessories (no armor restriction), warrior-only
    # trinket all included; cloth robe excluded.
    assert "Test Plate Chest" in names
    assert "Test Signet Ring" in names
    assert "Test Warrior Trinket" in names
    assert "Test Cloth Robe" not in names


def test_eligible_items_excludes_class_restricted_item_for_other_class():
    catalog = load_catalog(CATALOG_PATH)
    items = eligible_items(catalog, "mage")
    names = {item["name"] for item in items}

    assert "Test Cloth Robe" in names
    assert "Test Warrior Trinket" not in names
    assert "Test Plate Chest" not in names


def test_eligible_items_includes_everything_when_class_unknown():
    catalog = load_catalog(CATALOG_PATH)
    assert len(eligible_items(catalog, None)) == len(catalog["items"])


def test_resolve_bonus_ids_base_vs_max_and_voidcore():
    source = {"bonus_ids_base": [510], "bonus_ids_max": [516], "bonus_ids_voidcore_max": [522]}
    assert resolve_bonus_ids(source, use_max_upgrade=False, voidcore=False) == [510]
    assert resolve_bonus_ids(source, use_max_upgrade=True, voidcore=False) == [516]
    assert resolve_bonus_ids(source, use_max_upgrade=True, voidcore=True) == [522]
    # voidcore has no effect without use_max_upgrade -- it only extends the ceiling.
    assert resolve_bonus_ids(source, use_max_upgrade=False, voidcore=True) == [510]


def test_resolve_bonus_ids_voidcore_falls_back_to_max_when_absent():
    source = {"bonus_ids_base": [510], "bonus_ids_max": [516]}
    assert resolve_bonus_ids(source, use_max_upgrade=True, voidcore=True) == [516]


def test_build_input_appends_profilesets_for_every_source():
    catalog = load_catalog(CATALOG_PATH)
    items = eligible_items(catalog, "warrior")  # chest(2 sources, single slot) = 2
    combined, meta = build_input(EXPORT, items)  # ring(1 source) + trinket(1 source), paired = 4

    assert combined.startswith(EXPORT)
    ps_lines = [line for line in combined.splitlines() if line.startswith("profileset.")]
    assert len(ps_lines) == 6
    assert len(meta) == 6


def test_build_input_ring_gets_both_finger_variants():
    catalog = load_catalog(CATALOG_PATH)
    items = [item for item in catalog["items"] if item["name"] == "Test Signet Ring"]
    _, meta = build_input(EXPORT, items)

    variants = {info["slot"] for info in meta.values()}
    assert variants == {"finger1", "finger2"}


def test_build_input_uses_max_upgrade_bonus_ids_by_default():
    catalog = load_catalog(CATALOG_PATH)
    items = [item for item in catalog["items"] if item["name"] == "Test Plate Chest"]
    combined, meta = build_input(EXPORT, items)

    assert "bonus_id=516" in combined  # heroic source's bonus_ids_max
    assert "id=800001" in combined


def test_build_input_respects_use_max_upgrade_false():
    catalog = load_catalog(CATALOG_PATH)
    items = [item for item in catalog["items"] if item["name"] == "Test Plate Chest"]
    combined, _ = build_input(EXPORT, items, use_max_upgrade=False)

    assert "bonus_id=510" in combined
    assert "bonus_id=516" not in combined


def test_build_input_voidcore_swaps_in_extended_ceiling():
    catalog = load_catalog(CATALOG_PATH)
    items = [item for item in catalog["items"] if item["name"] == "Test Plate Chest"]
    combined, _ = build_input(EXPORT, items, use_max_upgrade=True, voidcore=True)

    assert "bonus_id=522" in combined
    assert "bonus_id=516" not in combined


def test_build_input_filters_by_category():
    catalog = load_catalog(CATALOG_PATH)
    items = eligible_items(catalog, "warrior")
    _, meta = build_input(EXPORT, items, categories=["delve"])

    # the delve trinket is a paired slot -> two profilesets, one category.
    assert len(meta) == 2
    assert {info["category"] for info in meta.values()} == {"delve"}


def test_meta_roundtrip(tmp_path):
    save_meta(tmp_path, {"DT0_0_chest": {"name": "X"}})
    assert load_meta(tmp_path)["DT0_0_chest"]["name"] == "X"


def test_summarize_picks_best_variant_and_ranks():
    def info(item_index, source_index, name, slot, category, label):
        return {
            "item_index": item_index,
            "source_index": source_index,
            "name": name,
            "slot": slot,
            "category": category,
            "label": label,
        }

    meta = {
        "DT0_0_finger1": info(0, 0, "Ring", "finger1", "world_boss", "WB"),
        "DT0_0_finger2": info(0, 0, "Ring", "finger2", "world_boss", "WB"),
        "DT1_0_chest": info(1, 0, "Chest", "chest", "raid", "Boss"),
    }
    results = {
        "player_name": "Vexatra",
        "baseline_dps": 100000.0,
        "profilesets": [
            {"name": "DT0_0_finger1", "mean": 99000.0},
            {"name": "DT0_0_finger2", "mean": 101000.0},
            {"name": "DT1_0_chest", "mean": 103000.0},
        ],
    }

    summary = summarize(results, meta)

    assert [r["name"] for r in summary["rows"]] == ["Chest", "Ring"]
    ring = summary["rows"][1]
    assert ring["slot"] == "Ring 2"
    assert ring["delta"] == 1000.0
    assert summary["categories"] == ["raid", "world_boss"]


def test_summarize_ignores_unknown_profilesets():
    results = {
        "player_name": "X",
        "baseline_dps": 1000.0,
        "profilesets": [{"name": "stray", "mean": 1100.0}],
    }
    summary = summarize(results, {})
    assert summary["rows"] == []
    assert summary["categories"] == []
