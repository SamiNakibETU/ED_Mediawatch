"""Diagnostic : le raffinage LLM des claims tourne-t-il, et que décide-t-il ?

Rejoue `ClaimLLM.refine` sur les claims déjà stockés (verbatim réel) et affiche,
pour chacun, la décision du LLM (valide ? référent confirmé/corrigé ?) + le temps.
Non destructif (aucune écriture). Sert à trancher entre « LLM inactif » et
« LLM actif mais imprécis ».

    railway ssh "python -m src.scripts.diag_llm"
"""

import asyncio
import time

from sqlalchemy import select

from src.database import get_session_factory
from src.models.claim import Claim
from src.models.referentiel import Referent, Subtheme
from src.services.analysis.claim_llm import get_claim_llm


async def main() -> None:
    llm = get_claim_llm()
    print("available (tier2):", llm.available())

    factory = get_session_factory()
    async with factory() as db:
        allowed = [
            (k, label)
            for k, label in (
                await db.execute(select(Referent.key, Referent.label).join(Subtheme))
            ).all()
        ]
        labels = dict(allowed)
        claims = list(
            (await db.execute(select(Claim).limit(20))).scalars().all()
        )

    print(f"{len(claims)} claims à re-tester · {len(allowed)} référents dans la grille\n")
    for c in claims:
        t0 = time.monotonic()
        refined = await llm.refine(
            sentence=c.verbatim,
            speaker=c.speaker_name,
            candidate_referent_key=c.referent_key,
            referent_label=labels.get(c.referent_key, c.referent_key),
            value=c.qty_value,
            unit=c.qty_unit or "",
            allowed=allowed,
        )
        dt = (time.monotonic() - t0) * 1000
        if refined is None:
            verdict = "None (échec/aucun provider)"
        else:
            verdict = (
                f"valid={refined.is_valid_claim} ref={refined.referent_key} "
                f"conf={refined.confidence}"
            )
        print(f"[{dt:6.0f} ms] {c.qty_value}{c.qty_unit} «{(c.verbatim or '')[:70]}…»")
        print(f"           candidat={c.referent_key}")
        print(f"           LLM → {verdict}\n")


if __name__ == "__main__":
    asyncio.run(main())
