"""Slot-pairing helpers shared by Top Gear and Droptimizer.

Rings and trinkets can occupy either of two equipment slots; a candidate item
of either kind gets one profileset per slot position so the report can show
whichever position actually gains more DPS.
"""

PAIRED_SLOTS = {
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


def slot_variants(slot: str) -> list[str]:
    return PAIRED_SLOTS.get(slot, [slot])
