"""Historique X par une instance Nitter : lecture des pages, fin de pagination, import."""

import asyncio

import httpx

from src.scripts import historique_x as hx
from src.services.collection.x_html_parser import lire_page_recherche


def _item(auteur, tid, texte, *, retweet=False, citation=None, lien=None):
    rt = '<div class="retweet-header"><span>Marine Le Pen retweeted</span></div>' if retweet else ""
    cite = (f'<div class="quote"><a class="quote-link" href="/{citation}/status/9"></a>'
            f'<a class="username" title="@{citation}">@{citation}</a><div class="quote-text">Texte cité</div></div>'
            if citation else "")
    corps = texte + (f' <a href="{lien}">{lien[8:30]}…</a>' if lien else "")
    return (f'<div class="timeline-item"><a class="tweet-link" href="/{auteur}/status/{tid}#m"></a>{rt}'
            f'<span class="tweet-date"><a href="/{auteur}/status/{tid}#m" title="Jun 24, 2024 · 7:31 AM UTC">'
            f'24 Jun</a></span><div class="tweet-content media-body">{corps}</div>{cite}'
            '<div class="tweet-stats">'
            '<span class="tweet-stat"><div class="icon-container"><span class="icon-comment"></span> 547</div></span>'
            '<span class="tweet-stat"><div class="icon-container"><span class="icon-heart"></span> 6,475</div></span>'
            '<span class="tweet-stat"><div class="icon-container"><span class="icon-views"></span> 774,660</div></span>'
            '</div></div>')


_CURSEURS = iter(range(10**6))


def _page(items, suite=True):
    """Chaque page porte son propre curseur, comme sur une vraie instance."""
    plus = (f'<div class="show-more"><a href="/search?q=x&amp;cursor=C{next(_CURSEURS)}">Load more</a></div>'
            if suite else "")
    return "<html><body><div class='timeline'>" + "".join(items) + plus + "</div></body></html>"


def test_les_mois_vont_du_plus_recent_au_plus_ancien_bornes_comprises():
    assert hx.mois("2025-11", "2026-02") == [
        ("2026-02", "2026-02-01", "2026-03-01"), ("2026-01", "2026-01-01", "2026-02-01"),
        ("2025-12", "2025-12-01", "2026-01-01"), ("2025-11", "2025-11-01", "2025-12-01")]


def test_une_page_donne_le_tweet_sous_son_adresse_x_avec_le_lien_complet_et_sans_les_retweets():
    html = _page([_item("MLP_officiel", "1", "Lisez le programme", lien="https://rassemblementnational.fr/22-mesures"),
                  _item("RNational_off", "2", "Un texte relayé", retweet=True),
                  _item("MLP_officiel", "3", "Cette présentation est malhonnête.", citation="bfmbusiness")])
    tweets, suite, retweets = lire_page_recherche(html)
    (a1, t1), (_, t3) = tweets
    assert retweets == 1 and suite and a1 == "MLP_officiel"
    assert t1["url"] == "https://x.com/MLP_officiel/status/1"
    assert t1["content"] == "Lisez le programme https://rassemblementnational.fr/22-mesures"
    assert (t1["likes"], t1["replies"], t1["views"]) == (6475, 547, 774660)
    assert t3["post_type"] == "quote" and t3["quoted_handle"] == "bfmbusiness"
    assert t3["published_at"].isoformat() == "2024-06-24T07:31:00+00:00"


def _lecteur(pages):
    """Un lecteur dont l'instance rend `pages` dans l'ordre, puis des pages vides avec un lien suivant."""
    vues = []

    def repondre(req):
        vues.append(str(req.url))
        k = len(vues) - 1
        return httpx.Response(200, text=pages[k] if k < len(pages) else _page([]))
    return hx.Lecteur("https://instance.test", 0, transport=httpx.MockTransport(repondre)), vues


def _pleine(debut, n=20):
    return _page([_item("MLP_officiel", str(i), f"Tweet {i}") for i in range(debut, debut + n)])


def test_une_page_vide_au_milieu_ne_coupe_pas_le_mois_mais_la_derniere_page_incomplete_le_termine():
    # Mesuré le 26/10/2026 : pleine, vide, pleine, incomplète, puis des pages vides sans fin.
    lecteur, vues = _lecteur([_pleine(0), _page([]), _pleine(20), _pleine(40, 6)])
    r = lecteur.mois("MLP_officiel", "2024-06-01", "2024-07-01")
    assert (len(r["tweets"]), r["fin"]) == (46, "complet")
    assert len(vues) == 5  # une seule page vide demandée après la dernière
    assert "since%3A2024-06-01" in vues[0] and "until%3A2024-07-01" in vues[0]


def test_un_mois_sans_tweet_s_arrete_vite():
    lecteur, vues = _lecteur([])
    r = lecteur.mois("ChudeauR", "2022-01-01", "2022-02-01")
    assert (r["tweets"], r["fin"], len(vues)) == ([], "complet", 2)


def test_des_refus_repetes_arretent_sans_rien_perdre(monkeypatch):
    monkeypatch.setattr(hx, "ATTENTES", (0, 0))
    lecteur = hx.Lecteur("https://instance.test", 0,
                         transport=httpx.MockTransport(lambda req: httpx.Response(429, text="trop")))
    try:
        lecteur.mois("MLP_officiel", "2024-06-01", "2024-07-01")
        raise AssertionError("aurait dû s'arrêter")
    except hx.Arret as exc:
        assert "429" in str(exc)


def test_le_lot_ne_peut_ecrire_que_des_champs_connus_et_les_ecrit_tous():
    from src.services.collection.x_zeeschuimer import CHAMPS_LOT, normaliser_lot
    lot = normaliser_lot([
        {"auteur": "MLP_officiel", "url": "https://x.com/MLP_officiel/status/1", "content": "Un tweet.",
         "published_at": "2024-06-24T07:31:00+00:00", "likes": 3, "personality_id": 999, "id": 5},
        {"auteur": "MLP_officiel", "url": "https://ailleurs.example/1", "content": "Refusé : pas une adresse x.com"},
    ], "xitter")
    ((_, d),) = lot
    assert set(d) == CHAMPS_LOT and d["collected_via"] == "xitter" and d["published_at"].year == 2024


def test_un_tweet_deja_collecte_n_est_pas_importe_deux_fois(tmp_path, monkeypatch):
    from src.config import get_settings
    from src.database import get_engine, get_session_factory, init_db
    from src.models.personality import Personality
    from src.services.collection.x_zeeschuimer import importer_lot, normaliser_lot

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'h.db'}")
    caches = (get_settings, get_engine, get_session_factory)
    for c in caches:
        c.cache_clear()
    brut = [{"auteur": "mlp_officiel", "url": "https://x.com/MLP_officiel/status/1", "content": "Un tweet."},
            {"auteur": "BFMTV", "url": "https://x.com/BFMTV/status/2", "content": "Hors panel."}]

    async def go():
        await init_db()
        async with get_session_factory()() as db:
            db.add(Personality(full_name="Marine Le Pen", handle="MLP_officiel", group_code="RN"))
            await db.commit()
        return (await importer_lot(normaliser_lot(brut, "xitter")),
                await importer_lot(normaliser_lot(brut, "xitter")))

    try:
        premier, second = asyncio.run(go())
    finally:
        for c in caches:
            c.cache_clear()
    assert (premier["nouveaux"], premier["hors_panel"], second["nouveaux"]) == (1, 1, 0)
