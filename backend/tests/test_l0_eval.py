"""Scoring de l'éval L0 : précision, précision par type, rappel estimé."""

import csv
from pathlib import Path

from src.services.analysis.l0_eval import score


def _write_decls(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["claim_id", "source_ref", "speaker", "claim_type", "theme",
                    "verbatim", "canonical", "label"])
        w.writerows(rows)


def test_precision_and_by_type(tmp_path):
    p = tmp_path / "d.csv"
    _write_decls(p, [
        [1, "post1", "X", "normatif", "immigration", "v", "c", "1"],
        [2, "post1", "X", "normatif", "immigration", "v", "c", "0"],
        [3, "post2", "X", "factuel_quantitatif", "economie", "v", "c", "1"],
        [4, "post2", "X", "factuel_quantitatif", "economie", "v", "c", "1"],
        [5, "post3", "X", "predictif", "", "v", "c", ""],  # non annoté → ignoré
    ])
    out = score(p)
    assert out["annotated"] == 4
    assert out["precision"] == 0.75
    assert out["precision_by_type"]["normatif"]["precision"] == 0.5
    assert out["precision_by_type"]["factuel_quantitatif"]["precision"] == 1.0


def test_recall_estimate_with_sources(tmp_path):
    d = tmp_path / "d.csv"
    _write_decls(d, [
        [1, "post1", "X", "normatif", "t", "v", "c", "1"],
        [2, "post2", "X", "normatif", "t", "v", "c", "1"],
        [3, "post2", "X", "normatif", "t", "v", "c", "1"],
    ])
    s = tmp_path / "s.csv"
    with s.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["source_ref", "platform", "n_extracted", "text", "missed"])
        w.writerow(["post1", "x", 1, "…", "1"])
        w.writerow(["post2", "x", 2, "…", "0"])
        w.writerow(["post3", "x", 0, "…", ""])  # non annoté → ignoré
    out = score(d, s)
    # 3 corrects, 1 raté → rappel 3/4.
    assert out["sources_annotated"] == 2
    assert out["missed_total"] == 1
    assert out["recall_estimate"] == 0.75


def test_empty_annotation(tmp_path):
    p = tmp_path / "d.csv"
    _write_decls(p, [[1, "post1", "X", "normatif", "t", "v", "c", ""]])
    assert "error" in score(p)
