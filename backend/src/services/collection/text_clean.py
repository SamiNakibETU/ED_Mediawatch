"""Nettoyage du texte d'article — prêt pour l'analyse, fidèle au verbatim.

Appliqué à TOUT article quelle que soit la source d'extraction (scraper-service,
content:encoded RSS, fallback). Objectif (demandé) : ne garder QUE le corps de
l'article — pas de liens, pas de « Lire aussi », pas de partage/newsletter/crédits
/temps de lecture, pas de navigation. On ne réécrit PAS les phrases (fidélité au
verbatim = garde-fou crédibilité ROADMAP §6) : on retire le bruit hors-article,
on déréférence les liens (on garde le texte d'ancre), on normalise les espaces.
"""

from __future__ import annotations

import re

from src.utils import strip_accents

# Liens markdown [texte](url) → on garde « texte » (le lien part).
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# URLs nues + emails (ne font pas partie de la prose de l'article).
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTISPACE_RE = re.compile(r"[ \t ]+")
_MULTILINE_RE = re.compile(r"\n{3,}")

# Lignes-teasers / méta : si une ligne COMMENCE par l'un de ces marqueurs
# (normalisés sans accents), c'est du hors-article → ligne entière supprimée.
_DROP_PREFIX = [
    "lire aussi", "a lire aussi", "a lire egalement", "a lire", "voir aussi",
    "sur le meme sujet", "le meme sujet", "a decouvrir", "a voir aussi",
    "ceci peut vous interesser", "vous aimerez aussi", "ces articles peuvent",
    "dans la meme rubrique", "pour aller plus loin", "en savoir plus",
    "publie le", "mis a jour le", "modifie le", "credit photo", "credits photo",
    "photo :", "illustration :", "source afp", "avec afp", "abonnez-vous",
    "s'abonner", "newsletter", "inscrivez-vous", "recevez", "suivez-nous",
    "suivez l'actualite", "suivez toute l'actualite", "partager",
    "partagez", "tweeter", "commenter", "reagir", "0 commentaire",
    "la suite apres cette publicite", "publicite", "lecture :", "temps de lecture",
    "cet article est reserve", "video :", "regardez :", "en images",
]

# Marqueurs « contient » — ne suppriment une ligne que si elle est COURTE
# (≤ 9 mots) : un bouton/lien isolé, pas un paragraphe qui les mentionne.
_DROP_CONTAINS_SHORT = [
    "partager sur", "partager l'article", "sur facebook", "sur twitter",
    "sur whatsapp", "sur linkedin", "copier le lien", "min de lecture",
    "minutes de lecture", "accepter les cookies", "gerer les cookies",
    "afficher les commentaires", "laisser un commentaire", "tous droits reserves",
    "mots-cles", "voir les commentaires", "ajouter aux favoris",
]

_RT_RE = re.compile(r"^\s*\d+\s*min(utes)?\b")  # « 5 min », « 3 minutes » seuls


def _is_boilerplate(line: str) -> bool:
    norm = strip_accents(line).strip().lower()
    if not norm:
        return False
    if any(norm.startswith(p) for p in _DROP_PREFIX):
        return True
    if _RT_RE.match(norm) and len(norm.split()) <= 6:
        return True
    if len(norm.split()) <= 9 and any(c in norm for c in _DROP_CONTAINS_SHORT):
        return True
    return False


def clean_article_text(text: str | None) -> str:
    """Corps d'article propre : sans liens ni boilerplate, verbatim préservé."""
    if not text:
        return ""
    t = _HTML_TAG_RE.sub(" ", text)          # restes de balises éventuels
    t = _MD_LINK_RE.sub(r"\1", t)            # [texte](url) → texte
    t = _URL_RE.sub("", t)                    # URLs nues retirées
    t = _EMAIL_RE.sub("", t)                  # emails retirés

    kept: list[str] = []
    prev: str | None = None
    for raw in t.splitlines():
        line = _MULTISPACE_RE.sub(" ", raw).strip()
        if _is_boilerplate(line):
            continue
        if line and line == prev:             # dédoublonne lignes consécutives identiques
            continue
        kept.append(line)
        prev = line if line else prev

    out = "\n".join(kept)
    out = _MULTILINE_RE.sub("\n\n", out)      # ≤ 1 ligne vide d'affilée
    return out.strip()
