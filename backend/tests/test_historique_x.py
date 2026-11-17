"""Historique X par une instance Nitter : lecture des pages, fin de pagination, import."""

import asyncio

import httpx
import pytest

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


def test_un_defi_arrete_tout_de_suite_meme_derriere_un_403(monkeypatch):
    # 1/11/2026 : la case Turnstile de xitter.cf passait pour un 403, avec 18 minutes d'attente pour rien.
    vues = []

    def repondre(req):
        vues.append(req)
        return httpx.Response(403, text='<h1>Confirm this search</h1><div class="cf-turnstile"></div>')
    lecteur = hx.Lecteur("https://instance.test", 0, transport=httpx.MockTransport(repondre))
    monkeypatch.setattr(hx.time, "sleep", lambda s: pytest.fail("aucune attente devant un défi"))
    with pytest.raises(hx.Arret, match="défi anti-robot"):
        lecteur.mois("MLP_officiel", "2024-06-01", "2024-07-01")
    assert len(vues) == 1


def test_un_tweet_qui_parle_de_turnstile_n_est_pas_un_defi():
    lecteur, _ = _lecteur([_page([_item("MLP_officiel", "1", "Cloudflare Turnstile, just a moment")], suite=False)])
    r = lecteur.mois("MLP_officiel", "2024-06-01", "2024-07-01")
    assert len(r["tweets"]) == 1


def test_le_controle_refuse_une_instance_qui_ne_pagine_pas():
    # 2/11/2026 : nitter.mie.foundation rendait la première page, puis plus rien.
    lecteur, vues = _lecteur([_pleine(0)])
    with pytest.raises(hx.Arret, match="pagination"):
        lecteur.controle()
    assert len(vues) == 4


def test_le_controle_accepte_une_instance_qui_pagine_meme_avec_une_page_vide():
    lecteur, vues = _lecteur([_pleine(0), _page([]), _pleine(20)])
    lecteur.controle()
    assert len(vues) == 3 and "MLP_officiel" in vues[0]


def test_un_mois_dense_sans_ses_premiers_jours_est_tronque():
    tous = [{"published_at": f"2026-08-01 09:{i:02d}:00+00:00"} for i in range(20)]
    assert hx.tronque(tous, "2026-07-01")
    assert not hx.tronque(tous, "2026-08-01")
    assert not hx.tronque(tous[:5], "2026-07-01")  # compte peu actif : rien à conclure


def test_un_mois_tronque_n_est_pas_fait_et_la_copie_locale_ne_le_rend_pas_complet(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(hx, "DOSSIER", tmp_path)
    assert "tronqué" not in hx.FAITS
    lignes = [{"auteur": "a", "url": f"https://x.com/a/status/{i}", "mois": "2026-07"} for i in range(3)]
    (tmp_path / "a.ndjson").write_text("\n".join(json.dumps(t) for t in lignes) + "\n", encoding="utf-8")
    etat = {"a": {"2026-07": {"n": 2, "fin": "tronqué", "envoye": False}}}
    hx.reparer(etat)
    assert etat["a"]["2026-07"]["fin"] == "tronqué"


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


def test_la_copie_locale_fait_foi_quand_l_etat_a_oublie_des_tweets(tmp_path, monkeypatch):
    # 27/10/2026 : mai 2022 de Le Pen revenu vide d'une relecture, noté vide et complet.
    import json
    monkeypatch.setattr(hx, "DOSSIER", tmp_path)
    lignes = [{"auteur": "MLP_officiel", "url": f"https://x.com/MLP_officiel/status/{i}", "mois": "2022-05"}
              for i in (1, 2, 2)]  # le tweet 2 relu deux fois
    (tmp_path / "MLP_officiel.ndjson").write_text("\n".join(json.dumps(t) for t in lignes) + "\n", encoding="utf-8")
    etat = {"MLP_officiel": {"2022-05": {"n": 0, "fin": "complet", "envoye": True}}}
    hx.reparer(etat)
    assert etat["MLP_officiel"]["2022-05"] == {"n": 2, "fin": "complet", "envoye": False}
    assert len(hx.archive("MLP_officiel")["2022-05"]) == 2


def test_un_mois_vide_n_est_tenu_pour_vide_qu_a_la_seconde_relance(tmp_path, monkeypatch):
    # 28/10/2026 : juillet 2022 de Chudeau noté vide et complet, 43 tweets à la relecture.
    monkeypatch.setattr(hx, "DOSSIER", tmp_path)
    etat = {"ChudeauR": {"2022-07": {"n": 0, "fin": "complet", "envoye": True},
                         "2022-06": {"n": 100, "fin": "complet", "envoye": False}}}
    hx.reparer(etat)
    assert etat["ChudeauR"]["2022-07"]["fin"] == "vide"
    assert etat["ChudeauR"]["2022-06"]["fin"] == "complet"
    assert hx.fin_vide(etat["ChudeauR"]["2022-07"]) == "vide confirmé"
    assert hx.fin_vide({}) == "vide"
    assert "vide" not in hx.FAITS and "vide confirmé" in hx.FAITS


def test_dans_un_fil_chaque_reponse_repond_a_celle_d_avant():
    from src.services.collection.x_html_parser import lire_page_statut
    html = ("<html><body><div class='main-tweet'>" + _item("MLP_officiel", "100", "Le tweet.") + "</div>"
            "<div class='replies'>"
            "<div class='reply thread thread-line'>" + _item("Alice", "101", "Réponse directe.")
            + _item("Bob", "102", "Réponse à Alice.") + "</div>"
            "<div class='reply thread thread-line'>" + _item("Carla", "103", "Autre réponse directe.") + "</div>"
            "<div class='show-more'><a href='/MLP_officiel/status/100?cursor=X'>Load more</a></div>"
            "</div></body></html>")
    p = lire_page_statut(html)
    assert p["principal"][1]["id"] == "100" and p["suite"].endswith("cursor=X")
    parents = {d["id"]: d["parent_id"] for _, d in p["reponses"]}
    assert parents == {"101": "100", "102": "101", "103": "100"}


def test_un_profil_donne_les_compteurs_exacts_et_la_date_de_creation():
    from src.services.collection.x_html_parser import lire_profil
    html = ("<div class='profile-card'><a class='profile-card-fullname'>Jean-Luc Mélenchon</a>"
            "<a class='profile-card-username'>@JLMelenchon</a><div class='profile-bio'><p>Candidat.</p></div>"
            "<div class='profile-joindate'><span title='10:50 AM - 8 Oct 2009'>Joined October 2009</span></div>"
            "<ul class='profile-statlist'>"
            "<li class='posts'><span class='profile-stat-num' title='55,936'>55.9K</span></li>"
            "<li class='followers'><span class='profile-stat-num' title='2,720,215'>2.7M</span></li></ul></div>")
    p = lire_profil(html)
    assert (p["handle"], p["abonnes"], p["tweets"], p["cree_le"]) == ("JLMelenchon", 2720215, 55936, "10:50 AM - 8 Oct 2009")
