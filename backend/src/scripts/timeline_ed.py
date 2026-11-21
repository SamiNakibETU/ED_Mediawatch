"""Historique X des figures du pool par les pages de profil de xitter.cf, pour ED Mediawatch.

Pourquoi : depuis fin octobre 2026, la recherche de xitter.cf pose un défi anti-robot (HTTP 403), qui arrête
``historique_x``. Les pages de profil restent ouvertes et leur robots.txt les autorise. Le lecteur existe déjà dans
X-tools (``canaux/timeline_x.py``, skill ``collecte-x``) : ce script le réutilise tel quel et change seulement le
dossier de sortie, pour que les données restent dans l'étude qui les demande (``donnees/x-timeline/``).

Ordre : les comptes du pool jamais collectés d'abord, puis ceux de l'historique par recherche, pour boucher leurs
mois vides. Une requête à la fois, pauses de 4 s, arrêt devant un défi ; relancer reprend au dernier curseur.
Limite connue : X borne la profondeur d'un profil ; un compte très actif peut s'arrêter sur « fin du profil »
avant la borne. Le statut de chaque compte le dit dans ``etat.json``.

Usage :  python -m src.scripts.timeline_ed [--borne 2022-01-01] [--comptes a b c]
         python -m src.scripts.timeline_ed --frais        (les tweets parus depuis le dernier passage)
         python -m src.scripts.timeline_ed --envoyer      (ED_URL et API_TOKEN dans l environnement)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from src.scripts.historique_x import comptes_du_pool

LECTEUR = Path(r"D:\Sami\iris\etudes\X-desinformation\X-tools\canaux\timeline_x.py")
ETUDE = Path(__file__).resolve().parents[4]
SORTIE = ETUDE / "donnees" / "x-timeline"
HISTORIQUE = ETUDE / "donnees" / "x-historique" / "etat.json"


def charger_lecteur():
    spec = importlib.util.spec_from_file_location("timeline_x", LECTEUR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DOSSIER = SORTIE            # les données d'ED restent dans ED
    return mod


def ordre() -> list[str]:
    """Les comptes jamais collectés d'abord, puis ceux de l'historique par recherche."""
    faits = set()
    if HISTORIQUE.exists():
        faits = {h.lower() for h in json.loads(HISTORIQUE.read_text(encoding="utf-8"))}
    pool = comptes_du_pool()
    return [c for c in pool if c.lower() not in faits] + [c for c in pool if c.lower() in faits]


ENVOI = SORTIE / "envoi.json"     # lignes de chaque fichier déjà envoyées


def envoyer_tout(jeton: str) -> int:
    """Envoie à la plateforme (ED_URL, /collect/tweets) ce qui n'est pas encore parti ; la plateforme écarte
    les doublons, et ``envoi.json`` garde le nombre de lignes déjà envoyées par compte : relancer est sûr."""
    from src.scripts import historique_x as hx

    hx.VIA = "xitter-profil"          # provenance distincte de l'historique par recherche
    fait = json.loads(ENVOI.read_text(encoding="utf-8")) if ENVOI.exists() else {}
    total = 0
    for f in sorted(SORTIE.glob("*.ndjson")):
        lignes = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        deja = fait.get(f.stem, 0)
        if len(lignes) <= deja:
            continue
        nouveaux = hx.envoyer(lignes[deja:], jeton)
        fait[f.stem] = len(lignes)
        ENVOI.write_text(json.dumps(fait, indent=1), encoding="utf-8")
        total += nouveaux
        print(f"{f.stem} : {len(lignes) - deja} envoyés, {nouveaux} nouveaux", flush=True)
    return total


PAGES_FRAIS = 6     # garde-fou par compte pour la passe du jour
RECUL_JOURS = 21    # on ne remonte pas plus loin que trois semaines


def rafraichir(mod, comptes: list[str]) -> int:
    """Passe du jour : relit le haut de chaque profil et s'arrête dès qu'une page n'apporte rien de neuf.

    Sert de collecte courante quand la recherche des comptes de recherche est fermée (21/11/2026 : X a changé
    son client web et la recherche rend « 404 »). Une requête à la fois, la pause du lecteur, arrêt devant un défi.
    """
    from datetime import date, timedelta

    from src.services.collection.x_html_parser import lire_page_recherche

    SORTIE.mkdir(parents=True, exist_ok=True)
    lecteur = mod.Lecteur(mod.INSTANCE, mod.PAUSE)
    recul = (date.today() - timedelta(days=RECUL_JOURS)).isoformat()
    total = 0
    for compte in comptes:
        vus = mod.deja_vus(compte)
        url, pages, neufs_compte = f"{mod.INSTANCE}/{compte}", 0, 0
        with (SORTIE / f"{compte}.ndjson").open("a", encoding="utf-8") as out:
            while pages < PAGES_FRAIS:
                tweets, suite, _ = lire_page_recherche(lecteur.page(url))
                pages += 1
                neufs = [t for a, t in tweets if a.lower() == compte.lower() and t["url"] not in vus]
                for t in neufs:
                    vus.add(t["url"])
                    out.write(json.dumps(t, ensure_ascii=False, default=str) + "\n")
                neufs_compte += len(neufs)
                # Le premier tweet peut être épinglé et ancien : on juge sur le dernier de la page.
                dernier = str(tweets[-1][1].get("published_at") or "") if tweets else ""
                if not neufs or not suite or (dernier and dernier[:10] < recul):
                    break
                url = f"{mod.INSTANCE}/{compte}" + suite[suite.index("?"):].replace("&amp;", "&")
        total += neufs_compte
        if neufs_compte:
            print(f"{compte} : {neufs_compte} tweets nouveaux, {pages} pages", flush=True)
    print(f"Passe fraîche terminée : {total} tweets nouveaux.", flush=True)
    return total


def main() -> int:
    if "--envoyer" in sys.argv:
        import os
        jeton = os.environ.get("API_TOKEN", "").strip()
        if not jeton:
            sys.exit("API_TOKEN manquant (et ED_URL pour l'adresse de la plateforme).")
        print(f"{envoyer_tout(jeton)} tweets nouveaux en base.")
        return 0
    mod = charger_lecteur()
    if "--frais" in sys.argv:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        try:
            rafraichir(mod, comptes_du_pool())
        except mod.Arret as exc:
            print(f"Arrêt : {exc}. Relancer plus tard reprend ; rien n'est perdu.", flush=True)
            return 2
        return 0
    if "--comptes" not in sys.argv:
        sys.argv += ["--comptes", *ordre()]
    if "--borne" not in sys.argv:
        sys.argv += ["--borne", "2022-01-01"]
    return mod.main()


if __name__ == "__main__":
    raise SystemExit(main())
