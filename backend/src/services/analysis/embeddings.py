"""Embeddings Cohere — blocking sémantique des référents.

À l'échelle actuelle (~dizaines de référents) un cosinus en mémoire suffit : pas
besoin de pgvector. Au déploiement, la colonne `Referent.embedding` (JSON)
devient `VECTOR(1024)` + index pgvector, sans changer cette logique.

Deux usages :
  * `nearest_referent(phrase)` — rattacher une prise de parole au bon référent
    même quand les mots-clés du lexique ratent (rappel).
  * `fusion_candidates()` — repérer des référents redondants (même objet formulé
    autrement) pour curer la grille (qualité du blocking, cf specs §4.1).
"""

from __future__ import annotations

import math

import structlog
from sqlalchemy import select

from src.config import get_settings
from src.database import get_session_factory
from src.models.referentiel import Referent

logger = structlog.get_logger(__name__)

try:
    import cohere
except Exception:  # noqa: BLE001
    cohere = None


def cosine(a: list[float], b: list[float]) -> float:
    """Cosinus entre deux vecteurs du MEME espace.

    `zip` s'arrete au plus court : comparer un vecteur de 1 024 dimensions a un
    de 384 aurait rendu un nombre plausible, calcule sur le tiers des
    coordonnees de l'un et la totalite de l'autre. Un corpus embarque par deux
    backends produirait alors des rapprochements faux sans qu'aucune erreur
    n'apparaisse — le pire des deux mondes. On rend zero, et le recalcul des
    embeddings remet le corpus dans un seul espace.
    """
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# Dimension par modele. Elle ne se devine pas et ne se mesure pas sans appel
# facture : l'index vectoriel doit la connaitre AVANT le premier vecteur.
_COHERE_DIMS = {"embed-multilingual-v3.0": 1024, "embed-multilingual-light-v3.0": 384}

# Cohere refuse au-dela de 96 textes par appel. Ce n'est pas un reglage de
# performance mais une limite de l'API : la depasser rend 400, et le lot entier
# est perdu. Vecu en production le 02/09/2026, des la premiere passe avec une
# cle valide — « total number of texts must be at most 96 - received 5000 ».
# Le defaut existait depuis l'ecriture de cette classe ; il ne pouvait pas se
# voir tant que le corpus tenait en quelques dizaines de declarations, puis tant
# que la cle etait refusee.
_COHERE_LOT = 96


class CohereEmbedder:
    """Cohere, avec repli local quand la cle est refusee.

    Une cle ABSENTE etait deja prevue (`get_embedder`) ; une cle REVOQUEE ne
    l'etait pas, et c'est le cas le plus courant — un secret tourne, un essai
    expire. Elle passait tous les controles de disponibilite puis echouait en
    401 a chaque appel : pas de vecteur, donc pas de sujet, donc une une vide,
    pendant que la chaine se declarait par ailleurs en bonne sante.

    Le repli n'est pas gratuit : les vecteurs locaux ont 384 dimensions contre
    1024, et deux espaces differents ne se comparent pas. C'est pourquoi
    `dim()` suit le backend REELLEMENT actif, et pourquoi l'embedding des
    declarations est recalcule quand la dimension change.
    """

    def __init__(self) -> None:
        s = get_settings()
        self._model = s.cohere_embed_model
        self._client = (
            cohere.AsyncClientV2(api_key=s.cohere_api_key)
            if (cohere and s.cohere_api_key)
            else None
        )
        self._fallback: LocalEmbedder | None = None

    def available(self) -> bool:
        return self._client is not None or bool(
            self._fallback and self._fallback.available())

    def dim(self) -> int:
        if self._client is None and self._fallback is not None:
            return self._fallback.dim()
        return _COHERE_DIMS.get(self._model, 1024)

    def _demote(self, exc: Exception) -> None:
        """Cohere nous refuse : on continue en local plutot que de s'arreter."""
        logger.warning("embeddings.cohere_rejected", error=str(exc)[:160])
        self._client = None
        self._fallback = LocalEmbedder()

    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        if not texts:
            return []
        if self._client is not None:
            try:
                out: list[list[float]] = []
                for i in range(0, len(texts), _COHERE_LOT):
                    resp = await self._client.embed(
                        model=self._model,
                        texts=texts[i : i + _COHERE_LOT],
                        input_type="search_query" if query else "search_document",
                        embedding_types=["float"],
                    )
                    out.extend(resp.embeddings.float_)
                return out
            except Exception as exc:  # noqa: BLE001
                # Un quota atteint ou une panne passagere doivent remonter : on
                # ne bascule que sur un refus d'identite, qui ne se repare pas
                # tout seul.
                if getattr(exc, "status_code", None) not in (401, 403):
                    raise
                self._demote(exc)
        if self._fallback is not None:
            return await self._fallback.embed(texts, query=query)
        return []


