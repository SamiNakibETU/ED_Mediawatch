"""Document d'atelier pour valider le référentiel des enjeux (étape 4 du plan de finalisation).

Pour chaque enjeu : la question, l'échelle, les jalons, combien de tweets du corpus local en parlent, et trois
tweets réels de figures différentes. Les relecteurs décident sur pièces : garder, reformuler, fusionner, retirer.

Les tweets sont repérés par mots-clés (``MOTS``), seulement pour donner des exemples et un ordre de grandeur de la
matière disponible sur X. Ce n'est pas une mesure : un tweet trouvé peut ne pas prendre position, un tweet manqué
peut en prendre une. La lecture par les modèles, une fois le référentiel validé, fait foi.

Corpus : ``donnees/x-historique/*.ndjson`` (recherche) et ``donnees/x-timeline/*.ndjson`` (pages de profil).

    python -m src.scripts.atelier_enjeux        -> documents/<date>_atelier-referentiel.md
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from src.services.analysis.enjeux import ENJEUX, THEMES

ETUDE = Path(__file__).resolve().parents[4]
SOURCES = [ETUDE / "donnees" / "x-historique", ETUDE / "donnees" / "x-timeline"]

# expressions qui signalent qu'un tweet touche l'enjeu (insensible à la casse et aux accents simples)
MOTS: dict[str, str] = {
    "tva_energie": r"\btva\b.{0,40}(énergie|energie|carburant|électricité|electricite|gaz)|(carburant|énergie).{0,40}\btva\b",
    "impot_fortune": r"\bisf\b|\bifi\b|impôt sur la fortune|impot sur la fortune|fortune immobili",
    "impot_jeunes": r"(moins de 30 ans|jeunes de moins de 30).{0,60}(impôt|impot|exonér|exoner)",
    "deficit": r"\bdéficit|\bdeficit|\bdette publique|\bla dette\b",
    "autoroutes": r"\bautoroutes?\b|\bpéages?\b|\bpeages?\b",
    "retraites": r"retraite à (60|62|64)|départ à la retraite|age de départ|âge de départ|\b(60|62|64) ans\b.{0,30}retraite|\b(40|42|43) annuités",
    "reforme_2023": r"réforme des retraites|reforme des retraites|abrog\w+.{0,40}retraite|retraite.{0,40}abrog",
    "smic": r"\bsmic\b",
    "assurance_chomage": r"assurance[- ]chômage|assurance[- ]chomage|indemnisation (du|des) chômeurs",
    "euro": r"sortie de l'euro|sortir de l'euro|\bmonnaie unique\b|\bl'euro\b",
    "frexit": r"\bfrexit\b|sortir de l'union européenne|sortie de l'ue|quitter l'ue|quitter l'union",
    "primaute_droit": r"primauté du droit|primaute du droit|droit (européen|europeen).{0,40}(constitution|droit national)|bouclier constitutionnel",
    "contribution_ue": r"contribution (de la france )?(au budget|à l'ue|a l'ue)|budget (de l'ue|européen)",
    "libre_echange": r"\bmercosur\b|\bceta\b|libre[- ]échange|libre[- ]echange|accord commercial",
    "referendum_immigration": r"référendum sur l'immigration|referendum sur l'immigration",
    "droit_du_sol": r"droit du sol",
    "regroupement_familial": r"regroupement familial",
    "ame": r"\bame\b|aide médicale d'état|aide medicale d'etat",
    "priorite_nationale": r"priorité nationale|priorite nationale|préférence nationale|preference nationale",
    "binationaux": r"\bbinationa|double.nationalité",
    "remigration": r"\bremigration|\brémigration",
    "expulsions": r"\boqtf\b|\bexpuls|reconduite à la frontière",
    "peines_planchers": r"peines? planchers?",
    "peine_de_mort": r"peine de mort",
    "legitime_defense": r"légitime défense|legitime defense",
    "majorite_penale": r"majorité pénale|majorite penale|excuse de minorité|excuse de minorite",
    "voile": r"\bvoile\b|\bhijab|\babaya",
    "proportionnelle": r"\bproportionnelle\b|mode de scrutin",
    "referendum_initiative": r"\bric\b|référendum d'initiative|referendum d'initiative",
    "art_49_3": r"\b49[.,-]?3\b",
    "union_droites": (r"union des droites|alliance (avec|des) (lr|ciotti|républicains)|coalition des droites"
                      r"|union de la droite|rassemblement des droites|s.alli(e|er|ons|ent) (pas )?avec"
                      r"|(alliance|accord) avec (le |la |les )?(rn|rassemblement national|reconqu|lr|républicains|ciotti|zemmour|maréchal)"),
    "ivg_constitution": r"\bivg\b.{0,60}constitution|constitution.{0,60}\bivg\b",
    "mariage_pour_tous": r"mariage pour tous",
    "pma_gpa": r"\bpma\b|\bgpa\b",
    "fin_de_vie": r"fin de vie|aide à mourir|aide a mourir|euthanasie|suicide assisté",
    "ukraine": r"\bukrain|\bpoutine\b|\bzelensky",
    "sanctions_russie": r"sanctions?.{0,40}russ|russ.{0,40}sanctions?",
    "otan": r"\botan\b|\bnato\b",
    "etat_palestinien": r"état palestinien|etat palestinien|reconnaissance de la palestine|reconnaître la palestine",
    "budget_defense": r"budget (de la défense|des armées|militaire)|loi de programmation militaire|\blpm\b",
    "service_militaire": r"service (militaire|national)",
    "nucleaire": r"\bnucléaire|\bnucleaire|\bepr\b|centrales?",
    "eolien": r"\béolien|\beolien|\béoliennes",
    "zfe": r"\bzfe\b|zones? à faibles? émissions|zones? a faibles? emissions",
}


def corpus() -> list[dict]:
    """Tous les tweets locaux, une fois chacun (même adresse = même tweet)."""
    vus, out = set(), []
    for dossier in SOURCES:
        for f in sorted(dossier.glob("*.ndjson")) if dossier.exists() else []:
            for ligne in f.read_text(encoding="utf-8").splitlines():
                if not ligne.strip():
                    continue
                try:
                    t = json.loads(ligne)
                except ValueError:          # ligne en cours d'écriture par une collecte qui tourne
                    continue
                url = t.get("url")
                if not url or url in vus or not t.get("content"):
                    continue
                vus.add(url)
                out.append({"url": url, "auteur": url.split("/")[3] if url.count("/") >= 3 else "?",
                            "date": str(t.get("published_at", ""))[:10], "texte": t["content"]})
    return out


def exemples(tweets: list[dict], k: int = 3) -> list[dict]:
    """Les plus récents, un par figure."""
    pris, out = set(), []
    for t in sorted(tweets, key=lambda t: t["date"], reverse=True):
        if t["auteur"].lower() in pris:
            continue
        pris.add(t["auteur"].lower())
        out.append(t)
        if len(out) == k:
            break
    return out


def court(texte: str, n: int = 280) -> str:
    texte = " ".join(texte.split())
    return texte if len(texte) <= n else texte[: n - 1].rstrip() + "…"


def ecrire(sortie: Path) -> Path:
    tweets = corpus()
    figures = len({t["auteur"].lower() for t in tweets})
    lignes = [
        f"# Atelier : valider le référentiel des enjeux ({len(ENJEUX)} questions)",
        "",
        f"Document préparé le {date.today():%d/%m/%Y} pour l'étape 4 du plan de finalisation d'ED Mediawatch.",
        f"Corpus local : {len(tweets):,} tweets de {figures} figures (historique par recherche et pages de profil)."
        .replace(",", " "),
        "",
        "**Comment lire.** Pour chaque enjeu : la question posée aux tweets, l'échelle des positions (du premier au",
        "dernier cran), le nombre de tweets qui en parlent et trois exemples réels. Le décompte vient d'une recherche",
        "par mots-clés : il donne un ordre de grandeur de la matière disponible sur X, pas une mesure.",
        "",
        "**Ce qu'on décide pour chaque enjeu** : garder tel quel, reformuler la question ou l'échelle, fusionner avec",
        "un autre, ou retirer. Un enjeu qui ne départage personne, ou presque absent de X, n'apprend rien.",
        "Les trois précisions de consigne d'octobre restent à intégrer : négations conditionnelles, mesures limitées",
        "à un territoire, Europe « de l'intérieur ».",
        "",
    ]
    resume = []
    for theme_id, theme in THEMES.items():
        bloc = [e for e in ENJEUX if e.theme == theme_id]
        if not bloc:
            continue
        lignes += [f"## {theme}", ""]
        for e in bloc:
            motif = re.compile(MOTS.get(e.slug, re.escape(e.titre)), re.IGNORECASE)
            trouves = [t for t in tweets if motif.search(t["texte"])]
            auteurs = Counter(t["auteur"] for t in trouves)
            resume.append((e, len(trouves), len(auteurs)))
            lignes += [f"### {e.titre}", "", f"*{e.question}*", ""]
            lignes += [f"{c.rang}. {c.label}" for c in e.echelle]
            lignes.append("")
            if e.jalons:
                lignes += ["Jalons publics : " + " ; ".join(e.jalons), ""]
            lignes.append(f"Matière sur X : **{len(trouves)} tweets** de {len(auteurs)} figures"
                          + (f" (surtout {', '.join(a for a, _ in auteurs.most_common(3))})." if auteurs else "."))
            lignes.append("")
            for t in exemples(trouves):
                lignes.append(f"> **{t['auteur']}**, {t['date']} : {court(t['texte'])} ([lien]({t['url']}))")
                lignes.append("")
            lignes += ["Décision : ☐ garder  ☐ reformuler  ☐ fusionner avec … ☐ retirer", "",
                       "Notes : ", ""]
    peu = [f"{e.titre} ({n})" for e, n, _ in resume if n < 20]
    lignes += ["## En résumé", "",
               "| Enjeu | Tweets | Figures |", "|---|---|---|"]
    lignes += [f"| {e.titre} | {n} | {a} |" for e, n, a in sorted(resume, key=lambda x: -x[1])]
    lignes += ["", "Enjeux avec moins de 20 tweets, à discuter en priorité : " + (", ".join(peu) or "aucun") + "."]
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return sortie


if __name__ == "__main__":
    out = ecrire(ETUDE / "documents" / f"{date.today():%Y-%m-%d}_atelier-referentiel.md")
    print(out)
