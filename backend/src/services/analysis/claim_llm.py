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
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from src.config import get_settings
from src.services.analysis.llm_usage import (
    BudgetExceeded,
    ProviderRefused,
    get_llm_budget,
)

logger = structlog.get_logger(__name__)

# Température du codage thématique : verrouillée, parce qu'un codeur se
# définit par (modèle, consigne, échantillonnage) — sans ça un taux d'accord
# n'est pas reproductible.
from src.services.analysis.cap import CAP_TEMPERATURE


# Un refus du fournisseur se reconnaît à son code : 401 la clé, 402 les crédits,
# 403 l'accès. Aucun des trois ne se répare en réessayant.
_REFUS = {401: "clé refusée", 402: "crédits épuisés", 403: "accès refusé"}


def _refus(exc: Exception) -> str | None:
    """Le motif, si le fournisseur refuse — sinon None (panne passagère)."""
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    try:
        code = int(code)
    except (TypeError, ValueError):
        return None
    motif = _REFUS.get(code)
    return f"le fournisseur de modèles a répondu : {motif}" if motif else None


def _usage_tokens(resp) -> tuple[int, int]:
    """Tokens réels (input, output) d'une réponse OpenAI-compatible ou Anthropic."""
    u = getattr(resp, "usage", None)
    if u is None:
        return 0, 0
    return (
        int(getattr(u, "prompt_tokens", None) or getattr(u, "input_tokens", 0) or 0),
        int(getattr(u, "completion_tokens", None) or getattr(u, "output_tokens", 0) or 0),
    )

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
    "openrouter": "https://openrouter.ai/api/v1",
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


# =========================================================================
# L0 — Extraction GÉNÉRALE de déclarations (Grand Livre exhaustif, tous types)
# =========================================================================

# Version du prompt d'extraction (méthode versionnée, cf specs §7.6). À bumper
# à chaque changement de consigne pour rendre les passes rejouables/traçables.
DECLARATION_PROMPT_VERSION = "decl-v3"  # v3 : locuteur attribué par déclaration
# v2 : stance_target = sujet nommé, requis

# Thèmes de 1er niveau (specs §2.3) — grille fermée pour la classification grossière.
DECLARATION_THEMES = [
    "immigration", "securite", "economie", "pouvoir_achat", "energie",
    "international", "logement", "social", "sante", "institutions",
    "ecologie", "education", "agriculture", "culture_identite", "justice",
]


class Declaration(BaseModel):
    """Une assertion atomique extraite d'une prise de parole (Grand Livre L0)."""

    verbatim: str = Field(
        description="Extrait EXACT du texte source (copie mot pour mot, sous-chaîne)."
    )
    canonical: str = Field(
        description="Reformulation autoportante (coréférences résolues), SANS rien "
        "ajouter d'absent du texte source ni jugement."
    )
    claim_type: Literal[
        "factuel_quantitatif", "factuel_qualitatif", "normatif", "predictif", "attributif"
    ]
    theme: str = Field(description="Un thème de la grille fournie, ou 'autre'.")
    stance_target: str = Field(
        description="LE SUJET PRÉCIS dont parle l'assertion, en 2 à 6 mots, sous "
        "forme de groupe nominal : « l'âge de départ à la retraite », « l'aide "
        "militaire à l'Ukraine », « le nombre d'expulsions annuelles ». TOUJOURS "
        "renseigné, quel que soit le type. Ni le locuteur, ni sa position, ni le "
        "thème général : l'OBJET dont on parle. Deux déclarations sur le même "
        "objet doivent recevoir le même libellé, aussi littéralement que possible."
    )
    stance_polarity: str | None = Field(
        default=None, description="pour|contre|nuance|inconnu"
    )
    check_worthy: bool = Field(
        description="Vrai si l'assertion est analysable/vérifiable (pas une banalité, "
        "salutation, ou pure émotion sans contenu)."
    )
    speaker: str | None = Field(
        default=None,
        description="Nom de la personne à qui le TEXTE attribue explicitement cette "
        "assertion — citation directe, discours rapporté, ou verbe d'attribution "
        "(« X a déclaré », « selon Y », « affirme Z »). Écris le nom tel qu'il "
        "apparaît dans le texte. Laisse null dans TOUS les autres cas : voix du "
        "journaliste, contexte, généralité, ou attribution seulement probable. "
        "Dans le doute, null — une imputation erronée est bien plus grave qu'une "
        "attribution manquante."
    )


