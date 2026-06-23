"""Extraction de claims quantitatifs → alimente Le Compteur.

Tier 1 (déterministe, sans LLM) : pour chaque phrase, si un déclencheur de
référent est présent ET qu'une quantité d'unité compatible est trouvée, on émet
un claim `factuel_quantitatif` rattaché au `referent_key`. Gratuit, rejouable,
sert de générateur de candidats (validation humaine ensuite, cf specs).

Tier 2 (LLM, optionnel) : si une clé est configurée, raffine canonical/horizon/
modality. Hook présent, inactif sans clé.
"""

from __future__ import annotations

import json
import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import BACKEND_DIR, get_settings
from src.database import get_session_factory
from src.models.article import Article
from src.models.claim import Claim
from src.models.personality import Personality
from src.models.post import Post
from src.models.referentiel import Referent, Subtheme, Theme
from src.services.analysis.claim_llm import get_claim_llm
from src.services.analysis.quantity import find_plain_numbers, find_quantities
from src.utils import sha256, strip_accents

logger = structlog.get_logger(__name__)

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_TRIGGERS_FILE = BACKEND_DIR / "data" / "referent_triggers.json"


def _load_triggers() -> dict:
    data = json.loads(_TRIGGERS_FILE.read_text(encoding="utf-8"))
    out = {}
    for key, spec in data["referents"].items():
        # frontière de mot : évite "epr" dans "représentant", "ame" dans "flamme"…
        patterns = [
            re.compile(r"\b" + re.escape(strip_accents(t).lower()) + r"\b")
            for t in spec["triggers"]
        ]
        out[key] = {
            "unit_kinds": set(spec["unit_kinds"]),
            "unit": spec["unit"],
            "patterns": patterns,
        }
    return out


def _sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENT_SPLIT.split(text or "") if s.strip()]
    return parts or ([text.strip()] if text and text.strip() else [])


def _dedup_key(src: str, ref: str, value: float, kind: str) -> str:
    return sha256(f"{src}:{ref}:{value}:{kind}")


def extract_from_text(text: str, triggers: dict) -> list[dict]:
    """Return list of {referent_key, value, unit, unit_kind, verbatim} for a text."""
    found: list[dict] = []
    for sent in _sentences(text):
        norm = strip_accents(sent).lower()
        quantities = find_quantities(sent)
        plains = None
        for ref_key, spec in triggers.items():
            trig_pos = -1
            for pat in spec["patterns"]:
                m = pat.search(norm)
                if m:
                    trig_pos = m.start()
                    break
            if trig_pos < 0:
                continue
            candidates = [q for q in quantities if q.unit_kind in spec["unit_kinds"]]
            if not candidates and "nb" in spec["unit_kinds"]:
                if plains is None:
                    plains = find_plain_numbers(sent)
                candidates = plains
            if not candidates:
                continue
            # quantité la plus proche du déclencheur
            q = min(candidates, key=lambda c: abs(c.start - trig_pos))
            found.append({
                "referent_key": ref_key,
                "value": q.value,
                "unit": spec["unit"],
                "unit_kind": q.unit_kind,
                "verbatim": sent[:600],
            })
    return found


async def _referent_index(db: AsyncSession) -> dict[str, tuple[str, str, str]]:
    """referent_key -> (theme_id, subtheme_id, label)."""
    rows = await db.execute(
        select(Referent.key, Subtheme.theme_id, Subtheme.id, Referent.label)
        .join(Subtheme, Referent.subtheme_id == Subtheme.id)
    )
    return {k: (theme, sub, label) for k, theme, sub, label in rows.all()}


async def _maybe_refine(llm, use_llm, c, speaker, ref_idx, allowed):
    """Return (referent_key, value, theme, sub, canonical, method, conf, extra) or None to drop."""
    theme, sub, _ = ref_idx.get(c["referent_key"], (None, None, c["referent_key"]))
    base = (c["referent_key"], c["value"], theme, sub, None, "deterministic", 0.5, {})
    if not use_llm:
        return base
    label = ref_idx.get(c["referent_key"], (None, None, c["referent_key"]))[2]
    refined = await llm.refine(
        sentence=c["verbatim"], speaker=speaker,
        candidate_referent_key=c["referent_key"], referent_label=label,
        value=c["value"], unit=c["unit"], allowed=allowed,
    )
    if refined is None:
        return base  # échec LLM → on garde le déterministe
    if not refined.is_valid_claim or refined.referent_key in ("none", "", None):
        return None  # faux positif écarté
    rk = refined.referent_key
    th, sb, _ = ref_idx.get(rk, (theme, sub, rk))
    extra = {"qty_horizon": refined.horizon, "qty_modality": refined.modality,
             "stance_polarity": refined.stance}
    return (rk, refined.value if refined.value is not None else c["value"],
            th, sb, refined.canonical, "llm", refined.confidence, extra)


