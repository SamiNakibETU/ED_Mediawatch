"""L2 — Dossier vivant par personnalité (synthèse RAG, coût borné).

Pour une figure : on rassemble des **faits déterministes** (volumétrie par thème/
type, période, contradictions impliquées — GRATUIT), puis UN SEUL appel LLM sur un
**échantillon borné** de ses déclarations (RAG) pour une synthèse neutre, cachée et
versionnée. Régénéré à la demande, jamais à chaque vue.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, or_, select

from src.database import get_session_factory
from src.models.claim import Claim
from src.models.contradiction import Contradiction
from src.models.dossier import Dossier
from src.models.personality import Personality
from src.services.analysis.claim_llm import DOSSIER_PROMPT_VERSION, get_claim_llm

logger = structlog.get_logger(__name__)

# Coût : pas de dossier sous ce seuil (rien à synthétiser) ; contexte LLM borné.
MIN_CLAIMS = 3
FACTS_CAP = 50


def build_facts(claims: list[Claim], cap: int = FACTS_CAP) -> str:
    """Échantillon borné de déclarations, formaté daté pour le contexte LLM.

    Claims supposés triés (récents d'abord) ; on en garde au plus `cap` → prompt
    de taille maîtrisée quelle que soit la prolixité de la figure."""
    lines = []
    for c in claims[:cap]:
        d = c.published_at.date().isoformat() if c.published_at else "?"
        text = (c.canonical or c.verbatim or "").strip()[:200]
        lines.append(f"- [{d}] ({c.theme or '?'}/{c.claim_type or '?'}) {text}")
    return "\n".join(lines)


async def get_dossier(personality_id: int) -> dict | None:
    factory = get_session_factory()
    async with factory() as db:
        d = (await db.execute(
            select(Dossier).where(Dossier.personality_id == personality_id)
        )).scalar_one_or_none()
        if not d:
            return None
        return {
            "personality_id": personality_id, "summary": d.summary, "data": d.data,
            "n_claims": d.n_claims, "model": d.model, "generated_at": d.generated_at,
        }


async def generate_dossier(personality_id: int, force: bool = False) -> dict:
    factory = get_session_factory()
    llm = get_claim_llm()

    async with factory() as db:
        p = await db.get(Personality, personality_id)
        if not p:
            return {"error": "personnalité introuvable"}
        existing = (await db.execute(
            select(Dossier).where(Dossier.personality_id == personality_id)
        )).scalar_one_or_none()
        if existing and not force:
            return {"cached": True, "personality_id": personality_id,
                    "n_claims": existing.n_claims, "generated_at": existing.generated_at}
        claims = list((await db.execute(
            select(Claim).where(Claim.personality_id == personality_id)
            .order_by(Claim.published_at.desc().nullslast())
        )).scalars().all())

    if len(claims) < MIN_CLAIMS:
        return {"skipped": "trop peu de déclarations", "n_claims": len(claims)}
    if not llm.available():
        return {"skipped": "LLM indisponible (clé tier-2 absente)", "n_claims": len(claims)}

    # Faits déterministes (gratuits).
    ids = [c.id for c in claims]
    async with factory() as db:
        n_contra = await db.scalar(
            select(func.count(Contradiction.id)).where(
                or_(Contradiction.claim_a_id.in_(ids), Contradiction.claim_b_id.in_(ids))
            )
        ) or 0
    dates = [c.published_at for c in claims if c.published_at]
    stats = {
        "par_theme": dict(Counter(c.theme for c in claims if c.theme)),
        "par_type": dict(Counter(c.claim_type for c in claims if c.claim_type)),
        "contradictions_impliquees": n_contra,
        "periode": [min(dates).date().isoformat(), max(dates).date().isoformat()] if dates else None,
    }

    synth = await llm.synthesize_dossier(
        speaker=p.full_name, party=(p.famille or p.group_code),
        facts=build_facts(claims),
    )
    if synth is None:
        return {"error": "synthèse LLM échouée", "n_claims": len(claims)}

    model = f"{llm._s.claim_tier2_provider}:{llm._s.claim_tier2_model}/{DOSSIER_PROMPT_VERSION}"
    data = {**synth.model_dump(), "stats": stats}
    async with factory() as db:
        dossier = await db.get(Dossier, existing.id) if existing else Dossier(
            personality_id=personality_id
        )
        dossier.summary = synth.summary
        dossier.data = data
        dossier.n_claims = len(claims)
        dossier.model = model
        dossier.generated_at = datetime.now(timezone.utc)
        db.add(dossier)
        await db.commit()

    logger.info("dossier.generated", personality_id=personality_id, n_claims=len(claims))
    return {"generated": True, "personality_id": personality_id,
            "n_claims": len(claims), "stats": stats, "summary": synth.summary}
