"""Mesure du jeu d'or : pour chaque cas, ce que la chaîne a retrouvé et où elle s'est arrêtée.

Le fichier des 23 cas sourcés est resté sur le serveur éteint. Il en reste la liste des recherches
X qui en ont été tirées (`documents/2026-10-26_recherches-x-jeu-or.md`) : 22 cas, avec pour chacun
les comptes concernés et une fenêtre de trois semaines autour de la déclaration. La mesure part de
là. Elle ne vérifie donc pas le mouvement exact, seulement que la chaîne a, pour les figures et
l'enjeu du cas : des tweets dans la fenêtre, des déclarations lues sur l'enjeu, un écart détecté,
et ce que les juges en ont fait.

    python -m src.scripts.mesurer_jeu_or [--sortie chemin.md]
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ETUDE = BACKEND.parents[1]
RECHERCHES = ETUDE / "documents" / "2026-10-26_recherches-x-jeu-or.md"

# Le début du nom du cas donne l'enjeu du référentiel. Sans enjeu, le cas est hors périmètre :
# la chaîne ne peut pas le voir, quel que soit le tweet.
ENJEU_DU_CAS = [
    ("retraites-", ("retraites", "reforme_2023")), ("otan-", ("otan",)),
    ("sanctions-russie-", ("sanctions_russie",)), ("binationaux-", ("binationaux",)),
    ("contribution-ue-", ("contribution_ue",)), ("eolien-", ("eolien",)),
    ("etat-palestinien-", ("etat_palestinien",)), ("impot-jeunes-", ("impot_jeunes",)),
    ("ivg-constitution-", ("ivg_constitution",)), ("union-droites-", ("union_droites",)),
    ("voile-", ("voile",)), ("zucman-", ("impot_fortune",)),
]


def enjeux_de(cas: str) -> tuple[str, ...]:
    return next((e for prefixe, e in ENJEU_DU_CAS if cas.startswith(prefixe)), ())


def lire_cas() -> dict[str, list[tuple[str, str, str]]]:
    cas: dict[str, list[tuple[str, str, str]]] = {}
    courant = None
    for ligne in RECHERCHES.read_text(encoding="utf-8").splitlines():
        m = re.search(r"cas `([^`]+)`", ligne)
        if m:
            courant = m.group(1)
            continue
        m = re.search(r"`from:(\w+) .*since:(\d{4}-\d\d-\d\d) until:(\d{4}-\d\d-\d\d)`", ligne)
        if m and courant:
            cas.setdefault(courant, []).append(m.groups())
    return cas


def mesurer() -> list[dict]:
    db = sqlite3.connect(f"file:{BACKEND / 'ed_mediawatch.db'}?mode=ro", uri=True)
    q = lambda sql, *a: db.execute(sql, a).fetchall()  # noqa: E731
    ids = {h.lower(): i for i, h in q("select id, handle from personalities where handle is not null")}
    lignes = []
    for cas, fenetres in sorted(lire_cas().items()):
        enjeux = enjeux_de(cas)
        figures = sorted({h for h, _, _ in fenetres})
        fids = [ids[h.lower()] for h in figures if h.lower() in ids]
        tweets = decl = 0
        for h, since, until in fenetres:
            fid = ids.get(h.lower())
            if fid is None:
                continue
            tweets += q("select count(*) from posts where personality_id=? and published_at>=? and published_at<?",
                        fid, since, until)[0][0]
            if enjeux:
                decl += q(f"select count(*) from declarations where personality_id=? and published_at>=? "
                          f"and published_at<? and enjeu in ({','.join('?' * len(enjeux))})",
                          fid, since, until, *enjeux)[0][0]
        autos: dict[str, int] = {}
        if enjeux and fids:
            marques = ",".join("?" * len(fids))
            for (auto,) in q(f"select auto from ecarts where enjeu in ({','.join('?' * len(enjeux))}) and type != 'chiffre' "
                             f"and (figure_a_id in ({marques}) or figure_b_id in ({marques}))",
                             *enjeux, *fids, *fids):
                autos[auto or "attente"] = autos.get(auto or "attente", 0) + 1
        if not enjeux:
            verdict, cause = "hors périmètre", "aucun enjeu du référentiel ne couvre ce cas"
        elif autos.get("retenu"):
            verdict, cause = "retrouvé", "au moins un écart retenu par les deux juges"
        elif autos.get("faible"):
            verdict, cause = "retrouvé, faible", "écart jugé réel mais ténu"
        elif autos:
            verdict, cause = "détecté puis écarté", "les juges n'ont retenu aucune des paires détectées"
        elif not tweets:
            verdict, cause = "manqué", "aucun tweet en base dans la fenêtre"
        elif not decl:
            verdict, cause = "manqué", "tweets en base, aucune déclaration lue sur l'enjeu dans la fenêtre"
        else:
            verdict, cause = "manqué", "déclarations lues, aucun écart détecté entre elles"
        lignes.append({"cas": cas, "figures": figures, "enjeux": enjeux, "tweets": tweets, "declarations": decl,
                       "ecarts": autos, "verdict": verdict, "cause": cause})
    return lignes


def en_markdown(lignes: list[dict]) -> str:
    compte: dict[str, int] = {}
    for l in lignes:
        compte[l["verdict"]] = compte.get(l["verdict"], 0) + 1
    dans = [l for l in lignes if l["enjeux"]]
    trouves = [l for l in dans if l["verdict"].startswith("retrouvé")]
    out = [
        "# Jeu d'or : mesure du " + date.today().strftime("%d/%m/%Y"), "",
        f"{len(trouves)} cas retrouvés sur {len(dans)} couverts par le référentiel "
        f"({len(lignes)} cas en tout, dont {len(lignes) - len(dans)} hors périmètre).", "",
        "Le fichier des 23 cas sourcés est resté sur le serveur éteint. La mesure part des recherches X "
        "qui en avaient été tirées : elle vérifie, pour les figures et l'enjeu de chaque cas, que la chaîne "
        "a des tweets dans la fenêtre, des déclarations lues, un écart détecté, et ce que les juges en ont "
        "fait. Elle ne vérifie pas que l'écart retenu est bien le mouvement décrit par le cas : c'est à "
        "relire à la main.", "",
        "| Cas | Figures | Tweets dans la fenêtre | Déclarations sur l'enjeu | Écarts (retenu, faible, écarté) | Résultat | Cause |",
        "|---|---|---|---|---|---|---|",
    ]
    for l in lignes:
        e = l["ecarts"]
        out.append(f"| `{l['cas']}` | {', '.join(l['figures'])} | {l['tweets']} | {l['declarations']} | "
                   f"{e.get('retenu', 0)}, {e.get('faible', 0)}, {e.get('ecarte', 0)} | {l['verdict']} | {l['cause']} |")
    out += ["", "Résultats : " + ", ".join(f"{k} {v}" for k, v in sorted(compte.items())) + "."]
    return "\n".join(out) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--sortie", type=Path, default=ETUDE / "documents" / f"{date.today():%Y-%m-%d}_jeu-or-mesure.md")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    texte = en_markdown(mesurer())
    a.sortie.write_text(texte, encoding="utf-8")
    print(texte)
    print(f"Écrit : {a.sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