class DeclarationSet(BaseModel):
    """Sortie structurée de la segmentation d'une prise de parole."""

    has_declaration: bool = Field(
        description="Faux si le texte ne contient aucune assertion analysable."
    )
    declarations: list[Declaration] = Field(default_factory=list)


_DECL_SYSTEM = (
    "Tu es un analyste du discours politique français, rigoureux et STRICTEMENT "
    "fidèle au texte. On te donne une prise de parole (tweet ou article) d'une "
    "personnalité ; tu la segmentes en assertions atomiques (molecular facts).\n"
    "Règles ABSOLUES :\n"
    "1. `verbatim` = extrait EXACT, copié mot pour mot du texte source (une "
    "sous-chaîne). N'invente, ne paraphrase, ne corrige JAMAIS le verbatim.\n"
    "2. `canonical` = reformulation autoportante neutre ; résous « il/le parti » "
    "SEULEMENT si le locuteur est donné ; n'ajoute AUCUNE information absente.\n"
    "3. Un objet par assertion distincte. Ne découpe pas une idée cohérente en "
    "miettes ; ne fusionne pas deux idées différentes.\n"
    "4. `claim_type` : factuel_quantitatif (chiffre), factuel_qualitatif (fait non "
    "chiffré), normatif (ce qu'il FAUT faire / valeur), predictif (ce qui VA "
    "arriver), attributif (impute une action/responsabilité à un acteur).\n"
    "5. Ignore le bruit (salutations, remerciements, liens, emojis seuls, "
    "banalités sans contenu) → check_worthy=false ou ne pas extraire.\n"
    "6. `theme` depuis la grille fournie uniquement, sinon 'autre'.\n"
    "7. `stance_target` = LE SUJET : un groupe nominal de 2 à 6 mots nommant "
    "l'objet dont parle l'assertion. Toujours renseigné. Emploie le MÊME "
    "libellé pour un même objet d'une déclaration à l'autre : c'est ce qui "
    "permet de confronter des propos entre eux.\n"
    "8. `speaker` = QUI parle. Un article de presse contient plusieurs voix : "
    "celle du journaliste, celles des personnes citées, celles de tiers "
    "commentés. N'attribue une assertion que si le texte le dit lui-même — "
    "citation directe, discours rapporté, verbe d'attribution. Une personne "
    "SIMPLEMENT MENTIONNÉE ou dont on PARLE n'est pas le locuteur. Sinon "
    "null. Dans le doute, null : une imputation erronée, publiée, retourne "
    "l'arme contre l'observatoire, alors qu'une attribution manquante ne coûte "
    "qu'une déclaration inexploitée.\n"
    "Si aucune assertion analysable : has_declaration=false, declarations=[]."
)


# =========================================================================
# L2 — Dossier vivant par personnalité (synthèse RAG, 1 appel par figure)
# =========================================================================

DOSSIER_PROMPT_VERSION = "dossier-v1"


class DossierSynthesis(BaseModel):
    """Synthèse structurée d'une figure, GROUNDED sur ses déclarations fournies."""

    summary: str = Field(
        description="3 à 6 phrases NEUTRES et factuelles résumant ce que la figure "
        "défend, d'après les déclarations fournies UNIQUEMENT. Aucun jugement, "
        "aucune information non présente."
    )
    themes_principaux: list[str] = Field(default_factory=list)
    positions_cles: list[str] = Field(
        default_factory=list,
        description="Positions saillantes, formulées sobrement et attribuables aux déclarations.",
    )
    revirements: list[str] = Field(
        default_factory=list,
        description="Changements de position datés OBSERVÉS dans les déclarations (sinon vide).",
    )
    points_de_vigilance: list[str] = Field(
        default_factory=list,
        description="Incohérences/tensions notables à vérifier (hypothèses prudentes, pas d'accusation).",
    )


