"""
services/campaign_service.py
Orchestrates the full campaign lifecycle end-to-end.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Generator, Iterator, List, Optional

from db.connection import Database
from services.message_validator import Draft, validate_draft, validate_or_raise
from services.person_service import get_active_persons, Person
from services.sender_queue import ApprovedDraft, dispatch, SendResult
from services.tone_engine import get_active_split, assign_tone

logger = logging.getLogger(__name__)


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class Campaign:
    id: int
    name: str
    topic_brief: str
    target_filter: Optional[str]
    tone_professional: int
    tone_semi_casual: int
    tone_casual: int
    total_recipients: int
    total_sent: int
    total_failed: int
    status: str
    created_at: datetime
    completed_at: Optional[datetime]


@dataclass
class CampaignResult:
    campaign_id: int
    sent: int
    failed: int
    skipped: int
    duration_seconds: float


# ── Row mapping ────────────────────────────────────────────────────────────────

def _row_to_campaign(row: dict) -> Campaign:
    return Campaign(
        id=row["id"],
        name=row["name"],
        topic_brief=row["topic_brief"],
        target_filter=row.get("target_filter"),
        tone_professional=row["tone_professional_percent"],
        tone_semi_casual=row["tone_semi_casual_percent"],
        tone_casual=row["tone_casual_percent"],
        total_recipients=row["total_recipients"],
        total_sent=row["total_sent"],
        total_failed=row["total_failed"],
        status=row["status"],
        created_at=row["created_at"],
        completed_at=row.get("completed_at"),
    )


# ── Campaign creation ──────────────────────────────────────────────────────────

def create_campaign(
    db: Database,
    name: str,
    topic_brief: str,
    target_filter: Optional[dict] = None,
) -> Campaign:
    """
    Create a draft campaign, snapshotting the active tone split.
    target_filter is stored as JSON, e.g. {"category": "journalist"}.
    """
    if not name.strip():
        raise ValueError("Campaign name cannot be empty.")
    if not topic_brief.strip():
        raise ValueError("Topic brief cannot be empty.")

    split = get_active_split(db)
    filter_str = json.dumps(target_filter) if target_filter else None

    new_id = db.execute(
        """
        INSERT INTO campaigns
            (name, topic_brief, target_filter,
             tone_professional_percent, tone_semi_casual_percent, tone_casual_percent,
             status)
        VALUES (%s, %s, %s, %s, %s, %s, 'draft')
        """,
        (name.strip(), topic_brief.strip(), filter_str,
         split.professional, split.semi_casual, split.casual),
    )
    row = db.fetch_one("SELECT * FROM campaigns WHERE id = %s", (new_id,))
    return _row_to_campaign(row)


def get_campaign(db: Database, campaign_id: int) -> Optional[Campaign]:
    row = db.fetch_one("SELECT * FROM campaigns WHERE id = %s", (campaign_id,))
    return _row_to_campaign(row) if row else None


def list_campaigns(db: Database) -> List[Campaign]:
    rows = db.fetch_all("SELECT * FROM campaigns ORDER BY id DESC")
    return [_row_to_campaign(r) for r in rows]


# ── Recipient list ─────────────────────────────────────────────────────────────

def build_recipient_list(db: Database, campaign: Campaign) -> List[Person]:
    """
    Build the list of active persons to contact.
    Respects the campaign's target_filter JSON.
    """
    filt = {}
    if campaign.target_filter:
        try:
            filt = json.loads(campaign.target_filter)
        except Exception:
            filt = {}

    category = filt.get("category")
    return get_active_persons(db, category=category)


# ── Draft management ───────────────────────────────────────────────────────────

@dataclass
class RecipientDraft:
    """An agent-supplied draft associated with one recipient."""
    person: Person
    tone: str
    draft: Optional[Draft] = None
    validated: bool = False
    skipped: bool = False
    skip_reason: Optional[str] = None


def prepare_recipient_drafts(
    db: Database,
    campaign: Campaign,
    recipients: List[Person],
) -> List[RecipientDraft]:
    """
    Assign a tone to each recipient (using the campaign's snapshotted split).
    Returns a list of RecipientDraft objects ready for the agent to fill.
    """
    from services.tone_engine import ToneSplit
    split = ToneSplit(
        id=0,
        professional=campaign.tone_professional,
        semi_casual=campaign.tone_semi_casual,
        casual=campaign.tone_casual,
        is_active=True,
        note=None,
    )
    result = []
    for person in recipients:
        tone = assign_tone(person.preferred_tone, split)
        result.append(RecipientDraft(person=person, tone=tone))
    return result


def submit_draft(
    db: Database,
    recipient_draft: RecipientDraft,
    subject: str,
    body: str,
    max_words: int = 200,
    idempotency_key: Optional[str] = None,
) -> RecipientDraft:
    """
    Accept a draft from the agent, validate it, and attach it to the RecipientDraft.
    Raises ValueError if validation fails.
    """
    d = Draft(
        person_id=recipient_draft.person.id,
        subject=subject,
        body=body,
        tone=recipient_draft.tone,
        idempotency_key=idempotency_key,
    )
    validate_or_raise(d, max_words)
    recipient_draft.draft = d
    recipient_draft.validated = True
    return recipient_draft


# ── Send phase ─────────────────────────────────────────────────────────────────

def run_send_phase(
    db: Database,
    campaign: Campaign,
    recipient_drafts: List[RecipientDraft],
    api_key: str,
    from_addr: str,
    rate_per_minute: int = 20,
) -> Generator[SendResult, None, CampaignResult]:
    """
    Convert validated RecipientDrafts → ApprovedDrafts → dispatch.
    Yields a SendResult per recipient, then returns CampaignResult.
    Updates campaign counters after each send.
    """
    # Mark campaign in_progress
    db.execute(
        "UPDATE campaigns SET status = 'in_progress', total_recipients = %s WHERE id = %s",
        (len(recipient_drafts), campaign.id),
    )

    approved: List[ApprovedDraft] = []
    skipped = 0

    for rd in recipient_drafts:
        if rd.skipped or not rd.validated or not rd.draft:
            # Log skipped entries
            db.execute(
                """
                INSERT INTO message_log
                    (campaign_id, person_id, recipient_email, recipient_name,
                     designation_snapshot, subject, message_body, word_count,
                     tone_used, status, error_message)
                VALUES (%s, %s, %s, %s, %s, 'N/A', 'skipped', 0, %s, 'skipped', %s)
                """,
                (
                    campaign.id, rd.person.id, rd.person.email,
                    rd.person.full_name, rd.person.designation,
                    rd.tone, rd.skip_reason or "Operator skipped",
                ),
            )
            skipped += 1
            continue
        approved.append(ApprovedDraft(
            person_id=rd.person.id,
            campaign_id=campaign.id,
            recipient_email=rd.person.email,
            recipient_name=rd.person.full_name,
            designation_snapshot=rd.person.designation,
            subject=rd.draft.subject,
            body=rd.draft.body,
            word_count=len(rd.draft.body.split()),
            tone_used=rd.tone,
        ))

    total_sent = 0
    total_failed = 0
    start_time = __import__("time").monotonic()

    for result in dispatch(db, approved, api_key, from_addr, rate_per_minute):
        if result.status == "sent":
            total_sent += 1
        else:
            total_failed += 1

        # Update campaign counters live
        db.execute(
            "UPDATE campaigns SET total_sent = %s, total_failed = %s WHERE id = %s",
            (total_sent, total_failed, campaign.id),
        )
        yield result

    duration = __import__("time").monotonic() - start_time

    # Mark campaign completed
    db.execute(
        "UPDATE campaigns SET status = 'completed', completed_at = NOW() WHERE id = %s",
        (campaign.id,),
    )

    return CampaignResult(
        campaign_id=campaign.id,
        sent=total_sent,
        failed=total_failed,
        skipped=skipped,
        duration_seconds=duration,
    )


def abort_campaign(db: Database, campaign_id: int) -> None:
    """Mark an in-progress campaign as aborted."""
    db.execute(
        "UPDATE campaigns SET status = 'aborted' WHERE id = %s AND status = 'in_progress'",
        (campaign_id,),
    )


# ── History queries ────────────────────────────────────────────────────────────

def history_for_person(db: Database, person_id: int) -> list[dict]:
    return db.fetch_all(
        """
        SELECT ml.id, ml.campaign_id, c.name AS campaign_name,
               ml.subject, ml.tone_used, ml.status, ml.sent_at, ml.word_count
        FROM message_log ml
        LEFT JOIN campaigns c ON c.id = ml.campaign_id
        WHERE ml.person_id = %s
        ORDER BY ml.created_at DESC
        """,
        (person_id,),
    )


def history_for_campaign(db: Database, campaign_id: int) -> list[dict]:
    return db.fetch_all(
        """
        SELECT ml.*, p.full_name
        FROM message_log ml
        JOIN persons p ON p.id = ml.person_id
        WHERE ml.campaign_id = %s
        ORDER BY ml.created_at ASC
        """,
        (campaign_id,),
    )


def history_failed(db: Database) -> list[dict]:
    return db.fetch_all(
        """
        SELECT ml.*, p.full_name, c.name AS campaign_name
        FROM message_log ml
        JOIN persons p ON p.id = ml.person_id
        LEFT JOIN campaigns c ON c.id = ml.campaign_id
        WHERE ml.status = 'failed'
        ORDER BY ml.created_at DESC
        """
    )


def history_by_date_range(db: Database, start: str, end: str) -> list[dict]:
    return db.fetch_all(
        """
        SELECT ml.*, p.full_name, p.email, c.name AS campaign_name
        FROM message_log ml
        JOIN persons p ON p.id = ml.person_id
        LEFT JOIN campaigns c ON c.id = ml.campaign_id
        WHERE DATE(ml.created_at) BETWEEN %s AND %s
        ORDER BY ml.created_at DESC
        """,
        (start, end),
    )
