"""Le système doit avancer seul — et cette autonomie a des conditions.

Trois défauts ont fait stagner la production à 15 déclarations pour 31 000
publications collectées. Aucun n'était visible dans un log : le pipeline
« tournait », les compteurs ne bougeaient pas.

1. La passe automatique n'exécutait que les étapes gratuites. Collecter sans
   jamais extraire ne produit qu'un tas de posts.
2. Le `LIMIT` de l'extraction s'appliquait AVANT la déduplication : chaque passe
   redescendait les mêmes posts récents, les jetait tous comme déjà traités, et
   n'atteignait jamais l'historique.
3. Deux jobs de collecte doublaient les étapes du pipeline, épuisant le quota X
   avant que quoi que ce soit d'autre puisse tourner.

Ces tests verrouillent les trois.
"""

import asyncio
import inspect

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.personality import Personality
from src.models.post import Post
from src.services import scheduler as sched
from src.services.analysis import declaration_extractor as extractor
from src.services.analysis.claim_llm import Declaration, DeclarationSet

_CACHES = (get_settings, get_engine, get_session_factory)


# ── Le périmètre de la passe automatique ─────────────────────────────────

def _scope(monkeypatch, **env) -> str:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    try:
        return sched.auto_scope()
    finally:
        get_settings.cache_clear()


def test_automatic_pass_includes_paid_stages(monkeypatch):
    """Sans extraction, la collecte ne produit qu'un tas de posts."""
    assert _scope(monkeypatch, LLM_DAILY_BUDGET_USD="5") == "full"


def test_automatic_pass_falls_back_to_free_without_a_cap(monkeypatch):
    """L'autonomie repose sur le plafond, pas sur la prudence de l'opérateur.
    Sans plafond armé, une boucle automatique pourrait dépenser sans borne."""
    assert _scope(monkeypatch, LLM_DAILY_BUDGET_USD="0",
                  LLM_MONTHLY_BUDGET_USD="0") == "free"


def test_operator_can_still_ask_for_free_only(monkeypatch):
    assert _scope(monkeypatch, PIPELINE_AUTO_SCOPE="free",
                  LLM_DAILY_BUDGET_USD="5") == "free"


# ── Un seul moteur ───────────────────────────────────────────────────────

def test_scheduler_does_not_duplicate_pipeline_stages():
    """Le graphe est l'autorité sur l'ordre. Un job parallèle qui refait une de
    ses étapes double la consommation — ici, deux collectes X par cycle sur le
    même quota, d'où des attentes de quota à répétition."""
    src = inspect.getsource(sched.create_scheduler)
    for forbidden in ("run_collection", "run_press_collection"):
        assert forbidden not in src, (
            f"{forbidden} est de nouveau planifié à part : le pipeline le fait déjà"
        )


# ── La progression de l'extraction ───────────────────────────────────────

def _decl(verbatim: str) -> Declaration:
    """Le vrai schéma, pas un double : `_store` applique de vraies règles
    dessus (verbatim présent dans la source, check_worthy) et un faux objet
    ferait passer le test là où la production échouerait."""
    return Declaration(
        verbatim=verbatim, canonical=verbatim, claim_type="normatif",
        theme="economie", stance_target="les impôts", check_worthy=True,
    )


class _FakeLLM:
    """Compte ce qu'on lui soumet : c'est la seule façon de voir la stagnation."""

    def __init__(self):
        self.seen: list[str] = []
        self._s = get_settings()

    def available(self) -> bool:
        return True

    async def segment_declarations(self, *, text, speaker=None):
        self.seen.append(text)
        return DeclarationSet(has_declaration=True, declarations=[_decl(text[:40])])


