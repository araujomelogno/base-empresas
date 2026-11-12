"""Catálogos de la carga v2: atributos de empresa y orígenes de teléfono (C1, C4).
Los ve cualquier usuario (los usan el mapeo, los filtros y la exportación); solo un
administrador los cambia. Cada cambio queda en la auditoría."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import catalogos
from ..auth import Usuario, requiere, usuario_actual
from ..db import get_conn

router = APIRouter()


class Atributo(BaseModel):
    clave: str | None = None
    nombre: str | None = None
    tipo: str | None = None
    opciones: list[str] | None = None
    sinonimos: list[str] | None = None
    filtrable: bool | None = None
    estratificable: bool | None = None
    activo: bool | None = None
    ambito: str | None = None


@router.get("/atributos")
def atributos(activos: bool | None = None, ambito: str | None = None, conn=Depends(get_conn),
              u: Usuario = Depends(usuario_actual)):
    return catalogos.atributos(conn, activos, ambito)


@router.post("/atributos")
def crear_atributo(body: Atributo, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return catalogos.crear_atributo(conn, body.model_dump(), u.email)


@router.put("/atributos/{atributo_id}")
def editar_atributo(atributo_id: int, body: Atributo, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return catalogos.actualizar_atributo(conn, atributo_id, body.model_dump(), u.email)


@router.delete("/atributos/{atributo_id}")
def borrar_atributo(atributo_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return catalogos.borrar_atributo(conn, atributo_id, u.email)


class Origen(BaseModel):
    codigo: str | None = None
    nombre: str | None = None
    prioridad: int | None = None
    activo: bool | None = None


class Orden(BaseModel):
    codigos: list[str]


@router.get("/origenes-telefono")
def origenes(activos: bool | None = None, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return catalogos.origenes(conn, activos)


@router.post("/origenes-telefono")
def crear_origen(body: Origen, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return catalogos.crear_origen(conn, body.model_dump(), u.email)


@router.put("/origenes-telefono/orden")
def ordenar_origenes(body: Orden, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return catalogos.ordenar_origenes(conn, body.codigos, u.email)


@router.put("/origenes-telefono/{origen_id}")
def editar_origen(origen_id: int, body: Origen, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return catalogos.actualizar_origen(conn, origen_id, body.model_dump(), u.email)


@router.delete("/origenes-telefono/{origen_id}")
def borrar_origen(origen_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return catalogos.borrar_origen(conn, origen_id, u.email)
