"""Aplica las migraciones numeradas de db/empresas/ en orden.

Uso:
    DATABASE_URL=postgresql://... python db/migrate.py

Cada archivo NNNN_nombre.sql se aplica una sola vez, dentro de una transacción,
y queda registrado en public.empresas_migraciones.
"""
import os
import pathlib
import sys

import psycopg

DIR = pathlib.Path(__file__).parent / "empresas"


def migraciones():
    return sorted(p for p in DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def aplicar(dsn: str, verbose: bool = True) -> list[str]:
    aplicadas = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS public.empresas_migraciones ("
            " nombre text PRIMARY KEY, aplicada timestamptz NOT NULL DEFAULT now())"
        )
        hechas = {r[0] for r in conn.execute("SELECT nombre FROM public.empresas_migraciones")}
        for p in migraciones():
            if p.name in hechas:
                continue
            with conn.transaction():
                conn.execute(p.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO public.empresas_migraciones (nombre) VALUES (%s)", (p.name,))
            aplicadas.append(p.name)
            if verbose:
                print(f"aplicada {p.name}")
    return aplicadas


if __name__ == "__main__":
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("Falta DATABASE_URL")
    hechas = aplicar(dsn)
    if not hechas:
        print("Sin migraciones pendientes")
