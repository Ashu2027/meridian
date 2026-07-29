"""
services/message_validator.py
Validates agent-provided drafts before they are sent.

KEY DESIGN DECISION (from user):
  The agent (Claude Code, Antigravity, or any CLI agent) generates the message
  content. This system does NOT call any AI API. The validator enforces the same
  hard rules that would be in a system-prompt:
    - ≤ 200 words (or the configured limit)
    - No emoji
    - No literal \\n escape sequences (must be real newlines)
    - No AI-sounding boilerplate phrases

An operator or agent submits a Draft and receives validation results.
The campaign review screen then lets the operator approve / edit / reject it.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ── Emoji detection ────────────────────────────────────────────────────────────

# Unicode ranges that cover emoji and pictographic symbols
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"   # Emoticons
    "\U0001F300-\U0001F5FF"   # Misc symbols & pictographs
    "\U0001F680-\U0001F6FF"   # Transport & map
    "\U0001F1E0-\U0001F1FF"   # Flags
    "\U00002700-\U000027BF"   # Dingbats
    "\U0001F900-\U0001F9FF"   # Supplemental symbols
    "\U00002600-\U000026FF"   # Misc symbols
    "\U0001FA00-\U0001FA6F"   # Chess symbols
    "\U0001FA70-\U0001FAFF"   # Symbols extended-A
    "]+",
    flags=re.UNICODE,
)

# ── AI boilerplate phrases ────────────────────────────────────────────────────
# Any match here triggers the same rejection as emoji / word-count excess.

BOILERPLATE_PHRASES: List[str] = [
    "i hope this email finds you well",
    "i hope this message finds you well",
    "i trust this email finds you well",
    "i trust this message finds you well",
    "i wanted to reach out",
    "i am reaching out",
    "please do not hesitate to contact me",
    "please do not hesitate to reach out",
    "please feel free to reach out",
    "feel free to contact me",
    "in today's fast-paced world",
    "in today's rapidly changing world",
    "as a valued member",
    "leverage synergies",
    "move the needle",
    "circle back",
    "take this to the next level",
    "at the end of the day",
    "going forward",
    "as per my last email",
    "touching base",
    "hope you are doing well",
    "hope all is well",
    "i am writing to you",
    "i am writing today",
    "i am writing to inform",
    "i am writing to let you know",
    "i am writing to follow up",
    "best regards and kind wishes",
    "warm regards and best wishes",
    "it is with great pleasure",
    "i am delighted to inform",
    "i am pleased to inform",
    "pursuant to",
    "as a follow-up to our previous",
]


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class Draft:
    """A message draft submitted by the agent for validation."""
    person_id: int
    subject: str
    body: str
    tone: str                           # 'professional' | 'semi_casual' | 'casual'
    idempotency_key: Optional[str] = None


@dataclass
class ValidationResult:
    valid: bool
    word_count: int
    violations: List[str] = field(default_factory=list)


# ── Validation logic ───────────────────────────────────────────────────────────

def count_words(text: str) -> int:
    return len(text.split())


def validate_draft(draft: Draft, max_words: int = 200) -> ValidationResult:
    """
    Validates a draft against the hard rules.
    Returns a ValidationResult with all violations listed.
    """
    violations: List[str] = []
    body = draft.body

    # 1. Word count
    wc = count_words(body)
    if wc > max_words:
        violations.append(
            f"Word count is {wc} (limit: {max_words}). "
            f"Please shorten by {wc - max_words} words."
        )

    # 2. Emoji check
    emoji_matches = _EMOJI_RE.findall(body)
    if emoji_matches:
        found = "".join(set(emoji_matches))
        violations.append(f"Message contains emoji: {found!r}. Remove all emoji.")

    # 3. Literal \n escape sequences (two-character sequence, not a real newline)
    if "\\n" in body:
        violations.append(
            r"Message contains literal '\n' escape sequences. "
            "Use real newline characters instead."
        )

    # 4. Boilerplate phrases
    body_lower = body.lower()
    for phrase in BOILERPLATE_PHRASES:
        if phrase in body_lower:
            violations.append(
                f"AI boilerplate detected: '{phrase}'. "
                "Rewrite this section to sound like a genuine individual email."
            )
            break  # report once per draft, let agent fix and resubmit

    # 5. Subject line not empty
    if not draft.subject.strip():
        violations.append("Subject line cannot be empty.")

    return ValidationResult(
        valid=len(violations) == 0,
        word_count=wc,
        violations=violations,
    )


def validate_or_raise(draft: Draft, max_words: int = 200) -> int:
    """
    Validate *draft* and raise ValueError listing all violations.
    Returns word_count on success.
    """
    result = validate_draft(draft, max_words)
    if not result.valid:
        raise ValueError("Draft validation failed:\n" + "\n".join(f"  • {v}" for v in result.violations))
    return result.word_count
