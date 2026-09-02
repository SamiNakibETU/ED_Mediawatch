"""Une clé révoquée ne doit pas valoir moins qu'une clé absente.

Vécu le 01/09/2026. La clé Cohere de production a été régénérée ; l'ancienne
est restée dans l'environnement. Le repli local existait pourtant — mais il ne
se déclenchait que sur une clé ABSENTE. Avec une clé présente et refusée,
`available()` répondait oui, chaque appel rendait 401, aucune déclaration n'a
été vectorisée, aucun sujet n'a pu être construit, et la une est restée vide
pendant que la collecte, elle, tournait très bien.

Le cas le plus courant n'était donc pas couvert : un secret ne disparaît pas,
il se périme.
"""

import asyncio

import pytest

from src.services.analysis.embeddings import CohereEmbedder, LocalEmbedder, cosine


class _Refus(Exception):
    """Ce que rend Cohere sur une clé révoquée."""

    status_code = 401


class _Panne(Exception):
    """Ce que rend un service momentanément indisponible."""

    status_code = 503


class _FauxCohere:
    def __init__(self, exc):
        self.exc = exc
        self.appels = 0

    async def embed(self, **kw):
        self.appels += 1
        raise self.exc


class _FauxLocal:
    """Le repli, sans charger 470 Mo de modèle."""

    def available(self):
        return True

    def dim(self):
        return 384

    async def embed(self, texts, *, query=False):
        return [[0.1] * 384 for _ in texts]


def _embedder(exc, monkeypatch):
    monkeypatch.setattr("src.services.analysis.embeddings.LocalEmbedder", _FauxLocal)
    emb = CohereEmbedder.__new__(CohereEmbedder)
    emb._model = "embed-multilingual-v3.0"
    emb._client = _FauxCohere(exc)
    emb._fallback = None
    return emb


def test_a_revoked_key_falls_back_instead_of_stopping(monkeypatch):
    """Le résultat attendu n'est pas une erreur propre : ce sont des vecteurs.

    Une chaîne d'analyse qui s'arrête proprement sur un secret périmé laisse la
    même page vide qu'une chaîne qui plante — la propreté de l'échec n'est pas
    ce qu'on demande au produit.
    """
    emb = _embedder(_Refus("Incorrect API key provided"), monkeypatch)

    vecteurs = asyncio.run(emb.embed(["un propos", "un autre"]))

    assert len(vecteurs) == 2
    assert len(vecteurs[0]) == 384, "les vecteurs viennent désormais du modèle local"
    assert emb.available(), "l'embedder reste utilisable, par un autre chemin"
    assert emb.dim() == 384, "la dimension annoncée suit le backend réellement actif"


def test_the_second_call_does_not_retry_the_dead_key(monkeypatch):
    """Rétrograder une fois, pas à chaque lot : cinq mille déclarations
    feraient cinq mille appels voués au même 401."""
    emb = _embedder(_Refus("Incorrect API key"), monkeypatch)

    asyncio.run(emb.embed(["a"]))
    asyncio.run(emb.embed(["b"]))

    assert emb._client is None
    assert emb._fallback is not None


def test_a_passing_outage_still_raises(monkeypatch):
    """Une panne de service se répare toute seule ; un refus d'identité, non.

    Basculer sur le modèle local au moindre incident réseau ferait entrer dans
    le corpus des vecteurs d'un autre espace pour une raison passagère — et le
    corpus entier devrait être recalculé au retour du service.
    """
    emb = _embedder(_Panne("service unavailable"), monkeypatch)

    try:
        asyncio.run(emb.embed(["a"]))
    except _Panne:
        pass
    else:
        raise AssertionError("une panne passagère ne doit pas être avalée")

    assert emb._client is not None, "le client Cohere reste en place"


def test_two_spaces_do_not_compare():
    """Le vrai danger du repli : `zip` s'arrête au plus court, et le cosinus
    d'un vecteur de 1 024 contre un de 384 rendait un nombre plausible calculé
    sur un tiers des coordonnées. Un rapprochement faux qui ne lève aucune
    erreur est pire qu'une panne."""
    assert cosine([1.0] * 1024, [1.0] * 384) == 0.0
    assert cosine([1.0] * 384, [1.0] * 384) == pytest.approx(1.0)


def test_the_local_backend_declares_its_dimension():
    """L'index vectoriel déclare une colonne d'une dimension fixe : il doit la
    connaître avant d'avoir vu le premier vecteur."""
    assert LocalEmbedder.DIM == 384


# ── La limite de lot du fournisseur ────────────────────────────────────────


class _CohereQuiCompte:
    """Un faux client qui applique la vraie limite de l'API."""

    LIMITE = 96

    def __init__(self):
        self.appels = []

    async def embed(self, *, model, texts, input_type, embedding_types):
        self.appels.append(len(texts))
        if len(texts) > self.LIMITE:
            raise ValueError(
                f"total number of texts must be at most {self.LIMITE} "
                f"- received {len(texts)}")

        class _R:
            class embeddings:  # noqa: N801
                float_ = [[0.5] * 1024 for _ in texts]
        return _R()


def test_a_large_batch_is_split_to_the_provider_limit():
    """Vécu en production le 02/09/2026, à la première passe avec une clé
    valide : le pipeline envoyait 5 000 textes en un appel, Cohere en accepte
    96, et le lot entier était perdu.

    Le défaut existait depuis l'écriture de la classe. Il ne pouvait pas se voir
    tant que le corpus tenait en quelques dizaines de déclarations, puis tant
    que la clé était refusée — l'échec d'authentification masquait l'échec de
    conception.
    """
    emb = CohereEmbedder.__new__(CohereEmbedder)
    emb._model = "embed-multilingual-v3.0"
    emb._client = _CohereQuiCompte()
    emb._fallback = None

    vecteurs = asyncio.run(emb.embed([f"déclaration {i}" for i in range(250)]))

    assert len(vecteurs) == 250, "on récupère autant de vecteurs que de textes"
    assert emb._client.appels == [96, 96, 58]
    assert all(len(v) == 1024 for v in vecteurs)


def test_the_order_of_vectors_follows_the_order_of_texts():
    """Les vecteurs sont réappariés aux déclarations par position : un lot
    remis dans le désordre attribuerait à chaque propos le vecteur d'un autre,
    et le regroupement en sujets deviendrait aléatoire sans qu'une seule erreur
    ne soit levée."""

    class _Indexe(_CohereQuiCompte):
        async def embed(self, *, model, texts, input_type, embedding_types):
            self.appels.append(len(texts))

            class _R:
                class embeddings:  # noqa: N801
                    float_ = [[float(len(t))] for t in texts]
            return _R()

    emb = CohereEmbedder.__new__(CohereEmbedder)
    emb._model = "embed-multilingual-v3.0"
    emb._client = _Indexe()
    emb._fallback = None

    textes = ["a" * n for n in range(1, 200)]
    vecteurs = asyncio.run(emb.embed(textes))

    assert [v[0] for v in vecteurs] == [float(len(t)) for t in textes]
