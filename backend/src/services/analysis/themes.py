"""De quoi parle l'extrême droite : thème de chaque tweet, vecteurs, sujets de la semaine.

Deux outils, chacun à sa place.

* **Le thème**, fermé : les neuf thèmes du référentiel, plus « autre ». Il est
  posé sur tous les tweets, retweets compris, par lots de 40 au tier 1 sans
  raisonnement. C'est lui qui fait les courbes : stable, comparable d'un mois à
  l'autre, il dit quelle part de la parole va à l'immigration ou à l'Europe.
* **Le vecteur**, ouvert : la position du tweet dans un espace de sens. Il sert
  à faire émerger les sujets d'une semaine (« l'affaire du moment »), que le
  thème ne nomme pas. Il sert à explorer, jamais à décider d'une
  contradiction : les regroupements par similarité bougent avec la période, et
  c'est sur eux que l'ancienne chaîne avait fabriqué de faux rapprochements.

Pour l'instant, tout porte sur X. Les vecteurs sont calculés dans un espace qui
pourra accueillir plus tard les articles de presse, le jour où l'on voudra
comparer ce dont parle l'extrême droite à ce dont parlent les médias.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from src.database import get_session_factory
from src.models.personality import Personality
from src.models.post import Post
from src.models.sujet_semaine import SujetSemaine
from src.services.analysis.enjeux import THEMES
from src.services.analysis.llm_usage import BudgetExceeded, ProviderRefused

logger = structlog.get_logger(__name__)

THEME_VERSION = "themes-1"
AUTRE = "autre"
CODES = tuple(THEMES) + (AUTRE,)
LOT_THEMES = 40


def _texte(post: Post) -> str:
    t = re.sub(r"https?://\S+", " ", post.content or "")
    return re.sub(r"\s+", " ", t).strip()


# ── Le thème ────────────────────────────────────────────────────────────

THEME_SYSTEM = (
    "Tu ranges des tweets de responsables politiques français par thème. Pour chaque tweet, "
    "donne UN code parmi :\n"
    + "\n".join(f"- {code} : {nom}" for code, nom in THEMES.items())
    + f"\n- {AUTRE} : vie du parti, campagne, agenda, hommages, polémiques sans objet "
    "politique, tout le reste.\n\n"
    "Le thème est ce dont le tweet parle, pas ce qu'il défend. Une attaque contre "
    "un adversaire sur l'immigration est « immigration ». Un tweet cité, écrit par quelqu'un "
    "d'autre, aide à comprendre de quoi il s'agit.\n\n"
    'Réponds par un JSON : {"themes": ["code du tweet 1", "code du tweet 2", ...]}, un code '
    "par tweet, dans l'ordre, autant de codes que de tweets."
)


class Themes(BaseModel):
    themes: list[str] = Field(default_factory=list)


def prompt_themes(posts: list[Post]) -> str:
    blocs = []
    for i, p in enumerate(posts, 1):
        b = f"[{i}] {_texte(p)[:700]}"
        if p.quoted_content:
            b += f"\n    (cite : {p.quoted_content.strip()[:200]})"
        blocs.append(b)
    return "\n\n".join(blocs)


async def classer(*, limit: int = 4000) -> dict:
    """Pose un thème sur les tweets qui n'en ont pas sous la version courante."""
    from src.services.analysis.claim_llm import get_claim_llm

    llm = get_claim_llm()
    factory = get_session_factory()
    async with factory() as db:
        posts = list((await db.execute(
            select(Post).where(or_(Post.theme_lu.is_(None), Post.theme_lu != THEME_VERSION))
            .order_by(Post.published_at.desc().nullslast()).limit(limit)
        )).scalars().all())

    stats = {"classes": 0, "vides": 0, "echecs": 0, "budget_atteint": False}
    vides = [p for p in posts if len(_texte(p)) < 15]
    pleins = [p for p in posts if len(_texte(p)) >= 15]
    async with factory() as db:
        for p in vides:
            o = await db.get(Post, p.id)
            o.theme_ed, o.theme_lu = AUTRE, THEME_VERSION
        await db.commit()
    stats["vides"] = len(vides)

    try:
        for i in range(0, len(pleins), LOT_THEMES):
            lot = pleins[i:i + LOT_THEMES]
            try:
                r = await llm.ask_json(tier=1, system=THEME_SYSTEM, prompt=prompt_themes(lot),
                                       schema=Themes, task="themes", max_tokens=600, raisonnement="off")
            except (BudgetExceeded, ProviderRefused):
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("themes.echec", error=str(exc)[:160])
                stats["echecs"] += len(lot)
                continue
            if len(r.themes) != len(lot):
                # Une liste décalée attribuerait à chaque tweet le thème du
                # voisin : on ne garde rien, le lot repassera.
                stats["echecs"] += len(lot)
                continue
            async with factory() as db:
                for p, code in zip(lot, r.themes):
                    o = await db.get(Post, p.id)
                    o.theme_ed = code if code in CODES else AUTRE
                    o.theme_lu = THEME_VERSION
                await db.commit()
            stats["classes"] += len(lot)
    except BudgetExceeded:
        stats["budget_atteint"] = True
    logger.info("themes.passe", **stats)
    return stats


