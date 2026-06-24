"""Pytest bootstrap : rend le package `src` importable quel que soit le cwd.

Le code applicatif importe `from src...` (backend/ doit être sur le path).
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
