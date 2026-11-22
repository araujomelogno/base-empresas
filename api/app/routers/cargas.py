"""Cargas de bases y bandeja de revisión (R1.3)."""
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel

from .. import lotes, borrado, cargas, storage, tareas
from ..auth import Usuario, requiere, usuario_actual
from ..db import conexion, get_conn

router = APIRouter()


@router.post("/cargas/analizar")
def analizar(archivo: UploadFile = File(...), tipo_fuente: str | None = Form(None),
             u: Usuario = Depends(requiere("steward"))):
    """Guarda el archivo y lo lee una sola vez (D51): sus filas quedan para la traducción, la validación y los lotes.
    Un archivo grande se lee en segundo plano: responde enseguida con {archivo_id, tarea_id} y el análisis es el
    resultado de la tarea «archivo.leer»."""
    datos = archivo.file.read()
    with conexion() as conn:
        a = storage.guardar(conn, archivo.filename or "archivo", datos, u.email)
        if not cargas.es_grande(datos, a["tipo"]):
            return cargas.analizar(conn, a, tipo_fuente)
        tid = tareas.crear(conn, "archivo.leer", {"archivo_id": a["id"], "tipo_fuente": tipo_fuente}, u.email)
        conn.execute("UPDATE tarea SET mensaje = 'Leyendo el archivo…' WHERE id = %s", (tid,))
    tareas.despachar(tid)
    return {"archivo_id": a["id"], "nombre": a["nombre"], "tarea_id": tid}


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
    clave: str | None = None             # A4 (D51): la web la genera al abrir el mapeo; dos pedidos, una carga


class Decisiones(BaseModel):
    decisiones: dict[str, str]


@router.post("/cargas")
def crear(body: NuevaCarga, u: Usuario = Depends(requiere("steward"))):
    with conexion() as conn:
        r = cargas.crear(conn, body.archivo_id, body.fuente, body.tipo_fuente, body.licencia, body.regla_fusion,
                         body.confianza, body.mapeo, body.guardar_plantilla, u.email, body.destino, body.reglas, body.opciones,
                         (body.clave or "").strip()[:100] or None)
    if not r.get("existente"):  # la carga que ya existía sigue con su tarea
        tareas.despachar(r["tarea_id"])
    return r


@router.get("/cargas/en-curso")
def en_curso(archivo_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    """A4: la carga de este archivo que la misma persona está creando, para ofrecer «Ir a la carga #N»."""
    return {"carga": cargas.en_curso(conn, archivo_id, u.email)}


class Valores(BaseModel):
    archivo_id: int
    mapeo: dict


@router.post("/cargas/valores")
def valores(body: Valores, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    """Valores de origen y de atributos de lista que hay que traducir al catálogo antes del preview."""
    return cargas.valores(conn, body.archivo_id, body.mapeo)


def _despachar(r: dict) -> dict:
    """Una carga pesada que quedó en cola no se despacha: arranca sola cuando termina la que está corriendo (D50)."""
    if not r.get("en_cola") and r.get("tarea_id"):
        tareas.despachar(r["tarea_id"])
    return r


@router.get("/cargas")
def listar(u: Usuario = Depends(usuario_actual)):
    lotes.revisar_trabadas()
    with conexion() as conn:
        return cargas.listar(conn)


@router.get("/cargas/plantillas")
def plantillas(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return conn.execute("SELECT * FROM carga_plantilla ORDER BY tipo_fuente").fetchall()


@router.get("/cargas/{carga_id}")
def obtener(carga_id: int, u: Usuario = Depends(usuario_actual)):
    lotes.revisar_trabadas()
    with conexion() as conn:
        return cargas.obtener(conn, carga_id)


@router.post("/cargas/{carga_id}/confirmar")
def confirmar(carga_id: int, u: Usuario = Depends(requiere("steward"))):
    with conexion() as conn:
        r = cargas.confirmar(conn, carga_id, u.email)
    return _despachar(r)


@router.post("/cargas/{carga_id}/reanudar")
def reanudar(carga_id: int, u: Usuario = Depends(requiere("steward"))):
    """L4: sigue una carga interrumpida (preview, confirmación o deshacer) desde el primer lote que no se hizo."""
    with conexion() as conn:
        r = lotes.reanudar(conn, carga_id, u.email)
    return _despachar(r)


@router.put("/cargas/{carga_id}/decisiones")
def decisiones(carga_id: int, body: Decisiones, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    return cargas.guardar_decisiones(conn, carga_id, body.decisiones, u.email)


@router.delete("/cargas/{carga_id}")
def deshacer(carga_id: int, u: Usuario = Depends(requiere("steward"))):
    """Descarta una carga que nunca se aplicó, o deshace por pasos (D50) una confirmada o interrumpida."""
    with conexion() as conn:
        r = cargas.deshacer(conn, carga_id, u.email)
    if r.get("estado") == "descartada":
        return r
    _despachar(r)
    with conexion() as conn:  # si ya terminó (o corre en línea, en los tests), el resumen de lo que hizo
        c = conn.execute("SELECT estado, resumen_op FROM carga WHERE id = %s", (carga_id,)).fetchone()
    return {**(c["resumen_op"] or {}), **r, "estado": c["estado"]}


@router.get("/cargas/{carga_id}/borrado")
def conteos_borrado(carga_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    """Lo que se borraría con la carga y qué tareas se cancelarían (para el modal de confirmación)."""
    return borrado.conteos_carga(conn, carga_id)


@router.delete("/cargas/{carga_id}/definitivo")
def borrar(carga_id: int, u: Usuario = Depends(requiere("admin"))):
    """Borrado definitivo (solo administrador): corre como tarea porque puede tocar miles de empresas."""
    with conexion() as conn:
        r = borrado.pedir_borrado_carga(conn, carga_id, u.email)
    return _despachar(r)


@router.get("/revision")
def revision(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return cargas.revision_pendiente(conn)


class Accion(BaseModel):
    accion: str


@router.post("/revision/{revision_id}")
def resolver_revision(revision_id: int, body: Accion, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    return cargas.resolver_revision(conn, revision_id, body.accion, u.email)
