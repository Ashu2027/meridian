"""
tests/test_mcp_server.py
Unit tests for MCP stdio server tool handlers, resource handlers, and prompt handlers.
"""
from __future__ import annotations

import json
from datetime import datetime
import pytest
from unittest.mock import MagicMock, patch

import sys
import importlib.util
from pathlib import Path

project_root = str(Path(__file__).parent.parent)
paths_removed = [p for p in sys.path if Path(p).resolve() == Path(project_root).resolve() or p in ("", ".")]
for p in paths_removed:
    sys.path.remove(p)

import mcp.server
import mcp.types

for p in paths_removed:
    sys.path.insert(0, p)

_mcp_server_path = Path(project_root) / "mcp" / "mcp_server.py"
_spec = importlib.util.spec_from_file_location("mcp_server_app", _mcp_server_path)
assert _spec is not None
assert _spec.loader is not None
mcp_server: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mcp_server)

from services.person_service import Person
from services.tone_engine import ToneSplit
from services.campaign_service import Campaign, RecipientDraft
from typing import Any


@pytest.fixture
def mock_mcp_db(mock_db, cfg):
    """Inject mock_db and cfg into mcp_server global state."""
    with patch.object(mcp_server, "_db", mock_db), patch.object(mcp_server, "_cfg", cfg):
        yield mock_db


@pytest.mark.asyncio
async def test_list_tools():
    res = await mcp_server.list_tools()
    assert len(res.tools) == 13
    names = {t.name for t in res.tools}
    assert "person_add" in names
    assert "campaign_send" in names


@pytest.mark.asyncio
async def test_list_resources():
    res = await mcp_server.list_resources()
    assert len(res.resources) == 3
    uris = {str(r.uri) for r in res.resources}
    assert "meridian://tone-settings/active" in uris


@pytest.mark.asyncio
async def test_handle_prompts():
    prompts = await mcp_server.handle_list_prompts()
    assert len(prompts) == 1
    assert prompts[0].name == "meridian-agent"

    prompt_res = await mcp_server.handle_get_prompt("meridian-agent", {})
    assert len(prompt_res.messages) == 1

    with pytest.raises(ValueError, match="Unknown prompt"):
        await mcp_server.handle_get_prompt("unknown-prompt", {})


@pytest.mark.asyncio
async def test_read_resources(mock_mcp_db):
    mock_split = ToneSplit(id=1, professional=40, semi_casual=40, casual=20, is_active=True, note="test")
    with patch("services.tone_engine.get_active_split", return_value=mock_split):
        res = await mcp_server.read_resource("meridian://tone-settings/active")
        data = json.loads(res.contents[0].text)
        assert data["professional_percent"] == 40

    mock_mcp_db.fetch_all.return_value = [{"category": "tech_founder", "standard_title": "CEO"}]
    res2 = await mcp_server.read_resource("meridian://designation-catalog")
    data2 = json.loads(res2.contents[0].text)
    assert "tech_founder" in data2

    mock_mcp_db.fetch_all.return_value = [{"id": 1, "full_name": "Alice"}]
    res3 = await mcp_server.read_resource("meridian://persons/recent")
    data3 = json.loads(res3.contents[0].text)
    assert data3[0]["full_name"] == "Alice"

    with pytest.raises(ValueError, match="Unknown resource"):
        await mcp_server.read_resource("meridian://unknown")


@pytest.mark.asyncio
async def test_db_required_raises():
    with patch.object(mcp_server, "_db", None):
        with pytest.raises(RuntimeError, match="Database not initialised"):
            mcp_server._db_required()


@pytest.mark.asyncio
async def test_call_tool_person_add(mock_mcp_db):
    mock_person = Person(
        id=1, full_name="John Doe", email="john@example.com",
        designation="CEO", category="tech_founder", organization="Acme",
        country="USA", preferred_tone="professional", notes="test",
        status="active", created_at=datetime.now(), updated_at=datetime.now()
    )
    with patch("services.person_service.add_person", return_value=mock_person):
        res = await mcp_server.call_tool("person_add", {
            "full_name": "John Doe", "email": "john@example.com",
            "designation": "CEO", "category": "tech_founder"
        })
        data = json.loads(res.content[0].text)
        assert data["ok"] is True
        assert data["id"] == 1


