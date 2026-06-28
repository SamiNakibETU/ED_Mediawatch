"""Tests pour paywall_bypass — helpers purs (pas de réseau réel)."""

import sys
from pathlib import Path

# Add scraper-service src to path for direct test invocation
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.paywall_bypass import (  # noqa: E402
    GOOGLEBOT_UA,
    is_premium_domain,
    looks_paywalled,
)


def test_googlebot_ua_constant():
    assert "Googlebot" in GOOGLEBOT_UA
    assert "google.com" in GOOGLEBOT_UA


def test_looks_paywalled_short_text():
    assert looks_paywalled("")
    assert looks_paywalled(None)
    assert looks_paywalled("trop court")


def test_looks_paywalled_clean_text_long():
    txt = " ".join(["analyse politique éditorial Liban Hezbollah"] * 50)
    assert not looks_paywalled(txt)


def test_looks_paywalled_with_chrome():
    # texte assez long mais avec multiples CTAs
    body = " ".join(["contenu propre éditorial"] * 80)
    chrome = " Abonnez-vous Subscribe now Continue reading Abonnez-vous "
    assert looks_paywalled(body + chrome)


def test_is_premium_domain_haaretz():
    assert is_premium_domain("https://www.haaretz.com/opinion/editorial/...")


def test_is_premium_domain_lemonde():
    assert is_premium_domain("https://www.lemonde.fr/international/article/...")


def test_is_premium_domain_olj_not_premium():
    # OLJ = full RSS, pas besoin de bypass
    assert not is_premium_domain("https://www.lorientlejour.com/article/...")


def test_is_premium_domain_aljazeera_not_premium():
    assert not is_premium_domain("https://www.aljazeera.com/news/...")
