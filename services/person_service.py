"""
services/person_service.py
CRUD + CSV import/export for the persons table.
All validation happens here — the service layer is the single gate.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from db.connection import Database, DatabaseError

# ── Validation helpers ────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

VALID_CATEGORIES = {
    "billionaire", "millionaire", "tech_founder", "politician",
    "content_creator", "journalist", "human_rights", "government_org",
    "government_official", "diplomat", "media_personality",
    "united_organization", "high_value_person", "other",
}

VALID_TONES = {"professional", "semi_casual", "casual", "auto"}
VALID_STATUSES = {"active", "unsubscribed", "bounced", "archived"}


def _validate_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError(f"Invalid email address: {email!r}")
    return email


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class PersonInput:
    full_name: str
    email: str
    designation: str
    category: str
    organization: Optional[str] = None
    country: Optional[str] = None
    preferred_tone: str = "auto"
    notes: Optional[str] = None


@dataclass
class Person:
    id: int
    full_name: str
    email: str
    designation: str
    category: str
    organization: Optional[str]
    country: Optional[str]
    preferred_tone: str
    notes: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass
class ImportResult:
    created: int = 0
    skipped: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)


# ── Mapping helper ─────────────────────────────────────────────────────────────

def _row_to_person(row: dict) -> Person:
    return Person(
        id=row["id"],
        full_name=row["full_name"],
        email=row["email"],
        designation=row["designation"],
        category=row["category"],
        organization=row.get("organization"),
        country=row.get("country"),
        preferred_tone=row["preferred_tone"],
        notes=row.get("notes"),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── Service functions ──────────────────────────────────────────────────────────

def add_person(db: Database, data: PersonInput) -> Person:
    """
    Validate and INSERT a new person.
    Raises ValueError on bad data, DatabaseError on DB issues.
    """
    email = _validate_email(data.email)

    if not data.full_name.strip():
        raise ValueError("full_name cannot be empty.")
    if not data.designation.strip():
        raise ValueError("designation cannot be empty.")
    if data.category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category: {data.category!r}")
    if data.preferred_tone not in VALID_TONES:
        raise ValueError(f"Invalid preferred_tone: {data.preferred_tone!r}")

    # Uniqueness check
    existing = db.fetch_one("SELECT id FROM persons WHERE email = %s", (email,))
    if existing:
        raise ValueError(f"A person with email {email!r} already exists (ID {existing['id']}).")

    new_id = db.execute(
        """
        INSERT INTO persons
            (full_name, email, designation, category, organization, country, preferred_tone, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            data.full_name.strip(),
            email,
            data.designation.strip(),
            data.category,
            data.organization,
            data.country,
            data.preferred_tone,
            data.notes,
        ),
    )
    row = db.fetch_one("SELECT * FROM persons WHERE id = %s", (new_id,))
    return _row_to_person(row)


def get_person(db: Database, person_id: int) -> Optional[Person]:
    row = db.fetch_one("SELECT * FROM persons WHERE id = %s", (person_id,))
    return _row_to_person(row) if row else None


def search_persons(
    db: Database,
    category: Optional[str] = None,
    status: Optional[str] = None,
    query: Optional[str] = None,
) -> List[Person]:
    """
    Flexible search.
    - category: filter by ENUM value
    - status:   filter by status ENUM
    - query:    substring match on full_name or email
    """
    clauses = []
    params: list = []

    if category:
        clauses.append("category = %s")
        params.append(category)
    if status:
        clauses.append("status = %s")
        params.append(status)
    if query:
        clauses.append("(full_name LIKE %s OR email LIKE %s)")
        like = f"%{query}%"
        params.extend([like, like])

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM persons {where} ORDER BY full_name ASC"
    rows = db.fetch_all(sql, tuple(params))
    return [_row_to_person(r) for r in rows]


def get_active_persons(db: Database, category: Optional[str] = None) -> List[Person]:
    """Return all active persons, optionally filtered by category."""
    return search_persons(db, category=category, status="active")


