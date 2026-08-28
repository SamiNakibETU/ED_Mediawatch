"""Regroupement en sujets — l'unité dans laquelle deux propos se confrontent.

Ce que ces tests protègent : comparer des déclarations parce qu'elles partagent
un THÈME (« économie », 15 rayons) ne veut rien dire — mesuré sur corpus réel,
3 751 déclarations, 0 contradiction trouvable. Il faut un SUJET (« la hausse des
impôts »). Avec, le même corpus a livré un revirement chiffré de Marine Le Pen
sur la contribution française à l'UE (six milliards vs sept, à quatre mois).
"""

from sqlalchemy import select

from src.services.analysis.subject_builder import slugify
from src.services.analysis.subject_clustering import (
    ClaimProbe,
    SubjectState,
    absorb,
    assign_or_create,
    entities_of,
    jaccard,
    mergeable_pairs,
)


def _subject(sid, centroid, entities, n=1):
    return SubjectState(subject_id=sid, bucket="economie", centroid=centroid,
                        entities=set(entities), n_claims=n)


def _probe(cid, embedding, entities):
    return ClaimProbe(claim_id=cid, bucket="economie", embedding=embedding,
                      entities=set(entities))


# ── Signature d'entités : ce que la déclaration NOMME ────────────────────

def test_entities_keep_named_things():
    e = entities_of("La contribution de la France à l'Union européenne augmente de six milliards.")
    assert "contribution" in e and "europeenne" in e
    # « France » est trop générique dans ce corpus : présent partout, il ne
    # distingue aucun sujet.
    assert "france" not in e


def test_entities_drop_empty_talk():
    # Un propos qui ne nomme rien ne peut fonder aucun sujet.
    assert len(entities_of("Il faut que nous fassions tous des efforts.")) < 2


def test_slugify_ignores_articles():
    # « l'aide à l'Ukraine » et « aide Ukraine » désignent le même objet.
    assert slugify("l'aide militaire à l'Ukraine") == slugify("Aide militaire à Ukraine")


# ── Rattachement ─────────────────────────────────────────────────────────

def test_vague_claim_joins_nothing():
    """Un propos sans entités ne rejoint ni ne fonde un sujet : il polluerait."""
    d = assign_or_create(_probe(1, [1.0, 0.0, 0.0], {"impots"}),
                         [_subject("s1", [1.0, 0.0, 0.0], {"impots", "hausse"})])
    assert d.subject_id is None and not d.created
    assert d.reason == "trop_vague"


def test_shared_entities_and_close_meaning_join():
    subj = _subject("s1", [1.0, 0.0, 0.0], {"impots", "hausse", "budget"})
    d = assign_or_create(_probe(2, [0.97, 0.24, 0.0], {"impots", "hausse", "fiscalite"}), [subj])
    assert d.subject_id == "s1" and not d.created


def test_same_entities_but_different_meaning_creates_subject():
    """Le gate d'entités ne suffit pas : le sens doit suivre."""
    subj = _subject("s1", [1.0, 0.0, 0.0], {"impots", "hausse", "budget"})
    d = assign_or_create(_probe(3, [0.0, 1.0, 0.0], {"impots", "hausse", "budget"}), [subj])
    assert d.created and d.reason == "cosinus_insuffisant"


def test_no_shared_entities_creates_subject():
    """Deux objets différents du même thème ne se rejoignent pas."""
    subj = _subject("s1", [1.0, 0.0, 0.0], {"impots", "hausse", "budget"})
    d = assign_or_create(_probe(4, [1.0, 0.0, 0.0], {"ukraine", "armes", "livraison"}), [subj])
    assert d.created and d.reason == "gate_entites"


def test_different_bucket_never_joins():
    subj = _subject("s1", [1.0, 0.0, 0.0], {"impots", "hausse"})
    probe = ClaimProbe(claim_id=5, bucket="international",
                       embedding=[1.0, 0.0, 0.0], entities={"impots", "hausse"})
    assert assign_or_create(probe, [subj]).created


# ── Évolution du sujet ───────────────────────────────────────────────────

def test_absorbing_moves_centroid_and_unions_entities():
    subj = _subject("s1", [1.0, 0.0, 0.0], {"impots"}, n=1)
    absorb(subj, _probe(6, [0.0, 1.0, 0.0], {"fiscalite"}))
    assert subj.n_claims == 2
    assert subj.centroid == [0.5, 0.5, 0.0]      # moyenne courante
    assert subj.entities == {"impots", "fiscalite"}
    assert subj.claim_ids == [6]


def test_converged_subjects_are_flagged_for_merge():
    """Le clustering dépend de l'ordre d'arrivée : deux sujets peuvent converger.
    Sans fusion, les propos qui devraient se confronter restent séparés."""
    a = _subject("a", [1.0, 0.0, 0.0], {"impots"})
    b = _subject("b", [0.99, 0.02, 0.0], {"fiscalite"})
    far = _subject("c", [0.0, 1.0, 0.0], {"ukraine"})
    pairs = mergeable_pairs([a, b, far])
    assert [(x, y) for x, y, _ in pairs] == [("a", "b")]


def test_jaccard_symmetry_and_bounds():
    assert jaccard(set(), {"a"}) == 0.0
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a", "b"}, {"b", "c"}) == jaccard({"b", "c"}, {"a", "b"})


# ── Idempotence du nommage ───────────────────────────────────────────────

def test_named_subjects_keep_their_label_on_rebuild(tmp_path, monkeypatch):
    """Reconstruire ne doit pas détruire le nommage.

    Vécu : `build_subjects` réécrivait `label` depuis les entités à chaque
    passe, effaçant le nom donné par le LLM (« la hausse des impôts » redevenait
    « augmenter expression fiscale impots »). Le travail de nommage — payant —
    était perdu à la passe suivante.
    """
    import asyncio

    from src.config import get_settings
    from src.database import get_engine, get_session_factory, init_db
    from src.models.claim import Claim
    from src.models.subject import Subject
    from src.services.analysis.subject_builder import build_subjects

    caches = (get_settings, get_engine, get_session_factory)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'lab.db'}")
    for c in caches:
        c.cache_clear()

    async def run():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            for i in range(3):
                db.add(Claim(
                    platform="x", verbatim=f"La contribution européenne augmente de {i} milliards.",
                    canonical=f"La contribution européenne augmente de {i} milliards.",
                    claim_type="factuel_quantitatif", theme="economie",
                    embedding=[1.0, 0.05 * i, 0.0], speaker_name=f"Locuteur {i}",
                    dedup_key=f"k{i}",
                ))
            await db.commit()

        await build_subjects(min_claims=2)
        async with factory() as db:
            subj = (await db.execute(select(Subject))).scalars().first()
            assert subj is not None
            subj.label = "la contribution française à l'UE"
            subj.status = "labelled"          # nommé par le LLM
            await db.commit()
            sid = subj.id

        await build_subjects(min_claims=2)    # deuxième passe
        async with factory() as db:
            again = await db.get(Subject, sid)
            assert again.label == "la contribution française à l'UE"
            assert again.status == "labelled"

    try:
        asyncio.run(run())
    finally:
        for c in caches:
            c.cache_clear()
