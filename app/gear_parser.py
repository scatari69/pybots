"""Parse the /simc addon export for gear candidates.

The addon appends non-equipped gear as commented blocks:

    ### Gear from Bags
    #
    # Voidclaw Gauntlets (676)
    # upgrade_levels=5:6:...          <- optional
    # hands=,id=237522,bonus_id=...

    ### Weekly Reward Choices
    #
    # Gaze of the All-Seer (691)
    # trinket1=,id=242395,...
    #
    ### End of Weekly Reward Choices

Each item is: a `#` separator, an optional `# Name (ilvl)` comment, an optional
`# upgrade_levels=...` comment, then the commented item string itself. Bag items
always use the first slot of a pair (finger1/trinket1) regardless of where they
would be equipped.
"""

import re
from dataclasses import dataclass

SLOTS = {
    "head", "neck", "shoulder", "shoulders", "back", "chest", "wrist", "wrists",
    "hands", "waist", "legs", "feet", "finger1", "finger2", "trinket1", "trinket2",
    "main_hand", "off_hand",
}

_ITEM_LINE_RE = re.compile(r"^#\s*([a-z_0-9]+)=(.*)$")
_NAME_RE = re.compile(r"^(.*?)\s*\((\d+)\)$")

BAGS_HEADER = "### Gear from Bags"
VAULT_HEADER = "### Weekly Reward Choices"
VAULT_FOOTER = "### End of Weekly Reward Choices"


@dataclass
class Candidate:
    index: int
    slot: str
    item_string: str  # full "slot=,id=..." form as exported
    name: str
    ilevel: int | None
    source: str  # "bags" | "vault"


def parse_candidates(export_text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    source: str | None = None
    pending_name: str | None = None
    pending_ilevel: int | None = None

    for raw_line in export_text.splitlines():
        line = raw_line.strip()

        if line.startswith("###"):
            if line == BAGS_HEADER:
                source = "bags"
            elif line == VAULT_HEADER:
                source = "vault"
            else:  # any other section (incl. vault footer) ends candidate parsing
                source = None
            pending_name = pending_ilevel = None
            continue

        if source is None:
            continue

        if line == "#" or not line:
            pending_name = pending_ilevel = None
            continue

        item_match = _ITEM_LINE_RE.match(line)
        if item_match and item_match.group(1) in SLOTS:
            slot = item_match.group(1)
            candidates.append(
                Candidate(
                    index=len(candidates),
                    slot=slot,
                    item_string=f"{slot}={item_match.group(2)}",
                    name=pending_name or f"{slot} item",
                    ilevel=pending_ilevel,
                    source=source,
                )
            )
            pending_name = pending_ilevel = None
        elif line.startswith("#"):
            comment = line.lstrip("#").strip()
            if comment and not comment.startswith("upgrade_levels="):
                name_match = _NAME_RE.match(comment)
                if name_match:
                    pending_name = name_match.group(1)
                    pending_ilevel = int(name_match.group(2))
                else:
                    pending_name = comment
                    pending_ilevel = None

    return candidates
