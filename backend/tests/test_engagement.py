"""Parsing des compteurs d'engagement Nitter (likes/RT/réponses/quotes).

L'engagement est un critère de métadonnées §5 : un « 1.2K » mal lu (→ 1) fausse
le signal. On verrouille plein ET compact.
"""

from src.services.collection.x_html_parser import _parse_count


def test_plain_integer():
    assert _parse_count("1234") == 1234


def test_thousands_comma():
    assert _parse_count("1,234") == 1234


def test_thousands_space_and_nbsp():
    assert _parse_count("1 234") == 1234
    assert _parse_count("1 234") == 1234


def test_thousands_dot_european():
    assert _parse_count("1.234") == 1234


def test_compact_k():
    assert _parse_count("1.2K") == 1200
    assert _parse_count("12K") == 12000


def test_compact_m():
    assert _parse_count("3M") == 3_000_000


def test_empty_is_zero():
    assert _parse_count("") == 0
    assert _parse_count("   ") == 0
