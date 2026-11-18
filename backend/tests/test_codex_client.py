"""La lecture par l'abonnement ChatGPT (Codex CLI) se branche comme un fournisseur.

Sans appeler Codex : on remplace `codex_client.demander` et on vérifie le trajet,
le refus de quota, le coût nul et les lots plus gros.
"""

import asyncio

import pytest
from pydantic import BaseModel

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.services.analysis import codex_client
from src.services.analysis.llm_usage import FREE_PROVIDERS, ProviderRefused

_CACHES = (get_settings, get_engine, get_session_factory)


class R(BaseModel):
    rang: int


def _env(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'c.db'}")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for c in _CACHES:
        c.cache_clear()
    import src.services.analysis.llm_usage as u
    monkeypatch.setattr(u, "_budget", None, raising=False)


def test_tokens_et_consigne():
    assert codex_client.tokens_de("tokens used\n22 114\n") == 22114
    assert codex_client.tokens_de("rien") == 0
    c = codex_client.consigne("SYSTEME", "TWEETS")
    assert c.index("SYSTEME") < c.index("TWEETS") and "JSON" in c


def test_codex_est_gratuit():
    assert "codex" in FREE_PROVIDERS


def test_ask_json_passe_par_codex(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, CLAIM_TIER2_PROVIDER="codex", OPENROUTER_API_KEY="")
    vus = {}

    async def faux(system, prompt, *, model, effort, timeout, codex):
        vus.update(model=model, system=system)
        return codex_client.Reponse(texte='voici {"rang": 2}', tokens=21000)

    monkeypatch.setattr(codex_client, "demander", faux)

    async def go():
        await init_db()
        from src.services.analysis.claim_llm import ClaimLLM
        llm = ClaimLLM()
        r1 = await llm.ask_json(tier=2, system="S", prompt="P", schema=R, task="t")
        # le second juge demande un modèle d'OpenRouter : sans clé, un autre modèle de l'abonnement
        m1 = vus["model"]
        r2 = await llm.ask_json(tier=2, system="S", prompt="P", schema=R, task="t", model="google/gemini-3.7-flash")
        return r1, r2, m1, vus["model"]

    r1, r2, m1, m2 = asyncio.run(go())
    s = get_settings()
    assert r1.rang == 2 and r2.rang == 2
    assert m1 == s.codex_model and m2 == s.codex_juge2_model


def test_quota_arrete_la_passe(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, CLAIM_TIER2_PROVIDER="codex")

    async def plein(*a, **k):
        raise codex_client.CodexRefus("Codex refuse : usage limit reached")

    monkeypatch.setattr(codex_client, "demander", plein)

    async def go():
        await init_db()
        from src.services.analysis.claim_llm import ClaimLLM
        await ClaimLLM().ask_json(tier=2, system="S", prompt="P", schema=R, task="t")

    with pytest.raises(ProviderRefused):
        asyncio.run(go())


def test_lots_plus_gros_par_codex(tmp_path, monkeypatch):
    from src.services.analysis.registre import LOT_EXTRACTION, LOT_FILTRE, tailles_de_lot

    _env(tmp_path, monkeypatch, CLAIM_TIER1_PROVIDER="openrouter", CLAIM_TIER2_PROVIDER="openrouter")
    assert tailles_de_lot() == (LOT_FILTRE, LOT_EXTRACTION)
    _env(tmp_path, monkeypatch, CLAIM_TIER1_PROVIDER="codex", CLAIM_TIER2_PROVIDER="codex")
    assert tailles_de_lot() == (codex_client.LOTS["filtre"], codex_client.LOTS["extraction"])
