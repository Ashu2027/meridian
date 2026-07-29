"""
api/server.py
FastAPI server — the agent-facing REST interface for Meridian.
Any CLI agent (Claude Code, Antigravity, etc.) can call this to:
  - Manage persons
  - Configure tone splits
  - Create campaigns and submit agent-drafted messages
  - Trigger sends (only with explicit confirm=true)
  - Query history

Authentication: Bearer token from AppConfig.api_secret_token
All responses follow the standard envelope: {ok, action, result, error}
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from config import AppConfig, load_config, ConfigMissingError
from db.connection import Database, wait_for_connection
from services import person_service, tone_engine, campaign_service
from services.message_validator import Draft, validate_draft

logger = logging.getLogger(__name__)

# ── App state ──────────────────────────────────────────────────────────────────

_db: Optional[Database] = None
_cfg: Optional[AppConfig] = None
# Rate ceiling: max campaign-send calls per hour per API client (Section 17.6)
_send_call_timestamps: list[float] = []
_MAX_SENDS_PER_HOUR = 10

# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db, _cfg
    try:
        _cfg = load_config()
    except ConfigMissingError:
        raise RuntimeError("Meridian is not configured. Run `python main.py` to complete setup.")
    _db = Database(_cfg)
    if not wait_for_connection(_db, retries=3, delay=2.0):
        raise RuntimeError("Cannot connect to TiDB. Check your configuration.")
    logger.info("Meridian API server started.")
    yield
    logger.info("Meridian API server shutting down.")


app = FastAPI(
    title="Meridian API",
    description=(
        "Agent-facing REST interface for Meridian email outreach system. "
        "Agents generate content; Meridian validates and sends."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── Auth ───────────────────────────────────────────────────────────────────────

bearer_scheme = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    if _cfg is None or credentials.credentials != _cfg.api_secret_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Bearer token.",
        )
    return credentials.credentials


# ── Response envelope ──────────────────────────────────────────────────────────

def ok_response(action: str, result: Any) -> dict:
    return {"ok": True, "action": action, "result": result, "error": None}


def err_response(action: str, code: str, message: str, http_status: int = 400):
    raise HTTPException(
        status_code=http_status,
        detail={"ok": False, "action": action, "result": None,
                "error": {"code": code, "message": message}},
    )


def get_db() -> Database:
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready.")
    return _db


# ── Request models ─────────────────────────────────────────────────────────────

class PersonAddRequest(BaseModel):
    full_name: str
    email: str
    designation: str
    category: str
    organization: Optional[str] = None
    country: Optional[str] = None
    preferred_tone: str = "auto"
    notes: Optional[str] = None
    idempotency_key: Optional[str] = None


class PersonSearchRequest(BaseModel):
    category: Optional[str] = None
    status: Optional[str] = None
    query: Optional[str] = None


class PersonUpdateRequest(BaseModel):
    person_id: int
    changes: Dict[str, Any]


class PersonStatusRequest(BaseModel):
    person_id: int
    new_status: str


class ToneSetRequest(BaseModel):
    professional: int
    semi_casual: int
    casual: int
    note: Optional[str] = None


class CampaignCreateRequest(BaseModel):
    name: str
    topic_brief: str
    target_filter: Optional[Dict[str, Any]] = None
    idempotency_key: Optional[str] = None


class DraftSubmitRequest(BaseModel):
    campaign_id: int
    person_id: int
    subject: str
    body: str
    tone: str
    idempotency_key: Optional[str] = None


class CampaignSendRequest(BaseModel):
    campaign_id: int
    confirm: bool = False          # Must be explicitly true — no implicit sends


class HistoryQueryRequest(BaseModel):
    person_id: Optional[int] = None
    campaign_id: Optional[int] = None
    date_start: Optional[str] = None
    date_end: Optional[str] = None


# ── Person endpoints ───────────────────────────────────────────────────────────

@app.post("/person/add", dependencies=[Depends(verify_token)])
def person_add(req: PersonAddRequest, db: Database = Depends(get_db)):
    try:
        person = person_service.add_person(db, person_service.PersonInput(
            full_name=req.full_name, email=req.email,
            designation=req.designation, category=req.category,
            organization=req.organization, country=req.country,
            preferred_tone=req.preferred_tone, notes=req.notes,
        ))
        return ok_response("person-add", {
            "id": person.id, "full_name": person.full_name, "email": person.email,
            "designation": person.designation, "category": person.category,
            "status": person.status,
        })
    except ValueError as exc:
        err_response("person-add", "PERSON_ADD_INVALID", str(exc))


@app.post("/person/search", dependencies=[Depends(verify_token)])
def person_search(req: PersonSearchRequest, db: Database = Depends(get_db)):
    persons = person_service.search_persons(
        db, category=req.category, status=req.status, query=req.query
    )
    return ok_response("person-search", [
        {"id": p.id, "full_name": p.full_name, "email": p.email,
         "designation": p.designation, "category": p.category,
         "preferred_tone": p.preferred_tone, "status": p.status}
        for p in persons
    ])


@app.post("/person/update", dependencies=[Depends(verify_token)])
def person_update(req: PersonUpdateRequest, db: Database = Depends(get_db)):
    try:
        p = person_service.update_person(db, req.person_id, req.changes)
        return ok_response("person-update", {"id": p.id, "full_name": p.full_name})
    except ValueError as exc:
        err_response("person-update", "PERSON_UPDATE_INVALID", str(exc))


@app.post("/person/set_status", dependencies=[Depends(verify_token)])
def person_set_status(req: PersonStatusRequest, db: Database = Depends(get_db)):
    try:
        person_service.set_status(db, req.person_id, req.new_status)
        return ok_response("person-set-status", {"person_id": req.person_id, "status": req.new_status})
    except ValueError as exc:
        err_response("person-set-status", "STATUS_INVALID", str(exc))


@app.get("/person/{person_id}", dependencies=[Depends(verify_token)])
def person_get(person_id: int, db: Database = Depends(get_db)):
    p = person_service.get_person(db, person_id)
    if not p:
        err_response("person-get", "PERSON_NOT_FOUND", f"Person #{person_id} not found.", 404)
    return ok_response("person-get", {
        "id": p.id, "full_name": p.full_name, "email": p.email,
        "designation": p.designation, "category": p.category,
        "organization": p.organization, "country": p.country,
        "preferred_tone": p.preferred_tone, "notes": p.notes, "status": p.status,
    })


# ── Tone endpoints ─────────────────────────────────────────────────────────────

@app.get("/tone", dependencies=[Depends(verify_token)])
def tone_get(db: Database = Depends(get_db)):
    split = tone_engine.get_active_split(db)
    return ok_response("tone-get", {
        "id": split.id,
        "professional_percent": split.professional,
        "semi_casual_percent": split.semi_casual,
        "casual_percent": split.casual,
        "is_active": split.is_active,
        "note": split.note,
    })


@app.post("/tone/set", dependencies=[Depends(verify_token)])
def tone_set(req: ToneSetRequest, db: Database = Depends(get_db)):
    try:
        saved = tone_engine.save_split(db, req.professional, req.semi_casual, req.casual, req.note)
        return ok_response("tone-set", {
            "id": saved.id,
            "professional_percent": saved.professional,
            "semi_casual_percent": saved.semi_casual,
            "casual_percent": saved.casual,
            "is_active": True,
        })
    except ValueError as exc:
        err_response("tone-set", "TONE_SPLIT_INVALID", str(exc))


# ── Campaign endpoints ─────────────────────────────────────────────────────────

@app.post("/campaign/create", dependencies=[Depends(verify_token)])
def campaign_create(req: CampaignCreateRequest, db: Database = Depends(get_db)):
    try:
        campaign = campaign_service.create_campaign(
            db, name=req.name, topic_brief=req.topic_brief, target_filter=req.target_filter
        )
        return ok_response("campaign-create", {
            "id": campaign.id,
            "name": campaign.name,
            "status": campaign.status,
            "tone_professional_percent": campaign.tone_professional,
            "tone_semi_casual_percent": campaign.tone_semi_casual,
            "tone_casual_percent": campaign.tone_casual,
        })
    except ValueError as exc:
        err_response("campaign-create", "CAMPAIGN_CREATE_INVALID", str(exc))


@app.get("/campaign/{campaign_id}/recipients", dependencies=[Depends(verify_token)])
def campaign_recipients(campaign_id: int, db: Database = Depends(get_db)):
    """
    Return the list of recipients + their assigned tones.
    The agent uses this to know exactly who to write for and in what tone.
    """
    camp = campaign_service.get_campaign(db, campaign_id)
    if not camp:
        err_response("campaign-recipients", "CAMPAIGN_NOT_FOUND", f"Campaign #{campaign_id} not found.", 404)

    recipients = campaign_service.build_recipient_list(db, camp)
    rds = campaign_service.prepare_recipient_drafts(db, camp, recipients)

    return ok_response("campaign-recipients", [
        {
            "person_id": rd.person.id,
            "full_name": rd.person.full_name,
            "email": rd.person.email,
            "designation": rd.person.designation,
            "category": rd.person.category,
            "organization": rd.person.organization,
            "country": rd.person.country,
            "tone": rd.tone,
            "topic_brief": camp.topic_brief,
        }
        for rd in rds
    ])


@app.post("/campaign/draft/validate", dependencies=[Depends(verify_token)])
def campaign_draft_validate(req: DraftSubmitRequest, db: Database = Depends(get_db)):
    """
    Validate a draft without storing it. The agent uses this to check
    a message before submitting it in the review queue.
    """
    max_words = int(db.get_config_value("max_words_per_message", "200"))
    result = validate_draft(
        Draft(person_id=req.person_id, subject=req.subject, body=req.body, tone=req.tone),
        max_words,
    )
    return ok_response("draft-validate", {
        "valid": result.valid,
        "word_count": result.word_count,
        "violations": result.violations,
    })


@app.post("/campaign/draft/submit", dependencies=[Depends(verify_token)])
def campaign_draft_submit(req: DraftSubmitRequest, db: Database = Depends(get_db)):
    """
    Store a validated agent draft in the pending queue (message_log, status=pending).
    The operator reviews and approves these before sending.
    """
    max_words = int(db.get_config_value("max_words_per_message", "200"))
    d = Draft(person_id=req.person_id, subject=req.subject, body=req.body, tone=req.tone,
              idempotency_key=req.idempotency_key)
    result = validate_draft(d, max_words)
    if not result.valid:
        err_response("draft-submit", "DRAFT_INVALID",
                     "Draft validation failed:\n" + "\n".join(result.violations))

    # Store in message_log as pending for operator review
    camp = campaign_service.get_campaign(db, req.campaign_id)
    if not camp:
        err_response("draft-submit", "CAMPAIGN_NOT_FOUND", f"Campaign #{req.campaign_id} not found.", 404)

    p = person_service.get_person(db, req.person_id)
    if not p:
        err_response("draft-submit", "PERSON_NOT_FOUND", f"Person #{req.person_id} not found.", 404)

    log_id = db.execute(
        """
        INSERT INTO message_log
            (campaign_id, person_id, recipient_email, recipient_name,
             designation_snapshot, subject, message_body, word_count,
             tone_used, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
        """,
        (req.campaign_id, req.person_id, p.email, p.full_name,
         p.designation, req.subject, req.body, result.word_count, req.tone),
    )
    return ok_response("draft-submit", {
        "log_id": log_id,
        "person_id": req.person_id,
        "word_count": result.word_count,
        "tone": req.tone,
        "status": "pending",
    })


@app.post("/campaign/send", dependencies=[Depends(verify_token)])
def campaign_send(req: CampaignSendRequest, db: Database = Depends(get_db)):
    """
    Trigger the send phase. REQUIRES confirm=true explicitly in every call.
    Pulls all pending-status drafts for the campaign and dispatches them.
    Enforces a per-hour ceiling of 10 campaign-send calls (Section 17.6).
    """
    # Guardrail 1: explicit confirmation every time
    if not req.confirm:
        err_response("campaign-send", "CONFIRM_REQUIRED",
                     "campaign_send requires confirm=true explicitly in every call. "
                     "There is no session memory of a prior confirmation.")

    # Guardrail 2: per-hour rate ceiling
    global _send_call_timestamps
    now = time.time()
    _send_call_timestamps = [t for t in _send_call_timestamps if now - t < 3600]
    if len(_send_call_timestamps) >= _MAX_SENDS_PER_HOUR:
        err_response("campaign-send", "RATE_CEILING_EXCEEDED",
                     f"Maximum {_MAX_SENDS_PER_HOUR} campaign-send calls per hour reached.",
                     http_status=429)
    _send_call_timestamps.append(now)

    camp = campaign_service.get_campaign(db, req.campaign_id)
    if not camp:
        err_response("campaign-send", "CAMPAIGN_NOT_FOUND", f"Campaign #{req.campaign_id} not found.", 404)
    if camp.status not in ("draft", "in_progress"):
        err_response("campaign-send", "CAMPAIGN_NOT_SENDABLE",
                     f"Campaign is in status '{camp.status}' — cannot send.")

    # Fetch all pending message_log rows for this campaign
    pending_logs = db.fetch_all(
        "SELECT * FROM message_log WHERE campaign_id = %s AND status = 'pending'",
        (req.campaign_id,),
    )
    if not pending_logs:
        err_response("campaign-send", "NO_PENDING_DRAFTS",
                     "No pending drafts found for this campaign. Submit drafts first.")

    # ── Duplicate-send guard ───────────────────────────────────────────────────
    # 1. Find person_ids already successfully sent in this campaign
    already_sent_rows = db.fetch_all(
        "SELECT DISTINCT person_id FROM message_log "
        "WHERE campaign_id = %s AND status = 'sent'",
        (req.campaign_id,),
    )
    already_sent_ids = {row["person_id"] for row in already_sent_rows}

    # 2. Deduplicate pending_logs by person_id — skip already-sent persons
    seen_ids: set = set()
    safe_pending = []
    skipped_duplicates = 0
    for log in pending_logs:
        pid = log["person_id"]
        if pid in already_sent_ids or pid in seen_ids:
            skipped_duplicates += 1
            continue
        seen_ids.add(pid)
        safe_pending.append(log)

    if not safe_pending:
        err_response("campaign-send", "NO_PENDING_DRAFTS",
                     f"All {skipped_duplicates} draft(s) were already sent or duplicates.")
    # ──────────────────────────────────────────────────────────────────────────

    from services.sender_queue import ApprovedDraft, dispatch
    approved = [
        ApprovedDraft(
            person_id=log["person_id"],
            campaign_id=log["campaign_id"],
            recipient_email=log["recipient_email"],
            recipient_name=log["recipient_name"],
            designation_snapshot=log["designation_snapshot"],
            subject=log["subject"],
            body=log["message_body"],
            word_count=log["word_count"],
            tone_used=log["tone_used"],
        )
        for log in safe_pending
    ]

    # Delete pending logs (will be reinserted by dispatch with final status)
    db.execute(
        "DELETE FROM message_log WHERE campaign_id = %s AND status = 'pending'",
        (req.campaign_id,),
    )

    rate = int(db.get_config_value("send_rate_per_minute", "20"))
    from_addr = f"{_cfg.default_from_name} <{_cfg.default_from_email}>"

    sent = failed = 0
    for result in dispatch(db, approved, _cfg.resend_api_key, from_addr, rate):
        if result.status == "sent":
            sent += 1
        else:
            failed += 1

    db.execute(
        "UPDATE campaigns SET status = 'completed', completed_at = NOW(), "
        "total_sent = %s, total_failed = %s WHERE id = %s",
        (sent, failed, req.campaign_id),
    )

    return ok_response("campaign-send", {
        "campaign_id": req.campaign_id,
        "sent": sent,
        "failed": failed,
    })


# ── History endpoints ──────────────────────────────────────────────────────────

@app.post("/history/query", dependencies=[Depends(verify_token)])
def history_query(req: HistoryQueryRequest, db: Database = Depends(get_db)):
    if req.person_id:
        logs = campaign_service.history_for_person(db, req.person_id)
        return ok_response("history-query", logs)
    elif req.campaign_id:
        logs = campaign_service.history_for_campaign(db, req.campaign_id)
        return ok_response("history-query", logs)
    elif req.date_start and req.date_end:
        logs = campaign_service.history_by_date_range(db, req.date_start, req.date_end)
        return ok_response("history-query", logs)
    else:
        err_response("history-query", "MISSING_FILTER",
                     "Provide person_id, campaign_id, or date_start+date_end.")


@app.get("/health")
def health():
    """Public health check — no auth required."""
    return {"status": "ok", "service": "meridian"}


# ── Designation catalog ────────────────────────────────────────────────────────

@app.get("/catalog/designations", dependencies=[Depends(verify_token)])
def designation_catalog(category: Optional[str] = None, db: Database = Depends(get_db)):
    titles = person_service.get_designation_catalog(db, category)
    return ok_response("designation-catalog", {"category": category, "titles": titles})
