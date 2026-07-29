"""
tests/test_campaign_service.py
Unit tests for services/campaign_service.py — creation, get, list,
recipient resolution, draft submission, history queries, send phase.
"""
from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from services.campaign_service import (
    Campaign, CampaignResult, RecipientDraft,
    _row_to_campaign, create_campaign, get_campaign, list_campaigns,
    build_recipient_list, prepare_recipient_drafts,
    submit_draft, run_send_phase, abort_campaign,
    history_for_person, history_for_campaign,
    history_failed, history_by_date_range,
)
from services.person_service import Person


# ── Helpers ────────────────────────────────────────────────────────────────────

def _camp_row(**kw) -> dict:
    defaults = {
        "id": 1, "name": "Q3 Outreach", "topic_brief": "Q3 results",
        "target_filter": None,
        "tone_professional_percent": 60, "tone_semi_casual_percent": 30,
        "tone_casual_percent": 10, "total_recipients": 0,
        "total_sent": 0, "total_failed": 0, "status": "draft",
        "created_at": datetime(2026, 1, 1), "completed_at": None,
    }
    defaults.update(kw)
    return defaults


def _tone_row(**kw) -> dict:
    defaults = {
        "id": 1, "professional_percent": 60,
        "semi_casual_percent": 30, "casual_percent": 10,
        "is_active": True, "updated_by_note": None,
    }
    defaults.update(kw)
    return defaults


def _person(**kw) -> Person:
    defaults = dict(
        id=1, full_name="Jane Doe", email="jane@example.com",
        designation="Editor", category="journalist",
        organization=None, country=None, preferred_tone="auto",
        notes=None, status="active",
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
    )
    defaults.update(kw)
    return Person(**defaults)


def _person_row(**kw) -> dict:
    defaults = {
        "id": 1, "full_name": "Jane Doe", "email": "jane@example.com",
        "designation": "Editor", "category": "journalist",
        "organization": None, "country": None, "preferred_tone": "auto",
        "notes": None, "status": "active",
        "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1),
    }
    defaults.update(kw)
    return defaults


def _campaign(**kw) -> Campaign:
    return _row_to_campaign(_camp_row(**kw))


# ── _row_to_campaign ───────────────────────────────────────────────────────────

class TestRowToCampaign:
    def test_basic_mapping(self):
        c = _row_to_campaign(_camp_row())
        assert c.id == 1
        assert c.name == "Q3 Outreach"
        assert c.tone_professional == 60
        assert c.status == "draft"

    def test_optional_completed_at(self):
        c = _row_to_campaign(_camp_row(completed_at=datetime(2026, 6, 1)))
        assert c.completed_at == datetime(2026, 6, 1)

    def test_none_completed_at(self):
        assert _row_to_campaign(_camp_row()).completed_at is None

    def test_none_target_filter(self):
        c = _row_to_campaign(_camp_row(target_filter=None))
        assert c.target_filter is None


# ── create_campaign ────────────────────────────────────────────────────────────

class TestCreateCampaign:
    def test_success(self, mock_db):
        mock_db.fetch_one.side_effect = [_tone_row(), _camp_row()]
        mock_db.execute.return_value = 1
        c = create_campaign(mock_db, "Q3 Outreach", "Q3 results")
        assert c.id == 1
        assert c.name == "Q3 Outreach"

    def test_empty_name_raises(self, mock_db):
        mock_db.fetch_one.return_value = _tone_row()
        with pytest.raises(ValueError, match="name"):
            create_campaign(mock_db, "   ", "Q3 results")

    def test_empty_brief_raises(self, mock_db):
        mock_db.fetch_one.return_value = _tone_row()
        with pytest.raises(ValueError, match="brief"):
            create_campaign(mock_db, "Q3", "   ")

    def test_with_target_filter(self, mock_db):
        mock_db.fetch_one.side_effect = [_tone_row(), _camp_row()]
        mock_db.execute.return_value = 1
        c = create_campaign(mock_db, "Q3", "Brief", target_filter={"category": "journalist"})
        assert c is not None
        # Verify JSON-encoded filter was passed to INSERT
        args = mock_db.execute.call_args[0]
        assert '{"category": "journalist"}' in str(args)

    def test_snapshots_active_tone_split(self, mock_db):
        tone = _tone_row(professional_percent=80, semi_casual_percent=15, casual_percent=5)
        camp = _camp_row(tone_professional_percent=80, tone_semi_casual_percent=15, tone_casual_percent=5)
        mock_db.fetch_one.side_effect = [tone, camp]
        mock_db.execute.return_value = 1
        c = create_campaign(mock_db, "Test", "Brief")
        assert c.tone_professional == 80


