"""Pone fase0/ y fase0/datos_ejemplo/ en el path para que los tests importen los scripts."""
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
for p in (AQUI, AQUI / "datos_ejemplo"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
