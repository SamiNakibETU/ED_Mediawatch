"""La doctrine part avec le système, elle ne s'attend pas.

Le défaut corrigé : la boucle d'apprentissage n'ouvrait qu'à partir de cinq
décisions humaines. Un observatoire qui démarre en a zéro — et personne ne relit
cent rapprochements d'un juge qui n'a rien appris. L'amorçage ne pouvait donc
jamais venir. La doctrine écrite à la main est ce plancher.

Ces tests verrouillent la mécanique, pas la qualité des verdicts : celle-là se
mesure avec `python -m src.scripts.eval_judge`, qui appelle le modèle.
"""

import asyncio

from src.services.analysis import learning
from src.services.analysis.contradiction_judge import ContradictionVerdict, _JUDGE_SYSTEM
from src.services.analysis.doctrine import GOLD, RULES, doctrine_block


def test_doctrine_is_in_the_prompt_from_the_first_run():
    """Sans décision humaine, la consigne doit déjà porter la doctrine."""
    async def go():
        async def zero():
            return {"enough_to_learn": False, "decided": 0}
        original = learning.judge_precision
        learning.judge_precision = zero
        try:
            return await learning.judge_system_prompt("BASE")
        finally:
            learning.judge_precision = original

    prompt = asyncio.run(go())
    assert "BASE" in prompt
    assert "DOCTRINE DE L'OBSERVATOIRE" in prompt
    assert "CAS D'ÉCOLE" in prompt


def test_every_gold_case_is_usable_as_an_example():
    """Un cas incomplet passerait silencieusement dans la consigne, et le juge
    apprendrait une forme qu'il ne verra jamais en production."""
    verdicts = set(ContradictionVerdict.model_fields["verdict"].annotation.__args__)
    for c in GOLD:
        for champ in ("subject", "who_a", "when_a", "who_b", "when_b", "a", "b", "verdict", "why"):
            assert c.get(champ), f"champ « {champ} » manquant : {c.get('a', '?')[:40]}"
        assert c["verdict"] in verdicts, f"verdict hors vocabulaire : {c['verdict']}"


def test_the_bench_covers_every_verdict():
    """Un banc qui n'exerce que « contradiction » ne détecte pas une consigne
    devenue incapable de dire « compatible »."""
    couverts = {c["verdict"] for c in GOLD}
    assert couverts == set(ContradictionVerdict.model_fields["verdict"].annotation.__args__)


def test_conservative_cases_outnumber_accusatory_ones():
    """L'asymétrie est assumée : un juge qui sur-détecte coûte la crédibilité du
    produit. Le banc doit refléter cette prudence, sinon il l'entraîne à
    accuser."""
    accusatoires = sum(c["verdict"] == "contradiction" for c in GOLD)
    assert accusatoires < len(GOLD) - accusatoires


def test_the_rules_that_the_bench_forced_are_still_there():
    """Trois règles ont été écrites APRÈS avoir vu le juge se tromper. Les
    perdre ferait retomber le banc de 14/14 à 10/14 sans que rien ne le dise."""
    # Le doute de périmètre doit être fondé sur le texte, pas inventé.
    assert "L'absence de précision n'est pas une précision divergente" in RULES
    # Deux locuteurs opposés : le verdict reste « contradiction ».
    assert "le verdict\n   reste « contradiction »" in RULES
    # « compatible » et « hors_sujet » ne disent pas la même chose.
    assert "Objets\n   DIFFÉRENTS → hors_sujet" in RULES


def test_doctrine_stays_affordable():
    """La doctrine part à CHAQUE appel du juge. Un catalogue qui enfle coûte à
    chaque paire et finit par noyer la consigne."""
    bloc = doctrine_block()
    assert len(bloc) < 12000, f"doctrine trop longue : {len(bloc)} caractères"
    assert _JUDGE_SYSTEM not in bloc, "la doctrine ne doit pas redire la consigne de base"
