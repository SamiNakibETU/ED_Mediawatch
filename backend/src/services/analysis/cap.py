"""Grille thématique CAP — Comparative Agendas Project.

Pourquoi remplacer la grille maison. Les quinze thèmes inventés au départ
avaient déjà dérivé à vingt-quatre valeurs en base, dont 236 propos sans thème
du tout. Surtout, une catégorie inventée n'est comparable à rien : « ils parlent
beaucoup d'immigration » reste une impression tant qu'on ne peut pas la mettre
en regard de l'attention du gouvernement, du Parlement ou de la presse.

Le CAP maintient depuis 1993 une grille de 21 topiques majeurs, appliquée dans
une vingtaine de pays. Le chapitre français existe (Sciences Po) et a codé les
manifestes des partis français en quasi-phrases avec cette même grille, de 1974
à 2013. Adopter le CAP, c'est donc rendre ce corpus immédiatement comparable à
un jeu de données existant — pas seulement « mieux rangé ».

Codes non consécutifs, volontairement : 11 et 22 ne sont pas attribués, et le
codebook les laisse vides pour préserver la continuité historique depuis 1947.
Ne pas « corriger » les trous.

Méthode. Deux questions séquentielles, pas un prompt unique — voir
« Le protocole de codage » plus bas : c'est la décomposition qui rend
l'annotation par modèle fiable, et un prompt holistique s'effondre. La fiabilité
se mesure avec l'alpha de Krippendorff contre un jeu annoté à la main
(`src/scripts/eval_cap.py`), aux seuils établis de l'analyse de contenu :
α ≥ 0,80 fiable, 0,67–0,79 provisoire, en dessous non fiable.

Portée de cette version. Topiques MAJEURS uniquement. Le CAP mesure 95 %
d'accord entre codeurs humains au niveau majeur et 75 % au niveau des
sous-topiques : c'est au niveau majeur que la grille est solide, et c'est celui
qui porte l'agrégation. Les ~220 sous-topiques viendront avec le codebook
français, dont les libellés officiels conditionnent la comparabilité — inventer
des libellés français sur des codes américains fabriquerait une comparabilité
fausse, ce qui est pire que pas de sous-topique du tout.
"""

from __future__ import annotations

# La signature du codeur, pas un simple numéro de grille.
#
# En analyse de contenu, un codeur se définit par le triplet (modèle, consigne,
# échantillonnage) : sans le verrouiller et l'enregistrer, un taux d'accord n'est
# ni interprétable ni reproductible — on ne sait plus ce qui a codé quoi. Toute
# modification de la consigne ou du modèle doit faire évoluer cette chaîne, ce
# qui remet automatiquement le corpus en file de recodage.
CAP_GRID = "cap-major-2019"
CAP_PROTOCOL = "2q-v2"        # décomposition en deux questions
# v2 : un échec d'appel ne s'enregistre plus comme « aucun thème ». Le
# changement de version remet tout le corpus en file de recodage — c'est
# exactement ce à quoi sert ce numéro, et 4 660 déclarations avaient été
# marquées sans jamais avoir été lues.
CAP_TEMPERATURE = 0.0


def coder_signature(model: str) -> str:
    """Identifiant reproductible du codeur qui a produit une annotation."""
    return f"{CAP_GRID}/{CAP_PROTOCOL}/{model}@t{CAP_TEMPERATURE}"


# Conservé pour les lectures existantes ; la signature complète prime.
CAP_VERSION = f"{CAP_GRID}/{CAP_PROTOCOL}"