def update_person(db: Database, person_id: int, changes: Dict[str, Any]) -> Person:
    """
    Apply a partial update.
    Only whitelisted fields can be changed.
    """
    allowed = {
        "full_name", "designation", "category", "organization",
        "country", "preferred_tone", "notes",
    }
    filtered = {k: v for k, v in changes.items() if k in allowed}
    if not filtered:
        raise ValueError("No valid fields to update.")

    if "category" in filtered and filtered["category"] not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category: {filtered['category']!r}")
    if "preferred_tone" in filtered and filtered["preferred_tone"] not in VALID_TONES:
        raise ValueError(f"Invalid preferred_tone: {filtered['preferred_tone']!r}")

    set_clause = ", ".join(f"{k} = %s" for k in filtered)
    params = list(filtered.values()) + [person_id]
    db.execute(f"UPDATE persons SET {set_clause} WHERE id = %s", tuple(params))
    row = db.fetch_one("SELECT * FROM persons WHERE id = %s", (person_id,))
    if not row:
        raise ValueError(f"Person #{person_id} not found.")
    return _row_to_person(row)


def set_status(db: Database, person_id: int, new_status: str) -> None:
    """
    Update persons.status.
    Records a note in persons.notes when transitioning to unsubscribed or bounced.
    """
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {new_status!r}")

    person = get_person(db, person_id)
    if not person:
        raise ValueError(f"Person #{person_id} not found.")

    note_append = ""
    if new_status in ("unsubscribed", "bounced"):
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        note_append = f"\n[{ts}] Status changed to {new_status}."

    if note_append:
        existing_notes = person.notes or ""
        db.execute(
            "UPDATE persons SET status = %s, notes = %s WHERE id = %s",
            (new_status, (existing_notes + note_append).strip(), person_id),
        )
    else:
        db.execute(
            "UPDATE persons SET status = %s WHERE id = %s",
            (new_status, person_id),
        )


def import_csv(db: Database, file_path: str) -> ImportResult:
    """
    Import persons from a CSV file.
    Required columns: full_name, email, designation, category
    Optional columns: organization, country, preferred_tone, notes
    Duplicate emails are skipped (not overwritten).
    Bad rows are reported but do not abort the whole import.
    """
    result = ImportResult()
    required = {"full_name", "email", "designation", "category"}

    try:
        with open(file_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if not required.issubset(set(reader.fieldnames or [])):
                missing = required - set(reader.fieldnames or [])
                raise ValueError(f"CSV missing required columns: {missing}")

            for row_num, row in enumerate(reader, start=2):
                try:
                    data = PersonInput(
                        full_name=row["full_name"].strip(),
                        email=row["email"].strip(),
                        designation=row["designation"].strip(),
                        category=row["category"].strip().lower(),
                        organization=row.get("organization") or None,
                        country=row.get("country") or None,
                        preferred_tone=row.get("preferred_tone", "auto").strip() or "auto",
                        notes=row.get("notes") or None,
                    )
                    add_person(db, data)
                    result.created += 1
                except ValueError as exc:
                    result.skipped += 1
                    result.errors.append({"row": row_num, "email": row.get("email", "?"), "reason": str(exc)})
    except FileNotFoundError:
        raise ValueError(f"File not found: {file_path}")

    return result


def export_csv(
    db: Database,
    destination_path: str,
    category: Optional[str] = None,
    status: Optional[str] = None,
) -> int:
    """Write filtered persons to a CSV file. Returns row count written."""
    persons = search_persons(db, category=category, status=status)
    fields = ["id", "full_name", "email", "designation", "category",
              "organization", "country", "preferred_tone", "status", "notes"]

    with open(destination_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for p in persons:
            writer.writerow({f: getattr(p, f, "") for f in fields})

    return len(persons)


def get_designation_catalog(db: Database, category: Optional[str] = None) -> List[str]:
    """Return standardized designation titles, optionally filtered by category."""
    if category:
        rows = db.fetch_all(
            "SELECT standard_title FROM designation_catalog WHERE category = %s ORDER BY standard_title",
            (category,),
        )
    else:
        rows = db.fetch_all(
            "SELECT standard_title FROM designation_catalog ORDER BY category, standard_title"
        )
    return [r["standard_title"] for r in rows]
