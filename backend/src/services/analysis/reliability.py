"""Alpha de Krippendorff — la mesure d'accord de l'analyse de contenu.

Pourquoi pas un simple taux d'accord. Deux codeurs qui rangent 80 % des propos
dans la même catégorie n'ont rien prouvé si cette catégorie représente 80 % du
corpus : le hasard seul y parviendrait. L'alpha corrige de l'accord attendu par
chance, ce qu'un pourcentage brut ne fait jamais.

Pourquoi l'alpha plutôt que le kappa. Il accepte n'importe quel nombre de
codeurs, tolère les valeurs manquantes, et fonctionne sur des catégories
nominales comme ici. C'est la mesure retenue par la littérature qui évalue
l'annotation par modèle, avec des seuils établis :

    α ≥ 0,80    fiable
    0,67 – 0,79 provisoire — utilisable en signalant la réserve
    α < 0,67    non fiable — la consigne est à revoir avant tout usage

Implémenté ici plutôt qu'importé : trente lignes, et la définition reste
lisible et vérifiable à côté de ce qu'elle mesure. Une dépendance pour une seule
métrique rendrait le calcul opaque sans rien simplifier.

Formule, cas nominal :

    α = 1 − Do / De

où Do est le désaccord observé et De le désaccord attendu si les codes étaient
distribués au hasard avec les mêmes fréquences marginales. Les unités codées par
un seul codeur ne pèsent sur aucun des deux termes : elles n'apportent aucune
information d'accord.
"""

from __future__ import annotations

from collections import Counter
from itertools import permutations

# Seuils usuels de l'analyse de contenu.
RELIABLE = 0.80
TENTATIVE = 0.67


def krippendorff_alpha(units: list[list]) -> float | None:
    """Alpha nominal. `units` : une liste de codes par unité, un par codeur.

    Un code `None` marque une valeur manquante — un codeur qui n'a pas tranché.
    Rend None quand il n'y a pas de quoi mesurer : aucune unité codée deux fois,
    ou un seul code employé partout (l'alpha n'est alors pas défini, et le
    prétendre parfait serait faux).
    """
    # Coïncidences : pour chaque unité, toutes les PAIRES ORDONNÉES de codes.
    # Chaque unité pèse en proportion inverse de son nombre de codeurs, sinon
    # une unité codée par cinq personnes écraserait quatre unités codées par
    # deux.
    coincidences: Counter = Counter()
    total = 0.0
    for codes in units:
        présents = [c for c in codes if c is not None]
        m = len(présents)
        if m < 2:
            continue
        poids = 1.0 / (m - 1)
        for a, b in permutations(présents, 2):
            coincidences[(a, b)] += poids
            total += poids

    if total == 0:
        return None

    marges: Counter = Counter()
    for (a, _), v in coincidences.items():
        marges[a] += v

    if len(marges) < 2:
        return None  # un seul code employé : l'alpha n'est pas défini

    # Do : part des paires où les deux codes diffèrent.
    do = sum(v for (a, b), v in coincidences.items() if a != b) / total
    # De : la même chose si les codes étaient tirés au hasard aux fréquences
    # observées, sans remise.
    de = sum(
        marges[a] * marges[b]
        for a, b in permutations(marges, 2)
    ) / (total * (total - 1))

    if de == 0:
        return None
    return 1.0 - do / de


def verdict(alpha: float | None) -> str:
    """Le seuil atteint, dit en clair plutôt qu'en chiffre seul."""
    if alpha is None:
        return "non mesurable"
    if alpha >= RELIABLE:
        return "fiable"
    if alpha >= TENTATIVE:
        return "provisoire — utilisable en signalant la réserve"
    return "non fiable — revoir la consigne avant tout usage"
