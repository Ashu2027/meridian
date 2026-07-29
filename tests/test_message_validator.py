"""
tests/test_message_validator.py
Unit tests for message_validator — word count, emoji, boilerplate, real newlines.
"""
from __future__ import annotations

import pytest
from services.message_validator import (
    Draft, ValidationResult,
    BOILERPLATE_PHRASES, validate_draft, validate_or_raise, count_words,
)


def _draft(body: str, subject: str = "Test Subject", tone: str = "professional") -> Draft:
    return Draft(person_id=1, subject=subject, body=body, tone=tone)


class TestCountWords:
    def test_simple(self):
        assert count_words("hello world foo") == 3

    def test_empty(self):
        assert count_words("") == 0

    def test_multiple_spaces(self):
        assert count_words("hello   world") == 2

    def test_newlines(self):
        assert count_words("hello\nworld\nfoo") == 3


class TestValidateDraft:
    def test_valid_draft(self):
        body = " ".join(["word"] * 100)
        result = validate_draft(_draft(body))
        assert result.valid is True
        assert result.word_count == 100
        assert result.violations == []

    def test_word_count_exactly_at_limit(self):
        body = " ".join(["word"] * 200)
        result = validate_draft(_draft(body), max_words=200)
        assert result.valid is True

    def test_word_count_over_limit(self):
        body = " ".join(["word"] * 201)
        result = validate_draft(_draft(body), max_words=200)
        assert result.valid is False
        assert any("201" in v for v in result.violations)
        assert any("limit: 200" in v for v in result.violations)

    def test_emoji_detected(self):
        result = validate_draft(_draft("Hello 😀 world"))
        assert result.valid is False
        assert any("emoji" in v.lower() for v in result.violations)

    def test_multiple_emoji_detected(self):
        result = validate_draft(_draft("Hey 🎉 this is 🚀 great"))
        assert result.valid is False
        assert any("emoji" in v.lower() for v in result.violations)

    def test_no_emoji_passes(self):
        result = validate_draft(_draft("Hello world, no emoji here."))
        assert result.valid is True

    def test_literal_backslash_n_detected(self):
        body = r"Hello world.\nThis should be a real newline."
        result = validate_draft(_draft(body))
        assert result.valid is False
        assert any(r"\n" in v for v in result.violations)

    def test_real_newline_passes(self):
        body = "Hello world.\nThis is a real newline."
        result = validate_draft(_draft(body))
        assert result.valid is True

    def test_empty_subject_fails(self):
        result = validate_draft(_draft("Valid body text here", subject=""))
        assert result.valid is False
        assert any("subject" in v.lower() for v in result.violations)

    def test_whitespace_only_subject_fails(self):
        result = validate_draft(_draft("Valid body text here", subject="   "))
        assert result.valid is False

    def test_multiple_violations_all_reported(self):
        """Emoji + word count over limit → both reported (boilerplate only reports once)."""
        body = "😀 " + " ".join(["word"] * 205)
        result = validate_draft(_draft(body), max_words=200)
        assert result.valid is False
        assert len(result.violations) >= 2


class TestBoilerplatePhrases:
    @pytest.mark.parametrize("phrase", [
        "I hope this email finds you well",
        "I wanted to reach out",
        "Please do not hesitate to contact me",
        "in today's fast-paced world",
        "as a valued member",
        "leverage synergies",
        "I am reaching out",
        "Hope you are doing well",
        "I trust this message finds you well",
        "touching base",
        "circle back",
        "going forward",
    ])
    def test_boilerplate_detected(self, phrase: str):
        result = validate_draft(_draft(f"Dear Sir, {phrase}, regarding our cooperation."))
        assert result.valid is False, f"Expected boilerplate to be caught: {phrase!r}"
        assert any("boilerplate" in v.lower() for v in result.violations)

    def test_clean_natural_text_passes(self):
        body = (
            "Working on the project has revealed something I think you'd find genuinely useful. "
            "There's a specific development in the pipeline that directly relates to your coverage "
            "of infrastructure policy — something you likely haven't seen reported anywhere yet.\n\n"
            "I'd value a brief conversation at a time that suits you."
        )
        result = validate_draft(_draft(body))
        assert result.valid is True, f"Clean text failed: {result.violations}"


class TestValidateOrRaise:
    def test_raises_on_invalid(self):
        body = " ".join(["word"] * 250)
        with pytest.raises(ValueError, match="validation failed"):
            validate_or_raise(_draft(body))

    def test_returns_word_count_on_success(self):
        body = " ".join(["word"] * 50)
        wc = validate_or_raise(_draft(body))
        assert wc == 50
