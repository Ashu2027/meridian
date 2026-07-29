"""
cli/screens_persons.py
All person management screens: Add, Search, Edit, Import CSV, Export CSV, Change Status.
"""
from __future__ import annotations

from pathlib import Path

import questionary
from rich import box
from rich.panel import Panel
from rich.prompt import Prompt

from cli.formatting import (
    console, header_panel, persons_table,
    success, error, warn, info, rule,
)
from db.connection import Database
from services.person_service import (
    VALID_CATEGORIES, VALID_STATUSES, VALID_TONES,
    PersonInput, add_person, export_csv, get_person,
    get_designation_catalog, import_csv, search_persons, set_status, update_person,
)


def _category_choices() -> list[str]:
    return [c.replace("_", " ").title() + f"  [{c}]" for c in sorted(VALID_CATEGORIES)]


def _pick_category(prompt: str = "Category:") -> str:
    display = [c.replace("_", " ").title() for c in sorted(VALID_CATEGORIES)]
    raw = sorted(VALID_CATEGORIES)
    choice = questionary.select(prompt, choices=display).ask()
    if choice is None:
        raise KeyboardInterrupt
    idx = display.index(choice)
    return raw[idx]


def _pick_tone(prompt: str = "Preferred tone override:") -> str:
    choices = ["auto", "professional", "semi_casual", "casual"]
    return questionary.select(prompt, choices=choices).ask() or "auto"


# ── Screen: Add a Person ───────────────────────────────────────────────────────

def screen_add_person(db: Database) -> None:
    console.clear()
    console.print(header_panel("ADD A PERSON", "Fill in the details below"))
    console.print()

    full_name = questionary.text(
        "Full name:",
        validate=lambda v: True if v.strip() else "Name cannot be empty.",
    ).ask()
    if full_name is None:
        return

    email = questionary.text(
        "Email:",
        validate=lambda v: True if "@" in v.strip() else "Must be a valid email.",
    ).ask()
    if email is None:
        return

    category = _pick_category()

    # Offer catalog suggestions
    catalog = get_designation_catalog(db, category)
    if catalog:
        catalog_choices = catalog + ["— Enter custom title —"]
        picked = questionary.select("Designation (catalog suggestions):", choices=catalog_choices).ask()
        if picked is None:
            return
        if picked == "— Enter custom title —":
            designation = questionary.text(
                "Custom designation:",
                validate=lambda v: True if v.strip() else "Cannot be empty.",
            ).ask() or ""
        else:
            designation = picked
    else:
        designation = questionary.text(
            "Designation:",
            validate=lambda v: True if v.strip() else "Cannot be empty.",
        ).ask() or ""

    organization = questionary.text("Organization (optional):").ask() or None
    country = questionary.text("Country (optional):").ask() or None
    preferred_tone = _pick_tone()
    notes = questionary.text("Notes (optional):").ask() or None

    console.print()
    try:
        person = add_person(db, PersonInput(
            full_name=full_name,
            email=email,
            designation=designation,
            category=category,
            organization=organization,
            country=country,
            preferred_tone=preferred_tone,
            notes=notes,
        ))
        console.print(Panel(
            f"[meridian.success]✓[/] Person saved — ID [bold]#{person.id}[/], "
            f"[meridian.title]{person.full_name}[/] [meridian.muted]<{person.email}>[/]",
            border_style="meridian.success",
            box=box.ROUNDED,
        ))
    except ValueError as exc:
        error(str(exc))

    questionary.press_any_key_to_continue().ask()


# ── Screen: Search / View Persons ──────────────────────────────────────────────

def screen_search_persons(db: Database) -> None:
    while True:
        console.clear()
        console.print(header_panel("SEARCH / VIEW PERSONS"))
        console.print()

        filter_category = None
        filter_status = None
        query_str = None

        filter_choice = questionary.select(
            "Filter by:",
            choices=[
                "All active persons",
                "By category",
                "By status",
                "Search by name / email",
                "Back",
            ],
        ).ask()

        if filter_choice is None or filter_choice == "Back":
            return

        if filter_choice == "By category":
            filter_category = _pick_category("Select category:")
        elif filter_choice == "By status":
            filter_status = questionary.select(
                "Select status:", choices=list(VALID_STATUSES)
            ).ask()
        elif filter_choice == "Search by name / email":
            query_str = questionary.text("Search term:").ask() or ""
        else:
            filter_status = "active"

        persons = search_persons(db, category=filter_category, status=filter_status, query=query_str)
        console.print()

        if not persons:
            warn("No persons found matching your filters.")
        else:
            console.print(persons_table(persons))
            info(f"{len(persons)} person(s) found.")

        questionary.press_any_key_to_continue().ask()


# ── Screen: Edit a Person ──────────────────────────────────────────────────────

