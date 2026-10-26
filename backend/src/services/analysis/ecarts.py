"""Les confrontations : détecter les écarts par requête, puis les faire relire.

La détection ne devine rien. Elle compare des positions déjà rangées sur la même
échelle, et ne retient que les crans différents. Ce qui reste à juger, c'est si
l'écart est réel : la lecture de chaque position peut être fausse, les deux
phrases peuvent ne pas parler de la même chose, la position peut avoir évolué
pour une raison dite publiquement. C'est le travail du juge, puis du relecteur.

Le parti de chaque propos est celui du jour où il a été tenu (`party_of`) : un
écart « dans le parti » compare deux personnes qui étaient dans le même parti
au moment où elles parlaient.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

import structlog
from pydantic import BaseModel
from sqlalchemy import select

from src.database import get_session_factory
from src.models.declaration import Declaration
from src.models.ecart import Ecart
from src.models.engagement_programme import EngagementProgramme
from src.models.personality import Personality
from src.models.post import Post
from src.services.affiliation import all_affiliations, party_of
from src.services.analysis.enjeux import PAR_SLUG, Point, ecarts as ecarts_temps
from src.services.analysis.llm_usage import BudgetExceeded, ProviderRefused
from src.utils import sha256

logger = structlog.get_logger(__name__)

FENETRE_PARTI = timedelta(days=90)
PARTIS_ED = ("RN", "UDR", "Reconquete")


def _cle(*parts) -> str:
    return sha256(":".join(str(p) for p in parts))[:64]


async def detecter() -> dict:
    """Recalcule les écarts des trois types. N'écrase jamais un écart déjà tranché."""
    factory = get_session_factory()
    async with factory() as db:
        rows = (await db.execute(
            select(Declaration, Personality)
            .join(Personality, Personality.id == Declaration.personality_id)
            .where(Declaration.position.isnot(None), Declaration.published_at.isnot(None))
        )).all()
        affils = await all_affiliations(db)
        prog = (await db.execute(
            select(EngagementProgramme).where(EngagementProgramme.position.isnot(None)))).scalars().all()
        existantes = set((await db.execute(select(Ecart.cle))).scalars().all())

    parti_de: dict[int, str | None] = {}
    par_enjeu: dict[str, list[tuple[Declaration, Personality]]] = defaultdict(list)
    for d, p in rows:
        if d.enjeu in PAR_SLUG and PAR_SLUG[d.enjeu].cran(d.position):
            par_enjeu[d.enjeu].append((d, p))
            parti_de[d.id] = party_of(affils, p, d.published_at)

    nouveaux: list[Ecart] = []

    def ajouter(type_, enjeu, a, b=None, eng=None, ampleur=1):
        cle = _cle(type_, enjeu, a.id, b.id if b else "", eng.id if eng else "")
        if cle in existantes:
            return
        existantes.add(cle)
        nouveaux.append(Ecart(
            type=type_, enjeu=enjeu, decl_a_id=a.id, decl_b_id=b.id if b else None,
            engagement_id=eng.id if eng else None, figure_a_id=a.personality_id,
            figure_b_id=b.personality_id if b else None, parti_a=parti_de.get(a.id),
            parti_b=parti_de.get(b.id) if b else (eng.parti if eng else None),
            date_a=a.published_at, date_b=b.published_at if b else None,
            position_a=a.position, position_b=b.position if b else (eng.position if eng else None),
            ampleur=ampleur, cle=cle,
        ))

    for slug, items in par_enjeu.items():
        enjeu = PAR_SLUG[slug]
        rang = {c.code: c.rang for c in enjeu.echelle}
        par_id = {d.id: d for d, _ in items}

        # 1. Une même figure dans le temps.
        points = [Point(d.personality_id, d.position, d.published_at, d.id) for d, _ in items]
        for e in ecarts_temps(enjeu, points):
            ajouter("temps", slug, par_id[e.avant.post_id], par_id[e.apres.post_id], ampleur=e.ampleur)

        # 2. Contre le programme de son parti, après sa publication.
        crans_prog: dict[tuple[str, int], list[EngagementProgramme]] = defaultdict(list)
        for g in prog:
            if g.enjeu == slug:
                crans_prog[(g.parti, g.annee)].append(g)
        for d, _ in items:
            for (parti, annee), engs in crans_prog.items():
                if parti_de.get(d.id) != parti or d.published_at.year < annee:
                    continue
                if d.position not in {g.position for g in engs}:
                    proche = min(engs, key=lambda g: abs(rang[g.position] - rang[d.position]))
                    ajouter("programme", slug, d, eng=proche,
                            ampleur=abs(rang[proche.position] - rang[d.position]))

        # 3. Deux voix du même parti, au même moment. Pour chaque paire de
        # figures et de crans, on garde seulement les deux propos les plus
        # proches dans le temps : vingt déclarations de chacun ne font pas
        # quatre cents écarts.
        meilleurs: dict[tuple, tuple[timedelta, Declaration, Declaration]] = {}
        tries = sorted(items, key=lambda x: x[0].published_at)
        for i, (a, _) in enumerate(tries):
            for b, _ in tries[i + 1:]:
                if b.published_at - a.published_at > FENETRE_PARTI:
                    break
                if a.personality_id == b.personality_id or a.position == b.position:
                    continue
                pa, pb = parti_de.get(a.id), parti_de.get(b.id)
                if not pa or pa != pb:
                    continue
                k = (min(a.personality_id, b.personality_id), max(a.personality_id, b.personality_id),
                     frozenset((a.position, b.position)))
                dt = b.published_at - a.published_at
                if k not in meilleurs or dt < meilleurs[k][0]:
                    meilleurs[k] = (dt, a, b)
        for _, a, b in meilleurs.values():
            ajouter("parti", slug, a, b, ampleur=abs(rang[a.position] - rang[b.position]))

    async with factory() as db:
        db.add_all(nouveaux)
        await db.commit()
    bilan = Counter(e.type for e in nouveaux)
    logger.info("ecarts.detectes", **{k: v for k, v in bilan.items()})
    return {"nouveaux": dict(bilan), "total_nouveaux": len(nouveaux)}


