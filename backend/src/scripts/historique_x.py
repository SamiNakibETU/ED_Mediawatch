"""Récupère l'historique X des figures suivies par une instance Nitter, mois par mois.

    python -m src.scripts.historique_x                       # les 12 comptes du jeu d'or, 2022-01 à 2026-05
    python -m src.scripts.historique_x --comptes MLP_officiel J_Bardella --depuis 2024-01
    python -m src.scripts.historique_x --sans-envoi          # archive locale seulement
    python -m src.scripts.historique_x --envoyer-archives    # envoie ce qui a été archivé sans être envoyé

Pourquoi ce chemin. Sans compte X, seule la recherche d'une instance Nitter rend
l'historique daté d'un compte. Mesuré le 26 octobre 2026 contre une capture
Zeeschuimer (Le Pen, juin-juillet 2024) : 258 tweets originaux et citations sur
258, texte identique. Détail : annexe 04 de X-tools, à l'IRIS.

Ce que fait le script, pour chaque compte et chaque mois (le plus récent d'abord) :
  1. suit la pagination de la recherche `from:<compte> since:<mois> until:<mois suivant>`
     jusqu'au bout, une page toutes les PAUSE secondes ;
  2. écrit les tweets dans `donnees/x-historique/<compte>.ndjson` (la copie locale fait foi) ;
  3. les envoie à la plateforme (`/collect/tweets`), qui écarte les doublons ;
  4. note le mois dans `etat.json`. Relancé, le script reprend où il s'était arrêté.

Les retweets ne sont pas récupérés (Nitter n'en donne pas l'identifiant), ni les
réponses à autrui (la recherche Nitter les exclut).

Politesse. L'instance est un service bénévole. Une requête à la fois, PAUSE secondes
entre deux, attente croissante au premier refus (429, 5xx, défi anti-robot), arrêt
net au-delà de cinq refus de suite. Le script se présente comme un outil de recherche.

Le jeton est lu dans API_TOKEN, l'adresse de la plateforme dans ED_URL.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from src.services.collection.x_html_parser import lire_page_recherche

ED_URL = os.environ.get("ED_URL", "https://edmediawatch-production.up.railway.app")
INSTANCE = "https://xitter.cf"
PAUSE = 3.0
ATTENTES = (30, 60, 120, 300, 600)  # après chaque refus de suite ; au-delà, arrêt
PAGES_VIDES_MAX = 5  # Nitter rend parfois une page vide au milieu : la suivante repart
# Une page pleine compte 19 ou 20 tweets ; la dernière d'une recherche en compte moins.
# Après elle, Nitter rend des pages vides sans fin : la première suffit pour conclure.
PAGE_PLEINE = 15
PAGES_MAX = 400  # garde-fou par mois
LOT_ENVOI = 400
# Un mois est fait quand sa recherche est allée au bout. « pages vides » en est une fin normale :
# relus le 27/10/2026, 31 mois finis ainsi ont rendu exactement les mêmes tweets.
FAITS = ("complet", "introuvable", "pages vides")
MOIS_ACTIF = 10  # un mois vide juste après un mois d'au moins 10 tweets est suspect
VIA = "xitter"
UA = "Mozilla/5.0 (compatible; ED-Mediawatch-recherche/1.0; Terra Nova Jeunes; historique de comptes publics)"

DOSSIER = Path(__file__).resolve().parents[4] / "donnees" / "x-historique"  # étude/donnees/

# Les comptes du jeu d'or, dans l'ordre où leurs mouvements comptent le plus.
JEU_OR = ["MLP_officiel", "J_Bardella", "MarionMarechal", "ZemmourEric", "eciotti", "sebchenu",
          "louis_aliot", "JphTanguy", "HeleneLaporteRN", "Thomas_Mng", "BallardPhilippe", "ChudeauR"]

DEFI = re.compile(r"anubis|making sure you'?re not a bot|cf-challenge|just a moment|checking your browser|"
                  r"challenge-platform|to defend nitter", re.I)


class Arret(Exception):
    """L'instance refuse de façon répétée : on s'arrête, l'état est sauvé."""


