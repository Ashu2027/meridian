"""
services/tone_engine.py
Tone split validation, persistence (history-preserving), and weighted assignment.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional, Tuple

from db.connection import Database

TONES = ("professional", "semi_casual", "casual")


@dataclass
class ToneSplit:
    id: int
    professional: int
    semi_casual: int
    casual: int
    is_active: bool
    note: Optional[str]


# ── Validation ─────────────────────────────────────────────────────────────────

def validate_split(
    professional: int,
    semi_casual: int,
    casual: int,
) -> Tuple[bool, str]:
    """
    Returns (True, "") when valid.
    Returns (False, human-readable reason) when not.
    """
    for name, val in [("professional", professional), ("semi_casual", semi_casual), ("casual", casual)]:
        if not (0 <= val <= 100):
            return False, f"Each value must be 0–100 (got {name}={val})."
    total = professional + semi_casual + casual
    if total != 100:
        diff = 100 - total
        direction = f"add {diff}%" if diff > 0 else f"remove {abs(diff)}%"
        return False, f"Total is {total}% — {direction} somewhere."
    return True, ""


# ── Persistence ────────────────────────────────────────────────────────────────

def get_active_split(db: Database) -> ToneSplit:
    """Fetch the currently active tone_settings row."""
    row = db.fetch_one(
        "SELECT * FROM tone_settings WHERE is_active = TRUE ORDER BY id DESC LIMIT 1"
    )
    if not row:
        # Fallback: seed default
        save_split(db, 60, 30, 10, "auto-seeded default")
        row = db.fetch_one(
            "SELECT * FROM tone_settings WHERE is_active = TRUE ORDER BY id DESC LIMIT 1"
        )
    return ToneSplit(
        id=row["id"],
        professional=row["professional_percent"],
        semi_casual=row["semi_casual_percent"],
        casual=row["casual_percent"],
        is_active=row["is_active"],
        note=row.get("updated_by_note"),
    )


def save_split(
    db: Database,
    professional: int,
    semi_casual: int,
    casual: int,
    note: Optional[str] = None,
) -> ToneSplit:
    """
    Deactivate the previous active row, insert a new one.
    Never UPDATE in place — preserves the full change history.
    """
    ok, reason = validate_split(professional, semi_casual, casual)
    if not ok:
        raise ValueError(reason)

    db.execute("UPDATE tone_settings SET is_active = FALSE WHERE is_active = TRUE")
    new_id = db.execute(
        """
        INSERT INTO tone_settings
            (professional_percent, semi_casual_percent, casual_percent, is_active, updated_by_note)
        VALUES (%s, %s, %s, TRUE, %s)
        """,
        (professional, semi_casual, casual, note),
    )
    return ToneSplit(
        id=new_id,
        professional=professional,
        semi_casual=semi_casual,
        casual=casual,
        is_active=True,
        note=note,
    )


def get_all_splits(db: Database) -> list[ToneSplit]:
    """Return full tone split history, newest first."""
    rows = db.fetch_all("SELECT * FROM tone_settings ORDER BY id DESC")
    return [
        ToneSplit(
            id=r["id"],
            professional=r["professional_percent"],
            semi_casual=r["semi_casual_percent"],
            casual=r["casual_percent"],
            is_active=r["is_active"],
            note=r.get("updated_by_note"),
        )
        for r in rows
    ]


# ── Tone assignment ────────────────────────────────────────────────────────────

def assign_tone(
    preferred_tone: str,
    split: ToneSplit,
    rng: Optional[random.Random] = None,
) -> str:
    """
    Assign a tone for one recipient.
    - If preferred_tone != 'auto': return that tone directly.
    - Otherwise: weighted-random pick using split percentages.
    Tone is assigned once at drafting time and never re-rolled on regenerate.
    """
    if preferred_tone in ("professional", "semi_casual", "casual"):
        return preferred_tone

    _rng = rng or random.Random()
    roll = _rng.uniform(0, 100)

    if roll < split.professional:
        return "professional"
    elif roll < split.professional + split.semi_casual:
        return "semi_casual"
    else:
        return "casual"