# code → (libellé français, aide au codage)
#
# Les libellés suivent la traduction française usuelle du codebook. L'aide est
# écrite pour lever les confusions du corpus réel, pas pour paraphraser le titre.
MAJOR: dict[int, tuple[str, str]] = {
    1:  ("Macroéconomie",
         "inflation, croissance, budget de l'État, dette, déficit, fiscalité générale"),
    2:  ("Droits civiques et libertés",
         "discriminations, libertés publiques, vie privée, droits des minorités, laïcité"),
    3:  ("Santé",
         "hôpital, assurance maladie, professionnels de santé, médicaments, santé publique"),
    4:  ("Agriculture",
         "agriculteurs, PAC, élevage, pêche, sécurité alimentaire"),
    5:  ("Travail et emploi",
         "chômage, salaires, droit du travail, syndicats, formation professionnelle, retraites"),
    6:  ("Éducation",
         "école, université, programmes scolaires, enseignants, recherche et enseignement"),
    7:  ("Environnement",
         "pollution, déchets, eau, biodiversité, climat"),
    8:  ("Énergie",
         "nucléaire, électricité, pétrole et gaz, renouvelables, prix de l'énergie"),
    9:  ("Immigration",
         "entrée et séjour des étrangers, asile, expulsions, naturalisation, frontières"),
    10: ("Transports",
         "routes, ferroviaire, aérien, transports publics, sécurité routière"),
    12: ("Justice et criminalité",
         "police, tribunaux, prisons, délinquance, terrorisme intérieur, drogues"),
    13: ("Protection sociale",
         "minima sociaux, allocations, aide aux familles, pauvreté, handicap, grand âge"),
    14: ("Logement",
         "logement social, loyers, accession, urbanisme, sans-abri"),
    15: ("Commerce intérieur",
         "entreprises, banques, assurance, concurrence, consommation, tourisme"),
    16: ("Défense",
         "armées, budget militaire, alliances, opérations extérieures, industrie de défense"),
    17: ("Technologies et communications",
         "numérique, télécommunications, médias, espace, recherche scientifique"),
    18: ("Commerce extérieur",
         "exportations, accords commerciaux, tarifs douaniers, investissements étrangers"),
    19: ("Affaires internationales",
         "diplomatie, aide au développement, Union européenne, conflits, relations bilatérales"),
    20: ("Fonctionnement de l'État et vie politique",
         "institutions, élections, votes et procédures parlementaires, fonction "
         "publique, partis, mandats"),
    21: ("Domaine public et territoires",
         "eau et forêts, littoral, outre-mer, aménagement du territoire, patrimoine naturel"),
    23: ("Culture",
         "arts, patrimoine, sport, langue, identité culturelle, religion dans l'espace public"),
}

CODES = tuple(sorted(MAJOR))

# ── Fiabilité mesurée ────────────────────────────────────────────────────
#
# Le résultat de la dernière évaluation (`src/scripts/eval_cap.py`), consigné
# ici pour que le produit sache dans quel état il est. Sans ça, l'interface
# publierait une répartition thématique comme un fait établi alors que sa
# fiabilité n'atteint pas le seuil.
#
# Historique de la consigne, pour mémoire :
#   0,522  première version, question unique
#   0,572  décomposition en deux questions, Q1 recadrée sur l'attention
#   0,599  attraction du topique 20 corrigée
#
# Les écarts restants sont dispersés — une paire différente à chaque fois —
# ce qui est la signature d'une ambiguïté d'annotation, pas d'un défaut de
# consigne. Continuer à régler contre ces cinquante étiquettes reviendrait à
# apprendre UN annotateur, pas la grille.
#
# Ce qu'il faut pour franchir le seuil : un second annotateur indépendant, une
# adjudication des désaccords, et un jeu de 200 unités. Le protocole de
# référence en emploie six, avec test de qualification et pilote.
RELIABILITY = {
    "alpha": 0.599,
    "verdict": "non fiable",
    "n_units": 50,
    "n_coders": 1,
    "measured": "2026-08-29",
    "caveat": "Un seul annotateur, 50 unités. La répartition thématique est "
              "indicative et ne doit pas être publiée comme une mesure tant que "
              "l'alpha n'atteint pas 0,67.",
}



def label(code: int | None) -> str:
    """Libellé lisible, ou une mention explicite quand le code manque."""
    if code is None:
        return "non codé"
    entry = MAJOR.get(int(code))
    return entry[0] if entry else f"code inconnu ({code})"


def is_valid(code: int | None) -> bool:
    return code is not None and int(code) in MAJOR


def grid_for_prompt() -> str:
    """La grille telle qu'elle est donnée au modèle, avec l'aide au codage."""
    return "\n".join(f"{c:>2} {MAJOR[c][0]} — {MAJOR[c][1]}" for c in CODES)


# ── Le protocole de codage ───────────────────────────────────────────────
#
# Deux questions séquentielles plutôt qu'une seule.
#
# La littérature est nette sur ce point : un prompt holistique qui demande à la
# fois « de quoi s'agit-il » et « dans quelle catégorie » s'effondre, et c'est la
# DÉCOMPOSITION qui débloque l'annotation par modèle à l'échelle. Mesuré sur un
# corpus politique en 2026 : Fleiss κ = 0,175 en holistique, performance
# supérieure à l'annotation humaine une fois décomposé, à un dixième du coût.
#
# Le mécanisme vaut d'être compris, parce qu'il explique exactement l'échec
# observé ici. Une question unique laisse le modèle prendre des raccourcis de
# co-occurrence : un propos agressif sans objet précis (« Untel est un
# détraqué ») déclenche un refus de coder alors que la question posée n'était pas
# celle du ton ; à l'inverse, un mot-clé thématique suffit à forcer un domaine.
# Séparer « y a-t-il un objet d'action publique ? » de « lequel ? » casse ce
# couplage : chaque question est jugée pour elle-même.
#
# Q1 est volontairement courte et sans grille : lui donner les 21 topiques
# l'inviterait à chercher lequel colle, alors qu'on lui demande seulement s'il y
# a un objet. Q2 ne se pose que si Q1 répond oui.

