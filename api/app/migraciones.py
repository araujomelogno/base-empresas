"""R3 (D52): nunca código en producción sin su migración.

Al arrancar, la API compara las migraciones que trae el código (db/empresas/NNNN_*.sql, incluidas en la imagen) con
las aplicadas (public.empresas_migraciones). Si falta alguna, lo dice en el log y GET /api/me se lo avisa a los
administradores, que lo ven en una franja roja, en lugar de errores 500 sueltos.
"""
import logging
import pathlib
import time

from .db import pool

log = logging.getLogger(__name__)
DIR = pathlib.Path(__file__).resolve().parents[2] / "db" / "empresas"
_cache: tuple[float, list[str]] = (0.0, [])


def del_codigo() -> list[str]:
    return sorted(p.name for p in DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")) if DIR.is_dir() else []


def faltantes(cache_segundos: float = 60) -> list[str]:
    """Las migraciones del código que la base todavía no tiene (por nombre de archivo). Se consulta cada minuto."""
    global _cache
    if time.monotonic() - _cache[0] < cache_segundos:
        return _cache[1]
    codigo = del_codigo()
    try:
        with pool().connection() as c:
            hay = c.execute("SELECT to_regclass('public.empresas_migraciones') IS NOT NULL AS hay").fetchone()["hay"]
            aplicadas = {r["nombre"] for r in c.execute("SELECT nombre FROM public.empresas_migraciones")} if hay else set()
    except Exception:
        log.warning("No se pudo revisar si faltan migraciones", exc_info=True)
        return _cache[1]
    _cache = (time.monotonic(), [m for m in codigo if m not in aplicadas])
    return _cache[1]


def mensaje(faltan: list[str]) -> str:
    return f"Faltan migraciones: {', '.join(m[:4] for m in faltan)}. Corré `desplegar.sh migrar`"


def revisar_al_arrancar():
    faltan = faltantes(cache_segundos=0)
    if faltan:
        log.error(mensaje(faltan))