@pytest.mark.asyncio
async def test_call_tool_person_search(mock_mcp_db):
    mock_person = Person(
        id=1, full_name="John Doe", email="john@example.com",
        designation="CEO", category="tech_founder", organization=None,
        country=None, preferred_tone="professional", notes=None,
        status="active", created_at=datetime.now(), updated_at=datetime.now()
    )
    with patch("services.person_service.search_persons", return_value=[mock_person]):
        res = await mcp_server.call_tool("person_search", {"query": "John"})
        data = json.loads(res.content[0].text)
        assert data["ok"] is True
        assert data["count"] == 1


@pytest.mark.asyncio
async def test_call_tool_person_update(mock_mcp_db):
    mock_person = Person(
        id=1, full_name="John Updated", email="john@example.com",
        designation="CTO", category="tech_founder", organization=None,
        country=None, preferred_tone="casual", notes=None,
        status="active", created_at=datetime.now(), updated_at=datetime.now()
    )
    with patch("services.person_service.update_person", return_value=mock_person):
        res = await mcp_server.call_tool("person_update", {"person_id": 1, "changes": {"designation": "CTO"}})
        data = json.loads(res.content[0].text)
        assert data["ok"] is True
        assert data["full_name"] == "John Updated"


@pytest.mark.asyncio
async def test_call_tool_person_set_status(mock_mcp_db):
    with patch("services.person_service.set_status") as mock_set:
        res = await mcp_server.call_tool("person_set_status", {"person_id": 1, "new_status": "archived"})
        data = json.loads(res.content[0].text)
        assert data["ok"] is True
        mock_set.assert_called_once_with(mock_mcp_db, 1, "archived")


@pytest.mark.asyncio
async def test_call_tool_person_import_csv(mock_mcp_db):
    mock_res = MagicMock(created=5, skipped=1, errors=[])
    with patch("services.person_service.import_csv", return_value=mock_res):
        res = await mcp_server.call_tool("person_import_csv", {"file_path": "test.csv"})
        data = json.loads(res.content[0].text)
        assert data["ok"] is True
        assert data["created"] == 5


@pytest.mark.asyncio
async def test_call_tool_tone_get_and_set(mock_mcp_db):
    mock_split = ToneSplit(id=1, professional=50, semi_casual=30, casual=20, is_active=True, note="split")
    with patch("services.tone_engine.get_active_split", return_value=mock_split):
        res = await mcp_server.call_tool("tone_get", {})
        data = json.loads(res.content[0].text)
        assert data["ok"] is True
        assert data["professional_percent"] == 50

    with patch("services.tone_engine.save_split", return_value=mock_split):
        res2 = await mcp_server.call_tool("tone_set", {"professional": 50, "semi_casual": 30, "casual": 20})
        data2 = json.loads(res2.content[0].text)
        assert data2["ok"] is True


@pytest.mark.asyncio
async def test_call_tool_campaign_create(mock_mcp_db):
    mock_camp = Campaign(
        id=10, name="Launch", topic_brief="Brief", target_filter=None,
        tone_professional=50, tone_semi_casual=30, tone_casual=20,
        total_recipients=1, total_sent=0, total_failed=0,
        status="draft", created_at=datetime.now(), completed_at=None
    )
    with patch("services.campaign_service.create_campaign", return_value=mock_camp):
        res = await mcp_server.call_tool("campaign_create", {"name": "Launch", "topic_brief": "Brief"})
        data = json.loads(res.content[0].text)
        assert data["ok"] is True
        assert data["id"] == 10


@pytest.mark.asyncio
async def test_call_tool_campaign_recipients(mock_mcp_db):
    mock_camp = Campaign(
        id=10, name="Launch", topic_brief="Brief", target_filter=None,
        tone_professional=50, tone_semi_casual=30, tone_casual=20,
        total_recipients=1, total_sent=0, total_failed=0,
        status="draft", created_at=datetime.now(), completed_at=None
    )
    mock_person = Person(
        id=1, full_name="Alice", email="alice@example.com",
        designation="CEO", category="tech_founder", organization="Acme",
        country=None, preferred_tone="casual", notes=None, status="active",
        created_at=datetime.now(), updated_at=datetime.now()
    )
    mock_rd = RecipientDraft(person=mock_person, tone="casual")
    with patch("services.campaign_service.get_campaign", return_value=mock_camp), \
         patch("services.campaign_service.build_recipient_list", return_value=[mock_person]), \
         patch("services.campaign_service.prepare_recipient_drafts", return_value=[mock_rd]):
        res = await mcp_server.call_tool("campaign_recipients", {"campaign_id": 10})
        data = json.loads(res.content[0].text)
        assert data["ok"] is True
        assert len(data["recipients"]) == 1

    with patch("services.campaign_service.get_campaign", return_value=None):
        res2 = await mcp_server.call_tool("campaign_recipients", {"campaign_id": 999})
        assert res2.isError is True


