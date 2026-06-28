"""Extraction presse : détection de mur payant (précision) + cookies par domaine.

Couvre aussi le wrapping `Extraction` (C0) : la qualité (méthode, complétude,
paywall) accompagne désormais chaque texte jusqu'à l'Article.
"""

import importlib

from src.services.collection.extractor_client import Extraction, _is_paywalled, build_extraction


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


def test_build_extraction_infers_full_text():
    """Un texte propre et assez long est marqué intégral, sans marqueur paywall."""
    ext = build_extraction("Marine Le Pen " * 80, "scraped")
    assert ext is not None
    assert ext.method == "scraped"
    assert ext.is_full is True
    assert ext.paywalled is False


def test_build_extraction_flags_paywall():
    """Un teaser paywall : non-intégral, paywall détecté (même si long)."""
    ext = build_extraction(
        "Bla bla. " * 50 + "Il vous reste 80 % de cet article à lire. Abonnez-vous.",
        "jina_ai",
    )
    assert ext is not None
    assert ext.paywalled is True
    assert ext.is_full is False


def test_build_extraction_none_on_empty():
    assert build_extraction("", "scraped") is None
    assert build_extraction(None, "scraped") is None


def test_extraction_default_is_empty():
    assert Extraction().ok is False


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
