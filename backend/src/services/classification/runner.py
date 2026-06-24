"""Passe de classification thématique sur les items (posts X + articles presse).

Stratégie §6 en deux temps :
  1. déterministe (lexiques CAP) — gratuit, couvre l'essentiel ;
  2. Cohere (embeddings) en FALLBACK sur les items que le lexique rate (score 0),
     rattachement au thème le plus proche d'ancres (libellé + mots-clés curés).

Idempotente / rejouable : ne (re)classe que les items sans thème, sauf `reset`.
Écrit sur les champs `theme`/`subtheme` déjà présents sur Post et Article.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select

from src.database import get_session_factory
from src.models.article import Article
from src.models.post import Post
from src.services.analysis.embeddings import cosine, get_embedder
from src.services.classification.theme_classifier import _lexicon, get_classifier

logger = structlog.get_logger(__name__)

# Cosinus minimal pour accepter un rattachement Cohere (fallback). Conservateur :
# en-deçà, on laisse l'item NON CLASSÉ plutôt que de forcer un thème douteux
# (un « non classé » honnête vaut mieux qu'un thème bruité — cf. it.2 : un seuil
# trop bas gonflait artificiellement travail_emploi / science_techno).
_COHERE_MIN = 0.42
_EMBED_BATCH = 96  # limite raisonnable par appel Cohere
_EMBED_MAXLEN = 1500  # tronque le texte embeddé (borne le coût)


def _post_text(p: Post) -> str:
    return p.content or ""


def _article_text(a: Article) -> str:
    return f"{a.title}. {a.content or ''}"


async def _build_anchors(embedder) -> dict[str, list[float]]:
    """Embedding d'une ancre par thème (nom du thème + mots-clés curés)."""
    lex = _lexicon()["themes"]
    ids = list(lex.keys())
    texts = [
        ", ".join([tid.replace("_", " ")] + lex[tid].get("keywords", [])[:25])
        for tid in ids
    ]
    vecs = await embedder.embed(texts)
    return dict(zip(ids, vecs)) if vecs else {}


async def _cohere_fallback(misses, anchors, embedder) -> int:
    """Classe par plus proche ancre les items ratés par le lexique. Renvoie le
    nombre rattaché."""
    n = 0
    for i in range(0, len(misses), _EMBED_BATCH):
        chunk = misses[i : i + _EMBED_BATCH]
        qvecs = await embedder.embed([t[:_EMBED_MAXLEN] for _, t in chunk], query=True)
        for (item, _), qv in zip(chunk, qvecs):
            best_id, best_score = None, 0.0
            for tid, av in anchors.items():
                s = cosine(qv, av)
                if s > best_score:
                    best_id, best_score = tid, s
            if best_id and best_score >= _COHERE_MIN:
                item.theme = best_id  # sous-thème laissé vide (le lexique a raté)
                n += 1
    return n


async def _classify_model(db, model, text_fn, classifier, reset, anchors, embedder) -> dict:
    stmt = select(model)
    if not reset:
        stmt = stmt.where(model.theme.is_(None))
    items = list((await db.execute(stmt)).scalars().all())

    det = 0
    misses: list[tuple] = []
    for it in items:
        r = classifier.classify(text_fn(it))
        if r["theme"]:
            it.theme, it.subtheme = r["theme"], r["subtheme"]
            det += 1
        else:
            misses.append((it, text_fn(it)))

    cohere_n = 0
    if anchors and embedder and misses:
        cohere_n = await _cohere_fallback(misses, anchors, embedder)

    await db.commit()
    return {
        "considered": len(items),
        "deterministic": det,
        "cohere": cohere_n,
        "unclassified": len(items) - det - cohere_n,
    }


async def classify_all(
    kind: str = "all", reset: bool = False, use_cohere: bool | None = None
) -> dict:
    """Classe posts et/ou articles par thème/sous-thème CAP.

    kind: 'x' | 'press' | 'all'. reset: reclasse même les items déjà classés.
    use_cohere: None = auto (si clé Cohere dispo) ; True/False = forcer.
    """
    classifier = get_classifier()
    embedder = get_embedder()
    if use_cohere is None:
        use_cohere = embedder.available()
    anchors = await _build_anchors(embedder) if use_cohere else None
    if use_cohere and not anchors:
        logger.warning("classify.cohere_unavailable")
        embedder = None

    factory = get_session_factory()
    out: dict = {"kind": kind, "reset": reset, "cohere": bool(anchors)}
    async with factory() as db:
        if kind in ("x", "all"):
            out["x"] = await _classify_model(
                db, Post, _post_text, classifier, reset, anchors, embedder
            )
        if kind in ("press", "all"):
            out["press"] = await _classify_model(
                db, Article, _article_text, classifier, reset, anchors, embedder
            )
    logger.info("classify.done", **{k: v for k, v in out.items() if k in ("x", "press")})
    return out
