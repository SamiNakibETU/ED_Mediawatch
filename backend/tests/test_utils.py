"""Helpers partagés : nettoyage HTML, clés de dédup, dates de flux (tz-aware)."""

import time
from datetime import timezone
from types import SimpleNamespace

from src.utils import clean_html, feed_datetime, status_id, tweet_guid


# --- clean_html : décode TOUTES les entités, retire les balises -------------

def test_clean_html_numeric_entity():
    assert clean_html("aujourd&#8217;hui") == "aujourd’hui"


def test_clean_html_named_entity():
    assert clean_html("d&eacute;put&eacute;") == "député"


def test_clean_html_strips_tags_and_nbsp():
    assert clean_html("<p>Bonjour&nbsp;<b>monde</b></p>") == "Bonjour monde"


def test_clean_html_none_is_empty():
    assert clean_html(None) == ""


# --- tweet_guid : dédup stable, indépendante de la forme d'URL --------------

def test_status_id_extraction():
    assert status_id("https://nitter.net/Bob/status/123#m") == "123"
    assert status_id("https://example.com/no-status") is None


def test_tweet_guid_stable_across_url_forms_and_case():
    a = tweet_guid("Bob", "https://nitter.net/Bob/status/123#m")
    b = tweet_guid("bob", "https://x.com/bob/status/123")
    assert a == b


def test_tweet_guid_differs_per_status():
    a = tweet_guid("Bob", "https://x.com/Bob/status/123")
    b = tweet_guid("Bob", "https://x.com/Bob/status/456")
    assert a != b


# --- feed_datetime : toujours tz-aware (UTC) --------------------------------

def test_feed_datetime_is_tz_aware():
    # Timestamp moderne (éviter la frontière epoch qui fait overflow mktime sous Windows).
    entry = SimpleNamespace(published_parsed=time.gmtime(1_700_000_000), updated_parsed=None)
    dt = feed_datetime(entry)
    assert dt is not None
    assert dt.tzinfo == timezone.utc


def test_feed_datetime_none_when_missing():
    assert feed_datetime(SimpleNamespace()) is None
