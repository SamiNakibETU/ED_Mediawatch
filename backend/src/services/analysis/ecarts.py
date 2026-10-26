"""Les confrontations : détecter les écarts par requête, vérifier, juger deux fois.

La détection ne devine rien. Elle compare des positions déjà rangées sur la même
échelle, ou des chiffres annoncés pour une même mesure, et ne retient que ce qui
diffère. Ce qui reste à établir, c'est si l'écart est réel.

Sans relecture humaine pour l'instant, trois verrous successifs :

1. **Le second avis.** Chaque déclaration qui crée un écart est relue seule, avec
   une question fermée : ce texte dit-il bien cela ? Mesuré le 26/10/2026 : les
   écarts concentrent les erreurs d'extraction (7 des 10 premiers écarts
   relevaient d'une lecture fausse). Une déclaration mal lue devient
   « douteuse » et sort de tout calcul.
2. **Deux juges de familles différentes.** Chacun relit les deux textes, vérifie
   la lecture de chaque côté, puis qualifie l'écart. Deux modèles se trompent
   rarement de la même façon.
3. **La décision automatique.** « retenu » seulement si les deux juges tiennent
   l'écart pour réel ; « écarté » si l'un relève une erreur de lecture ou un
   contexte différent ; « faible » sinon. Rien n'est présenté comme vérifié par
   un humain.

Le parti de chaque propos est celui du jour où il a été tenu (`party_of`).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import structlog
from pydantic import BaseModel
from sqlalchemy import or_, select

from src.database import get_session_factory
from src.models.declaration import Declaration
from src.models.ecart import Ecart
from src.models.engagement_programme import EngagementProgramme
from src.models.personality import Personality
from src.models.post import Post
from src.services.affiliation import all_affiliations, party_of
from src.services.analysis.enjeux import HORS_LISTE, PAR_SLUG, Point, ecarts as ecarts_temps
from src.services.analysis.llm_usage import BudgetExceeded, ProviderRefused
from src.utils import sha256

logger = structlog.get_logger(__name__)

FENETRE_PARTI = timedelta(days=90)
PARTIS_ED = ("RN", "UDR", "Reconquete")
REELS = ("revirement", "glissement", "report_condition", "imprecision_chiffree",
         "divergence", "ecart_au_programme")
ERREURS = ("erreur_de_lecture", "contexte_different")
SEUIL_CHIFFRE = 0.10  # deux chiffres à moins de 10 % l'un de l'autre sont un arrondi


def _cle(*parts) -> str:
    return sha256(":".join(str(p) for p in parts))[:64]


def _norme(t: str | None) -> str:
    return re.sub(r"\W+", " ", (t or "").lower()).strip()


def _sain(d: Declaration) -> bool:
    return not d.douteuse


# ── Détection ───────────────────────────────────────────────────────────

async def detecter() -> dict:
    """Recalcule les écarts des quatre types. N'écrase jamais un écart déjà tranché."""
    factory = get_session_factory()
    async with factory() as db:
        rows = (await db.execute(
            select(Declaration, Personality)
            .join(Personality, Personality.id == Declaration.personality_id)
            .where(Declaration.published_at.isnot(None))
        )).all()
        affils = await all_affiliations(db)
        prog = (await db.execute(
            select(EngagementProgramme).where(EngagementProgramme.position.isnot(None)))).scalars().all()
        existantes = set((await db.execute(select(Ecart.cle))).scalars().all())

    parti_de: dict[int, str | None] = {}
    par_enjeu: dict[str, list[Declaration]] = defaultdict(list)
    chiffrees: dict[tuple, list[Declaration]] = defaultdict(list)
    for d, p in rows:
        if not _sain(d):
            continue
        parti_de[d.id] = party_of(affils, p, d.published_at)
        if d.enjeu in PAR_SLUG and PAR_SLUG[d.enjeu].cran(d.position):
            par_enjeu[d.enjeu].append(d)
        if d.valeur is not None and d.unite:
            # Une même mesure : même enjeu (ou même objet hors liste), même unité.
            objet = d.enjeu if d.enjeu != HORS_LISTE else f"hl:{_norme(d.objet)}"
            chiffrees[(objet, _norme(d.unite))].append(d)

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
            valeur_a=f"{a.valeur:g} {a.unite}" if a.valeur is not None else None,
            valeur_b=f"{b.valeur:g} {b.unite}" if b is not None and b.valeur is not None else None,
            ampleur=ampleur, cle=cle,
        ))

    for slug, items in par_enjeu.items():
        enjeu = PAR_SLUG[slug]
        rang = {c.code: c.rang for c in enjeu.echelle}
        par_id = {d.id: d for d in items}

        # 1. Une même figure dans le temps.
        points = [Point(d.personality_id, d.position, d.published_at, d.id) for d in items]
        for e in ecarts_temps(enjeu, points):
            ajouter("temps", slug, par_id[e.avant.post_id], par_id[e.apres.post_id], ampleur=e.ampleur)

        # 2. Contre le programme de son parti, après sa publication.
        crans_prog: dict[tuple[str, int], list[EngagementProgramme]] = defaultdict(list)
        for g in prog:
            if g.enjeu == slug:
                crans_prog[(g.parti, g.annee)].append(g)
        for d in items:
            for (parti, annee), engs in crans_prog.items():
                if parti_de.get(d.id) != parti or d.published_at.year < annee:
                    continue
                if d.position not in {g.position for g in engs}:
                    proche = min(engs, key=lambda g: abs(rang[g.position] - rang[d.position]))
                    ajouter("programme", slug, d, eng=proche,
                            ampleur=abs(rang[proche.position] - rang[d.position]))

        # 3. Deux voix du même parti, au même moment : pour chaque paire de
        # figures et de crans, les deux propos les plus proches dans le temps.
        meilleurs: dict[tuple, tuple[timedelta, Declaration, Declaration]] = {}
        tries = sorted(items, key=lambda x: x.published_at)
        for i, a in enumerate(tries):
            for b in tries[i + 1:]:
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

    # 4. Imprécision chiffrée : une même mesure, deux chiffres, au sein d'un
    # même parti (ou d'une même personne). Pour chaque paire de figures et de
    # valeurs, une seule fois.
    vus: set[tuple] = set()
    for (objet, _unite), items in chiffrees.items():
        tries = sorted(items, key=lambda x: x.published_at)
        for i, a in enumerate(tries):
            for b in tries[i + 1:]:
                pa, pb = parti_de.get(a.id), parti_de.get(b.id)
                if not pa or pa != pb:
                    continue
                va, vb = abs(a.valeur), abs(b.valeur)
                if max(va, vb) == 0 or abs(va - vb) / max(va, vb) < SEUIL_CHIFFRE:
                    continue
                k = (a.personality_id, b.personality_id, a.valeur, b.valeur, objet)
                if k in vus:
                    continue
                vus.add(k)
                ecart_rel = abs(va - vb) / max(va, vb)
                enjeu_code = a.enjeu if a.enjeu in PAR_SLUG else HORS_LISTE
                ajouter("chiffre", enjeu_code, a, b, ampleur=2 if ecart_rel >= 0.5 else 1)

    async with factory() as db:
        db.add_all(nouveaux)
        await db.commit()
    bilan = Counter(e.type for e in nouveaux)
    logger.info("ecarts.detectes", **{k: v for k, v in bilan.items()})
    return {"nouveaux": dict(bilan), "total_nouveaux": len(nouveaux)}


