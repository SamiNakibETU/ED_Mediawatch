"""Extraction presse : détection de mur payant (précision) + cookies par domaine."""

import importlib

from src.services.collection.extractor_client import _is_paywalled


def test_paywall_markers_detected():
    assert _is_paywalled("Bla. Il vous reste 80 % de cet article à lire. Abonnez-vous.")
    assert _is_paywalled("Article réservé aux abonnés")
    assert _is_paywalled("Connectez-vous pour lire la suite")


def test_real_article_not_paywalled():
    assert not _is_paywalled(
        "Marine Le Pen a déclaré que la politique migratoire devait changer en "
        "profondeur, lors d'un meeting à Hénin-Beaumont devant ses militants."
    )


def test_empty_not_paywalled():
    assert not _is_paywalled("")
    assert not _is_paywalled(None)


def test_cookie_for_domain(monkeypatch):
    monkeypatch.setenv("SITE_COOKIES", '{"lemonde.fr": "ssid=abc; lmd=1"}')
    from src.config import get_settings
    from src.services.collection import extractor_client as ec
    get_settings.cache_clear()
    ec._site_cookies.cache_clear()
    try:
        assert ec._cookie_for("https://www.lemonde.fr/x/article.html") == "ssid=abc; lmd=1"
        assert ec._cookie_for("https://www.lefigaro.fr/x") is None
    finally:
        get_settings.cache_clear()
        ec._site_cookies.cache_clear()