# ── get_campaign ───────────────────────────────────────────────────────────────

class TestGetCampaign:
    def test_found(self, mock_db):
        mock_db.fetch_one.return_value = _camp_row()
        c = get_campaign(mock_db, 1)
        assert c is not None and c.id == 1

    def test_not_found_returns_none(self, mock_db):
        mock_db.fetch_one.return_value = None
        assert get_campaign(mock_db, 999) is None


# ── list_campaigns ─────────────────────────────────────────────────────────────

class TestListCampaigns:
    def test_returns_multiple(self, mock_db):
        mock_db.fetch_all.return_value = [_camp_row(), _camp_row(id=2, name="Q4")]
        results = list_campaigns(mock_db)
        assert len(results) == 2
        assert results[1].name == "Q4"

    def test_empty_returns_empty_list(self, mock_db):
        mock_db.fetch_all.return_value = []
        assert list_campaigns(mock_db) == []


# ── build_recipient_list ───────────────────────────────────────────────────────

class TestBuildRecipientList:
    def test_no_filter(self, mock_db):
        mock_db.fetch_all.return_value = [_person_row(), _person_row(id=2, email="b@b.com")]
        c = _campaign()
        result = build_recipient_list(mock_db, c)
        assert len(result) == 2

    def test_with_category_filter(self, mock_db):
        mock_db.fetch_all.return_value = [_person_row(category="diplomat")]
        c = _campaign(target_filter=json.dumps({"category": "diplomat"}))
        result = build_recipient_list(mock_db, c)
        assert len(result) == 1

    def test_malformed_filter_treated_as_empty(self, mock_db):
        mock_db.fetch_all.return_value = [_person_row()]
        c = _campaign(target_filter="NOT_JSON{{{")
        result = build_recipient_list(mock_db, c)
        assert len(result) == 1  # Doesn't crash — falls back to no filter


# ── prepare_recipient_drafts ───────────────────────────────────────────────────

class TestPrepareRecipientDrafts:
    def test_assigns_tone_per_person(self):
        db = MagicMock()
        c = _campaign(tone_professional_percent=100, tone_semi_casual_percent=0, tone_casual_percent=0)
        persons = [_person(), _person(id=2, email="bob@ex.com")]
        result = prepare_recipient_drafts(db, c, persons)
        assert len(result) == 2
        # With 100% professional, every person gets professional
        assert all(rd.tone == "professional" for rd in result)

    def test_preferred_tone_override(self):
        db = MagicMock()
        c = _campaign()
        persons = [_person(preferred_tone="casual")]
        result = prepare_recipient_drafts(db, c, persons)
        assert result[0].tone == "casual"

    def test_returns_recipient_draft_objects(self):
        db = MagicMock()
        c = _campaign()
        result = prepare_recipient_drafts(db, c, [_person()])
        assert isinstance(result[0], RecipientDraft)
        assert result[0].validated is False
        assert result[0].draft is None

    def test_empty_recipients(self):
        db = MagicMock()
        c = _campaign()
        assert prepare_recipient_drafts(db, c, []) == []


# ── submit_draft ───────────────────────────────────────────────────────────────

class TestSubmitDraft:
    def _rd(self, **kw) -> RecipientDraft:
        return RecipientDraft(person=_person(**kw), tone="professional")

    def test_valid_draft_marks_validated(self):
        rd = self._rd()
        body = " ".join(["word"] * 50)
        result = submit_draft(MagicMock(), rd, subject="Test", body=body)
        assert result.validated is True
        assert result.draft is not None
        assert result.draft.subject == "Test"

    def test_emoji_raises_value_error(self):
        rd = self._rd()
        with pytest.raises(ValueError):
            submit_draft(MagicMock(), rd, subject="Test", body="Hello 😀")

    def test_word_limit_enforced(self):
        rd = self._rd()
        body = " ".join(["word"] * 20)
        with pytest.raises(ValueError):
            submit_draft(MagicMock(), rd, subject="Test", body=body, max_words=10)

    def test_empty_subject_raises(self):
        rd = self._rd()
        with pytest.raises(ValueError):
            submit_draft(MagicMock(), rd, subject="", body="Valid body text here")


# ── run_send_phase ─────────────────────────────────────────────────────────────

