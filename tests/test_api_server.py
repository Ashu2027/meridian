"""
tests/test_api_server.py
Integration tests for the FastAPI server endpoints.
Uses TestClient (no real DB or Resend calls — all mocked).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from config import AppConfig


def _make_cfg() -> AppConfig:
    return AppConfig(
        tidb_host="localhost", tidb_port=4000,
        tidb_user="test", tidb_password="test",
        tidb_database="meridian_test", tidb_use_tls=False,
        resend_api_key="re_testkey", default_from_name="Test",
        default_from_email="test@example.com",
        api_secret_token="valid-token-1234",
        api_host="127.0.0.1", api_port=8765,
    )


def _make_person_row(**kwargs):
    defaults = {
        "id": 1, "full_name": "Jane Whitmore", "email": "jane@example.com",
        "designation": "Managing Editor", "category": "journalist",
        "organization": None, "country": None, "preferred_tone": "auto",
        "notes": None, "status": "active",
        "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1),
    }
    defaults.update(kwargs)
    return defaults


@pytest.fixture
def client():
    """
    Return a TestClient with the lifespan bypassed.
    patch() context managers are entered BEFORE TestClient.__enter__ so the
    lifespan never hits the real filesystem or network.
    FastAPI dependency_overrides injects mock_db into every route handler.
    """
    mock_db = MagicMock()
    mock_db.fetch_one.return_value = None
    mock_db.fetch_all.return_value = []
    mock_db.execute.return_value = 1
    mock_db.ping.return_value = True
    mock_db.get_config_value.return_value = "200"

    cfg = _make_cfg()

    from api.server import app, get_db

    # Override FastAPI dependency so every route handler gets mock_db
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("api.server.load_config", return_value=cfg), \
         patch("api.server.wait_for_connection", return_value=True):
        with TestClient(app, raise_server_exceptions=False) as c:
            # Fix module-level globals so the Bearer token check works
            import api.server as srv
            srv._cfg = cfg
            srv._db = mock_db
            c.mock_db = mock_db
            yield c

    app.dependency_overrides.clear()


HEADERS = {"Authorization": "Bearer valid-token-1234"}


class TestAuth:
    def test_no_token_returns_401(self, client):
        response = client.post("/person/search", json={})
        assert response.status_code == 401

    def test_wrong_token_returns_401(self, client):
        response = client.post("/person/search", json={}, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401

    def test_valid_token_accepted(self, client):
        response = client.post("/person/search", json={}, headers=HEADERS)
        assert response.status_code == 200


class TestHealthEndpoint:
    def test_health_no_auth_required(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestPersonAdd:
    def test_add_person_success(self, client):
        client.mock_db.fetch_one.side_effect = [None, _make_person_row()]
        client.mock_db.execute.return_value = 1

        response = client.post("/person/add", headers=HEADERS, json={
            "full_name": "Jane Whitmore",
            "email": "jane@example.com",
            "designation": "Managing Editor",
            "category": "journalist",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["result"]["full_name"] == "Jane Whitmore"

    def test_add_person_duplicate_email(self, client):
        client.mock_db.fetch_one.return_value = {"id": 1}  # duplicate

        response = client.post("/person/add", headers=HEADERS, json={
            "full_name": "Jane", "email": "jane@example.com",
            "designation": "Editor", "category": "journalist",
        })
        assert response.status_code == 400

    def test_add_person_invalid_category(self, client):
        client.mock_db.fetch_one.return_value = None

        response = client.post("/person/add", headers=HEADERS, json={
            "full_name": "Jane", "email": "jane@example.com",
            "designation": "Editor", "category": "INVALID",
        })
        assert response.status_code == 400


class TestPersonSearch:
    def test_search_returns_list(self, client):
        client.mock_db.fetch_all.return_value = [_make_person_row()]

        response = client.post("/person/search", headers=HEADERS, json={"status": "active"})
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert len(body["result"]) == 1

    def test_search_empty_returns_ok(self, client):
        client.mock_db.fetch_all.return_value = []
        response = client.post("/person/search", headers=HEADERS, json={})
        assert response.status_code == 200
        assert response.json()["result"] == []


class TestToneEndpoints:
    def test_tone_get(self, client):
        client.mock_db.fetch_one.return_value = {
            "id": 1, "professional_percent": 60, "semi_casual_percent": 30,
            "casual_percent": 10, "is_active": True, "updated_by_note": None,
        }
        response = client.get("/tone", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()["result"]
        assert data["professional_percent"] == 60

    def test_tone_set_valid(self, client):
        client.mock_db.execute.return_value = 5
        response = client.post("/tone/set", headers=HEADERS, json={
            "professional": 50, "semi_casual": 30, "casual": 20, "note": "test"
        })
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_tone_set_invalid_sum(self, client):
        response = client.post("/tone/set", headers=HEADERS, json={
            "professional": 50, "semi_casual": 30, "casual": 15
        })
        assert response.status_code == 400


class TestDraftValidate:
    def test_valid_draft(self, client):
        body = " ".join(["word"] * 50)
        response = client.post("/campaign/draft/validate", headers=HEADERS, json={
            "campaign_id": 1, "person_id": 1,
            "subject": "Test subject",
            "body": body, "tone": "professional",
        })
        assert response.status_code == 200
        assert response.json()["result"]["valid"] is True

    def test_draft_with_emoji_invalid(self, client):
        response = client.post("/campaign/draft/validate", headers=HEADERS, json={
            "campaign_id": 1, "person_id": 1,
            "subject": "Test", "body": "Hello 😀 world", "tone": "professional",
        })
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["valid"] is False
        assert len(result["violations"]) > 0

    def test_draft_over_word_limit(self, client):
        client.mock_db.get_config_value.return_value = "50"
        body = " ".join(["word"] * 60)
        response = client.post("/campaign/draft/validate", headers=HEADERS, json={
            "campaign_id": 1, "person_id": 1,
            "subject": "Test", "body": body, "tone": "professional",
        })
        assert response.status_code == 200
        assert response.json()["result"]["valid"] is False


class TestCampaignSendGuardrail:
    def test_send_without_confirm_fails(self, client):
        response = client.post("/campaign/send", headers=HEADERS, json={
            "campaign_id": 1, "confirm": False
        })
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error"]["code"] == "CONFIRM_REQUIRED"

    def test_send_with_confirm_true_proceeds(self, client):
        # confirm=True passes the guardrail — next failure is CAMPAIGN_NOT_FOUND (fetch_one=None)
        # The point is it must NOT return CONFIRM_REQUIRED
        client.mock_db.fetch_one.return_value = None   # campaign not found
        client.mock_db.fetch_all.return_value = []
        response = client.post("/campaign/send", headers=HEADERS, json={
            "campaign_id": 999, "confirm": True
        })
        # Response should be a valid JSON 400, not a CONFIRM_REQUIRED error
        assert response.status_code in (400, 404)
        body = response.json()
        error_code = body.get("detail", {}).get("error", {}).get("code", "")
        assert error_code != "CONFIRM_REQUIRED"


class TestPersonUpdate:
    def test_update_success(self, client):
        client.mock_db.execute.return_value = 1
        client.mock_db.fetch_one.return_value = _make_person_row(full_name="Jane Updated")

        response = client.post("/person/update", headers=HEADERS, json={
            "person_id": 1, "changes": {"full_name": "Jane Updated"}
        })
        assert response.status_code == 200
        assert response.json()["result"]["full_name"] == "Jane Updated"

    def test_update_invalid_fields_returns_400(self, client):
        response = client.post("/person/update", headers=HEADERS, json={
            "person_id": 1, "changes": {"email": "hacker@evil.com"}
        })
        assert response.status_code == 400

    def test_set_status_success(self, client):
        client.mock_db.fetch_one.return_value = _make_person_row(status="unsubscribed")
        response = client.post("/person/set_status", headers=HEADERS, json={
            "person_id": 1, "new_status": "unsubscribed"
        })
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_set_status_invalid_returns_400(self, client):
        client.mock_db.fetch_one.return_value = _make_person_row()
        response = client.post("/person/set_status", headers=HEADERS, json={
            "person_id": 1, "new_status": "deleted"
        })
        assert response.status_code == 400

    def test_get_person_by_id(self, client):
        client.mock_db.fetch_one.return_value = _make_person_row()
        response = client.get("/person/1", headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["result"]["id"] == 1

    def test_get_person_not_found(self, client):
        client.mock_db.fetch_one.return_value = None
        response = client.get("/person/999", headers=HEADERS)
        assert response.status_code == 404


class TestCampaignCreate:
    def _tone_row(self):
        return {
            "id": 1, "professional_percent": 60, "semi_casual_percent": 30,
            "casual_percent": 10, "is_active": True, "updated_by_note": None,
        }

    def _camp_row(self):
        return {
            "id": 1, "name": "Q3 Outreach", "topic_brief": "Q3 results",
            "target_filter": None, "tone_professional_percent": 60,
            "tone_semi_casual_percent": 30, "tone_casual_percent": 10,
            "total_recipients": 0, "total_sent": 0, "total_failed": 0,
            "status": "draft", "created_at": datetime(2026, 1, 1), "completed_at": None,
        }

    def test_create_success(self, client):
        client.mock_db.fetch_one.side_effect = [self._tone_row(), self._camp_row()]
        client.mock_db.execute.return_value = 1

        response = client.post("/campaign/create", headers=HEADERS, json={
            "name": "Q3 Outreach", "topic_brief": "Q3 results"
        })
        assert response.status_code == 200
        assert response.json()["result"]["name"] == "Q3 Outreach"

    def test_create_empty_name_returns_400(self, client):
        client.mock_db.fetch_one.return_value = self._tone_row()
        response = client.post("/campaign/create", headers=HEADERS, json={
            "name": "", "topic_brief": "Brief"
        })
        assert response.status_code == 400


class TestHistoryEndpoints:
    def _log_row(self):
        return {
            "id": 1, "campaign_id": 1, "campaign_name": "Q3",
            "subject": "Hello", "tone_used": "professional",
            "status": "sent", "sent_at": datetime(2026, 1, 1),
            "word_count": 50, "full_name": "Jane",
        }

    def test_history_query_by_person(self, client):
        client.mock_db.fetch_all.return_value = [self._log_row()]
        response = client.post("/history/query", headers=HEADERS, json={"person_id": 1})
        assert response.status_code == 200
        assert len(response.json()["result"]) == 1

    def test_history_query_by_campaign(self, client):
        client.mock_db.fetch_all.return_value = [self._log_row()]
        response = client.post("/history/query", headers=HEADERS, json={"campaign_id": 1})
        assert response.status_code == 200

    def test_history_query_missing_filter(self, client):
        response = client.post("/history/query", headers=HEADERS, json={})
        assert response.status_code == 400

    def test_catalog_designations(self, client):
        response = client.get("/catalog/designations", headers=HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert "result" in body
        # The endpoint returns a catalog dict with category/titles keys OR a list of dicts
        result = body["result"]
        assert result is not None

