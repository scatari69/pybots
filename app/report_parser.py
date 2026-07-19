import json
from pathlib import Path


def _display_name(stat: dict) -> str:
    return stat.get("spell_name") or stat["name"].replace("_", " ").title()


def _abilities(player: dict) -> list[dict]:
    damage_stats = [s for s in player["stats"] if s.get("type") == "damage"]
    total = sum(s.get("compound_amount", 0.0) for s in damage_stats)

    abilities = [
        {
            "name": _display_name(stat),
            "amount": stat.get("compound_amount", 0.0),
            "percent": (stat.get("compound_amount", 0.0) / total * 100) if total else 0.0,
            "count": stat.get("num_executes", {}).get("mean", 0.0),
        }
        for stat in damage_stats
        if stat.get("compound_amount", 0.0) > 0
    ]
    abilities.sort(key=lambda a: a["amount"], reverse=True)
    return abilities


def _buffs(player: dict) -> list[dict]:
    buffs = [
        {
            "name": buff.get("spell_name") or buff["name"].replace("_", " ").title(),
            "uptime": buff["uptime"],
            "count": buff.get("start_count", 0.0),
        }
        for buff in player.get("buffs", []) + player.get("buffs_constant", [])
        if buff.get("uptime") is not None
    ]
    buffs.sort(key=lambda b: b["uptime"], reverse=True)
    return buffs


def parse_profilesets(results_path: Path) -> dict:
    """Extract baseline dps + profileset results for a Top Gear run."""
    data = json.loads(results_path.read_text())
    sim = data["sim"]
    player = sim["players"][0]

    return {
        "player_name": player["name"],
        "baseline_dps": player["collected_data"]["dps"]["mean"],
        "profilesets": sim.get("profilesets", {}).get("results", []),
    }


def parse_report(results_path: Path) -> dict:
    """Extract the fields needed for the summary page out of simc's json2 report.

    Only looks at the first player -- simcbots targets single-character "quick
    sims" like Raidbots' Quick Sim, not full raid compositions.
    """
    data = json.loads(results_path.read_text())
    sim = data["sim"]
    options = sim["options"]
    player = sim["players"][0]
    dps = player["collected_data"]["dps"]

    return {
        "player_name": player["name"],
        "specialization": player.get("specialization", ""),
        "race": player.get("race", ""),
        "dps_mean": dps["mean"],
        "dps_error": dps.get("mean_std_dev", 0.0),
        "iterations": options.get("iterations"),
        "fight_style": options.get("fight_style"),
        "fight_length": player["collected_data"]["fight_length"]["mean"],
        "abilities": _abilities(player),
        "buffs": _buffs(player),
    }
