"""Conexiones a Cloud SQL Postgres (esquema `empresas`)."""
from contextlib import contextmanager

from fastapi import Request

from psycopg.rows import dict_row
from psycopg.types.json import set_json_dumps
from psycopg_pool import ConnectionPool

from . import settings
from .util import json_dumps

set_json_dumps(json_dumps)

_pool: ConnectionPool | None = None


def _opciones() -> str:
    o = "-c search_path=empresas,public -c timezone=" + settings.TZ
    if settings.DB_STATEMENT_TIMEOUT_MS > 0:  # D55: una consulta de la web no puede ocupar una conexión más de 15 s
        o += f" -c statement_timeout={settings.DB_STATEMENT_TIMEOUT_MS}"
    return o


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            settings.DATABASE_URL,
            min_size=1,
            max_size=max(2, settings.DB_POOL_MAX),
            kwargs={"row_factory": dict_row, "options": _opciones()},
            timeout=settings.DB_POOL_TIMEOUT,   # D55: 10 s esperando una conexión libre, después 503 «base ocupada»
            open=True,
        )
    return _pool


def sin_limite(conn, segundos: float = 0):
    """Levanta (0) o cambia el tiempo máximo por consulta solo para esta transacción: tareas, jobs, descargas y el
    sorteo, que pueden tardar más que una pantalla."""
    conn.execute(f"SET LOCAL statement_timeout = {int(segundos * 1000)}")


def cerrar():
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def conexion():
    """Conexión en una transacción: commit al salir bien, rollback si hay excepción."""
    with pool().connection() as conn:
        with conn.transaction():
            yield conn


# D55: rutas que no son pantallas y pueden tardar más que los 15 s de una consulta de la web
_SIN_LIMITE = ("/api/jobs/", "/api/tareas/")
_LIMITE_LARGO = (("/csv", 120), ("/sortear", 120), ("/muestras/marco", 120), ("/api/calidad", 60))


def limite_de_ruta(ruta: str) -> float | None:
    """Segundos por consulta para esa ruta (0: sin límite; None: el de la web)."""
    if ruta.startswith(_SIN_LIMITE):
        return 0
    for parte, seg in _LIMITE_LARGO:
        if parte in ruta:
            return seg
    return None


def get_conn(request: Request):
    """Dependencia de FastAPI."""
    with conexion() as conn:
        seg = limite_de_ruta(request.url.path) if settings.DB_STATEMENT_TIMEOUT_MS > 0 else None
        if seg is not None:
            sin_limite(conn, seg)
        yield conn
