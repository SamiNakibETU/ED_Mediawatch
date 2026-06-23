"""Relevance filter: does a press item mention / report an RN (& affiliés) voice?

Lightweight lexical pass (fast, deterministic, free) that runs on every RSS
entry before we pay for full-text extraction. The LLM/NLP thematic +
inconsistency layer comes later and operates only on what this keeps.
"""

from __future__ import annotations

import json
from functools import lru_cache

from src.config import BACKEND_DIR
from src.utils import strip_accents


@lru_cache
def _keywords() -> dict:
    path = BACKEND_DIR / "data" / "rn_keywords.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _word_present(needle: str, haystack: str) -> bool:
    """Substring match with word-ish boundaries for short sigles (rn, udr)."""
    if len(needle) <= 3:
        padded = f" {haystack} "
        return f" {needle} " in padded or f" {needle}," in padded or f" {needle}." in padded
    return needle in haystack


def assess(text: str, personality_surnames: set[str]) -> dict:
    """Return relevance verdict for a normalized-or-raw text blob.

    -> {"relevant": bool, "is_statement": bool,
        "keywords": [...], "personalities": [...]}
    """
    norm = strip_accents(text)
    kw = _keywords()

    matched_kw: list[str] = []
    for bucket in ("parties", "figures_noyau"):
        for term in kw[bucket]:
            if _word_present(strip_accents(term), norm):
                matched_kw.append(term)
    for sigle in kw["sigles"]:
        if _word_present(sigle, norm):
            matched_kw.append(sigle.upper())

    matched_people: list[str] = []
    for surname in personality_surnames:
        s = strip_accents(surname)
        if len(s) >= 4 and _word_present(s, norm):
            matched_people.append(surname)

    relevant = bool(matched_kw or matched_people)
    is_statement = False
    if relevant and (matched_people or any(f in matched_kw for f in kw["figures_noyau"])):
        is_statement = any(strip_accents(m) in norm for m in kw["statement_markers"])

    return {
        "relevant": relevant,
        "is_statement": is_statement,
        "keywords": sorted(set(matched_kw)),
        "personalities": sorted(set(matched_people)),
    }
