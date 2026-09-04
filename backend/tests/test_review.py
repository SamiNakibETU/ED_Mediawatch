"""La revue est l'endroit où toutes les précautions prises en amont peuvent être annulées.

Le verbatim est vérifié contre sa source, l'attribution contre le texte, le parti
contre une affiliation datée — puis un modèle écrit trois paragraphes de prose et
peut y glisser une affirmation qu'aucune déclaration ne porte. Le lecteur n'a
alors aucun moyen de faire la différence : c'est le même français, dans la même
page, sous le même bandeau.

D'où la règle, testée ici : un paragraphe existe s'il cite des déclarations
qu'on a effectivement fournies. Sans citation, il est retiré ; avec une citation
inventée, il est retiré aussi — et ce second cas est le plus grave, parce qu'un
modèle qui fabrique une référence n'a probablement pas mieux fondé le reste de
sa phrase.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.review import Review
from src.models.subject import Subject
from src.pipeline.stages import BY_NAME, PAID
from src.services.analysis.review import (
    Paragraphe,
    RevueEcrite,
    build_reviews,
    ground,
    periode_hebdo,
)

_CACHES = (get_settings, get_engine, get_session_factory)


# ── Le garde-fou, isolé ────────────────────────────────────────────────────


def test_a_paragraph_without_a_source_does_not_survive():
    """Une phrase peut être juste et rester inutilisable : si on ne peut pas
    remonter à ce qui la fonde, un observatoire ne la publie pas."""
    revue = RevueEcrite(titre="t", paragraphes=[
        Paragraphe(texte="Le RN a durci sa position.", claim_ids=[]),
        Paragraphe(texte="Chenu a demandé un moratoire.", claim_ids=[1]),
    ])
    gardes, cites = ground(revue, {1, 2})
    assert [p["texte"] for p in gardes] == ["Chenu a demandé un moratoire."]
    assert cites == [1]


def test_an_invented_source_takes_its_paragraph_down():
    """Citer une déclaration qu'on ne lui a pas donnée est la faute grave : le
    modèle a fabriqué une référence, rien ne dit que la phrase soit mieux
    fondée. On ne garde pas la moitié qu'on croit vraie."""
    revue = RevueEcrite(titre="t", paragraphes=[
        Paragraphe(texte="Elle a parlé de dette.", claim_ids=[1, 999]),
    ])
    gardes, cites = ground(revue, {1, 2})
    assert gardes == [] and cites == []


def test_the_iso_week_runs_monday_to_monday():
    """La clé de période sert d'identité en base : deux calculs différents de
    « la semaine dernière » créeraient deux revues du même moment."""
    mercredi = datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc)
    period, debut, fin = periode_hebdo(mercredi)
    assert period == "2026-W36"
    assert debut.weekday() == 0 and (fin - debut) == timedelta(days=7)
    assert debut <= mercredi < fin


# ── L'étape, de bout en bout, avec un modèle factice ───────────────────────


class _LLM:
    """Un modèle qui répond ce qu'on lui dit de répondre."""

    def __init__(self, revue):
        self.revue = revue
        self.appels = 0

        class _S:
            claim_tier2_model = "modele-de-test"
        self._s = _S()

    def available(self):
        return True

    async def write_review(self, *, prompt, system):
        self.appels += 1
        return self.revue


def _run(tmp_path, monkeypatch, revue, check):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'revue.db'}")
    for c in _CACHES:
        c.cache_clear()
    llm = _LLM(revue)
    monkeypatch.setattr("src.services.analysis.review.get_claim_llm", lambda: llm)

    async def go():
        await init_db()
        factory = get_session_factory()
        # Une semaine close : celle d'avant aujourd'hui.
        quand = datetime.now(timezone.utc) - timedelta(days=8)
        async with factory() as db:
            s = Subject(label="Le budget de la sécurité sociale",
                        slug="budget-securite-sociale", theme="social", status="labelled",
                        first_seen=quand, last_seen=quand)
            db.add(s)
            await db.commit()
            await db.refresh(s)
            for i, qui in enumerate(("Marine Le Pen", "Sébastien Chenu", "Marine Le Pen")):
                db.add(Claim(platform="x", subject_id=s.id, speaker_name=qui,
                             party="RN", verbatim=f"propos {i}", claim_type="normatif",
                             published_at=quand, confidence=0.7, dedup_key=f"r{i}"))
            await db.commit()
            sid = s.id
        await check(factory, sid, llm)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def _revue_valide(ids):
    return RevueEcrite(titre="Deux lectures du même budget", paragraphes=[
        Paragraphe(texte="Marine Le Pen s'est exprimée deux fois.", claim_ids=ids[:1]),
        Paragraphe(texte="Sébastien Chenu a pris une autre position.", claim_ids=ids[1:2]),
    ])


