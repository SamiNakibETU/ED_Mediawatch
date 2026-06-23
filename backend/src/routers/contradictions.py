from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.contradiction import TYPE_LABELS, Contradiction
from src.schemas import ContradictionPage
from src.security import require_token
from src.services.analysis.claim_sources import resolve_claim_urls
from src.services.analysis.contradiction_detector import run_contradiction_detection

router = APIRouter(tags=["contradictions"])


@router.get("/contradiction-types")
async def contradiction_types() -> dict:
    """Libellés des types (pour l'UI)."""
    return {str(k): v for k, v in TYPE_LABELS.items()}


@router.get("/contradictions", response_model=ContradictionPage)
async def list_contradictions(
    status: str = Query("pending", description="pending|confirmed|rejected|all"),
    type: int | None = Query(None, ge=1, le=6),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ContradictionPage:
    stmt = select(Contradiction).order_by(
        Contradiction.score.desc(), Contradiction.id.desc()
    )
    count_stmt = select(func.count(Contradiction.id))
    if status != "all":
        stmt = stmt.where(Contradiction.status == status)
        count_stmt = count_stmt.where(Contradiction.status == status)
    if type:
        stmt = stmt.where(Contradiction.type == type)
        count_stmt = count_stmt.where(Contradiction.type == type)

    total = await db.scalar(count_stmt) or 0
    items = list((await db.execute(stmt.limit(limit).offset(offset))).scalars().all())

    # Provenance : URL source de chaque claim (pour vérifier le verbatim en contexte).
    all_claims = [c.claim_a for c in items] + [c.claim_b for c in items]
    urls = await resolve_claim_urls(db, all_claims)
    for c in items:
        c.claim_a.source_url = urls.get(c.claim_a.id)
        c.claim_b.source_url = urls.get(c.claim_b.id)

    return ContradictionPage(total=total, limit=limit, offset=offset, items=items)


@router.post("/detect-contradictions", response_model=dict, dependencies=[Depends(require_token)])
async def detect() -> dict:
    """Lance la détection (types 1/2/3/6) sur les claims chiffrés."""
    return await run_contradiction_detection()


@router.post("/contradictions/{cid}/validate", response_model=dict)
async def validate(
    cid: int,
    decision: str = Query(..., description="confirm | reject"),
    validator: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if decision not in ("confirm", "reject"):
        raise HTTPException(400, "decision must be 'confirm' or 'reject'")
    c = await db.get(Contradiction, cid)
    if c is None:
        raise HTTPException(404, "contradiction introuvable")
    c.status = "confirmed" if decision == "confirm" else "rejected"
    c.validator = validator
    c.validated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": cid, "status": c.status}
