"""Chaque page se charge sans erreur JavaScript.

Deux fois dans la même journée, une page s'est chargée vide sans que rien ne le
signale : une variable supprimée par mégarde avec le bloc voisin, et la page de
validation restait blanche. Aucun test ne pouvait le voir — la suite couvre le
backend, et le front n'est exécuté nulle part.

Ce test ne juge pas l'apparence. Il ouvre chaque page dans un navigateur, la
laisse appeler l'API, et échoue si la console rapporte une erreur. C'est le
minimum qui distingue « la page existe » de « la page marche ».

Il s'ignore proprement quand Playwright n'est pas installé : la suite doit
rester exécutable sans navigateur.
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="navigateur absent")

RACINE = Path(__file__).resolve().parents[1]
PAGES = ["index", "sujets", "sujet", "figure", "revue", "engagements",
         "archive", "contradictions", "compteur", "atelier", "codage"]

# Bruit extérieur : les portraits viennent d'un service tiers qui refuse parfois
# la requête. Un 403 sur une image n'est pas un défaut de la page.
IGNORE = ("403", "404", "net::ERR", "favicon")


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def serveur():
    port = _port_libre()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.app:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
        cwd=RACINE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.skip("le serveur n'a pas démarré")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_every_page_loads_without_a_script_error(serveur):
    """Une erreur de script laisse une page blanche sous un bandeau intact :
    de l'extérieur, ça ressemble à « il n'y a pas encore de données »."""
    from playwright.sync_api import sync_playwright

    fautes: dict[str, list[str]] = {}
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        for nom in PAGES:
            erreurs: list[str] = []
            page = nav.new_page(viewport={"width": 1280, "height": 900})
            page.on("pageerror", lambda e: erreurs.append(str(e)))
            page.on("console",
                    lambda m: erreurs.append(m.text) if m.type == "error" else None)
            page.goto(f"{serveur}/{nom}.html", wait_until="networkidle")
            page.wait_for_timeout(800)
            page.close()
            reelles = [e for e in erreurs if not any(b in e for b in IGNORE)]
            if reelles:
                fautes[nom] = reelles[:3]
        nav.close()

    assert not fautes, f"erreurs de script : {fautes}"