@pytest.mark.asyncio
async def test_call_tool_draft_validate_and_submit(mock_mcp_db):
    res = await mcp_server.call_tool("draft_validate", {
        "person_id": 1, "subject": "Hello", "body": "Short message body.", "tone": "professional"
    })
    data = json.loads(res.content[0].text)
    assert data["ok"] is True

    mock_camp = Campaign(
        id=10, name="Launch", topic_brief="Brief", target_filter=None,
        tone_professional=50, tone_semi_casual=30, tone_casual=20,
        total_recipients=1, total_sent=0, total_failed=0,
        status="draft", created_at=datetime.now(), completed_at=None
    )
    mock_person = Person(
        id=1, full_name="Alice", email="alice@example.com",
        designation="CEO", category="tech_founder", organization=None,
        country=None, preferred_tone="casual", notes=None, status="active",
        created_at=datetime.now(), updated_at=datetime.now()
    )
    with patch("services.campaign_service.get_campaign", return_value=mock_camp), \
         patch("services.person_service.get_person", return_value=mock_person):
        res2 = await mcp_server.call_tool("draft_submit", {
            "campaign_id": 10, "person_id": 1, "subject": "Hello",
            "body": "Valid body message.", "tone": "casual"
        })
        data2 = json.loads(res2.content[0].text)
        assert data2["ok"] is True
        assert data2["status"] == "pending"


@pytest.mark.asyncio
async def test_call_tool_campaign_send(mock_mcp_db):
    res_no_confirm = await mcp_server.call_tool("campaign_send", {"campaign_id": 10, "confirm": False})
    assert res_no_confirm.isError is True

    mock_mcp_db.fetch_all.return_value = []
    res_no_drafts = await mcp_server.call_tool("campaign_send", {"campaign_id": 10, "confirm": True})
    assert res_no_drafts.isError is True

    pending_draft = {
        "person_id": 1, "campaign_id": 10, "recipient_email": "alice@example.com",
        "recipient_name": "Alice", "designation_snapshot": "CEO", "subject": "Hi",
        "message_body": "Body", "word_count": 1, "tone_used": "casual"
    }
    mock_mcp_db.fetch_all.return_value = [pending_draft]
    mock_dispatch_result = MagicMock(status="sent")
    with patch("services.sender_queue.dispatch", return_value=[mock_dispatch_result]):
        res_send = await mcp_server.call_tool("campaign_send", {"campaign_id": 10, "confirm": True})
        data = json.loads(res_send.content[0].text)
        assert data["ok"] is True
        assert data["sent"] == 1


@pytest.mark.asyncio
async def test_call_tool_history_query(mock_mcp_db):
    with patch("services.campaign_service.history_for_person", return_value=[{"id": 1}]):
        res1 = await mcp_server.call_tool("history_query", {"person_id": 1})
        data1 = json.loads(res1.content[0].text)
        assert data1["ok"] is True

    with patch("services.campaign_service.history_for_campaign", return_value=[{"id": 1}]):
        res2 = await mcp_server.call_tool("history_query", {"campaign_id": 10})
        data2 = json.loads(res2.content[0].text)
        assert data2["ok"] is True

    with patch("services.campaign_service.history_by_date_range", return_value=[{"id": 1}]):
        res3 = await mcp_server.call_tool("history_query", {"date_start": "2026-01-01", "date_end": "2026-01-31"})
        data3 = json.loads(res3.content[0].text)
        assert data3["ok"] is True

    res4 = await mcp_server.call_tool("history_query", {})
    assert res4.isError is True


@pytest.mark.asyncio
async def test_call_tool_unknown_and_error(mock_mcp_db):
    res = await mcp_server.call_tool("unknown_tool", {})
    assert res.isError is True

    with patch("services.person_service.add_person", side_effect=ValueError("Invalid email")):
        res_val_err = await mcp_server.call_tool("person_add", {
            "full_name": "x", "email": "bad", "designation": "x", "category": "x"
        })
        assert res_val_err.isError is True
