"""Lecture d'un scrutin au format de data.assemblee-nationale.fr."""

from datetime import date

from src.scripts.importer_scrutins import lire_scrutin

SCRUTIN = {"scrutin": {
    "uid": "VTANR5L17V1234", "numero": "1234", "legislature": "17", "dateScrutin": "2025-05-27",
    "typeVote": {"codeTypeVote": "SPS", "libelleTypeVote": "scrutin public solennel"},
    "sort": {"code": "adopté"}, "titre": "l'ensemble de la proposition de loi relative au droit à l'aide à mourir",
    "syntheseVote": {"decompte": {"pour": "305", "contre": "199", "abstentions": "57", "nonVotants": "1"}},
    "ventilationVotes": {"organe": {"groupes": {"groupe": [
        {"organeRef": "PO845401", "vote": {"positionMajoritaire": "abstention",
                                           "decompteVoix": {"pour": "1", "contre": "2", "abstentions": "0"},
                                           "decompteNominatif": {
            "pours": {"votant": {"acteurRef": "PA1", "parDelegation": "false"}},   # un seul : un objet, pas une liste
            "contres": {"votant": [{"acteurRef": "PA2", "parDelegation": "true"},
                                   {"acteurRef": "PA3", "parDelegation": "false"}]},
            "abstentions": None,
            "nonVotants": {"votant": [{"acteurRef": "PA4", "causePositionVote": "PAN"}]}}}},
        {"organeRef": "PO800000", "vote": {"positionMajoritaire": "pour",
                                           "decompteVoix": {"pour": "1", "contre": "1", "abstentions": "0"},
                                           "decompteNominatif": {
            "pours": {"votant": [{"acteurRef": "PA9"}]}, "contres": None, "abstentions": None, "nonVotants": None}}},
    ]}}},
}}


def test_entete():
    e, _ = lire_scrutin(SCRUTIN)
    assert e["uid"] == "VTANR5L17V1234" and e["legislature"] == 17 and e["numero"] == 1234
    assert e["date"] == date(2025, 5, 27) and e["type"] == "SPS" and e["sort"] == "adopté"
    assert (e["pour"], e["contre"], e["abstentions"]) == (305, 199, 57)


def test_votes_nominatifs_objet_ou_liste():
    _, votes = lire_scrutin(SCRUTIN)
    par = {v["acteur"]: v for v in votes}
    assert set(par) == {"PA1", "PA2", "PA3", "PA4", "PA9"}
    assert par["PA1"]["vote"] == "pour" and par["PA1"]["majorite"] == "contre" and par["PA1"]["groupe"] == "PO845401"
    assert par["PA2"]["delegation"] is True and par["PA3"]["delegation"] is False
    assert par["PA4"]["vote"] == "non_votant" and par["PA4"]["cause"] == "PAN"
    # Égalité dans le décompte : pas de majorité, quoi que dise le champ publié.
    assert par["PA9"]["majorite"] is None


def test_majorite_tiree_du_decompte_pas_du_champ_publie():
    _, votes = lire_scrutin(SCRUTIN)
    assert next(v for v in votes if v["acteur"] == "PA2")["majorite"] == "contre"


def test_scrutin_sans_ventilation():
    brut = {"scrutin": {**SCRUTIN["scrutin"], "ventilationVotes": None, "syntheseVote": None}}
    e, votes = lire_scrutin(brut)
    assert votes == [] and e["pour"] is None
