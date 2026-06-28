"""Détection de quantités chiffrées en français (montants + unités).

Tier déterministe de l'extraction de claims : repère les expressions du type
« 40 milliards d'euros », « 90 Md€ », « 3,5 % », « 35 000 expulsions »,
« 64 ans », et les classe par `unit_kind` pour comparaison entre claims.
Gratuit, déterministe, sans LLM — sert de filtre check-worthiness + extraction
brute. Le tier LLM (optionnel) raffine ensuite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# unit_kind canoniques
MILLIARDS_EUR = "milliards_eur"
MILLIONS_EUR = "millions_eur"
PCT = "pct"
ANS = "ans"
EUR = "eur"
NB = "nb"


@dataclass
class Quantity:
    value: float
    unit_kind: str
    raw: str
    start: int
    end: int


# espaces possibles entre milliers (espace normal, insécable, fine insécable)
_SPACES = "    "
_NUM = r"\d{1,3}(?:[%s.]\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?" % _SPACES


def _to_float(s: str) -> float | None:
    for sp in _SPACES:
        s = s.replace(sp, "")
    s = s.replace(",", ".")          # virgule = décimale FR
    if s.count(".") > 1:             # points multiples = séparateurs de milliers
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


# Ordre = priorité (du plus spécifique au plus générique).
_PATTERNS: list[tuple[str, str]] = [
    (rf"({_NUM})\s*(?:milliards?|mds?|md)\s*(?:d['’]?euros|€|eur)?", MILLIARDS_EUR),
    (rf"({_NUM})\s*(?:millions?|m)\s*(?:d['’]?euros|€|eur)?", MILLIONS_EUR),
    (rf"({_NUM})\s*(?:%|pour\s*cent|pourcent)", PCT),
    (rf"({_NUM})\s*ans?\b", ANS),
    (rf"({_NUM})\s*(?:€|euros?)\b", EUR),
]

_COMPILED = [(re.compile(rx, re.IGNORECASE), kind) for rx, kind in _PATTERNS]
_PLAIN_NUM = re.compile(rf"\b({_NUM})\b")

# Un nombre nu suivi de l'une de ces unités N'EST PAS un compte générique : il
# mesure autre chose (temps, monnaie déjà typée, mesure, amendements, victimes…).
# Élimine les faux positifs « 210 jours », « 400 sous-amendements », « 178 blessés »
# captés à tort comme « nb d'expulsions / de recrutements » (précision §4).
_DISQUALIFY_AFTER = re.compile(
    r"\s*(?:de\s+|d['’])?"
    r"(?:jours?|journ[ée]es?|mois|heures?|semaines?|minutes?|secondes?|"
    r"euros?|€|%|amendements?|sous[-\s]?amendements?|articles?|pages?|"
    r"degr[ée]s?|km|kg|m[²2]|litres?)\b",
    re.IGNORECASE,
)
# Contexte « victimes » dans la fenêtre proche (≤ 40 car.) : un bilan de
# blessés/morts n'est jamais un de nos référents quantitatifs.
_CASUALTY_NEAR = re.compile(r"bless[ée]s?|morts?|tu[ée]s?|victimes?|d[ée]c[ée]d", re.IGNORECASE)


def find_quantities(text: str) -> list[Quantity]:
    """Toutes les quantités explicites (avec unité) du texte."""
    out: list[Quantity] = []
    claimed: list[tuple[int, int]] = []
    for rx, kind in _COMPILED:
        for m in rx.finditer(text):
            val = _to_float(m.group(1))
            if val is None:
                continue
            span = (m.start(), m.end())
            if any(s < span[1] and span[0] < e for s, e in claimed):
                continue
            claimed.append(span)
            out.append(Quantity(val, kind, m.group(0).strip(), *span))
    return out


def _looks_like_year(raw: str, val: float) -> bool:
    digits = raw.strip()
    return (
        val == int(val)
        and 1900 <= val <= 2099
        and re.fullmatch(r"\d{4}", digits) is not None  # 4 chiffres nus, sans séparateur
    )


def find_plain_numbers(
    text: str, exclude_spans: list[tuple[int, int]] | None = None
) -> list[Quantity]:
    """Grands nombres « nus » (sans unité) — candidats pour les référents en `nb`.

    Exclut : les années (1900-2099 en 4 chiffres nus) ; les nombres déjà couverts
    par une quantité TYPÉE (`exclude_spans` : euros/%/ans → « 6000 euros » n'est pas
    un compte) ; les nombres suivis d'une unité disqualifiante (jours, amendements,
    blessés… → mesurent autre chose). Précision d'abord, le LLM raffine ensuite.
    """
    exclude_spans = exclude_spans or []
    out: list[Quantity] = []
    for m in _PLAIN_NUM.finditer(text):
        raw = m.group(1)
        val = _to_float(raw)
        if val is None or val < 100:  # ignore les petits nombres bruités
            continue
        if _looks_like_year(raw, val):
            continue
        span = (m.start(), m.end())
        if any(s < span[1] and span[0] < e for s, e in exclude_spans):
            continue  # déjà capté comme quantité typée (euros, %, ans…)
        if _DISQUALIFY_AFTER.match(text, m.end()):
            continue  # « 210 jours », « 400 sous-amendements »…
        if _CASUALTY_NEAR.search(text[m.end(): m.end() + 40]):
            continue  # « 178 policiers et gendarmes blessés »…
        out.append(Quantity(val, NB, m.group(0).strip(), *span))
    return out
