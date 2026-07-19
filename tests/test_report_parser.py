from pathlib import Path

from app.report_parser import parse_report

SAMPLE = Path(__file__).parent / "fixtures" / "sample_results.json"


def test_parse_report_extracts_header_fields():
    summary = parse_report(SAMPLE)

    assert summary["player_name"] == "Test"
    assert summary["specialization"] == "Fury Warrior"
    assert summary["dps_mean"] == 3698.26
    assert summary["fight_style"] == "Patchwerk"
    assert summary["iterations"] == 65


def test_parse_report_abilities_sorted_by_amount_and_zero_filtered():
    summary = parse_report(SAMPLE)
    names = [a["name"] for a in summary["abilities"]]

    # "flask" has compound_amount 0.0 and must be dropped.
    assert "Flask of Alchemical Chaos" not in names
    # Sorted descending by amount: auto attack mh > oh > charge.
    assert names == ["Auto Attack Mh", "Auto Attack Oh", "Charge"]


def test_parse_report_ability_percent_sums_close_to_100():
    summary = parse_report(SAMPLE)
    total_percent = sum(a["percent"] for a in summary["abilities"])
    assert abs(total_percent - 100) < 0.01


def test_parse_report_buffs_include_constant_and_variable():
    summary = parse_report(SAMPLE)
    names = {b["name"] for b in summary["buffs"]}

    assert "Blood Fury" in names
    assert "Battle Shout" in names
    # Sorted descending by uptime.
    assert summary["buffs"][0]["name"] == "Battle Shout"
