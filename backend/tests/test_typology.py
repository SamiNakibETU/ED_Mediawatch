"""Typologie fine X (RT simple / RT commenté / réponse) + genre presse.

L'user veut distinguer « a juste RT » de « a RT et commenté » et savoir à qui il
répond ; et privilégier les interviews/entretiens côté presse.
"""

import re

from src.services.collection.relevance import classify_genre
from src.services.collection.x_collector import parse_feed
from src.utils import strip_accents


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(t)).lower()


# --- Genre presse ----------------------------------------------------------


def test_genre_interview():
    assert classify_genre(_norm("Bardella au micro de France Inter")) == "interview"
    assert classify_genre(_norm("Entretien avec Marine Le Pen")) == "interview"


def test_genre_tribune():
    assert classify_genre(_norm("Tribune de Marion Maréchal")) == "tribune"


def test_genre_communique():
    assert classify_genre(_norm("Dans un communiqué, le RN dénonce")) == "communique"


def test_genre_none_for_plain_news():
    assert classify_genre(_norm("Le RN en tête dans les sondages")) is None


# --- Typologie X (chemin RSS) ----------------------------------------------

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>R to @Enthoven_R: Bien vu.</title>
<link>https://nitter.net/J_Bardella/status/1#m</link></item>
<item><title>Un vrai message original ici.</title>
<link>https://nitter.net/J_Bardella/status/2#m</link></item>
</channel></rss>"""


def test_parse_feed_detects_reply_and_target():
    posts = {p["url"].split("/status/")[1][0]: p for p in parse_feed(_RSS, "J_Bardella")}
    reply = posts["1"]
    assert reply["is_reply"] is True
    assert reply["post_type"] == "reply"
    assert reply["reply_to_handle"] == "Enthoven_R"
    assert reply["collected_via"] == "rss"


def test_parse_feed_original():
    posts = {p["url"].split("/status/")[1][0]: p for p in parse_feed(_RSS, "J_Bardella")}
    orig = posts["2"]
    assert orig["post_type"] == "original"
    assert orig["reply_to_handle"] is None
