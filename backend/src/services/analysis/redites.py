"""Une phrase dite une fois et reprise vingt fois reste une phrase.

Vu le 04/09/2026 sur la page du sujet « l'interdiction du port du voile » :
154 « prises de position consignées », dont une soixantaine de Jean-Philippe
Tanguy disant la même chose.

    « Jean-Philippe Tanguy déclare qu'il sanctionnera le port du voile. »
    « Jean-Philippe Tanguy a déclaré que le port du voile serait sanctionné »
    « Le Rassemblement national prévoit de sanctionner le port du voile »
    « Jean-Philippe Tanguy a assuré dimanche que la question avait été… » (×3)

Il n'a pas pris soixante positions : il en a pris une, dans une interview du
dimanche, et vingt rédactions l'ont reprise. Le dédoublonnage existait par
SOURCE (`dedup_key` = source + verbatim) et pas entre sources : deux articles,
deux déclarations, toujours.

MESURÉ : sur le plus gros sujet du corpus local, 71 propos se réduisent à 18
distincts au seuil 0,93. Les trois quarts de ce que le produit affichait étaient
des redites.

CE QUE ÇA CASSAIT, AU-DELÀ DE L'AFFICHAGE. Le juge sémantique cherche des propos
DIFFÉRENTS sur le même objet, et plafonne exprès la similarité à 0,90 pour
écarter « la même phrase reformulée par l'extracteur ». Sur un corpus aux trois
quarts redondant, il passait donc son quota à écarter des redites : 24
rapprochements trouvés, aucun confirmé. On ne trouve pas de contradiction dans
un corpus qui ne dit qu'une chose.

CE QU'ON GARDE. La reprise n'est pas du bruit, c'est un SIGNAL : qu'une phrase
soit reprise par vingt journaux dit quelque chose de son poids. Elle devient
donc un compte (`n_reprises`) porté par la déclaration retenue, au lieu de
vingt lignes. Rien n'est supprimé — les redites restent en base, rattachées à
leur original, et la source de chacune reste vérifiable.

QUI EST RETENU. Le mieux sourcé, pas le premier venu : une citation directe
prime sur du discours rapporté, un post du locuteur prime sur un article, et à
égalité le plus ancien — c'est lui qui a été dit, les autres le répètent.
"""

from __future__ import annotations

import structlog
from sqlalchemy import func, select

from src.database import get_session_factory
from src.models.claim import Claim
from src.services.analysis.embeddings import cosine

logger = structlog.get_logger(__name__)

# Au-delà, deux propos du même locuteur sur le même sujet sont la même prise de
# position. Calibré sur le corpus : à 0,90 le regroupement mordait sur des
# nuances réelles (71 → 14), à 0,95 il laissait passer des redites (71 → 19).
SEUIL_REDITE = 0.93

# Un locuteur peut redire la même chose six mois plus tard, et c'est alors une
# information — il n'a pas changé d'avis. Au-delà de cette fenêtre, deux propos
# identiques restent deux prises de parole distinctes.
FENETRE_JOURS = 21


def _qualite(c) -> tuple:
    """Clé de choix du représentant. Plus grand = meilleur.

    Une citation directe prime sur du rapporté (ce sont ses mots), un post du
    locuteur prime sur un article (aucun intermédiaire), et à égalité le plus
    ancien l'emporte : c'est lui qui a été dit, les autres le reprennent.
    """
    return (
        1 if c.quote_style == "direct" else 0,
        1 if c.platform == "x" else 0,
        -(c.published_at.timestamp() if c.published_at else 0),
        -c.id,
    )


def grouper(claims: list) -> list[list]:
    """Groupes de redites. Le premier de chaque groupe est le représentant.

    Regroupement glouton par transitivité assumée : si A ≈ B et B ≈ C, les trois
    sont la même prise de position. Sur des propos aussi proches (0,93), la
    chaîne ne dérive pas, et un regroupement strict laisserait passer des paires
    évidentes pour une décimale.
    """
    restants = [c for c in claims if getattr(c, "embedding", None)]
    restants.sort(key=_qualite, reverse=True)
    vus: set[int] = set()
    groupes: list[list] = []
    for tete in restants:
        if tete.id in vus:
            continue
        vus.add(tete.id)
        groupe = [tete]
        for autre in restants:
            if autre.id in vus:
                continue
            if tete.published_at and autre.published_at:
                ecart = abs((tete.published_at - autre.published_at).days)
                if ecart > FENETRE_JOURS:
                    continue
            if cosine(tete.embedding, autre.embedding) >= SEUIL_REDITE:
                vus.add(autre.id)
                groupe.append(autre)
        groupes.append(groupe)
    return groupes


async def fold_redites() -> dict:
    """Rattache chaque redite à la prise de position qu'elle reprend.

    Recalculé entièrement à chaque passe : c'est une valeur DÉRIVÉE des vecteurs
    et des sujets, tous deux susceptibles de bouger. La leçon des compteurs de
    sujets vaut ici — ce qui se déduit ne s'accumule pas.
    """
    factory = get_session_factory()
    async with factory() as db:
        # Blocage par (sujet, locuteur) : une redite tombe toujours dans le même
        # sujet que son original, et comparer tout le corpus à lui-même coûterait
        # des millions de produits scalaires pour rien.
        blocs = (await db.execute(
            select(Claim.subject_id, Claim.speaker_name)
            .where(Claim.subject_id.isnot(None), Claim.speaker_name.isnot(None))
            .group_by(Claim.subject_id, Claim.speaker_name)
            .having(func.count(Claim.id) > 1)
        )).all()

        redites = representants = 0
        for sujet_id, locuteur in blocs:
            claims = list((await db.execute(
                select(Claim).where(Claim.subject_id == sujet_id,
                                    Claim.speaker_name == locuteur)
            )).scalars().all())
            for groupe in grouper(claims):
                tete, suite = groupe[0], groupe[1:]
                tete.duplicate_of = None
                tete.n_reprises = len(suite)
                representants += 1
                for c in suite:
                    c.duplicate_of = tete.id
                    c.n_reprises = 0
                    redites += 1
        await db.commit()

    out = {"prises_de_position": representants, "redites": redites}
    logger.info("redites.done", **out)
    return out
