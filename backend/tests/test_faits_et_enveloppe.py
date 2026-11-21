"""Regroupement des écarts par fait, et lecture d'une liste JSON rendue sans son enveloppe."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field, ValidationError

from src.routers.ecarts import cle_fait
from src.scripts.mesurer_jeu_or import enjeux_de
from src.services.analysis.claim_llm import _valider


def ecart(**k):
    base = dict(id=1, type="parti", enjeu="fin_de_vie", parti_a="RN", parti_b="RN",
                position_a="contre", position_b="pour", figure_a_id=1, figure_b_id=2)
    return SimpleNamespace(**{**base, **k})


def test_un_vote_qui_divise_un_parti_est_un_seul_fait():
    # Douze voix contre, deux pour : vingt-quatre paires, un fait.
    paires = [ecart(id=i, figure_a_id=a, figure_b_id=b) for i, (a, b) in enumerate(
        (a, b) for a in range(12) for b in (100, 101))]
    assert len({cle_fait(e) for e in paires}) == 1


def test_le_sens_de_la_paire_ne_change_pas_le_fait():
    assert cle_fait(ecart(position_a="pour", position_b="contre")) == cle_fait(ecart())


def test_deux_partis_ou_deux_enjeux_font_deux_faits():
    assert cle_fait(ecart(parti_a="UDR")) != cle_fait(ecart())
    assert cle_fait(ecart(enjeu="voile")) != cle_fait(ecart())


def test_dans_le_temps_un_fait_par_figure_et_par_enjeu():
    a = ecart(type="temps", figure_a_id=7, figure_b_id=7, position_a="x", position_b="y")
    b = ecart(type="temps", id=2, figure_a_id=7, figure_b_id=7, position_a="y", position_b="x")
    c = ecart(type="temps", id=3, figure_a_id=8, figure_b_id=8)
    assert cle_fait(a) == cle_fait(b) != cle_fait(c)


def test_les_ecarts_de_chiffre_ne_sont_pas_regroupes():
    assert cle_fait(ecart(type="chiffre", id=1)) != cle_fait(ecart(type="chiffre", id=2))


class Ligne(BaseModel):
    t: str = ""


class Liste(BaseModel):
    tweets: list[Ligne] = Field(default_factory=list)


class Deux(BaseModel):
    a: list[Ligne] = Field(default_factory=list)
    b: str = ""


@pytest.mark.parametrize("texte, attendu", [
    ('{"tweets": [{"t": "a"}, {"t": "b"}]}', 2),
    ('{"t": "a"}\n{"t": "b"}\n{"t": "c"}', 3),
    ('{"t": "a"}{"t": "b"}', 2),
    ('[{"t": "a"}, {"t": "b"}]', 2),
    ('Voici :\n{"tweets": [{"t": "a"}]}', 1),
])
def test_liste_rendue_avec_ou_sans_enveloppe(texte, attendu):
    assert len(_valider(Liste, texte).tweets) == attendu


def test_un_schema_a_plusieurs_champs_ne_devine_rien():
    with pytest.raises(ValidationError):
        _valider(Deux, '{"t": "a"}{"t": "b"}')


def test_enjeu_d_un_cas_du_jeu_d_or():
    assert enjeux_de("retraites-abrogation-report-juin-2024") == ("retraites", "reforme_2023")
    assert enjeux_de("darmanin-demission-lepen-bardella-juin-2026") == ()
