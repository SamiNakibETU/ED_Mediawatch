"""Lecture par l'abonnement ChatGPT de Sami, au moyen de Codex CLI (`codex exec`).

Choix de Sami (18/11/2026) : l'abonnement plutôt qu'une facture à l'appel. Codex
CLI, connecté au compte ChatGPT, rend le même service qu'une API : une consigne,
une réponse JSON. Trois différences avec un fournisseur à clé :

- **Le préambule de Codex pèse ~20 000 tokens par appel** (mesuré le 18/11 :
  22 114 tokens pour ranger un seul tweet, 35 s). D'où des lots plus gros que chez
  OpenRouter (`LOTS`) : le préambule se paie une fois par lot, pas par tweet.
- **Le coût est nul, le quota ne l'est pas.** L'abonnement a des fenêtres d'usage.
  Un dépassement remonte en `ProviderRefused` : la passe s'arrête, rien n'est marqué,
  les tweets repasseront.
- **Seuls les modèles ouverts au compte ChatGPT marchent** (`codex_model`). Le modèle
  par défaut de la config de Codex (gpt-6.1-terra) est refusé : on le fixe ici.

Codex tourne dans un dossier vide, en lecture seule, sans règles ni mémoire
(`--ephemeral --ignore-rules`) : il ne voit que la consigne, jamais le dépôt.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Lots par tâche quand on lit par Codex (au lieu de 25 au filtre, 8 à l'extraction).
LOTS = {"filtre": 80, "extraction": 25}

# Messages de Codex qui signalent un refus durable : réessayer n'y change rien.
_QUOTA = re.compile(r"usage limit|rate limit|quota|too many requests|not supported when using codex|"
                    r"model_not_found|log in|login|unauthorized", re.IGNORECASE)
_TOKENS = re.compile(r"tokens used\s*\n\s*([\d\s ,.]+)", re.IGNORECASE)

# Deux appels à la fois au plus : l'abonnement est un compte, pas une ferme.
_SEM = asyncio.Semaphore(int(os.environ.get("CODEX_PARALLELE", "2")))


class CodexRefus(RuntimeError):
    """Codex refuse (quota, modèle, connexion) : inutile de réessayer tout de suite."""


@dataclass
class Reponse:
    texte: str
    tokens: int


def binaire(nom: str = "codex") -> str:
    """Chemin complet : sous Windows, `codex` est un `codex.cmd` que l'exécution directe ne trouve pas."""
    chemin = shutil.which(nom)
    if not chemin:
        raise CodexRefus(f"Codex CLI introuvable ({nom}) : installer avec `npm i -g @openai/codex`, puis `codex login`")
    return chemin


def consigne(system: str, prompt: str) -> str:
    return (f"{system.strip()}\n\n---\n\n{prompt.strip()}\n\n---\n\n"
            "Réponds uniquement par l'objet JSON demandé, sans texte autour, sans bloc de code. "
            "N'ouvre aucun fichier, ne lance aucune commande : tout ce qu'il faut est ci-dessus.")


def tokens_de(journal: str) -> int:
    m = _TOKENS.search(journal)
    return int(re.sub(r"\D", "", m.group(1)) or 0) if m else 0


async def demander(system: str, prompt: str, *, model: str, effort: str = "low",
                   timeout: float = 900, codex: str = "codex") -> Reponse:
    """Une question, une réponse texte (le JSON est validé par l'appelant)."""
    exe = binaire(codex)
    async with _SEM:
        with tempfile.TemporaryDirectory(prefix="codex-lecture-") as d:
            sortie = Path(d) / "reponse.txt"
            proc = await asyncio.create_subprocess_exec(
                exe, "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-rules",
                "-s", "read-only", "--color", "never", "-C", d,
                "-m", model, "-c", f"model_reasoning_effort={effort}",
                "-o", str(sortie), "-",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, cwd=d,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(consigne(system, prompt).encode("utf-8")), timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError(f"Codex n'a pas répondu en {timeout:.0f} s")
            journal = out.decode("utf-8", errors="replace")
            texte = sortie.read_text(encoding="utf-8") if sortie.exists() else ""
    erreurs = [l for l in journal.splitlines() if l.startswith("ERROR") and "models_manager" not in l]
    if not texte.strip():
        motif = erreurs[-1] if erreurs else journal[-400:]
        if _QUOTA.search(motif):
            raise CodexRefus(f"Codex refuse : {motif[:300]}")
        raise RuntimeError(f"Codex sans réponse (code {proc.returncode}) : {motif[:300]}")
    return Reponse(texte=texte, tokens=tokens_de(journal))