Q1_SYSTEM = """Tu détermines si une déclaration a un OBJET RELEVANT DE LA VIE
PUBLIQUE, sans te préoccuper de savoir lequel.

Le CAP code l'ATTENTION portée aux domaines d'action publique. Un fait divers,
un événement, un constat chiffré comptent autant qu'une proposition : parler
d'un vol commis à Nice, c'est porter attention à la délinquance ; décrire une
station d'épuration, c'est porter attention à l'eau. La déclaration n'a pas
besoin de proposer quoi que ce soit.

Réponds OUI dès qu'elle dit quelque chose à propos :
  · d'un domaine de la vie publique — santé, immigration, énergie, école,
    logement, délinquance, économie, défense, environnement, transports,
    agriculture, médias, culture, territoires… — que ce soit sous forme de
    proposition, de constat, d'événement, de chiffre ou de critique ;
  · du processus politique : élections, campagnes, alliances, motions de
    censure, dissolution, partis, institutions, mandats, votes, conduite d'un
    responsable dans l'exercice de sa charge ;
  · d'un pays étranger, d'une organisation internationale, d'une relation
    diplomatique.

Réponds NON dans le seul cas où la déclaration n'a AUCUN objet de ce type :
  · jugement sur la personnalité de quelqu'un (« untel est incompétent »,
    « c'est un détraqué »), sans rien affirmer de son action ;
  · caractérisation d'un camp ou d'un discours sans objet nommé (« ce propos
    est incohérent », « ils sont éloignés du réel ») ;
  · salutation, remerciement, félicitations, hommage personnel, émotion ;
  · anecdote strictement privée.

Le TON n'entre pas dans la décision, et la présence d'un nom propre non plus.
Ce qui compte est qu'il y ait un OBJET dont on puisse dire de quel domaine il
relève. Dans le doute, réponds OUI : la question du domaine sera posée ensuite.

Réponds par un seul mot : OUI ou NON."""


CODING_RULE = """RÈGLE DE CODAGE — le domaine substantiel prédominant.

Code le DOMAINE dont il est substantiellement question, jamais la CIBLE de la
politique ni l'INSTRUMENT employé.

  · Un programme de santé mentale pour anciens combattants se code en SANTÉ (3),
    pas en défense (16) : le sujet est la santé, les anciens combattants sont la
    cible.
  · Une déduction fiscale sur les prêts immobiliers se code en LOGEMENT (14),
    pas en macroéconomie (1) : la fiscalité est l'instrument, le logement est le
    sujet.
  · « Il faut une loi contre les squats » se code en LOGEMENT (14), pas en
    justice (12) : la loi est l'instrument.
  · Le terrorisme se code selon son objet : un attentat visant un transport
    aérien va en TRANSPORTS (10), une politique antiterroriste générale en
    JUSTICE ET CRIMINALITÉ (12).

Le processus politique est un domaine à part entière : élections, alliances,
motions de censure, dissolution, financement des partis, conduite d'un
responsable dans sa charge se codent 20.

Un seul code, celui du domaine PRÉDOMINANT. Si la déclaration mêle deux
domaines, choisis celui sur lequel elle AFFIRME quelque chose, pas celui
qu'elle mentionne en passant.

ATTENTION AU TOPIQUE 20. Il attire à tort, parce que presque tout ce corpus est
tenu par des responsables politiques. Le 20 ne se code que si l'OBJET est
l'institution, l'élection, la procédure ou le parti eux-mêmes. Qu'une
déclaration soit tenue par un élu, vise un ministre ou cite un gouvernement ne
la range pas en 20 : « le budget du Premier ministre est un copié-collé » porte
sur le BUDGET (1), « le maire a mis fin au jumelage avec une ville israélienne »
porte sur la RELATION ÉTRANGÈRE (19), « les magistrats attaquent des
responsables » porte sur la JUSTICE (12). Demande-toi de quoi il est question,
pas qui en parle ni qui est visé.

On a déjà établi que cette déclaration porte sur un objet d'action publique :
ta seule tâche est de dire lequel. Réponds par un nombre."""


# ── Ce qui a été retiré, et pourquoi ─────────────────────────────────────
#
# Une première version traduisait l'ancien thème vers un topique CAP par un
# dictionnaire écrit à la main. Gratuit, instantané, et faux : 31 % d'accord
# seulement avec une relecture du texte. C'est normal — la correspondance
# héritait des erreurs de la grille qu'elle traduisait, et un propos mal rangé en
# « institutions » restait mal rangé en 20. Une table de correspondance ne relit
# pas le texte ; elle propage une classification sans jamais la corriger.
#
# Le codage passe donc entièrement par la lecture du texte, en deux questions.
