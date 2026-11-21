"""Fait entrer en base les scrutins publics de l'Assemblée et le vote des députés du panel.

Lit les archives `Scrutins.json.zip` de data.assemblee-nationale.fr (une par législature), rangées dans
`donnees/assemblee/l16/` et `l17/`. Ne garde que les votes des figures suivies qui ont un identifiant
de député (`personalities.an_id`). Repère l'enjeu d'un scrutin par les mots-clés de l'atelier, dans
son titre : c'est un rattachement à vérifier, pas une lecture.

Relancer remplace les scrutins et les votes déjà importés.

    python -m src.scripts.importer_scrutins
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

os.environ.setdefault("SCHEDULER_ENABLED", "false")

ETUDE = Path(__file__).resolve().parents[4]
DOSSIER = ETUDE / "donnees" / "assemblee"
POSITIONS = {"pours": "pour", "contres": "contre", "abstentions": "abstention", "nonVotants": "non_votant"}


def liste(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def majorite_comptee(vote: dict) -> str | None:
    """La position la plus fréquente du groupe d'après son décompte ; aucune en cas d'égalité.

    Le champ « positionMajoritaire » publié par l'Assemblée ne suit pas toujours le décompte : sur l'aide
    à mourir en première lecture (27 mai 2025), il donne « abstention » au groupe RN, qui a voté contre à
    101 voix sur 123. Sur la 17e législature, 3 % des positions publiées diffèrent ainsi du décompte.
    """
    dv = vote.get("decompteVoix") or {}
    nb = {"pour": int(dv.get("pour") or 0), "contre": int(dv.get("contre") or 0),
          "abstention": int(dv.get("abstentions") or 0)}
    haut = max(nb.values())
    gagnants = [k for k, n in nb.items() if n == haut]
    return gagnants[0] if haut and len(gagnants) == 1 else None


def lire_scrutin(brut: dict) -> tuple[dict, list[dict]]:
    """Le scrutin et la liste de ses votes nominatifs : (acteur, vote, groupe, majorité du groupe)."""
    s = brut["scrutin"]
    decompte = (s.get("syntheseVote") or {}).get("decompte") or {}
    entete = {
        "uid": s["uid"], "legislature": int(s["legislature"]), "numero": int(s["numero"]),
        "date": date.fromisoformat(s["dateScrutin"][:10]),
        "titre": (s.get("titre") or (s.get("objet") or {}).get("libelle") or "").strip(),
        "type": ((s.get("typeVote") or {}).get("codeTypeVote") or "?")[:8],
        "sort": ((s.get("sort") or {}).get("code") or None),
        "pour": int(decompte["pour"]) if decompte.get("pour") is not None else None,
        "contre": int(decompte["contre"]) if decompte.get("contre") is not None else None,
        "abstentions": int(decompte["abstentions"]) if decompte.get("abstentions") is not None else None,
    }
    votes = []
    groupes = (((s.get("ventilationVotes") or {}).get("organe") or {}).get("groupes") or {}).get("groupe")
    for g in liste(groupes):
        vote = g.get("vote") or {}
        majorite = majorite_comptee(vote)
        nominatif = vote.get("decompteNominatif") or {}
        for cle, position in POSITIONS.items():
            for v in liste((nominatif.get(cle) or {}).get("votant") if isinstance(nominatif.get(cle), dict) else None):
                votes.append({"acteur": v.get("acteurRef"), "vote": position, "groupe": g.get("organeRef"),
                              "majorite": majorite,
                              "delegation": str(v.get("parDelegation", "")).lower() == "true",
                              "cause": (v.get("causePositionVote") or None)})
    return entete, votes


def scrutins(zip_path: Path):
    with zipfile.ZipFile(zip_path) as z:
        for nom in z.namelist():
            if nom.endswith(".json"):
                yield lire_scrutin(json.loads(z.read(nom)))


async def importer() -> dict:
    from sqlalchemy import delete, select

    from src.database import get_session_factory, init_db
    from src.models.personality import Personality
    from src.models.vote import Scrutin, Vote
    from src.scripts.atelier_enjeux import MOTS

    await init_db()
    motifs = [(k, re.compile(v, re.I)) for k, v in MOTS.items()]
    factory = get_session_factory()
    async with factory() as db:
        figures = {a: i for i, a in (await db.execute(
            select(Personality.id, Personality.an_id).where(Personality.an_id.isnot(None)))).all()}
    bilan = {"scrutins": 0, "votes": 0, "avec_enjeu": 0}
    for leg in sorted(DOSSIER.glob("l*/Scrutins.json.zip")):
        try:
            lus = list(scrutins(leg))
        except zipfile.BadZipFile:
            print(f"{leg.parent.name} : archive illisible ou incomplète, laissée de côté", flush=True)
            continue
        async with factory() as db:
            uids = [e["uid"] for e, _ in lus]
            for i in range(0, len(uids), 500):
                await db.execute(delete(Vote).where(Vote.scrutin_uid.in_(uids[i:i + 500])))
                await db.execute(delete(Scrutin).where(Scrutin.uid.in_(uids[i:i + 500])))
            for entete, votes in lus:
                enjeu = next((k for k, r in motifs if r.search(entete["titre"])), None)
                db.add(Scrutin(**entete, enjeu=enjeu))
                bilan["avec_enjeu"] += enjeu is not None
                for v in votes:
                    pid = figures.get(v["acteur"])
                    if pid is None:
                        continue
                    db.add(Vote(scrutin_uid=entete["uid"], personality_id=pid, vote=v["vote"], groupe=v["groupe"],
                                majorite_groupe=v["majorite"], par_delegation=v["delegation"], cause=v["cause"]))
                    bilan["votes"] += 1
            await db.commit()
        bilan["scrutins"] += len(lus)
        print(f"{leg.parent.name} : {len(lus)} scrutins", flush=True)
    return bilan


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(asyncio.run(importer()), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