def test_a_review_is_written_once_and_never_again(tmp_path, monkeypatch):
    """Une revue décrit un état du corpus à une date. La réécrire plus tard avec
    ce qui est arrivé depuis produirait un texte qui n'a jamais été vrai au
    moment qu'il prétend décrire — et ferait repayer l'appel à chaque passe."""

    async def check(factory, sid, llm):
        async with factory() as db:
            ids = [c.id for c in (await db.execute(select(Claim))).scalars().all()]
        llm.revue = _revue_valide(ids)

        premiere = await build_reviews()
        assert premiere["ecrites"] == 1
        seconde = await build_reviews()
        assert seconde["ecrites"] == 0 and seconde["deja_ecrites"] == 1
        assert llm.appels == 1, "la seconde passe ne redemande rien au modèle"

        async with factory() as db:
            r = (await db.execute(select(Review))).scalars().one()
        assert r.status == "brouillon", "la machine propose, elle ne publie pas"
        assert len(r.body) == 2 and r.claim_ids

    _run(tmp_path, monkeypatch, None, check)


def test_a_fully_ungrounded_review_is_not_stored(tmp_path, monkeypatch):
    """Si tout est rejeté, on n'écrit pas une revue vide — et on ne marque
    rien : la semaine repassera, avec peut-être une meilleure réponse."""

    async def check(factory, sid, llm):
        llm.revue = RevueEcrite(titre="t", paragraphes=[
            Paragraphe(texte="Une affirmation sans source.", claim_ids=[]),
        ])
        stats = await build_reviews()
        assert stats["ecrites"] == 0 and stats["rejetees"] == 1
        async with factory() as db:
            assert (await db.execute(select(Review))).scalars().all() == []

    _run(tmp_path, monkeypatch, None, check)


def test_a_subject_with_a_single_voice_gets_no_review(tmp_path, monkeypatch):
    """Une revue d'un sujet où une seule personne parle paraphrase une
    déclaration : elle se lit comme un communiqué, pas comme une revue."""

    async def check(factory, sid, llm):
        async with factory() as db:
            for c in (await db.execute(select(Claim))).scalars().all():
                c.speaker_name = "Marine Le Pen"
            await db.commit()
        assert (await build_reviews())["ecrites"] == 0
        assert llm.appels == 0, "on ne paie pas un appel pour l'écarter ensuite"

    _run(tmp_path, monkeypatch, None, check)


def test_the_review_comes_after_the_naming():
    """Une revue qui désigne son sujet par « sujet 412 » ne se lit pas."""
    assert BY_NAME["review"].cost == PAID
    assert "label_subjects" in BY_NAME["review"].depends_on


def test_an_unnamed_subject_gets_no_review(tmp_path, monkeypatch):
    """Un sujet resté en « auto » porte les mots-clés de son regroupement —
    « adherents affilies cfdt designe ». Une revue titrée là-dessus se lit comme
    une sortie de machine, ce qu'elle est. L'étape dépend du nommage ; encore
    faut-il qu'il ait abouti pour CE sujet."""

    async def check(factory, sid, llm):
        async with factory() as db:
            (await db.get(Subject, sid)).status = "auto"
            await db.commit()
        assert (await build_reviews())["ecrites"] == 0
        assert llm.appels == 0

    _run(tmp_path, monkeypatch, None, check)


# ── La mémoire de la revue ─────────────────────────────────────────────────
# Sans antériorité, une revue hebdomadaire décrit et ne compare pas : elle
# republie chaque lundi un état des lieux interchangeable, quand la promesse du
# produit est de tenir le compte de ce qui se dit DANS LA DURÉE.


