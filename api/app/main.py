"""API de la Base de Empresas (Cloud Run).

Todas las rutas cuelgan de /api: Firebase Hosting reescribe /api/** al servicio de
Cloud Run. En desarrollo, si SERVE_WEB=1, la misma app sirve la web estática en /.
"""
import logging
import os
import pathlib
from contextlib import asynccontextmanager

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


@app.exception_handler(Exception)
async def error_no_manejado(request: Request, exc: Exception):
    logging.exception("Error no manejado en %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Error interno: {type(exc).__name__}"})


if os.environ.get("SERVE_WEB") == "1":
    web = pathlib.Path(__file__).resolve().parents[2] / "web" / "public"
    app.mount("/", StaticFiles(directory=web, html=True), name="web")
