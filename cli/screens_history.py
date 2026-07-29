"""
cli/screens_history.py
History / Logs browsing screens.
"""
from __future__ import annotations

import questionary
from rich import box
from rich.panel import Panel

from cli.formatting import console, header_panel, message_log_table, success, error, warn, info
from db.connection import Database
from services.campaign_service import (
    history_for_person, history_for_campaign,
    history_failed, history_by_date_range, list_campaigns,
)
from services.person_service import get_person, search_persons


def _pick_person_id(db: Database) -> int | None:
    query = questionary.text("Search person by name or email:").ask()
    if not query:
        return None
    persons = search_persons(db, query=query)
    if not persons:
        warn("No persons found.")
        return None
    choices = [f"#{p.id}  {p.full_name}  <{p.email}>" for p in persons]
    picked = questionary.select("Select person:", choices=choices).ask()
    if not picked:
        return None
    return int(picked.split()[0].lstrip("#"))


def screen_history_by_person(db: Database) -> None:
    console.clear()
    console.print(header_panel("HISTORY — BY PERSON", "All messages ever sent to a specific person"))
    console.print()

    person_id = _pick_person_id(db)
    if person_id is None:
        return

    person = get_person(db, person_id)
    if not person:
        error(f"Person #{person_id} not found.")
        questionary.press_any_key_to_continue().ask()
        return

    logs = history_for_person(db, person_id)
    console.print()
    info(f"History for [bold]{person.full_name}[/] <{person.email}>")
    console.print()

    if not logs:
        warn("No messages have been sent to this person yet.")
    else:
        console.print(message_log_table(logs))
        info(f"{len(logs)} message(s) found.")

    questionary.press_any_key_to_continue().ask()


def screen_history_by_campaign(db: Database) -> None:
    console.clear()
    console.print(header_panel("HISTORY — BY CAMPAIGN"))
    console.print()

    campaigns = list_campaigns(db)
    if not campaigns:
        warn("No campaigns found.")
        questionary.press_any_key_to_continue().ask()
        return

    choices = [f"#{c.id}  {c.name}  [{c.status}]" for c in campaigns]
    picked = questionary.select("Select campaign:", choices=choices).ask()
    if not picked:
        return

    campaign_id = int(picked.split()[0].lstrip("#"))
    logs = history_for_campaign(db, campaign_id)
    console.print()

    if not logs:
        warn("No messages found for this campaign.")
    else:
        console.print(message_log_table(logs))
        info(f"{len(logs)} message(s).")

    questionary.press_any_key_to_continue().ask()


def screen_history_by_date(db: Database) -> None:
    console.clear()
    console.print(header_panel("HISTORY — BY DATE RANGE"))
    console.print()

    start = questionary.text(
        "Start date (YYYY-MM-DD):",
        validate=lambda v: True if len(v.strip()) == 10 else "Use YYYY-MM-DD format.",
    ).ask()
    if not start:
        return

    end = questionary.text(
        "End date (YYYY-MM-DD):",
        validate=lambda v: True if len(v.strip()) == 10 else "Use YYYY-MM-DD format.",
    ).ask()
    if not end:
        return

    logs = history_by_date_range(db, start.strip(), end.strip())
    console.print()

    if not logs:
        warn("No messages found in that date range.")
    else:
        console.print(message_log_table(logs))
        info(f"{len(logs)} message(s).")

    questionary.press_any_key_to_continue().ask()


def screen_history_failed(db: Database) -> None:
    console.clear()
    console.print(header_panel("HISTORY — FAILED SENDS ONLY"))
    console.print()

    logs = history_failed(db)

    if not logs:
        success("No failed sends found.")
    else:
        console.print(message_log_table(logs))
        info(f"{len(logs)} failed message(s).")

        # Show error details
        show_details = questionary.confirm("Show error details?", default=False).ask()
        if show_details:
            for log in logs:
                if log.get("error_message"):
                    console.print(Panel(
                        f"[meridian.muted]ID #{log['id']}[/]  {log.get('recipient_email', '')}\n\n"
                        f"[meridian.error]{log['error_message']}[/]",
                        border_style="meridian.error",
                        box=box.ROUNDED,
                    ))

    questionary.press_any_key_to_continue().ask()


def history_menu(db: Database) -> None:
    while True:
        console.clear()
        console.print(header_panel("HISTORY / LOGS"))
        console.print()

        choice = questionary.select(
            "Select view:",
            choices=[
                "Search by person (all messages ever sent)",
                "Browse by campaign",
                "Browse by date range",
                "View failed sends only",
                "Back to Main Menu",
            ],
        ).ask()

        if choice is None or choice == "Back to Main Menu":
            return
        elif choice.startswith("Search by person"):
            screen_history_by_person(db)
        elif choice.startswith("Browse by campaign"):
            screen_history_by_campaign(db)
        elif choice.startswith("Browse by date"):
            screen_history_by_date(db)
        elif choice.startswith("View failed"):
            screen_history_failed(db)
