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

from . import settings
from .db import cerrar
from .routers import admin, campo, cargas, empresas, estudios

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def ciclo(_app):
    yield
    cerrar()


app = FastAPI(title="Base de Empresas — Equipos", version="1.0.0", docs_url="/api/docs",
              openapi_url="/api/openapi.json", lifespan=ciclo)

if settings.CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["X-Renglones", "X-Items-Sin-Telefono", "X-Contactos-Incluidos", "Content-Disposition"])

for r in (empresas.router, cargas.router, estudios.router, campo.router, admin.router):
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
