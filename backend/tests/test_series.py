"""Une série temporelle ne saute pas les mois vides.

C'est le défaut le plus courant des graphiques faits à partir d'un GROUP BY, et
le plus difficile à repérer : la page reste belle, l'axe reste lisible, et deux
barres voisines qui sont à six mois d'écart se lisent comme deux mois qui se
suivent. Un observatoire qui affiche « il parlait autant en mars qu'en
septembre » alors qu'il s'est tu entre les deux a menti sans qu'aucune erreur
n'apparaisse nulle part.

Un mois de silence est une information, pas un trou dans les données.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import or_

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.contradiction import Contradiction
from src.models.personality import Personality
from src.routers.series import _combler, _serie, _veille_depuis

_CACHES = (get_settings, get_engine, get_session_factory)


def test_the_empty_months_are_in_the_series():
    """Janvier et avril consignés : février et mars valent zéro, pas rien."""
    points = _combler({"2026-01": {"mois": "2026-01", "n": 4, "contradictions": 0},
                       "2026-04": {"mois": "2026-04", "n": 2, "contradictions": 0}},
                      "2026-01", "2026-04")
    assert [p["mois"] for p in points] == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert [p["n"] for p in points] == [4, 0, 0, 2]


def test_the_series_crosses_the_new_year():
    """Le passage de décembre à janvier est l'endroit où une boucle sur les mois
    se casse ; celui-ci compte 14 mois, pas 2."""
    points = _combler({"2025-12": {"mois": "2025-12", "n": 1, "contradictions": 0}},
                      "2025-12", "2027-01")
    assert len(points) == 14
    assert points[1]["mois"] == "2026-01"
    assert points[-1]["mois"] == "2027-01"


def _run(tmp_path, monkeypatch, check):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'ser.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            p = Personality(full_name="Marine Le Pen", handle="MLP_officiel",
                            group_code="RN", is_active=True)
            db.add(p)
            await db.commit()
            await db.refresh(p)
            # Trois mois de prise de parole, un trou de deux mois au milieu.
            quand = {"2026-01": 2, "2026-04": 1, "2026-05": 3}
            ids = []
            for mois, n in quand.items():
                an, m = (int(x) for x in mois.split("-"))
                for i in range(n):
                    c = Claim(platform="x", personality_id=p.id,
                              speaker_name="Marine Le Pen", verbatim=f"{mois}-{i}",
                              claim_type="normatif", confidence=0.7,
                              dedup_key=f"{mois}-{i}",
                              published_at=datetime(an, m, 10, tzinfo=timezone.utc))
                    db.add(c)
                    await db.flush()
                    ids.append(c.id)
            # Un revirement entre janvier et mai : les deux bouts sont marqués.
            db.add(Contradiction(claim_a_id=ids[0], claim_b_id=ids[-1], type=1,
                                 score=0.8, status="pending"))
            await db.commit()
            pid = p.id
        async with factory() as db:
            await check(db, pid)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_a_speakers_series_counts_months_and_flags_the_turnaround(tmp_path, monkeypatch):
    async def check(db, pid):
        d = await _serie(db, ids_claims_filter=(
            or_(Claim.personality_id == pid, Claim.speaker_name == "Marine Le Pen"),))
        assert d["total"] == 6
        assert [(p["mois"], p["n"]) for p in d["points"]] == [
            ("2026-01", 2), ("2026-02", 0), ("2026-03", 0),
            ("2026-04", 1), ("2026-05", 3)]
        # Le rapprochement se lit aux deux bouts : c'est un lien entre deux
        # dates, pas un événement d'un seul mois.
        marques = {p["mois"]: p["contradictions"] for p in d["points"]}
        assert marques["2026-01"] == 1 and marques["2026-05"] == 1
        assert marques["2026-04"] == 0

    _run(tmp_path, monkeypatch, check)


def test_an_unattributed_claim_never_enters_a_speakers_series(tmp_path, monkeypatch):
    """Sans auteur, il n'y a rien à imputer — la même règle qu'en une."""
    async def check(db, pid):
        db.add(Claim(platform="presse", verbatim="propos sans auteur",
                     claim_type="normatif", confidence=0.7, dedup_key="orphelin",
                     published_at=datetime(2026, 2, 1, tzinfo=timezone.utc)))
        await db.commit()
        d = await _serie(db, ids_claims_filter=(
            or_(Claim.personality_id == pid, Claim.speaker_name == "Marine Le Pen"),))
        assert d["total"] == 6
        assert next(p for p in d["points"] if p["mois"] == "2026-02")["n"] == 0

    _run(tmp_path, monkeypatch, check)


def test_an_empty_series_says_so_rather_than_inventing_a_range(tmp_path, monkeypatch):
    """Aucune déclaration : pas de points, et surtout pas un axe de douze mois à
    zéro qui donnerait l'impression d'un suivi qui n'a pas eu lieu."""
    async def check(db, pid):
        d = await _serie(db, ids_claims_filter=(Claim.speaker_name == "Personne",))
        assert d == {"points": [], "total": 0, "veille_depuis": None}

    _run(tmp_path, monkeypatch, check)


# ── Depuis quand on regarde ────────────────────────────────────────────────
# Mesuré le 03/09/2026 sur le corpus réel : mars 2026 comptait 9 publications,
# août 2026 en comptait 2 097. Ce n'est pas une explosion du discours, c'est le
# début de la veille. Le graphique devait pouvoir faire la différence, sans
# quoi il aurait publié la montée en charge de l'outil comme un résultat.

def _pt(mois, n, retro):
    return {"mois": mois, "n": n, "retro": retro, "contradictions": 0}


def test_the_watch_starts_where_the_backfill_stops():
    points = [_pt("2026-06", 255, 255), _pt("2026-07", 341, 259),
              _pt("2026-08", 2097, 0), _pt("2026-09", 520, 0)]
    assert _veille_depuis(points) == "2026-08"


def test_an_empty_month_does_not_backdate_the_watch():
    """Sans une seule donnée, un mois ne prouve pas qu'on regardait. Le faire
    compter comme surveillé ferait remonter la date d'un mois, gratuitement."""
    points = [_pt("2026-01", 9, 9), _pt("2026-02", 0, 0), _pt("2026-03", 100, 0)]
    assert _veille_depuis(points) == "2026-03"


def test_a_corpus_entirely_rebuilt_afterwards_claims_no_watch():
    """Tout rattrapé : aucune date de début, et donc aucune tendance à lire."""
    assert _veille_depuis([_pt("2026-01", 9, 9), _pt("2026-02", 40, 40)]) is None


def test_the_months_before_the_watch_are_marked_as_rebuilt(tmp_path, monkeypatch):
    """Le compte d'un mois rattrapé est un plancher : il doit arriver en façade
    marqué comme tel, pas nu."""
    async def check(db, pid):
        d = await _serie(db, ids_claims_filter=(
            or_(Claim.personality_id == pid, Claim.speaker_name == "Marine Le Pen"),))
        # Les déclarations du test n'ont pas de source (ni post ni article) :
        # sans date de collecte, on ne PRÉTEND PAS qu'elles ont été rattrapées.
        # L'inconnu n'est pas le rétrospectif — la même règle que pour le codage.
        assert all(p["retro"] == 0 for p in d["points"])
        assert d["veille_depuis"] == "2026-01"

    _run(tmp_path, monkeypatch, check)
