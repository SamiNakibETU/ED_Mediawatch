"""Un article de presse n'est jamais, en bloc, la parole d'une personne.

Règle absolue de l'observatoire : **sans attribution certaine, on n'attribue
pas**. Un papier qui mentionne une figure contient aussi la voix du journaliste
et de tiers cités. Présumer que la seule figure suivie mentionnée est l'auteur
de tout le contenu fabrique des imputations fausses — et une imputation fausse,
publiée, retourne l'arme contre l'observatoire.

Deux occurrences réelles, sur les DEUX chemins d'extraction :
  * L0 (`declaration_extractor`) — des propos de Marylise Léon et Benjamin
    Haddad prêtés à Marine Le Pen, puis des « revirements » bâtis dessus ;
  * quantitatif (`claim_extractor`) — un chiffre énoncé par Benjamin Haddad
    dans un papier franceinfo crédité à Marine Le Pen.

La correction d'alors — n'attribuer aucun propos de presse — tenait la règle
mais coûtait cher : TOUTE la presse tombait en « non attribué », donc hors de la
comparaison, alors que rattacher un propos à quelqu'un à une date est l'objet
même du produit. La réponse n'est pas de deviner, c'est de faire dire au texte
qui parle, puis de le vérifier. Ces tests verrouillent les deux moitiés :
jamais de déduction, et jamais d'attribution non vérifiée.
"""

import asyncio
import inspect
import re
from datetime import datetime, timezone

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.article import Article
from src.models.claim import Claim
from src.models.media_source import MediaSource
from src.models.personality import Personality
from src.services.analysis import claim_extractor, declaration_extractor
from src.services.analysis.claim_llm import Declaration, DeclarationSet
from src.services.analysis.declaration_extractor import attributed_speaker

SOURCE = (
    "Face aux patrons, Marine Le Pen déroule un programme libéral. "
    "« Il faut baisser les impôts », a déclaré Marine Le Pen devant le MEDEF. "
    "De son côté, Marylise Léon estime que la réforme est injuste. "
    "Jordan Bardella n’a pas réagi."
)
SUIVIS = {"Marine Le Pen": 76, "Éric Ciotti": 12}


# ── La règle : jamais de déduction ───────────────────────────────────────

def test_l0_never_presumes_a_speaker_from_mentions():
    src = inspect.getsource(declaration_extractor.run_declaration_extraction)
    assert not re.search(r"speaker\w*\s*=\s*mp\[0\]", src)
    # L'attribution de presse doit passer par le garde-fou, jamais en direct.
    assert "attributed_speaker(decl.speaker" in src


def test_quantitative_extractor_never_presumes_a_speaker_for_press():
    src = inspect.getsource(claim_extractor)
    press = src[src.index('platform="press"') - 3000 : src.index('platform="press"') + 200] \
        if 'platform="press"' in src else src
    assert not re.search(r"speaker\s*=\s*mp\[0\]", press), (
        "l'extracteur quantitatif présume à nouveau un locuteur depuis les "
        "mentions d'un article — cf. docstring de ce test"
    )


def test_rule_is_documented_where_it_is_enforced():
    """La règle doit rester expliquée dans le code : sans le pourquoi, elle
    sera « simplifiée » par la prochaine personne qui passe."""
    for mod in (declaration_extractor, claim_extractor):
        src = inspect.getsource(mod)
        assert "JAMAIS de locuteur présumé" in src, f"{mod.__name__} a perdu la justification"


# ── Le garde-fou : jamais d'attribution non vérifiée ─────────────────────

def test_named_speaker_present_in_the_text_is_accepted():
    """Le texte dit qui parle : c'est le seul cas où l'on attribue."""
    assert attributed_speaker("Marine Le Pen", SOURCE, SUIVIS) == ("Marine Le Pen", 76)


def test_partial_name_resolves_to_the_followed_figure():
    """« Le Pen » et « Marine Le Pen » doivent être la MÊME voix : sans ce
    rattachement, deux graphies feraient deux locuteurs et il n'y aurait plus
    rien à comparer dans le temps."""
    assert attributed_speaker("Le Pen", SOURCE, SUIVIS) == ("Marine Le Pen", 76)


