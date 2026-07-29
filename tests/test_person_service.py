"""
tests/test_person_service.py
Unit tests for person_service — CRUD, validation, CSV import/export.
"""
from __future__ import annotations

import csv
import os
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from services.person_service import (
    PersonInput, Person, ImportResult,
    add_person, get_person, search_persons, update_person, set_status,
    import_csv, export_csv, _validate_email,
)


def _make_person(**kwargs) -> dict:
    defaults = {
        "id": 1, "full_name": "Jane Whitmore", "email": "jane@example.com",
        "designation": "Managing Editor", "category": "journalist",
        "organization": "The Daily", "country": "UK", "preferred_tone": "auto",
        "notes": None, "status": "active",
        "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1),
    }
    defaults.update(kwargs)
    return defaults


class TestValidateEmail:
    def test_valid(self):
        assert _validate_email("test@example.com") == "test@example.com"

    def test_strips_and_lowercases(self):
        assert _validate_email("  TEST@EXAMPLE.COM  ") == "test@example.com"

    def test_no_at_fails(self):
        with pytest.raises(ValueError):
            _validate_email("notanemail")

    def test_no_domain_fails(self):
        with pytest.raises(ValueError):
            _validate_email("test@")


class TestAddPerson:
    def test_success(self, mock_db):
        mock_db.fetch_one.side_effect = [None, _make_person()]  # no duplicate, then new row
        mock_db.execute.return_value = 1
        result = add_person(mock_db, PersonInput(
            full_name="Jane Whitmore", email="jane@example.com",
            designation="Managing Editor", category="journalist",
        ))
        assert result.id == 1
        assert result.full_name == "Jane Whitmore"

    def test_duplicate_email_raises(self, mock_db):
        mock_db.fetch_one.return_value = {"id": 99}  # duplicate found
        with pytest.raises(ValueError, match="already exists"):
            add_person(mock_db, PersonInput(
                full_name="Jane", email="jane@example.com",
                designation="Editor", category="journalist",
            ))

    def test_empty_name_raises(self, mock_db):
        mock_db.fetch_one.return_value = None
        with pytest.raises(ValueError, match="full_name"):
            add_person(mock_db, PersonInput(
                full_name="  ", email="jane@example.com",
                designation="Editor", category="journalist",
            ))

    def test_invalid_category_raises(self, mock_db):
        mock_db.fetch_one.return_value = None
        with pytest.raises(ValueError, match="category"):
            add_person(mock_db, PersonInput(
                full_name="Jane", email="jane@example.com",
                designation="Editor", category="INVALID_CAT",
            ))

    def test_invalid_tone_raises(self, mock_db):
        mock_db.fetch_one.return_value = None
        with pytest.raises(ValueError, match="preferred_tone"):
            add_person(mock_db, PersonInput(
                full_name="Jane", email="jane@example.com",
                designation="Editor", category="journalist",
                preferred_tone="very_casual",
            ))

    def test_invalid_email_raises(self, mock_db):
        with pytest.raises(ValueError):
            add_person(mock_db, PersonInput(
                full_name="Jane", email="notanemail",
                designation="Editor", category="journalist",
            ))


class TestGetPerson:
    def test_found(self, mock_db):
        mock_db.fetch_one.return_value = _make_person()
        person = get_person(mock_db, 1)
        assert person is not None
        assert person.id == 1

    def test_not_found(self, mock_db):
        mock_db.fetch_one.return_value = None
        assert get_person(mock_db, 999) is None


class TestSearchPersons:
    def test_returns_all(self, mock_db):
        mock_db.fetch_all.return_value = [_make_person(), _make_person(id=2, email="bob@example.com")]
        results = search_persons(mock_db)
        assert len(results) == 2

    def test_returns_empty(self, mock_db):
        mock_db.fetch_all.return_value = []
        assert search_persons(mock_db) == []

    def test_builds_correct_where_clause(self, mock_db):
        mock_db.fetch_all.return_value = []
        search_persons(mock_db, category="journalist", status="active", query="Jane")
        call_args = mock_db.fetch_all.call_args[0]
        sql = call_args[0]
        assert "category = %s" in sql
        assert "status = %s" in sql
        assert "LIKE %s" in sql


class TestUpdatePerson:
    def test_updates_allowed_fields(self, mock_db):
        mock_db.fetch_one.return_value = _make_person(full_name="Jane Updated")
        result = update_person(mock_db, 1, {"full_name": "Jane Updated"})
        assert result.full_name == "Jane Updated"
        mock_db.execute.assert_called_once()

    def test_rejects_unknown_fields(self, mock_db):
        with pytest.raises(ValueError, match="No valid fields"):
            update_person(mock_db, 1, {"email": "hacker@evil.com"})

    def test_invalid_category_rejected(self, mock_db):
        with pytest.raises(ValueError, match="category"):
            update_person(mock_db, 1, {"category": "INVALID"})

    def test_not_found_raises(self, mock_db):
        mock_db.execute.return_value = 0
        mock_db.fetch_one.return_value = None
        with pytest.raises(ValueError, match="not found"):
            update_person(mock_db, 999, {"full_name": "Ghost"})


