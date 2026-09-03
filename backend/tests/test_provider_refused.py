"""Un fournisseur fermé n'arrête que ce qui a besoin de lui.

Le refus de crédits fait échouer l'extraction, qui est payante. Traité comme un
échec ordinaire, il emportait toute la chaîne d'aval — y compris la
vectorisation, le regroupement et la détection, qui ne demandent aucun modèle et
travaillent sur ce qui est déjà en base. Une passe entière perdue pour une
facture impayée chez un tiers.

C'est la même distinction que pour le plafond de dépense interne, déjà traitée :
la protection a fonctionné, les étapes gratuites continuent. On ajoute seulement
que le refus vient de dehors, donc qu'il ne se lèvera pas tout seul — et qu'une
passe ainsi amputée ne doit pas se déclarer « ok ».
"""

import asyncio

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.pipeline.stages import FREE, PAID, Stage
from src.services.analysis.llm_usage import ProviderRefused

_CACHES = (get_settings, get_engine, get_session_factory)


def _run(tmp_path, monkeypatch, ordered):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'ref.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        from src.pipeline.runner import _run_stages

        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            from src.models.pipeline_run import PipelineRun

            run = PipelineRun(trigger="test", scope="full")
            db.add(run)
            await db.commit()
            await db.refresh(run)
            rid = run.id
        return await _run_stages(ordered, rid)

    try:
        return asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


async def _refuse():
    raise ProviderRefused("le fournisseur de modèles a répondu : crédits épuisés")


async def _travaille():
    return {"fait": 1}


def test_a_refusal_stops_the_paid_steps_and_lets_the_free_ones_through(
        tmp_path, monkeypatch):
    """Vectoriser et regrouper ce qui est déjà en base ne demande aucun modèle :
    ces étapes doivent tourner même quand le fournisseur est fermé."""
    ordered = [
        Stage("extraction", "Extraction", PAID, _refuse),
        Stage("nommage", "Nommage", PAID, _travaille),
        Stage("vecteurs", "Vecteurs", FREE, _travaille),
    ]
    report, failed, budget, refus = _run(tmp_path, monkeypatch, ordered)
    etats = {s["stage"]: s["status"] for s in report}

    assert etats["extraction"] == "refused"
    assert etats["nommage"] == "skipped", "inutile de redemander au même mur"
    assert etats["vecteurs"] == "ok", "le gratuit continue"
    assert not failed, "un fournisseur fermé n'est pas un défaut du code"
    assert "crédits épuisés" in refus


def test_a_refused_pass_does_not_report_ok(tmp_path, monkeypatch):
    """« ok » sur une passe où le fournisseur a tout refusé serait le même
    mensonge que « 0 sujet nommé » : un état qu'on lit comme un travail
    terminé."""
    ordered = [Stage("extraction", "Extraction", PAID, _refuse)]
    _report, _failed, _budget, refus = _run(tmp_path, monkeypatch, ordered)
    assert refus is not None


def test_a_real_bug_still_fails_and_still_stops_its_dependents(
        tmp_path, monkeypatch):
    """La distinction ne doit pas devenir une excuse : une erreur de code garde
    son ancien traitement, et ce qui dépend d'elle ne tourne pas sur des données
    à moitié écrites."""

    async def _casse():
        raise ValueError("une vraie faute")

    ordered = [
        Stage("extraction", "Extraction", PAID, _casse),
        Stage("vecteurs", "Vecteurs", FREE, _travaille, depends_on=("extraction",)),
    ]
    report, failed, _budget, refus = _run(tmp_path, monkeypatch, ordered)
    etats = {s["stage"]: s["status"] for s in report}

    assert etats["extraction"] == "failed"
    assert etats["vecteurs"] == "skipped"
    assert failed == {"extraction", "vecteurs"} and refus is None
