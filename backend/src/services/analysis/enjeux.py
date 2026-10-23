"""Le registre des positions : une liste fermée d'enjeux, une échelle par enjeu.

On part d'en haut, à l'inverse des sujets émergents. Une question fermée, posée
par l'équipe, et chaque prise de parole rangée sur son échelle. Un revirement
n'est plus une devinette sur des cosinus : c'est la même personne à deux
endroits différents de la même échelle, à deux dates.

Les échelles sont ordinales : `rang` sert à mesurer l'ampleur d'un écart (passer
de 60 à 62 ans n'est pas passer de 60 à 64). Le silence n'a pas de cran : se
taire n'est pas une position, et on ne l'écrit pas.

Les mots-clés ne décident de rien. Ils trient ce qui part au modèle, et c'est
le modèle qui dit si le texte prend position. Un tweet qui nomme l'Ukraine pour
parler du prix du blé est écarté à la lecture, pas au filtre.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

# Version du référentiel. Elle change dès qu'une question, une échelle ou un
# mot-clé change : une position lue sous une autre version se relit.
ENJEUX_VERSION = "enjeux-v1"


@dataclass(frozen=True)
class Cran:
    code: str
    label: str
    rang: int


@dataclass(frozen=True)
class Enjeu:
    slug: str
    titre: str
    question: str
    echelle: tuple[Cran, ...]
    motifs: str  # expression régulière, insensible à la casse
    # Racines pour le premier tri en SQL (LIKE), que `motifs` affine ensuite.
    # SQLite et Postgres n'ont pas la même syntaxe d'expression régulière.
    amorces: tuple[str, ...]
    # Repères publics, pour lire la trajectoire. Ce ne sont pas des positions :
    # ils ne sortent jamais d'un tweet et ne comptent dans aucun écart.
    jalons: tuple[str, ...] = ()

    def cran(self, code: str | None) -> Cran | None:
        return next((c for c in self.echelle if c.code == code), None)

    def concerne(self, texte: str) -> bool:
        return bool(re.search(self.motifs, texte or "", re.IGNORECASE))


ENJEUX: tuple[Enjeu, ...] = (
    Enjeu(
        slug="ukraine",
        titre="Ukraine et Russie",
        question="La France doit-elle aider militairement l'Ukraine face à la Russie ?",
        echelle=(
            Cran("aide_militaire", "aider militairement, y compris en armes", 1),
            Cran("aide_limitee", "aider, mais sans armes offensives ni troupes", 2),
            Cran("negocier", "cesser l'escalade, négocier avec la Russie", 3),
            Cran("contre_aide", "s'opposer à l'aide, lever les sanctions", 4),
        ),
        motifs=r"ukrain|zelensk|\bkiev\b|\bkyiv\b|poutine|\brussie\b|\brusses?\b|kremlin|donbass|crimée",
        amorces=("ukrain", "zelensk", "kiev", "kyiv", "poutine", "russ", "kremlin", "donbass", "crimée"),
        jalons=("2022-02-24 : invasion russe de l'Ukraine",),
    ),
    Enjeu(
        slug="retraites",
        titre="Âge de départ à la retraite",
        question="À quel âge doit-on pouvoir partir à la retraite ?",
        echelle=(
            Cran("60_tous", "60 ans pour tous", 1),
            Cran("60_carrieres_longues", "60 ans pour les carrières longues, plus tard pour les autres", 2),
            Cran("62", "62 ans", 3),
            Cran("64_ou_plus", "64 ans ou plus", 4),
        ),
        motifs=r"retraite|\b6[024] ans\b|âge légal|age legal|annuités|trimestres",
        amorces=("retraite", "60 ans", "62 ans", "64 ans", "âge légal", "age legal", "annuités", "trimestres"),
        jalons=("2023-04-14 : promulgation de la réforme portant l'âge légal à 64 ans",),
    ),
    Enjeu(
        slug="otan",
        titre="OTAN",
        question="La France doit-elle quitter le commandement intégré de l'OTAN ?",
        echelle=(
            Cran("quitter", "quitter le commandement intégré", 1),
            Cran("quitter_plus_tard", "le quitter, mais pas en temps de guerre", 2),
            Cran("rester", "rester dans le commandement intégré", 3),
        ),
        motifs=r"\botan\b|\bnato\b|commandement intégré|alliance atlantique",
        amorces=("otan", "nato", "commandement intégré", "alliance atlantique"),
        jalons=("2009 : retour de la France dans le commandement intégré",),
    ),
)

PAR_SLUG: dict[str, Enjeu] = {e.slug: e for e in ENJEUX}


def enjeux_concernes(texte: str) -> list[Enjeu]:
    return [e for e in ENJEUX if e.concerne(texte)]


@dataclass(frozen=True)
class Point:
    """Une position datée d'une figure, telle qu'elle est en base."""

    personality_id: int
    position: str
    published_at: datetime
    post_id: int


@dataclass(frozen=True)
class Ecart:
    personality_id: int
    avant: Point
    apres: Point
    ampleur: int  # différence de rang, toujours positive


def ecarts(enjeu: Enjeu, points: list[Point], *, min_jours: int = 30) -> list[Ecart]:
    """Les changements de position d'une même figure, dans l'ordre du temps.

    On compare chaque position à la précédente de la même personne, pas à la
    première : une trajectoire 1 → 3 → 1 fait deux écarts, et c'est ce qu'il
    faut montrer. Deux positions à moins de `min_jours` d'écart ne comptent
    pas : dans la même semaine, c'est une nuance de formulation, pas un
    revirement, et c'est le relecteur qui tranchera en lisant les deux textes.
    """
    par_figure: dict[int, list[Point]] = {}
    for p in points:
        if enjeu.cran(p.position):
            par_figure.setdefault(p.personality_id, []).append(p)

    out: list[Ecart] = []
    for pid, serie in par_figure.items():
        serie.sort(key=lambda p: p.published_at)
        prec = serie[0]
        for p in serie[1:]:
            if p.position != prec.position:
                if (p.published_at - prec.published_at).days >= min_jours:
                    ampleur = abs(enjeu.cran(p.position).rang - enjeu.cran(prec.position).rang)
                    out.append(Ecart(pid, prec, p, ampleur))
                    prec = p
                # Un écart trop rapproché ne remplace pas la référence : la
                # position suivante se compare encore à la dernière qui tenait.
                continue
            prec = p
    out.sort(key=lambda e: (-e.ampleur, e.apres.published_at))
    return out
