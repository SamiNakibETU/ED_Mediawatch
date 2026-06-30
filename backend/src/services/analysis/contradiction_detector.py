"""Détection de contradictions numériques (types 1, 2, 3, 6).

Approche « blocking par référent » (specs §4.1) : on ne compare jamais tous les
claims entre eux, seulement à l'intérieur d'un bloc partageant `referent_key`
(et même unité). Chaque paire de valeurs incompatibles devient une arête typée :

  1 revirement intra-locuteur · 2 intra-parti · 3 inter-partis · 6 variance.

Toutes en statut `pending` → revue humaine avant publication.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session_factory
from src.models.claim import Claim
from src.models.contradiction import Contradiction
from src.models.referentiel import Referent

logger = structlog.get_logger(__name__)

# Écart relatif minimal pour considérer deux valeurs incompatibles (ignore l'arrondi).
EPSILON = 0.02

# Plancher de score par type : un revirement (1) ou une contradiction de parti
# (2/3) prime sur la simple ampleur numérique (cf specs : type 1 le plus accablant).
_TYPE_FLOOR = {1: 0.85, 2: 0.6, 3: 0.6, 6: 0.0}


def _rel_diff(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), 1.0)


def _classify(a: Claim, b: Claim) -> int:
    """Type de contradiction selon locuteur/parti (cf TYPE_LABELS)."""
    if a.speaker_name and b.speaker_name and a.speaker_name == b.speaker_name:
        if a.published_at and b.published_at and a.published_at != b.published_at:
            return 1  # même personne, dates différentes
    if a.party and b.party:
        if a.speaker_name != b.speaker_name and a.party == b.party:
            return 2  # même parti, locuteurs différents
        if a.party != b.party:
            return 3  # partis différents
    return 6  # variance générique (locuteur/parti inconnus)


def _rationale(a: Claim, b: Claim, label: str) -> str:
    def side(c: Claim) -> str:
        who = c.speaker_name or (c.party or "source presse")
        when = c.published_at.date().isoformat() if c.published_at else "?"
        return f"{c.qty_value:g} {c.qty_unit or ''} ({who}, {when})"

    return f"{label} — {side(a)}  ≠  {side(b)}"


# Stances opposées (contradiction normative). 'nuance'/'inconnu' ne contredisent pas.
_OPPOSITE = {("pour", "contre"), ("contre", "pour")}


def _rationale_norm(a: Claim, b: Claim, label: str) -> str:
    def side(c: Claim) -> str:
        who = c.speaker_name or (c.party or "source presse")
        when = c.published_at.date().isoformat() if c.published_at else "?"
        return f"{c.stance_polarity} ({who}, {when}) : « {(c.verbatim or '')[:90]} »"

    return f"{label} — {side(a)}  ⇄  {side(b)}"


async def _existing_pairs(db: AsyncSession) -> set[tuple[int, int]]:
    rows = await db.execute(select(Contradiction.claim_a_id, Contradiction.claim_b_id))
    return set(rows.all())


async def run_contradiction_detection() -> dict:
    factory = get_session_factory()
    new = pairs = 0

    async with factory() as db:
        labels = dict((await db.execute(select(Referent.key, Referent.label))).all())
        claims = list(
            (
                await db.execute(
                    select(Claim)
                    .where(Claim.qty_value.isnot(None), Claim.referent_key.isnot(None))
                    .order_by(Claim.referent_key, Claim.published_at.asc().nullslast())
                )
            ).scalars().all()
        )
        seen = await _existing_pairs(db)

        # Regroupement par (référent, unité) = blocs comparables.
        blocks: dict[tuple[str, str | None], list[Claim]] = {}
        for c in claims:
            blocks.setdefault((c.referent_key, c.qty_unit_kind), []).append(c)

        for (ref_key, _kind), block in blocks.items():
            label = labels.get(ref_key, ref_key)
            for i in range(len(block)):
                for j in range(i + 1, len(block)):
                    a, b = block[i], block[j]
                    if a.qty_value is None or b.qty_value is None:
                        continue
                    diff = _rel_diff(a.qty_value, b.qty_value)
                    if diff <= EPSILON:
                        continue  # valeurs équivalentes (arrondi)
                    pairs += 1
                    ca, cb = sorted((a.id, b.id))
                    if (ca, cb) in seen:
                        continue
                    ctype = _classify(a, b)
                    score = round(min(max(diff, _TYPE_FLOOR.get(ctype, 0.0)), 1.0), 3)
                    db.add(Contradiction(
                        claim_a_id=ca, claim_b_id=cb, referent_key=ref_key,
                        type=ctype, score=score,
                        rationale=_rationale(a, b, label), status="pending",
                    ))
                    seen.add((ca, cb))
                    new += 1

        # --- Passe NORMATIVE (zéro coût LLM) : positions opposées sur un même
        # référent. Bloc = referent_key ; candidat = stances opposées (pour/contre).
        norm_claims = list(
            (
                await db.execute(
                    select(Claim)
                    .where(
                        Claim.referent_key.isnot(None),
                        Claim.qty_value.is_(None),  # non chiffré (le numérique est traité au-dessus)
                        Claim.stance_polarity.in_(["pour", "contre"]),
                    )
                    .order_by(Claim.referent_key, Claim.published_at.asc().nullslast())
                )
            ).scalars().all()
        )
        norm_blocks: dict[str, list[Claim]] = {}
        for c in norm_claims:
            norm_blocks.setdefault(c.referent_key, []).append(c)

        norm_new = 0
        for ref_key, block in norm_blocks.items():
            label = labels.get(ref_key, ref_key)
            for i in range(len(block)):
                for j in range(i + 1, len(block)):
                    a, b = block[i], block[j]
                    if (a.stance_polarity, b.stance_polarity) not in _OPPOSITE:
                        continue
                    ca, cb = sorted((a.id, b.id))
                    if (ca, cb) in seen:
                        continue
                    ctype = _classify(a, b)
                    # Score normatif : opposition franche + plancher de type.
                    score = round(min(max(0.7, _TYPE_FLOOR.get(ctype, 0.0)), 1.0), 3)
                    db.add(Contradiction(
                        claim_a_id=ca, claim_b_id=cb, referent_key=ref_key,
                        type=ctype, score=score,
                        rationale=_rationale_norm(a, b, label), status="pending",
                    ))
                    seen.add((ca, cb))
                    norm_new += 1

        await db.commit()

    stats = {"blocks": len(blocks), "pairs_incompatibles": pairs,
             "contradictions_new": new + norm_new, "normative_new": norm_new}
    logger.info("contradictions.detected", **stats)
    return stats
