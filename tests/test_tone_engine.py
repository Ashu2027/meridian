"""
tests/test_tone_engine.py
Unit tests for tone_engine — covers validation, save, assign_tone.
Target: 100% of tone_engine.py functions.
"""
from __future__ import annotations

import random
import pytest
from unittest.mock import MagicMock, call, patch

from services.tone_engine import (
    ToneSplit, assign_tone, get_active_split,
    save_split, validate_split, get_all_splits,
)


# ── validate_split ─────────────────────────────────────────────────────────────

class TestValidateSplit:
    def test_valid_split(self):
        ok, msg = validate_split(60, 30, 10)
        assert ok is True
        assert msg == ""

    def test_valid_all_zero_except_one(self):
        ok, _ = validate_split(100, 0, 0)
        assert ok is True

    def test_fails_when_sum_not_100(self):
        ok, msg = validate_split(60, 30, 9)
        assert ok is False
        assert "99%" in msg
        assert "add 1%" in msg

    def test_fails_when_sum_over_100(self):
        ok, msg = validate_split(60, 30, 15)
        assert ok is False
        assert "105%" in msg
        assert "remove 5%" in msg

    def test_fails_value_out_of_range_negative(self):
        ok, msg = validate_split(-1, 60, 41)
        assert ok is False
        assert "0–100" in msg

    def test_fails_value_out_of_range_over(self):
        ok, msg = validate_split(60, 101, -61)
        assert ok is False
        assert "0–100" in msg

    def test_all_zeros_fails(self):
        ok, msg = validate_split(0, 0, 0)
        assert ok is False

    def test_exact_boundaries(self):
        ok, _ = validate_split(0, 0, 100)
        assert ok is True
        ok2, _ = validate_split(0, 100, 0)
        assert ok2 is True


# ── get_active_split ────────────────────────────────────────────────────────────

class TestGetActiveSplit:
    def test_returns_active_row(self, mock_db):
        mock_db.fetch_one.return_value = {
            "id": 5, "professional_percent": 50, "semi_casual_percent": 35,
            "casual_percent": 15, "is_active": True, "updated_by_note": "test",
        }
        split = get_active_split(mock_db)
        assert split.id == 5
        assert split.professional == 50
        assert split.semi_casual == 35
        assert split.casual == 15

    def test_seeds_default_when_no_row(self, mock_db):
        # First call returns None (no row), second returns seeded row
        mock_db.fetch_one.side_effect = [
            None,
            {"id": 1, "professional_percent": 60, "semi_casual_percent": 30,
             "casual_percent": 10, "is_active": True, "updated_by_note": "auto-seeded default"},
        ]
        mock_db.execute.return_value = 1
        split = get_active_split(mock_db)
        assert split.professional == 60


# ── save_split ─────────────────────────────────────────────────────────────────

class TestSaveSplit:
    def test_saves_valid_split(self, mock_db):
        mock_db.execute.return_value = 7
        result = save_split(mock_db, 50, 30, 20, "test note")
        assert result.id == 7
        assert result.professional == 50
        # Deactivate old row first, then insert new
        assert mock_db.execute.call_count == 2

    def test_raises_on_invalid_split(self, mock_db):
        with pytest.raises(ValueError, match="Total"):
            save_split(mock_db, 50, 30, 15)

    def test_never_updates_in_place(self, mock_db):
        """Ensure we UPDATE is_active=FALSE first, then INSERT."""
        mock_db.execute.return_value = 8
        save_split(mock_db, 60, 30, 10, "note")
        first_call = mock_db.execute.call_args_list[0][0][0]
        assert "UPDATE" in first_call and "is_active = FALSE" in first_call
        second_call = mock_db.execute.call_args_list[1][0][0]
        assert "INSERT" in second_call


# ── assign_tone ────────────────────────────────────────────────────────────────

class TestAssignTone:
    def _split(self, pro=60, semi=30, cas=10):
        return ToneSplit(id=1, professional=pro, semi_casual=semi, casual=cas, is_active=True, note=None)

    def test_override_professional(self):
        assert assign_tone("professional", self._split()) == "professional"

    def test_override_semi_casual(self):
        assert assign_tone("semi_casual", self._split()) == "semi_casual"

    def test_override_casual(self):
        assert assign_tone("casual", self._split()) == "casual"

    def test_auto_respects_distribution(self):
        """With 1000 rolls, distribution should be approximately correct."""
        split = self._split(60, 30, 10)
        counts = {"professional": 0, "semi_casual": 0, "casual": 0}
        rng = random.Random(42)
        for _ in range(1000):
            tone = assign_tone("auto", split, rng)
            counts[tone] += 1
        # Allow ±10% tolerance
        assert 500 <= counts["professional"] <= 700, counts
        assert 200 <= counts["semi_casual"] <= 400, counts
        assert 50 <= counts["casual"] <= 150, counts

    def test_100_percent_professional(self):
        split = self._split(100, 0, 0)
        rng = random.Random(0)
        for _ in range(50):
            assert assign_tone("auto", split, rng) == "professional"

    def test_100_percent_casual(self):
        split = self._split(0, 0, 100)
        rng = random.Random(0)
        for _ in range(50):
            assert assign_tone("auto", split, rng) == "casual"

    def test_unknown_preferred_tone_treated_as_auto(self):
        """Any value that isn't a known tone falls back to weighted random."""
        split = self._split(100, 0, 0)
        rng = random.Random(0)
        result = assign_tone("unknown_tone", split, rng)
        assert result == "professional"  # because 100% professional
