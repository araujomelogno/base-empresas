"""Cargas de bases y bandeja de revisión (R1.3)."""
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel

from .. import borrado, cargas, storage, tareas
from ..auth import Usuario, requiere, usuario_actual
from ..db import conexion, get_conn

router = APIRouter()


@router.post("/cargas/analizar")
def analizar(archivo: UploadFile = File(...), tipo_fuente: str | None = Form(None),
             u: Usuario = Depends(requiere("steward"))):
    datos = archivo.file.read()
    with conexion() as conn:
        a = storage.guardar(conn, archivo.filename or "archivo", datos, u.email)
        return cargas.analizar(conn, a, tipo_fuente)


class NuevaCarga(BaseModel):
    archivo_id: int
    fuente: str
    tipo_fuente: str
    licencia: str
    regla_fusion: str | None = None      # API anterior (una sola regla); reglas la reemplaza
    reglas: list[dict] | None = None     # F6.2: [{criterio, tipo, umbral}] en orden
    destino: str = "definitiva"          # F6.1: definitiva | provisoria
    opciones: dict | None = None         # con_rut_a_definitiva, sin_rut_a_provisoria
    confianza: int | None = None
    mapeo: dict
    guardar_plantilla: bool = True


class Decisiones(BaseModel):
    decisiones: dict[str, str]


@router.post("/cargas")
def crear(body: NuevaCarga, u: Usuario = Depends(requiere("steward"))):
    with conexion() as conn:
        r = cargas.crear(conn, body.archivo_id, body.fuente, body.tipo_fuente, body.licencia, body.regla_fusion,
                         body.confianza, body.mapeo, body.guardar_plantilla, u.email, body.destino, body.reglas, body.opciones)
    tareas.despachar(r["tarea_id"])
    return r


class Valores(BaseModel):
    archivo_id: int
    mapeo: dict


@router.post("/cargas/valores")
def valores(body: Valores, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    """Valores de origen y de atributos de lista que hay que traducir al catálogo antes del preview."""
    return cargas.valores(conn, body.archivo_id, body.mapeo)


@router.get("/cargas")
def listar(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return cargas.listar(conn)


@router.get("/cargas/plantillas")
def plantillas(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return conn.execute("SELECT * FROM carga_plantilla ORDER BY tipo_fuente").fetchall()


@router.get("/cargas/{carga_id}")
def obtener(carga_id: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return cargas.obtener(conn, carga_id)


@router.post("/cargas/{carga_id}/confirmar")
def confirmar(carga_id: int, u: Usuario = Depends(requiere("steward"))):
    with conexion() as conn:
        tid = cargas.confirmar(conn, carga_id, u.email)
    tareas.despachar(tid)
    return {"tarea_id": tid}


@router.put("/cargas/{carga_id}/decisiones")
def decisiones(carga_id: int, body: Decisiones, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    return cargas.guardar_decisiones(conn, carga_id, body.decisiones, u.email)


@router.delete("/cargas/{carga_id}")
def deshacer(carga_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    return cargas.deshacer(conn, carga_id, u.email)


@router.get("/cargas/{carga_id}/borrado")
def conteos_borrado(carga_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    """Lo que se borraría con la carga y qué tareas se cancelarían (para el modal de confirmación)."""
    return borrado.conteos_carga(conn, carga_id)


@router.delete("/cargas/{carga_id}/definitivo")
def borrar(carga_id: int, u: Usuario = Depends(requiere("admin"))):
    """Borrado definitivo (solo administrador): corre como tarea porque puede tocar miles de empresas."""
    with conexion() as conn:
        tid = borrado.pedir_borrado_carga(conn, carga_id, u.email)
    tareas.despachar(tid)
    return {"tarea_id": tid}


@router.get("/revision")
def revision(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return cargas.revision_pendiente(conn)


class Accion(BaseModel):
    accion: str


@router.post("/revision/{revision_id}")
def resolver_revision(revision_id: int, body: Accion, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    return cargas.resolver_revision(conn, revision_id, body.accion, u.email)
