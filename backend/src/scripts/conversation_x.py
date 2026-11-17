"""Conversations X : les réponses à quelques tweets, en cascade, et le profil de chaque compte.

    python -m src.scripts.conversation_x https://x.com/MLP_officiel/status/2050574077631357295 [...]
    python -m src.scripts.conversation_x URL --profondeur 3 --reponses-max 300 --sans-profils

Pour chaque tweet de départ, par une instance Nitter (voir `historique_x`) :
  1. les réponses, triées par date (le tri « pertinent » de X écarte des réponses), page après page ;
  2. en cascade, les réponses aux réponses qui en ont au moins SEUIL, jusqu'à PROFONDEUR ;
  3. le profil de chaque compte rencontré : bio, lieu, création, abonnés, abonnements, tweets, j'aime.

Sortie dans `donnees/x-conversations/<date>/` :
  tweets.ndjson    un tweet par ligne : compteurs, médias, `parent_id` (le tweet auquel il répond),
                   `profondeur` (0 pour un tweet de départ), `conversation` (le tweet de départ) ;
  comptes.ndjson   un profil par ligne ;
  liens.csv        qui répond à qui (source -> cible), une ligne par réponse, pour Gephi ;
  noeuds.csv       un compte par ligne, avec ses compteurs et son activité dans le corpus ;
  resume.md        les chiffres de chaque conversation.

Mêmes règles de politesse que `historique_x` : une requête à la fois, PAUSE secondes entre deux.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from src.scripts.historique_x import INSTANCE, PAUSE, Arret, Lecteur
from src.services.collection.x_html_parser import lire_page_statut, lire_profil

RACINE = Path(__file__).resolve().parents[4] / "donnees" / "x-conversations"
_URL = re.compile(r"(?:x|twitter)\.com/(\w+)/status/(\d+)")


def _avec_tri(chemin: str) -> str:
    """Le tri par date, gardé d'une page à l'autre (le lien « suite » de Nitter le perd)."""
    chemin = chemin.replace("&amp;", "&")
    return chemin if "sort=" in chemin else chemin + ("&" if "?" in chemin else "?") + "sort=recency"


class Cascade:
    def __init__(self, lecteur: Lecteur, profondeur: int, reponses_max: int, seuil: int, requetes_max: int):
        self.lecteur, self.profondeur, self.reponses_max = lecteur, profondeur, reponses_max
        self.seuil, self.requetes_max = seuil, requetes_max
        self.tweets: dict[str, dict] = {}
        self.visites: set[str] = set()

    def _garder(self, auteur: str, d: dict, conversation: str, profondeur: int) -> None:
        if d["id"] in self.tweets:
            return
        d = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in d.items()}
        self.tweets[d["id"]] = {"auteur": auteur, **d, "conversation": conversation, "profondeur": profondeur}

    def statut(self, auteur: str, tid: str, conversation: str, profondeur: int) -> list[tuple[str, str, int]]:
        """Lit un tweet et ses réponses ; rend les réponses à suivre en cascade."""
        if tid in self.visites:
            return []
        self.visites.add(tid)
        chemin, lues, a_suivre = _avec_tri(f"/{auteur}/status/{tid}"), 0, []
        while chemin and lues < self.reponses_max and self.lecteur.requetes < self.requetes_max:
            page = lire_page_statut(self.lecteur.page(self.lecteur.instance + chemin))
            if page["principal"] and lues == 0:
                a, d = page["principal"]
                self._garder(a, d, conversation, profondeur)
            if not page["reponses"]:
                break
            for a, d in page["reponses"]:
                parent = self.tweets.get(d.get("parent_id") or "")
                self._garder(a, d, conversation, (parent["profondeur"] if parent else profondeur) + 1)
                lues += 1
                p = self.tweets[d["id"]]["profondeur"]
                if (d.get("replies") or 0) >= self.seuil and p < self.profondeur:
                    a_suivre.append((a, d["id"], p))
            chemin = _avec_tri(page["suite"]) if page["suite"] else None
        return a_suivre

    def conversation(self, auteur: str, tid: str) -> None:
        file = [(auteur, tid, 0)]
        while file and self.lecteur.requetes < self.requetes_max:
            a, t, p = file.pop(0)  # en largeur : tout le premier niveau avant le second
            file += self.statut(a, t, tid, p)
            print(f"  {a}/{t} : {len(self.tweets)} tweets, {len(file)} fils en attente, "
                  f"{self.lecteur.requetes} requêtes", flush=True)


def profils(lecteur: Lecteur, handles: list[str], requetes_max: int) -> dict[str, dict]:
    out = {}
    for i, h in enumerate(handles, 1):
        if lecteur.requetes >= requetes_max:
            print(f"  plafond de requêtes atteint : {len(handles) - i + 1} profils non lus", flush=True)
            break
        p = lire_profil(lecteur.page(f"{lecteur.instance}/{h}"))
        out[h] = p or {"handle": h, "introuvable": True}
        if i % 20 == 0:
            print(f"  {i} profils sur {len(handles)}", flush=True)
    return out


def ecrire(dossier: Path, tweets: dict[str, dict], comptes: dict[str, dict], departs: list[str]) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    with (dossier / "tweets.ndjson").open("w", encoding="utf-8") as f:
        for t in tweets.values():
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    with (dossier / "comptes.ndjson").open("w", encoding="utf-8") as f:
        for c in comptes.values():
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    with (dossier / "liens.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Source", "Target", "tweet_id", "parent_id", "conversation", "profondeur", "date", "likes",
                    "retweets", "replies"])
        for t in tweets.values():
            parent = tweets.get(t.get("parent_id") or "")
            if parent:
                w.writerow([t["auteur"], parent["auteur"], t["id"], parent["id"], t["conversation"], t["profondeur"],
                            t.get("published_at"), t.get("likes"), t.get("retweets"), t.get("replies")])

    activite = defaultdict(lambda: {"reponses": 0, "jaime_recus": 0, "conversations": set()})
    for t in tweets.values():
        a = activite[t["auteur"]]
        a["reponses"] += t["profondeur"] > 0
        a["jaime_recus"] += t.get("likes") or 0
        a["conversations"].add(t["conversation"])
    with (dossier / "noeuds.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Id", "Label", "abonnes", "abonnements", "tweets", "cree_le", "certifie", "lieu",
                    "reponses_dans_le_corpus", "jaime_recus", "conversations", "bio"])
        for h, a in activite.items():
            c = comptes.get(h, {})
            w.writerow([h, c.get("nom") or h, c.get("abonnes"), c.get("abonnements"), c.get("tweets"),
                        c.get("cree_le"), c.get("certifie"), c.get("lieu"), a["reponses"], a["jaime_recus"],
                        len(a["conversations"]), (c.get("bio") or "").replace("\n", " ")])

    lignes = [f"# Conversations X, {datetime.now():%d/%m/%Y %H:%M}", ""]
    for dep in departs:
        conv = [t for t in tweets.values() if t["conversation"] == dep]
        racine = tweets.get(dep)
        rep = [t for t in conv if t["profondeur"] > 0]
        if not racine:
            lignes += [f"## {dep}", "", "Tweet introuvable.", ""]
            continue
        auteurs = Counter(t["auteur"] for t in rep)
        jeunes = [h for h in auteurs if (comptes.get(h, {}).get("cree_le") or "").endswith(("2025", "2026"))]
        lus = sorted(rep, key=lambda t: -(t.get("likes") or 0))[:5]
        lignes += [
            f"## @{racine['auteur']}, {racine.get('published_at', '')[:10]}", "",
            f"> {racine['content'][:280]}", "",
            f"- {racine.get('likes')} j'aime, {racine.get('replies')} réponses annoncées par X ; "
            f"{len(rep)} réponses lues, de {len(auteurs)} comptes, jusqu'à la profondeur "
            f"{max((t['profondeur'] for t in rep), default=0)}.",
            f"- Comptes créés en 2025 ou 2026 parmi les répondants : {len(jeunes)} sur {len(auteurs)}.",
            f"- Répondants les plus actifs : " + ", ".join(f"@{h} ({n})" for h, n in auteurs.most_common(5)) + ".",
            "- Réponses les plus aimées :",
            *[f"  - @{t['auteur']} ({t.get('likes')} j'aime) : {t['content'][:140].replace(chr(10), ' ')}"
              for t in lus],
            "",
        ]
    (dossier / "resume.md").write_text("\n".join(lignes), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="réponses en cascade et profils, par une instance Nitter")
    p.add_argument("urls", nargs="+", help="adresses de tweets (x.com/<compte>/status/<id>)")
    p.add_argument("--profondeur", type=int, default=2, help="1 : réponses directes ; 2 : et leurs réponses ; ...")
    p.add_argument("--reponses-max", type=int, default=200, help="réponses lues au plus par tweet visité")
    p.add_argument("--seuil", type=int, default=2, help="une réponse est suivie si elle a au moins ce nombre de réponses")
    p.add_argument("--requetes-max", type=int, default=800)
    p.add_argument("--sans-profils", action="store_true")
    p.add_argument("--instance", default=INSTANCE)
    p.add_argument("--pause", type=float, default=PAUSE)
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    departs = []
    for u in a.urls:
        m = _URL.search(u)
        if not m:
            sys.exit(f"adresse de tweet illisible : {u}")
        departs.append((m.group(1), m.group(2)))

    lecteur = Lecteur(a.instance, max(a.pause, 1.0))
    cascade = Cascade(lecteur, a.profondeur, a.reponses_max, a.seuil, a.requetes_max)
    dossier = RACINE / datetime.now().strftime("%Y-%m-%d_%H%M")
    comptes: dict[str, dict] = {}
    try:
        for auteur, tid in departs:
            print(f"Conversation de @{auteur}/{tid}", flush=True)
            cascade.conversation(auteur, tid)
        if not a.sans_profils:
            handles = sorted({t["auteur"] for t in cascade.tweets.values()})
            print(f"Profils : {len(handles)} comptes", flush=True)
            comptes = profils(lecteur, handles, a.requetes_max + len(handles))
    except Arret as exc:
        print(f"Arrêt : l'instance refuse ({exc}). Ce qui a été lu est écrit.", flush=True)
    ecrire(dossier, cascade.tweets, comptes, [t for _, t in departs])
    print(f"{len(cascade.tweets)} tweets, {len(comptes)} profils, {lecteur.requetes} requêtes -> {dossier}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
