"""Archivage / reçus (C3) : cible d'archive canonique.

Un tweet doit être archivé via son URL x.com canonique (le lien Nitter pointe une
instance éphémère qui s'archive mal) ; un article presse via son URL telle quelle.
"""

from src.services.archive.archiver import _archive_target


def test_x_target_canonicalized_to_xcom():
    assert (
        _archive_target("x", "https://nitter.net/J_Bardella/status/123#m")
        == "https://x.com/J_Bardella/status/123"
    )


def test_x_target_other_instance():
    assert (
        _archive_target("x", "https://nitter.poast.org/MLP_officiel/status/9")
        == "https://x.com/MLP_officiel/status/9"
    )


def test_press_target_unchanged():
    url = "https://www.lemonde.fr/politique/article/x.html"
    assert _archive_target("press", url) == url


def test_x_target_without_status_unchanged():
    url = "https://nitter.net/J_Bardella"
    assert _archive_target("x", url) == url
