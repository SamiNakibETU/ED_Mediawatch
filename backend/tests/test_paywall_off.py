"""Murs payants : coupé par défaut, aucune voie de contournement n'est appelée (décision du 17/11/2026)."""

import asyncio

from src.config import get_settings
from src.services.collection import extractor_client as ec


def test_bypass_is_off_by_default():
    assert get_settings().paywall_bypass_enabled is False


def test_only_public_reading_when_bypass_is_off(monkeypatch):
    called = []

    def spy(name, result=None):
        async def f(*a, **k):
            called.append(name)
            return result
        return f

    for name in ("_via_cookies", "_via_ladder", "_via_removepaywall", "_via_wayback"):
        monkeypatch.setattr(ec, name, spy(name, "x" * 5000))
    monkeypatch.setattr(ec, "_via_service", spy("_via_service"))
    monkeypatch.setattr(ec, "_via_trafilatura", spy("_via_trafilatura", None))
    monkeypatch.setattr(ec, "_via_jina", spy("_via_jina", None))
    settings = get_settings()
    monkeypatch.setattr(settings, "paywall_bypass_enabled", False)
    monkeypatch.setattr(settings, "extractor_url", "http://service")
    monkeypatch.setattr(settings, "ladder_url", "http://ladder")
    monkeypatch.setattr(settings, "removepaywall_enabled", True)
    monkeypatch.setattr(settings, "jina_reader_enabled", True)
    asyncio.run(ec.extract_fulltext("https://www.lemonde.fr/article"))
    assert called == ["_via_trafilatura", "_via_jina"]
