"""La revue de la semaine : ce qu'elle met à la une, et à quoi elle compare la semaine."""

import asyncio
from datetime import datetime, timedelta, timezone

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.declaration import Declaration
from src.models.personality import Personality
from src.models.post import Post
from src.models.sujet_semaine import SujetSemaine
from src.services.analysis.revue import revue

_CACHES = (get_settings, get_engine, get_session_factory)
LUNDI = datetime(2026, 10, 19, tzinfo=timezone.utc)


def _construire(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'r.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await init_db()
        async with get_session_factory()() as db:
            lp = Personality(full_name="Marine Le Pen", handle="MLP_officiel", group_code="RN")
            jb = Personality(full_name="Jordan Bardella", handle="J_Bardella", group_code="RN")
            db.add_all([lp, jb])
            await db.flush()
            n = 0

            def tweet(fig, jour, theme, **kw):
                nonlocal n
                n += 1
                p = Post(personality_id=fig.id, guid=f"g{n}", url=f"https://x.com/{fig.handle}/status/{n}",
                         content=kw.pop("texte", f"Tweet {n} sur un sujet de la semaine."),
                         published_at=LUNDI + timedelta(days=jour, hours=10), theme_ed=theme, **kw)
                db.add(p)
                return p

            # Quatre semaines d'avant : l'immigration fait un quart des tweets.
            for semaine in range(1, 5):
                for k in range(8):
                    tweet(lp if k % 2 else jb, -7 * semaine + k % 5, "cap9" if k < 2 else "cap1")
            # La semaine : l'immigration passe aux trois quarts, et un retweet ne compte pas.
            sujet = [tweet(lp, 1, "cap9", likes=10), tweet(jb, 2, "cap9", likes=900, retweets=50),
                     tweet(jb, 3, "cap9", likes=5)]
            tweet(lp, 4, "cap1")
            rt = tweet(lp, 2, "cap9", is_retweet=True, post_type="retweet", likes=99999)
            rt2 = tweet(jb, 2, "cap9", is_retweet=True, post_type="retweet", texte=rt.content)
            await db.flush()
            db.add(SujetSemaine(semaine="2026-W43", debut=LUNDI, ordre=2, libelle="Un meeting relayé",
                                theme="cap20", n_tweets=2, n_figures=2, post_ids=[rt.id, rt2.id]))
            db.add(SujetSemaine(semaine="2026-W43", debut=LUNDI, ordre=1, libelle="Le projet de loi immigration",
                                theme="cap9", n_tweets=3, n_figures=2, post_ids=[p.id for p in sujet]))
            db.add(Declaration(post_id=sujet[1].id, personality_id=jb.id, published_at=sujet[1].published_at,
                               enjeu="droit_du_sol", position="supprimer", verbatim="x" * 30,
                               cle="d1"))
            db.add(Declaration(post_id=sujet[0].id, personality_id=lp.id, published_at=sujet[0].published_at,
                               enjeu="droit_du_sol", position="supprimer", verbatim="y" * 30,
                               douteuse=True, cle="d2"))
            await db.commit()
            return await revue(db)

    try:
        return asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_la_une_montre_d_abord_les_tweets_les_plus_lus_du_sujet(tmp_path, monkeypatch):
    r = _construire(tmp_path, monkeypatch)
    s = r["une"][0]
    assert s["libelle"] == "Le projet de loi immigration" and s["n_figures"] == 2
    assert s["tweets"][0]["author"] == "J_Bardella"  # 900 j'aime et 50 partages
    assert {v["nom"] for v in s["voix"]} == {"Marine Le Pen", "Jordan Bardella"}


def test_un_retweet_n_est_ni_compte_ni_mis_en_avant(tmp_path, monkeypatch):
    r = _construire(tmp_path, monkeypatch)
    assert (r["volume"]["tweets"], r["volume"]["retweets"], r["volume"]["figures"]) == (4, 2, 2)
    assert (r["une"][0]["n_tweets"], r["une"][0]["n_retweets"]) == (3, 0)
    assert all(p["post_type"] != "retweet" for p in r["plus_vus"])


def test_la_semaine_se_compare_a_la_moyenne_des_quatre_precedentes(tmp_path, monkeypatch):
    r = _construire(tmp_path, monkeypatch)
    imm = next(t for t in r["familles"] if t["code"] == "immigration")
    assert (imm["part"], imm["reference"], imm["ecart"]) == (75.0, 25.0, 50.0)


def test_une_declaration_douteuse_reste_hors_de_la_revue(tmp_path, monkeypatch):
    r = _construire(tmp_path, monkeypatch)
    assert r["declarations"] == 1 and r["enjeux"][0]["figures"] == 1


def test_un_sujet_porte_par_des_relais_montre_une_fois_le_texte_relaye(tmp_path, monkeypatch):
    r = _construire(tmp_path, monkeypatch)
    s = r["une"][1]
    assert (s["n_tweets"], s["n_retweets"]) == (0, 2)
    assert len(s["tweets"]) == 1 and s["tweets"][0]["post_type"] == "retweet"
