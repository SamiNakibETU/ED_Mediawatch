"""Codage CAP des déclarations — une étape du pipeline, pas un prompt de plus.

Pourquoi une étape séparée plutôt qu'un champ de plus dans l'extraction L0. Le
codage se fait en DEUX questions (voir `cap.py`) : le joindre à la segmentation
mêlerait trois tâches dans un même appel, ce que la littérature identifie
précisément comme la cause de l'effondrement de fiabilité. Au tier 1 les deux
questions coûtent moitié moins qu'un seul appel de tier 2, et le prompt L0 reste
concentré sur ce qu'il sait faire.

Ce qui a été retiré. Une première version traduisait l'ancien thème vers un
topique par un dictionnaire écrit à la main : gratuit, instantané, et à 31 %
d'accord seulement avec une relecture du texte. Une table de correspondance ne
relit rien — elle propage la classification qu'elle traduit, erreurs comprises.
Tout passe désormais par la lecture.

Le codage est idempotent (marque `cap_version`), reprenable et borné : une passe
interrompue ne perd rien, la suivante continue. Comme l'extraction, il s'arrête
proprement sur le plafond de dépense.
"""

from __future__ import annotations

import structlog
from sqlalchemy import func, or_, select

from src.database import get_session_factory
from src.models.claim import Claim
from src.services.analysis.cap import CAP_VERSION, coder_signature, is_valid
from src.services.analysis.claim_llm import get_claim_llm
from src.services.analysis.llm_usage import BudgetExceeded, ProviderRefused

logger = structlog.get_logger(__name__)


def _todo_filter():
    """Les déclarations qui n'ont pas de code à jour.

    `cap_version` porte la décision, pas `cap_major` : une déclaration codée
    « aucun topique » a bien été examinée et ne doit pas repasser à chaque fois.
    Sans ça, tout ce qui n'est pas de la politique publique — et c'est une part
    notable du corpus — serait resoumis à chaque passe, indéfiniment.
    """
    return or_(Claim.cap_version.is_(None), ~Claim.cap_version.startswith(CAP_VERSION))


async def code_claims(*, limit: int = 1500) -> dict:
    """Code les déclarations en attente. Rend le compte de ce qui a été fait."""
    llm = get_claim_llm()
    factory = get_session_factory()

    async with factory() as db:
        batch = list((await db.execute(
            select(Claim).where(_todo_filter())
            .order_by(Claim.published_at.desc().nullslast())
            .limit(limit)
        )).scalars().all())

    if not batch:
        async with factory() as db:
            reste = await db.scalar(
                select(func.count()).select_from(Claim).where(_todo_filter())) or 0
        return {"coded": 0, "no_topic": 0, "remaining": reste}

    coded = no_topic = echecs = 0
    budget_hit = False
    signature = coder_signature(llm._s.claim_tier1_model)
    for claim in batch:
        try:
            code = await llm.code_cap(claim.canonical or claim.verbatim or "")
        except BudgetExceeded as exc:
            logger.warning("cap_coding.budget_exceeded", detail=str(exc))
            budget_hit = True
            break
        except ProviderRefused:
            # Le fournisseur est fermé : inutile de lui reposer la question
            # mille fois, et surtout rien à marquer.
            raise
        except Exception as exc:  # noqa: BLE001
            # Un échec ponctuel ne marque RIEN : la déclaration repassera à la
            # prochaine passe. La marquer reviendrait à écrire « examiné, aucun
            # thème » sur un propos que le modèle n'a pas lu.
            logger.warning("cap_coding.claim_failed", claim_id=claim.id,
                           error=str(exc)[:120])
            echecs += 1
            continue
        async with factory() as db:
            obj = await db.get(Claim, claim.id)
            if obj is None:
                continue
            obj.cap_major = code if is_valid(code) else None
            # La signature complète du codeur, pas la grille seule : sans le
            # modèle et le protocole, on ne sait plus ce qui a produit quoi, et
            # un taux d'accord cesse d'être reproductible.
            obj.cap_version = signature
            await db.commit()
        coded += bool(code)
        no_topic += not code

    async with factory() as db:
        reste = await db.scalar(
            select(func.count()).select_from(Claim).where(_todo_filter())) or 0

    stats = {"coded": coded, "no_topic": no_topic, "remaining": reste,
             "echecs": echecs, "budget_exceeded": budget_hit, "coder": signature}
    logger.info("cap_coding.done", **stats)
    return stats


async def distribution() -> list[dict]:
    """Répartition de l'attention par topique, du plus au moins investi.

    C'est la mesure que la grille rend possible et que la grille maison ne
    permettait pas : une part d'attention comparable à celle du gouvernement,
    du Parlement ou de la presse, qui codent avec la même grille.
    """
    from src.services.analysis.cap import label

    factory = get_session_factory()
    async with factory() as db:
        rows = (await db.execute(
            select(Claim.cap_major, func.count())
            .where(Claim.cap_version.startswith(CAP_VERSION))
            .group_by(Claim.cap_major)
        )).all()

    total = sum(n for _, n in rows) or 1
    out = [
        {"code": c, "label": label(c), "n": n, "part": round(100 * n / total, 1)}
        for c, n in rows if c is not None
    ]
    out.sort(key=lambda d: -d["n"])
    sans = sum(n for c, n in rows if c is None)
    if sans:
        # Affiché, jamais masqué : la part du corpus qui ne relève d'aucun
        # domaine d'action publique est un résultat, pas un raté de codage.
        out.append({"code": None, "label": "hors politique publique",
                    "n": sans, "part": round(100 * sans / total, 1)})
    return out
