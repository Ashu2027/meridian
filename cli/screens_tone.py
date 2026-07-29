"""
cli/screens_tone.py
Tone split configuration screen with live validation and visual progress bars.
"""
from __future__ import annotations

import questionary
from rich import box
from rich.panel import Panel
from rich.text import Text

from cli.formatting import console, header_panel, tone_bar, success, error, warn, info, rule
from db.connection import Database
from services.tone_engine import (
    get_active_split, get_all_splits,
    save_split, validate_split, ToneSplit,
)


def _render_tone_panel(pro: int, semi: int, cas: int, valid: bool, msg: str) -> None:
    total = pro + semi + cas
    total_style = "meridian.success" if valid else "meridian.error"

    lines = Text()
    lines.append(tone_bar("Professional", pro) + "\n", style="meridian.pro")
    lines.append(tone_bar("Semi-casual",  semi) + "\n", style="meridian.semi")
    lines.append(tone_bar("Casual",       cas)  + "\n\n", style="meridian.cas")
    lines.append(f"  Running total: ", style="meridian.muted")
    lines.append(f"{total}%  ", style=total_style)
    if valid:
        lines.append("✓ valid", style="meridian.success")
    else:
        lines.append(f"✗  {msg}", style="meridian.error")

    console.print(Panel(
        lines,
        title="[bold meridian.title]CONFIGURE TONE SPLIT[/]",
        border_style="meridian.border",
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
        expand=True,
    ))


def screen_tone_config(db: Database) -> None:
    console.clear()
    console.print(header_panel(
        "CONFIGURE TONE SPLIT",
        "Percentages must sum to 100 • Changes are logged, never overwritten"
    ))
    console.print()

    current = get_active_split(db)
    info(f"Current split → Professional: {current.professional}%  "
         f"Semi-casual: {current.semi_casual}%  Casual: {current.casual}%")
    console.print()

    # Get new values
    def _get_int(prompt: str, default: int) -> int:
        val = questionary.text(
            prompt,
            default=str(default),
            validate=lambda v: True if v.strip().isdigit() else "Must be a whole number.",
        ).ask()
        return int(val or default)

    pro  = _get_int(f"Professional % (current: {current.professional}):", current.professional)
    semi = _get_int(f"Semi-casual  % (current: {current.semi_casual}):",  current.semi_casual)
    cas  = _get_int(f"Casual       % (current: {current.casual}):",       current.casual)

    console.print()
    valid, reason = validate_split(pro, semi, cas)
    _render_tone_panel(pro, semi, cas, valid, reason)
    console.print()

    if not valid:
        error(f"Cannot save: {reason}")
        questionary.press_any_key_to_continue().ask()
        return

    choice = questionary.select(
        "What would you like to do?",
        choices=["Save", f"Reset to default (60/30/10)", "Cancel"],
    ).ask()

    if choice is None or choice == "Cancel":
        warn("No changes saved.")
        questionary.press_any_key_to_continue().ask()
        return

    if choice.startswith("Reset"):
        pro, semi, cas = 60, 30, 10

    note = questionary.text("Note for this change (optional):").ask() or None

    try:
        saved = save_split(db, pro, semi, cas, note)
        success(f"Tone split saved (ID #{saved.id}) → "
                f"Pro: {saved.professional}%  Semi: {saved.semi_casual}%  Cas: {saved.casual}%")
    except ValueError as exc:
        error(str(exc))

    questionary.press_any_key_to_continue().ask()


def screen_tone_history(db: Database) -> None:
    """Show the full tone split history."""
    console.clear()
    console.print(header_panel("TONE SPLIT HISTORY"))
    console.print()

    splits = get_all_splits(db)
    for s in splits:
        active_marker = " ← [meridian.success]ACTIVE[/]" if s.is_active else ""
        console.print(
            f"  [meridian.muted]#{s.id}[/]  "
            f"[meridian.pro]Pro:{s.professional}%[/]  "
            f"[meridian.semi]Semi:{s.semi_casual}%[/]  "
            f"[meridian.cas]Cas:{s.casual}%[/]"
            + (f"  [meridian.muted]{s.note}[/]" if s.note else "")
            + active_marker
        )

    questionary.press_any_key_to_continue().ask()
