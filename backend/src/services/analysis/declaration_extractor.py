"""L0 — Extraction GÉNÉRALE de déclarations (Grand Livre exhaustif).

Segmente chaque prise de parole (post X / article presse) en assertions atomiques
de TOUS types (factuel_quantitatif|qualitatif, normatif, predictif, attributif) via
LLM contraint par schéma, et les range dans la table `claims` (le Grand Livre).

Garde-fou de légitimité (specs §2.1) : le `verbatim` rendu par le LLM doit être une
sous-chaîne RÉELLE du texte source (à la normalisation près) — sinon on rejette
(rien d'inventé n'entre dans le substrat). Le `canonical` n'ajoute rien d'absent.

Sans LLM (clé absente) : aucune déclaration n'est créée (on ne fabrique pas de
substrat à partir de rien). Idempotent (dedup par source+verbatim).
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session_factory
from src.models.article import Article
from src.models.claim import Claim
from src.models.personality import Personality
from src.models.post import Post
from src.services.analysis.claim_llm import (
    DECLARATION_PROMPT_VERSION,
    Declaration,
    get_claim_llm,
)
from src.utils import sha256, strip_accents

logger = structlog.get_logger(__name__)

_WS = re.compile(r"\s+")
_URL = re.compile(r"https?://\S+|www\.\S+")
_ALPHA = re.compile(r"[A-Za-zÀ-ÿ]{2,}")


def worth_segmenting(text: str | None) -> bool:
    """Pré-filtre DÉTERMINISTE (gratuit) avant tout appel LLM : on ne segmente que
    du texte qui porte du contenu (≥ 5 mots alpha hors liens). Évite de brûler du
    LLM sur des tweets « lien seul », emojis, ou trop courts (maîtrise du coût)."""
    if not text:
        return False
    return len(_ALPHA.findall(_URL.sub("", text))) >= 5
# Normalise guillemets/apostrophes/tirets « typographiques » → ASCII, pour comparer.
_QUOTES = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"', "’": "'", "‘": "'",
                         "–": "-", "—": "-", "…": "..."})


def _canon(s: str) -> str:
    """Forme comparable : sans accents, guillemets neutralisés, espaces compactés.

    Les guillemets (« » " ") sont remplacés par des espaces — leur présence et leur
    espacement interne varient (français : « texte » avec espaces) et ne doivent pas
    faire échouer la vérif. Apostrophes/tirets conservés (mots : « d'abord »)."""
    s = s.translate(_QUOTES).replace('"', " ")
    return _WS.sub(" ", strip_accents(s)).strip().lower()


def verbatim_in_source(verbatim: str, source: str) -> bool:
    """Le verbatim est-il réellement présent dans le texte source ? (anti-hallu)

    Tolère la normalisation (accents, guillemets, espaces) mais EXIGE que le LLM
    n'ait pas inventé/altéré le propos. Verbatim trop court = rejeté (pas une preuve).
    """
    v = _canon(verbatim)
    if len(v) < 12:
        return False
    return v in _canon(source)


def _dedup_key(src_ref: str, verbatim: str) -> str:
    return sha256(f"decl:{src_ref}:{_canon(verbatim)}")[:64]


async def _store(
    db: AsyncSession, *, decl: Declaration, src_ref: str, platform: str,
    post_id: int | None, article_id: int | None, personality_id: int | None,
    speaker_name: str | None, party: str | None, published_at, model: str,
) -> bool:
    if not decl.check_worthy:
        return False
    if not verbatim_in_source(decl.verbatim, _SRC_CACHE.get(src_ref, "")):
        logger.debug("decl.verbatim_rejected", src=src_ref, v=decl.verbatim[:60])
        return False
    dk = _dedup_key(src_ref, decl.verbatim)
    if await db.scalar(select(Claim.id).where(Claim.dedup_key == dk)):
        return False
    db.add(Claim(
        platform=platform, post_id=post_id, article_id=article_id,
        personality_id=personality_id, speaker_name=speaker_name, party=party,
        verbatim=decl.verbatim[:2000], canonical=(decl.canonical or None),
        claim_type=decl.claim_type, theme=(decl.theme if decl.theme != "autre" else None),
        stance_polarity=decl.stance_polarity, published_at=published_at,
        extraction_method="llm_segment", extraction_model=model,
        confidence=0.7, dedup_key=dk,
    ))
    return True


# Cache texte source par ref (pour la vérif verbatim sans le re-passer partout).
_SRC_CACHE: dict[str, str] = {}


async def run_declaration_extraction(
    limit_posts: int = 500, limit_articles: int = 300
) -> dict:
    llm = get_claim_llm()
    if not llm.available():
        return {"declarations_new": 0, "skipped": "LLM indisponible (clé tier-2 absente)"}

    factory = get_session_factory()
    model = f"{get_claim_llm()._s.claim_tier2_provider}:{get_claim_llm()._s.claim_tier2_model}/{DECLARATION_PROMPT_VERSION}"
    n_new = posts_done = arts_done = skipped = 0
    _SRC_CACHE.clear()

    # Coût : on ne re-segmente JAMAIS une source déjà traitée (1 requête en amont).
    async with factory() as db:
        done_posts = set((await db.execute(
            select(Claim.post_id).where(
                Claim.extraction_method == "llm_segment", Claim.post_id.isnot(None)
            )
        )).scalars().all())
        done_arts = set((await db.execute(
            select(Claim.article_id).where(
                Claim.extraction_method == "llm_segment", Claim.article_id.isnot(None)
            )
        )).scalars().all())
        posts = (
            await db.execute(
                select(Post, Personality)
                .join(Personality, Post.personality_id == Personality.id)
                .where(Post.is_retweet.is_(False))
                .order_by(Post.published_at.desc().nullslast())
                .limit(limit_posts)
            )
        ).all()

    for post, p in posts:
        # Garde-fous coût (gratuits) AVANT l'appel LLM : déjà fait / bruit.
        if post.id in done_posts or not worth_segmenting(post.content):
            skipped += 1
            continue
        src_ref = f"post{post.id}"
        _SRC_CACHE[src_ref] = post.content or ""
        result = await llm.segment_declarations(text=post.content, speaker=p.full_name)
        posts_done += 1
        if not result or not result.has_declaration:
            continue
        async with factory() as db:
            for decl in result.declarations:
                if await _store(
                    db, decl=decl, src_ref=src_ref, platform="x", post_id=post.id,
                    article_id=None, personality_id=p.id, speaker_name=p.full_name,
                    party=(p.famille or p.group_code), published_at=post.published_at,
                    model=model,
                ):
                    n_new += 1
            await db.commit()

    async with factory() as db:
        arts = (
            await db.execute(
                select(Article).order_by(Article.published_at.desc().nullslast())
                .limit(limit_articles)
            )
        ).scalars().all()

    for art in arts:
        text = f"{art.title}. {art.content}"
        if art.id in done_arts or not worth_segmenting(text):
            skipped += 1
            continue
        src_ref = f"art{art.id}"
        _SRC_CACHE[src_ref] = text
        mp = art.matched_personalities or []
        speaker = mp[0] if len(mp) == 1 else None
        result = await llm.segment_declarations(text=text, speaker=speaker)
        arts_done += 1
        if not result or not result.has_declaration:
            continue
        async with factory() as db:
            for decl in result.declarations:
                if await _store(
                    db, decl=decl, src_ref=src_ref, platform="press", post_id=None,
                    article_id=art.id, personality_id=None, speaker_name=speaker,
                    party=None, published_at=art.published_at, model=model,
                ):
                    n_new += 1
            await db.commit()

    stats = {"declarations_new": n_new, "posts_processed": posts_done,
             "articles_processed": arts_done, "skipped_no_llm": skipped,
             "prompt_version": DECLARATION_PROMPT_VERSION}
    logger.info("declarations.extracted", **stats)
    return stats
