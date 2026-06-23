"""Raffinage LLM des claims quantitatifs (tier-1 open + tier-2 fidélité).

Le détecteur déterministe sort des *candidats* (peu nombreux). Ce service les
fiabilise :
  * **Tier-1** (Groq/Cerebras/Mistral, OpenAI-compatible) : filtre binaire pas
    cher — la phrase affirme-t-elle vraiment ce référent ? Élimine les faux positifs.
  * **Tier-2** (Anthropic Claude Haiku — fidélité maximale, sortie structurée) :
    canonicalise (coréférence résolue, RIEN d'inventé), confirme/réassigne le
    referent_key dans la grille fermée, extrait horizon/modalité/stance + confiance.

Provider-agnostic et opt-in (`LLM_REFINE_ENABLED`). Sans clé → inactif (on garde
les claims déterministes tels quels). Repris dans l'esprit du llm_router PMO.
"""

from __future__ import annotations

import json

import structlog
from pydantic import BaseModel, Field

from src.config import get_settings

logger = structlog.get_logger(__name__)

# Imports optionnels (le déterministe doit marcher sans ces libs).
try:
    from anthropic import AsyncAnthropic
except Exception:  # noqa: BLE001
    AsyncAnthropic = None
try:
    from openai import AsyncOpenAI
except Exception:  # noqa: BLE001
    AsyncOpenAI = None

_OPENAI_BASE = {
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "mistral": "https://api.mistral.ai/v1",
}


class RefinedClaim(BaseModel):
    """Sortie structurée du tier-2."""

    is_valid_claim: bool = Field(
        description="La phrase affirme-t-elle réellement une valeur pour ce référent ?"
    )
    referent_key: str = Field(
        description="Clé du référent confirmée ou réassignée depuis la liste fournie, ou 'none'."
    )
    canonical: str = Field(
        description="Reformulation autoportante, coréférences résolues, SANS rien ajouter d'absent du texte."
    )
    value: float | None = None
    unit: str | None = None
    horizon: str | None = Field(default=None, description="annuel|total|a_horizon_2027|inconnu")
    modality: str | None = Field(default=None, description="affirme|estime|promet|inconnu")
    stance: str | None = Field(default=None, description="pour|contre|nuance|inconnu")
    confidence: float = Field(ge=0.0, le=1.0)


_SYSTEM = (
    "Tu es un assistant d'analyse du discours politique français, rigoureux et "
    "fidèle au texte. Règles strictes :\n"
    "1. N'invente JAMAIS d'information absente du texte source.\n"
    "2. Résous les coréférences (« il », « le parti ») uniquement si le locuteur est donné.\n"
    "3. `referent_key` doit appartenir à la grille fournie, sinon 'none'.\n"
    "4. Si la phrase n'affirme pas réellement la valeur chiffrée du référent "
    "(nombre hors sujet, citation rapportée non chiffrée, contexte différent), "
    "mets is_valid_claim=false.\n"
    "5. `canonical` = reformulation autoportante et neutre, sans ajout ni jugement.\n\n"
    "Exemples :\n"
    "- Texte « Le RN promet de ramener la retraite à 60 ans » + référent age_legal_cible "
    "→ is_valid_claim=true, value=60, modality=promet, canonical=\"Le RN promet l'âge légal "
    "de départ à la retraite à 60 ans.\"\n"
    "- Texte « 35 000 personnes ont manifesté contre le RN » + référent expulsions "
    "→ is_valid_claim=false (le nombre ne concerne pas le référent)."
)


