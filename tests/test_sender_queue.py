"""
tests/test_sender_queue.py
Unit tests for sender_queue — RateLimiter, send_with_retry, dispatch.
All Resend API calls are mocked.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch, call

import pytest

from services.sender_queue import (
    ApprovedDraft, RateLimiter, SendResult,
    _is_permanent, send_with_retry, dispatch,
)


def _draft(**kwargs) -> ApprovedDraft:
    defaults = dict(
        person_id=1, campaign_id=1,
        recipient_email="jane@example.com", recipient_name="Jane",
        designation_snapshot="Editor", subject="Test", body="Hello world.",
        word_count=2, tone_used="professional",
    )
    defaults.update(kwargs)
    return ApprovedDraft(**defaults)


class TestIsPermanent:
    def test_invalid_to_is_permanent(self):
        assert _is_permanent("invalid_to address")

    def test_hard_bounce_is_permanent(self):
        assert _is_permanent("hard bounce returned")

    def test_timeout_is_not_permanent(self):
        assert not _is_permanent("connection timeout")

    def test_500_error_is_not_permanent(self):
        assert not _is_permanent("500 internal server error")


class TestRateLimiter:
    def test_acquires_immediately_when_tokens_available(self):
        limiter = RateLimiter(rate_per_minute=60)  # 1 token/sec
        start = time.monotonic()
        limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.5  # Should be nearly instant

    def test_rate_at_least_one(self):
        limiter = RateLimiter(rate_per_minute=0)
        assert limiter._rate == 1


class TestSendWithRetry:
    def test_success_on_first_attempt(self):
        with patch("services.sender_queue.send_via_resend", return_value=("msg_id_123", None)):
            msg_id, err = send_with_retry("re_key", "from@test.com", _draft())
        assert msg_id == "msg_id_123"
        assert err is None

    def test_retries_on_transient_error(self):
        responses = [
            (None, "500 internal server error"),
            (None, "503 service unavailable"),
            ("msg_id_ok", None),
        ]
        with patch("services.sender_queue.send_via_resend", side_effect=responses):
            with patch("time.sleep"):
                msg_id, err = send_with_retry("re_key", "from@test.com", _draft(), max_attempts=3)
        assert msg_id == "msg_id_ok"
        assert err is None

    def test_gives_up_after_max_attempts(self):
        with patch("services.sender_queue.send_via_resend", return_value=(None, "503 error")):
            with patch("time.sleep"):
                msg_id, err = send_with_retry("re_key", "from@test.com", _draft(), max_attempts=3)
        assert msg_id is None
        assert err is not None

    def test_no_retry_on_permanent_error(self):
        with patch("services.sender_queue.send_via_resend", return_value=(None, "invalid_to address")) as mock_send:
            msg_id, err = send_with_retry("re_key", "from@test.com", _draft(), max_attempts=3)
        assert mock_send.call_count == 1  # Only called once — no retry
        assert msg_id is None

    def test_exponential_backoff_delays(self):
        with patch("services.sender_queue.send_via_resend", return_value=(None, "503 error")):
            with patch("time.sleep") as mock_sleep:
                send_with_retry("re_key", "from@test.com", _draft(), max_attempts=3)
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert len(sleep_calls) == 2  # 2 waits for 3 attempts
        assert sleep_calls[1] > sleep_calls[0]  # Exponential: second wait > first


class TestDispatch:
    def _make_db(self, execute_return=1):
        db = MagicMock()
        db.execute.return_value = execute_return
        db.get_config_value.return_value = "200"
        return db

    def test_successful_sends(self):
        db = self._make_db()
        drafts = [_draft(), _draft(recipient_email="bob@example.com", person_id=2)]

        with patch("services.sender_queue.send_via_resend", return_value=("msg_123", None)):
            results = list(dispatch(db, drafts, "re_key", "from@test.com", rate_per_minute=1000))

        assert len(results) == 2
        assert all(r.status == "sent" for r in results)

    def test_failed_send_marks_bounced(self):
        db = self._make_db()
        draft = _draft()

        with patch("services.sender_queue.send_via_resend", return_value=(None, "invalid_to address")):
            with patch("services.sender_queue.set_status") as mock_set_status:
                results = list(dispatch(db, [draft], "re_key", "from@test.com", rate_per_minute=1000))

        assert results[0].status == "failed"
        mock_set_status.assert_called_once_with(db, 1, "bounced")

    def test_logs_every_attempt(self):
        db = self._make_db()
        drafts = [_draft(), _draft(person_id=2, recipient_email="b@b.com")]

        with patch("services.sender_queue.send_via_resend", return_value=("msg_ok", None)):
            list(dispatch(db, drafts, "re_key", "from@test.com", rate_per_minute=1000))

        # execute called twice — once per sent email (for INSERT into message_log)
        assert db.execute.call_count == 2

    def test_empty_drafts_yields_nothing(self):
        db = self._make_db()
        results = list(dispatch(db, [], "re_key", "from@test.com"))
        assert results == []
