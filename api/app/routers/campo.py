"""Campo: CDR, ingesta del .sav, conciliación y actividad (R1.8–R1.11)."""
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel

from .. import actividad, cdr, conciliacion, sav, storage, tareas
from ..auth import Usuario, requiere, requiere_job, usuario_actual
from ..db import conexion, get_conn

router = APIRouter()


class Llamada(BaseModel):
    cdr_id: str
    inicio: str
    destino: str | None = None
    encuestador: str | None = None
    duracion: int | None = None
    userfield: str | None = None
    disposicion: str | None = None
    campania: str | None = None


class Lote(BaseModel):
    origen: str = "uContact"
    llamadas: list[Llamada]


@router.post("/intentos/lote")
def lote(body: Lote, conn=Depends(get_conn), actor: str = Depends(requiere_job)):
    return cdr.procesar_lote(conn, [ll.model_dump() for ll in body.llamadas], body.origen, actor)


@router.get("/cdr/lotes")
def lotes(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return conn.execute("SELECT * FROM cdr_lote ORDER BY id DESC LIMIT 60").fetchall()


@router.post("/partes/{parte_id}/sav/analizar")
def sav_analizar(parte_id: int, archivo: UploadFile = File(...), plantilla_de_parte: int | None = Form(None),
                 u: Usuario = Depends(requiere("coordinador"))):
    datos = archivo.file.read()
    with conexion() as conn:
        a = storage.guardar(conn, archivo.filename or "resultados.sav", datos, u.email)
        return sav.analizar(conn, parte_id, a, u.email, plantilla_de_parte)


class Mapeo(BaseModel):
    ingesta_id: int
    mapeo: dict


@router.post("/sav/{ingesta_id}/contar")
def sav_contar(ingesta_id: int, body: Mapeo, conn=Depends(get_conn), u: Usuario = Depends(requiere("coordinador"))):
    return sav.recontar(conn, ingesta_id, body.mapeo)


@router.post("/partes/{parte_id}/sav")
def sav_confirmar(parte_id: int, body: Mapeo, u: Usuario = Depends(requiere("coordinador"))):
    with conexion() as conn:
        tid = sav.confirmar(conn, parte_id, body.ingesta_id, body.mapeo, u.email)
    tareas.despachar(tid)
    return {"tarea_id": tid, "ingesta_id": body.ingesta_id}


@router.post("/sav/{ingesta_id}/remapear")
def sav_remapear(ingesta_id: int, body: Mapeo, u: Usuario = Depends(requiere("coordinador"))):
    with conexion() as conn:
        tid = sav.remapear(conn, ingesta_id, body.mapeo, u.email)
    tareas.despachar(tid)
    return {"tarea_id": tid, "ingesta_id": ingesta_id}


@router.get("/sav")
def sav_listar(parte_id: int | None = None, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return sav.listar(conn, parte_id)


@router.get("/sav/{ingesta_id}")
def sav_obtener(ingesta_id: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return sav.obtener(conn, ingesta_id)


@router.get("/conciliacion")
def conciliacion_listar(tipo: str | None = None, estado: str = "pendiente", conn=Depends(get_conn),
                        u: Usuario = Depends(usuario_actual)):
    return conciliacion.listar(conn, tipo, estado)


class Resolucion(BaseModel):
    accion: str
    item_id: int | None = None


@router.post("/conciliacion/{conciliacion_id}")
def conciliacion_resolver(conciliacion_id: int, body: Resolucion, conn=Depends(get_conn),
                          u: Usuario = Depends(requiere("coordinador"))):
    return conciliacion.resolver(conn, conciliacion_id, body.accion, body.item_id, u.email)


@router.get("/actividad")
def tablero(estudio_id: int | None = None, muestra_id: int | None = None, encuestador: str | None = None,
            desde: str | None = None, hasta: str | None = None, conn=Depends(get_conn),
            u: Usuario = Depends(usuario_actual)):
    return actividad.tablero(conn, {"estudio_id": estudio_id, "muestra_id": muestra_id, "encuestador": encuestador,
                                    "desde": desde, "hasta": hasta})
