"""API de la Base de Empresas (Cloud Run).

Todas las rutas cuelgan de /api: Firebase Hosting reescribe /api/** al servicio de
Cloud Run. En desarrollo, si SERVE_WEB=1, la misma app sirve la web estática en /.
"""
import logging
import os
import pathlib
import time
from contextlib import asynccontextmanager

import psycopg
from psycopg_pool import PoolTimeout

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import migraciones, settings, tareas
from .db import cerrar
from .routers import admin, campo, cargas, catalogos, contactos, empresas, estudios, fase2, provisorias

logging.basicConfig(level=logging.INFO)


def _al_recibir_sigterm():
    """D52: en un despliegue o al cerrar la instancia, la tarea que está corriendo revierte su paso y vuelve a la
    cola para que la tome otra instancia. Se encadena con el manejo de uvicorn (que espera los pedidos en curso)."""
    import signal

    previo = signal.getsignal(signal.SIGTERM)

    def manejar(signum, frame):
        tareas.apagar()
        logging.getLogger(__name__).warning("SIGTERM: las tareas en curso vuelven a la cola")
        if callable(previo):
            previo(signum, frame)
        elif previo == signal.SIG_DFL:
            raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, manejar)
    except ValueError:  # fuera del hilo principal (por ejemplo, en los tests)
        pass


@asynccontextmanager
async def ciclo(_app):
    _al_recibir_sigterm()
    try:
        migraciones.revisar_al_arrancar()   # R3: si falta una migración, que se vea en el log al arrancar
    except Exception:
        logging.getLogger(__name__).warning("No se pudo revisar las migraciones al arrancar", exc_info=True)
    yield
    cerrar()


app = FastAPI(title="Base de Empresas — Equipos", version="1.0.0", docs_url="/api/docs",
              openapi_url="/api/openapi.json", lifespan=ciclo)

if settings.CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["X-Renglones", "X-Items-Sin-Telefono", "X-Contactos-Incluidos", "Content-Disposition"])

for r in (empresas.router, contactos.router, provisorias.router, cargas.router, catalogos.router, estudios.router, campo.router, fase2.router, admin.router):
    app.include_router(r, prefix="/api")


@app.get("/api/salud")
def salud():
    return {"ok": True}


# ── P-5 (D55): la web no se queda esperando ni muestra «Error» ──
CONSULTA_LENTA = "La consulta tardó demasiado. Si hay una carga grande en curso, probá en unos minutos."
BASE_OCUPADA = "La base está ocupada; reintentá en unos segundos"


@app.exception_handler(psycopg.errors.QueryCanceled)
async def consulta_cancelada(request: Request, exc: Exception):
    """statement_timeout: la consulta se cortó a los 15 s y la conexión vuelve al pool para los demás."""
    logging.getLogger(__name__).warning("Consulta cortada por tiempo en %s %s: %s", request.method, request.url.path,
                                        str(exc).splitlines()[0] if str(exc) else "")
    return JSONResponse(status_code=503, content={"detail": CONSULTA_LENTA, "codigo": "consulta_lenta"})


@app.exception_handler(PoolTimeout)
async def pool_ocupado(request: Request, exc: Exception):
    logging.getLogger(__name__).warning("Sin conexión libre a la base en %s %s (pool)", request.method, request.url.path)
    return JSONResponse(status_code=503, content={"detail": BASE_OCUPADA, "codigo": "base_ocupada", "reintentar": True})


class PedidosLentos:
    """P-6: los pedidos que tardan más de 2 s quedan en el log con el endpoint, la duración y el usuario. Middleware
    ASGI puro: no cambia cómo viajan las respuestas ni las excepciones."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        t0, estado = time.monotonic(), {}

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                estado["codigo"] = mensaje["status"]
            await send(mensaje)
        try:
            await self.app(scope, receive, enviar)
        finally:
            seg = time.monotonic() - t0
            if seg > settings.PEDIDO_LENTO_SEGUNDOS:
                logging.getLogger("pedidos").warning(
                    "pedido lento: %s %s %.1f s usuario=%s estado=%s", scope.get("method"), scope["path"], seg,
                    (scope.get("state") or {}).get("usuario", "-"), estado.get("codigo", "error"))


app.add_middleware(PedidosLentos)


@app.exception_handler(Exception)
async def error_no_manejado(request: Request, exc: Exception):
    logging.exception("Error no manejado en %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Error interno: {type(exc).__name__}"})


if os.environ.get("SERVE_WEB") == "1":
    web = pathlib.Path(__file__).resolve().parents[2] / "web" / "public"
    app.mount("/", StaticFiles(directory=web, html=True), name="web")