def test_speaker_outside_the_pool_is_kept_but_unlinked():
    """Une voix qui n'est pas suivie reste une voix. La consigner nommément
    vaut mieux que de la verser au tas « non attribué » : c'est ce qui permet
    de confronter un propos RN à celui d'un syndicaliste."""
    assert attributed_speaker("Marylise Léon", SOURCE, SUIVIS) == ("Marylise Léon", None)


def test_name_absent_from_the_source_is_refused():
    """Le modèle propose, le texte dispose. Un nom qui n'est pas dans le papier
    n'a pas pu y être désigné comme l'auteur du propos."""
    assert attributed_speaker("Éric Ciotti", SOURCE, SUIVIS) == (None, None)
    assert attributed_speaker("Emmanuel Macron", SOURCE, SUIVIS) == (None, None)


def test_a_collective_is_not_a_speaker():
    """« Le gouvernement » n'a pas de position qu'on puisse suivre dans le
    temps : ce n'est pas quelqu'un."""
    for junk in ("le gouvernement", "une source proche", "", None, "   "):
        assert attributed_speaker(junk, SOURCE, SUIVIS) == (None, None)


def test_ambiguous_surname_is_refused():
    """Deux Le Pen dans le même papier : on n'attribue pas. Choisir au hasard
    entre deux figures est exactement le défaut qu'on a corrigé."""
    deux = {"Marine Le Pen": 1, "Jean-Marie Le Pen": 2}
    assert attributed_speaker("Le Pen", SOURCE, deux) == (None, None)


def test_x_posts_keep_their_certain_attribution():
    """Sur X, le compte EST l'auteur : cette attribution-là ne se discute pas,
    et le chemin de presse ne doit pas l'avoir affaiblie."""
    src = inspect.getsource(declaration_extractor.run_declaration_extraction)
    assert "speaker=p.full_name" in src.replace(" ", "").replace("\n", "") \
        or "speaker=p.full_name" in src


# ── Le chemin presse, exécuté ────────────────────────────────────────────
#
# Tout ce qui précède lit le code sans le faire tourner. Ça a suffi à laisser
# passer une panne de trois jours : une ligne supprimée par mégarde faisait
# échouer la boucle presse sur un NameError à la première itération, en
# production, à chaque passe — et tout l'aval (codage, vecteurs, sujets) était
# sauté. Le local ne voyait rien, sa file d'articles étant vide : la ligne ne
# s'exécutait jamais. Un test qui LIT le code ne remplace pas un test qui le
# LANCE.

_CACHES = (get_settings, get_engine, get_session_factory)

ARTICLE_TITRE = "Face aux patrons, Marine Le Pen déroule un programme libéral"
ARTICLE_CORPS = (
    "« Il faut baisser les impôts », a déclaré Marine Le Pen devant le MEDEF. "
    "De son côté, Marylise Léon estime que la réforme est injuste et le dit "
    "sans détour. Jordan Bardella n’a pas réagi."
)


def _decl(verbatim: str, speaker: str | None) -> Declaration:
    """Le vrai schéma, pas un double : `_store` applique de vraies règles
    dessus (verbatim présent dans la source, check_worthy)."""
    return Declaration(
        verbatim=verbatim, canonical=verbatim, claim_type="normatif",
        theme="economie", stance_target="les impôts", check_worthy=True,
        speaker=speaker,
    )


class _PresseLLM:
    """Rend deux voix pour un même papier — le cas normal d'un article."""

    def __init__(self):
        self.known_recu: list[str] | None = None
        self.speaker_recu: str | None = "sentinelle"
        self._s = get_settings()

    def available(self) -> bool:
        return True

    async def segment_declarations(self, *, text, speaker=None, known=None):
        self.known_recu = known
        self.speaker_recu = speaker
        return DeclarationSet(has_declaration=True, declarations=[
            _decl("Il faut baisser les impôts", "Marine Le Pen"),
            _decl("la réforme est injuste", "Marylise Léon"),
            _decl("un programme libéral", "Emmanuel Macron"),   # absent du texte
        ])