def screen_edit_person(db: Database) -> None:
    console.clear()
    console.print(header_panel("EDIT A PERSON"))
    console.print()

    id_str = questionary.text(
        "Enter person ID to edit:",
        validate=lambda v: True if v.strip().isdigit() else "Must be a numeric ID.",
    ).ask()
    if id_str is None:
        return

    person = get_person(db, int(id_str))
    if not person:
        error(f"No person found with ID #{id_str}.")
        questionary.press_any_key_to_continue().ask()
        return

    info(f"Editing: [bold]{person.full_name}[/] <{person.email}>")
    console.print()

    changes: dict = {}

    new_name = questionary.text(f"Full name [{person.full_name}]:", default=person.full_name).ask()
    if new_name and new_name != person.full_name:
        changes["full_name"] = new_name

    new_desig = questionary.text(f"Designation [{person.designation}]:", default=person.designation).ask()
    if new_desig and new_desig != person.designation:
        changes["designation"] = new_desig

    new_org = questionary.text(f"Organization [{person.organization or ''}]:", default=person.organization or "").ask()
    if new_org != (person.organization or ""):
        changes["organization"] = new_org or None

    new_country = questionary.text(f"Country [{person.country or ''}]:", default=person.country or "").ask()
    if new_country != (person.country or ""):
        changes["country"] = new_country or None

    new_tone = _pick_tone(f"Preferred tone [{person.preferred_tone}]:")
    if new_tone != person.preferred_tone:
        changes["preferred_tone"] = new_tone

    new_notes = questionary.text(f"Notes [{person.notes or ''}]:", default=person.notes or "").ask()
    if new_notes != (person.notes or ""):
        changes["notes"] = new_notes or None

    console.print()
    if not changes:
        warn("No changes made.")
    else:
        try:
            updated = update_person(db, person.id, changes)
            success(f"Person #{updated.id} updated successfully.")
        except ValueError as exc:
            error(str(exc))

    questionary.press_any_key_to_continue().ask()


# ── Screen: Change Status ──────────────────────────────────────────────────────

def screen_change_status(db: Database) -> None:
    console.clear()
    console.print(header_panel("CHANGE PERSON STATUS"))
    console.print()

    id_str = questionary.text(
        "Enter person ID:",
        validate=lambda v: True if v.strip().isdigit() else "Must be a numeric ID.",
    ).ask()
    if id_str is None:
        return

    person = get_person(db, int(id_str))
    if not person:
        error(f"No person found with ID #{id_str}.")
        questionary.press_any_key_to_continue().ask()
        return

    info(f"[bold]{person.full_name}[/] — current status: [bold]{person.status}[/]")
    console.print()

    new_status = questionary.select(
        "New status:",
        choices=list(VALID_STATUSES),
        default=person.status,
    ).ask()
    if new_status is None or new_status == person.status:
        warn("No change made.")
        questionary.press_any_key_to_continue().ask()
        return

    try:
        set_status(db, person.id, new_status)
        success(f"Status updated to [bold]{new_status}[/].")
    except ValueError as exc:
        error(str(exc))

    questionary.press_any_key_to_continue().ask()


# ── Screen: Import CSV ─────────────────────────────────────────────────────────

def screen_import_csv(db: Database) -> None:
    console.clear()
    console.print(header_panel("IMPORT FROM CSV"))
    console.print()
    info("Required columns: full_name, email, designation, category")
    info("Optional columns: organization, country, preferred_tone, notes")
    info(f"Drop CSV files in [bold]data/imports/[/] or enter any path below.")
    console.print()

    file_path = questionary.text(
        "CSV file path:",
        validate=lambda v: True if v.strip() else "Path cannot be empty.",
    ).ask()
    if file_path is None:
        return

    try:
        result = import_csv(db, file_path.strip())
        console.print()
        console.print(Panel(
            f"[meridian.success]Created:[/]  {result.created}\n"
            f"[meridian.warn]Skipped:[/]  {result.skipped}\n"
            + (
                "\n[meridian.error]Errors:[/]\n" + "\n".join(
                    f"  Row {e['row']} ({e['email']}): {e['reason']}" for e in result.errors
                ) if result.errors else ""
            ),
            title="Import Complete",
            border_style="meridian.accent",
            box=box.ROUNDED,
        ))
    except ValueError as exc:
        error(str(exc))

    questionary.press_any_key_to_continue().ask()


# ── Screen: Export CSV ─────────────────────────────────────────────────────────

def screen_export_csv(db: Database) -> None:
    console.clear()
    console.print(header_panel("EXPORT TO CSV"))
    console.print()

    filter_choice = questionary.select(
        "Export which persons?",
        choices=["All persons", "Active only", "By category", "By status"],
    ).ask()
    if filter_choice is None:
        return

    category = status = None
    if filter_choice == "Active only":
        status = "active"
    elif filter_choice == "By category":
        category = _pick_category()
    elif filter_choice == "By status":
        status = questionary.select("Select status:", choices=list(VALID_STATUSES)).ask()

    dest = questionary.text(
        "Destination file path:",
        default="data/exports/persons_export.csv",
    ).ask()
    if dest is None:
        return

    Path(dest).parent.mkdir(parents=True, exist_ok=True)

    try:
        count = export_csv(db, dest, category=category, status=status)
        success(f"{count} person(s) exported to [bold]{dest}[/].")
    except Exception as exc:
        error(str(exc))

    questionary.press_any_key_to_continue().ask()


# ── Submenu router ─────────────────────────────────────────────────────────────

def persons_menu(db: Database) -> None:
    while True:
        console.clear()
        console.print(header_panel("MANAGE PERSONS"))
        console.print()

        choice = questionary.select(
            "Select an action:",
            choices=[
                "Add a Person",
                "Search / View Persons",
                "Edit a Person",
                "Import from CSV",
                "Export to CSV",
                "Change Status (unsubscribe / archive / bounce)",
                "Back to Main Menu",
            ],
        ).ask()

        if choice is None or choice == "Back to Main Menu":
            return
        elif choice == "Add a Person":
            screen_add_person(db)
        elif choice == "Search / View Persons":
            screen_search_persons(db)
        elif choice == "Edit a Person":
            screen_edit_person(db)
        elif choice == "Import from CSV":
            screen_import_csv(db)
        elif choice == "Export to CSV":
            screen_export_csv(db)
        elif choice.startswith("Change Status"):
            screen_change_status(db)
