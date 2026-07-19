from pathlib import Path

from app.gear_parser import parse_candidates

EXPORT = (Path(__file__).parent / "fixtures" / "sample_export.simc").read_text()


def test_finds_all_bag_and_vault_items():
    candidates = parse_candidates(EXPORT)

    assert len(candidates) == 5
    assert [c.source for c in candidates] == ["bags", "bags", "bags", "vault", "vault"]


def test_names_and_ilevels_come_from_comment_lines():
    candidates = parse_candidates(EXPORT)
    by_name = {c.name: c for c in candidates}

    assert by_name["Voidclaw Gauntlets"].ilevel == 676
    assert by_name["Voidclaw Gauntlets"].slot == "hands"
    assert by_name["Gaze of the All-Seer"].source == "vault"


def test_upgrade_levels_comment_is_not_mistaken_for_a_name():
    candidates = parse_candidates(EXPORT)
    ring = next(c for c in candidates if c.slot == "finger1")

    assert ring.name == "Platinum Star Band"
    assert ring.item_string.startswith("finger1=,id=215135,")


def test_equipped_gear_and_character_info_are_not_candidates():
    candidates = parse_candidates(EXPORT)

    # Equipped head item id must not appear among candidates.
    assert not any("id=249952" in c.item_string for c in candidates)
    # catalyst/upgrade currency comments are not items.
    assert not any("catalyst" in c.item_string for c in candidates)


def test_indices_are_sequential():
    candidates = parse_candidates(EXPORT)
    assert [c.index for c in candidates] == [0, 1, 2, 3, 4]


def test_export_without_sections_yields_nothing():
    assert parse_candidates("warrior=Foo\nlevel=80\nhead=,id=123\n") == []
