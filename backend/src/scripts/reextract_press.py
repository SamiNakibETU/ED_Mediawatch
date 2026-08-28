"""Remet la presse en file pour une extraction avec attribution du locuteur.

Pourquoi ce script existe. Jusqu'à `decl-v2`, aucun propos tiré d'un article ne
recevait de locuteur : la règle « sans attribution certaine, on n'attribue pas »
était appliquée en bloc, faute de savoir faire mieux. Résultat, toute la presse
tombait dans « non attribué » — donc hors de la comparaison, alors que rattacher
un propos à quelqu'un à une date est l'objet même du produit.

`decl-v3` fait dire au texte qui parle, déclaration par déclaration, et vérifie
le nom contre le papier. Les extractions antérieures restent muettes : elles ne
repasseront jamais toutes seules, puisque leur source est marquée comme traitée.
Ce script efface ces déclarations-là et rouvre leurs articles.

    python -m src.scripts.reextract_press            # dit ce qu'il ferait
    python -m src.scripts.reextract_press --apply    # le fait

Ne touche à rien d'autre : les propos issus de X gardent leur attribution, qui
n'a jamais été douteuse (le compte EST l'auteur).
"""

import asyncio
import sys

from sqlalchemy import delete, func, select, update

from src.database import get_session_factory, init_db
from src.models.article import Article
from src.models.claim import Claim
from src.services.analysis.claim_llm import DECLARATION_PROMPT_VERSION


def _obsolete():
    """Les déclarations de presse produites par un prompt antérieur."""
    return (
        Claim.extraction_method == "llm_segment",
        Claim.article_id.isnot(None),
        Claim.extraction_model.notlike(f"%{DECLARATION_PROMPT_VERSION}%"),
    )


async def main() -> None:
    apply = "--apply" in sys.argv
    await init_db()
    factory = get_session_factory()

    async with factory() as db:
        n = await db.scalar(select(func.count()).select_from(Claim).where(*_obsolete())) or 0
        arts = [r[0] for r in (await db.execute(
            select(Claim.article_id).where(*_obsolete()).distinct()
        )).all()]

        print(f"\nPrompt courant        : {DECLARATION_PROMPT_VERSION}")
        print(f"Déclarations à refaire : {n}")
        print(f"Articles à rouvrir     : {len(arts)}")

        if not n:
            print("\nRien à faire : la presse est déjà extraite avec le prompt courant.\n")
            return
        if not apply:
            print("\nRelance avec --apply pour effacer ces déclarations et rouvrir "
                  "leurs articles.\nLa prochaine passe complète les ré-extraira, "
                  "attribution comprise.\n")
            return

        await db.execute(delete(Claim).where(*_obsolete()))
        await db.execute(
            update(Article).where(Article.id.in_(arts)).values(l0_done_at=None)
        )
        await db.commit()

    print(f"\n{n} déclarations effacées, {len(arts)} articles rouverts.")
    print("La prochaine passe complète les ré-extrait, avec le locuteur.\n")


if __name__ == "__main__":
    asyncio.run(main())
