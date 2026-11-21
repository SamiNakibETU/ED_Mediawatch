"""Tire les déclarations à relire à la main (critère 2 du plan : 90 % justes sur 200).

L'échantillon est stratifié par année et par figure, pour que les têtes d'affiche, qui pèsent
l'essentiel du registre, ne l'occupent pas seules : dans chaque année, on tourne entre les figures
et on prend une déclaration à la fois. Le tirage est reproductible (graine fixe).

Le classeur a une ligne par déclaration : la figure, la date, la question de l'enjeu, la position
lue, le passage cité, le tweet entier et son lien. Deux colonnes sont à remplir par relecteur :
un verdict (juste, faux, discutable) et un commentaire.

    python -m src.scripts.echantillon_controle [--n 200] [--sortie chemin.xlsx]
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ETUDE = BACKEND.parents[1]
GRAINE = 20261121


def tirer(n: int) -> list[dict]:
    from src.services.analysis.enjeux import PAR_SLUG

    db = sqlite3.connect(f"file:{BACKEND / 'ed_mediawatch.db'}?mode=ro", uri=True)
    rows = db.execute("""
        select d.id, d.published_at, pe.full_name, pe.group_code, d.enjeu, d.position, d.verbatim,
               p.content, p.url
        from declarations d join posts p on p.id = d.post_id
        join personalities pe on pe.id = d.personality_id
        where d.position is not null and (d.douteuse is null or d.douteuse = 0) and d.published_at is not null
    """).fetchall()
    rng = random.Random(GRAINE)
    par_annee: dict[str, dict[str, list]] = {}
    for r in rows:
        enjeu = PAR_SLUG.get(r[4])
        if enjeu is None or enjeu.cran(r[5]) is None:
            continue
        par_annee.setdefault(r[1][:4], {}).setdefault(r[2], []).append(r)
    annees = sorted(par_annee)
    total = sum(len(v) for a in par_annee.values() for v in a.values())
    tirage: list = []
    for a in annees:
        figures = par_annee[a]
        quota = max(1, round(n * sum(len(v) for v in figures.values()) / total))
        for v in figures.values():
            rng.shuffle(v)
        noms = sorted(figures)
        rng.shuffle(noms)
        pris, tour = [], 0
        while len(pris) < quota and any(figures[f] for f in noms):
            f = noms[tour % len(noms)]
            if figures[f]:
                pris.append(figures[f].pop())
            tour += 1
        tirage += pris
    rng.shuffle(tirage)
    out = []
    for r in tirage[:n]:
        enjeu = PAR_SLUG[r[4]]
        out.append({"id": r[0], "date": r[1][:10], "figure": r[2], "parti": r[3] or "", "enjeu": enjeu.titre,
                    "question": enjeu.question, "position": enjeu.cran(r[5]).label, "passage": r[6] or "",
                    "tweet": r[7] or "", "lien": r[8] or ""})
    return sorted(out, key=lambda x: (x["date"], x["figure"]))


def ecrire(lignes: list[dict], sortie: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "Déclarations"
    entetes = ["N°", "Date", "Figure", "Parti", "Enjeu", "Question", "Position lue", "Passage cité",
               "Tweet entier", "Lien", "Verdict relecteur 1", "Commentaire 1", "Verdict relecteur 2", "Commentaire 2"]
    largeurs = [7, 11, 22, 8, 24, 38, 30, 50, 70, 30, 18, 32, 18, 32]
    ws.append(entetes)
    for i, l in enumerate(lignes, 1):
        ws.append([l["id"], l["date"], l["figure"], l["parti"], l["enjeu"], l["question"], l["position"],
                   l["passage"], l["tweet"], l["lien"], "", "", "", ""])
        if l["lien"]:
            ws.cell(row=i + 1, column=10).hyperlink = l["lien"]
    for col, largeur in zip("ABCDEFGHIJKLMN", largeurs):
        ws.column_dimensions[col].width = largeur
    for c in ws[1]:
        c.font = Font(bold=True)
    for ligne in ws.iter_rows(min_row=1):
        for c in ligne:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "C2"
    choix = DataValidation(type="list", formula1='"juste,faux,discutable"', allow_blank=True)
    ws.add_data_validation(choix)
    choix.add(f"K2:K{len(lignes) + 1}")
    choix.add(f"M2:M{len(lignes) + 1}")

    aide = wb.create_sheet("Consigne")
    for t in [
        "Pour chaque ligne, lire le tweet entier, puis dire si la position lue est bien celle que le tweet exprime.",
        "juste : l'auteur prend bien cette position sur cette question.",
        "faux : mauvaise position, mauvais enjeu, ou l'auteur rapporte la position d'un autre.",
        "discutable : la position se défend mais le tweet est ambigu, ironique ou conditionnel. Dire pourquoi.",
        "Chaque relecteur remplit ses deux colonnes sans regarder celles de l'autre.",
        "Critère du plan : au moins 90 % de « juste ».",
    ]:
        aide.append([t])
    aide.column_dimensions["A"].width = 120
    wb.save(sortie)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--n", type=int, default=200)
    p.add_argument("--sortie", type=Path,
                   default=ETUDE / "documents" / f"{date.today():%Y-%m-%d}_controle-200-declarations.xlsx")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    lignes = tirer(a.n)
    ecrire(lignes, a.sortie)
    annees: dict[str, int] = {}
    for l in lignes:
        annees[l["date"][:4]] = annees.get(l["date"][:4], 0) + 1
    print(f"{len(lignes)} déclarations, {len({l['figure'] for l in lignes})} figures, par année : {annees}")
    print(f"Écrit : {a.sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