def mois(debut: str, fin: str) -> list[tuple[str, str, str]]:
    """[(« 2026-05 », since, until)], du plus récent au plus ancien, bornes comprises."""
    a, b = date.fromisoformat(debut + "-01"), date.fromisoformat(fin + "-01")
    out = []
    while b >= a:
        suivant = date(b.year + (b.month == 12), b.month % 12 + 1, 1)
        out.append((b.strftime("%Y-%m"), b.isoformat(), suivant.isoformat()))
        b = date(b.year - (b.month == 1), (b.month - 2) % 12 + 1, 1)
    return out


class Lecteur:
    def __init__(self, instance: str, pause: float, transport: httpx.BaseTransport | None = None):
        self.instance, self.pause = instance.rstrip("/"), pause
        self.http = httpx.Client(headers={"User-Agent": UA, "Accept-Language": "fr,en;q=0.8"},
                                 timeout=40, follow_redirects=True, transport=transport)
        self.requetes = 0
        self._derniere = 0.0

    def page(self, url: str) -> str:
        refus = 0
        while True:
            attente = self.pause + random.uniform(0, 1) - (time.monotonic() - self._derniere)
            if attente > 0:
                time.sleep(attente)
            self._derniere = time.monotonic()
            self.requetes += 1
            try:
                r = self.http.get(url)
                motif = (f"HTTP {r.status_code}" if r.status_code in (429, 403) or r.status_code >= 500
                         else "défi anti-robot" if DEFI.search(r.text[:5000]) else None)
                if motif is None:
                    return r.text
            except httpx.HTTPError as exc:
                motif = f"réseau ({type(exc).__name__})"
            if refus >= len(ATTENTES):
                raise Arret(f"{motif}, {refus} refus de suite")
            print(f"    {motif} : pause de {ATTENTES[refus]} s", flush=True)
            time.sleep(ATTENTES[refus])
            refus += 1

    def mois(self, compte: str, since: str, until: str) -> dict:
        """Tous les tweets d'un compte sur un mois, en suivant la pagination jusqu'au bout."""
        q = f"from:{compte} since:{since} until:{until}"
        url = f"{self.instance}/search?" + urlencode({"f": "tweets", "q": q})
        vus: dict[str, dict] = {}
        retweets = pages = vides = 0
        derniere: int | None = None  # nombre d'items de la dernière page non vide
        curseurs: set[str] = set()
        fin = "complet"
        while True:
            html = self.page(url)
            pages += 1
            if 'class="error-panel"' in html and not vus:
                return {"tweets": [], "retweets": 0, "pages": pages, "fin": "introuvable"}
            tweets, suite, rt = lire_page_recherche(html)
            retweets += rt
            for auteur, t in tweets:
                if auteur.lower() == compte.lower():
                    vus[t["url"]] = {"auteur": auteur, **t}
            n = len(tweets) + rt
            if n:
                vides, derniere = 0, n
            else:
                vides += 1
                # Fin naturelle : la page d'avant était déjà incomplète, ou rien depuis le début.
                if (derniere is not None and derniere < PAGE_PLEINE) or (derniere is None and vides >= 2):
                    break
                if vides >= PAGES_VIDES_MAX:
                    fin = "pages vides"  # arrêt au milieu d'un flux plein : le mois sera relu
                    break
            if not suite:
                break
            if suite in curseurs or pages >= PAGES_MAX:
                fin = "boucle" if suite in curseurs else "plafond"
                break
            curseurs.add(suite)
            url = self.instance + suite.replace("&amp;", "&")
        return {"tweets": list(vus.values()), "retweets": retweets, "pages": pages, "fin": fin}


def charger_etat() -> dict:
    f = DOSSIER / "etat.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def sauver_etat(etat: dict) -> None:
    f = DOSSIER / "etat.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)  # jamais d'état à moitié écrit