_DOSSIER_SYSTEM = (
    "Tu es un analyste politique rigoureux. On te donne les déclarations RÉELLES "
    "(datées, sourcées) d'une figure, extraites d'un corpus de veille. Tu produis "
    "une synthèse NEUTRE, strictement fondée sur ces déclarations.\n"
    "Règles : 1) n'invente RIEN d'absent ; 2) reste factuel et non partisan "
    "(pas d'éditorial) ; 3) un revirement n'est cité que s'il est OBSERVABLE dans "
    "les déclarations datées fournies ; 4) les points de vigilance sont des "
    "hypothèses prudentes à valider par un humain, jamais des accusations ; "
    "5) si le matériau est trop maigre, le dire dans summary et laisser les listes vides."
)


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
        # AVANT le try : BudgetExceeded doit remonter, pas être avalé en fail-open.
        await get_llm_budget().check_or_raise()
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
            tin, tout = _usage_tokens(resp)
            await get_llm_budget().record(
                provider=prov, model=self._s.claim_tier1_model, task="tier1_gate",
                input_tokens=tin, output_tokens=tout,
            )
            ans = (resp.choices[0].message.content or "").strip().lower()
            return "non" not in ans  # fail-open : on ne bloque que sur un NON clair
        except Exception as exc:  # noqa: BLE001
            logger.debug("claim_llm.tier1_fail", error=str(exc)[:120])
            return True  # en cas d'échec, ne pas bloquer

    async def _ask_tier1(self, system: str, user: str, task: str) -> str:
        """Une question courte au modèle bon marché. Rend la réponse brute."""
        prov = self._s.claim_tier1_provider
        client = self._openai.get(prov) if prov != "anthropic" else None
        if client is None:
            return ""
        await get_llm_budget().check_or_raise()
        resp = await client.chat.completions.create(
            model=self._s.claim_tier1_model,
            max_tokens=256,
            temperature=CAP_TEMPERATURE,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        tin, tout = _usage_tokens(resp)
        await get_llm_budget().record(
            provider=prov, model=self._s.claim_tier1_model, task=task,
            input_tokens=tin, output_tokens=tout,
        )
        return (resp.choices[0].message.content or "").strip()

    async def _ask_tier1_garde(self, *args, **kw) -> str:
        """`_ask_tier1`, mais un refus du fournisseur remonte nommé."""
        try:
            return await self._ask_tier1(*args, **kw)
        except Exception as exc:
            motif = _refus(exc)
            if motif:
                raise ProviderRefused(motif) from exc
            raise

    async def code_cap(self, text: str) -> int | None:
        """Range une déclaration dans la grille CAP, en DEUX questions.

        Q1 — cette déclaration porte-t-elle sur un objet d'action publique ?
        Q2 — si oui, lequel des 21 topiques ?

        Pourquoi ne pas poser une seule question. La littérature le mesure : un
        prompt holistique qui demande à la fois « de quoi s'agit-il » et « dans
        quelle catégorie » s'effondre (Fleiss κ = 0,175 sur un corpus politique
        comparable), et c'est la décomposition qui rend l'annotation fiable. Le
        mécanisme s'observait ici même — une question unique laissait le ton
        décider : « untel est un détraqué » était refusé au codage parce que
        violent, alors que la question portait sur l'existence d'un objet.

        Séparer les deux coûte un appel de plus au tier 1, soit environ 20 % —
        et Q1 est courte, elle ne porte pas la grille. Le prix d'une mesure
        fiable, sur une tâche dont tout le reste dépend.

        Rend None quand aucun topique ne s'applique : c'est une DÉCISION, pas un
        échec. Une part notable de ce corpus est de l'attaque et du
        positionnement, sans objet d'action publique.
        """
        from src.services.analysis.cap import (
            CODING_RULE, Q1_SYSTEM, grid_for_prompt, is_valid,
        )

        if not text or not text.strip():
            return None
        extrait = text.strip()[:600]

        try:
            q1 = await self._ask_tier1_garde(
                Q1_SYSTEM, f"Déclaration : {extrait!r}\n\nRéponse :", "cap_q1")
            if "oui" not in q1.lower():
                return None

            q2 = await self._ask_tier1_garde(
                "Tu ranges une déclaration politique dans une grille thématique.\n\n"
                + grid_for_prompt() + "\n\n" + CODING_RULE,
                f"Déclaration : {extrait!r}\n\nCode :", "cap_q2")
            # Le premier entier rencontré, VALIDÉ contre la grille : un code
            # hors grille est une hallucination, pas un topique inédit.
            digits = "".join(c if c.isdigit() else " " for c in q2).split()
            code = int(digits[0]) if digits else None
            return code if is_valid(code) else None
        except ProviderRefused:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("claim_llm.cap_fail", error=str(exc)[:120])
            return None

    async def _tier2_anthropic(
        self, prompt: str, *, schema=RefinedClaim, system: str = _SYSTEM,
        max_tokens: int = 600, task: str = "refine",
    ):
        await get_llm_budget().check_or_raise()
        try:
            resp = await self._anthropic.messages.parse(
                model=self._s.claim_tier2_model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
            tin, tout = _usage_tokens(resp)
            await get_llm_budget().record(
                provider="anthropic", model=self._s.claim_tier2_model, task=task,
                input_tokens=tin, output_tokens=tout,
            )
            return resp.parsed_output
        except Exception as exc:  # noqa: BLE001
            logger.warning("claim_llm.tier2_anthropic_fail", error=str(exc)[:160])
            return None

    async def _tier2_openai(
        self, prov: str, prompt: str, *, schema=RefinedClaim, system: str = _SYSTEM,
        max_tokens: int = 1500, task: str = "refine",
    ):
        client = self._openai[prov]
        model = self._s.claim_tier2_model
        budget = get_llm_budget()
        await budget.check_or_raise()
        # 1) sortie structurée native (json_schema), si le provider/modèle la gère
        try:
            resp = await client.beta.chat.completions.parse(
                model=model, max_tokens=max_tokens, temperature=0,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": prompt}],
                response_format=schema,
            )
            tin, tout = _usage_tokens(resp)
            await budget.record(provider=prov, model=model, task=task,
                                input_tokens=tin, output_tokens=tout)
            parsed = resp.choices[0].message.parsed
            if parsed is not None:
                return parsed
        except Exception as exc:  # noqa: BLE001
            logger.debug("claim_llm.parse_unsupported", prov=prov, error=str(exc)[:120])

        # 2) repli : mode json_object + validation Pydantic manuelle
        await budget.check_or_raise()
        try:
            schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
            resp = await client.chat.completions.create(
                model=model, max_tokens=max_tokens, temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content":
                        prompt + "\n\nRéponds UNIQUEMENT par un JSON valide conforme à ce schéma "
                        f"(mêmes clés) :\n{schema_json}"},
                ],
            )
            tin, tout = _usage_tokens(resp)
            await budget.record(provider=prov, model=model, task=task,
                                input_tokens=tin, output_tokens=tout)
            content = resp.choices[0].message.content or ""
            return schema.model_validate_json(content)
        except Exception as exc:  # noqa: BLE001
            if _refus(exc):
                raise ProviderRefused(_refus(exc)) from exc
            logger.warning("claim_llm.tier2_openai_fail", prov=prov, error=str(exc)[:160])
            return None

    async def segment_declarations(
        self, *, text: str, speaker: str | None,
        themes: list[str] | None = None, known: list[str] | None = None,
    ) -> DeclarationSet | None:
        """L0 — segmente une prise de parole en déclarations atomiques (tous types).

        Sortie structurée + fidèle au verbatim. None si LLM indisponible/échec
        (le substrat ne se peuple alors pas — pas de déclaration inventée)."""
        if not text or not text.strip():
            return None
        grid = ", ".join(themes or DECLARATION_THEMES)
        # `speaker` connu (un post X : le compte EST l'auteur) → on le donne et
        # l'attribution ne se discute pas. Sinon (un article), c'est au modèle de
        # dire qui parle, assertion par assertion, et seulement quand le texte le
        # dit. `known` liste les figures suivies repérées dans l'article : un
        # contexte pour orthographier un nom, pas une réponse à recopier.
        if speaker:
            entete = f"Locuteur : {speaker} (auteur du texte — toutes les assertions lui reviennent)\n"
        else:
            entete = (
                "Locuteur : NON DONNÉ. Ce texte est un article : il contient la voix du "
                "journaliste et celles des personnes citées. Renseigne `speaker` "
                "assertion par assertion, uniquement quand le texte l'attribue "
                "explicitement ; sinon null.\n"
            )
            if known:
                entete += f"Figures suivies mentionnées : {', '.join(known)}\n"
        prompt = (
            entete
            + f"Grille de thèmes : {grid}\n\n"
            f"Prise de parole (texte source EXACT) :\n«««\n{text.strip()[:6000]}\n»»»\n\n"
            "Tâche : segmente en assertions atomiques selon les règles. Pour chacune : "
            "verbatim EXACT, canonical fidèle, claim_type, theme, stance, check_worthy, speaker."
        )
        prov = self._s.claim_tier2_provider
        if prov == "anthropic" and self._anthropic is not None:
            return await self._tier2_anthropic(
                prompt, schema=DeclarationSet, system=_DECL_SYSTEM, max_tokens=3000,
                task="l0_segment",
            )
        if prov in self._openai:
            return await self._tier2_openai(
                prov, prompt, schema=DeclarationSet, system=_DECL_SYSTEM,
                max_tokens=4000, task="l0_segment",
            )
        return None

    async def synthesize_dossier(
        self, *, speaker: str, party: str | None, facts: str
    ) -> DossierSynthesis | None:
        """L2 — synthèse d'une figure à partir d'un contexte BORNÉ de déclarations
        (RAG). Un seul appel LLM par figure. None si LLM indisponible/échec."""
        if not facts.strip():
            return None
        prompt = (
            f"Figure : {speaker}" + (f" ({party})" if party else "") + "\n\n"
            f"Déclarations réelles (datées, échantillon borné) :\n{facts}\n\n"
            "Tâche : produis la synthèse structurée (summary neutre, thèmes, positions, "
            "revirements observés, points de vigilance prudents), fondée UNIQUEMENT sur "
            "ces déclarations."
        )
        prov = self._s.claim_tier2_provider
        if prov == "anthropic" and self._anthropic is not None:
            return await self._tier2_anthropic(
                prompt, schema=DossierSynthesis, system=_DOSSIER_SYSTEM,
                max_tokens=1500, task="dossier",
            )
        if prov in self._openai:
            return await self._tier2_openai(
                prov, prompt, schema=DossierSynthesis, system=_DOSSIER_SYSTEM,
                max_tokens=2000, task="dossier",
            )
        return None

    async def label_subject(self, prompt: str, system: str):
        """Nomme un groupe de déclarations (cf. subject_labeller). Import tardif
        pour éviter le cycle : ce module y est importé."""
        from src.services.analysis.subject_labeller import SubjectLabel

        prov = self._s.claim_tier2_provider
        if prov == "anthropic" and self._anthropic is not None:
            return await self._tier2_anthropic(
                prompt, schema=SubjectLabel, system=system, max_tokens=300,
                task="subject_label",
            )
        if prov in self._openai:
            return await self._tier2_openai(
                prov, prompt, schema=SubjectLabel, system=system, max_tokens=400,
                task="subject_label",
            )
        return None

    async def read_pledge(self, *, verbatim: str, canonical: str | None = None):
        """Lit un engagement dans une déclaration, en DEUX questions.

        Q1 au tier 1 — le locuteur engage-t-il SA propre action ? Elle écarte à
        bas prix les injonctions adressées à d'autres et les jugements, qui
        forment l'essentiel des propos normatifs.

        Q2 au tier 2 — qu'observerait-on pour dire que c'est tenu ? C'est le
        filtre de vérifiabilité du Polimètre, et il demande de comprendre la
        phrase, pas de la classer.
        """
        from src.services.analysis.pledges import (
            EngagementLu, Q1_SYSTEM as _Q1, Q2_SYSTEM as _Q2,
        )

        # Le modèle voit les deux : la reformulation lève les « nous » et les
        # « il » — sans quoi il ne peut pas dire QUI s'engage — mais le fragment
        # se recopie dans le texte original, seul endroit où les mots sont ceux
        # du locuteur.
        brut = (verbatim or "").strip()[:800]
        reformule = (canonical or "").strip()[:800]
        extrait = reformule or brut
        try:
            q1 = await self._ask_tier1_garde(
                _Q1, f"Déclaration : {extrait!r}\n\nRéponse :", "engagement_q1")
        except BudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("claim_llm.pledge_q1_fail", error=str(exc)[:120])
            return None
        if "oui" not in q1.lower():
            return None

        prompt = (f"Texte original, seul endroit où recopier le fragment :\n"
                  f"«««\n{brut}\n»»»"
                  + (f"\n\nReformulation, pour comprendre qui s'engage :\n{reformule}"
                     if reformule and reformule != brut else ""))
        prov = self._s.claim_tier2_provider
        if prov == "anthropic" and self._anthropic is not None:
            return await self._tier2_anthropic(
                prompt, schema=EngagementLu, system=_Q2, max_tokens=400,
                task="engagement_q2")
        if prov in self._openai:
            return await self._tier2_openai(
                prov, prompt, schema=EngagementLu, system=_Q2, max_tokens=500,
                task="engagement_q2")
        return None

    async def write_review(self, *, prompt: str, system: str):
        """Écrit la revue d'un sujet sur une période (cf. `review.py`).

        Import tardif : `review` importe ce module. Le schéma impose des
        paragraphes CITANTS — c'est la relecture, côté appelant, qui écarte
        ceux qui ne le sont pas."""
        from src.services.analysis.review import RevueEcrite

        prov = self._s.claim_tier2_provider
        if prov == "anthropic" and self._anthropic is not None:
            return await self._tier2_anthropic(
                prompt, schema=RevueEcrite, system=system, max_tokens=1800,
                task="revue",
            )
        if prov in self._openai:
            return await self._tier2_openai(
                prov, prompt, schema=RevueEcrite, system=system, max_tokens=2200,
                task="revue",
            )
        return None

    async def judge_contradiction(self, prompt: str, system: str | None = None):
        """A4 — verdict structuré sur une paire de déclarations (juge sémantique).

        Le schéma et la consigne vivent dans `contradiction_judge` (import tardif :
        ce module y importe déjà `get_claim_llm`, on évite le cycle). None si LLM
        indisponible/échec — aucune arête n'est alors créée."""
        from src.services.analysis.contradiction_judge import (
            ContradictionVerdict,
            _JUDGE_SYSTEM,
        )
        from src.services.analysis.learning import judge_system_prompt

        # Consigne : doctrine posée puis décisions humaines. `system` explicite
        # n'est utilisé que par l'évaluation, qui doit pouvoir retirer les cas
        # d'école pour ne pas corriger la copie avec le corrigé posé dessus.
        if system is None:
            system = await judge_system_prompt(_JUDGE_SYSTEM)
        prov = self._s.claim_tier2_provider
        if prov == "anthropic" and self._anthropic is not None:
            return await self._tier2_anthropic(
                prompt, schema=ContradictionVerdict, system=system,
                max_tokens=800, task="judge",
            )
        if prov in self._openai:
            return await self._tier2_openai(
                prov, prompt, schema=ContradictionVerdict, system=system,
                max_tokens=1000, task="judge",
            )
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