class TestSetStatus:
    def test_set_active(self, mock_db):
        mock_db.fetch_one.return_value = _make_person(status="archived")
        set_status(mock_db, 1, "active")
        mock_db.execute.assert_called_once()

    def test_unsubscribed_appends_note(self, mock_db):
        mock_db.fetch_one.return_value = _make_person(notes="original note")
        set_status(mock_db, 1, "unsubscribed")
        call_args = mock_db.execute.call_args[0]
        sql = call_args[0]
        # Should UPDATE both status and notes
        assert "notes" in sql

    def test_invalid_status_raises(self, mock_db):
        mock_db.fetch_one.return_value = _make_person()
        with pytest.raises(ValueError, match="Invalid status"):
            set_status(mock_db, 1, "deleted")

    def test_not_found_raises(self, mock_db):
        mock_db.fetch_one.return_value = None
        with pytest.raises(ValueError, match="not found"):
            set_status(mock_db, 999, "active")


class TestImportCsv:
    def _write_csv(self, rows: list[dict], path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    def test_successful_import(self, mock_db):
        person_row = {
            "id": 10, "full_name": "Alice", "email": "alice@test.com",
            "designation": "CEO", "category": "tech_founder",
            "organization": None, "country": None, "preferred_tone": "auto",
            "notes": None, "status": "active",
            "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1),
        }
        # For each person: fetch_one("SELECT id FROM...")=None (no dup), fetch_one("SELECT * FROM...")=row
        mock_db.fetch_one.side_effect = [None, person_row, None, person_row]
        mock_db.execute.return_value = 10

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            path = f.name

        try:
            rows = [
                {"full_name": "Alice", "email": "alice@test.com", "designation": "CEO", "category": "tech_founder"},
                {"full_name": "Bob",   "email": "bob@test.com",   "designation": "Editor", "category": "journalist"},
            ]
            self._write_csv(rows, path)
            result = import_csv(mock_db, path)
            assert result.created == 2
            assert result.skipped == 0
        finally:
            os.unlink(path)

    def test_duplicate_email_skipped(self, mock_db):
        mock_db.fetch_one.return_value = {"id": 1}  # always "found"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            path = f.name
        try:
            rows = [{"full_name": "Alice", "email": "alice@test.com", "designation": "CEO", "category": "tech_founder"}]
            self._write_csv(rows, path)
            result = import_csv(mock_db, path)
            assert result.created == 0
            assert result.skipped == 1
            assert result.errors[0]["reason"].find("already exists") >= 0
        finally:
            os.unlink(path)

    def test_missing_required_column_raises(self, mock_db):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            path = f.name
        try:
            with open(path, "w") as fh:
                fh.write("full_name,email\nAlice,alice@test.com\n")
            with pytest.raises(ValueError, match="missing required columns"):
                import_csv(mock_db, path)
        finally:
            os.unlink(path)

    def test_bad_row_skipped_rest_continues(self, mock_db):
        person_row = {
            "id": 10, "full_name": "Alice", "email": "alice@test.com",
            "designation": "CEO", "category": "tech_founder",
            "organization": None, "country": None, "preferred_tone": "auto",
            "notes": None, "status": "active",
            "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1),
        }
        # Row 1 (Alice): no dup check, then get inserted row
        # Row 2 (empty name): validation fails before hitting DB
        # Row 3 (Carol): no dup check, then get inserted row
        mock_db.fetch_one.side_effect = [None, person_row, None, person_row]
        mock_db.execute.return_value = 10

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            path = f.name
        try:
            rows = [
                {"full_name": "Alice", "email": "alice@test.com",   "designation": "CEO",    "category": "tech_founder"},
                {"full_name": "",      "email": "bad@test.com",     "designation": "Editor", "category": "journalist"},  # empty name
                {"full_name": "Carol", "email": "carol@test.com",   "designation": "Head",   "category": "diplomat"},
            ]
            self._write_csv(rows, path)
            result = import_csv(mock_db, path)
            assert result.skipped >= 1  # bad row skipped
        finally:
            os.unlink(path)

    def test_file_not_found_raises(self, mock_db):
        with pytest.raises(ValueError, match="File not found"):
            import_csv(mock_db, "/nonexistent/path/file.csv")


class TestExportCsv:
    def test_exports_to_file(self, mock_db):
        from datetime import datetime
        mock_db.fetch_all.return_value = [
            {"id": 1, "full_name": "Jane", "email": "jane@ex.com",
             "designation": "Editor", "category": "journalist",
             "organization": None, "country": None, "preferred_tone": "auto",
             "notes": None, "status": "active",
             "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1)},
        ]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            count = export_csv(mock_db, path)
            assert count == 1
            with open(path) as fh:
                content = fh.read()
            assert "jane@ex.com" in content
        finally:
            os.unlink(path)