def _extraire_un_article(tmp_path, monkeypatch):
    """Un article, deux figures suivies, une passe complète d'extraction."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'presse.db'}")
    monkeypatch.setenv("L0_PILOT_HANDLES", "")
    for c in _CACHES:
        c.cache_clear()

    llm = _PresseLLM()
    claims: list[Claim] = []

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            db.add(MediaSource(id="lemonde", name="Le Monde",
                               rss_url="https://lemonde.fr/rss.xml"))
            db.add(Personality(full_name="Marine Le Pen", handle="mlp_officiel",
                               group_code="RN"))
            db.add(Personality(full_name="Jordan Bardella", handle="j_bardella",
                               group_code="RN"))
            await db.commit()
            db.add(Article(
                media_source_id="lemonde", url="https://lemonde.fr/a/1",
                url_hash="h1", title=ARTICLE_TITRE, content=ARTICLE_CORPS,
                published_at=datetime(2026, 5, 4, tzinfo=timezone.utc),
                matched_personalities=["Marine Le Pen", "Jordan Bardella",
                                       "Figure inconnue au répertoire"],
            ))
            await db.commit()

        monkeypatch.setattr(declaration_extractor, "get_claim_llm", lambda: llm)
        stats = await declaration_extractor.run_declaration_extraction(
            limit_posts=0, limit_articles=10
        )

        async with factory() as db:
            claims.extend((await db.execute(
                select(Claim).order_by(Claim.id))).scalars().all())
        return stats

    try:
        stats = asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()
    return stats, claims, llm


def test_the_press_path_runs_end_to_end(tmp_path, monkeypatch):
    """La boucle presse doit produire des déclarations, pas une exception.

    C'est le test qui manquait : il échoue à la première itération si le
    contexte des figures repérées disparaît de nouveau."""
    stats, claims, llm = _extraire_un_article(tmp_path, monkeypatch)

    assert stats["articles_processed"] == 1
    assert stats["remaining_articles"] == 0, "l'article n'a pas été marqué comme vu"
    assert len(claims) == 3, "les déclarations retenues doivent entrer au Grand Livre"


def test_the_model_gets_the_followed_figures_as_context_only(tmp_path, monkeypatch):
    """Les figures repérées sont un contexte d'orthographe, jamais une réponse :
    `speaker` reste vide pour un article, et le contexte est filtré sur le
    répertoire — un nom qui n'y est pas ne doit pas être proposé."""
    _, _, llm = _extraire_un_article(tmp_path, monkeypatch)

    assert llm.speaker_recu is None, "un locuteur a été présumé pour un article"
    assert llm.known_recu == ["Marine Le Pen", "Jordan Bardella"]


def test_each_press_declaration_is_attributed_on_its_own(tmp_path, monkeypatch):
    """Un papier porte plusieurs voix : chacune est vérifiée séparément.

    Trois sorts distincts pour trois propos du même article — la figure suivie
    rattachée à sa fiche, la voix extérieure nommée sans fiche, et le propos
    dont le locuteur proposé n'est pas dans le texte CONSERVÉ mais non attribué.
    Refuser une attribution n'est pas refuser le propos : le texte a bien été
    écrit, c'est seulement le « qui » qui n'est pas établi."""
    stats, claims, _ = _extraire_un_article(tmp_path, monkeypatch)

    par_nom = {c.speaker_name: c for c in claims}
    assert set(par_nom) == {"Marine Le Pen", "Marylise Léon", None}
    assert par_nom["Marine Le Pen"].personality_id is not None
    assert par_nom["Marylise Léon"].personality_id is None
    assert par_nom[None].personality_id is None
    assert stats["press_attributed"] == 2
    assert all(c.platform == "press" and c.article_id for c in claims)