# ── Les vecteurs ────────────────────────────────────────────────────────

async def vectoriser(*, limit: int = 4000) -> dict:
    """Calcule le vecteur des tweets qui n'en ont pas pour le modèle actif."""
    from src.services.analysis.embeddings import backend_tag, get_embedder

    emb = get_embedder()
    if not emb.available():
        return {"skipped": "aucun modèle de vecteurs disponible"}
    tag = backend_tag()
    factory = get_session_factory()
    async with factory() as db:
        posts = list((await db.execute(
            select(Post).where(or_(Post.vecteur_tag.is_(None), Post.vecteur_tag != tag))
            .order_by(Post.published_at.desc().nullslast()).limit(limit)
        )).scalars().all())
    posts = [p for p in posts if len(_texte(p)) >= 15]
    faits = 0
    for i in range(0, len(posts), 480):
        lot = posts[i:i + 480]
        vecs = await emb.embed([_texte(p)[:2000] for p in lot])
        if len(vecs) != len(lot):
            break
        tag = backend_tag()  # le modèle a pu basculer en local pendant l'appel
        async with factory() as db:
            for p, v in zip(lot, vecs):
                o = await db.get(Post, p.id)
                o.vecteur, o.vecteur_tag = [round(x, 5) for x in v], tag
            await db.commit()
        faits += len(lot)
    return {"vectorises": faits, "modele": tag}


# ── Les sujets de la semaine ────────────────────────────────────────────

class Libelles(BaseModel):
    libelles: list[str] = Field(default_factory=list)


LIBELLE_SYSTEM = (
    "On te donne plusieurs groupes de tweets de responsables politiques français, publiés la "
    "même semaine. Chaque groupe parle d'un même sujet. Nomme le sujet de chaque groupe en "
    "quelques mots, de façon factuelle et neutre, comme un titre de rubrique (« la réforme des "
    "retraites à l'Assemblée », « l'attaque au couteau d'Annecy »). Pas de jugement, pas "
    "d'adjectif qui prend parti. Si deux groupes parlent du même événement, donne-leur "
    "exactement le même libellé.\n\n"
    'Réponds par un JSON : {"libelles": ["sujet du groupe 1", ...]}, dans l\'ordre.'
)


