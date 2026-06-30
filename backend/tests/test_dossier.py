"""L2 — bornage du contexte LLM du dossier (coût maîtrisé)."""

from datetime import datetime, timezone

from src.services.analysis.dossier_generator import build_facts


class _C:
    def __init__(self, text, theme="immigration", ct="normatif", d="2026-06-01"):
        self.canonical = text
        self.verbatim = text
        self.theme = theme
        self.claim_type = ct
        self.published_at = datetime.fromisoformat(d + "T00:00:00+00:00")


def test_facts_capped():
    claims = [_C(f"déclaration numéro {i}") for i in range(120)]
    facts = build_facts(claims, cap=40)
    assert facts.count("\n") + 1 == 40       # borné à 40 lignes → prompt maîtrisé


def test_facts_format_dated_and_typed():
    facts = build_facts([_C("il faut rétablir la double peine", d="2026-05-12")])
    assert "[2026-05-12]" in facts
    assert "(immigration/normatif)" in facts
    assert "double peine" in facts


def test_facts_empty():
    assert build_facts([]) == ""
