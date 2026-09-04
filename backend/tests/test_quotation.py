"""Un article de presse n'est jamais, en soi, la parole d'une personne.

Relevé en production le 04/09/2026 : les six déclarations en tête de la une
venaient toutes de la presse et s'affichaient toutes entre guillemets sous le
nom du locuteur. Quatre étaient des phrases de journaliste — « Marine Le Pen
assure avoir elle-même souhaité ce départ », à la troisième personne, ou
« répétée ce samedi par Jordan Bardella depuis la Foire de Châlons », qui n'est
même pas une phrase.

Le garde-fou d'extraction vérifiait que le verbatim était bien dans l'article :
fidélité au DOCUMENT. La page la lisait comme la fidélité au LOCUTEUR. Ces
tests gèlent la séparation des deux.
"""

from src.routers.declarations import _empreinte
from src.services.analysis.quotation import DIRECT, RAPPORTE, style_de_citation

ARTICLE = (
    "Interrogé samedi à la Foire de Châlons, le député RN a été catégorique. "
    "« Nous sanctionnerons le port du voile dans l'espace public », a déclaré "
    "Jean-Philippe Tanguy. Marine Le Pen assure avoir elle-même souhaité ce "
    "départ. La promesse d'un référendum sur l'immigration, répétée ce samedi "
    "par Jordan Bardella, figure au programme."
)


def test_words_inside_the_quotation_marks_are_the_speakers():
    assert style_de_citation(
        "Nous sanctionnerons le port du voile dans l'espace public", ARTICLE) == DIRECT


def test_a_journalists_sentence_about_someone_is_not_a_quotation():
    """Le cas qui a été publié : une phrase à la troisième personne, exacte dans
    le document, et fausse dès qu'on l'entoure de guillemets sous un nom."""
    assert style_de_citation(
        "Marine Le Pen assure avoir elle-même souhaité ce départ.", ARTICLE) == RAPPORTE


def test_a_fragment_of_narration_is_not_a_quotation():
    assert style_de_citation(
        "répétée ce samedi par Jordan Bardella", ARTICLE) == RAPPORTE


def test_a_quotation_swallowed_with_its_attribution_tail_is_reported():
    """« … » a déclaré X : pris ensemble, ce n'est plus ce que X a dit, c'est ce
    que le journal écrit. Un guillemet ouvrant en tête ne suffit pas."""
    assert style_de_citation(
        "« Nous sanctionnerons le port du voile dans l'espace public », a déclaré "
        "Jean-Philippe Tanguy", ARTICLE) == RAPPORTE


def test_the_quotation_survives_normalisation():
    """Accents, apostrophes courbes et espaces insécables varient entre le
    rendu du modèle et le document ; la localisation ne doit pas s'y casser."""
    assert style_de_citation(
        "Nous sanctionnerons le port du voile dans l’espace public", ARTICLE) == DIRECT


def test_a_verbatim_absent_from_the_document_is_never_promoted():
    """Introuvable : on ne sait pas, donc on ne prétend pas citer. L'inconnu
    n'est pas du style direct — même règle que partout ailleurs."""
    assert style_de_citation("une phrase qui n'y est pas du tout", ARTICLE) == RAPPORTE
    assert style_de_citation("", ARTICLE) == RAPPORTE
    assert style_de_citation("Nous sanctionnerons", "") == RAPPORTE


def test_an_opening_quote_alone_does_not_make_a_quotation():
    """Une citation qui commence ne couvre pas forcément le passage retenu."""
    source = "« Je le dis clairement, dit-il, et le journal ajoute autre chose."
    assert style_de_citation("et le journal ajoute autre chose", source) == RAPPORTE


# ── Ce que la une en fait ──────────────────────────────────────────────────

def test_the_same_sentence_carried_by_two_outlets_appears_once():
    """Deux journaux qui citent la même phrase produisent deux déclarations,
    dans deux articles : le dédoublonnage par source les laissait toutes les
    deux en tête de la une. Qu'une phrase soit reprise ailleurs pèse déjà dans
    le score par la reprise presse ; ce n'est pas une raison de l'afficher deux
    fois."""
    a = "Je soumettrai aux Français par référendum une grande loi de lutte"
    b = '"Je soumettrai aux Français, par référendum, une grande loi de lutte"'
    assert _empreinte(a) == _empreinte(b)


def test_two_different_statements_keep_their_own_place():
    assert _empreinte("Nous sanctionnerons le port du voile") != _empreinte(
        "Nous supprimerons l'aide médicale d'État")


# ── La contradiction doit être MONTRÉE, pas annoncée ───────────────────────
# La une écrivait « contredit un autre propos » sans jamais montrer lequel :
# l'affirmation la plus lourde du produit, invérifiable d'un clic. Or c'est la
# promesse même — qui a dit quoi, quand, et où ça diverge.

import asyncio
from datetime import datetime, timezone

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.contradiction import Contradiction
from src.routers.declarations import _en_regard

_CACHES = (get_settings, get_engine, get_session_factory)


def _pose(tmp_path, monkeypatch, statut, check):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'reg.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            ids = []
            for i, (texte, jour) in enumerate((
                ("six milliards d'euros", 16), ("sept milliards d'euros", 13))):
                c = Claim(platform="press", personality_id=1,
                          speaker_name="Marine Le Pen", verbatim=texte,
                          canonical=texte, claim_type="factuel_quantitatif",
                          quote_style="direct", confidence=0.7, dedup_key=f"g{i}",
                          published_at=datetime(2025, 7, jour, tzinfo=timezone.utc))
                db.add(c)
                await db.flush()
                ids.append(c.id)
            db.add(Contradiction(claim_a_id=ids[0], claim_b_id=ids[1], type=1,
                                 score=0.9, status=statut,
                                 rationale="deux montants pour la même hausse"))
            await db.commit()
        async with factory() as db:
            await check(db, ids)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_each_side_of_a_contradiction_carries_the_other(tmp_path, monkeypatch):
    """Les deux propos se répondent : depuis l'un comme depuis l'autre, la page
    peut poser le second à côté du premier."""
    async def check(db, ids):
        vus = await _en_regard(db, ids)
        assert set(vus) == set(ids)
        assert vus[ids[0]]["text"] == "sept milliards d'euros"
        assert vus[ids[1]]["text"] == "six milliards d'euros"
        assert vus[ids[0]]["type"] == "revirement intra-locuteur"
        assert vus[ids[0]]["rationale"] == "deux montants pour la même hausse"

    _pose(tmp_path, monkeypatch, "pending", check)


def test_a_rejected_pairing_is_never_shown(tmp_path, monkeypatch):
    """Un relecteur a écarté le rapprochement : la page ne le ressort pas par
    la petite porte. C'est l'humain qui tranche, et sa décision tient."""
    async def check(db, ids):
        assert await _en_regard(db, ids) == {}

    _pose(tmp_path, monkeypatch, "rejected", check)


def test_the_status_travels_with_the_pairing(tmp_path, monkeypatch):
    """« À relire » n'est pas « établi ». La page doit pouvoir le dire avant que
    le lecteur ne conclue au mensonge."""
    async def check(db, ids):
        assert (await _en_regard(db, ids))[ids[0]]["status"] == "confirmed"

    _pose(tmp_path, monkeypatch, "confirmed", check)