# ── Divergences entre partis ────────────────────────────────────────────

async def divergences(db, *, depuis_jours: int = 365) -> list[dict]:
    """La position dominante de RN, UDR et Reconquête sur chaque enjeu, et là où elles diffèrent.

    Une position dominante est le cran le plus fréquent parmi les déclarations
    du parti sur la période, avec sa part : un parti à 55 % sur un cran n'est
    pas un parti unanime, et la page le dit.
    """
    depuis = datetime.now(timezone.utc) - timedelta(days=depuis_jours)
    rows = (await db.execute(
        select(Declaration, Personality)
        .join(Personality, Personality.id == Declaration.personality_id)
        .where(Declaration.position.isnot(None), Declaration.published_at >= depuis)
    )).all()
    affils = await all_affiliations(db)
    compte: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for d, p in rows:
        parti = party_of(affils, p, d.published_at)
        if parti in PARTIS_ED and d.enjeu in PAR_SLUG:
            compte[d.enjeu][parti][d.position] += 1
    out = []
    for slug, partis in compte.items():
        enjeu = PAR_SLUG[slug]
        dominantes = {}
        for parti, c in partis.items():
            code, n = c.most_common(1)[0]
            total = sum(c.values())
            dominantes[parti] = {"position": code, "label": enjeu.cran(code).label,
                                 "part": round(100 * n / total), "declarations": total}
        if len(dominantes) >= 2:
            out.append({"enjeu": slug, "titre": enjeu.titre, "question": enjeu.question,
                        "partis": dominantes,
                        "divergent": len({v["position"] for v in dominantes.values()}) > 1})
    out.sort(key=lambda x: (not x["divergent"], x["titre"]))
    return out


# ── Le juge ─────────────────────────────────────────────────────────────

