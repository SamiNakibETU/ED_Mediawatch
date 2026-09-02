"""Un accord ne se mesure qu'entre codeurs indépendants.

L'état des lieux est écrit dans `cap.py` : α = 0,599, un seul annotateur,
cinquante unités. Ce que cet écran change, ce n'est pas le calcul — il existait
déjà — mais la possibilité d'y mettre autre chose qu'un fichier annoté une fois.

Deux conditions d'indépendance sont testées ici, parce que les violer ne
produit pas une erreur mais un nombre trop beau :

  · le code de la machine ne doit pas être montré avant la décision — le voir
    fait du codeur un relecteur, et l'accord mesure alors la docilité ;
  · les unités ne se choisissent pas selon la réponse de la machine — un
    échantillon trié par confiance flatte ou accable, et l'alpha ne mesure plus
    la grille mais le tri.
"""

import asyncio
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.services.analysis.cap import CAP_VERSION

_CACHES = (get_settings, get_engine, get_session_factory)


def _run(tmp_path, monkeypatch, check):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'cod.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            for i in range(14):
                db.add(Claim(
                    platform="x", speaker_name="Marine Le Pen", party="RN",
                    verbatim=f"déclaration numéro {i}", claim_type="normatif",
                    cap_major=9 if i % 2 else 1, cap_version=f"{CAP_VERSION}/m@t0.0",
                    published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                    confidence=0.7, dedup_key=f"c{i}"))
            await db.commit()

        from src.app import app
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://t") as client:
            await check(client)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_the_machine_code_is_never_shown_before_the_decision(tmp_path, monkeypatch):
    """Le biais d'ancrage suffit à rendre un alpha inutilisable, et il ne laisse
    aucune trace : le codeur croit décider, il confirme."""

    async def check(client):
        d = (await client.get("/codage/suivant", params={"coder": "sami"})).json()
        assert d["claim"], "une unité est proposée"
        assert "cap_major" not in d["claim"] and "code" not in d["claim"]

    _run(tmp_path, monkeypatch, check)


def test_a_coder_never_sees_the_same_unit_twice(tmp_path, monkeypatch):
    """Recoder la même unité gonflerait le compte sans rien ajouter à la
    mesure — et ferait tourner le codeur en rond."""

    async def check(client):
        premier = (await client.get("/codage/suivant", params={"coder": "sami"})).json()["claim"]
        await client.post("/codage", json={"claim_id": premier["id"],
                                           "coder": "sami", "code": 20})
        second = (await client.get("/codage/suivant", params={"coder": "sami"})).json()["claim"]
        assert second["id"] != premier["id"]

    _run(tmp_path, monkeypatch, check)


def test_two_coders_are_independent(tmp_path, monkeypatch):
    """Le second codeur repart de la première unité : sa file n'est pas celle du
    premier. C'est toute la raison d'être de la table."""

    async def check(client):
        a = (await client.get("/codage/suivant", params={"coder": "sami"})).json()["claim"]
        await client.post("/codage", json={"claim_id": a["id"], "coder": "sami", "code": 20})
        b = (await client.get("/codage/suivant", params={"coder": "autre"})).json()["claim"]
        assert b["id"] == a["id"]

    _run(tmp_path, monkeypatch, check)


def test_out_of_scope_is_a_decision_not_a_missing_answer(tmp_path, monkeypatch):
    """« Hors politique publique » se code et compte : une part notable du
    corpus est de l'attaque sans objet d'action publique, et l'écarter du calcul
    ne laisserait que les unités faciles."""

    async def check(client):
        c = (await client.get("/codage/suivant", params={"coder": "sami"})).json()["claim"]
        r = await client.post("/codage", json={"claim_id": c["id"],
                                               "coder": "sami", "code": None})
        assert r.status_code == 200 and r.json()["label"] == "hors politique publique"
        d = (await client.get("/codage/suivant", params={"coder": "sami"})).json()
        assert d["faites"] == 1, "la décision compte comme une unité codée"

    _run(tmp_path, monkeypatch, check)


def test_a_code_outside_the_grid_is_refused(tmp_path, monkeypatch):
    """Les codes 11 et 22 n'existent pas dans la grille — le codebook les laisse
    vides pour préserver la continuité historique depuis 1947. Un code hors
    grille est une faute de saisie, pas un topique inédit."""

    async def check(client):
        c = (await client.get("/codage/suivant", params={"coder": "sami"})).json()["claim"]
        r = await client.post("/codage", json={"claim_id": c["id"],
                                               "coder": "sami", "code": 11})
        assert r.status_code == 400

    _run(tmp_path, monkeypatch, check)


def test_alpha_stays_silent_below_ten_common_units(tmp_path, monkeypatch):
    """Sous une dizaine d'unités communes, un alpha varie de 0,2 d'une unité à
    l'autre. Afficher ce nombre reviendrait à le désavouer la fois suivante."""

    async def check(client):
        for _ in range(3):
            c = (await client.get("/codage/suivant", params={"coder": "sami"})).json()["claim"]
            await client.post("/codage", json={"claim_id": c["id"],
                                               "coder": "sami", "code": 20})
        d = (await client.get("/codage/fiabilite")).json()
        paire = [m for m in d["mesures"] if {"sami", "machine"} == {m["a"], m["b"]}][0]
        assert paire["alpha"] is None
        assert "peu d'unités" in paire["verdict"]

    _run(tmp_path, monkeypatch, check)


def test_a_full_agreement_over_enough_units_is_measured(tmp_path, monkeypatch):
    """Le cas où la mesure existe : douze unités codées comme la machine
    donnent un alpha de 1. Ce n'est pas un résultat à viser — 100 % d'accord
    contre un seul annotateur signale qu'on a appris l'annotateur — mais c'est
    la preuve que la chaîne de mesure fonctionne de bout en bout."""

    async def check(client):
        vus = []
        for _ in range(12):
            c = (await client.get("/codage/suivant", params={"coder": "sami"})).json()["claim"]
            vus.append(c["id"])
            # Même code que la machine : i pair → 1, impair → 9.
            await client.post("/codage", json={
                "claim_id": c["id"], "coder": "sami",
                "code": 1 if (c["id"] - vus[0]) % 2 == 0 else 9})
        d = (await client.get("/codage/fiabilite")).json()
        paire = [m for m in d["mesures"] if {"sami", "machine"} == {m["a"], m["b"]}][0]
        assert paire["n"] == 12
        assert paire["alpha"] == pytest.approx(1.0)
        assert paire["verdict"] == "fiable"

    _run(tmp_path, monkeypatch, check)