def _extract(tmp_path, monkeypatch, n_posts, runs, limit_posts):
    """Peuple un corpus, lance l'extraction `runs` fois, rend les lots vus."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'l0.db'}")
    monkeypatch.setenv("L0_PILOT_HANDLES", "")
    for c in _CACHES:
        c.cache_clear()

    batches: list[list[str]] = []

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            p = Personality(full_name="Marine Le Pen", handle="mlp_officiel",
                            group_code="RN")
            db.add(p)
            await db.commit()
            await db.refresh(db_p := p)
            for i in range(n_posts):
                db.add(Post(
                    personality_id=db_p.id, guid=f"g{i}", url=f"https://x.com/s/{i}",
                    content=(f"Déclaration numéro {i} : il faut baisser les impôts "
                             "sur les classes populaires immédiatement."),
                ))
            await db.commit()

        for _ in range(runs):
            llm = _FakeLLM()
            monkeypatch.setattr(extractor, "get_claim_llm", lambda llm=llm: llm)
            await extractor.run_declaration_extraction(
                limit_posts=limit_posts, limit_articles=0
            )
            batches.append(llm.seen)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()
    return batches


def test_extraction_advances_through_the_backlog(tmp_path, monkeypatch):
    """Le bug : le LIMIT s'appliquait avant la déduplication. Les mêmes posts
    récents redescendaient à chaque passe, tous écartés comme déjà traités —
    et l'archive n'était jamais atteinte. Chaque passe doit avancer."""
    first, second, third = _extract(tmp_path, monkeypatch,
                                    n_posts=9, runs=3, limit_posts=3)
    assert len(first) == len(second) == len(third) == 3
    assert not (set(first) & set(second)), "la deuxième passe repasse sur le même lot"
    assert not (set(first) & set(third))
    assert not (set(second) & set(third))


def test_exhausted_corpus_stops_costing(tmp_path, monkeypatch):
    """Une fois tout traité, une passe de plus ne doit rien renvoyer au LLM."""
    batches = _extract(tmp_path, monkeypatch, n_posts=3, runs=2, limit_posts=10)
    assert len(batches[0]) == 3
    assert batches[1] == [], "on repaie une segmentation déjà faite"


def test_barren_post_is_not_resubmitted(tmp_path, monkeypatch):
    """Un post qui ne produit aucune déclaration ne laisse pas de trace dans
    `claims` : sans marque sur la SOURCE, il repartait au LLM à chaque passe —
    on payait indéfiniment le même silence."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'barren.db'}")
    monkeypatch.setenv("L0_PILOT_HANDLES", "")
    for c in _CACHES:
        c.cache_clear()

    seen: list[list[str]] = []

    class _Silent(_FakeLLM):
        async def segment_declarations(self, *, text, speaker=None):
            self.seen.append(text)
            return DeclarationSet(has_declaration=False)   # rien à en tirer

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            p = Personality(full_name="Jordan Bardella", handle="j_bardella",
                            group_code="RN")
            db.add(p)
            await db.commit()
            await db.refresh(p)
            db.add(Post(personality_id=p.id, guid="g0", url="https://x.com/s/0",
                        content="Un texte qui contient assez de mots pour passer "
                                "le pré-filtre déterministe sans rien affirmer."))
            await db.commit()

        for _ in range(2):
            llm = _Silent()
            monkeypatch.setattr(extractor, "get_claim_llm", lambda llm=llm: llm)
            await extractor.run_declaration_extraction(limit_posts=10, limit_articles=0)
            seen.append(llm.seen)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()

    assert len(seen[0]) == 1
    assert seen[1] == [], "le post stérile est renvoyé au LLM : on paie deux fois"


def test_remaining_is_reported(tmp_path, monkeypatch):
    """Sans « ce qui reste », on relance à l'aveugle jusqu'à ce que le compteur
    cesse de bouger — et on ne sait jamais si c'est fini ou cassé."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'rest.db'}")
    monkeypatch.setenv("L0_PILOT_HANDLES", "")
    for c in _CACHES:
        c.cache_clear()

    out = {}

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            p = Personality(full_name="Marine Le Pen", handle="mlp_officiel",
                            group_code="RN")
            db.add(p)
            await db.commit()
            await db.refresh(p)
            for i in range(5):
                db.add(Post(personality_id=p.id, guid=f"g{i}",
                            url=f"https://x.com/s/{i}",
                            content=f"Position {i} : il faut baisser les impôts "
                                    "des classes populaires sans attendre."))
            await db.commit()
        llm = _FakeLLM()
        monkeypatch.setattr(extractor, "get_claim_llm", lambda: llm)
        out.update(await extractor.run_declaration_extraction(
            limit_posts=2, limit_articles=0))

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()

    assert out["posts_processed"] == 2
    assert out["remaining_posts"] == 3