class LocalEmbedder:
    """Repli LOCAL (sentence-transformers) quand Cohere n'a pas de clé.

    Sans lui, l'absence d'une clé tierce suffit à bloquer TOUTE la chaîne
    d'analyse : pas d'embedding -> pas de rattachement au référent -> aucune
    contradiction détectable. Faire dépendre le coeur du produit d'un secret
    optionnel est une fragilité, pas un choix.

    Modèle multilingue (français inclus), CPU, gratuit, ~470 Mo au premier
    chargement puis mis en cache. Dimension 384 (vs 1024 Cohere) : les vecteurs
    ne sont PAS comparables entre backends — d'où `backend_tag`, qui permet de
    détecter un corpus mélangé plutôt que de comparer des choux et des carottes.
    """

    MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    BATCH = 128
    DIM = 384

    def __init__(self) -> None:
        self._model = None
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            self._cls = SentenceTransformer
        except Exception:  # noqa: BLE001
            self._cls = None

    def available(self) -> bool:
        return self._cls is not None

    def dim(self) -> int:
        return self.DIM

    def _ensure(self):
        if self._model is None and self._cls is not None:
            logger.info("embeddings.local_load", model=self.MODEL_NAME)
            self._model = self._cls(self.MODEL_NAME)
        return self._model

    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        model = self._ensure()
        if model is None or not texts:
            return []
        # `encode` est synchrone et gourmand : on le sort de la boucle d'events.
        import asyncio  # noqa: PLC0415

        # Encodage PAR LOTS : un seul appel sur 3 000+ textes fait mourir le
        # process en silence (mémoire). Mesuré : 200 passent, 3 187 tuent le run
        # avec un code de sortie 0 trompeur.
        out: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH):
            chunk = texts[i : i + self.BATCH]
            vectors = await asyncio.to_thread(
                model.encode, chunk, normalize_embeddings=True, show_progress_bar=False
            )
            out.extend(list(map(float, v)) for v in vectors)
        return out


_embedder = None


def get_embedder():
    """Cohere si une clé existe, sinon repli local. Jamais rien de bloquant."""
    global _embedder
    if _embedder is None:
        cohere_emb = CohereEmbedder()
        if cohere_emb.available():
            _embedder = cohere_emb
        else:
            local = LocalEmbedder()
            if local.available():
                logger.info("embeddings.fallback_local")
            _embedder = local
    return _embedder


def backend_tag() -> str:
    """Identifiant du backend actif — les vecteurs de backends différents ne se
    comparent pas (dimensions et espaces distincts)."""
    emb = get_embedder()
    actif_cohere = isinstance(emb, CohereEmbedder) and emb._client is not None
    return "cohere" if actif_cohere else "local-minilm"


async def embed_referents() -> dict:
    """Calcule + cache l'embedding du label de chaque référent (idempotent)."""
    embedder = get_embedder()
    if not embedder.available():
        return {"embedded": 0, "skipped": "cohere indisponible"}

    factory = get_session_factory()
    async with factory() as db:
        refs = list((await db.execute(select(Referent))).scalars().all())
        todo = [r for r in refs if not r.embedding]
        if not todo:
            return {"embedded": 0, "total": len(refs), "note": "déjà à jour"}
        vectors = await embedder.embed([r.label for r in todo])
        for r, v in zip(todo, vectors):
            r.embedding = v
        await db.commit()
    return {"embedded": len(todo), "total": len(refs)}


async def nearest_referent(sentence: str, top: int = 3) -> list[dict]:
    embedder = get_embedder()
    if not embedder.available():
        return []
    qvec = (await embedder.embed([sentence], query=True))
    if not qvec:
        return []
    q = qvec[0]
    factory = get_session_factory()
    async with factory() as db:
        refs = list(
            (await db.execute(select(Referent).where(Referent.embedding.isnot(None)))).scalars().all()
        )
    scored = sorted(
        ({"key": r.key, "label": r.label, "score": round(cosine(q, r.embedding), 4)} for r in refs),
        key=lambda d: d["score"], reverse=True,
    )
    return scored[:top]


async def fusion_candidates(threshold: float = 0.86) -> list[dict]:
    """Paires de référents sémantiquement proches (candidats à fusion/revue)."""
    factory = get_session_factory()
    async with factory() as db:
        refs = list(
            (await db.execute(select(Referent).where(Referent.embedding.isnot(None)))).scalars().all()
        )
    out: list[dict] = []
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            s = cosine(refs[i].embedding, refs[j].embedding)
            if s >= threshold:
                out.append({
                    "a": refs[i].key, "a_label": refs[i].label,
                    "b": refs[j].key, "b_label": refs[j].label,
                    "score": round(s, 4),
                })
    return sorted(out, key=lambda d: d["score"], reverse=True)
