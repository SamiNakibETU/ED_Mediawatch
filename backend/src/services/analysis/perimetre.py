"""Ce que l'observatoire consigne, et ce qu'il laisse passer.

Deux règles, écrites ici une fois, parce qu'elles étaient jusqu'ici implicites et
appliquées de travers à chaque écran.

1. LE PÉRIMÈTRE. ED Mediawatch suit l'extrême droite : le référentiel contient
   168 personnes, RN, UDR, Reconquête et mouvance identitaire, et rien d'autre.
   Or l'extraction presse enregistrait TOUT nom prononcé dans un article — le
   modèle nomme le locuteur, la vérification exige seulement que ce nom soit
   littéralement dans le papier. Résultat mesuré le 04/09/2026 : 659 propos
   attribués à 139 personnes hors périmètre, dont Dominique de Villepin,
   Jean-Luc Mélenchon, François Hollande et Benyamin Netanyahou — parce qu'un
   article sur le RN cite aussi ses adversaires.

   La règle : une déclaration sans `personality_id` n'est pas le matériau de
   l'observatoire. C'est le même critère pour les deux canaux — un post X
   appartient toujours à un compte suivi — et il écarte du même coup les propos
   que la presse ne rattache à personne, qui inondaient les pages de sujets sous
   la mention « non attribué ».

2. LES REDITES. Une phrase dite une fois et reprise par vingt rédactions reste
   une phrase. Voir `redites.py` pour le regroupement ; ici, seulement la
   conséquence : on ne compte et on n'affiche que les originaux.

Les deux exclusions sont des FILTRES, pas des suppressions. Les lignes restent
en base, avec leur source, et la règle peut changer sans qu'on ait rien perdu.
"""

from __future__ import annotations

from src.models.claim import Claim


def du_perimetre():
    """La déclaration est-elle imputable à une figure suivie ?"""
    return Claim.personality_id.isnot(None)


def sans_redite():
    """Est-ce la prise de position, et non l'une de ses reprises ?"""
    return Claim.duplicate_of.is_(None)


def retenu():
    """Les deux à la fois : ce qu'un écran de l'observatoire peut montrer."""
    return du_perimetre() & sans_redite()
