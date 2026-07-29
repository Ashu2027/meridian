"""
mcp/mcp_server.py
MCP stdio server — exposes the Meridian service layer as native MCP tools.
Compatible with Claude Code, Claude Desktop, and any MCP-capable client.

Run directly:  python mcp/mcp_server.py
Or register in your MCP client config pointing to this file.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

# Add project root to path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult, ListResourcesResult, ListToolsResult,
    ReadResourceResult, Resource, TextContent, Tool,
    Prompt, PromptMessage, GetPromptResult
)

from config import load_config, ConfigMissingError
from db.connection import Database, wait_for_connection
from services import person_service, tone_engine, campaign_service
from services.message_validator import Draft, validate_draft

logger = logging.getLogger(__name__)

# ── App + DB init ──────────────────────────────────────────────────────────────

_server = Server("meridian")
_db: Optional[Database] = None
_cfg = None


async def _init() -> None:
    global _db, _cfg
    try:
        _cfg = load_config()
    except ConfigMissingError as exc:
        logger.error("Meridian not configured: %s", exc)
        sys.exit(2)
    _db = Database(_cfg)
    if not wait_for_connection(_db, retries=3, delay=2.0):
        logger.error("Cannot connect to TiDB.")
        sys.exit(2)


def _db_required() -> Database:
    if _db is None:
        raise RuntimeError("Database not initialised.")
    return _db


# ── Tool definitions ───────────────────────────────────────────────────────────

@_server.list_tools()  # type: ignore
async def list_tools() -> ListToolsResult:
    return ListToolsResult(tools=[
        Tool(name="person_add",         description="Add a new person to the contact database.",
             input_schema={"type": "object", "required": ["full_name", "email", "designation", "category"],
                          "properties": {"full_name": {"type": "string"}, "email": {"type": "string"},
                                         "designation": {"type": "string"}, "category": {"type": "string"},
                                         "organization": {"type": "string"}, "country": {"type": "string"},
                                         "preferred_tone": {"type": "string", "enum": ["auto","professional","semi_casual","casual"]},
                                         "notes": {"type": "string"}}}),
        Tool(name="person_search",      description="Search persons by category, status, or name/email.",
             input_schema={"type": "object", "properties": {"category": {"type": "string"},
                                                            "status": {"type": "string"},
                                                            "query": {"type": "string"}}}),
        Tool(name="person_update",      description="Update a person's fields (not email).",
             input_schema={"type": "object", "required": ["person_id", "changes"],
                          "properties": {"person_id": {"type": "integer"},
                                         "changes": {"type": "object"}}}),
        Tool(name="person_set_status",  description="Change a person's status (active/unsubscribed/bounced/archived).",
             input_schema={"type": "object", "required": ["person_id", "new_status"],
                          "properties": {"person_id": {"type": "integer"},
                                         "new_status": {"type": "string"}}}),
        Tool(name="person_import_csv",  description="Import persons from a CSV file.",
             input_schema={"type": "object", "required": ["file_path"],
                          "properties": {"file_path": {"type": "string"}}}),
        Tool(name="tone_get",           description="Get the currently active tone split.",
             input_schema={"type": "object", "properties": {}}),
        Tool(name="tone_set",           description="Set a new tone split (must sum to 100).",
             input_schema={"type": "object", "required": ["professional", "semi_casual", "casual"],
                          "properties": {"professional": {"type": "integer"},
                                         "semi_casual": {"type": "integer"},
                                         "casual": {"type": "integer"},
                                         "note": {"type": "string"}}}),
        Tool(name="campaign_create",    description="Create a new draft campaign.",
             input_schema={"type": "object", "required": ["name", "topic_brief"],
                          "properties": {"name": {"type": "string"},
                                         "topic_brief": {"type": "string"},
                                         "target_filter": {"type": "object"}}}),
        Tool(name="campaign_recipients",description="Get recipients and their assigned tones for a campaign. Use this to know who to write for.",
             input_schema={"type": "object", "required": ["campaign_id"],
                          "properties": {"campaign_id": {"type": "integer"}}}),
        Tool(name="draft_validate",     description="Validate a draft message without storing it. Check word count, emoji, boilerplate.",
             input_schema={"type": "object", "required": ["person_id", "subject", "body", "tone"],
                          "properties": {"person_id": {"type": "integer"},
                                         "subject": {"type": "string"},
                                         "body": {"type": "string"},
                                         "tone": {"type": "string"}}}),
        Tool(name="draft_submit",       description="Submit a validated agent-written draft for operator review.",
             input_schema={"type": "object", "required": ["campaign_id", "person_id", "subject", "body", "tone"],
                          "properties": {"campaign_id": {"type": "integer"},
                                         "person_id": {"type": "integer"},
                                         "subject": {"type": "string"},
                                         "body": {"type": "string"},
                                         "tone": {"type": "string"},
                                         "idempotency_key": {"type": "string"}}}),
        Tool(name="campaign_send",      description="Send all pending drafts for a campaign. REQUIRES confirm=true explicitly.",
             input_schema={"type": "object", "required": ["campaign_id", "confirm"],
                          "properties": {"campaign_id": {"type": "integer"},
                                         "confirm": {"type": "boolean"}}}),
        Tool(name="history_query",      description="Query message history by person_id, campaign_id, or date range.",
             input_schema={"type": "object",
                          "properties": {"person_id": {"type": "integer"},
                                         "campaign_id": {"type": "integer"},
                                         "date_start": {"type": "string"},
                                         "date_end": {"type": "string"}}}),
    ])


# ── Tool handler ───────────────────────────────────────────────────────────────

@_server.call_tool()  # type: ignore
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    db = _db_required()

    def _text(data: Any) -> CallToolResult:
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, default=str))])

    def _err(code: str, msg: str) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text",
                                 text=json.dumps({"ok": False, "error": {"code": code, "message": msg}}))],
            isError=True,
        )

    try:
        # ── Persons ────────────────────────────────────────────────────────────
        if name == "person_add":
            p_input = person_service.PersonInput(
                full_name=str(arguments["full_name"]),
                email=str(arguments["email"]),
                designation=str(arguments["designation"]),
                category=str(arguments["category"]),
                organization=str(arguments["organization"]) if "organization" in arguments else None,
                country=str(arguments["country"]) if "country" in arguments else None,
                preferred_tone=str(arguments["preferred_tone"]) if "preferred_tone" in arguments else None,
                notes=str(arguments["notes"]) if "notes" in arguments else None
            )
            p = person_service.add_person(db, p_input)
            return _text({"ok": True, "id": p.id, "full_name": p.full_name, "email": p.email})

        elif name == "person_search":
            persons = person_service.search_persons(
                db,
                category=arguments.get("category"),
                status=arguments.get("status"),
                query=arguments.get("query"),
            )
            return _text({"ok": True, "count": len(persons), "persons": [
                {"id": p.id, "full_name": p.full_name, "email": p.email,
                 "designation": p.designation, "category": p.category,
                 "tone": p.preferred_tone, "status": p.status}
                for p in persons
            ]})

        elif name == "person_update":
            p = person_service.update_person(db, arguments["person_id"], arguments["changes"])
            return _text({"ok": True, "id": p.id, "full_name": p.full_name})

        elif name == "person_set_status":
            person_service.set_status(db, arguments["person_id"], arguments["new_status"])
            return _text({"ok": True, "person_id": arguments["person_id"], "status": arguments["new_status"]})

        elif name == "person_import_csv":
            result = person_service.import_csv(db, arguments["file_path"])
            return _text({"ok": True, "created": result.created, "skipped": result.skipped, "errors": result.errors})

        # ── Tone ───────────────────────────────────────────────────────────────
        elif name == "tone_get":
            split = tone_engine.get_active_split(db)
            return _text({"ok": True,
                           "professional_percent": split.professional,
                           "semi_casual_percent": split.semi_casual,
                           "casual_percent": split.casual,
                           "is_active": split.is_active, "note": split.note})

        elif name == "tone_set":
            saved = tone_engine.save_split(
                db, arguments["professional"], arguments["semi_casual"],
                arguments["casual"], arguments.get("note")
            )
            return _text({"ok": True, "id": saved.id,
                           "professional_percent": saved.professional,
                           "semi_casual_percent": saved.semi_casual,
                           "casual_percent": saved.casual})

        # ── Campaign ───────────────────────────────────────────────────────────
        elif name == "campaign_create":
            camp = campaign_service.create_campaign(
                db, name=arguments["name"],
                topic_brief=arguments["topic_brief"],
                target_filter=arguments.get("target_filter"),
            )
            return _text({"ok": True, "id": camp.id, "name": camp.name, "status": camp.status})

        elif name == "campaign_recipients":
            camp = campaign_service.get_campaign(db, arguments["campaign_id"])
            if not camp:
                return _err("CAMPAIGN_NOT_FOUND", f"Campaign #{arguments['campaign_id']} not found.")
            recipients = campaign_service.build_recipient_list(db, camp)
            rds = campaign_service.prepare_recipient_drafts(db, camp, recipients)
            return _text({"ok": True, "campaign": camp.name, "topic_brief": camp.topic_brief,
                           "recipients": [
                               {"person_id": rd.person.id, "full_name": rd.person.full_name,
                                "email": rd.person.email, "designation": rd.person.designation,
                                "category": rd.person.category, "tone": rd.tone,
                                "organization": rd.person.organization}
                               for rd in rds
                           ]})

        elif name == "draft_validate":
            max_words = int(db.get_config_value("max_words_per_message", "200"))
            result = validate_draft(
                Draft(person_id=arguments["person_id"], subject=arguments["subject"],
                      body=arguments["body"], tone=arguments["tone"]),
                max_words,
            )
            return _text({"ok": result.valid, "valid": result.valid,
                           "word_count": result.word_count, "violations": result.violations})

        elif name == "draft_submit":
            max_words = int(db.get_config_value("max_words_per_message", "200"))
            d = Draft(person_id=arguments["person_id"], subject=arguments["subject"],
                      body=arguments["body"], tone=arguments["tone"],
                      idempotency_key=arguments.get("idempotency_key"))
            result = validate_draft(d, max_words)
            if not result.valid:
                return _err("DRAFT_INVALID",
                             "Violations: " + " | ".join(result.violations))
            camp = campaign_service.get_campaign(db, arguments["campaign_id"])
            p = person_service.get_person(db, arguments["person_id"])
            if not camp or not p:
                return _err("NOT_FOUND", "Campaign or person not found.")
            log_id = db.execute(
                "INSERT INTO message_log (campaign_id, person_id, recipient_email, recipient_name, "
                "designation_snapshot, subject, message_body, word_count, tone_used, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
                (camp.id, p.id, p.email, p.full_name, p.designation,
                 arguments["subject"], arguments["body"], result.word_count, arguments["tone"]),
            )
            return _text({"ok": True, "log_id": log_id, "status": "pending",
                           "word_count": result.word_count})

        elif name == "campaign_send":
            if not arguments.get("confirm", False):
                return _err("CONFIRM_REQUIRED",
                             "campaign_send requires confirm=true explicitly in every call.")
            pending_logs = db.fetch_all(
                "SELECT * FROM message_log WHERE campaign_id = %s AND status = 'pending'",
                (arguments["campaign_id"],),
            )
            if not pending_logs:
                return _err("NO_PENDING_DRAFTS", "No pending drafts for this campaign.")

            from services.sender_queue import ApprovedDraft, dispatch
            approved = [ApprovedDraft(
                person_id=l["person_id"], campaign_id=l["campaign_id"],
                recipient_email=l["recipient_email"], recipient_name=l["recipient_name"],
                designation_snapshot=l["designation_snapshot"], subject=l["subject"],
                body=l["message_body"], word_count=l["word_count"], tone_used=l["tone_used"],
            ) for l in pending_logs]
            db.execute(
                "DELETE FROM message_log WHERE campaign_id = %s AND status = 'pending'",
                (arguments["campaign_id"],),
            )
            rate = int(db.get_config_value("send_rate_per_minute", "20"))
            assert _cfg is not None
            from_addr = f"{_cfg.default_from_name} <{_cfg.default_from_email}>"
            sent = failed = 0
            for r in dispatch(db, approved, _cfg.resend_api_key, from_addr, rate):
                if r.status == "sent": sent += 1
                else: failed += 1
            return _text({"ok": True, "campaign_id": arguments["campaign_id"],
                           "sent": sent, "failed": failed})

        elif name == "history_query":
            if "person_id" in arguments:
                logs = campaign_service.history_for_person(db, arguments["person_id"])
            elif "campaign_id" in arguments:
                logs = campaign_service.history_for_campaign(db, arguments["campaign_id"])
            elif "date_start" in arguments:
                logs = campaign_service.history_by_date_range(
                    db, arguments["date_start"], arguments["date_end"]
                )
            else:
                return _err("MISSING_FILTER", "Provide person_id, campaign_id, or date range.")
            serialised = [{k: str(v) if hasattr(v, "isoformat") else v for k, v in row.items()} for row in logs]
            return _text({"ok": True, "count": len(serialised), "logs": serialised})

        else:
            return _err("UNKNOWN_TOOL", f"Unknown tool: {name!r}")

    except ValueError as exc:
        return _err("VALIDATION_ERROR", str(exc))
    except Exception as exc:
        logger.exception("Tool %r failed", name)
        return _err("INTERNAL_ERROR", str(exc))


# ── Resources ──────────────────────────────────────────────────────────────────

@_server.list_resources()  # type: ignore
async def list_resources() -> ListResourcesResult:
    return ListResourcesResult(resources=[
        Resource(uri="meridian://tone-settings/active",
                 name="Active Tone Split",
                 description="Current tone split percentages.",
                 mimeType="application/json"),
        Resource(uri="meridian://designation-catalog",
                 name="Designation Catalog",
                 description="Standardized designation titles for all categories.",
                 mimeType="application/json"),
        Resource(uri="meridian://persons/recent",
                 name="Recent Persons",
                 description="10 most recently added or updated persons.",
                 mimeType="application/json"),
    ])


@_server.read_resource()  # type: ignore
async def read_resource(uri: str) -> ReadResourceResult:
    db = _db_required()

    if uri == "meridian://tone-settings/active":
        split = tone_engine.get_active_split(db)
        data = {"professional_percent": split.professional,
                "semi_casual_percent": split.semi_casual,
                "casual_percent": split.casual, "note": split.note}
        return ReadResourceResult(contents=[TextContent(type="text", text=json.dumps(data))])

    elif uri == "meridian://designation-catalog":
        rows = db.fetch_all("SELECT category, standard_title FROM designation_catalog ORDER BY category, standard_title")
        by_cat: dict = {}
        for r in rows:
            by_cat.setdefault(r["category"], []).append(r["standard_title"])
        return ReadResourceResult(contents=[TextContent(type="text", text=json.dumps(by_cat))])

    elif uri == "meridian://persons/recent":
        rows = db.fetch_all(
            "SELECT id, full_name, email, designation, category, status "
            "FROM persons ORDER BY updated_at DESC LIMIT 10"
        )
        return ReadResourceResult(contents=[TextContent(type="text", text=json.dumps(rows, default=str))])

    raise ValueError(f"Unknown resource: {uri}")


# ── Prompts (System Instructions for AI) ───────────────────────────────────────

@_server.list_prompts()  # type: ignore
async def handle_list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name="meridian-agent",
            description="Default system instructions and guidelines for the Meridian AI agent.",
            arguments=[]
        )
    ]

@_server.get_prompt()  # type: ignore
async def handle_get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
    if name != "meridian-agent":
        raise ValueError(f"Unknown prompt: {name}")

    prompt_file = Path(__file__).parent.parent / "SYSTEM_PROMPT.md"
    content = "You are the Meridian AI Agent."
    if prompt_file.exists():
        content = prompt_file.read_text(encoding="utf-8")

    return GetPromptResult(
        description="Meridian system instructions",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=content
                )
            )
        ]
    )

# ── Main ───────────────────────────────────────────────────────────────────────

async def main() -> None:
    await _init()
    async with stdio_server() as (read_stream, write_stream):
        await _server.run(read_stream, write_stream, _server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
