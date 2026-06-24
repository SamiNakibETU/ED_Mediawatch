"""Garde anti-tweets-vides : ne pas forcer Cohere sur un post sans contenu
classifiable (source du bruit science_techno/travail_emploi à l'it.2)."""

from src.services.classification.runner import _classifiable


def test_empty_or_media_only_not_classifiable():
    assert _classifiable("Image") is False
    assert _classifiable("RT by @BeaurainJose: Image") is False
    assert _classifiable("https://t.co/abcd") is False
    assert _classifiable("@Marine_LP 👍🇫🇷") is False
    assert _classifiable("") is False


def test_real_content_is_classifiable():
    assert _classifiable("Il faut expulser les clandestins en OQTF maintenant") is True
    # Le préfixe RT + mention sont retirés, le reste compte.
    assert _classifiable("RT by @x: La submersion migratoire menace notre pays") is True
