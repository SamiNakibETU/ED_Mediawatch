"""Le programme d'un parti, lu une fois et rangé dans le référentiel des enjeux.

Pourquoi le lire hors de la production. Un programme ne change pas : on le lit
une fois, sur un poste, et le résultat va dans `data/programme/<source>.json`,
versionné. Ce fichier se relit, se corrige à la main, se compare d'une version
à l'autre ; la production ne fait que le charger (`ensure_programme`).

Le texte des livrets est mis en page sur deux colonnes : les mots sont coupés
en fin de ligne (« prévoi-/ra »). Ils sont recollés avant lecture, sinon la
vérification du verbatim échouerait sur chaque phrase coupée.

Les mêmes règles que pour les tweets : le référentiel est le même, le verbatim
doit se retrouver dans la page, un cran deviné passe hors liste.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from src.database import get_session_factory
from src.models.engagement_programme import EngagementProgramme
from src.services.analysis.enjeux import ENJEUX_VERSION, HORS_LISTE, referentiel_pour_prompt
from src.services.analysis.registre import DeclLue, valider

logger = structlog.get_logger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "programme"
CONSIGNES_VERSION = "programme-1"
PAGES_PAR_APPEL = 3


def nettoyer(texte: str) -> str:
    """Recolle les mots coupés en fin de ligne et remet le texte d'un seul tenant."""
    t = texte or ""
    t = re.sub(r"(\w)\s?-\s*\n\s*(\w)", r"\1\2", t)    # « in -\ntérêt » → « intérêt »
    t = re.sub(r"\s*\n\s*", " ", t)
    t = re.sub(r"(?<=\w) (?=[’'])|(?<=[’']) (?=\w)", "", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def pages(pdf: Path) -> list[tuple[int, str]]:
    """(numéro de page, texte nettoyé) pour chaque page qui porte du texte."""
    from pypdf import PdfReader  # lecture locale seulement : la production ne lit pas de PDF

    out = []
    for i, p in enumerate(PdfReader(str(pdf)).pages, 1):
        t = nettoyer(p.extract_text() or "")
        if len(t) > 80:
            out.append((i, t))
    return out


PROGRAMME_SYSTEM = (
    "Tu lis des pages d'un programme électoral français et tu en tires les ENGAGEMENTS : "
    "chaque mesure que le programme promet, propose ou refuse, pour un registre qui compare "
    "ces engagements à ce que disent ensuite les responsables du parti.\n\n"
    "# Règles\n"
    "1. Un engagement dit ce qui sera fait ou ce qu'il faut faire. Le constat, le diagnostic, "
    "la critique de l'adversaire et les chiffres de contexte ne sont pas des engagements.\n"
    "2. Si l'engagement répond à l'une des questions du référentiel ci-dessous, donne le code "
    "de l'enjeu et le code de position correspondant. Seulement les codes écrits.\n"
    f"3. Sinon, ou si aucun cran ne convient exactement, utilise l'enjeu « {HORS_LISTE} », "
    "laisse la position à null et écris l'objet en quelques mots (« créer 85 000 places de "
    "prison », « obliger les communes de plus de 10 000 habitants à avoir une police "
    "municipale »).\n"
    "4. Ne force jamais un cran, ne range jamais par voisinage de thème.\n"
    "5. verbatim : la phrase de la page qui porte l'engagement, recopiée à l'identique, une "
    "phrase au plus.\n"
    "6. modalite : « promet » (« nous ferons », « la loi prévoira »), « propose », « refuse ». "
    "valeur et unite seulement si la phrase contient un chiffre.\n"
    "7. Un même engagement répété sur deux pages ne s'écrit qu'une fois.\n\n"
    "# Référentiel\n"
    + referentiel_pour_prompt()
    + "\n\n# Réponse\n"
    'Un JSON : {"engagements": [{"page": 12, "enjeu": "...", "position": "...", "objet": null, '
    '"modalite": "promet", "valeur": null, "unite": null, "verbatim": "..."}]}. Une liste vide '
    "si les pages n'en contiennent aucun."
)


class EngLu(DeclLue):
    page: int | None = None


class Lecture(BaseModel):
    engagements: list[EngLu] = Field(default_factory=list)


def prompt_pages(livret: str, lot: list[tuple[int, str]]) -> str:
    return f"Livret : {livret}\n\n" + "\n\n".join(f"[page {n}]\n{t}" for n, t in lot)


async def lire_livret(llm, pdf: Path) -> list[dict]:
    """Les engagements d'un livret, validés contre le texte de leur page."""
    livret = pdf.stem
    pp = pages(pdf)
    par_page = dict(pp)
    out: list[dict] = []
    vus: set[str] = set()
    for i in range(0, len(pp), PAGES_PAR_APPEL):
        lot = pp[i:i + PAGES_PAR_APPEL]
        r = await llm.ask_json(tier=2, system=PROGRAMME_SYSTEM, prompt=prompt_pages(livret, lot),
                               schema=Lecture, task="programme", max_tokens=6000, raisonnement="low")
        texte_lot = " ".join(t for _, t in lot)
        for e in r.engagements:
            texte = par_page.get(e.page or -1, texte_lot)
            v = valider(e, texte) or valider(e, texte_lot)
            if v is None:
                continue
            cle = re.sub(r"\W+", "", v.verbatim.lower())[:200] + v.enjeu
            if cle in vus:
                continue
            vus.add(cle)
            page = e.page if e.page in par_page and v.verbatim[:40].lower() in par_page[e.page].lower() else next(
                (n for n, t in lot if v.verbatim[:40].lower() in t.lower()), e.page)
            out.append({"livret": livret, "page": page, "enjeu": v.enjeu, "position": v.position,
                        "objet": v.objet, "modalite": v.modalite, "valeur": v.valeur, "unite": v.unite,
                        "verbatim": v.verbatim.strip()})
    return out


# ── Chargement en production ────────────────────────────────────────────

def _empreinte(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def ensure_programme() -> dict:
    """Charge chaque `data/programme/*.json` dont l'empreinte a changé.

    La table est entièrement dérivée des fichiers : la recharger efface et
    réécrit les lignes d'une source, sans rien perdre qui ne soit dans le dépôt.
    """
    if not DATA_DIR.is_dir():
        return {"programme": "aucun fichier"}
    factory = get_session_factory()
    bilan = {}
    for path in sorted(DATA_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        source, empreinte = doc["source"], _empreinte(path)
        async with factory() as db:
            actuelle = await db.scalar(select(func.max(EngagementProgramme.empreinte))
                                       .where(EngagementProgramme.source == source))
            if actuelle == empreinte:
                bilan[source] = "à jour"
                continue
            await db.execute(delete(EngagementProgramme).where(EngagementProgramme.source == source))
            for e in doc["engagements"]:
                db.add(EngagementProgramme(
                    source=source, parti=doc["parti"], annee=doc["annee"], lecteur=doc.get("lecteur"),
                    empreinte=empreinte, livret=e["livret"], page=e.get("page"), enjeu=e["enjeu"],
                    position=e.get("position"), objet=(e.get("objet") or None) and e["objet"][:200],
                    modalite=e.get("modalite"), valeur=e.get("valeur"),
                    unite=(e.get("unite") or None) and e["unite"][:40], verbatim=e["verbatim"],
                ))
            await db.commit()
            bilan[source] = len(doc["engagements"])
    logger.info("programme.charge", **{k: str(v) for k, v in bilan.items()})
    return bilan


def entete(source: str, parti: str, annee: int, titre: str, lecteur: str) -> dict:
    return {"source": source, "parti": parti, "annee": annee, "titre": titre,
            "lecteur": lecteur, "version": f"{CONSIGNES_VERSION}/{ENJEUX_VERSION}"}
