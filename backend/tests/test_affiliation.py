"""Résolution du parti à la date (SpeakerAffiliation) — critère §5."""

from datetime import date, datetime, timezone

from src.models.affiliation import SpeakerAffiliation
from src.services.affiliation import party_at


def _aff(party, start, end):
    return SpeakerAffiliation(
        personality_id=1, party=party, date_start=start, date_end=end
    )


# Cas Ciotti : LR jusqu'au 2024-06-12, UDR ensuite.
CIOTTI = [
    _aff("LR", date(2022, 12, 11), date(2024, 6, 12)),
    _aff("UDR", date(2024, 6, 12), None),
]


def test_party_before_transition():
    assert party_at(CIOTTI, date(2023, 1, 1)) == "LR"


def test_party_after_transition():
    assert party_at(CIOTTI, date(2025, 1, 1)) == "UDR"


def test_party_accepts_datetime():
    assert party_at(CIOTTI, datetime(2023, 1, 1, tzinfo=timezone.utc)) == "LR"


def test_no_date_falls_back_to_current():
    # Sans date connue : on prend l'affiliation en cours (date_end None).
    assert party_at(CIOTTI, None) == "UDR"


def test_no_affiliations_is_none():
    assert party_at([], date(2024, 1, 1)) is None
    assert party_at(None, date(2024, 1, 1)) is None


def test_uncovered_date_falls_back_to_current():
    # Date antérieure à toute affiliation connue → repli sur l'en-cours.
    assert party_at(CIOTTI, date(2000, 1, 1)) == "UDR"


def test_single_open_affiliation():
    affils = [_aff("RN", date(2024, 7, 8), None)]
    assert party_at(affils, date(2025, 3, 1)) == "RN"