JUGE_SYSTEM = (
    "Tu examines un écart relevé automatiquement entre deux positions politiques sur une même "
    "question. Les positions ont été lues par un modèle dans des tweets : ta première tâche est de "
    "vérifier cette lecture.\n\n"
    "1. Relis chaque texte. La position attribuée est-elle bien celle que dit le texte ? Si l'une "
    "est mal lue, le type est « erreur_de_lecture ».\n"
    "2. Les deux textes parlent-ils vraiment de la même chose (même mesure, même portée, même "
    "contexte) ? Sinon, le type est « contexte_different ».\n"
    "3. Sinon, qualifie l'écart :\n"
    "   - « revirement » : la même personne a changé de position ;\n"
    "   - « divergence » : deux personnes du même camp disent des choses incompatibles ;\n"
    "   - « ecart_au_programme » : la personne contredit le programme de son parti ;\n"
    "   - « nuance » : les positions sont proches, la différence tient à la formulation.\n"
    "4. force : 0 (aucun écart réel) à 3 (contradiction nette, qu'un journaliste publierait).\n"
    "5. justification : « oui » si l'un des textes explique publiquement le changement, « non » "
    "sinon, « inconnue » si on ne peut pas savoir.\n"
    "6. explication : deux phrases au plus, factuelles, qui citent les mots des textes. Pas de "
    "jugement moral.\n\n"
    'Réponds par un JSON : {"type": "...", "force": 0, "justification": "...", "explication": "..."}'
)


class Verdict(BaseModel):
    type: Literal["erreur_de_lecture", "contexte_different", "revirement", "divergence",
                  "ecart_au_programme", "nuance"] | str = "nuance"
    force: int = 0
    justification: str = "inconnue"
    explication: str = ""


def _bloc(titre: str, nom: str, date, position: str, texte: str) -> str:
    j = date.date().isoformat() if date else "date inconnue"
    return f"## {titre} : {nom}, {j}\nPosition attribuée : {position}\nTexte :\n«««\n{texte.strip()[:1500]}\n»»»"


async def juger(*, limit: int = 40) -> dict:
    """Fait relire par le juge les écarts qui ne l'ont pas encore été."""
    from src.services.analysis.claim_llm import get_claim_llm

    llm = get_claim_llm()
    factory = get_session_factory()
    async with factory() as db:
        a_juger = list((await db.execute(
            select(Ecart).where(Ecart.juge_type.is_(None), Ecart.statut == "a_relire")
            .order_by(Ecart.ampleur.desc(), Ecart.date_b.desc().nullslast()).limit(limit)
        )).scalars().all())
    stats = {"juges": 0, "echecs": 0, "budget_atteint": False}
    for e in a_juger:
        async with factory() as db:
            enjeu = PAR_SLUG[e.enjeu]
            da = await db.get(Declaration, e.decl_a_id)
            pa = await db.get(Post, da.post_id)
            fa = await db.get(Personality, e.figure_a_id)
            blocs = [_bloc("A", f"{fa.full_name} ({e.parti_a or '?'})", da.published_at,
                           enjeu.cran(e.position_a).label, pa.content)]
            if e.decl_b_id:
                db_ = await db.get(Declaration, e.decl_b_id)
                pb = await db.get(Post, db_.post_id)
                fb = await db.get(Personality, e.figure_b_id)
                blocs.append(_bloc("B", f"{fb.full_name} ({e.parti_b or '?'})", db_.published_at,
                                   enjeu.cran(e.position_b).label, pb.content))
            elif e.engagement_id:
                g = await db.get(EngagementProgramme, e.engagement_id)
                blocs.append(f"## B : programme {g.parti} {g.annee}, livret {g.livret}, page {g.page}\n"
                             f"Position attribuée : {enjeu.cran(g.position).label}\nTexte :\n«««\n{g.verbatim}\n»»»")
        prompt = (f"Question : {enjeu.question}\nType d'écart relevé : {e.type}\n\n" + "\n\n".join(blocs))
        try:
            v = await llm.ask_json(tier=2, system=JUGE_SYSTEM, prompt=prompt, schema=Verdict,
                                   task="juge_ecarts", max_tokens=2500, raisonnement="low")
        except BudgetExceeded:
            stats["budget_atteint"] = True
            break
        except ProviderRefused:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("ecarts.juge_echec", ecart=e.id, error=str(exc)[:160])
            stats["echecs"] += 1
            continue
        async with factory() as db:
            o = await db.get(Ecart, e.id)
            o.juge_type = str(v.type)[:20]
            o.juge_force = max(0, min(3, int(v.force)))
            o.juge_justification = v.justification if v.justification in ("oui", "non", "inconnue") else "inconnue"
            o.juge_explication = v.explication[:1500]
            o.juge_lecteur = f"juge-1/{llm.model_for(2)}"[:120]
            await db.commit()
        stats["juges"] += 1
    logger.info("ecarts.juges", **stats)
    return stats
