"""La grille CAP remplace une grille maison qui n'était comparable à rien.

Quinze thèmes inventés au départ, vingt-quatre valeurs en base six mois plus
tard, 310 propos sans thème du tout. Le CAP maintient depuis 1993 une grille de
21 topiques appliquée dans une vingtaine de pays ; le chapitre français a codé
les manifestes des partis français avec elle. L'adopter rend ce corpus
comparable à un jeu de données existant.

Ces tests portent sur la MÉCANIQUE — la grille, l'idempotence, la signature du
codeur, la remontée de la fiabilité. La JUSTESSE du codage ne se teste pas, elle
se mesure : `python -m src.scripts.eval_cap` rend l'alpha de Krippendorff contre
un jeu annoté à la main.
"""

import asyncio

import pytest
from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.pipeline.stages import BY_NAME, resolve_order
from src.services.analysis import cap
from src.services.analysis.cap_coder import _todo_filter, code_claims, distribution
from src.services.analysis.reliability import krippendorff_alpha, verdict

_CACHES = (get_settings, get_engine, get_session_factory)


# ── La grille ────────────────────────────────────────────────────────────

def test_the_grid_is_the_cap_grid():
    """21 topiques, codes non consécutifs. Les trous sont voulus : le codebook
    laisse 11 et 22 vides pour préserver la continuité depuis 1947."""
    assert len(cap.MAJOR) == 21
    assert 11 not in cap.MAJOR and 22 not in cap.MAJOR
    assert min(cap.CODES) == 1 and max(cap.CODES) == 23


def test_every_topic_carries_coding_help():
    """Un libellé seul ne suffit pas à trancher « Travail » contre
    « Protection sociale »."""
    for code, (libelle, aide) in cap.MAJOR.items():
        assert libelle and len(aide) > 20, f"topique {code} sans aide au codage"


