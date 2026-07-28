"""Style guard for ALL generated outbound text.

HARD RULE 8: zero em dashes. Reject/regenerate any draft containing an em dash
(U+2014) or a double hyphen used as one. Also reject tired cold-outreach cliches.
Outbound copy must read human.
"""
from __future__ import annotations

import re
from typing import Callable

EM_DASH = "—"   # —
EN_DASH = "–"   # – (common em-dash substitute; also rejected)
DOUBLE_HYPHEN = re.compile(r"--")

BANNED_PHRASES = [
    "i hope this finds you well",
    "i hope this email finds you well",
    "i came across your profile",
    "i wanted to reach out",
    "reaching out",
    "touch base",
    "circle back",
    "synergy",
    "in today's fast-paced",
    "game-changer",
    "game changer",
    "to whom it may concern",
]


def violations(text: str) -> list[str]:
    """Return a list of style problems in `text`. Empty list == clean."""
    problems: list[str] = []
    if not text:
        return ["empty text"]
    if EM_DASH in text:
        problems.append("contains em dash (—)")
    if EN_DASH in text:
        problems.append("contains en dash (–)")
    if DOUBLE_HYPHEN.search(text):
        problems.append("contains double hyphen (--) used as a dash")
    low = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in low:
            problems.append(f"banned phrase: '{phrase}'")
    return problems


def is_clean(text: str) -> bool:
    return not violations(text)


# Required email body structure (matches templates/competitor_cold_intro.txt).
GREETING_PREFIX = "Hi "
SIGN_OFF = "Harp\nFounder, X Analyst"
# Length band (words). Widened so a template-length ~270-word draft passes, but
# runaway drafts regenerate.
MIN_WORDS = 140
MAX_WORDS = 350   # 15% buffer over the ~270-300w the LLM naturally writes, so a
                  # 2-word overage no longer kills a draft after 4 retries


def format_violations(body: str) -> list[str]:
    """Structural checks on an email BODY. Empty list == well-formed.

    Hard rules (enforced in code, not by prompt judgment): the body must open
    with a "Hi " greeting, end with the exact "Harp\\nFounder, X Analyst"
    sign-off block, contain at least one blank-line paragraph break, and fall
    within the 140-350 word band.
    """
    if not body or not body.strip():
        return ["empty body"]
    norm = body.replace("\r\n", "\n").strip()
    problems: list[str] = []
    if not norm.startswith(GREETING_PREFIX):
        problems.append("body does not start with 'Hi '")
    if not norm.endswith(SIGN_OFF):
        problems.append("body does not end with the 'Harp / Founder, X Analyst' sign-off")
    elif not norm[:-len(SIGN_OFF)].endswith("\n\n"):
        # sign-off must be its own block: a blank line must precede it, so the
        # closing sentence never jams straight into "Harp".
        problems.append("sign-off must be preceded by a blank line")
    if "\n\n" not in norm:
        problems.append("body has no blank-line paragraph breaks")
    wc = len(norm.split())
    if wc < MIN_WORDS:
        problems.append(f"body too short ({wc} words, min {MIN_WORDS})")
    elif wc > MAX_WORDS:
        problems.append(f"body too long ({wc} words, max {MAX_WORDS})")
    return problems


def is_well_formed(body: str) -> bool:
    return not format_violations(body)


def sanitize(text: str) -> str:
    """Deterministic last-resort fixups for dash characters only.

    Never silently rewrites banned phrases (those must be regenerated), but a
    stray em/en dash can be safely normalized to a comma-space.
    """
    if not text:
        return text
    text = text.replace(EM_DASH, ", ").replace(EN_DASH, "-")
    text = DOUBLE_HYPHEN.sub(",", text)
    # collapse ", ," artifacts
    text = re.sub(r",\s*,", ",", text)
    return text


def enforce(generate: Callable[[], str], max_attempts: int = 3) -> str:
    """Call `generate` until it returns clean text.

    On the final attempt, apply dash sanitization as a safety net. Raises
    ValueError if banned phrases still remain after all attempts.
    """
    last = ""
    for attempt in range(max_attempts):
        last = generate() or ""
        if is_clean(last):
            return last
    # Final safety net: fix dashes deterministically, re-check.
    fixed = sanitize(last)
    remaining = violations(fixed)
    if remaining:
        raise ValueError(f"draft still violates style after {max_attempts} attempts: {remaining}")
    return fixed
