"""Nettoyage du corps d'article : retire liens + boilerplate, garde le verbatim."""

from src.services.collection.text_clean import clean_article_text


def test_removes_read_also_teasers():
    txt = (
        "Marine Le Pen a déclaré que la politique migratoire devait changer.\n"
        "Lire aussi : Le RN en tête des sondages\n"
        "Elle a insisté sur la sécurité.\n"
        "À lire également : la réaction de la majorité\n"
    )
    out = clean_article_text(txt)
    assert "politique migratoire" in out
    assert "insisté sur la sécurité" in out
    assert "Lire aussi" not in out
    assert "À lire également" not in out


def test_strips_links_and_urls():
    txt = "Le candidat (voir [son programme](https://rn.fr/prog)) a parlé. https://x.com/abc"
    out = clean_article_text(txt)
    assert "son programme" in out          # texte d'ancre gardé
    assert "https://" not in out           # URLs retirées
    assert "rn.fr/prog" not in out


def test_drops_share_newsletter_credits():
    txt = (
        "Un vrai paragraphe d'article qui doit rester intact ici.\n"
        "Partager sur Facebook\n"
        "Abonnez-vous à notre newsletter\n"
        "Crédit photo : AFP\n"
        "5 min de lecture\n"
        "Suivez-nous sur Twitter\n"
    )
    out = clean_article_text(txt)
    assert "paragraphe d'article qui doit rester" in out
    for noise in ("Partager", "Abonnez-vous", "Crédit photo", "min de lecture", "Suivez-nous"):
        assert noise not in out


def test_keeps_verbatim_sentence_unchanged():
    s = "« La France d'abord », a martelé le député devant ses militants."
    assert clean_article_text(s) == s      # prose intacte (fidélité verbatim)


def test_long_paragraph_with_marker_not_dropped():
    # « partager » dans une vraie phrase longue ne doit PAS supprimer le paragraphe.
    s = ("Le responsable a expliqué vouloir partager sa vision avec les Français "
         "lors d'un meeting très suivi dans le sud de la France ce week-end.")
    assert "vision avec les Français" in clean_article_text(s)


def test_empty():
    assert clean_article_text("") == ""
    assert clean_article_text(None) == ""
