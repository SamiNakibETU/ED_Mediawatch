"""Fiche personnalité — ce qu'un militant, un analyste ou un journaliste consulte.

La question à laquelle cette page répond n'est pas « qu'a-t-elle dit hier ? »
(le registre le fait déjà) mais « **qu'a-t-elle défendu, sur quoi, et est-ce que
ça a bougé ?** ». D'où la structure : une chronologie par thème plutôt qu'un
flux, chaque propos daté et rattaché à sa source, et les rapprochements validés
qui l'impliquent.

Tout est servi depuis le Grand Livre : aucune synthèse n'est produite ici, et
rien n'est affiché qui ne soit traçable jusqu'à un verbatim et une URL.
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.claim import Claim
from src.models.contradiction import Contradiction, TYPE_LABELS
from src.models.dossier import Dossier
from src.models.personality import Personality
from src.models.subject import Subject
from src.models.post import Post
from src.services.analysis.amplification import who_they_amplify
from src.services.analysis.claim_sources import resolve_claim_urls

router = APIRouter(prefix="/figures", tags=["figures"])


@router.get("")
async def list_figures(
    q: str | None = Query(None, description="Filtre sur le nom ou le handle"),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Répertoire des figures, ordonné par volume de propos consignés.

    Une figure sans déclaration n'est pas masquée : son absence est une
    information (collecte muette, compte introuvable) et le compteur à zéro la
    rend visible plutôt que de la faire disparaître.
    """
    counts = dict(
        (
            await db.execute(
                select(Claim.personality_id, func.count())
                .where(Claim.personality_id.isnot(None))
                .group_by(Claim.personality_id)
            )
        ).all()
    )
    stmt = select(Personality).where(Personality.is_active.is_(True))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Personality.full_name.ilike(like), Personality.handle.ilike(like)))
    people = list((await db.execute(stmt)).scalars().all())
    people.sort(key=lambda p: (-counts.get(p.id, 0), p.full_name))

    return {
        "total": len(people),
        "items": [
            {
                "id": p.id, "full_name": p.full_name, "handle": p.handle,
                "group_code": p.group_code, "famille": p.famille, "role": p.role,
                "photo_url": p.photo_url, "n_claims": counts.get(p.id, 0),
                "last_status": p.last_status,
            }
            for p in people[:limit]
        ],
    }


