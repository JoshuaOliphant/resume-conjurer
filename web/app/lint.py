# ABOUTME: Grimoire style checks run on the stitched cover letter (the CompositionPort lint piece).
# ABOUTME: Pure functions over text; results are computed from the real document, never hardcoded.
"""Style linting for the stitched documents.

Mirrors the pure-regex/counting checks the CLI pipeline's `lint.py` runs, scoped
to what the web review screen surfaces. Computed from the actual stitched text so
the displayed result can't drift from what's on screen — the product's "won't
pretend" stance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

COVER_LETTER_WORD_LIMIT = 350
FILLER_WORDS = ("very", "really", "in order to")
GENERIC_OPENERS = ("i am excited", "i am writing", "i am thrilled", "as a")


@dataclass(frozen=True)
class LintCheck:
    label: str
    detail: str
    passed: bool


def lint_cover_letter(cover_text: str) -> list[LintCheck]:
    """Run the grimoire checklist against the stitched cover letter."""
    lower = cover_text.lower()
    has_em_dash = "—" in cover_text or "--" in cover_text
    fillers = [p for p in FILLER_WORDS if re.search(rf"\b{re.escape(p)}\b", lower)]
    generic_opener = lower.lstrip().startswith(GENERIC_OPENERS)
    words = len(cover_text.split())
    return [
        LintCheck(
            "No em dashes in prose",
            "Checked the cover letter." if not has_em_dash else "Found an em dash.",
            not has_em_dash,
        ),
        LintCheck(
            "No filler words",
            "No 'very', 'really', 'in order to'."
            if not fillers
            else f"Found: {', '.join(fillers)}.",
            not fillers,
        ),
        LintCheck(
            "No AI-generic openers",
            "Opening doesn't start with 'I am excited to'."
            if not generic_opener
            else "Opens with a generic phrase.",
            not generic_opener,
        ),
        LintCheck(
            "Cover letter under 350 words",
            f"Currently {words} words.",
            words < COVER_LETTER_WORD_LIMIT,
        ),
    ]
