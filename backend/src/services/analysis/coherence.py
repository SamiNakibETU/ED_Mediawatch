"""L'indice de cohérence : par parti et par enjeu, trois mesures simples et leur moyenne.

Pour un parti et un enjeu :

- **Alignement** (douze derniers mois) : part des figures du parti dont la dernière position sur l'enjeu
  est la position la plus répandue dans le parti. Au moins trois figures.
- **Constance** : part des figures qui ont pris position au moins deux fois, à plus de trente jours
  d'écart, sans qu'aucun écart « dans le temps » n'ait été retenu par les deux juges. Au moins deux figures.
- **Conformité au programme** : part des déclarations dont la position est l'une de celles que retient le
  programme en vigueur à leur date (le plus récent qui traite l'enjeu). Au moins cinq déclarations. Programmes
  lus : RN 2022 (projet présidentiel et livrets thématiques), RN 2024 (législatives, européennes).

- **Votes** : part des votes exprimés par les députés suivis, sur les votes d'ensemble, solennels et motions
  rattachés à l'enjeu, qui suivent la position la plus fréquente de leur groupe. Au moins dix votes. Ne dépend
  d'aucune lecture automatique.

L'indice vaut la moyenne des mesures disponibles, sur 100, et n'est donné que si deux mesures au moins le
sont. L'indice d'un parti demande au moins cinq enjeux mesurés. Au niveau d'un parti, chaque mesure additionne numérateurs et dénominateurs de tous les enjeux : un
enjeu dont parlent beaucoup de figures pèse plus qu'un enjeu marginal.

Le parti d'une déclaration est celui de son auteur le jour où il l'a écrite. Les déclarations jugées
douteuses sont écartées. Une position mal lue fausse l'indice ; la relecture des 200 déclarations dira
de combien.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

PARTIS = ("RN", "UDR", "Reconquete")
FENETRE_JOURS = 365
MIN_ALIGNEMENT, MIN_CONSTANCE, MIN_PROGRAMME = 3, 2, 5
MIN_ENJEUX = 5   # enjeux mesurés au moins, pour donner l'indice d'un parti
MIN_VOTES = 10   # votes exprimés au moins, sur les votes d'ensemble rattachés à l'enjeu
ECART_MIN_JOURS = 30


@dataclass(frozen=True)
class Decl:
    parti: str
    enjeu: str
    figure: int
    date: datetime
    position: str


def _part(n: int, d: int) -> dict:
    return {"n": n, "sur": d, "part": round(100 * n / d) if d else None}


def mesurer(decls: list[Decl], revirements: set[tuple[int, str]],
            programme: dict[tuple[str, str], dict[int, set[str]]], maintenant: datetime,
            votes: dict[tuple[str, str], tuple[int, int]] | None = None) -> dict:
    """Les quatre mesures et l'indice, par parti et par enjeu, puis par parti.

    `votes` : pour un parti et un enjeu, (votes alignés sur la majorité du groupe, votes exprimés).
    """
    votes = votes or {}
    depuis = maintenant - timedelta(days=FENETRE_JOURS)
    groupes: dict[tuple[str, str], dict[int, list[Decl]]] = defaultdict(lambda: defaultdict(list))
    for d in decls:
        groupes[(d.parti, d.enjeu)][d.figure].append(d)

    par_parti: dict[str, list[dict]] = defaultdict(list)
    for parti, enjeu in set(groupes) | set(votes):
        figures = groupes.get((parti, enjeu), {})
        recentes = {f: [x for x in ds if x.date >= depuis] for f, ds in figures.items()}
        derniere = {f: max(xs, key=lambda x: x.date).position for f, xs in recentes.items() if xs}
        alignement = majoritaire = None
        if len(derniere) >= MIN_ALIGNEMENT:
            majoritaire, n = Counter(derniere.values()).most_common(1)[0]
            alignement = _part(n, len(derniere))

        repetes = [f for f, ds in figures.items()
                   if len(ds) >= 2 and (max(x.date for x in ds) - min(x.date for x in ds)).days > ECART_MIN_JOURS]
        constance = (_part(sum(1 for f in repetes if (f, enjeu) not in revirements), len(repetes))
                     if len(repetes) >= MIN_CONSTANCE else None)

        conformite = None
        if (parti, enjeu) in programme:
            par_annee = programme[(parti, enjeu)]

            def en_vigueur(x: Decl) -> set[str] | None:
                annees = [a for a in par_annee if a <= x.date.year]
                return par_annee[max(annees)] if annees else None

            ds = [(x, c) for xs in figures.values() for x in xs if (c := en_vigueur(x)) is not None]
            if len(ds) >= MIN_PROGRAMME:
                conformite = _part(sum(1 for x, c in ds if x.position in c), len(ds))

        alignes, exprimes = votes.get((parti, enjeu), (0, 0))
        au_vote = _part(alignes, exprimes) if exprimes >= MIN_VOTES else None

        mesures = [m["part"] for m in (alignement, constance, conformite, au_vote) if m]
        par_parti[parti].append({
            "enjeu": enjeu, "figures": len(figures), "declarations": sum(len(v) for v in figures.values()),
            "alignement": alignement, "position_majoritaire": majoritaire, "constance": constance,
            "programme": conformite, "votes": au_vote,
            "indice": round(sum(mesures) / len(mesures)) if len(mesures) >= 2 else None,
        })

    out = {}
    for parti in PARTIS:
        lignes = sorted(par_parti.get(parti, []),
                        key=lambda x: (x["indice"] is None, x["indice"] if x["indice"] is not None else 0))
        total = {}
        for cle in ("alignement", "constance", "programme", "votes"):
            n = sum(x[cle]["n"] for x in lignes if x[cle])
            d = sum(x[cle]["sur"] for x in lignes if x[cle])
            total[cle] = _part(n, d) if d else None
        mesures = [m["part"] for m in total.values() if m]
        mesures_enjeux = sum(1 for x in lignes if x["indice"] is not None)
        out[parti] = {
            **total,
            # Un indice de parti sur deux ou trois enjeux dirait plus du hasard que du parti.
            "indice": round(sum(mesures) / len(mesures)) if len(mesures) >= 2 and mesures_enjeux >= MIN_ENJEUX else None,
            "enjeux_mesures": mesures_enjeux,
            "enjeux": lignes,
        }
    return out


async def votes_par_enjeu(db) -> dict[tuple[str, str], tuple[int, int]]:
    """Votes alignés et votes exprimés des députés suivis, par parti et par enjeu, sur les votes d'ensemble,
    solennels et motions rattachés à un enjeu."""
    from sqlalchemy import func, or_, select

    from src.models.vote import Scrutin, Vote
    from src.services.analysis.votes import EXPRIMES, noms_des_groupes

    noms = await noms_des_groupes(db)
    rows = (await db.execute(
        select(Vote.groupe, Scrutin.enjeu, Vote.vote == Vote.majorite_groupe, func.count())
        .join(Scrutin, Scrutin.uid == Vote.scrutin_uid)
        .where(Scrutin.enjeu.isnot(None), Vote.vote.in_(EXPRIMES), Vote.majorite_groupe.isnot(None),
               or_(Scrutin.type.in_(("SPS", "MOC")), Scrutin.titre.like("l'ensemble%"), Scrutin.titre.like("l’ensemble%")))
        .group_by(Vote.groupe, Scrutin.enjeu, Vote.vote == Vote.majorite_groupe))).all()
    out: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for groupe, enjeu, aligne, n in rows:
        if noms.get(groupe, "autre") == "autre":
            continue
        cle = (noms[groupe], enjeu)
        out[cle][1] += n
        if aligne:
            out[cle][0] += n
    return {k: (a, t) for k, (a, t) in out.items()}


async def indice(db, *, maintenant: datetime | None = None) -> dict:
    from sqlalchemy import or_, select

    from src.models.declaration import Declaration
    from src.models.ecart import Ecart
    from src.models.engagement_programme import EngagementProgramme
    from src.models.personality import Personality
    from src.services.affiliation import all_affiliations, party_of
    from src.services.analysis.enjeux import PAR_SLUG

    maintenant = maintenant or datetime.now(timezone.utc)
    rows = (await db.execute(
        select(Declaration, Personality).join(Personality, Personality.id == Declaration.personality_id)
        .where(Declaration.position.isnot(None), Declaration.published_at.isnot(None),
               or_(Declaration.douteuse.is_(None), Declaration.douteuse.is_(False))))).all()
    affils = await all_affiliations(db)
    decls = []
    for d, p in rows:
        parti = party_of(affils, p, d.published_at)
        enjeu = PAR_SLUG.get(d.enjeu)
        if parti in PARTIS and enjeu and enjeu.cran(d.position):
            date = d.published_at if d.published_at.tzinfo else d.published_at.replace(tzinfo=timezone.utc)
            decls.append(Decl(parti, d.enjeu, p.id, date, d.position))
    revirements = {(e.figure_a_id, e.enjeu) for e in (await db.execute(
        select(Ecart).where(Ecart.auto == "retenu", Ecart.type == "temps"))).scalars()}
    programme: dict[tuple[str, str], dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for g in (await db.execute(select(EngagementProgramme).where(EngagementProgramme.position.isnot(None)))).scalars():
        programme[(g.parti, g.enjeu)][g.annee].add(g.position)

    resultat = mesurer(decls, revirements, programme, maintenant, await votes_par_enjeu(db))
    for parti in resultat.values():
        for x in parti["enjeux"]:
            e = PAR_SLUG[x["enjeu"]]
            x["titre"], x["question"] = e.titre, e.question
            x["position_majoritaire_label"] = e.cran(x["position_majoritaire"]).label if x["position_majoritaire"] else None
    return {"calcule_le": maintenant.isoformat(), "fenetre_jours": FENETRE_JOURS,
            "seuils": {"alignement": MIN_ALIGNEMENT, "constance": MIN_CONSTANCE, "programme": MIN_PROGRAMME,
                       "votes": MIN_VOTES, "enjeux": MIN_ENJEUX},
            "partis": resultat}
