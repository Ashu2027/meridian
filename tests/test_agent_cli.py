"""
tests/test_agent_cli.py
Unit tests for agent/agent_cli.py.

Each agent action calls _ok() or _err() which prints JSON then calls sys.exit().
We catch SystemExit and capture stdout with capsys.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent.agent_cli import run_agent_command
from config import AppConfig


# ── Helpers ────────────────────────────────────────────────────────────────────

def _cfg() -> AppConfig:
    return AppConfig(
        resend_api_key="re_test",
        default_from_name="Test",
        default_from_email="t@t.com",
        api_secret_token="tok",
    )


def _person_row(**kw):
    defaults = {
        "id": 1, "full_name": "Jane Doe", "email": "jane@example.com",
        "designation": "Editor", "category": "journalist",
        "organization": None, "country": None, "preferred_tone": "auto",
        "notes": None, "status": "active",
        "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1),
    }
    defaults.update(kw)
    return defaults


def _run(action, params, mock_db, cfg=None):
    """Run agent command, capture exit code and stdout JSON."""
    cfg = cfg or _cfg()
    with pytest.raises(SystemExit) as exc_info:
        run_agent_command(action, params, mock_db, cfg)
    return exc_info.value.code


def _run_json(action, params, mock_db, capsys, cfg=None):
    """Run agent command and return (exit_code, parsed_json)."""
    code = _run(action, params, mock_db, cfg)
    out = capsys.readouterr().out
    return code, json.loads(out)


# ── person-add ─────────────────────────────────────────────────────────────────

class TestPersonAdd:
    def test_success(self, mock_db, capsys):
        mock_db.fetch_one.side_effect = [None, _person_row()]
        mock_db.execute.return_value = 1

        code, result = _run_json("person-add", {
            "full_name": "Jane Doe", "email": "jane@example.com",
            "designation": "Editor", "category": "journalist",
        }, mock_db, capsys)

        assert code == 0
        assert result["ok"] is True
        assert result["result"]["full_name"] == "Jane Doe"

    def test_invalid_email_exits_1(self, mock_db, capsys):
        code, result = _run_json("person-add", {
            "full_name": "Jane", "email": "notanemail",
            "designation": "Editor", "category": "journalist",
        }, mock_db, capsys)
        assert code == 1
        assert result["ok"] is False
        assert result["error"]["code"] == "PERSON_ADD_INVALID"

    def test_invalid_category_exits_1(self, mock_db, capsys):
        mock_db.fetch_one.return_value = None
        code, result = _run_json("person-add", {
            "full_name": "Jane", "email": "jane@ex.com",
            "designation": "Editor", "category": "INVALID_CAT",
        }, mock_db, capsys)
        assert code == 1
        assert result["ok"] is False


# ── person-search ──────────────────────────────────────────────────────────────

class TestPersonSearch:
    def test_returns_list(self, mock_db, capsys):
        mock_db.fetch_all.return_value = [_person_row()]

        code, result = _run_json("person-search", {"status": "active"}, mock_db, capsys)
        assert code == 0
        assert result["ok"] is True
        assert len(result["result"]) == 1
        assert result["result"][0]["email"] == "jane@example.com"

    def test_empty_returns_ok(self, mock_db, capsys):
        mock_db.fetch_all.return_value = []
        code, result = _run_json("person-search", {}, mock_db, capsys)
        assert code == 0
        assert result["result"] == []

    def test_search_with_query(self, mock_db, capsys):
        mock_db.fetch_all.return_value = [_person_row()]
        code, result = _run_json("person-search", {"query": "Jane"}, mock_db, capsys)
        assert code == 0


# ── person-update ──────────────────────────────────────────────────────────────

class TestPersonUpdate:
    def test_success(self, mock_db, capsys):
        mock_db.execute.return_value = 1
        mock_db.fetch_one.return_value = _person_row(full_name="Jane Updated")

        code, result = _run_json("person-update", {
            "person_id": 1, "changes": {"full_name": "Jane Updated"},
        }, mock_db, capsys)
        assert code == 0
        assert result["ok"] is True

    def test_invalid_fields_exits_1(self, mock_db, capsys):
        code, result = _run_json("person-update", {
            "person_id": 1, "changes": {"email": "hacker@evil.com"},
        }, mock_db, capsys)
        assert code == 1
        assert result["error"]["code"] == "PERSON_UPDATE_INVALID"

    def test_missing_person_id_exits_1(self, mock_db, capsys):
        code, result = _run_json("person-update", {"changes": {}}, mock_db, capsys)
        assert code == 1


# ── person-set-status ──────────────────────────────────────────────────────────

class TestPersonSetStatus:
    def test_success(self, mock_db, capsys):
        mock_db.fetch_one.return_value = _person_row()
        code, result = _run_json("person-set-status", {
            "person_id": 1, "new_status": "unsubscribed",
        }, mock_db, capsys)
        assert code == 0
        assert result["result"]["status"] == "unsubscribed"

    def test_invalid_status_exits_1(self, mock_db, capsys):
        mock_db.fetch_one.return_value = _person_row()
        code, result = _run_json("person-set-status", {
            "person_id": 1, "new_status": "deleted",
        }, mock_db, capsys)
        assert code == 1
        assert result["error"]["code"] == "STATUS_INVALID"

    def test_missing_person_exits_1(self, mock_db, capsys):
        mock_db.fetch_one.return_value = None
        code, result = _run_json("person-set-status", {
            "person_id": 999, "new_status": "active",
        }, mock_db, capsys)
        assert code == 1


# ── person-import-csv ──────────────────────────────────────────────────────────

class TestPersonImportCsv:
    def test_success(self, mock_db, capsys, tmp_path):
        csv_file = tmp_path / "persons.csv"
        csv_file.write_text(
            "full_name,email,designation,category\n"
            "Alice,alice@test.com,CEO,tech_founder\n"
        )
        person_row = _person_row(full_name="Alice", email="alice@test.com")
        mock_db.fetch_one.side_effect = [None, person_row]
        mock_db.execute.return_value = 1

        code, result = _run_json("person-import-csv", {"file_path": str(csv_file)}, mock_db, capsys)
        assert code == 0
        assert result["result"]["created"] == 1

    def test_missing_file_exits_1(self, mock_db, capsys):
        code, result = _run_json("person-import-csv", {
            "file_path": "/nonexistent/file.csv"
        }, mock_db, capsys)
        assert code == 1
        assert result["error"]["code"] == "IMPORT_FAILED"


# ── person-export-csv ──────────────────────────────────────────────────────────

class TestPersonExportCsv:
    def test_success(self, mock_db, capsys, tmp_path):
        mock_db.fetch_all.return_value = [_person_row()]
        dest = str(tmp_path / "out.csv")

        code, result = _run_json("person-export-csv", {"file_path": dest}, mock_db, capsys)
        assert code == 0
        assert result["result"]["exported"] == 1


# ── tone-get ───────────────────────────────────────────────────────────────────

class TestToneGet:
    def test_returns_active_split(self, mock_db, capsys):
        mock_db.fetch_one.return_value = {
            "id": 1, "professional_percent": 60, "semi_casual_percent": 30,
            "casual_percent": 10, "is_active": True, "updated_by_note": None,
        }
        code, result = _run_json("tone-get", {}, mock_db, capsys)
        assert code == 0
        assert result["result"]["professional_percent"] == 60


# ── tone-set ───────────────────────────────────────────────────────────────────

class TestToneSet:
    def test_valid_split(self, mock_db, capsys):
        mock_db.execute.return_value = 5
        code, result = _run_json("tone-set", {
            "professional": 50, "semi_casual": 30, "casual": 20, "note": "test"
        }, mock_db, capsys)
        assert code == 0
        assert result["result"]["professional_percent"] == 50

    def test_invalid_sum_exits_1(self, mock_db, capsys):
        code, result = _run_json("tone-set", {
            "professional": 50, "semi_casual": 30, "casual": 15
        }, mock_db, capsys)
        assert code == 1
        assert result["error"]["code"] == "TONE_SPLIT_INVALID"

    def test_missing_param_exits_1(self, mock_db, capsys):
        code, result = _run_json("tone-set", {"professional": 50}, mock_db, capsys)
        assert code == 1


# ── campaign-create ────────────────────────────────────────────────────────────

class TestCampaignCreate:
    def _camp_row(self):
        return {
            "id": 1, "name": "Q3 Outreach", "topic_brief": "Q3 results",
            "target_filter": None, "tone_professional_percent": 60,
            "tone_semi_casual_percent": 30, "tone_casual_percent": 10,
            "total_recipients": 0, "total_sent": 0, "total_failed": 0,
            "status": "draft", "created_at": datetime(2026, 1, 1), "completed_at": None,
        }

    def test_success(self, mock_db, capsys):
        mock_db.fetch_one.side_effect = [
            # get_active_split → tone_settings row
            {"id": 1, "professional_percent": 60, "semi_casual_percent": 30,
             "casual_percent": 10, "is_active": True, "updated_by_note": None},
            # fetch_one after INSERT → campaign row
            self._camp_row(),
        ]
        mock_db.execute.return_value = 1

        code, result = _run_json("campaign-create", {
            "name": "Q3 Outreach", "topic_brief": "Q3 results"
        }, mock_db, capsys)
        assert code == 0
        assert result["result"]["name"] == "Q3 Outreach"

    def test_empty_name_exits_1(self, mock_db, capsys):
        mock_db.fetch_one.return_value = {
            "id": 1, "professional_percent": 60, "semi_casual_percent": 30,
            "casual_percent": 10, "is_active": True, "updated_by_note": None,
        }
        code, result = _run_json("campaign-create", {
            "name": "", "topic_brief": "test"
        }, mock_db, capsys)
        assert code == 1

    def test_missing_name_key_exits_1(self, mock_db, capsys):
        code, result = _run_json("campaign-create", {"topic_brief": "test"}, mock_db, capsys)
        assert code == 1


# ── campaign-recipients ────────────────────────────────────────────────────────

class TestCampaignRecipients:
    def _camp_row(self):
        return {
            "id": 1, "name": "Q3", "topic_brief": "Q3 results",
            "target_filter": None, "tone_professional_percent": 60,
            "tone_semi_casual_percent": 30, "tone_casual_percent": 10,
            "total_recipients": 0, "total_sent": 0, "total_failed": 0,
            "status": "draft", "created_at": datetime(2026, 1, 1), "completed_at": None,
        }

    def test_success(self, mock_db, capsys):
        mock_db.fetch_one.return_value = self._camp_row()
        mock_db.fetch_all.return_value = [_person_row()]

        code, result = _run_json("campaign-recipients", {"campaign_id": 1}, mock_db, capsys)
        assert code == 0
        assert len(result["result"]) == 1
        assert "tone" in result["result"][0]

    def test_not_found_exits_1(self, mock_db, capsys):
        mock_db.fetch_one.return_value = None
        code, result = _run_json("campaign-recipients", {"campaign_id": 999}, mock_db, capsys)
        assert code == 1
        assert result["error"]["code"] == "CAMPAIGN_NOT_FOUND"

    def test_missing_key_exits_1(self, mock_db, capsys):
        code, result = _run_json("campaign-recipients", {}, mock_db, capsys)
        assert code == 1


# ── draft-validate ─────────────────────────────────────────────────────────────

class TestDraftValidate:
    def test_valid_draft(self, mock_db, capsys):
        mock_db.get_config_value.return_value = "200"
        body = " ".join(["word"] * 50)
        code, result = _run_json("draft-validate", {
            "person_id": 1, "subject": "Test", "body": body, "tone": "professional",
        }, mock_db, capsys)
        assert code == 0
        assert result["result"]["valid"] is True

    def test_invalid_draft_still_exits_0(self, mock_db, capsys):
        """draft-validate always exits 0 — validation results go in the JSON body."""
        mock_db.get_config_value.return_value = "200"
        code, result = _run_json("draft-validate", {
            "person_id": 1, "subject": "Test",
            "body": "Hello 😀 world", "tone": "professional",
        }, mock_db, capsys)
        assert code == 0
        assert result["result"]["valid"] is False

    def test_over_word_limit(self, mock_db, capsys):
        mock_db.get_config_value.return_value = "10"
        body = " ".join(["word"] * 20)
        code, result = _run_json("draft-validate", {
            "person_id": 1, "subject": "Test", "body": body, "tone": "casual",
        }, mock_db, capsys)
        assert code == 0
        assert result["result"]["valid"] is False
        assert result["result"]["word_count"] == 20


# ── campaign-send ──────────────────────────────────────────────────────────────

class TestCampaignSend:
    def test_no_confirm_exits_1(self, mock_db, capsys):
        code, result = _run_json("campaign-send", {
            "campaign_id": 1, "confirm": False
        }, mock_db, capsys)
        assert code == 1
        assert result["error"]["code"] == "CONFIRM_REQUIRED"

    def test_confirm_missing_treated_as_false(self, mock_db, capsys):
        code, result = _run_json("campaign-send", {"campaign_id": 1}, mock_db, capsys)
        assert code == 1
        assert result["error"]["code"] == "CONFIRM_REQUIRED"

    def test_confirm_true_no_pending_exits_1(self, mock_db, capsys):
        mock_db.fetch_one.return_value = {
            "id": 1, "name": "Q3", "topic_brief": "q3",
            "target_filter": None, "tone_professional_percent": 60,
            "tone_semi_casual_percent": 30, "tone_casual_percent": 10,
            "total_recipients": 0, "total_sent": 0, "total_failed": 0,
            "status": "draft", "created_at": datetime(2026, 1, 1), "completed_at": None,
        }
        mock_db.fetch_all.return_value = []  # no pending drafts

        code, result = _run_json("campaign-send", {
            "campaign_id": 1, "confirm": True
        }, mock_db, capsys)
        assert code == 1
        assert result["error"]["code"] == "NO_PENDING_DRAFTS"


# ── history-query ──────────────────────────────────────────────────────────────

class TestHistoryQuery:
    def _log_row(self):
        return {
            "id": 1, "campaign_id": 1, "campaign_name": "Q3",
            "subject": "Hello", "tone_used": "professional",
            "status": "sent", "sent_at": datetime(2026, 1, 1),
            "word_count": 50, "created_at": datetime(2026, 1, 1),
        }

    def test_by_person_id(self, mock_db, capsys):
        mock_db.fetch_all.return_value = [self._log_row()]
        code, result = _run_json("history-query", {"person_id": 1}, mock_db, capsys)
        assert code == 0
        assert len(result["result"]) == 1

    def test_by_campaign_id(self, mock_db, capsys):
        mock_db.fetch_all.return_value = [self._log_row()]
        code, result = _run_json("history-query", {"campaign_id": 1}, mock_db, capsys)
        assert code == 0

    def test_by_date_range(self, mock_db, capsys):
        mock_db.fetch_all.return_value = [self._log_row()]
        code, result = _run_json("history-query", {
            "date_start": "2026-01-01", "date_end": "2026-12-31"
        }, mock_db, capsys)
        assert code == 0

    def test_missing_filter_exits_1(self, mock_db, capsys):
        code, result = _run_json("history-query", {}, mock_db, capsys)
        assert code == 1
        assert result["error"]["code"] == "MISSING_FILTER"


# ── unknown action ─────────────────────────────────────────────────────────────

class TestUnknownAction:
    def test_exits_1_with_unknown_action(self, mock_db, capsys):
        code, result = _run_json("totally-fake-action", {}, mock_db, capsys)
        assert code == 1
        assert result["error"]["code"] == "UNKNOWN_ACTION"


# ── coverage gap: export-csv error path (line 108) ────────────────────────────

class TestPersonExportCsvError:
    def test_missing_file_path_key_exits_1(self, mock_db, capsys):
        """KeyError when 'file_path' key is missing → EXPORT_FAILED."""
        code, result = _run_json("person-export-csv", {}, mock_db, capsys)
        assert code == 1
        assert result["error"]["code"] == "EXPORT_FAILED"


# ── coverage gap: campaign-send with confirm=True, campaign not found (line 197)

class TestCampaignSendCoverageGaps:
    def test_campaign_not_found_exits_1(self, mock_db, capsys):
        """confirm=True but campaign doesn't exist → CAMPAIGN_NOT_FOUND."""
        mock_db.fetch_one.return_value = None
        code, result = _run_json("campaign-send", {
            "campaign_id": 999, "confirm": True
        }, mock_db, capsys)
        assert code == 1
        assert result["error"]["code"] == "CAMPAIGN_NOT_FOUND"

    def test_successful_dispatch_loop(self, mock_db, capsys):
        """confirm=True, campaign found, pending drafts exist → dispatched."""
        from services.sender_queue import SendResult

        camp_row = {
            "id": 1, "name": "Q3", "topic_brief": "Q3",
            "target_filter": None, "tone_professional_percent": 60,
            "tone_semi_casual_percent": 30, "tone_casual_percent": 10,
            "total_recipients": 1, "total_sent": 0, "total_failed": 0,
            "status": "draft", "created_at": datetime(2026, 1, 1), "completed_at": None,
        }
        pending_log = {
            "person_id": 1, "campaign_id": 1,
            "recipient_email": "jane@example.com", "recipient_name": "Jane",
            "designation_snapshot": "Editor", "subject": "Test",
            "message_body": "Hello world.", "word_count": 2, "tone_used": "professional",
        }
        mock_db.fetch_one.return_value = camp_row
        # First call: pending_logs; second call: already_sent_ids (empty = no duplicates)
        mock_db.fetch_all.side_effect = [[pending_log], []]
        mock_db.execute.return_value = 1
        mock_db.get_config_value.return_value = "20"

        sent_result = SendResult(
            person_id=1, email="jane@example.com",
            status="sent", resend_message_id="msg_ok",
        )

        with patch("services.sender_queue.dispatch", return_value=iter([sent_result])):
            code, result = _run_json("campaign-send", {
                "campaign_id": 1, "confirm": True
            }, mock_db, capsys)

        assert code == 0
        assert result["result"]["sent"] == 1
        assert result["result"]["failed"] == 0

    def test_dispatch_with_failure(self, mock_db, capsys):
        """confirm=True with a draft that fails to send."""
        from services.sender_queue import SendResult

        camp_row = {
            "id": 1, "name": "Q3", "topic_brief": "Q3",
            "target_filter": None, "tone_professional_percent": 60,
            "tone_semi_casual_percent": 30, "tone_casual_percent": 10,
            "total_recipients": 1, "total_sent": 0, "total_failed": 0,
            "status": "draft", "created_at": datetime(2026, 1, 1), "completed_at": None,
        }
        pending_log = {
            "person_id": 1, "campaign_id": 1,
            "recipient_email": "bad@bad.com", "recipient_name": "Bad",
            "designation_snapshot": "Editor", "subject": "Test",
            "message_body": "Hello.", "word_count": 1, "tone_used": "professional",
        }
        mock_db.fetch_one.return_value = camp_row
        # First call: pending_logs; second call: already_sent_ids (empty = no duplicates)
        mock_db.fetch_all.side_effect = [[pending_log], []]
        mock_db.execute.return_value = 1
        mock_db.get_config_value.return_value = "20"

        fail_result = SendResult(
            person_id=1, email="bad@bad.com",
            status="failed", error_message="invalid_to",
        )

        with patch("services.sender_queue.dispatch", return_value=iter([fail_result])):
            code, result = _run_json("campaign-send", {
                "campaign_id": 1, "confirm": True
            }, mock_db, capsys)

        assert code == 0
        assert result["result"]["failed"] == 1
        assert result["result"]["sent"] == 0

