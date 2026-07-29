"""
services/sender_queue.py
Rate-limited, retry-backed Resend API sender.
Every attempt is logged to message_log before moving to the next recipient.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Generator, List, Optional

import resend

from db.connection import Database
from services.person_service import set_status

logger = logging.getLogger(__name__)

# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class ApprovedDraft:
    person_id: int
    campaign_id: Optional[int]
    recipient_email: str
    recipient_name: str
    designation_snapshot: str
    subject: str
    body: str
    word_count: int
    tone_used: str


@dataclass
class SendResult:
    person_id: int
    email: str
    status: str           # 'sent' | 'failed' | 'skipped'
    resend_message_id: Optional[str] = None
    error_message: Optional[str] = None
    log_id: Optional[int] = None


# ── Token-bucket rate limiter ──────────────────────────────────────────────────

class RateLimiter:
    """
    Simple token-bucket implementation.
    Refills at *rate_per_minute* tokens per 60 seconds.
    Thread-safe for single-process sequential sends.
    """

    def __init__(self, rate_per_minute: int) -> None:
        self._rate = max(1, rate_per_minute)
        self._tokens: float = float(self._rate)
        self._last_refill: float = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._rate, self._tokens + elapsed * (self._rate / 60.0))
        self._last_refill = now

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait_time = (1.0 - self._tokens) * (60.0 / self._rate)
            time.sleep(wait_time)


# ── Resend caller ──────────────────────────────────────────────────────────────

_PERMANENT_ERRORS = {
    "invalid_to",
    "invalid_from",
    "not_found",
    "validation_error",
    "missing_required_field",
}

_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_permanent(error_str: str) -> bool:
    e = error_str.lower()
    return any(k in e for k in _PERMANENT_ERRORS) or "hard bounce" in e


def send_via_resend(
    api_key: str,
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    POST one email to Resend.
    Returns (resend_message_id, None) on success.
    Returns (None, error_message) on failure.
    """
    resend.api_key = api_key
    try:
        params: resend.Emails.SendParams = {
            "from": from_addr,
            "to": [to_addr],
            "subject": subject,
            "text": body,
        }
        resp = resend.Emails.send(params)
        return resp.get("id"), None
    except Exception as exc:
        return None, str(exc)


def send_with_retry(
    api_key: str,
    from_addr: str,
    draft: ApprovedDraft,
    max_attempts: int = 3,
) -> tuple[Optional[str], Optional[str]]:
    """
    Exponential-backoff retry wrapper.
    Returns (message_id, None) on success or (None, error) after exhausting attempts.
    """
    base_delay = 2.0
    last_error: Optional[str] = None

    for attempt in range(1, max_attempts + 1):
        msg_id, err = send_via_resend(
            api_key, from_addr, draft.recipient_email, draft.subject, draft.body
        )
        if msg_id:
            return msg_id, None
        last_error = err or "Unknown error"
        if _is_permanent(last_error):
            logger.warning("Permanent send failure for %s: %s", draft.recipient_email, last_error)
            return None, last_error
        if attempt < max_attempts:
            sleep_time = base_delay * (2 ** (attempt - 1))
            logger.info("Transient error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt, max_attempts, sleep_time, last_error)
            time.sleep(sleep_time)

    return None, last_error


# ── Log helpers ────────────────────────────────────────────────────────────────

def _insert_log(db: Database, draft: ApprovedDraft, status: str,
                resend_id: Optional[str] = None,
                error: Optional[str] = None) -> int:
    sent_at = "NOW()" if status == "sent" else "NULL"
    log_id = db.execute(
        f"""
        INSERT INTO message_log
            (campaign_id, person_id, recipient_email, recipient_name,
             designation_snapshot, subject, message_body, word_count,
             tone_used, resend_message_id, status, error_message, sent_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, {"NOW()" if status == "sent" else "NULL"})
        """,
        (
            draft.campaign_id, draft.person_id, draft.recipient_email,
            draft.recipient_name, draft.designation_snapshot,
            draft.subject, draft.body, draft.word_count, draft.tone_used,
            resend_id, status, error,
        ),
    )
    return log_id


# ── Main dispatch ──────────────────────────────────────────────────────────────

def dispatch(
    db: Database,
    approved_drafts: List[ApprovedDraft],
    api_key: str,
    from_addr: str,
    rate_per_minute: int = 20,
    max_retry_attempts: int = 3,
) -> Generator[SendResult, None, None]:
    """
    Send all approved drafts, rate-limited.
    Yields a SendResult after each send attempt.
    Logs every outcome to message_log before moving to next recipient.
    """
    limiter = RateLimiter(rate_per_minute)

    for draft in approved_drafts:
        limiter.acquire()

        msg_id, err = send_with_retry(api_key, from_addr, draft, max_retry_attempts)

        if msg_id:
            log_id = _insert_log(db, draft, "sent", resend_id=msg_id)
            logger.info("✓ Sent to %s (resend_id=%s)", draft.recipient_email, msg_id)
            yield SendResult(
                person_id=draft.person_id,
                email=draft.recipient_email,
                status="sent",
                resend_message_id=msg_id,
                log_id=log_id,
            )
        else:
            log_id = _insert_log(db, draft, "failed", error=err)
            if err and _is_permanent(err):
                set_status(db, draft.person_id, "bounced")
            logger.error("✗ Failed for %s: %s", draft.recipient_email, err)
            yield SendResult(
                person_id=draft.person_id,
                email=draft.recipient_email,
                status="failed",
                error_message=err,
                log_id=log_id,
            )
