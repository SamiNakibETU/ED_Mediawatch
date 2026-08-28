"""Construction des sujets à partir du Grand Livre — le chaînon manquant.

Diagnostic qui motive ce module : la chaîne d'analyse comparait des déclarations
partageant un THÈME (15 rayons : « économie », « institutions »). À cette
granularité, deux propos n'ont rien à voir : 3 751 déclarations, 0 contradiction
trouvable. Un sujet, c'est « l'âge de départ à la retraite », pas « économie ».

Deux signaux, dans cet ordre :

  1. **`stance_target`** — le LLM nomme l'objet de chaque déclaration
     (prompt decl-v2). C'est le signal fort : deux propos qui reçoivent le même
     libellé parlent du même objet. Coût nul, il est déjà produit.
  2. **entités partagées + cosinus** — repli pour les déclarations extraites
     avant decl-v2 (`stance_target` à NULL), et pour rapprocher deux libellés qui
     désignent le même objet avec des mots différents (« l'aide à l'Ukraine » /
     « le soutien militaire à Kiev »).

Le regroupement est incrémental et idempotent : relancer ne recrée rien, ça
rattache seulement ce qui ne l'était pas.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict

import structlog
from sqlalchemy import func, select

from src.database import get_session_factory
from src.models.claim import Claim
from src.models.subject import Subject
from src.services.analysis.subject_clustering import (
    ETA_ENTITY_OVERLAP,
    MERGE_COSINE,
    THETA_COSINE,
    cosine,
    entities_of,
    idf_weights,
    weighted_overlap,
)

logger = structlog.get_logger(__name__)

# Articles et déterminants : « l'âge de départ » et « âge de départ » sont le
# même sujet. On les retire de la forme comparable, pas du libellé affiché.
# Articles et prépositions vides, retirés PARTOUT dans le libellé : sans ça
# « l'aide militaire à l'Ukraine » et « aide militaire à Ukraine » deviennent
# deux sujets distincts — le même objet scindé en deux, donc jamais confronté.
_FILLER = {"l", "le", "la", "les", "un", "une", "des", "du", "de", "d",
           "au", "aux", "a", "en", "et", "the"}
_PUNCT = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")


def slugify(label: str) -> str:
    """Forme comparable d'un libellé de sujet."""
    s = "".join(
        c for c in unicodedata.normalize("NFD", (label or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    s = s.replace("'", " ").replace("’", " ")
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    kept = [w for w in s.split() if w not in _FILLER]
    return " ".join(kept)[:300]


def _mean(vectors: list[list[float]]) -> list[float]:
    n = len(vectors)
    return [sum(v[i] for v in vectors) / n for i in range(len(vectors[0]))]


async def build_subjects(*, min_claims: int = 2, limit: int = 8000) -> dict:
    """(Re)construit les sujets depuis les déclarations. Idempotent.

    `min_claims` : un sujet porté par une seule déclaration n'est pas un sujet,
    c'est un propos isolé — il n'y a rien à y confronter. On ne le matérialise
    pas, mais la déclaration reste dans le Grand Livre.
    """
    factory = get_session_factory()
    async with factory() as db:
        claims = list(
            (
                await db.execute(
                    select(Claim)
                    .where(Claim.embedding.isnot(None))
                    .order_by(Claim.published_at.asc().nullsfirst())
                    .limit(limit)
                )
            ).scalars().all()
        )

    if not claims:
        return {"subjects": 0, "assigned": 0, "skipped": "aucune déclaration embeddée"}

    # ── Étape 1 : regroupement exact par libellé de sujet ────────────────
    by_slug: dict[str, list[Claim]] = defaultdict(list)
    orphans: list[Claim] = []
    for c in claims:
        slug = slugify(c.stance_target) if c.stance_target else ""
        if len(slug) >= 4:
            by_slug[slug].append(c)
        else:
            orphans.append(c)

    # ── Étape 2 : les orphelins rejoignent un groupe par entités + cosinus ──
    # (déclarations d'avant decl-v2, sans libellé de sujet)
    groups: dict[str, list[Claim]] = dict(by_slug)
    centroids = {
        s: _mean([c.embedding for c in cs]) for s, cs in groups.items() if cs
    }
    ents = {
        s: set().union(*(entities_of(c.canonical or c.verbatim) for c in cs))
        for s, cs in groups.items()
    }

    # Clustering incrémental : une orpheline rejoint le meilleur groupe assez
    # proche, ou EN OUVRE UN. Sans cette création, un corpus entièrement
    # antérieur à decl-v2 ne produit aucun sujet — il n'y a aucun germe.
    # Rareté des entités, calculée UNE FOIS sur tout le corpus : c'est elle qui
    # permet de rapprocher deux propos ne partageant qu'un terme, pourvu qu'il
    # soit distinctif (« Fresnaye » vaut mieux que « national »).
    all_entities = [entities_of(c.canonical or c.verbatim) for c in claims]
    idf = idf_weights(all_entities)

    attached = seeded = 0
    for c in orphans:
        e = entities_of(c.canonical or c.verbatim)
        if len(e) < 2:
            continue  # ne nomme rien : ne fonde ni ne rejoint un sujet
        best, best_score = None, 0.0
        for s, cen in centroids.items():
            if weighted_overlap(e, ents[s], idf) < ETA_ENTITY_OVERLAP:
                continue
            sc = cosine(c.embedding, cen)
            if sc > best_score:
                best, best_score = s, sc

        if best and best_score >= THETA_COSINE:
            groups[best].append(c)
            # Centroïde en moyenne courante : le sujet se déplace en absorbant.
            n = len(groups[best])
            centroids[best] = [
                (v * (n - 1) + x) / n for v, x in zip(centroids[best], c.embedding)
            ]
            ents[best] |= e
            attached += 1
        else:
            # Nouveau sujet, nommé par ses entités les plus saillantes. Le
            # libellé restera provisoire jusqu'à une extraction decl-v2.
            slug = " ".join(sorted(e)[:4])[:300]
            if slug in groups:
                slug = f"{slug} {c.id}"
            groups[slug] = [c]
            centroids[slug] = list(c.embedding)
            ents[slug] = set(e)
            seeded += 1

    # ── Étape 3 : fusion des libellés désignant le même objet ────────────
    slugs = [s for s, cs in groups.items() if len(cs) >= min_claims]
    merged: dict[str, str] = {}
    for i, a in enumerate(slugs):
        if a in merged:
            continue
        for b in slugs[i + 1:]:
            if b in merged:
                continue
            if cosine(centroids[a], centroids[b]) >= MERGE_COSINE:
                merged[b] = a  # b rejoint a
    for b, a in merged.items():
        groups[a].extend(groups.pop(b, []))

    # ── Étape 4 : persistance ────────────────────────────────────────────
    kept = {s: cs for s, cs in groups.items() if len(cs) >= min_claims}
    created = updated = assigned = 0
    async with factory() as db:
        existing = {
            s.slug: s for s in (await db.execute(select(Subject))).scalars().all()
        }
        for slug, cs in kept.items():
            # Libellé retenu : la forme la plus fréquente dans le groupe.
            labels = Counter(c.stance_target for c in cs if c.stance_target)
            label = labels.most_common(1)[0][0] if labels else slug
            themes = Counter(c.theme for c in cs if c.theme)
            dates = [c.published_at for c in cs if c.published_at]
            speakers = {c.speaker_name for c in cs if c.speaker_name}

            subj = existing.get(slug)
            if subj is None:
                subj = Subject(slug=slug)
                db.add(subj)
                created += 1
            else:
                updated += 1
            # Un libellé posé par le LLM ou curé à la main ne se réécrit PAS :
            # la reconstruction détruisait le nommage à chaque passe, et le
            # sommaire retombait sur des sacs d'entités. Seuls les sujets encore
            # « auto » reçoivent le libellé calculé.
            if subj.status == "auto" or not subj.label:
                subj.label = label[:300]
            subj.theme = themes.most_common(1)[0][0] if themes else None
            subj.centroid = _mean([c.embedding for c in cs])
            subj.entities = sorted(
                set().union(*(entities_of(c.canonical or c.verbatim) for c in cs))
            )[:40]
            subj.n_claims = len(cs)
            subj.n_speakers = len(speakers)
            subj.first_seen = min(dates) if dates else None
            subj.last_seen = max(dates) if dates else None
        await db.commit()

        # Rattachement des déclarations (subject_id sur Claim).
        ids = {
            s.slug: s.id for s in (await db.execute(select(Subject))).scalars().all()
        }
        for slug, cs in kept.items():
            sid = ids.get(slug)
            if sid is None:
                continue
            for c in cs:
                obj = await db.get(Claim, c.id)
                if obj is not None and obj.subject_id != sid:
                    obj.subject_id = sid
                    assigned += 1
        await db.commit()

    stats = {
        "subjects": len(kept), "created": created, "updated": updated,
        "claims_assigned": assigned, "orphans_attached": attached, "subjects_seeded": seeded,
        "labels_merged": len(merged),
        "claims_without_subject": len(claims) - sum(len(cs) for cs in kept.values()),
    }
    logger.info("subjects.built", **stats)
    return stats
