"""Lecture des votes à l'Assemblée : dissidences dans un groupe, scrutins par enjeu, votes d'une figure.

Un vote dissident est un vote exprimé (pour, contre, abstention) différent de la position la plus fréquente
de son groupe sur ce scrutin, d'après le décompte (voir `importer_scrutins.majorite_comptee`). Les non-votants
ne comptent pas.
Le nom d'un groupe se déduit de ses membres suivis : le groupe où siègent la plupart des figures RN
du panel est le groupe RN de la législature.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import select

from src.models.personality import Personality
from src.models.vote import Scrutin, Vote

EXPRIMES = ("pour", "contre", "abstention")
MIN_VOTANTS = 5


def _important(s: Scrutin) -> bool:
    return s.type in ("SPS", "MOC") or s.titre.lower().lstrip().startswith(("l'ensemble", "l’ensemble"))


async def noms_des_groupes(db) -> dict[str, str]:
    """organeRef -> RN, UDR, … : le parti de la grande majorité des figures suivies du groupe.

    Un groupe n'est nommé que s'il réunit au moins cinq figures suivies, dont 80 % du même parti. Sans ce
    seuil, le groupe LR de 2022-2024, où siégeaient deux figures aujourd'hui à l'UDR, prenait le nom d'UDR.
    Les autres groupes sont « autre » et sortent des comptes par parti.
    """
    from sqlalchemy import func

    rows = (await db.execute(select(Vote.groupe, Personality.group_code, func.count(func.distinct(Vote.personality_id)))
                             .join(Personality, Personality.id == Vote.personality_id)
                             .group_by(Vote.groupe, Personality.group_code))).all()
    par: dict[str, Counter] = defaultdict(Counter)
    for g, code, n in rows:
        if g:
            par[g][code or "?"] += n
    noms = {}
    for g, c in par.items():
        code, n = c.most_common(1)[0]
        total = sum(c.values())
        noms[g] = code if total >= 5 and n / total >= 0.8 else "autre"
    return noms


def _scrutin(s: Scrutin) -> dict:
    return {"uid": s.uid, "legislature": s.legislature, "numero": s.numero, "date": s.date.isoformat(),
            "titre": s.titre, "type": s.type, "sort": s.sort, "pour": s.pour, "contre": s.contre,
            "abstentions": s.abstentions, "enjeu": s.enjeu,
            "url": f"https://www.assemblee-nationale.fr/dyn/{s.legislature}/scrutins/{s.numero}"}


async def dissidences(db, *, limit: int = 40) -> dict:
    """Les scrutins où des figures suivies ont voté autrement que leur groupe, les plus partagés d'abord."""
    from sqlalchemy import func

    noms = await noms_des_groupes(db)
    # Les comptes par scrutin, groupe et vote se font dans la base : 450 000 votes ne se chargent pas en mémoire.
    rows = (await db.execute(
        select(Vote.scrutin_uid, Vote.groupe, Vote.majorite_groupe, Vote.vote, func.count())
        .where(Vote.vote.in_(EXPRIMES), Vote.majorite_groupe.isnot(None))
        .group_by(Vote.scrutin_uid, Vote.groupe, Vote.majorite_groupe, Vote.vote))).all()
    par: dict[tuple[str, str], dict] = {}
    exprimes, dissidents = Counter(), Counter()
    for uid, groupe, majorite, vote, n in rows:
        parti = noms.get(groupe, "autre")
        if parti == "autre":
            continue
        exprimes[parti] += n
        x = par.setdefault((uid, groupe), {"parti": parti, "majorite": majorite, "alignes": 0, "contre_groupe": 0})
        if vote == majorite:
            x["alignes"] += n
        else:
            dissidents[parti] += n
            x["contre_groupe"] += n
    # Un vrai partage : au moins cinq votants suivis dans le groupe ; les votes d'ensemble, solennels et motions
    # d'abord, puis par la taille du camp minoritaire. Trié par la seule proportion, le haut de la
    # liste était fait d'amendements votés par trois députés.
    partages = [(k, x) for k, x in par.items() if x["contre_groupe"] and x["contre_groupe"] + x["alignes"] >= MIN_VOTANTS]
    scrutins = {s.uid: s for s in (await db.execute(
        select(Scrutin).where(Scrutin.uid.in_({k[0] for k, _ in partages})))).scalars()} if partages else {}
    partages.sort(key=lambda kx: (_important(scrutins[kx[0][0]]), min(kx[1]["contre_groupe"], kx[1]["alignes"]),
                                  scrutins[kx[0][0]].date), reverse=True)
    out = []
    for (uid, groupe), x in partages[:limit]:
        noms_dissidents = (await db.execute(
            select(Personality.id, Personality.full_name, Vote.vote).join(Personality, Personality.id == Vote.personality_id)
            .where(Vote.scrutin_uid == uid, Vote.groupe == groupe, Vote.vote.in_(EXPRIMES), Vote.vote != x["majorite"]))).all()
        out.append({**_scrutin(scrutins[uid]), "parti": x["parti"], "majorite": x["majorite"], "alignes": x["alignes"],
                    "dissidents": [{"id": i, "nom": nom, "vote": v} for i, nom, v in noms_dissidents]})
    return {
        "par_parti": {pa: {"votes_exprimes": exprimes[pa], "dissidents": dissidents[pa],
                           "part": round(1000 * dissidents[pa] / exprimes[pa]) / 10 if exprimes[pa] else None}
                      for pa in exprimes},
        "scrutins": out,
        "total_scrutins_partages": len(partages),
    }


async def par_enjeu(db, slug: str, *, limit: int = 30) -> list[dict]:
    """Les scrutins rattachés à un enjeu, solennels et votes d'ensemble d'abord, avec le vote du panel par parti."""
    noms = await noms_des_groupes(db)
    scrutins = (await db.execute(select(Scrutin).where(Scrutin.enjeu == slug))).scalars().all()
    scrutins = sorted(scrutins, key=lambda s: (_important(s), s.date), reverse=True)[:limit]
    out = []
    for s in scrutins:
        votes = (await db.execute(select(Vote, Personality).join(Personality, Personality.id == Vote.personality_id)
                                  .where(Vote.scrutin_uid == s.uid))).all()
        partis: dict[str, Counter] = defaultdict(Counter)
        for v, p in votes:
            partis[noms.get(v.groupe, "?")][v.vote] += 1
        out.append({**_scrutin(s), "panel": {pa: dict(c) for pa, c in partis.items()}})
    return out


async def de_la_figure(db, personality_id: int) -> dict:
    """Les votes d'une figure : ses votes dissidents, et ses votes sur les scrutins rattachés à un enjeu."""
    rows = (await db.execute(
        select(Vote, Scrutin).join(Scrutin, Scrutin.uid == Vote.scrutin_uid)
        .where(Vote.personality_id == personality_id).order_by(Scrutin.date.desc()))).all()
    exprimes = [(v, s) for v, s in rows if v.vote in EXPRIMES]
    dissidents = [{**_scrutin(s), "vote": v.vote, "majorite": v.majorite_groupe}
                  for v, s in exprimes if v.majorite_groupe and v.vote != v.majorite_groupe]
    sur_enjeu = [{**_scrutin(s), "vote": v.vote, "majorite": v.majorite_groupe}
                 for v, s in rows if s.enjeu and _important(s)]
    return {"scrutins": len(rows), "exprimes": len(exprimes), "dissidents": dissidents[:30],
            "nb_dissidents": len(dissidents), "sur_enjeu": sur_enjeu[:30]}
