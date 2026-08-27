"""Protocole d'évaluation du L0 (précision / rappel sur annotation humaine).

Le Grand Livre ne vaut que si l'extraction est mesurée (plan phase 1 : ~200
déclarations annotées avant d'ouvrir aux 168 figures). Deux moments :

  1. `export_for_annotation()` → deux CSV dans data/eval/ :
       * declarations : chaque claim extrait (verbatim, canonical, type, thème)
         avec une colonne `label` à remplir à la main —
         1 = correcte (fidèle + bien typée), 0 = fausse/inventée/mal découpée.
       * sources : chaque source segmentée (texte complet) avec une colonne
         `missed` — nombre d'assertions analysables que le LLM a RATÉES.
  2. `score(...)` → précision = moyenne des labels ; rappel estimé =
       corrects / (corrects + ratés). Par type de claim aussi (le quantitatif
       et le normatif n'échouent pas pareil).

Aucun appel LLM ici : on évalue ce que `run_declaration_extraction` a déjà écrit.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import select

from src.database import get_session_factory
from src.models.article import Article
from src.models.claim import Claim
from src.models.post import Post

logger = structlog.get_logger(__name__)

EVAL_DIR = Path(__file__).resolve().parents[3] / "data" / "eval"


async def export_for_annotation(limit: int = 250) -> dict:
    """Exporte les derniers claims `llm_segment` + leurs sources, à annoter."""
    factory = get_session_factory()
    async with factory() as db:
        claims = list(
            (
                await db.execute(
                    select(Claim)
                    .where(Claim.extraction_method == "llm_segment")
                    .order_by(Claim.id.desc())
                    .limit(limit)
                )
            ).scalars().all()
        )
        # Textes sources (pour juger fidélité et rappel).
        post_ids = {c.post_id for c in claims if c.post_id}
        art_ids = {c.article_id for c in claims if c.article_id}
        posts = {
            p.id: p
            for p in (
                await db.execute(select(Post).where(Post.id.in_(post_ids or {0})))
            ).scalars()
        }
        arts = {
            a.id: a
            for a in (
                await db.execute(select(Article).where(Article.id.in_(art_ids or {0})))
            ).scalars()
        }

    if not claims:
        return {"exported": 0, "note": "aucun claim llm_segment (lancer extract_declarations)"}

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    decl_path = EVAL_DIR / f"l0_declarations_{stamp}.csv"
    src_path = EVAL_DIR / f"l0_sources_{stamp}.csv"

    with decl_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(
            ["claim_id", "source_ref", "speaker", "claim_type", "theme",
             "verbatim", "canonical", "label"]
        )
        for c in claims:
            ref = f"post{c.post_id}" if c.post_id else f"art{c.article_id}"
            w.writerow(
                [c.id, ref, c.speaker_name or "", c.claim_type, c.theme or "",
                 c.verbatim, c.canonical or "", ""]
            )

    seen: set[str] = set()
    with src_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["source_ref", "platform", "n_extracted", "text", "missed"])
        counts: dict[str, int] = {}
        for c in claims:
            ref = f"post{c.post_id}" if c.post_id else f"art{c.article_id}"
            counts[ref] = counts.get(ref, 0) + 1
        for c in claims:
            ref = f"post{c.post_id}" if c.post_id else f"art{c.article_id}"
            if ref in seen:
                continue
            seen.add(ref)
            if c.post_id and c.post_id in posts:
                text, platform = posts[c.post_id].content or "", "x"
            elif c.article_id and c.article_id in arts:
                a = arts[c.article_id]
                text, platform = f"{a.title}. {a.content or ''}"[:4000], "press"
            else:
                text, platform = "", "?"
            w.writerow([ref, platform, counts[ref], text, ""])

    logger.info("l0_eval.exported", declarations=len(claims), sources=len(seen))
    return {
        "exported": len(claims),
        "sources": len(seen),
        "declarations_csv": str(decl_path),
        "sources_csv": str(src_path),
        "consigne": "label : 1=correcte, 0=fausse/mal découpée ; missed : assertions ratées par source",
    }


def score(declarations_csv: Path | str, sources_csv: Path | str | None = None) -> dict:
    """Précision (et rappel si le CSV sources annoté est fourni)."""
    labels: list[int] = []
    by_type: dict[str, list[int]] = {}
    with Path(declarations_csv).open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter=";"):
            raw = (row.get("label") or "").strip()
            if raw not in {"0", "1"}:
                continue  # non annoté → ignoré
            lab = int(raw)
            labels.append(lab)
            by_type.setdefault(row.get("claim_type") or "?", []).append(lab)

    if not labels:
        return {"error": "aucune ligne annotée (colonne label vide)"}

    correct = sum(labels)
    out: dict = {
        "annotated": len(labels),
        "precision": round(correct / len(labels), 3),
        "precision_by_type": {
            t: {"n": len(v), "precision": round(sum(v) / len(v), 3)}
            for t, v in sorted(by_type.items())
        },
    }

    if sources_csv:
        missed = 0
        n_sources = 0
        with Path(sources_csv).open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter=";"):
                raw = (row.get("missed") or "").strip()
                if not raw.isdigit():
                    continue
                missed += int(raw)
                n_sources += 1
        if n_sources:
            out["sources_annotated"] = n_sources
            out["missed_total"] = missed
            out["recall_estimate"] = round(correct / (correct + missed), 3) if (correct + missed) else None
    return out
