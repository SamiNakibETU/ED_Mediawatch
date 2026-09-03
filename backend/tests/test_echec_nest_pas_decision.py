"""Un appel raté ne doit jamais s'enregistrer comme une décision.

C'est la même faute, retrouvée quatre fois le 03/09/2026, et elle a coûté cher
une fois : pendant que le fournisseur de modèles refusait tous les appels, 4 660
déclarations sur 4 682 ont été marquées « hors politique publique » et retirées
de la file de codage sans qu'un modèle les ait jamais lues. La répartition
thématique affichait alors 0,3 % pour son premier topique — un chiffre qui a
l'air d'un résultat.

Le mécanisme est toujours le même. Une fonction rend `None` pour dire « le
modèle a répondu : rien ici », et rend aussi `None` quand l'appel échoue.
L'appelant, qui ne peut plus distinguer les deux, marque le travail comme fait.
La marque est irréversible sans changer de version de protocole.

La règle : `None` est réservé aux décisions. Un échec remonte. Et une marque de
« traité » ne s'appose qu'après une réponse.

Ces tests lisent le code plutôt que de l'exécuter, parce que ce qu'ils gardent
est une règle d'écriture, pas un comportement observable — le comportement
fautif, justement, ne s'observait pas.
"""

import inspect


def test_the_thematic_coder_reraises_instead_of_returning_none():
    from src.services.analysis.claim_llm import ClaimLLM

    _, _, apres = inspect.getsource(ClaimLLM.code_cap).rpartition("except Exception")
    assert "raise" in apres and "return None" not in apres


def test_the_pledge_reader_reraises_instead_of_returning_none():
    from src.services.analysis.claim_llm import ClaimLLM

    src = inspect.getsource(ClaimLLM.read_pledge)
    _, _, apres = src.rpartition("except Exception")
    assert "raise" in apres, "un Q1 raté ne dit pas « il ne s'engage pas »"


def test_the_extractor_does_not_mark_a_source_it_could_not_read():
    """Le cas le plus coûteux : une publication marquée « traitée » sort de la
    file pour de bon, et ses déclarations sont perdues sans trace."""
    from src.services.analysis.declaration_extractor import run_declaration_extraction

    src = inspect.getsource(run_declaration_extraction)
    assert src.count("if result is None:") == 2, "les deux boucles, X et presse"
    for boucle in src.split("if result is None:")[1:]:
        avant_marque = boucle[: boucle.find("done_")]
        assert "continue" in avant_marque


def test_every_marking_step_lets_a_refusal_through():
    """Un fournisseur fermé arrête l'étape ; il ne la fait pas tourner à vide en
    marquant tout ce qu'elle touche."""
    from src.services.analysis.cap_coder import code_claims
    from src.services.analysis.declaration_extractor import run_declaration_extraction
    from src.services.analysis.pledges import detect_pledges

    for fn in (code_claims, detect_pledges, run_declaration_extraction):
        assert "ProviderRefused" in inspect.getsource(fn), fn.__name__


def test_each_marking_step_counts_its_failures():
    """Un échec qu'on ne compte pas est un échec qu'on ne voit pas : c'est ce
    qui a permis à la faute de vivre plusieurs jours."""
    from src.services.analysis.cap_coder import code_claims
    from src.services.analysis.pledges import detect_pledges

    for fn in (code_claims, detect_pledges):
        assert "echecs" in inspect.getsource(fn), fn.__name__
