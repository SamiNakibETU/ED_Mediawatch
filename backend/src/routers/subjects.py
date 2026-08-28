"""Les sujets — l'entrée principale du produit.

Un militant ou un journaliste n'arrive pas en cherchant « ce qu'a tweeté
untel » : il arrive avec un objet en tête (« la hausse des impôts », « l'aide à
l'Ukraine ») et veut savoir qui a dit quoi dessus, quand, et si ça a bougé.

Le sommaire est donc ordonné par ce qui rend un sujet exploitable : plusieurs
locuteurs d'abord (il y a une confrontation possible), puis l'étendue temporelle
(un revirement se lit sur la durée), puis le volume.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.claim import Claim
from src.models.contradiction import Contradiction, TYPE_LABELS
from src.models.subject import Subject
from src.services.analysis.claim_sources import resolve_claim_urls

router = APIRouter(prefix="/subjects", tags=["subjects"])

# Étendue minimale pour qu'un sujet puisse révéler une évolution de position.
# En deçà, l'absence de contradiction ne prouve rien : le sujet est trop court.
MIN_SPAN_DAYS = 30


def _span_days(s: Subject) -> int:
    if not (s.first_seen and s.last_seen):
        return 0
    return (s.last_seen - s.first_seen).days


@router.get("")
async def list_subjects(
    q: str | None = Query(None, description="Filtre sur le libellé"),
    theme: str | None = Query(None),
    confrontable: bool = Query(False, description="Au moins deux locuteurs"),
    limit: int = Query(60, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(Subject).where(Subject.status != "incoherent")
    if q:
        stmt = stmt.where(Subject.label.ilike(f"%{q.strip()}%"))
    if theme:
        stmt = stmt.where(Subject.theme == theme)
    if confrontable:
        stmt = stmt.where(Subject.n_speakers >= 2)
    subjects = list((await db.execute(stmt)).scalars().all())

    # Ordre du sommaire. Un sujet est EXPLOITABLE quand plusieurs voix s'y
    # expriment ET qu'il court sur la durée : c'est là qu'une confrontation ou
    # un revirement peut exister. Un rassemblement de deux jours à quatre
    # locuteurs n'a rien à révéler ; un débat fiscal sur seize mois, si.
    subjects.sort(key=lambda s: (
        not (s.n_speakers >= 2 and _span_days(s) >= MIN_SPAN_DAYS),  # exploitables d'abord
        -(s.n_speakers or 0), -_span_days(s), -(s.n_claims or 0),
    ))
    subjects = subjects[:limit]

    # Une frise miniature par sujet : les dates de prise de parole, groupées par
    # locuteur. C'est ce qui remplace la photographie d'un site de presse — un
    # sujet n'a pas d'image, mais il a une forme : trois voix qui se répondent
    # sur deux ans ne ressemblent pas à quinze propos tassés sur une semaine, et
    # cette différence est exactement ce qu'on vient chercher.
    #
    # Une seule requête pour toute la page : le faire sujet par sujet
    # multiplierait les allers-retours pour un élément décoratif au premier
    # regard et informatif au second.
    frises: dict[int, list[dict]] = {}
    if subjects:
        ids = [s.id for s in subjects]
        rows = (await db.execute(
            select(Claim.subject_id, Claim.speaker_name, Claim.published_at)
            .where(Claim.subject_id.in_(ids), Claim.published_at.isnot(None))
            .order_by(Claim.published_at.asc())
        )).all()
        grouped: dict[int, dict[str, list]] = {}
        for sid, who, when in rows:
            grouped.setdefault(sid, {}).setdefault(who or "non attribué", []).append(when)
        for sid, by_who in grouped.items():
            # Quatre voix au plus : au-delà, la miniature devient un pâté de
            # lignes d'un pixel où l'on ne distingue plus rien.
            top = sorted(by_who.items(), key=lambda kv: -len(kv[1]))[:4]
            frises[sid] = [{"speaker": w, "dates": d[:40]} for w, d in top]

    # Le dernier propos en date sur chaque sujet. Un sommaire qui n'affiche que
    # des compteurs demande de cliquer pour savoir de quoi il retourne ; une
    # phrase réelle, datée et attribuée, dit tout de suite si le sujet vit.
    latest: dict[int, dict] = {}
    if subjects:
        rows = (await db.execute(
            select(Claim.subject_id, Claim.speaker_name, Claim.published_at,
                   Claim.canonical, Claim.verbatim)
            .where(Claim.subject_id.in_([s.id for s in subjects]),
                   Claim.published_at.isnot(None))
            .order_by(Claim.published_at.desc())
        )).all()
        for sid, who, when, canon, verb in rows:
            if sid not in latest:
                latest[sid] = {"speaker": who, "published_at": when,
                               "text": canon or verb}

    themes = dict(
        (
            await db.execute(
                select(Subject.theme, func.count())
                .where(Subject.theme.isnot(None), Subject.status != "incoherent")
                .group_by(Subject.theme).order_by(func.count().desc())
            )
        ).all()
    )

    return {
        "total": len(subjects),
        "themes": themes,
        "items": [
            {
                "id": s.id, "label": s.label, "theme": s.theme,
                "n_claims": s.n_claims, "n_speakers": s.n_speakers,
                "span_days": _span_days(s),
                "first_seen": s.first_seen, "last_seen": s.last_seen,
                "named": s.status == "labelled",
                "frise": frises.get(s.id, []),
                "latest": latest.get(s.id),
            }
            for s in subjects
        ],
    }


@router.get("/{subject_id}")
async def subject_detail(
    subject_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "Sujet inconnu")

    claims = list(
        (
            await db.execute(
                select(Claim).where(Claim.subject_id == subject_id)
                .order_by(Claim.published_at.asc().nullsfirst())
            )
        ).scalars().all()
    )
    urls = await resolve_claim_urls(db, claims)

    # Groupé par locuteur : c'est la lecture utile sur un sujet — « qui défend
    # quoi », et l'évolution de chacun dans le temps.
    by_speaker: dict[str, list[dict]] = {}
    for c in claims:
        who = c.speaker_name or c.party or "non attribué"
        by_speaker.setdefault(who, []).append({
            "id": c.id,
            "text": c.canonical or c.verbatim,
            "verbatim": c.verbatim,
            "claim_type": c.claim_type,
            "stance_polarity": c.stance_polarity,
            "qty_value": c.qty_value, "qty_unit": c.qty_unit,
            "published_at": c.published_at,
            "platform": c.platform,
            "source_url": urls.get(c.id),
        })

    ids = {c.id for c in claims}
    edges = []
    if ids:
        rows = list((await db.execute(
            select(Contradiction).where(
                or_(Contradiction.claim_a_id.in_(ids), Contradiction.claim_b_id.in_(ids))
            ).order_by(Contradiction.score.desc())
        )).scalars().all())
        edges = [{
            "id": e.id, "type_label": TYPE_LABELS.get(e.type, "?"),
            "score": e.score, "status": e.status, "rationale": e.rationale,
            "detection_method": e.detection_method,
            "claim_a_id": e.claim_a_id, "claim_b_id": e.claim_b_id,
        } for e in rows]

    return {
        "subject": {
            "id": subject.id, "label": subject.label, "theme": subject.theme,
            "n_claims": subject.n_claims, "n_speakers": subject.n_speakers,
            "span_days": _span_days(subject),
            "first_seen": subject.first_seen, "last_seen": subject.last_seen,
            "entities": subject.entities or [],
            "named": subject.status == "labelled",
            "note": subject.note,
        },
        "speakers": [
            {"name": name, "n": len(items), "claims": items}
            for name, items in sorted(by_speaker.items(), key=lambda kv: -len(kv[1]))
        ],
        "contradictions": edges,
    }
