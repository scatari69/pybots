from pathlib import Path

from app.gear_parser import parse_candidates
from app.topgear import build_input, load_meta, save_meta, summarize

EXPORT = (Path(__file__).parent / "fixtures" / "sample_export.simc").read_text()


def test_build_input_appends_profilesets_after_export():
    candidates = parse_candidates(EXPORT)
    combined, meta = build_input(EXPORT, candidates)

    assert combined.startswith(EXPORT)
    # 3 single-slot items -> 1 profileset each is wrong: hands x2 are single-slot,
    # ring and trinket get 2 variants each: 2*1 + 1*2 + 1*2 + 1*1 = 7
    ps_lines = [line for line in combined.splitlines() if line.startswith("profileset.")]
    assert len(ps_lines) == 7
    assert len(meta) == 7


def test_build_input_ring_gets_both_finger_variants():
    candidates = parse_candidates(EXPORT)
    combined, meta = build_input(EXPORT, candidates)
    ring_index = next(c.index for c in candidates if c.slot == "finger1")

    variants = {info["slot"] for info in meta.values() if info["index"] == ring_index}
    assert variants == {"finger1", "finger2"}
    assert f'profileset."TG{ring_index}_finger2"+=finger2=,id=215135,' in combined


def test_build_input_single_slot_keeps_exported_slot():
    candidates = parse_candidates(EXPORT)
    _, meta = build_input(EXPORT, candidates)
    hands = [info for info in meta.values() if info["slot"] == "hands"]

    assert len(hands) == 2  # two bag gloves, one variant each


def test_meta_roundtrip(tmp_path):
    save_meta(tmp_path, {"TG0_hands": {"index": 0, "name": "X", "slot": "hands"}})
    assert load_meta(tmp_path)["TG0_hands"]["name"] == "X"


def test_summarize_picks_best_variant_and_ranks():
    def info(index, name, slot, source, ilevel):
        return {"index": index, "name": name, "slot": slot, "source": source, "ilevel": ilevel}

    meta = {
        "TG0_finger1": info(0, "Ring", "finger1", "bags", 676),
        "TG0_finger2": info(0, "Ring", "finger2", "bags", 676),
        "TG1_hands": info(1, "Gloves", "hands", "vault", 691),
    }
    results = {
        "player_name": "Vexatra",
        "baseline_dps": 100000.0,
        "profilesets": [
            {"name": "TG0_finger1", "mean": 99000.0, "mean_error": 50.0},
            {"name": "TG0_finger2", "mean": 101000.0, "mean_error": 50.0},
            {"name": "TG1_hands", "mean": 103000.0, "mean_error": 60.0},
        ],
    }

    summary = summarize(results, meta)

    assert summary["baseline_dps"] == 100000.0
    assert [r["name"] for r in summary["rows"]] == ["Gloves", "Ring"]
    ring = summary["rows"][1]
    assert ring["slot"] == "Ring 2"  # best variant won
    assert ring["delta"] == 1000.0
    assert round(ring["delta_pct"], 2) == 1.0


def test_summarize_ignores_unknown_profilesets():
    results = {
        "player_name": "X",
        "baseline_dps": 1000.0,
        "profilesets": [{"name": "stray", "mean": 1100.0}],
    }
    assert summarize(results, {})["rows"] == []
