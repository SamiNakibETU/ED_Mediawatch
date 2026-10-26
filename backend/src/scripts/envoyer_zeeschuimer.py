"""Envoie un ou plusieurs exports Zeeschuimer à la plateforme en ligne.

    python -m src.scripts.envoyer_zeeschuimer export1.ndjson [export2.ndjson ...]

Le jeton est lu dans la variable d'environnement API_TOKEN (le même que sur
Railway). L'adresse vient de ED_URL, par défaut la production.
"""

import json
import os
import sys
import urllib.request

URL = os.environ.get("ED_URL", "https://edmediawatch-production.up.railway.app")


def main() -> None:
    jeton = os.environ.get("API_TOKEN", "").strip()
    if not jeton:
        sys.exit("API_TOKEN manquant : définis-le avant d'envoyer.")
    for chemin in sys.argv[1:]:
        with open(chemin, "rb") as f:
            corps = f.read()
        req = urllib.request.Request(f"{URL}/collect/zeeschuimer", data=corps, method="POST",
                                     headers={"X-API-Token": jeton, "Content-Type": "application/x-ndjson"})
        with urllib.request.urlopen(req, timeout=300) as r:
            bilan = json.load(r)
        print(f"{os.path.basename(chemin)} : {bilan['tweets_lus']} tweets lus, {bilan['nouveaux']} nouveaux, "
              f"{bilan['figures']} figures, {bilan['hors_panel']} hors panel")


if __name__ == "__main__":
    main()