# ── Divergences entre partis ────────────────────────────────────────────

async def divergences(db, *, depuis_jours: int = 365) -> list[dict]:
    """La position dominante de RN, UDR et Reconquête sur chaque enjeu, et là où elles diffèrent."""
    depuis = datetime.now(timezone.utc) - timedelta(days=depuis_jours)
    rows = (await db.execute(
        select(Declaration, Personality)
        .join(Personality, Personality.id == Declaration.personality_id)
        .where(Declaration.position.isnot(None), Declaration.published_at >= depuis,
               or_(Declaration.douteuse.is_(None), Declaration.douteuse.is_(False)))
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


# ── Le second avis ──────────────────────────────────────────────────────

AVIS_SYSTEM = (
    "Tu vérifies la lecture d'une déclaration politique. On te donne un tweet, une question, "
    "et la position qu'un premier lecteur a attribuée à l'auteur du tweet sur cette question. "
    "Réponds seulement à ceci : le tweet dit-il bien, de la part de son auteur, cette "
    "position-là ?\n\n"
    "- « conforme » : oui, c'est ce que dit le texte.\n"
    "- « autre » : l'auteur prend bien position sur la question, mais pas celle-là. Donne "
    "alors le code de la bonne position, s'il est dans l'échelle.\n"
    "- « aucune » : le texte ne prend pas position sur cette question, ou c'est la position "
    "de quelqu'un d'autre.\n\n"
    "Attention aux négations (« sans nous, pas de baisse » veut dire que l'auteur veut la "
    "baisse) et aux mesures limitées à un territoire ou une catégorie.\n\n"
    'Réponds par un JSON : {"avis": "conforme|autre|aucune", "position": null, "raison": "une phrase"}'
)


class Avis(BaseModel):
    avis: str = "conforme"
    position: str | None = None
    raison: str = ""


async def second_avis(*, limit: int = 80) -> dict:
    """Relit seule chaque déclaration qui crée un écart encore ouvert."""
    from src.services.analysis.claim_llm import get_claim_llm

    llm = get_claim_llm()
    factory = get_session_factory()
    async with factory() as db:
        ids: set[int] = set()
        for a, b in (await db.execute(
                select(Ecart.decl_a_id, Ecart.decl_b_id).where(Ecart.auto.is_(None)))).all():
            ids.add(a)
            if b:
                ids.add(b)
        decls = list((await db.execute(
            select(Declaration).where(Declaration.id.in_(ids), Declaration.verification.is_(None))
            .limit(limit))).scalars().all()) if ids else []
    stats = {"verifiees": 0, "douteuses": 0, "echecs": 0, "budget_atteint": False}
    for d in decls:
        enjeu = PAR_SLUG.get(d.enjeu)
        if enjeu is None:
            continue
        async with factory() as db:
            post = await db.get(Post, d.post_id)
        echelle = "\n".join(f"- {c.code} : {c.label}" for c in enjeu.echelle)
        cran = enjeu.cran(d.position)
        valeur = f"\nChiffre retenu : {d.valeur:g} {d.unite}" if d.valeur is not None else ""
        prompt = (f"Question : {enjeu.question}\nÉchelle :\n{echelle}\n\n"
                  f"Position attribuée : {d.position} ({cran.label if cran else '?'}){valeur}\n"
                  f"Phrase retenue : « {d.verbatim} »\n\nTweet complet :\n«««\n{post.content[:1500]}\n»»»")
        try:
            a = await llm.ask_json(tier=2, system=AVIS_SYSTEM, prompt=prompt, schema=Avis,
                                   task="second_avis", max_tokens=1500, raisonnement="low")
        except BudgetExceeded:
            stats["budget_atteint"] = True
            break
        except ProviderRefused:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("ecarts.avis_echec", decl=d.id, error=str(exc)[:160])
            stats["echecs"] += 1
            continue
        async with factory() as db:
            o = await db.get(Declaration, d.id)
            o.verification_par = f"avis-1/{llm.model_for(2)}"[:120]
            if a.avis == "conforme":
                o.verification = "conforme"
            else:
                o.verification, o.douteuse = "douteuse", True
                o.doute_motif = (f"second avis : {a.avis}"
                                 + (f", plutôt {a.position}" if a.position else "")
                                 + (f". {a.raison}" if a.raison else ""))[:300]
                stats["douteuses"] += 1
            await db.commit()
        stats["verifiees"] += 1
    if stats["douteuses"]:
        stats["ecarts_ecartes"] = await _ecarter_douteux()
    logger.info("ecarts.second_avis", **stats)
    return stats


async def _ecarter_douteux() -> int:
    """Les écarts encore ouverts qui reposent sur une déclaration douteuse sont écartés."""
    factory = get_session_factory()
    n = 0
    async with factory() as db:
        douteuses = set((await db.execute(
            select(Declaration.id).where(Declaration.douteuse.is_(True)))).scalars().all())
        for e in (await db.execute(select(Ecart).where(Ecart.auto.is_(None)))).scalars():
            if e.decl_a_id in douteuses or (e.decl_b_id and e.decl_b_id in douteuses):
                e.auto = "ecarte"
                n += 1
        await db.commit()
    return n


# ── Les deux juges ──────────────────────────────────────────────────────

JUGE_SYSTEM = (
    "Tu examines un écart relevé automatiquement entre deux positions politiques sur une même "
    "question. Les positions ont été lues par un modèle dans des tweets : ta première tâche est de "
    "vérifier cette lecture.\n\n"
    "1. Relis chaque texte. La position attribuée à A est-elle bien celle que dit A ? Même "
    "question pour B. Réponds par lecture_a et lecture_b (« juste » ou « fausse »). Si l'une "
    "est fausse, le type est « erreur_de_lecture ».\n"
    "2. Les deux textes parlent-ils de la même chose (même mesure, même portée, même contexte) ? "
    "Sinon, le type est « contexte_different ».\n"
    "3. Sinon, qualifie le mouvement, même s'il est petit :\n"
    "   - « revirement » : position opposée ;\n"
    "   - « glissement » : position voisine ;\n"
    "   - « report_condition » : même objectif, mais reporté ou soumis à une condition nouvelle ;\n"
    "   - « imprecision_chiffree » : même mesure, chiffres différents (au-delà d'un arrondi) ;\n"
    "   - « divergence » : deux personnes du même camp qui disent des choses incompatibles ;\n"
    "   - « ecart_au_programme » : la personne contredit le programme de son parti ;\n"
    "   - « nuance » : la différence tient à la formulation, pas au fond.\n"
    "4. force : 0 (aucun écart réel) à 3 (écart net, qu'un journaliste publierait).\n"
    "5. justification : « oui » si l'un des textes explique publiquement le changement, « non » "
    "sinon, « inconnue » si on ne peut pas savoir.\n"
    "6. explication : deux phrases au plus, factuelles, qui citent les mots des textes.\n\n"
    'Réponds par un JSON : {"lecture_a": "juste", "lecture_b": "juste", "type": "...", '
    '"force": 0, "justification": "...", "explication": "..."}'
)


class Verdict(BaseModel):
    lecture_a: str = "juste"
    lecture_b: str = "juste"
    type: str = "nuance"
    force: int = 0
    justification: str = "inconnue"
    explication: str = ""


def _bloc(titre: str, nom: str, date, position: str, texte: str, valeur: str | None = None) -> str:
    j = date.date().isoformat() if date else "date inconnue"
    v = f"\nChiffre retenu : {valeur}" if valeur else ""
    return f"## {titre} : {nom}, {j}\nPosition attribuée : {position}{v}\nTexte :\n«««\n{texte.strip()[:1500]}\n»»»"


def decision_auto(v1: Verdict, v2: Verdict | None) -> str:
    """retenu si les deux juges tiennent l'écart pour réel, écarté si l'un relève une erreur."""
    verdicts = [v for v in (v1, v2) if v is not None]
    if any(v.type in ERREURS for v in verdicts):
        return "ecarte"
    if v2 is not None and all(v.type in REELS and v.force >= 2 for v in verdicts):
        return "retenu"
    return "faible"


async def _prompt_ecart(db, e: Ecart) -> tuple[str, Declaration, Declaration | None]:
    enjeu = PAR_SLUG.get(e.enjeu)
    question = enjeu.question if enjeu else "même mesure, chiffres annoncés"
    label = (lambda code: (enjeu.cran(code).label if enjeu and enjeu.cran(code) else (code or "chiffre")))
    da = await db.get(Declaration, e.decl_a_id)
    pa = await db.get(Post, da.post_id)
    fa = await db.get(Personality, e.figure_a_id)
    blocs = [_bloc("A", f"{fa.full_name} ({e.parti_a or '?'})", da.published_at,
                   label(e.position_a), pa.content, e.valeur_a)]
    db_ = None
    if e.decl_b_id:
        db_ = await db.get(Declaration, e.decl_b_id)
        pb = await db.get(Post, db_.post_id)
        fb = await db.get(Personality, e.figure_b_id)
        blocs.append(_bloc("B", f"{fb.full_name} ({e.parti_b or '?'})", db_.published_at,
                           label(e.position_b), pb.content, e.valeur_b))
    elif e.engagement_id:
        g = await db.get(EngagementProgramme, e.engagement_id)
        blocs.append(f"## B : programme {g.parti} {g.annee}, livret {g.livret}, page {g.page}\n"
                     f"Position attribuée : {label(g.position)}\nTexte :\n«««\n{g.verbatim}\n»»»")
    prompt = f"Question : {question}\nType d'écart relevé : {e.type}\n\n" + "\n\n".join(blocs)
    return prompt, da, db_


async def juger(*, limit: int = 40) -> dict:
    """Fait relire par les deux juges les écarts ouverts, puis décide automatiquement."""
    from src.services.analysis.claim_llm import get_claim_llm

    llm = get_claim_llm()
    juge2 = llm._s.juge2_model
    factory = get_session_factory()
    async with factory() as db:
        a_juger = list((await db.execute(
            select(Ecart).where(Ecart.auto.is_(None), Ecart.statut == "a_relire")
            .order_by(Ecart.ampleur.desc(), Ecart.date_b.desc().nullslast()).limit(limit)
        )).scalars().all())
    stats = {"juges": 0, "retenus": 0, "faibles": 0, "ecartes": 0, "echecs": 0, "budget_atteint": False}
    for e in a_juger:
        async with factory() as db:
            prompt, da, db_ = await _prompt_ecart(db, e)
        try:
            v1 = await llm.ask_json(tier=2, system=JUGE_SYSTEM, prompt=prompt, schema=Verdict,
                                    task="juge_ecarts", max_tokens=2500, raisonnement="low")
            v2 = await llm.ask_json(tier=2, system=JUGE_SYSTEM, prompt=prompt, schema=Verdict,
                                    task="juge2_ecarts", max_tokens=2500, raisonnement="low", model=juge2)
        except BudgetExceeded:
            stats["budget_atteint"] = True
            break
        except ProviderRefused:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("ecarts.juge_echec", ecart=e.id, error=str(exc)[:160])
            stats["echecs"] += 1
            continue
        auto = decision_auto(v1, v2)
        async with factory() as db:
            o = await db.get(Ecart, e.id)
            o.juge_type, o.juge_force = v1.type[:20], max(0, min(3, int(v1.force)))
            o.juge_justification = v1.justification if v1.justification in ("oui", "non", "inconnue") else "inconnue"
            o.juge_explication, o.juge_lecteur = v1.explication[:1500], f"juge-2/{llm.model_for(2)}"[:120]
            o.juge2_type, o.juge2_force = v2.type[:20], max(0, min(3, int(v2.force)))
            o.juge2_explication, o.juge2_lecteur = v2.explication[:1500], f"juge-2/{juge2}"[:120]
            o.auto = auto
            # Une lecture jugée fausse par les deux juges rend la déclaration douteuse.
            for cote, decl in (("a", da), ("b", db_)):
                if decl is None:
                    continue
                if getattr(v1, f"lecture_{cote}") == "fausse" and getattr(v2, f"lecture_{cote}") == "fausse":
                    od = await db.get(Declaration, decl.id)
                    od.douteuse = True
                    od.doute_motif = f"les deux juges de l'écart {e.id} jugent la lecture fausse"
            await db.commit()
        stats["juges"] += 1
        stats[{"retenu": "retenus", "faible": "faibles", "ecarte": "ecartes"}[auto]] += 1
    logger.info("ecarts.juges", **stats)
    return stats
