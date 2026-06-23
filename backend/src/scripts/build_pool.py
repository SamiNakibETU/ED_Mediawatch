"""Generate the monitoring pool (RN + UDR deputies + curated far-right figures).

Two sources, merged:
  1. assemblee-nationale group membership (RN=123, UDR=16): names, official
     photos, circo — broad coverage of sitting deputies. Handles come from the
     reusable twitter_handles map (discourse-analysis project).
  2. aide/personnalites_extreme_droite.csv (curated, verified): party/official
     accounts, Reconquête, identitaires, polémistes + VERIFIED handles and a
     `famille`/`statut_verif` taxonomy. Authoritative for handles when verified.

Curated verified handles override inherited ones. Handles marked "(a confirmer)"
are stored as NULL on purpose — a wrong @ pollutes a watch more than an empty one.

    python -m src.scripts.build_pool
"""

import csv
import json
import sys
import unicodedata
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
REF = (
    REPO_ROOT / "_reference"
    / "Analyse_discursive_depute_fr_sur_conflit_Israelo_Palestinien"
    / "pipeline" / "collection" / "config"
)
DEPUTES_FILE = REF / "deputes_groupes_17e.json"
HANDLES_FILE = REF / "twitter_handles.json"
AIDE_CSV = REPO_ROOT / "aide" / "personnalites_extreme_droite.csv"
OUT_FILE = BACKEND_DIR / "data" / "pool_rn_udr.json"

TARGET_GROUPS = {"RN", "UDR"}


def normalize(name: str) -> str:
    name = name.replace("M.", " ").replace("Mme", " ")
    name = "".join(
        c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)
    ).lower()
    for ch in "'’.-_()":
        name = name.replace(ch, " ")
    return " ".join(name.split())


def clean_handle(raw: str) -> str | None:
    raw = (raw or "").strip().lstrip("@")
    if not raw or raw.lower() in {"x", ""} or "confirmer" in raw.lower():
        return None
    return raw


def famille_to_group(famille: str) -> str:
    f = famille.strip().lower()
    if f == "rn":
        return "RN"
    if f == "udr":
        return "UDR"
    return "FIGURE"


def build_handle_lookup(handles: dict[str, str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for raw_name, handle in handles.items():
        h = clean_handle(handle)
        if h:
            lookup[normalize(raw_name)] = h
    return lookup


def load_an_deputes() -> dict[str, dict]:
    deputes = json.loads(DEPUTES_FILE.read_text(encoding="utf-8"))
    lookup = build_handle_lookup(json.loads(HANDLES_FILE.read_text(encoding="utf-8")))
    pool: dict[str, dict] = {}
    for dep in deputes["deputes"]:
        if dep.get("groupe_actuel") not in TARGET_GROUPS:
            continue
        name = dep["nom_complet"]
        pool[normalize(name)] = {
            "full_name": name,
            "handle": lookup.get(normalize(name)),
            "group_code": dep["groupe_actuel"],
            "group_long": dep.get("groupe_long"),
            "famille": dep["groupe_actuel"],
            "role": "Député",
            "verif": "an_2024",
            "circo": dep.get("circo"),
            "departement": dep.get("departement"),
            "photo_url": dep.get("photo_url"),
            "an_id": dep.get("id"),
        }
    return pool


def merge_aide(pool: dict[str, dict]) -> int:
    added = 0
    with AIDE_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row["nom"].strip()
            key = normalize(name)
            handle = clean_handle(row.get("compte_X", ""))
            famille = row.get("famille", "").strip()
            verif = row.get("statut_verif", "").strip()
            role = row.get("fonction", "").strip() or None

            if key in pool:
                rec = pool[key]
                # Verified curated handle wins; otherwise keep AN handle.
                if handle and verif == "verifie":
                    rec["handle"] = handle
                    rec["verif"] = "verifie"
                rec["famille"] = famille or rec["famille"]
                if role:
                    rec["role"] = role
            else:
                pool[key] = {
                    "full_name": name,
                    "handle": handle,
                    "group_code": famille_to_group(famille),
                    "group_long": row.get("note", "").strip() or famille,
                    "famille": famille,
                    "role": role,
                    "verif": verif,
                    "circo": None,
                    "departement": None,
                    "photo_url": None,
                    "an_id": None,
                }
                added += 1
    return added


def main() -> int:
    for p in (DEPUTES_FILE, HANDLES_FILE, AIDE_CSV):
        if not p.exists():
            print(f"ERROR: missing {p}", file=sys.stderr)
            return 1

    pool = load_an_deputes()
    added = merge_aide(pool)
    records = list(pool.values())

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(
            {
                "version": "2.0",
                "description": "Pool RN+UDR (AN 17e) fusionné avec la liste curée extrême droite (aide/).",
                "groups": sorted({r["group_code"] for r in records}),
                "familles": sorted({r["famille"] for r in records if r["famille"]}),
                "count": len(records),
                "with_handle": sum(1 for r in records if r["handle"]),
                "personalities": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Pool écrit: {OUT_FILE}")
    print(f"  total={len(records)}  avec_handle={sum(1 for r in records if r['handle'])}")
    print(f"  AN deputes + {added} figures curées ajoutées")
    print(f"  familles: {sorted({r['famille'] for r in records if r['famille']})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