class ClaimLLM:
    def __init__(self) -> None:
        s = get_settings()
        self._s = s
        self._anthropic = None
        self._openai: dict[str, object] = {}

        if s.anthropic_api_key and AsyncAnthropic is not None:
            self._anthropic = AsyncAnthropic(api_key=s.anthropic_api_key)
        if AsyncOpenAI is not None:
            for prov, base in _OPENAI_BASE.items():
                key = getattr(s, f"{prov}_api_key", "")
                if key:
                    self._openai[prov] = AsyncOpenAI(api_key=key, base_url=base)

    def available(self) -> bool:
        """Le tier-2 (canonicalisation) est-il disponible ?"""
        prov = self._s.claim_tier2_provider
        if prov == "anthropic":
            return self._anthropic is not None
        return prov in self._openai

    async def _tier1_gate(self, sentence: str, referent_label: str) -> bool:
        prov = self._s.claim_tier1_provider
        client = self._openai.get(prov) if prov != "anthropic" else None
        if client is None:
            return True  # pas de gate dispo → on laisse passer vers le tier-2
        try:
            resp = await client.chat.completions.create(
                model=self._s.claim_tier1_model,
                max_tokens=256,  # marge pour les modèles à raisonnement (gpt-oss)
                temperature=0,
                messages=[
                    {"role": "system", "content":
                        "Tu réponds par un seul mot : OUI ou NON."},
                    {"role": "user", "content":
                        f"La phrase suivante affirme-t-elle une valeur chiffrée pour « {referent_label} » ? "
                        f"Phrase : {sentence!r}"},
                ],
            )
            ans = (resp.choices[0].message.content or "").strip().lower()
            return "non" not in ans  # fail-open : on ne bloque que sur un NON clair
        except Exception as exc:  # noqa: BLE001
            logger.debug("claim_llm.tier1_fail", error=str(exc)[:120])
            return True  # en cas d'échec, ne pas bloquer

    async def _tier2_anthropic(self, prompt: str) -> RefinedClaim | None:
        try:
            resp = await self._anthropic.messages.parse(
                model=self._s.claim_tier2_model,
                max_tokens=600,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                output_format=RefinedClaim,
            )
            return resp.parsed_output
        except Exception as exc:  # noqa: BLE001
            logger.warning("claim_llm.tier2_anthropic_fail", error=str(exc)[:160])
            return None

    async def _tier2_openai(self, prov: str, prompt: str) -> RefinedClaim | None:
        client = self._openai[prov]
        model = self._s.claim_tier2_model
        # 1) sortie structurée native (json_schema), si le provider/modèle la gère
        try:
            resp = await client.beta.chat.completions.parse(
                model=model, max_tokens=1500, temperature=0,
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": prompt}],
                response_format=RefinedClaim,
            )
            parsed = resp.choices[0].message.parsed
            if parsed is not None:
                return parsed
        except Exception as exc:  # noqa: BLE001
            logger.debug("claim_llm.parse_unsupported", prov=prov, error=str(exc)[:120])

        # 2) repli : mode json_object + validation Pydantic manuelle
        try:
            schema = json.dumps(RefinedClaim.model_json_schema(), ensure_ascii=False)
            resp = await client.chat.completions.create(
                model=model, max_tokens=1500, temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content":
                        prompt + "\n\nRéponds UNIQUEMENT par un JSON valide conforme à ce schéma "
                        f"(mêmes clés) :\n{schema}"},
                ],
            )
            content = resp.choices[0].message.content or ""
            return RefinedClaim.model_validate_json(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("claim_llm.tier2_openai_fail", prov=prov, error=str(exc)[:160])
            return None

    async def refine(
        self,
        *,
        sentence: str,
        speaker: str | None,
        candidate_referent_key: str,
        referent_label: str,
        value: float,
        unit: str,
        allowed: list[tuple[str, str]],
    ) -> RefinedClaim | None:
        """Valide + canonicalise un candidat quantitatif. None si rejeté/échec."""
        if not await self._tier1_gate(sentence, referent_label):
            return RefinedClaim(
                is_valid_claim=False, referent_key="none", canonical="",
                confidence=0.0,
            )

        grid = "\n".join(f"- {k} : {label}" for k, label in allowed)
        prompt = (
            f"Locuteur : {speaker or 'inconnu'}\n"
            f"Phrase source (verbatim) : {sentence!r}\n\n"
            f"Candidat détecté : référent={candidate_referent_key} "
            f"(« {referent_label} »), valeur={value} {unit}.\n\n"
            f"Grille fermée des référents possibles :\n{grid}\n\n"
            "Tâche : confirme ou corrige le référent (depuis la grille uniquement, "
            "ou 'none' si aucun ne convient), reformule l'assertion de façon "
            "autoportante sans rien ajouter, extrais valeur/unité/horizon/modalité/"
            "stance, et donne une confiance [0,1]."
        )

        prov = self._s.claim_tier2_provider
        if prov == "anthropic" and self._anthropic is not None:
            return await self._tier2_anthropic(prompt)
        if prov in self._openai:
            return await self._tier2_openai(prov, prompt)
        return None


_client: ClaimLLM | None = None


def get_claim_llm() -> ClaimLLM:
    global _client
    if _client is None:
        _client = ClaimLLM()
    return _client
