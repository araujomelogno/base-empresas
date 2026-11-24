"""Aplica las migraciones numeradas de db/empresas/ en orden.

Uso:
    DATABASE_URL=postgresql://... python db/migrate.py

Cada archivo NNNN_nombre.sql se aplica una sola vez, dentro de una transacción,
y queda registrado en public.empresas_migraciones.

Un archivo que empieza con «-- migrate: sin-transaccion» (D55) se ejecuta sentencia por sentencia, fuera de una
transacción: es lo que necesita CREATE INDEX CONCURRENTLY, que arma el índice sin bloquear la aplicación. Si un
intento anterior dejó un índice a medio armar (inválido), se borra y se vuelve a crear. Al final se informa el tamaño
de cada índice.
"""
import os
import pathlib
import re
import sys

import psycopg

DIR = pathlib.Path(__file__).parent / "empresas"


def migraciones():
    return sorted(p for p in DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


SIN_TRANSACCION = "-- migrate: sin-transaccion"
_INDICE = re.compile(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+CONCURRENTLY\s+IF\s+NOT\s+EXISTS\s+(\w+)\s+ON\s+(\w+)\.", re.I)


def sentencias(texto: str) -> list[str]:
    """Las sentencias de un archivo sin transacción: sin comentarios, separadas por «;» al final de la línea."""
    limpio = "\n".join(linea for linea in texto.splitlines() if not linea.strip().startswith("--"))
    return [s.strip() for s in re.split(r";\s*(?:\n|$)", limpio) if s.strip()]


def _sin_transaccion(conn, texto: str, verbose: bool):
    indices = []
    for sql in sentencias(texto):
        m = _INDICE.search(sql)
        if m:
            nombre, esquema = m.group(1), m.group(2)
            invalido = conn.execute(
                "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace"
                " WHERE c.relname = %s AND n.nspname = %s AND NOT i.indisvalid", (nombre, esquema)).fetchone()
            if invalido:  # quedó a medio armar en un intento anterior (por ejemplo, el job se cortó)
                conn.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{esquema}"."{nombre}"')
            indices.append((esquema, nombre))
        conn.execute(sql)
    if verbose:
        for esquema, nombre in indices:
            r = conn.execute("SELECT pg_size_pretty(pg_relation_size(c.oid)) FROM pg_class c JOIN pg_namespace n"
                             " ON n.oid = c.relnamespace WHERE c.relname = %s AND n.nspname = %s", (nombre, esquema)).fetchone()
            print(f"  índice {nombre}: {r[0] if r else '?'}")


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
            texto = p.read_text(encoding="utf-8")
            if texto.startswith(SIN_TRANSACCION):
                _sin_transaccion(conn, texto, verbose)
                conn.execute("INSERT INTO public.empresas_migraciones (nombre) VALUES (%s)", (p.name,))
            else:
                with conn.transaction():
                    conn.execute(texto)
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