def archiver(compte: str, cle_mois: str, tweets: list[dict]) -> None:
    with (DOSSIER / f"{compte}.ndjson").open("a", encoding="utf-8") as f:
        for t in tweets:
            f.write(json.dumps({**t, "mois": cle_mois}, ensure_ascii=False, default=str) + "\n")


def envoyer(tweets: list[dict], jeton: str) -> int:
    nouveaux = 0
    for i in range(0, len(tweets), LOT_ENVOI):
        lot = [{k: v for k, v in t.items() if k != "mois"} for t in tweets[i:i + LOT_ENVOI]]
        r = httpx.post(f"{ED_URL}/collect/tweets", headers={"X-API-Token": jeton}, timeout=300,
                       content=json.dumps({"via": VIA, "tweets": lot}, default=str),
                       )
        r.raise_for_status()
        nouveaux += r.json().get("nouveaux", 0)
    return nouveaux


def archive(compte: str) -> dict[str, list[dict]]:
    """La copie locale d'un compte, par mois, un tweet par adresse (un mois relu y figure deux fois)."""
    f = DOSSIER / f"{compte}.ndjson"
    par: dict[str, dict[str, dict]] = {}
    if f.exists():
        for ligne in f.open(encoding="utf-8"):
            t = json.loads(ligne)
            par.setdefault(t["mois"], {})[t["url"]] = t
    return {m: list(v.values()) for m, v in par.items()}


def reparer(etat: dict) -> None:
    """Remet dans l'état ce que la copie locale contient et que l'état a oublié.

    Le 27/10/2026, mai 2022 de Marine Le Pen est revenu vide d'une relecture (288 tweets
    au premier passage) et l'état l'avait noté vide et complet. La copie locale, écrite
    en ajout seulement, gardait les tweets : elle fait foi.
    """
    for compte, par_mois in etat.items():
        for m, tweets in archive(compte).items():
            e = par_mois.get(m)
            if e is not None and len(tweets) > (e.get("n") or 0):
                print(f"{compte} {m} : l'état disait {e.get('n') or 0} tweets, la copie locale en a {len(tweets)}",
                      flush=True)
                e.update(n=len(tweets), fin="complet", envoye=False)
    sauver_etat(etat)


