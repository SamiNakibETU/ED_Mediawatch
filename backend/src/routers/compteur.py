"""Le Compteur — « à combien le chiffrez-vous ? »

[EN PAUSE — analyse] Sous-système d'ANALYSE gelé pour le MVP « Revue de veille »
(cf. docs/MVP_SPEC.md §0 et §12 « Différé »). LLM coupé. Ne pas étendre tant que
le socle de veille n'est pas atteint ; masqué de la nav principale (spec §8).

Pour chaque référent suivi, toutes les valeurs annoncées dans le temps, par qui.
Matérialise « les chiffres ne collent pas » : dispersion d'un coup d'œil.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.claim import Claim
from src.models.referentiel import Referent
from src.security import require_token
from src.services.analysis.claim_sources import resolve_claim_urls

router = APIRouter(tags=["compteur"])


@router.get("/compteurs")
async def list_compteurs(db: AsyncSession = Depends(get_db)) -> dict:
    """Référents quantitatifs ayant des claims, avec dispersion des valeurs."""
    rows = (
        await db.execute(
            select(
                Claim.referent_key,
                func.count(Claim.id),
                func.min(Claim.qty_value),
                func.max(Claim.qty_value),
                func.avg(Claim.qty_value),
                Claim.qty_unit,
            )
            .where(Claim.qty_value.isnot(None), Claim.referent_key.isnot(None))
            .group_by(Claim.referent_key, Claim.qty_unit)
            .order_by(func.count(Claim.id).desc())
        )
    ).all()

    labels = dict(
        (await db.execute(select(Referent.key, Referent.label))).all()
    )
    out = []
    for key, n, vmin, vmax, vavg, unit in rows:
        spread = (vmax - vmin) if (vmax is not None and vmin is not None) else 0
        out.append({
            "referent_key": key,
            "label": labels.get(key, key),
            "unit": unit,
            "n_claims": n,
            "min": vmin, "max": vmax, "avg": round(vavg, 2) if vavg else None,
            "spread": round(spread, 2),
        })
    return {"compteurs": out}


@router.get("/compteur")
async def compteur(
    key: str = Query(..., description="referent_key"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Série temporelle de toutes les valeurs annoncées pour un référent."""
    ref = await db.get(Referent, key)
    claims = (
        await db.execute(
            select(Claim)
            .where(Claim.referent_key == key, Claim.qty_value.isnot(None))
            .order_by(Claim.published_at.asc().nullslast())
        )
    ).scalars().all()

    urls = await resolve_claim_urls(db, claims)
    points = [
        {
            "claim_id": c.id,
            "value": c.qty_value,
            "unit": c.qty_unit,
            "speaker": c.speaker_name,
            "party": c.party,
            "platform": c.platform,
            "published_at": c.published_at,
            "verbatim": c.verbatim,
            "confidence": c.confidence,
            "human_validated": c.human_validated,
            "source_url": urls.get(c.id),
        }
        for c in claims
    ]
    return {
        "referent_key": key,
        "label": ref.label if ref else key,
        "unit": ref.unit if ref else None,
        "n": len(points),
        "points": points,
    }


@router.post("/extract-claims", dependencies=[Depends(require_token)])
async def trigger_extract(
    use_llm: bool | None = Query(None),
    reset: bool = Query(False, description="purge les claims existants avant de rejouer"),
) -> dict:
    """Extraction des claims quantitatifs (posts + presse).

    use_llm: None = suit LLM_REFINE_ENABLED ; true/false = force le raffinage LLM.
    reset: vide la table claims d'abord (les contradictions liées sont
    supprimées en cascade) — utile pour rejouer après un changement de logique LLM.
    """
    from src.services.analysis.claim_extractor import run_claim_extraction

    return await run_claim_extraction(use_llm=use_llm, reset=reset)


@router.post("/embed-claims", dependencies=[Depends(require_token)])
async def trigger_embed_claims(limit: int = Query(2000, ge=1, le=10000)) -> dict:
    """Calcule les embeddings manquants des claims (A0, idempotent)."""
    from src.services.analysis.claim_embeddings import embed_claims

    return await embed_claims(limit=limit)


@router.get("/near-duplicate-claims")
async def near_duplicate_claims(threshold: float = Query(0.92, ge=0.5, le=1.0)) -> dict:
    """Groupes de claims quasi identiques (même assertion répétée) — qualité du Compteur."""
    from src.services.analysis.claim_embeddings import near_duplicate_groups

    groups = await near_duplicate_groups(threshold=threshold)
    return {"threshold": threshold, "groups": len(groups), "items": groups}


@router.post("/extract-declarations", dependencies=[Depends(require_token)])
async def trigger_extract_declarations(
    limit_posts: int = Query(500, ge=1, le=5000),
    limit_articles: int = Query(300, ge=1, le=5000),
) -> dict:
    """L0 — segmente posts/articles en déclarations (tous types) → Grand Livre."""
    from src.services.analysis.declaration_extractor import run_declaration_extraction

    return await run_declaration_extraction(
        limit_posts=limit_posts, limit_articles=limit_articles
    )


@router.get("/grand-livre")
async def grand_livre(
    speaker: str | None = Query(None, description="nom du locuteur (sous-chaîne)"),
    party: str | None = Query(None),
    theme: str | None = Query(None),
    claim_type: str | None = Query(None, description="factuel_quantitatif|factuel_qualitatif|normatif|predictif|attributif"),
    platform: str | None = Query(None, description="x | press"),
    q: str | None = Query(None, description="recherche plein-texte sur le verbatim"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Le Grand Livre (L0) — toutes les déclarations, navigables/requêtables."""
    stmt = select(Claim).order_by(Claim.published_at.desc().nullslast(), Claim.id.desc())
    count_stmt = select(func.count(Claim.id))
    filters = []
    if speaker:
        filters.append(Claim.speaker_name.ilike(f"%{speaker}%"))
    if party:
        filters.append(Claim.party == party)
    if theme:
        filters.append(Claim.theme == theme)
    if claim_type:
        filters.append(Claim.claim_type == claim_type)
    if platform:
        filters.append(Claim.platform == platform)
    if q:
        filters.append(Claim.verbatim.ilike(f"%{q}%"))
    for f in filters:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    total = await db.scalar(count_stmt) or 0
    rows = list((await db.execute(stmt.limit(limit).offset(offset))).scalars().all())
    return {
        "total": total, "limit": limit, "offset": offset,
        "items": [
            {
                "id": c.id, "platform": c.platform, "speaker_name": c.speaker_name,
                "party": c.party, "claim_type": c.claim_type, "theme": c.theme,
                "stance_polarity": c.stance_polarity, "verbatim": c.verbatim,
                "canonical": c.canonical, "published_at": c.published_at,
                "referent_key": c.referent_key, "qty_value": c.qty_value,
                "extraction_method": c.extraction_method, "human_validated": c.human_validated,
            }
            for c in rows
        ],
    }
