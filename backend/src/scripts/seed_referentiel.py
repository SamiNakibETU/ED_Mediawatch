"""Charge data/referentiel.json en base (idempotent, versionné, aligné CAP).

    python -m src.scripts.seed_referentiel            # merge + prune sûr
    python -m src.scripts.seed_referentiel --no-prune # merge seul

Le `prune` réconcilie la base avec le fichier (référentiel versionné, cadre §7) :
les sous-thèmes et thèmes ABSENTS du fichier sont supprimés — mais UNIQUEMENT
s'ils sont devenus vides (sous-thème sans référent, thème sans sous-thème). Un
sous-thème portant encore des référents n'est jamais supprimé (cela cascaderait
sur les référents → `Claim.referent_key` SET NULL). Aucune donnée d'analyse n'est
détruite ; seules des coquilles de taxonomie réorganisées disparaissent.
"""

import asyncio
import json
import sys

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select

from src.config import BACKEND_DIR
from src.database import get_session_factory, init_db
from src.models.referentiel import Referent, Subtheme, Theme

logger = structlog.get_logger(__name__)
FILE = BACKEND_DIR / "data" / "referentiel.json"


async def seed(prune: bool = True) -> dict:
    data = json.loads(FILE.read_text(encoding="utf-8"))
    version = data["version"]
    file_theme_ids = {t["id"] for t in data["themes"]}
    file_sub_ids = {st["id"] for t in data["themes"] for st in t["subthemes"]}

    await init_db()
    factory = get_session_factory()
    n_themes = n_subs = n_refs = 0
    pruned_themes = pruned_subs = skipped = 0

    async with factory() as db:
        # 1) Upsert thèmes / sous-thèmes (re-parentés via theme_id) / référents.
        for t in data["themes"]:
            await db.merge(Theme(
                id=t["id"], label=t["label"], order=t.get("order", 0),
                version=version, code=t.get("code"), salience=t.get("salience"),
            ))
            n_themes += 1
            for st in t["subthemes"]:
                await db.merge(Subtheme(id=st["id"], theme_id=t["id"], label=st["label"]))
                n_subs += 1
                for r in st.get("referents", []):
                    await db.merge(Referent(
                        key=r["key"], subtheme_id=st["id"], label=r["label"],
                        unit=r.get("unit", ""), version=version,
                    ))
                    n_refs += 1
        await db.flush()

        # 2) Prune sûr (réconciliation), uniquement sur des coquilles vides.
        if prune:
            for sub in (await db.execute(select(Subtheme))).scalars().all():
                if sub.id in file_sub_ids:
                    continue
                n_ref = await db.scalar(
                    select(func.count(Referent.key)).where(Referent.subtheme_id == sub.id)
                )
                if n_ref:
                    logger.warning("seed_referentiel.skip_subtheme_with_referents",
                                   subtheme=sub.id, referents=n_ref)
                    skipped += 1
                else:
                    await db.execute(sa_delete(Subtheme).where(Subtheme.id == sub.id))
                    pruned_subs += 1
            for th in (await db.execute(select(Theme))).scalars().all():
                if th.id in file_theme_ids:
                    continue
                n_sub = await db.scalar(
                    select(func.count(Subtheme.id)).where(Subtheme.theme_id == th.id)
                )
                if n_sub:
                    logger.warning("seed_referentiel.skip_theme_with_subthemes",
                                   theme=th.id, subthemes=n_sub)
                    skipped += 1
                else:
                    await db.execute(sa_delete(Theme).where(Theme.id == th.id))
                    pruned_themes += 1
        await db.commit()

    stats = {
        "version": version, "themes": n_themes, "subthemes": n_subs, "referents": n_refs,
        "pruned_themes": pruned_themes, "pruned_subthemes": pruned_subs, "skipped": skipped,
    }
    logger.info("seed_referentiel.done", **stats)
    print(f"Référentiel chargé (CAP): {stats}")
    return stats


if __name__ == "__main__":
    asyncio.run(seed(prune="--no-prune" not in sys.argv))