def envoyer_archives(etat: dict, jeton: str) -> None:
    """Envoie les mois archivés mais pas encore envoyés (jeton absent, plateforme injoignable)."""
    for compte, par_mois in etat.items():
        a_envoyer = {m for m, e in par_mois.items() if not e.get("envoye")}
        if not a_envoyer:
            continue
        copie = archive(compte)
        for m in sorted(a_envoyer):
            tweets = copie.get(m, [])
            if not tweets:
                par_mois[m]["envoye"] = True
                continue
            par_mois[m]["nouveaux"] = envoyer(tweets, jeton)
            par_mois[m]["envoye"] = True
            sauver_etat(etat)
            print(f"{compte} {m} : {len(tweets)} envoyés, {par_mois[m]['nouveaux']} nouveaux", flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description="historique X des figures suivies, par une instance Nitter")
    p.add_argument("--comptes", nargs="*", default=JEU_OR)
    p.add_argument("--depuis", default="2022-01", help="premier mois, AAAA-MM")
    p.add_argument("--jusqua", default="2026-05", help="dernier mois, AAAA-MM (la suite est collectée chaque heure)")
    p.add_argument("--instance", default=INSTANCE)
    p.add_argument("--pause", type=float, default=PAUSE, help="secondes entre deux requêtes (3 au minimum conseillé)")
    p.add_argument("--sans-envoi", action="store_true", help="archive locale seulement")
    p.add_argument("--envoyer-archives", action="store_true", help="envoie les mois archivés non envoyés, puis s'arrête")
    p.add_argument("--refaire", action="store_true", help="relit aussi les mois déjà faits")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    DOSSIER.mkdir(parents=True, exist_ok=True)
    jeton = os.environ.get("API_TOKEN", "").strip()
    etat = charger_etat()

    if a.envoyer_archives:
        if not jeton:
            sys.exit("API_TOKEN manquant.")
        envoyer_archives(etat, jeton)
        return 0
    envoi = bool(jeton) and not a.sans_envoi
    if not envoi:
        print("Envoi désactivé (pas d'API_TOKEN, ou --sans-envoi) : archive locale seulement.", flush=True)

    if sys.platform == "win32":
        # Pas de mise en veille tant que le script tourne : le 26/10/2026, une veille a tué
        # en silence la collecte du Mot de la semaine. La demande tombe à la fin du processus.
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)

    reparer(etat)
    lecteur = Lecteur(a.instance, max(a.pause, 1.0))
    fenetres = mois(a.depuis, a.jusqua)
    debut_session = time.monotonic()
    total = 0
    try:
        for compte in a.comptes:
            par_mois = etat.setdefault(compte, {})
            precedent = 0  # tweets du mois traité juste avant (le mois suivant dans le temps)
            for cle, since, until in fenetres:
                if not a.refaire and par_mois.get(cle, {}).get("fin") in FAITS:
                    precedent = par_mois[cle].get("n") or 0
                    continue
                avant = par_mois.get(cle, {})
                t0 = time.monotonic()
                r = lecteur.mois(compte, since, until)
                if r["fin"] == "introuvable":
                    par_mois[cle] = {"fin": "introuvable", "n": 0}
                    sauver_etat(etat)
                    print(f"{compte} : compte introuvable sur l'instance, on passe au suivant", flush=True)
                    break
                if not r["tweets"] and avant.get("n"):
                    # L'instance cale parfois en rendant des pages vides, sans erreur : un mois qui
                    # avait des tweets ne devient pas vide. On garde le passage précédent.
                    avant["fin"] = "complet"
                    sauver_etat(etat)
                    print(f"{compte} {cle} : vide cette fois, {avant['n']} tweets au passage précédent, gardés",
                          flush=True)
                    precedent = avant["n"]
                    continue
                if not r["tweets"] and precedent >= MOIS_ACTIF:
                    # Vide juste après un mois actif : sans doute l'instance qui cale. Une seconde
                    # chance après une minute ; vide encore, le mois sera relu à la prochaine relance.
                    print(f"{compte} {cle} : vide après un mois de {precedent} tweets, nouvel essai dans 60 s",
                          flush=True)
                    time.sleep(60)
                    r = lecteur.mois(compte, since, until)
                    if not r["tweets"]:
                        r["fin"] = "vide"
                tweets = r["tweets"]
                precedent = len(tweets)
                archiver(compte, cle, tweets)
                dates = sorted(t["published_at"] for t in tweets if t.get("published_at"))
                e = {"n": len(tweets), "retweets": r["retweets"], "pages": r["pages"], "fin": r["fin"],
                     "plus_ancien": str(dates[0]) if dates else None, "envoye": False,
                     "le": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                if envoi and tweets:
                    e["nouveaux"] = envoyer(tweets, jeton)
                    e["envoye"] = True
                elif not tweets:
                    e["envoye"] = True
                par_mois[cle] = e
                sauver_etat(etat)
                total += len(tweets)
                duree = time.monotonic() - debut_session
                print(f"{compte} {cle} : {len(tweets)} tweets ({r['retweets']} retweets ignorés), "
                      f"{r['pages']} pages, {r['fin']}"
                      + (f", {e['nouveaux']} nouveaux en base" if "nouveaux" in e else "")
                      + f" [{time.monotonic() - t0:.0f} s ; session {duree / 60:.0f} min, {total} tweets, "
                        f"{lecteur.requetes} requêtes]", flush=True)
    except Arret as exc:
        print(f"Arrêt : l'instance refuse ({exc}). Rien n'est perdu : relancer plus tard reprend ici.", flush=True)
        return 2
    except KeyboardInterrupt:
        print("Interrompu. Relancer reprend au mois en cours.", flush=True)
        return 1
    print(f"Terminé : {total} tweets en {(time.monotonic() - debut_session) / 60:.0f} min.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
