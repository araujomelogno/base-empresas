"""Conexiones a Cloud SQL Postgres (esquema `empresas`)."""
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg.types.json import set_json_dumps
from psycopg_pool import ConnectionPool

from . import settings
from .util import json_dumps

set_json_dumps(json_dumps)

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            settings.DATABASE_URL,
            min_size=1,
            max_size=max(2, settings.DB_POOL_MAX),
            kwargs={"row_factory": dict_row, "options": "-c search_path=empresas,public -c timezone=" + settings.TZ},
            open=True,
        )
    return _pool


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


def get_conn():
    """Dependencia de FastAPI."""
    with conexion() as conn:
        yield conn
