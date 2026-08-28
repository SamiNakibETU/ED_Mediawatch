"""Doctrine du juge — les règles et les premiers cas tranchés, écrits à la main.

Le problème que ce fichier résout. La boucle d'apprentissage
(`learning.py`) n'ouvre qu'à partir de cinq décisions humaines. En dessous,
elle rend la consigne inchangée. Un observatoire qui démarre a donc zéro
décision, donc zéro apprentissage — et personne ne va relire cent
rapprochements d'un juge qui n'a encore rien appris. Le système attendait un
amorçage qui ne pouvait pas venir.

D'où ce fichier : la doctrine de départ, POSÉE et non apprise. Des règles
éditoriales, et des cas d'école tranchés à la main. Le juge part instruit ; les
décisions de la rédaction viennent ensuite l'affiner, et PRIMENT sur ces
exemples quand elles les contredisent — la doctrine est un plancher, pas un
plafond.

Les cas ci-dessous ne sont pas des illustrations décoratives. Ils couvrent les
confusions qui coûtent réellement, dans cet ordre de gravité :

1. **Le périmètre.** Deux chiffres différents sur deux périmètres différents ne
   se contredisent pas. C'est la première cause de faux positif, et la plus
   humiliante à publier.
2. **L'attribution.** Un propos rapporté n'est pas un propos tenu. Prêter à
   quelqu'un ce qu'il cite est la faute la plus grave d'un observatoire.
3. **La procédure.** Voter contre un texte dont on approuve le principe est
   ordinaire en politique et ne contredit rien.
4. **Le temps.** Une prédiction démentie par les faits n'est pas une
   contradiction ; c'est une prédiction fausse, ce qui est un autre sujet.
5. **Le revirement assumé.** Revendiqué, il n'a rien de caché — le signaler
   comme une contradiction, c'est reprocher à quelqu'un d'avoir changé d'avis
   ouvertement.

Chaque cas est écrit comme les vraies déclarations du corpus : une phrase, un
objet, un locuteur implicite. Ils servent deux fois — comme exemples dans la
consigne, et comme jeu d'évaluation (`src/scripts/eval_judge.py`) : une consigne
modifiée qui régresse dessus se voit immédiatement.
"""

from __future__ import annotations

DOCTRINE_VERSION = "doctrine-v1"


# ── Les règles éditoriales ───────────────────────────────────────────────
#
# Elles complètent les règles logiques déjà dans la consigne du juge. Celles-ci
# relèvent de la déontologie de l'observatoire, pas de la logique : elles disent
# ce qu'on accepte de publier, pas ce qui est vrai.

RULES = """
DOCTRINE DE L'OBSERVATOIRE — ce qu'on accepte de signaler, et ce qu'on refuse.

A. Le périmètre avant le chiffre. Avant de conclure à une contradiction
   chiffrée, vérifie que les deux valeurs portent sur le même périmètre, la même
   unité et la même période. « 6 milliards » et « 7 milliards » ne se
   contredisent que s'il s'agit de la même chose, comptée pareil.

   Mais le doute doit être FONDÉ SUR LE TEXTE. Si les deux déclarations
   désignent la même grandeur avec les mêmes mots et qu'aucune n'introduit de
   distinction (période, sous-ensemble, mode de calcul), il n'y a pas de doute à
   avoir : deux montants différents pour la même chose se contredisent.
   L'absence de précision n'est pas une précision divergente — invoquer un
   périmètre que personne n'a mentionné, c'est inventer une excuse, pas
   appliquer une règle.

B. Un propos rapporté n'est pas un propos tenu. Si l'une des déclarations
   attribue une position à un tiers (« la gauche prétend que… », « le
   gouvernement affirme… »), elle documente ce que le locuteur dit D'UN AUTRE,
   pas ce qu'il défend. Hors sujet.

C. La procédure n'est pas la position. Voter contre un texte dont on approuve
   le principe, s'abstenir par tactique, refuser un calendrier tout en
   soutenant un objectif : c'est de la politique ordinaire, pas un revirement.
   Compatible, sauf si le propos porte explicitement sur le principe lui-même.

D. Une prédiction démentie n'est pas une contradiction. « Ça va arriver » suivi
   de « ça n'est pas arrivé » décrit un pronostic raté, pas deux positions
   inconciliables. Hors sujet — sauf si le locuteur nie avoir fait la
   prédiction.

E. Un revirement revendiqué se dit, il ne se dénonce pas. Si le locuteur
   reconnaît lui-même le changement, le verdict est « evolution_assumee ». On
   ne reproche pas à quelqu'un d'avoir changé d'avis ouvertement.

F. Le degré n'est pas le sens. Durcir ou nuancer une position sans l'inverser
   n'est pas se contredire. « Il faut réduire » puis « il faut supprimer » est
   une intensification, pas un revirement.

G. Deux locuteurs différents qui s'opposent sur le même objet : le verdict
   reste « contradiction ». Ce n'est pas un revirement mais une divergence — la
   nuance se porte dans l'explication, jamais dans le verdict. Ne réponds pas
   « compatible » au motif que deux personnes distinctes peuvent penser
   différemment : c'est vrai de toute divergence, et ça viderait le produit de
   son objet.

H. « compatible » et « hors_sujet » ne disent pas la même chose. Même objet,
   positions conciliables (périmètres, procédure, degré) → compatible. Objets
   DIFFÉRENTS → hors_sujet. Si ton explication commence par « les deux
   déclarations portent sur des objets différents », le verdict est
   « hors_sujet », pas « compatible ».

I. Dans le doute, le verdict le MOINS accusatoire. Une fausse contradiction
   publiée détruit la crédibilité de l'observatoire et se retourne contre lui ;
   un faux négatif ne coûte qu'une occasion manquée. L'asymétrie est assumée.
   Elle ne vaut PAS contre les règles G et H, qui tranchent une étiquette, pas
   un degré de gravité.
"""


