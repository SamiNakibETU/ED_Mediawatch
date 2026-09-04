"""Personne ne doit écarter à la main ce qu'une machine pouvait écarter.

Relevé en production le 04/09/2026 : 25 rapprochements en attente, zéro tranché.
En les lisant, on comprend pourquoi.

    « La mairie de Chessy condamnée à verser 6000 euros à un Algérien sous
      OQTF » ≠ « Suspensions de séance à répétition, logorrhées insupportables »
    motif : Expulsions promises par an — 210 ≠ 6000 nb_par_an

    « Jordan Bardella a répété la promesse d'un référendum sur l'immigration »
    ≠ « Dominique de Villepin l'a qualifiée d'énième surenchère »

Le premier vient du détecteur déterministe, qui ne lit pas les phrases : il
compare des nombres partageant un référent, et le rattachement était faux — une
amende de 6 000 € comptée comme un nombre d'expulsions par an. Le second est
vrai, mais Villepin n'est pas suivi par un observatoire de l'extrême droite.

Aucun des deux n'aurait dû atteindre un relecteur. La chaîne était à l'envers :
un étage bête et bon marché écrivait directement dans la file humaine, et
l'humain servait de premier filtre à la machine. L'ordre juste — rappel large,
puis vérification par le modèle, puis décision humaine — est celui que décrit la
littérature de la vérification automatique.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.contradiction import Contradiction
from src.services.analysis.contradiction_detector import A_VERIFIER
from src.services.analysis.contradiction_judge import (
    ContradictionVerdict,
    _lire_les_detections,
)

_CACHES = (get_settings, get_engine, get_session_factory)
QUAND = datetime(2026, 6, 25, tzinfo=timezone.utc)


class _LLM:
    """Un juge qui rend le verdict qu'on lui dit, et compte ses lectures."""

    def __init__(self, verdict, explication="parce que"):
        self.reponse = ContradictionVerdict(
            verdict=verdict, explanation=explication, confidence=0.8)
        self.lectures = 0

    async def judge_contradiction(self, prompt):
        self.lectures += 1
        return self.reponse


def _run(tmp_path, monkeypatch, *, statut, pid_b, judge_version, check, llm):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'file.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            ids = []
            for i, pid in enumerate((1, pid_b)):
                c = Claim(platform="press", personality_id=pid,
                          speaker_name=f"Locuteur {i}", verbatim=f"propos {i}",
                          canonical=f"propos {i}", claim_type="factuel_quantitatif",
                          confidence=0.7, dedup_key=f"f{i}", published_at=QUAND)
                db.add(c)
                await db.flush()
                ids.append(c.id)
            db.add(Contradiction(claim_a_id=ids[0], claim_b_id=ids[1], type=6,
                                 score=0.9, status=statut,
                                 rationale="Expulsions par an — 210 ≠ 6000",
                                 judge_version=judge_version))
            await db.commit()
        stats = await _lire_les_detections(llm, factory, {}, max_pairs=10)
        async with factory() as db:
            arete = (await db.execute(select(Contradiction))).scalars().one()
            await check(stats, arete, llm)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_a_nonsense_pairing_is_thrown_out_before_a_human_sees_it(tmp_path, monkeypatch):
    """Le juge lit « 6 000 € d'amende » contre « 210 expulsions », voit que les
    deux propos ne portent pas sur le même objet, et écarte — en nommant la
    cause, pour qu'on sache quoi corriger en amont."""
    llm = _LLM("hors_sujet", "Les deux propos ne portent pas sur le même objet.")

    async def check(stats, arete, llm):
        assert stats["ecartees"] == 1 and stats["promues"] == 0
        assert arete.status == "rejected"
        assert arete.rejection_reason == "objets_differents"
        assert "même objet" in arete.rationale

    _run(tmp_path, monkeypatch, statut=A_VERIFIER, pid_b=2, judge_version=None,
         check=check, llm=llm)


def test_a_real_one_reaches_the_queue_with_a_sentence_not_two_numbers(tmp_path, monkeypatch):
    """Promue, mais son motif chiffré est remplacé par une explication : un
    relecteur ne peut pas trancher sur « 210 ≠ 6000 »."""
    llm = _LLM("contradiction", "Les deux chiffres portent sur la même mesure.")

    async def check(stats, arete, llm):
        assert stats["promues"] == 1
        assert arete.status == "pending"
        assert arete.rationale == "Les deux chiffres portent sur la même mesure."
        assert arete.detection_method == "deterministic_llm"
        assert arete.judge_version

    _run(tmp_path, monkeypatch, statut=A_VERIFIER, pid_b=2, judge_version=None,
         check=check, llm=llm)


def test_a_pairing_that_leaves_the_perimeter_costs_no_model_call(tmp_path, monkeypatch):
    """Bardella contre Villepin : reconnaître que ce n'est pas l'objet de
    l'observatoire ne demande aucun modèle, et le filtre le moins cher passe
    en premier."""
    llm = _LLM("contradiction")

    async def check(stats, arete, llm):
        assert stats["hors_perimetre"] == 1
        assert arete.status == "rejected" and arete.rejection_reason == "hors_perimetre"
        assert llm.lectures == 0, "aucun appel au modèle pour un hors-périmètre"

    _run(tmp_path, monkeypatch, statut=A_VERIFIER, pid_b=None, judge_version=None,
         check=check, llm=llm)


def test_an_unread_pairing_already_queued_is_taken_back(tmp_path, monkeypatch):
    """La réparation de l'existant : les arêtes entrées dans la file humaine
    avant que la règle n'existe n'ont jamais été lues (`judge_version` vide).
    Elles repassent par le juge au lieu de rester à la charge d'un relecteur."""
    llm = _LLM("compatible", "Les deux positions se concilient.")

    async def check(stats, arete, llm):
        assert llm.lectures == 1, "l'arête reprise a bien été lue"
        assert arete.status == "rejected"
        assert arete.rejection_reason == "pas_contradictoire"

    _run(tmp_path, monkeypatch, statut="pending", pid_b=2, judge_version=None,
         check=check, llm=llm)


def test_a_human_decision_is_never_undone(tmp_path, monkeypatch):
    """Un rapprochement déjà jugé par un modèle et laissé à un relecteur garde
    sa place ; et rien de ce qu'un humain a tranché n'est repris — la
    réparation ne touche que ce que personne n'a lu."""
    llm = _LLM("contradiction")

    async def check(stats, arete, llm):
        assert arete.status == "confirmed"
        assert llm.lectures == 0

    _run(tmp_path, monkeypatch, statut="confirmed", pid_b=2, judge_version="judge-v1",
         check=check, llm=llm)