class _LLMEspion(_LLM):
    """Retient le prompt reçu : c'est lui qui décide de ce que la revue peut
    dire, et donc ce qu'il faut geler."""

    def __init__(self, revue):
        super().__init__(revue)
        self.prompt = None

    async def write_review(self, *, prompt, system):
        self.prompt = prompt
        return await super().write_review(prompt=prompt, system=system)


def _avec_anterieur(tmp_path, monkeypatch, revue, check):
    """Le même décor, plus un propos tenu six mois plus tôt sur le même sujet."""
    espion = _LLMEspion(revue)

    async def check_augmente(factory, sid, _llm):
        # Après `_run`, qui pose son propre modèle factice : sans ce second
        # branchement, l'espion serait remplacé et les tests passeraient à vide.
        monkeypatch.setattr("src.services.analysis.review.get_claim_llm", lambda: espion)
        vieux_jour = datetime.now(timezone.utc) - timedelta(days=190)
        async with factory() as db:
            db.add(Claim(platform="x", subject_id=sid, speaker_name="Marine Le Pen",
                         party="RN", verbatim="la position d'il y a six mois",
                         claim_type="normatif", published_at=vieux_jour,
                         confidence=0.7, dedup_key="ancien", relevance=4.0))
            await db.commit()
            ancien = (await db.execute(
                select(Claim).where(Claim.dedup_key == "ancien"))).scalar_one()
            recents = [c.id for c in (await db.execute(
                select(Claim).where(Claim.dedup_key != "ancien"))).scalars().all()]
        await check(factory, sid, espion, ancien.id, recents)

    _run(tmp_path, monkeypatch, revue, check_augmente)


def test_the_writer_is_given_what_was_said_before(tmp_path, monkeypatch):
    """Ce qui précède arrive au rédacteur séparé de la semaine, et annoncé comme
    tel : mélangé aux propos récents, il daterait la semaine de six mois."""

    async def check(factory, sid, espion, ancien_id, recents):
        espion.revue = _revue_valide(recents)
        await build_reviews()
        assert "AVANT cette semaine" in espion.prompt
        assert f"[{ancien_id}]" in espion.prompt
        semaine, avant = espion.prompt.split("AVANT cette semaine")
        assert f"[{ancien_id}]" not in semaine, "l'ancien propos n'est pas de la semaine"
        assert f"[{recents[0]}]" in semaine

    _avec_anterieur(tmp_path, monkeypatch, None, check)


def test_a_review_that_only_cites_the_past_is_not_this_weeks(tmp_path, monkeypatch):
    """Le rédacteur peut citer l'antériorité — sinon il ne pourrait pas montrer
    un déplacement. Mais une revue qui ne cite QUE le passé porte un titre de
    période qu'elle ne couvre pas : elle n'est pas enregistrée."""

    async def check(factory, sid, espion, ancien_id, recents):
        espion.revue = RevueEcrite(titre="Retour sur le printemps", paragraphes=[
            Paragraphe(texte="Elle défendait alors l'inverse.", claim_ids=[ancien_id]),
        ])
        stats = await build_reviews()
        assert stats["ecrites"] == 0
        async with factory() as db:
            assert (await db.execute(select(Review))).scalars().first() is None

    _avec_anterieur(tmp_path, monkeypatch, None, check)


def test_a_review_may_cite_both_sides_of_a_shift(tmp_path, monkeypatch):
    """Le cas qui justifie tout le reste : un paragraphe qui met l'ancien propos
    en regard du nouveau. Il doit passer entier."""

    async def check(factory, sid, espion, ancien_id, recents):
        espion.revue = RevueEcrite(titre="Un déplacement en six mois", paragraphes=[
            Paragraphe(texte="Elle disait l'inverse au printemps.",
                       claim_ids=[ancien_id, recents[0]]),
        ])
        stats = await build_reviews()
        assert stats["ecrites"] == 1
        async with factory() as db:
            r = (await db.execute(select(Review))).scalars().one()
        assert ancien_id in r.claim_ids and recents[0] in r.claim_ids

    _avec_anterieur(tmp_path, monkeypatch, None, check)