def test_no_topic_outshouts_the_others():
    """Le topique 20 avait une aide trois fois plus longue que les autres, et
    il sur-attirait d'autant : à énumération plus riche, sélection plus
    probable. Mesuré : six écarts sur dix-neuf pointaient vers lui."""
    longueurs = [len(aide) for _, aide in cap.MAJOR.values()]
    plus_long, median = max(longueurs), sorted(longueurs)[len(longueurs) // 2]
    assert plus_long < median * 2.2, (
        "une aide au codage domine les autres en longueur : elle biaisera la "
        "sélection du modèle"
    )


def test_an_invalid_code_is_refused():
    """Un code hors grille est une hallucination, pas un topique inédit."""
    for bad in (0, 11, 22, 24, 99, None):
        assert not cap.is_valid(bad)
    assert cap.is_valid(9) and cap.is_valid(23)


# ── Le protocole ─────────────────────────────────────────────────────────

def test_the_protocol_asks_two_questions():
    """Un prompt holistique qui demande à la fois « de quoi s'agit-il » et
    « dans quelle catégorie » s'effondre — c'est la décomposition qui rend
    l'annotation fiable. Q1 ne doit pas porter la grille, sans quoi elle
    invite à chercher un topique au lieu de juger l'existence d'un objet."""
    assert cap.Q1_SYSTEM and cap.CODING_RULE
    assert "OUI ou NON" in cap.Q1_SYSTEM
    for libelle, _ in cap.MAJOR.values():
        assert libelle not in cap.Q1_SYSTEM or libelle.lower() in cap.Q1_SYSTEM.lower()
    assert "Macroéconomie" not in cap.Q1_SYSTEM, "Q1 ne doit pas porter la grille"


def test_the_rules_that_the_measurements_forced_are_still_there():
    """Trois corrections successives, chacune mesurée : 0,522 → 0,572 → 0,599.
    Les perdre ferait retomber l'alpha sans que rien ne le signale."""
    # Q1 recadrée sur l'attention : le CAP code aussi les événements, pas
    # seulement les propositions.
    assert "ATTENTION portée" in cap.Q1_SYSTEM or "l'ATTENTION" in cap.Q1_SYSTEM
    # La règle n° 1 du codebook.
    assert "jamais la CIBLE" in cap.CODING_RULE and "INSTRUMENT" in cap.CODING_RULE
    # L'anti-attraction du topique 20.
    assert "ATTENTION AU TOPIQUE 20" in cap.CODING_RULE


def test_the_coder_is_fully_identified():
    """Un codeur se définit par (modèle, consigne, échantillonnage). Sans les
    trois, un taux d'accord n'est ni interprétable ni reproductible."""
    sig = cap.coder_signature("un-modele")
    assert cap.CAP_GRID in sig and cap.CAP_PROTOCOL in sig
    assert "un-modele" in sig and str(cap.CAP_TEMPERATURE) in sig


def test_the_bridge_is_gone():
    """Une table de correspondance ne relit pas le texte : elle propage la
    classification qu'elle traduit, erreurs comprises. Mesurée à 31 % d'accord
    avec une relecture, elle a été retirée."""
    assert not hasattr(cap, "LEGACY_TO_CAP")
    assert not hasattr(cap, "from_legacy")


# ── La fiabilité ─────────────────────────────────────────────────────────

def test_alpha_beats_raw_agreement_where_it_matters():
    """Le cas qui justifie la métrique : une catégorie ultra-dominante donne
    80 % d'accord brut et un alpha négatif — moins bien que le hasard."""
    domine = [[1, 1]] * 8 + [[1, 2], [2, 1]]
    brut = sum(1 for a, b in domine if a == b) / len(domine)
    assert brut == 0.8
    assert krippendorff_alpha(domine) < 0


def test_alpha_is_undefined_rather_than_perfect():
    """Un seul code employé partout : l'alpha n'est pas défini. Rendre 1,0
    serait affirmer une fiabilité qu'aucune donnée ne soutient."""
    assert krippendorff_alpha([[1, 1], [1, 1]]) is None
    assert krippendorff_alpha([[1, None], [2, None]]) is None
    assert krippendorff_alpha([[1, 1], [2, 2], [3, 3]]) == pytest.approx(1.0)


def test_the_thresholds_are_the_established_ones():
    assert verdict(0.85).startswith("fiable")
    assert verdict(0.70).startswith("provisoire")
    assert verdict(0.50).startswith("non fiable")
    assert verdict(None) == "non mesurable"


def test_the_measured_reliability_travels_with_the_measure():
    """Le produit doit savoir dans quel état il est : sans ça l'interface
    publierait une répartition thématique comme un fait établi."""
    r = cap.RELIABILITY
    assert 0 <= r["alpha"] <= 1 and r["n_units"] >= 50
    seuil_atteint = r["alpha"] >= 0.67
    assert (r["verdict"] == "non fiable") != seuil_atteint
    if not seuil_atteint:
        assert r["caveat"], "une mesure sous le seuil doit porter sa réserve"


# ── Le codage ────────────────────────────────────────────────────────────

def _fake_llm(monkeypatch, reponses):
    """Codeur déterministe : ces tests portent sur la mécanique, pas sur la
    justesse — celle-là se mesure avec `eval_cap.py`."""
    import src.services.analysis.cap_coder as mod
    suite = list(reponses)

    class Faux:
        _s = type("S", (), {"claim_tier1_model": "modele-de-test"})()

        @staticmethod
        async def code_cap(_texte):
            return suite.pop(0) if suite else None

    monkeypatch.setattr(mod, "get_claim_llm", lambda: Faux())


def _with_claims(tmp_path, monkeypatch, themes, check):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'cap.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            for i, theme in enumerate(themes):
                db.add(Claim(
                    platform="x", verbatim=f"Propos {i}", canonical=f"Propos {i}",
                    claim_type="normatif", theme=theme, dedup_key=f"k{i}",
                    extraction_method="llm_segment",
                ))
            await db.commit()
        await check(factory)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_every_claim_goes_through_the_reader(tmp_path, monkeypatch):
    _fake_llm(monkeypatch, [1, 9, 12])

    async def check(factory):
        stats = await code_claims(limit=50)
        assert stats["coded"] == 3
        async with factory() as db:
            codes = sorted(
                (await db.execute(select(Claim.cap_major))).scalars().all())
        assert codes == [1, 9, 12]

    _with_claims(tmp_path, monkeypatch, ["economie", "immigration", "securite"], check)


def test_a_coded_claim_is_never_recoded(tmp_path, monkeypatch):
    """Sans marque de version, chaque passe repaierait le corpus entier."""
    _fake_llm(monkeypatch, [9, 3])

    async def check(factory):
        assert (await code_claims(limit=50))["coded"] == 2
        second = await code_claims(limit=50)
        assert second["coded"] == 0 and second["remaining"] == 0

    _with_claims(tmp_path, monkeypatch, ["immigration", "sante"], check)


def test_the_signature_is_written_on_every_annotation(tmp_path, monkeypatch):
    _fake_llm(monkeypatch, [9, 3])

    async def check(factory):
        await code_claims(limit=50)
        async with factory() as db:
            sigs = set((await db.execute(select(Claim.cap_version))).scalars().all())
        assert sigs == {cap.coder_signature("modele-de-test")}

    _with_claims(tmp_path, monkeypatch, ["immigration", "sante"], check)


def test_unclassifiable_claims_stop_being_resubmitted(tmp_path, monkeypatch):
    """Une part notable du corpus n'est pas du discours de politique publique.
    « Aucun topique » est une DÉCISION : la resoumettre à chaque passe
    reviendrait à payer indéfiniment pour la même réponse."""
    _fake_llm(monkeypatch, [None, None])

    async def check(factory):
        first = await code_claims(limit=50)
        assert first["no_topic"] == 2 and first["coded"] == 0
        assert (await code_claims(limit=50))["remaining"] == 0

    _with_claims(tmp_path, monkeypatch, ["inconnu_1", "inconnu_2"], check)


def test_the_share_outside_public_policy_is_shown(tmp_path, monkeypatch):
    """Cette part est un résultat, pas un raté : la masquer donnerait une
    répartition flatteuse et fausse."""
    _fake_llm(monkeypatch, [9, 3, None])

    async def check(factory):
        await code_claims(limit=50)
        rows = await distribution()
        assert any(r["code"] is None and r["label"] == "hors politique publique"
                   for r in rows)
        assert sum(r["part"] for r in rows) == pytest.approx(100, abs=0.5)

    _with_claims(tmp_path, monkeypatch, ["immigration", "sante", "autre"], check)


# ── Le pipeline ──────────────────────────────────────────────────────────

def test_coding_runs_before_anything_aggregates_by_topic():
    """Sujets, fiches et revue s'agrègent par topique : coder après aurait
    produit des agrégats vides puis à refaire."""
    assert "extract_l0" in BY_NAME["cap_coding"].depends_on
    order = [s.name for s in resolve_order()]
    assert order.index("cap_coding") < order.index("build_subjects")


# ── Un échec d'appel n'est pas une décision de codage ───────────────────────


def test_a_failed_call_is_not_recorded_as_a_coding_decision():
    """Vécu le 03/09/2026. `code_cap` rendait None dans deux cas opposés : le
    modèle répond « aucun objet d'action publique » — une décision — et l'appel
    échoue. Le codeur enregistrait les deux de la même façon.

    Résultat : pendant que le fournisseur refusait tous les appels, 4 660
    déclarations sur 4 682 ont été marquées « hors politique publique » et
    retirées de la file, sans qu'un modèle les ait jamais lues. La répartition
    thématique affichait 0,3 % pour le premier topique — un chiffre qui a l'air
    d'un résultat.

    On ne peut pas distinguer les deux après coup : c'est à l'appel de le faire.
    """
    import inspect

    from src.services.analysis.claim_llm import ClaimLLM

    source = inspect.getsource(ClaimLLM.code_cap)
    tete, _, queue = source.rpartition("except Exception")
    assert "raise" in queue, "un échec doit remonter, pas se déguiser en None"
    assert "return None" not in queue


def test_the_coder_only_marks_what_was_actually_read():
    """La marque `cap_version` sort une déclaration de la file pour de bon.
    L'apposer sur un propos que le modèle n'a pas lu est irréversible sans
    changer de version de protocole."""
    import inspect

    from src.services.analysis.cap_coder import code_claims

    source = inspect.getsource(code_claims)
    assert "echecs += 1" in source and "continue" in source
    assert "ProviderRefused" in source


def test_changing_the_protocol_requeues_the_whole_corpus():
    """C'est à ça que sert le numéro de protocole : le comportement du codeur a
    changé, donc ce qu'il a produit avant ne vaut plus, et tout doit repasser."""
    from src.services.analysis.cap import CAP_PROTOCOL, CAP_VERSION

    assert CAP_PROTOCOL == "2q-v2"
    assert not "cap-major-2019/2q-v1".startswith(CAP_VERSION), (
        "l'ancien marquage ne doit plus satisfaire le filtre de recodage")
