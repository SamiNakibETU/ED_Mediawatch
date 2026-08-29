"""État du codage thématique, et recodage forcé.

    python -m src.scripts.recode_cap                    # état
    python -m src.scripts.recode_cap --apply            # code ce qui manque
    python -m src.scripts.recode_cap --apply --limit N

Le codage tourne normalement tout seul, comme étape du pipeline (`cap_coding`).
Ce script sert à deux choses : voir où on en est, et forcer une passe sans
attendre le cycle — typiquement après un changement de consigne, qui fait
évoluer la signature du codeur et remet donc tout le corpus en file.

Pour mesurer la QUALITÉ du codage, ce n'est pas ici : `eval_cap.py`.
"""

import asyncio
import sys

from sqlalchemy import func, select

from src.database import get_session_factory, init_db
from src.models.claim import Claim
from src.services.analysis.cap import CAP_VERSION, coder_signature
from src.services.analysis.cap_coder import _todo_filter, code_claims, distribution
from src.services.analysis.claim_llm import get_claim_llm


def _arg(name: str, default: int) -> int:
    if name in sys.argv:
        try:
            return int(sys.argv[sys.argv.index(name) + 1])
        except (IndexError, ValueError):
            pass
    return default


async def _report() -> None:
    factory = get_session_factory()
    async with factory() as db:
        total = await db.scalar(select(func.count()).select_from(Claim)) or 0
        reste = await db.scalar(
            select(func.count()).select_from(Claim).where(_todo_filter())) or 0
        coders = (await db.execute(
            select(Claim.cap_version, func.count())
            .where(Claim.cap_version.isnot(None))
            .group_by(Claim.cap_version))).all()

    print(f"\nCorpus       : {total} déclarations")
    print(f"À coder      : {reste}")
    print(f"Codeur actif : {coder_signature(get_claim_llm()._s.claim_tier1_model)}")
    if coders:
        print("\nCodeurs présents en base :")
        for sig, n in coders:
            marque = "" if str(sig).startswith(CAP_VERSION) else "  ← périmé"
            print(f"  {n:5d}  {sig}{marque}")

    rows = await distribution()
    if rows:
        print("\nRépartition de l'attention :")
        for r in rows:
            print(f"  {r['part']:5.1f} %  {r['n']:5d}  {r['label']}")


async def main() -> None:
    await init_db()
    await _report()
    if "--apply" not in sys.argv:
        print("\nRelance avec --apply pour coder ce qui manque.\n")
        return
    stats = await code_claims(limit=_arg("--limit", 1500))
    print(f"\nCodés : {stats['coded']}  ·  sans topique : {stats['no_topic']}"
          f"  ·  restant : {stats['remaining']}\n")


if __name__ == "__main__":
    asyncio.run(main())
