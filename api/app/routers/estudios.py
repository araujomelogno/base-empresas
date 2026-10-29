"""Estudios, partes, muestras y CSV para uContact (R1.5, R1.6, R1.7)."""
import datetime as dt

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel

from .. import exportacion, muestras
from ..auth import Usuario, requiere, usuario_actual
from ..db import get_conn

router = APIRouter()


class NuevaParte(BaseModel):
    nombre: str
    survey_id: str | None = None
    link_base: str | None = None
    respondente_objetivo: str | None = None


class EdicionParte(BaseModel):
    nombre: str | None = None
    survey_id: str | None = None
    link_base: str | None = None
    respondente_objetivo: str | None = None


class NuevoEstudio(BaseModel):
    nombre: str
    cliente: str | None = None
    campo_desde: dt.date
    campo_hasta: dt.date
    partes: list[NuevaParte] = []


class EdicionEstudio(BaseModel):
    nombre: str | None = None
    cliente: str | None = None
    campo_desde: dt.date | None = None
    campo_hasta: dt.date | None = None


@router.get("/estudios")
def listar(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return conn.execute(
        "SELECT e.*, (SELECT count(*) FROM parte p WHERE p.estudio_id = e.id) AS n_partes,"
        " (SELECT count(*) FROM muestra m WHERE m.estudio_id = e.id) AS n_muestras,"
        " (SELECT count(*) FROM muestra m WHERE m.estudio_id = e.id AND m.estado = 'activa') AS muestras_activas"
        " FROM estudio e ORDER BY e.campo_desde DESC, e.id DESC").fetchall()


@router.post("/estudios")
def crear(body: NuevoEstudio, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.crear_estudio(conn, body.model_dump(), u.email)


@router.get("/estudios/{estudio_id}")
def detalle(estudio_id: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return muestras.estudio_detalle(conn, estudio_id)


@router.patch("/estudios/{estudio_id}")
def editar(estudio_id: int, body: EdicionEstudio, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.actualizar_estudio(conn, estudio_id, body.model_dump(exclude_none=True), u.email)


@router.post("/estudios/{estudio_id}/partes")
def crear_parte(estudio_id: int, body: NuevaParte, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.crear_parte(conn, estudio_id, body.model_dump(), u.email)


@router.patch("/partes/{parte_id}")
def editar_parte(parte_id: int, body: EdicionParte, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.actualizar_parte(conn, parte_id, body.model_dump(exclude_none=True), u.email)


@router.get("/partes")
def partes(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return conn.execute(
        "SELECT p.id, p.nombre, p.survey_id, p.estudio_id, e.nombre AS estudio_nombre, (p.plantilla_mapeo IS NOT NULL) AS tiene_plantilla"
        " FROM parte p JOIN estudio e ON e.id = p.estudio_id ORDER BY e.campo_desde DESC, p.id").fetchall()


class NuevaMuestra(BaseModel):
    estudio_id: int
    nombre: str
    criterios: dict


@router.post("/muestras")
def crear_muestra(body: NuevaMuestra, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.crear_muestra(conn, body.estudio_id, body.nombre, body.criterios, u.email)


@router.post("/muestras/marco")
def marco(criterios: dict, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """Previsualiza el marco (disponibles por estrato y exclusiones por regla) sin sortear."""
    return muestras.previsualizar_marco(conn, criterios)


@router.get("/muestras")
def listar_muestras(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return conn.execute(
        "SELECT m.id, m.nombre, m.estado, m.semilla, m.config_version, m.sorteada, m.estudio_id, e.nombre AS estudio_nombre,"
        " (SELECT count(*) FROM muestra_item i WHERE i.muestra_id = m.id) AS n_items,"
        " (SELECT count(*) FROM muestra_item i WHERE i.muestra_id = m.id AND i.liberado) AS n_liberados"
        " FROM muestra m JOIN estudio e ON e.id = m.estudio_id ORDER BY m.id DESC").fetchall()


@router.get("/muestras/{muestra_id}")
def detalle_muestra(muestra_id: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return muestras.detalle(conn, muestra_id)


@router.get("/muestras/{muestra_id}/items")
def items(muestra_id: int, estrato: str | None = None, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return muestras.items(conn, muestra_id, estrato)


class Sorteo(BaseModel):
    semilla: int | None = None


@router.post("/muestras/{muestra_id}/sortear")
def sortear(muestra_id: int, body: Sorteo | None = None, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.sortear(conn, muestra_id, u.email, body.semilla if body else None)


@router.post("/muestras/{muestra_id}/verificar")
def verificar(muestra_id: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return muestras.verificar(conn, muestra_id)


class Liberacion(BaseModel):
    estrato: str
    cantidad: int = 1
    motivo: str


@router.post("/muestras/{muestra_id}/liberar")
def liberar(muestra_id: int, body: Liberacion, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.liberar(conn, muestra_id, body.estrato, body.cantidad, body.motivo, u.email)


@router.post("/muestras/{muestra_id}/cerrar")
def cerrar(muestra_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("jefe"))):
    return muestras.cerrar(conn, muestra_id, u.email)


@router.get("/muestras/{muestra_id}/csv")
def csv(muestra_id: int, parte_id: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("coordinador", "jefe"))):
    nombre, contenido, resumen = exportacion.generar_csv(conn, muestra_id, parte_id, u)
    return Response(
        content=contenido.encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"',
                 "X-Renglones": str(resumen["renglones"]), "X-Items-Sin-Telefono": str(resumen["items_sin_telefono"]),
                 "X-Contactos-Incluidos": "1" if resumen["con_contactos"] else "0",
                 "Access-Control-Expose-Headers": "X-Renglones, X-Items-Sin-Telefono, X-Contactos-Incluidos"})


@router.get("/muestras/{muestra_id}/csv/resumen")
def csv_resumen(muestra_id: int, parte_id: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    filas, ctx = exportacion.filas_csv(conn, muestra_id, parte_id, False)
    return {**ctx["resumen"], "ejemplo": filas[:5], "columnas": ctx["cfg"]["csv_ucontact"]["columnas"]}