def regrouper(vecteurs, *, seuil: float = 0.74, fusion: float = 0.84) -> list[list[int]]:
    """Regroupement « par chef de file » : chaque tweet rejoint le groupe le plus proche
    au-dessus du seuil, sinon il en ouvre un. Linéaire, déterministe dans un ordre donné,
    suffisant pour quelques milliers de tweets par semaine.

    Réglé sur la semaine du 19 octobre 2026 (1 545 tweets, vecteurs Cohere) : à
    0,62 deux groupes absorbaient la moitié de la semaine (« critiques de
    l'opposition », 482 tweets) ; à 0,74 les sujets sont nommables. Un même
    événement se coupe parfois en deux (le meeting d'Orléans, 41 et 30
    tweets) : une seconde passe fusionne les groupes dont les centres sont
    très proches."""
    import numpy as np

    if not len(vecteurs):
        return []
    x = np.asarray(vecteurs, dtype=np.float32)
    x /= np.linalg.norm(x, axis=1, keepdims=True) + 1e-9
    centres: list = []
    membres: list[list[int]] = []
    for i, v in enumerate(x):
        if centres:
            sims = np.asarray(centres) @ v
            j = int(sims.argmax())
            if sims[j] >= seuil:
                membres[j].append(i)
                c = x[membres[j]].mean(axis=0)
                centres[j] = c / (np.linalg.norm(c) + 1e-9)
                continue
        centres.append(v.copy())
        membres.append([i])

    # Fusion des groupes jumeaux, du plus gros au plus petit.
    ordre = sorted(range(len(membres)), key=lambda k: -len(membres[k]))
    gardes: list[int] = []
    for k in ordre:
        if len(membres[k]) >= 2:
            cible = next((g for g in gardes if float(centres[g] @ centres[k]) >= fusion), None)
            if cible is not None:
                membres[cible] += membres[k]
                c = x[membres[cible]].mean(axis=0)
                centres[cible] = c / (np.linalg.norm(c) + 1e-9)
                continue
        gardes.append(k)
    return [membres[k] for k in gardes]


