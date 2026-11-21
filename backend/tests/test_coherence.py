"""L'indice de cohérence : les trois mesures, leurs seuils, le programme en vigueur à la date."""

from datetime import datetime, timedelta, timezone

from src.services.analysis.coherence import Decl, mesurer

MAINTENANT = datetime(2026, 11, 21, tzinfo=timezone.utc)


def d(figure, position, jours_avant, enjeu="voile", parti="RN"):
    return Decl(parti, enjeu, figure, MAINTENANT - timedelta(days=jours_avant), position)


def ligne(res, enjeu="voile", parti="RN"):
    return next(x for x in res[parti]["enjeux"] if x["enjeu"] == enjeu)


def test_alignement_sur_la_derniere_position_de_chaque_figure():
    decls = [d(1, "partout", 10), d(2, "partout", 20), d(3, "certains_lieux", 30),
             d(3, "partout", 400)]  # la position ancienne de la figure 3 ne compte pas
    x = ligne(mesurer(decls, set(), {}, MAINTENANT))
    assert x["alignement"] == {"n": 2, "sur": 3, "part": 67}
    assert x["position_majoritaire"] == "partout"


def test_pas_d_alignement_sous_trois_figures():
    x = ligne(mesurer([d(1, "partout", 10), d(2, "partout", 20)], set(), {}, MAINTENANT))
    assert x["alignement"] is None


def test_constance_compte_les_revirements_retenus():
    decls = [d(1, "partout", 10), d(1, "partout", 100), d(2, "partout", 10), d(2, "certains_lieux", 200)]
    x = ligne(mesurer(decls, {(2, "voile")}, {}, MAINTENANT))
    assert x["constance"] == {"n": 1, "sur": 2, "part": 50}


def test_constance_ignore_les_propos_rapproches():
    # Deux propos à moins de trente jours ne disent rien de la constance.
    decls = [d(1, "partout", 10), d(1, "partout", 20), d(2, "partout", 10), d(2, "partout", 25)]
    assert ligne(mesurer(decls, set(), {}, MAINTENANT))["constance"] is None


def test_programme_en_vigueur_a_la_date():
    programme = {("RN", "voile"): {2022: {"certains_lieux"}, 2024: {"partout"}}}
    decls = [d(1, "partout", 1500), d(2, "partout", 1400),       # 2022-2023 : contre le programme de 2022
             d(3, "partout", 300), d(4, "partout", 200), d(5, "partout", 100)]  # 2025-2026 : conformes à 2024
    x = ligne(mesurer(decls, set(), programme, MAINTENANT))
    assert x["programme"] == {"n": 3, "sur": 5, "part": 60}


def test_avant_tout_programme_rien_ne_compte():
    programme = {("RN", "voile"): {2026: {"partout"}}}
    decls = [d(i, "certains_lieux", 700) for i in range(6)]
    assert ligne(mesurer(decls, set(), programme, MAINTENANT))["programme"] is None


def test_indice_de_parti_demande_cinq_enjeux():
    decls = []
    for k, enjeu in enumerate(("voile", "ame", "eolien", "nucleaire")):
        decls += [d(10 * k + i, "x", 10, enjeu) for i in range(3)]
        decls += [d(10 * k + i, "x", 200, enjeu) for i in range(3)]
    res = mesurer(decls, set(), {}, MAINTENANT)
    assert all(x["indice"] == 100 for x in res["RN"]["enjeux"])
    assert res["RN"]["enjeux_mesures"] == 4 and res["RN"]["indice"] is None
    decls += [d(90 + i, "x", 10, "smic") for i in range(3)] + [d(90 + i, "x", 200, "smic") for i in range(3)]
    assert mesurer(decls, set(), {}, MAINTENANT)["RN"]["indice"] == 100


def test_un_parti_sans_donnees_est_present_et_vide():
    res = mesurer([], set(), {}, MAINTENANT)
    assert res["UDR"]["indice"] is None and res["UDR"]["enjeux"] == []
