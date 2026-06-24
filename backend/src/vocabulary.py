"""Vocabulaire contrôlé partagé — une seule source de vérité pour les valeurs
d'énumération utilisées en base, dans les routers ET dans le front.

Avant : ces chaînes ("prise_de_parole", "far_right", "x"…) étaient recopiées à
la main dans les modèles, les routers, les collecteurs, les seeds et le front.
Une faute de frappe filtrait silencieusement vers zéro résultat, sans erreur.
Ici, un seul endroit ; le front les récupère via `GET /vocabulary`.

Volontairement des classes de constantes `str` (pas un `enum.StrEnum`, réservé à
Python ≥ 3.11) : substitution directe des littéraux, zéro changement de
comportement, compatible toute version, et `Source.X` vaut littéralement "x".
"""

from __future__ import annotations


class Source:
    """Origine d'un item (champ source-agnostique `Post.source`)."""

    X = "x"
    PRESS = "press"
    ALL = (X, PRESS)


class Nature:
    """Nature d'un item de presse (cf. `relevance.py`)."""

    PRISE_DE_PAROLE = "prise_de_parole"
    MENTION = "mention"
    ALL = (PRISE_DE_PAROLE, MENTION)


class Leaning:
    """Orientation éditoriale d'une source presse (extrême droite → gauche radicale)."""

    FAR_RIGHT = "far_right"
    RIGHT = "right"
    CENTER = "center"
    LEFT = "left"
    FAR_LEFT = "far_left"
    ALL = (FAR_RIGHT, RIGHT, CENTER, LEFT, FAR_LEFT)
    LABELS = {
        FAR_RIGHT: "Extrême droite",
        RIGHT: "Droite",
        CENTER: "Centre",
        LEFT: "Gauche",
        FAR_LEFT: "Gauche radicale",
    }


class GroupCode:
    """Regroupement de surface d'une figure suivie."""

    RN = "RN"
    UDR = "UDR"
    FIGURE = "FIGURE"
    ALL = (RN, UDR, FIGURE)


class Verif:
    """Statut de vérification du handle X."""

    VERIFIE = "verifie"
    A_CONFIRMER = "a_confirmer"
    AN_2024 = "an_2024"
    FIABLE = "fiable"
    ALL = (VERIFIE, A_CONFIRMER, AN_2024, FIABLE)


class RunStatus:
    """État d'un `CollectionRun`."""

    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    ALL = (RUNNING, COMPLETED, ERROR)


class RunKind:
    """Type de passe de collecte (désambiguïse `CollectionRun`)."""

    X = "x"
    PRESS = "press"
    ALL = (X, PRESS)


def as_dict() -> dict:
    """Payload exposé par `GET /vocabulary` (consommé par le front)."""
    return {
        "source": list(Source.ALL),
        "nature": list(Nature.ALL),
        "leaning": list(Leaning.ALL),
        "leaning_labels": Leaning.LABELS,
        "group_code": list(GroupCode.ALL),
        "verif": list(Verif.ALL),
    }
