"""Regroupement des déclarations en SUJETS — la brique qui manquait.

Le problème que ce module résout : « institutions », « économie » ne sont pas
des sujets, ce sont des rayons de bibliothèque. Comparer deux déclarations parce
qu'elles sont toutes deux rangées sous « institutions » n'a aucun sens — mesuré
sur corpus réel : 3 751 déclarations, 15 thèmes, 0 contradiction trouvable.

Un sujet, c'est « l'âge de départ à la retraite », « l'aide militaire à
l'Ukraine », « le nombre d'expulsions annuelles ». Cette granularité ne peut pas
être devinée d'avance (une grille fermée de 28 référents ne captait que 1,3 % du
corpus) : elle doit ÉMERGER des déclarations elles-mêmes.

Algorithme repris de `online_clustering` (plateforme PMO, éprouvé en production
sur la presse du Moyen-Orient), adapté aux déclarations :

  1. bucket grossier = thème, pour ne pas comparer tout avec tout ;
  2. **gate d'entités** (Jaccard ≥ ETA) — c'est le cœur : deux propos parlent du
     même sujet s'ils nomment les mêmes choses, pas s'ils partagent un rayon ;
  3. cosinus ≥ THETA sur le centroïde du sujet ;
  4. rien ne dépasse → nouveau sujet.

Le centroïde est une moyenne courante : un sujet se déplace à mesure qu'il
absorbe des propos, sans qu'on recalcule tout.

Module pur : il opère sur des dataclasses, jamais sur l'ORM. L'appelant charge,
décide, persiste — ce qui rend la logique testable sans base.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

# Hyperparamètres. Calibrés sur le corpus ED (embeddings MiniLM local 384d) —
# à recalibrer si l'on change de modèle d'embeddings.
# Rattachement au centroïde d'un sujet. CALIBRÉ sur le corpus (28/08) : parmi
# les déclarations passant le gate d'entités, le meilleur cosinus plafonne à
# 0,80 et sa médiane est 0,52 — un seuil à 0,72 n'attrapait que 2 candidats sur
# 600. Le gate pondéré par la rareté fait déjà le tri sémantique ; le cosinus
# n'est qu'une confirmation, il n'a pas à être le filtre principal.
THETA_COSINE = 0.62
ETA_ENTITY_OVERLAP = 0.20 # recouvrement d'entités pondéré par la rareté (IDF)
ETA_ENTITY_JACCARD = 0.25 # ancien seuil Jaccard, conservé pour `assign_or_create`
MIN_ENTITIES = 2          # en dessous, le propos est trop vague pour un sujet
MERGE_COSINE = 0.88       # fusion de deux sujets devenus quasi identiques

Vec = Sequence[float]

# Mots vides : tout ce qui ne DÉSIGNE rien. Un sujet se reconnaît à ce qu'il
# nomme ; « il faut que nous fassions » ne nomme rien.
_STOP = {
    "affirme", "declare", "estime", "propose", "denonce", "explique", "ajoute",
    # Formes conjuguées vues en corpus. Liste CURÉE, pas de règle morphologique :
    # un filtre sur « -ions » supprimerait « élections », « régions », « questions ».
    "fassions", "fassent", "puisse", "puissent", "soient", "aient", "ferons",
    "feront", "allons", "iront", "devons", "doivent", "sommes", "etaient",
    "serait", "seraient", "aurait", "auraient", "pourrait", "pourraient",
    "faut", "doit", "peut", "veut", "va", "fait", "dit", "etre", "avoir",
    "cette", "cet", "ces", "leur", "leurs", "notre", "nos", "votre", "vos",
    # Pronoms : « nous » revient dans presque tout propos politique et ne
    # distingue aucun sujet — le garder rapprocherait n'importe quoi.
    "nous", "vous", "elle", "elles", "lui", "eux", "ceux", "celles", "celui",
    "cela", "ceci", "dont", "lequel", "laquelle", "quoi", "qui", "que",
    "tout", "tous", "toute", "toutes", "meme", "aussi", "encore", "plus",
    "moins", "tres", "bien", "sans", "sous", "dans", "avec", "pour", "par",
    "sur", "entre", "vers", "chez", "depuis", "pendant", "selon", "contre",
    "france", "francais", "francaise", "francaises", "pays", "gouvernement",
    "monsieur", "madame", "president", "ministre", "annee", "annees", "jour",
    "aujourd", "hui", "hier", "demain", "chose", "choses", "gens", "personnes",
}

_WORD = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'-]{3,}")


def _fold(word: str) -> str:
    """Forme comparable : sans accents, minuscule."""
    return "".join(
        c for c in unicodedata.normalize("NFD", word.lower())
        if unicodedata.category(c) != "Mn"
    )


def entities_of(text: str, *, max_entities: int = 12) -> set[str]:
    """Signature d'entités d'une déclaration : ce qu'elle NOMME.

    Approche déterministe et gratuite, sans NER : les mots pleins portent le
    sujet. Les noms propres (capitalisés hors début de phrase) comptent double
    dans la mesure où ils sont conservés en priorité — ce sont eux qui
    distinguent « l'aide à l'Ukraine » de « l'aide au développement ».
    """
    if not text:
        return set()
    words = _WORD.findall(text)
    proper: list[str] = []
    common: list[str] = []
    for i, w in enumerate(words):
        f = _fold(w)
        if f in _STOP or len(f) < 4:
            continue
        # Capitalisé sans être en tête de phrase → nom propre probable.
        (proper if (w[0].isupper() and i > 0) else common).append(f)

    seen: dict[str, None] = {}
    for w in proper + common:
        seen.setdefault(w, None)
        if len(seen) >= max_entities:
            break
    return set(seen)


def cosine(a: Vec, b: Vec) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def idf_weights(entity_sets: Sequence[set[str]]) -> dict[str, float]:
    """Rareté de chaque entité dans le corpus (IDF).

    Toutes les entités ne se valent pas : « impôts » revient partout et ne
    distingue rien, « Fresnaye » n'apparaît que dans les propos qui parlent
    d'elle. Pondérer par la rareté est ce qui permet de rapprocher deux
    déclarations qui ne partagent qu'un seul terme — pourvu qu'il soit parlant.
    """
    n = max(1, len(entity_sets))
    df: dict[str, int] = {}
    for s in entity_sets:
        for e in s:
            df[e] = df.get(e, 0) + 1
    return {e: math.log(1 + n / (1 + c)) for e, c in df.items()}


def weighted_overlap(a: set[str], b: set[str], idf: dict[str, float]) -> float:
    """Recouvrement d'entités pondéré par leur rareté, dans [0, 1].

    Remplace Jaccard, qui pénalise mécaniquement les ensembles fournis : trois
    propos sur l'arrivée de Virginie de la Fresnaye au RN ne partageaient que
    « gaulle » sur six entités chacun — Jaccard 0,09, sous le seuil, donc trois
    sujets distincts pour un seul objet. Normalisé par le plus PETIT des deux
    côtés : un propos court ne doit pas être rejeté parce que l'autre est long.
    """
    if not a or not b:
        return 0.0
    shared = sum(idf.get(e, 0.0) for e in a & b)
    if shared == 0.0:
        return 0.0
    mass_a = sum(idf.get(e, 0.0) for e in a)
    mass_b = sum(idf.get(e, 0.0) for e in b)
    denom = min(mass_a, mass_b)
    return shared / denom if denom else 0.0


@dataclass
class SubjectState:
    """Un sujet en cours de constitution."""

    subject_id: str
    bucket: str
    centroid: list[float]
    entities: set[str] = field(default_factory=set)
    n_claims: int = 0
    claim_ids: list[int] = field(default_factory=list)


@dataclass
class ClaimProbe:
    """Une déclaration candidate à un sujet."""

    claim_id: int
    bucket: str
    embedding: list[float]
    entities: set[str]


@dataclass
class Decision:
    subject_id: str | None
    created: bool
    score: float
    entity_jaccard: float
    reason: str | None = None


def assign_or_create(
    probe: ClaimProbe,
    candidates: Sequence[SubjectState],
    *,
    theta: float = THETA_COSINE,
    eta: float = ETA_ENTITY_JACCARD,
) -> Decision:
    """Rattache la déclaration à un sujet existant, ou en ouvre un nouveau."""
    if len(probe.entities) < MIN_ENTITIES:
        # Un propos qui ne nomme rien ne fonde pas un sujet et n'en rejoint
        # aucun : le laisser entrer polluerait un sujet réel.
        return Decision(None, False, 0.0, 0.0, "trop_vague")

    same_bucket = [c for c in candidates if c.bucket == probe.bucket]
    if not same_bucket:
        return Decision(None, True, 0.0, 0.0, "premier_du_bucket")

    gated = [(c, jaccard(probe.entities, c.entities)) for c in same_bucket]
    gated = [(c, ej) for c, ej in gated if ej >= eta]
    if not gated:
        return Decision(None, True, 0.0, 0.0, "gate_entites")

    scored = sorted(
        ((c, cosine(probe.embedding, c.centroid), ej) for c, ej in gated),
        key=lambda t: -t[1],
    )
    best, score, ej = scored[0]
    if score >= theta:
        return Decision(best.subject_id, False, score, ej)
    return Decision(None, True, score, ej, "cosinus_insuffisant")


def absorb(state: SubjectState, probe: ClaimProbe) -> SubjectState:
    """Intègre la déclaration : centroïde en moyenne courante, entités unies."""
    n = state.n_claims
    state.centroid = [
        (c * n + v) / (n + 1) for c, v in zip(state.centroid, probe.embedding)
    ]
    state.entities |= probe.entities
    state.n_claims = n + 1
    state.claim_ids.append(probe.claim_id)
    return state


def mergeable_pairs(
    subjects: Sequence[SubjectState], *, threshold: float = MERGE_COSINE
) -> list[tuple[str, str, float]]:
    """Sujets devenus quasi identiques — à fusionner lors d'une passe de curage.

    Le clustering incrémental dépend de l'ordre d'arrivée : deux sujets nés
    séparément peuvent converger. Sans cette passe, le même sujet existe en
    double et les propos qui devraient se confronter restent séparés.
    """
    out: list[tuple[str, str, float]] = []
    for i in range(len(subjects)):
        for j in range(i + 1, len(subjects)):
            a, b = subjects[i], subjects[j]
            if a.bucket != b.bucket:
                continue
            s = cosine(a.centroid, b.centroid)
            if s >= threshold:
                out.append((a.subject_id, b.subject_id, s))
    return sorted(out, key=lambda t: -t[2])