# ── Les cas d'école ──────────────────────────────────────────────────────
#
# Chaque cas porte le locuteur ET la date : c'est ce que le juge reçoit en
# production (`_pair_prompt`), et la doctrine en dépend — « même locuteur » et
# « deux voix » ne se tranchent pas pareil. Une première version les avait
# omis ; l'évaluation renvoyait alors « les locuteurs ne sont pas identifiés »
# sur trois cas, et mesurait un défaut du banc d'essai, pas du juge.
# `subject` est le sujet de rapprochement, que la production fournit toujours :
# sans lui, le juge doit deviner si les deux propos parlent de la même chose,
# et il refuse prudemment de trancher — on mesurait alors ce manque, pas lui.
# `verdict` reprend le vocabulaire fermé de `ContradictionVerdict`.
# `why` est ce qu'on veut lire dans l'explication — court, factuel, sans morale.

GOLD: list[dict] = [
    # — Le périmètre : la première cause de faux positif —
    {
        "who_a": "Marine Le Pen", "when_a": "2025-11-13",
        "who_b": "Marine Le Pen", "when_b": "2025-07-16",
        "subject": "la contribution française au budget européen",
        "a": "La contribution de la France au budget européen a augmenté de six milliards d'euros.",
        "b": "La hausse de la contribution française à l'Union européenne coûte exactement sept milliards d'euros.",
        "verdict": "contradiction",
        "why": "Même locuteur, même objet, même unité : deux montants inconciliables.",
    },
    {
        "who_a": "Jordan Bardella", "when_a": "2025-03-02",
        "who_b": "Jordan Bardella", "when_b": "2025-09-14",
        "subject": "le déficit public",
        "a": "Le déficit public atteindra 5 % du PIB cette année.",
        "b": "Le déficit de la Sécurité sociale dépassera 20 milliards d'euros.",
        "verdict": "hors_sujet",
        "why": "Déficit public et déficit de la Sécurité sociale sont deux agrégats distincts.",
    },
    {
        "who_a": "Sébastien Chenu", "when_a": "2025-01-20",
        "who_b": "Sébastien Chenu", "when_b": "2025-06-08",
        "subject": "les expulsions d'étrangers en situation irrégulière",
        "a": "Nous avons expulsé 4 000 étrangers en situation irrégulière l'an dernier.",
        "b": "Plus de 15 000 obligations de quitter le territoire ont été prononcées l'an dernier.",
        "verdict": "compatible",
        "why": "Une expulsion exécutée et une obligation prononcée ne comptent pas la même chose.",
    },
    # — L'attribution : la faute la plus grave —
    {
        "who_a": "Marine Le Pen", "when_a": "2025-02-11",
        "who_b": "Marine Le Pen", "when_b": "2025-10-03",
        "subject": "le coût de l'immigration",
        "a": "La gauche prétend que l'immigration enrichit le pays.",
        "b": "L'immigration coûte plus qu'elle ne rapporte.",
        "verdict": "hors_sujet",
        "why": "La première rapporte la position d'un tiers, elle n'engage pas son auteur.",
    },
    {
        "who_a": "Éric Ciotti", "when_a": "2025-04-05",
        "who_b": "Éric Ciotti", "when_b": "2025-04-19",
        "subject": "le financement des retraites",
        "a": "Le gouvernement affirme que la réforme financera les retraites jusqu'en 2035.",
        "b": "Cette réforme ne réglera rien au financement des retraites.",
        "verdict": "hors_sujet",
        "why": "La première rapporte le propos du gouvernement, la seconde exprime la position du locuteur.",
    },
    # — La procédure : la politique ordinaire —
    {
        "who_a": "Jordan Bardella", "when_a": "2025-12-04",
        "who_b": "Jordan Bardella", "when_b": "2025-12-06",
        "subject": "le budget de l'État",
        "a": "Nous avons voté contre ce budget.",
        "b": "Nous soutenons la baisse des impôts de production que ce budget contient.",
        "verdict": "compatible",
        "why": "Rejeter un texte d'ensemble n'implique pas de rejeter chacune de ses mesures.",
    },
    {
        "who_a": "Marine Le Pen", "when_a": "2025-10-08",
        "who_b": "Marine Le Pen", "when_b": "2025-10-09",
        "subject": "la censure du gouvernement",
        "a": "Nous nous sommes abstenus sur la motion de censure.",
        "b": "Ce gouvernement doit partir.",
        "verdict": "compatible",
        "why": "Une abstention tactique ne contredit pas l'objectif affiché.",
    },
    # — Le temps : prédiction, intensification —
    {
        "who_a": "Sébastien Chenu", "when_a": "2025-05-12",
        "who_b": "Sébastien Chenu", "when_b": "2025-09-30",
        "subject": "la chute du gouvernement",
        "a": "Le gouvernement tombera avant l'été.",
        "b": "Le gouvernement est toujours en place à la rentrée.",
        "verdict": "hors_sujet",
        "why": "Une prédiction non réalisée n'est pas une position inconciliable avec un constat.",
    },
    {
        "who_a": "Sarah Knafo", "when_a": "2025-02-02",
        "who_b": "Sarah Knafo", "when_b": "2026-01-15",
        "subject": "l'aide médicale d'État",
        "a": "Il faut réduire l'aide médicale d'État.",
        "b": "Il faut supprimer l'aide médicale d'État.",
        "verdict": "compatible",
        "why": "La seconde durcit la première sans en inverser le sens.",
    },
    # — Le revirement, assumé ou non —
    {
        "who_a": "Marine Le Pen", "when_a": "2017-03-20",
        "who_b": "Marine Le Pen", "when_b": "2025-06-11",
        "subject": "la sortie de l'euro",
        "a": "La sortie de l'euro est indispensable au redressement du pays.",
        "b": "La sortie de l'euro n'est plus à l'ordre du jour, nous avons fait évoluer notre position.",
        "verdict": "evolution_assumee",
        "why": "Le changement de position est explicitement revendiqué.",
    },
    {
        "who_a": "Éric Zemmour", "when_a": "2024-11-08",
        "who_b": "Éric Zemmour", "when_b": "2026-02-17",
        "subject": "le rétablissement de la peine de mort",
        "a": "Il faut rétablir la peine de mort pour les crimes les plus graves.",
        "b": "Nous n'avons jamais demandé le rétablissement de la peine de mort.",
        "verdict": "contradiction",
        "why": "La seconde nie l'existence de la position défendue dans la première.",
    },
    {
        "who_a": "Marine Le Pen", "when_a": "2022-01-14",
        "who_b": "Marine Le Pen", "when_b": "2025-11-27",
        "subject": "l'âge légal de départ à la retraite",
        "a": "L'âge légal de départ à la retraite doit être ramené à 60 ans.",
        "b": "Revenir à la retraite à 60 ans n'est pas finançable.",
        "verdict": "contradiction",
        "why": "Même locuteur, positions inconciliables sur la même mesure.",
    },
    # — Deux voix : une divergence, pas un reniement —
    {
        "who_a": "Marine Le Pen", "when_a": "2025-07-30",
        "who_b": "Jordan Bardella", "when_b": "2025-08-04",
        "subject": "la reconnaissance de l'État de Palestine",
        "a": "La reconnaissance de l'État de Palestine est une faute diplomatique.",
        "b": "La reconnaissance de l'État de Palestine est une étape nécessaire vers la paix.",
        "verdict": "contradiction",
        "why": "Positions opposées sur le même objet ; deux locuteurs, donc une divergence, pas un revirement.",
    },
    # — Le piège du mot identique —
    {
        "who_a": "Jordan Bardella", "when_a": "2025-03-18",
        "who_b": "Jordan Bardella", "when_b": "2025-03-25",
        "subject": "le budget",
        "a": "Le budget de la défense doit atteindre 2 % du PIB.",
        "b": "Le budget de l'État doit être réduit de 2 %.",
        "verdict": "hors_sujet",
        "why": "Le mot « budget » désigne ici deux objets différents.",
    },
]


def doctrine_block() -> str:
    """Les règles et les cas d'école, prêts à être ajoutés à la consigne du juge."""
    lines = [RULES, "\nCAS D'ÉCOLE — tranchés par la rédaction, aligne-toi dessus :"]
    for i, c in enumerate(GOLD, 1):
        lines.append(
            f"{i}. [{c['subject']}]\n"
            f"   A — {c['who_a']}, {c['when_a']} : « {c['a']} »\n"
            f"   B — {c['who_b']}, {c['when_b']} : « {c['b']} »\n"
            f"   → {c['verdict']} — {c['why']}"
        )
    return "\n".join(lines)
