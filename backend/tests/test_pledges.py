"""Exiger n'est pas s'engager, et une intention n'est pas un engagement.

Deux confusions ruinent un registre d'engagements, et ce sont exactement celles
qu'un modèle fait quand on lui pose une seule question.

La première : prendre une injonction pour un engagement. « Le gouvernement doit
démissionner » ne promet rien — personne ne pourra dire que le locuteur a tenu
ou non parole. Un registre qui les mélange compte comme promesses les exigences
adressées aux autres, c'est-à-dire l'essentiel de ce que dit une opposition.

La seconde : retenir l'invérifiable. C'est la règle qui fonde le Polimètre de
l'Université Laval — ne sont suivis que les engagements dont une observation
peut dire s'ils ont été tenus. « Nous serons plus fermes » n'en est pas un.

Et par-dessus, la règle de la maison : l'engagement se cite dans les mots du
locuteur, vérifiés contre le texte d'origine.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.pipeline.stages import BY_NAME, PAID
from src.services.analysis.pledges import (
    EN_ATTENTE,
    VERDICTS,
    EngagementLu,
    detect_pledges,
)

_CACHES = (get_settings, get_engine, get_session_factory)

VERBATIM = "Avec @MLP_officiel, nous bâtirons une filière souveraine d'IA"


class _LLM:
    """Répond ce qu'on lui dit, et compte ce qu'on lui a demandé."""

    def __init__(self, lu):
        self.lu = lu
        self.vus = []

        class _S:
            claim_tier2_model = "modele-de-test"
        self._s = _S()

    def available(self):
        return True

    async def read_pledge(self, *, verbatim, canonical=None):
        self.vus.append(verbatim)
        return self.lu(verbatim) if callable(self.lu) else self.lu


def _run(tmp_path, monkeypatch, lu, check, *, claims=None):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'eng.db'}")
    for c in _CACHES:
        c.cache_clear()
    llm = _LLM(lu)
    monkeypatch.setattr("src.services.analysis.pledges.get_claim_llm", lambda: llm)

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            for i, (texte, typ) in enumerate(claims or [(VERBATIM, "predictif")]):
                db.add(Claim(platform="x", speaker_name="Alexandre Loubet", party="RN",
                             verbatim=texte, claim_type=typ,
                             published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                             confidence=0.7, dedup_key=f"e{i}"))
            await db.commit()
        await check(factory, llm)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_a_verifiable_commitment_enters_the_register(tmp_path, monkeypatch):
    """Le cas utile : un engagement du locuteur, avec ce qu'on observerait."""
    lu = EngagementLu(verbatim=VERBATIM,
                      mesure="Une filière française d'IA existe et fonctionne.",
                      verifiable=True)

    async def check(factory, llm):
        stats = await detect_pledges()
        assert stats["engagements"] == 1
        async with factory() as db:
            c = (await db.execute(select(Claim))).scalars().one()
        assert c.pledge_status == EN_ATTENTE, "la machine consigne, elle ne juge pas"
        assert c.pledge_measure.startswith("Une filière")

    _run(tmp_path, monkeypatch, lu, check)


def test_an_unverifiable_intention_is_left_out(tmp_path, monkeypatch):
    """« Nous serons plus fermes » : aucune observation ne tranche. Un registre
    long et invérifiable vaut moins qu'un registre court et sûr — c'est la règle
    qui fonde la méthode."""
    lu = EngagementLu(verbatim=VERBATIM, mesure="", verifiable=False)

    async def check(factory, llm):
        stats = await detect_pledges()
        assert stats["engagements"] == 0 and stats["non_verifiables"] == 1
        async with factory() as db:
            c = (await db.execute(select(Claim))).scalars().one()
        assert c.pledge_status is None
        # Mais la déclaration est marquée comme EXAMINÉE : sans ça, chaque passe
        # la resoumettrait, indéfiniment, au prix de deux appels.
        assert c.pledge_version

    _run(tmp_path, monkeypatch, lu, check)


def test_a_fragment_absent_from_the_source_is_refused(tmp_path, monkeypatch):
    """Un engagement reformulé est un engagement qu'on prête. La règle vaut ici
    comme à l'extraction : le modèle propose, le texte dispose."""
    lu = EngagementLu(verbatim="Nous supprimerons l'impôt sur la fortune",
                      mesure="L'ISF est supprimé par une loi.", verifiable=True)

    async def check(factory, llm):
        stats = await detect_pledges()
        assert stats["engagements"] == 0 and stats["hors_source"] == 1

    _run(tmp_path, monkeypatch, lu, check)


def test_a_statement_of_fact_is_never_submitted(tmp_path, monkeypatch):
    """Un constat n'engage personne. Le pré-filtre est gratuit et retire les
    trois quarts du corpus avant le premier appel — ce qui rend l'étape tenable
    à l'échelle du fonds."""
    claims = [("Le chômage a augmenté de 3 %.", "factuel_quantitatif"),
              ("La France va mal.", "factuel_qualitatif"),
              (VERBATIM, "predictif")]
    lu = EngagementLu(verbatim=VERBATIM, mesure="Une filière existe.", verifiable=True)

    async def check(factory, llm):
        await detect_pledges()
        assert llm.vus == [VERBATIM], "seuls les propos qui peuvent engager sont soumis"

    _run(tmp_path, monkeypatch, lu, check, claims=claims)


def test_a_second_pass_re_examines_nothing(tmp_path, monkeypatch):
    """L'étape tourne à chaque passe : sans marque d'examen, elle repaierait
    l'analyse du corpus entier toutes les quatre heures."""
    lu = EngagementLu(verbatim=VERBATIM, mesure="Une filière existe.", verifiable=True)

    async def check(factory, llm):
        await detect_pledges()
        await detect_pledges()
        assert len(llm.vus) == 1

    _run(tmp_path, monkeypatch, lu, check)


def test_no_verdict_is_ever_posted_by_the_machine():
    """Les cinq verdicts du Polimètre existent en base ; « en attente » est le
    seul que la machine pose. Passer à « réalisée » ou « rompue » demande une
    observation du monde et une source — c'est une décision humaine."""
    assert VERDICTS[0] == EN_ATTENTE
    assert set(VERDICTS) == {"en attente", "en cours", "partiellement réalisée",
                             "réalisée", "rompue"}


def test_the_step_is_paid_and_bounded():
    assert BY_NAME["pledges"].cost == PAID
    assert "extract_l0" in BY_NAME["pledges"].depends_on
