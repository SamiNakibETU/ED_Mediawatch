"""Classification d'un item de presse vis-à-vis des voix d'extrême droite.

100% déterministe (aucun LLM). Deux questions :
  1. L'item concerne-t-il vraiment le RN / affiliés (parti ou figure suivie) ?
  2. NATURE : `prise_de_parole` (une figure ED s'exprime réellement — interview,
     tribune, citation/position attribuée) vs `mention` (le RN est nommé/couvert,
     sans parole directe).

Robustesse (« blindé ») :
  * Matching par **frontière de mot** (regex \\b) — fini « Ranc » ⊂ « France ».
  * Figure reconnue par **nom complet** d'abord (spécifique) ; nom de famille
    seul seulement s'il est **non ambigu** (≥5 lettres, hors mots/villes
    courants) ou **curé** (figures_noyau).
  * `prise_de_parole` exige une **attribution** : « selon X », un verbe de parole
    *fort* près de la figure, un format d'interview, ou — pour les verbes à sens
    ambigu (critiquer/accuser…) — la figure en **position sujet** juste avant le
    verbe (« le RN dénonce », pas « le RN est dénoncé »).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from src.config import BACKEND_DIR
from src.utils import strip_accents

# Noms de famille à NE jamais matcher seuls (collisions : mots/villes/prénoms).
_AMBIGUOUS_SURNAMES = {
    "paris", "pen", "blanc", "roy", "loir", "ranc", "bay", "vos", "bloch",
    "perez", "diaz", "bigot", "jolly", "gery", "vert", "bon", "petit", "noir",
    "leroy", "martin", "bernard", "robert", "richard", "michel",
}

# Verbes « forts » : la figure s'exprime quel que soit le sens de phrase.
_STRONG_VERBS = [
    "declare", "declarait", "a declare", "affirme", "affirmait", "a affirme",
    "estime", "a estime", "estimait", "propose", "a propose", "proposait",
    "promet", "a promis", "annonce", "a annonce", "assure", "a assure",
    "reclame", "a reclame", "plaide", "revendique", "deplore", "explique",
    "juge", "regrette", "insiste", "rappelle", "souhaite", "defend", "alerte",
    "confirme", "twitte", "tweete", "conclut", "ajoute", "poursuit", "lance",
    "a lance", "martele", "a martele", "met en garde", "previent", "ironise",
    "exige", "considere", "repond", "a repondu", "veut", "vante", "a ecrit",
    "a poste", "reagit", "a reagi", "s indigne", "s insurge",
]

# Verbes à direction ambiguë : ne comptent que si la figure est SUJET juste avant.
_DIR_VERBS = [
    "denonce", "accuse", "critique", "condamne", "tacle", "fustige",
    "interpelle", "qualifie", "pointe", "salue", "met en cause",
]

_INTERVIEW_MARKERS = [
    "interview", "entretien", "tribune", "au micro", "sur le plateau",
    "interroge", "questionne", "invite de", "grand jury", "dans un communique",
    "communique de", "porte parole",
]

_QUOTE_RE = re.compile(r"[«»“”]|\"")


@lru_cache
def _keywords() -> dict:
    path = BACKEND_DIR / "data" / "rn_keywords.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(text or "")).lower()


def _alt(terms) -> str:
    uniq = sorted({t for t in terms if t}, key=len, reverse=True)
    return "|".join(re.escape(t) for t in uniq)


@lru_cache
def _static() -> dict:
    kw = _keywords()
    return {
        "parties": [strip_accents(p).lower() for p in kw["parties"]],
        "sigles": [s.lower() for s in kw["sigles"]],
        "figures": [strip_accents(f).lower() for f in kw["figures_noyau"]],
    }


class RelevanceIndex:
    """Pré-compile le matching pour une liste de personnalités suivies."""

    def __init__(self, full_names: list[str]) -> None:
        sp = _static()
        names: set[str] = set(sp["figures"])
        self._display: dict[str, str] = {}

        for full in full_names:
            n = _norm(full)
            toks = n.split()
            if len(toks) >= 2:
                names.add(n)
                self._display[n] = full
            if toks:
                surname = toks[-1]
                if len(surname) >= 5 and surname not in _AMBIGUOUS_SURNAMES:
                    names.add(surname)
                    self._display.setdefault(surname, full)
        for f in sp["figures"]:
            self._display.setdefault(f, f.title())

        party_terms = sp["parties"] + sp["sigles"]
        speakers = _alt(list(names) + party_terms)
        self._name_re = re.compile(rf"\b(?:{_alt(names)})\b")
        self._party_re = re.compile(rf"\b(?:{_alt(party_terms)})\b")
        self._speaker_re = re.compile(rf"\b(?:{speakers})\b")
        self._strong_re = re.compile(rf"\b(?:{_alt(_STRONG_VERBS)})\b")
        self._interview_re = re.compile(rf"\b(?:{_alt(_INTERVIEW_MARKERS)})\b")
        self._attr_re = re.compile(
            rf"\b(?:selon|d apres)\s+(?:[a-z'-]+\s+){{0,2}}(?:{speakers})\b"
        )
        # Figure SUJET immédiatement avant un verbe directionnel.
        self._dir_subject_re = re.compile(
            rf"\b(?:{speakers})\b\s+(?:(?:a|ont|se|s|y|ne|n|qui)\s+)?"
            rf"(?:[a-z]+ement\s+)?(?:{_alt(_DIR_VERBS)})\b"
        )

    def assess(self, text: str) -> dict:
        norm = _norm(text)
        figures = sorted({m.group(0) for m in self._name_re.finditer(norm)})
        party = bool(self._party_re.search(norm))
        relevant = bool(figures or party)

        nature = None
        if relevant:
            nature = "prise_de_parole" if self._is_prise_de_parole(norm) else "mention"

        keywords = sorted({
            (m.group(0).upper() if len(m.group(0)) <= 3 else m.group(0))
            for m in self._party_re.finditer(norm)
        })
        return {
            "relevant": relevant,
            "nature": nature,
            "is_statement": nature == "prise_de_parole",
            "personalities": [self._display.get(f, f.title()) for f in figures],
            "keywords": keywords,
        }

    def _is_prise_de_parole(self, norm: str) -> bool:
        if self._attr_re.search(norm):            # « selon X »
            return True
        if self._dir_subject_re.search(norm):     # « le RN dénonce … »
            return True
        for m in self._speaker_re.finditer(norm):  # verbe fort / interview à proximité
            window = norm[max(0, m.start() - 30): m.end() + 30]
            if self._strong_re.search(window) or self._interview_re.search(window):
                return True
        return False


def build_index(full_names: list[str]) -> RelevanceIndex:
    return RelevanceIndex(full_names)
