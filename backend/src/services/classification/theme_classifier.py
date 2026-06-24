"""Classification thématique déterministe (CAP), sans LLM.

Premier temps de la stratégie §6 : lexiques par thème/sous-thème, frontière de
mot, accents normalisés — gratuit, rejouable, transparent. Le thème retenu est
celui qui compte le plus de mots-clés distincts (codage mutuellement exclusif,
cadre §2) ; un thème secondaire est rendu s'il talonne. Le fallback Cohere
(cf. runner) tranche les items que le lexique rate (score 0).

Réutilise l'esprit regex/strip_accents de relevance.py.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from src.config import BACKEND_DIR
from src.utils import strip_accents

_WS_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", strip_accents(text or "")).strip()


def _alt(terms) -> str:
    # plus longs d'abord (matching gourmand des expressions multi-mots)
    uniq = sorted({strip_accents(t) for t in terms if t}, key=len, reverse=True)
    return "|".join(re.escape(t) for t in uniq)


def _compile(terms) -> re.Pattern:
    return re.compile(rf"(?<![a-z0-9])(?:{_alt(terms)})(?![a-z0-9])")


@lru_cache
def _lexicon() -> dict:
    path = BACKEND_DIR / "data" / "theme_lexicon.json"
    return json.loads(path.read_text(encoding="utf-8"))


class ThemeClassifier:
    """Pré-compile les regex de chaque thème/sous-thème du lexique."""

    def __init__(self, lexicon: dict | None = None) -> None:
        lex = (lexicon or _lexicon())["themes"]
        self._theme_re: dict[str, re.Pattern] = {}
        self._subtheme_re: dict[str, dict[str, re.Pattern]] = {}
        for theme_id, spec in lex.items():
            kws = spec.get("keywords", [])
            if kws:
                self._theme_re[theme_id] = _compile(kws)
            subs = spec.get("subthemes", {})
            if subs:
                self._subtheme_re[theme_id] = {
                    sid: _compile(words) for sid, words in subs.items() if words
                }

    def _score(self, regex: re.Pattern, norm: str) -> int:
        # nb de mots-clés DISTINCTS matchés (évite qu'un terme répété domine)
        return len({m.group(0) for m in regex.finditer(norm)})

    def classify(self, text: str) -> dict:
        norm = _norm(text)
        if not norm:
            return {"theme": None, "subtheme": None, "score": 0, "secondary": None}

        scores = {
            tid: self._score(rx, norm) for tid, rx in self._theme_re.items()
        }
        ranked = sorted(
            ((tid, s) for tid, s in scores.items() if s > 0),
            key=lambda kv: (kv[1], len(kv[0])),  # score, puis stable
            reverse=True,
        )
        if not ranked:
            return {"theme": None, "subtheme": None, "score": 0, "secondary": None}

        theme, score = ranked[0]
        secondary = ranked[1][0] if len(ranked) > 1 and ranked[1][1] >= 1 else None

        subtheme = None
        if theme in self._subtheme_re:
            sub_scores = {
                sid: self._score(rx, norm)
                for sid, rx in self._subtheme_re[theme].items()
            }
            best = max(sub_scores.items(), key=lambda kv: kv[1], default=(None, 0))
            subtheme = best[0] if best[1] > 0 else None

        return {"theme": theme, "subtheme": subtheme, "score": score, "secondary": secondary}


@lru_cache
def get_classifier() -> ThemeClassifier:
    return ThemeClassifier()


def reset_cache() -> None:
    """Tests : rejouer avec un lexique modifié."""
    _lexicon.cache_clear()
    get_classifier.cache_clear()