@router.get("/{figure_id}")
async def figure_detail(
    figure_id: int,
    theme: str | None = Query(None, description="Restreindre la chronologie à un thème"),
    limit: int = Query(150, ge=1, le=500),
    offset: int = Query(0, ge=0, description="Pagination de la chronologie"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    p = await db.get(Personality, figure_id)
    if p is None:
        raise HTTPException(404, "Figure inconnue")

    # Les propos rattachés à la figure : par identifiant (posts X) OU par nom
    # (presse, où l'attribution passe par le locuteur cité).
    author = or_(Claim.personality_id == figure_id, Claim.speaker_name == p.full_name)

    by_theme = dict(
        (
            await db.execute(
                select(Claim.theme, func.count()).where(author, Claim.theme.isnot(None))
                .group_by(Claim.theme).order_by(func.count().desc())
            )
        ).all()
    )
    by_type = dict(
        (await db.execute(select(Claim.claim_type, func.count()).where(author).group_by(Claim.claim_type))).all()
    )
    span = (await db.execute(
        select(func.min(Claim.published_at), func.max(Claim.published_at)).where(author)
    )).one()

    # Ce que la figure défend, SUJET PAR SUJET — la lecture utile d'une fiche.
    # Une chronologie brute répond à « qu'a-t-elle dit le 12 mars » ; personne
    # n'arrive avec cette question. On arrive avec « que dit-elle des retraites,
    # et depuis quand » — et, si d'autres en parlent aussi, « qui dit le
    # contraire ». D'où le renvoi vers le sujet, où la confrontation se voit.
    rows = (await db.execute(
        select(Subject, func.count(Claim.id),
               func.min(Claim.published_at), func.max(Claim.published_at))
        .join(Claim, Claim.subject_id == Subject.id)
        .where(author, Subject.status != "incoherent")
        .group_by(Subject.id)
        .order_by(func.count(Claim.id).desc())
    )).all()
    by_subject = [
        {
            "id": sub.id, "label": sub.label, "theme": sub.theme, "status": sub.status,
            "n": n, "first_seen": lo, "last_seen": hi,
            "span_days": (hi - lo).days if (lo and hi) else 0,
            "n_speakers": sub.n_speakers or 1,
            # Un sujet à une seule voix n'a rien à confronter : le dire évite de
            # laisser croire qu'un silence adverse est un accord.
            "confrontable": (sub.n_speakers or 1) >= 2,
        }
        for sub, n, lo, hi in rows
    ]

    stmt = select(Claim).where(author)
    if theme:
        stmt = stmt.where(Claim.theme == theme)

    # Combien la chronologie compte RÉELLEMENT, filtre thématique appliqué.
    # Sans ce total, la fiche annonçait « 1 445 propos consignés » et n'en
    # servait jamais que 150 : le reste n'était pas seulement absent, il était
    # inatteignable, et rien à l'écran ne le disait.
    n_timeline = await db.scalar(
        select(func.count()).select_from(stmt.subquery())
    ) or 0
    claims = list(
        (await db.execute(
            stmt.order_by(Claim.published_at.desc().nullslast()).limit(limit).offset(offset)
        )).scalars().all()
    )
    urls = await resolve_claim_urls(db, claims)

    # Chronologie groupée par mois : c'est l'échelle à laquelle une position se
    # lit — un jour est trop fin, une année masque le mouvement.
    months: dict[str, list[dict]] = defaultdict(list)
    for c in claims:
        key = c.published_at.strftime("%Y-%m") if c.published_at else "date-inconnue"
        months[key].append({
            "id": c.id,
            "verbatim": c.verbatim,
            "canonical": c.canonical,
            "claim_type": c.claim_type,
            "theme": c.theme,
            "stance_polarity": c.stance_polarity,
            "qty_value": c.qty_value,
            "qty_unit": c.qty_unit,
            "published_at": c.published_at,
            "platform": c.platform,
            "source_url": urls.get(c.id),
        })

    claim_ids = {c.id for c in claims}
    edges = []
    if claim_ids:
        rows = list((await db.execute(
            select(Contradiction).where(
                or_(Contradiction.claim_a_id.in_(claim_ids), Contradiction.claim_b_id.in_(claim_ids))
            ).order_by(Contradiction.score.desc()).limit(30)
        )).scalars().all())
        edges = [{
            "id": e.id, "type": e.type, "type_label": TYPE_LABELS.get(e.type, "?"),
            "score": e.score, "status": e.status, "rationale": e.rationale,
            "detection_method": e.detection_method,
            "claim_a_id": e.claim_a_id, "claim_b_id": e.claim_b_id,
        } for e in rows]

    dossier = (await db.execute(select(Dossier).where(Dossier.personality_id == figure_id))).scalar_one_or_none()
    n_posts = await db.scalar(
        select(func.count()).select_from(Post).where(Post.personality_id == figure_id)
    )

    return {
        "figure": {
            "id": p.id, "full_name": p.full_name, "handle": p.handle,
            "group_code": p.group_code, "group_long": p.group_long, "famille": p.famille,
            "role": p.role, "circo": p.circo, "departement": p.departement,
            "photo_url": p.photo_url, "verif": p.verif,
            "x_followers": getattr(p, "followers_count", None),
            "last_status": p.last_status,
        },
        "stats": {
            "n_claims": sum(by_type.values()),
            "n_posts": n_posts or 0,
            "by_theme": by_theme,
            "by_type": by_type,
            "first_seen": span[0],
            "last_seen": span[1],
        },
        "timeline": [
            {"month": m, "claims": months[m]}
            for m in sorted(months, reverse=True)
        ],
        "by_subject": by_subject,
        # Qui la figure relaie. Un retweet nu vaut adhésion, un relais commenté
        # est ambigu — la distinction est portée jusqu'à l'écran.
        "amplifies": await who_they_amplify(figure_id, limit=15),
        "timeline_total": n_timeline,
        "timeline_offset": offset,
        "timeline_count": len(claims),
        "contradictions": edges,
        "dossier": {
            "summary": dossier.summary,
            "data": dossier.data,
            "generated_at": dossier.generated_at,
            "model": dossier.model,
        } if dossier else None,
    }