async def run_claim_extraction(
    limit_posts: int = 5000,
    limit_articles: int = 5000,
    use_llm: bool | None = None,
    reset: bool = False,
) -> dict:
    triggers = _load_triggers()
    factory = get_session_factory()
    n_claims = 0

    llm = get_claim_llm()
    if use_llm is None:
        use_llm = get_settings().llm_refine_enabled
    use_llm = bool(use_llm) and llm.available()

    if reset:
        from sqlalchemy import delete

        from src.models.claim import Claim as _Claim
        from src.models.contradiction import Contradiction as _Contradiction

        async with factory() as db:
            # Contradictions d'abord (arêtes), puis claims (nœuds).
            await db.execute(delete(_Contradiction))
            await db.execute(delete(_Claim))
            await db.commit()
        logger.info("claims.reset")

    async with factory() as db:
        ref_idx = await _referent_index(db)
        allowed = [(k, v[2]) for k, v in ref_idx.items()]

        # --- Posts X (locuteur = personnalité) ---
        posts = (
            await db.execute(
                select(Post, Personality)
                .join(Personality, Post.personality_id == Personality.id)
                .where(Post.is_retweet.is_(False))
                .limit(limit_posts)
            )
        ).all()
        for post, p in posts:
            for c in extract_from_text(post.content, triggers):
                refined = await _maybe_refine(llm, use_llm, c, p.full_name, ref_idx, allowed)
                if refined is None:
                    continue
                rk, value, theme, sub, canonical, method, conf, extra = refined
                dk = _dedup_key(f"post{post.id}", rk, value, c["unit_kind"])
                if await db.scalar(select(Claim.id).where(Claim.dedup_key == dk)):
                    continue
                db.add(Claim(
                    platform="x", post_id=post.id, personality_id=p.id,
                    speaker_name=p.full_name, party=(p.famille or p.group_code),
                    verbatim=c["verbatim"], canonical=canonical,
                    claim_type="factuel_quantitatif",
                    theme=theme, subtheme=sub, referent_key=rk,
                    qty_value=value, qty_unit=c["unit"], qty_unit_kind=c["unit_kind"],
                    published_at=post.published_at, extraction_method=method,
                    confidence=conf, dedup_key=dk, **extra,
                ))
                n_claims += 1
        await db.commit()

        # --- Articles presse (locuteur = personnalité citée si unique) ---
        arts = (
            await db.execute(select(Article).limit(limit_articles))
        ).scalars().all()
        for art in arts:
            text = f"{art.title}. {art.content}"
            mp = art.matched_personalities or []
            speaker = mp[0] if len(mp) == 1 else None
            for c in extract_from_text(text, triggers):
                refined = await _maybe_refine(llm, use_llm, c, speaker, ref_idx, allowed)
                if refined is None:
                    continue
                rk, value, theme, sub, canonical, method, conf, extra = refined
                dk = _dedup_key(f"art{art.id}", rk, value, c["unit_kind"])
                if await db.scalar(select(Claim.id).where(Claim.dedup_key == dk)):
                    continue
                db.add(Claim(
                    platform="press", article_id=art.id, speaker_name=speaker,
                    verbatim=c["verbatim"], canonical=canonical,
                    claim_type="factuel_quantitatif",
                    theme=theme, subtheme=sub, referent_key=rk,
                    qty_value=value, qty_unit=c["unit"], qty_unit_kind=c["unit_kind"],
                    published_at=art.published_at, extraction_method=method,
                    confidence=max(conf, 0.0), dedup_key=dk, **extra,
                ))
                n_claims += 1
        await db.commit()

    stats = {"claims_new": n_claims, "posts_scanned": len(posts), "articles_scanned": len(arts)}
    logger.info("claims.extracted", **stats)
    return stats
