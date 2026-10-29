"""Tests con Postgres real (como en paneles). Cada test arranca con el esquema recién migrado.

    TEST_DATABASE_URL=postgresql://postgres@localhost/empresas_test pytest
"""
import io
import os
import sys
import tempfile

import psycopg
import pytest

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@localhost/empresas_test")
os.environ.update({
    "DATABASE_URL": DSN, "AUTH_MODE": "dev", "TASKS_MODE": "inline", "JOB_TOKEN": "token-job",
    "TAREA_TOKEN": "token-tarea", "STORAGE_DIR": tempfile.mkdtemp(prefix="empresas-test-"),
})
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(RAIZ, "api"))
sys.path.insert(0, os.path.join(RAIZ, "db"))

import migrate  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import rut as rutmod  # noqa: E402
from app.main import app  # noqa: E402

USUARIOS = {
    "admin": "admin@equipos.com.uy", "steward": "steward@equipos.com.uy", "jefe": "jefe@equipos.com.uy",
    "coordinador": "coord@equipos.com.uy", "lectura": "lectura@equipos.com.uy",
}


def _crear_db():
    base, nombre = DSN.rsplit("/", 1)
    with psycopg.connect(base + "/postgres", autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nombre,)).fetchone():
            c.execute(f'CREATE DATABASE "{nombre}"')


@pytest.fixture(scope="session", autouse=True)
def _db_sesion():
    _crear_db()
    yield


@pytest.fixture(autouse=True)
def db(request):
    if request.module.__name__.endswith("test_unidad"):
        yield None  # reglas puras: no necesitan base
        return
    from app import db as appdb

    appdb.cerrar()  # el pool no debe reusar planes preparados sobre el esquema anterior
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS empresas CASCADE")
        c.execute("DROP TABLE IF EXISTS public.empresas_migraciones")
    migrate.aplicar(DSN, verbose=False)
    with psycopg.connect(DSN, autocommit=True) as c:
        for rol, email in USUARIOS.items():
            c.execute("INSERT INTO empresas.usuario (email, rol, exportar_contactos) VALUES (%s, %s, %s)",
                      (email, rol, rol in ("admin", "coordinador")))
    yield DSN


@pytest.fixture
def sql(db):
    """Conexión directa para preparar datos y verificar resultados."""
    from psycopg.rows import dict_row

    with psycopg.connect(db, autocommit=True, row_factory=dict_row,
                         options="-c search_path=empresas,public") as c:
        yield c


class Cliente:
    def __init__(self):
        self.c = TestClient(app, raise_server_exceptions=True)

    def _h(self, rol):
        return {"X-Dev-User": USUARIOS[rol]}

    def get(self, url, rol="admin", **kw):
        return self.c.get("/api" + url, headers=self._h(rol), **kw)

    def post(self, url, rol="admin", **kw):
        return self.c.post("/api" + url, headers=self._h(rol), **kw)

    def put(self, url, rol="admin", **kw):
        return self.c.put("/api" + url, headers=self._h(rol), **kw)

    def patch(self, url, rol="admin", **kw):
        return self.c.patch("/api" + url, headers=self._h(rol), **kw)

    def delete(self, url, rol="admin", **kw):
        return self.c.delete("/api" + url, headers=self._h(rol), **kw)

    def subir(self, url, nombre, contenido: bytes, rol="admin", **data):
        return self.c.post("/api" + url, headers=self._h(rol), files={"archivo": (nombre, io.BytesIO(contenido))},
                           data={k: str(v) for k, v in data.items() if v is not None})


@pytest.fixture
def api():
    return Cliente()


def rut_valido(n: int, registro: str = "21") -> str:
    """El n-ésimo RUT válido del registro (determinístico)."""
    k = 0
    i = 100000
    while True:
        base = f"{registro}{i:06d}001"
        dv = rutmod.digito_verificador(base)
        if dv is not None:
            if k == n:
                return base + str(dv)
            k += 1
        i += 1


def csv_bytes(filas: list[dict], sep=";") -> bytes:
    cols = list(filas[0].keys())
    lineas = [sep.join(cols)] + [sep.join("" if f.get(c) is None else str(f.get(c)) for c in cols) for f in filas]
    return ("\n".join(lineas) + "\n").encode("utf-8")


def cargar(api, filas, rol="steward", regla="rut", fuente="Base de prueba", tipo_fuente=None, confianza=None,
           confirmar=True, nombre="base.csv", contenido=None):
    """Sube, crea el preview y (opcional) confirma una carga. Devuelve el detalle de la carga.
    Por defecto la plantilla de mapeo se comparte entre archivos con las mismas columnas."""
    if tipo_fuente is None:
        tipo_fuente = "prueba:" + "|".join(sorted(filas[0])) if filas else "prueba"
    r = api.subir("/cargas/analizar", nombre, contenido or csv_bytes(filas), rol=rol, tipo_fuente=tipo_fuente)
    assert r.status_code == 200, r.text
    a = r.json()
    body = {"archivo_id": a["archivo_id"], "fuente": fuente, "tipo_fuente": tipo_fuente, "licencia": "uso interno",
            "regla_fusion": regla, "mapeo": a["mapeo"]}
    if confianza is not None:
        body["confianza"] = confianza
    r = api.post("/cargas", rol=rol, json=body)
    assert r.status_code == 200, r.text
    cid = r.json()["carga_id"]
    if confirmar:
        r = api.post(f"/cargas/{cid}/confirmar", rol=rol)
        assert r.status_code == 200, r.text
    return api.get(f"/cargas/{cid}").json()