class TestRunSendPhase:
    def _validated_rd(self) -> RecipientDraft:
        from services.message_validator import Draft
        rd = RecipientDraft(person=_person(), tone="professional")
        rd.draft = Draft(
            person_id=1, subject="Test", body="Hello world.",
            tone="professional",
        )
        rd.validated = True
        return rd

    def test_yields_send_results(self, mock_db):
        from services.sender_queue import SendResult
        c = _campaign()
        rds = [self._validated_rd()]

        fake_result = SendResult(
            person_id=1,
            email="jane@example.com",
            status="sent",
            resend_message_id="msg_ok",
        )

        with patch("services.campaign_service.dispatch", return_value=iter([fake_result])):
            gen = run_send_phase(mock_db, c, rds, "re_key", "from@test.com")
            results = list(gen)

        assert len(results) == 1
        assert results[0].status == "sent"

    def test_failed_send_counted(self, mock_db):
        from services.sender_queue import SendResult
        mock_db.fetch_one.return_value = _camp_row()
        mock_db.execute.return_value = 1

        fail_result = SendResult(
            person_id=1,
            email="jane@example.com",
            status="failed",
            error_message="invalid_to",
        )

        with patch("services.campaign_service.dispatch", return_value=iter([fail_result])):
            gen = run_send_phase(
                mock_db, _campaign(), [self._validated_rd()],
                "re_key", "from@test.com",
            )
            results = list(gen)

        assert any(r.status == "failed" for r in results)

    def test_skipped_rd_logs_to_db(self, mock_db):
        c = _campaign()
        rd = RecipientDraft(person=_person(), tone="professional")
        rd.skipped = True
        rd.skip_reason = "Operator skipped"

        with patch("services.campaign_service.dispatch", return_value=iter([])):
            gen = run_send_phase(mock_db, c, [rd], "re_key", "from@test.com")
            list(gen)

        # Should INSERT a 'skipped' record into message_log
        insert_calls = [
            call for call in mock_db.execute.call_args_list
            if "INSERT INTO message_log" in str(call)
        ]
        assert len(insert_calls) == 1

    def test_marks_campaign_completed(self, mock_db):
        c = _campaign()
        with patch("services.campaign_service.dispatch", return_value=iter([])):
            gen = run_send_phase(mock_db, c, [], "re_key", "from@test.com")
            list(gen)
        completed_calls = [
            call for call in mock_db.execute.call_args_list
            if "completed" in str(call)
        ]
        assert len(completed_calls) >= 1


# ── abort_campaign ─────────────────────────────────────────────────────────────

class TestAbortCampaign:
    def test_updates_status(self, mock_db):
        abort_campaign(mock_db, 1)
        sql = mock_db.execute.call_args[0][0]
        assert "aborted" in sql
        assert "in_progress" in sql


# ── history queries ────────────────────────────────────────────────────────────

class TestHistoryQueries:
    def _log_row(self):
        return {
            "id": 1, "campaign_id": 1, "campaign_name": "Q3",
            "subject": "Hello", "tone_used": "professional",
            "status": "sent", "sent_at": datetime(2026, 1, 1),
            "word_count": 50,
        }

    def test_history_for_person(self, mock_db):
        mock_db.fetch_all.return_value = [self._log_row()]
        result = history_for_person(mock_db, person_id=1)
        assert len(result) == 1
        sql = mock_db.fetch_all.call_args[0][0]
        assert "person_id" in sql

    def test_history_for_campaign(self, mock_db):
        mock_db.fetch_all.return_value = [self._log_row()]
        result = history_for_campaign(mock_db, campaign_id=1)
        assert len(result) == 1
        sql = mock_db.fetch_all.call_args[0][0]
        assert "campaign_id" in sql

    def test_history_failed(self, mock_db):
        mock_db.fetch_all.return_value = [self._log_row()]
        result = history_failed(mock_db)
        assert len(result) == 1
        sql = mock_db.fetch_all.call_args[0][0]
        assert "failed" in sql

    def test_history_by_date_range(self, mock_db):
        mock_db.fetch_all.return_value = [self._log_row()]
        result = history_by_date_range(mock_db, "2026-01-01", "2026-12-31")
        assert len(result) == 1
        sql = mock_db.fetch_all.call_args[0][0]
        assert "BETWEEN" in sql

    def test_history_empty(self, mock_db):
        mock_db.fetch_all.return_value = []
        assert history_for_person(mock_db, 1) == []
        assert history_for_campaign(mock_db, 1) == []
        assert history_failed(mock_db) == []