def semaine_iso(d: datetime) -> tuple[str, datetime]:
    lundi = (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    an, num, _ = lundi.isocalendar()
    return f"{an}-W{num:02d}", lundi


async def sujets_de_la_semaine(lundi: datetime, *, top: int = 12, min_tweets: int = 5,
                               min_figures: int = 2) -> dict:
    """Regroupe les tweets d'une semaine, nomme les plus gros groupes, et les enregistre."""
    from sqlalchemy import delete

    from src.services.analysis.claim_llm import get_claim_llm

    semaine, lundi = semaine_iso(lundi)
    fin = lundi + timedelta(days=7)
    factory = get_session_factory()
    async with factory() as db:
        rows = (await db.execute(
            select(Post.id, Post.personality_id, Post.vecteur, Post.theme_ed, Post.content)
            .where(Post.published_at >= lundi, Post.published_at < fin, Post.vecteur.isnot(None))
            .order_by(Post.published_at)
        )).all()
    if len(rows) < min_tweets:
        return {"semaine": semaine, "sujets": 0, "tweets": len(rows)}
    groupes = regrouper([r.vecteur for r in rows])
    # Les retweets d'un même tweet portent le même texte : deux groupes qui en
    # partagent un parlent du même sujet, et se réunissent avant d'être nommés.
    def _norme(i: int) -> str:
        t = re.sub(r"https?://\S+", "", rows[i].content or "").lower()
        return re.sub(r"\W+", " ", t).strip()[:160]

    proprietaire: dict[str, int] = {}
    parent = list(range(len(groupes)))

    def _racine(a: int) -> int:
        while parent[a] != a:
            a = parent[a]
        return a

    for k, g in enumerate(groupes):
        for i in g:
            t = _norme(i)
            if len(t) < 30:
                continue
            if t in proprietaire:
                parent[_racine(k)] = _racine(proprietaire[t])
            else:
                proprietaire[t] = k
    reunis: dict[int, list[int]] = {}
    for k, g in enumerate(groupes):
        reunis.setdefault(_racine(k), []).extend(g)
    groupes = list(reunis.values())
    candidats = []
    for g in groupes:
        figures = {rows[i].personality_id for i in g}
        if len(g) >= min_tweets and len(figures) >= min_figures:
            candidats.append((g, figures))
    candidats.sort(key=lambda c: (-len(c[1]), -len(c[0])))
    candidats = candidats[:top]
    if not candidats:
        return {"semaine": semaine, "sujets": 0, "tweets": len(rows)}

    llm = get_claim_llm()
    # Pas d'expression régulière dans une f-string : la barre oblique inverse
    # n'y est permise qu'à partir de Python 3.12.
    def _court(i: int) -> str:
        return re.sub(r"https?://\S+", "", rows[i].content or "")[:220]

    prompt = "\n\n".join(
        f"## Groupe {k}\n" + "\n".join("- " + _court(i) for i in g[:6])
        for k, (g, _) in enumerate(candidats, 1))
    r = await llm.ask_json(tier=1, system=LIBELLE_SYSTEM, prompt=prompt, schema=Libelles,
                           task="sujets_semaine", max_tokens=800, raisonnement="off")
    libelles = r.libelles if len(r.libelles) == len(candidats) else [None] * len(candidats)

    # Deux groupes qui reçoivent le même nom sont le même sujet, coupé en deux
    # par les retweets d'un même texte : on les réunit.
    fusion: dict[str, tuple[list[int], set]] = {}
    for (g, figures), lib in zip(candidats, libelles):
        cle = re.sub(r"\W+", " ", (lib or f"sujet {len(fusion) + 1}").lower()).strip()
        if cle in fusion:
            fusion[cle][0].extend(g)
            fusion[cle][1].update(figures)
        else:
            fusion[cle] = (list(g), set(figures))
    noms = {re.sub(r"\W+", " ", (lib or "").lower()).strip(): lib for lib in libelles if lib}
    regroupes = sorted(fusion.items(), key=lambda kv: (-len(kv[1][1]), -len(kv[1][0])))

    async with factory() as db:
        await db.execute(delete(SujetSemaine).where(SujetSemaine.semaine == semaine))
        for k, (cle, (g, figures)) in enumerate(regroupes, 1):
            lib = noms.get(cle)
            theme = Counter(rows[i].theme_ed for i in g if rows[i].theme_ed).most_common(1)
            db.add(SujetSemaine(
                semaine=semaine, debut=lundi, ordre=k, libelle=(lib or f"sujet {k}")[:200],
                theme=theme[0][0] if theme else None, n_tweets=len(g), n_figures=len(figures),
                post_ids=[rows[i].id for i in g], modele=llm.model_for(1),
            ))
        await db.commit()
    return {"semaine": semaine, "sujets": len(candidats), "tweets": len(rows)}


async def sujets_recents(*, semaines: int = 2) -> dict:
    """La semaine en cours et la précédente, recalculées à chaque passe."""
    now = datetime.now(timezone.utc)
    return {"semaines": [await sujets_de_la_semaine(now - timedelta(days=7 * k)) for k in range(semaines)]}


# ── Lecture, pour la page Thèmes ────────────────────────────────────────

PAS = {"heure", "jour", "semaine", "mois"}


def _case(d: datetime, pas: str) -> str:
    if pas == "heure":
        return d.strftime("%Y-%m-%dT%H:00")
    if pas == "jour":
        return d.strftime("%Y-%m-%d")
    if pas == "semaine":
        return semaine_iso(d)[1].strftime("%Y-%m-%d")
    return d.strftime("%Y-%m")


async def serie(db, *, pas: str, debut: datetime, fin: datetime, parti: str | None = None,
                figure_id: int | None = None, retweets: bool = True) -> dict:
    """Le nombre de tweets par thème et par case de temps, sur une période."""
    stmt = (select(Post.published_at, Post.theme_ed, Post.post_type, Post.is_retweet)
            .join(Personality, Personality.id == Post.personality_id)
            .where(Post.published_at >= debut, Post.published_at < fin, Post.theme_ed.isnot(None)))
    if parti:
        stmt = stmt.where(Personality.group_code == parti)
    if figure_id:
        stmt = stmt.where(Post.personality_id == figure_id)
    cases: dict[str, Counter] = {}
    for d, theme, ptype, rt in (await db.execute(stmt)).all():
        if not retweets and (rt or ptype == "retweet"):
            continue
        cases.setdefault(_case(d, pas), Counter())[theme] += 1
    ordre = sorted(cases)
    return {"pas": pas, "themes": [{"code": c, "label": THEMES.get(c, "Autre")} for c in CODES],
            "cases": [{"case": k, **{c: cases[k].get(c, 0) for c in CODES}} for k in ordre]}
