"""Tareas diferidas con progreso visible (cargas grandes, ingestas de .sav).

En producción cada tarea se encola en Cloud Tasks, que llama a POST /tareas/{id}/ejecutar
con el header X-Tarea-Token. En desarrollo corre en un hilo (background) y en los tests
corre en línea (inline), siempre con el mismo código.

Cancelación (al borrar la carga, la muestra o el estudio): cancelar() marca la tarea
«cancelada» en una conexión con autocommit. Una tarea cancelada no arranca, y una que está
corriendo lo nota la próxima vez que informa progreso: progreso() lanza Cancelada, que revierte
toda su transacción. No se aplica nada y la tarea termina «cancelada», no en error.
"""
import contextvars
import datetime as dt
import logging
import threading
import time
import traceback
from dataclasses import dataclass

from psycopg.types.json import Jsonb

from . import settings
from .db import conexion, pool

log = logging.getLogger(__name__)
_HANDLERS = {}
ACTIVAS = ("pendiente", "corriendo")
TRABADA_MINUTOS = 30   # más que el dispatch_deadline de Cloud Tasks (1800 s)


class Cancelada(Exception):
    """La tarea se canceló mientras corría: su transacción se revierte entera."""


@dataclass
class Continuar:
    """Lo devuelve un handler por pasos (cargas por lotes, D50): el paso hecho se confirma y la misma tarea se
    vuelve a encolar para el paso siguiente, después de «demora» segundos. Cada paso es una transacción corta."""
    mensaje: str | None = None
    demora: float = 0


# Tareas a despachar cuando la transacción del paso en curso haga commit (p. ej. la carga que esperaba en cola)
_despues: contextvars.ContextVar[list | None] = contextvars.ContextVar("tareas_despues", default=None)


def despues(tarea_id: int):
    """Despacha la tarea cuando termine bien la tarea actual (después del commit). Fuera de una tarea, enseguida."""
    pendientes = _despues.get()
    if pendientes is None:
        despachar(tarea_id)
    else:
        pendientes.append(tarea_id)


def handler(tipo: str):
    def deco(fn):
        _HANDLERS[tipo] = fn
        return fn

    return deco


_AL_CORTARSE = {}


def al_cortarse(tipo: str):
    """Gancho para cuando una tarea de ese tipo falla o se cancela: fn(conexión autocommit, tarea, mensaje, cancelada)
    devuelve las tareas a despachar (p. ej. la carga que esperaba en cola). Reemplaza la marca «error» genérica."""
    def deco(fn):
        _AL_CORTARSE[tipo] = fn
        return fn

    return deco


def _cortada(t: dict, mensaje: str, cancelada: bool):
    fn = _AL_CORTARSE.get(t["tipo"])
    if fn is None:
        return
    try:
        with pool().connection() as c:
            c.autocommit = True
            siguientes = fn(c, t, mensaje, cancelada) or []
        for tid in siguientes:
            despachar(tid)
    except Exception:
        log.error("No se pudo registrar el corte de la tarea %s: %s", t["id"], traceback.format_exc())


def crear(conn, tipo: str, payload: dict, actor: str) -> int:
    return conn.execute(
        "INSERT INTO tarea (tipo, payload, creado_por) VALUES (%s, %s, %s) RETURNING id",
        (tipo, Jsonb(payload), actor),
    ).fetchone()["id"]


_inline = threading.local()


def despachar(tarea_id: int, demora: float = 0):
    """Llamar DESPUÉS del commit de la transacción que creó la tarea.
    En modo inline (tests) las tareas encadenadas se ejecutan en un bucle por hilo, no en llamadas anidadas: cada
    paso suelta su conexión antes de que empiece el siguiente."""
    modo = settings.TASKS_MODE
    if modo == "inline":
        cola = getattr(_inline, "cola", None)
        if cola is not None:
            cola.append(tarea_id)
            return
        _inline.cola = [tarea_id]
        try:
            while _inline.cola:
                ejecutar(_inline.cola.pop(0))
        finally:
            _inline.cola = None
    elif modo == "cloudtasks":
        _encolar_cloud_tasks(tarea_id, demora)
    else:
        def correr():
            if demora:
                time.sleep(demora)
            ejecutar(tarea_id)
        threading.Thread(target=correr, daemon=True).start()


def url_ejecutar(tarea_id: int) -> str:
    """URL a la que Cloud Tasks llama para ejecutar la tarea. Las rutas de la API cuelgan de /api
    (main.py), así que sin ese prefijo Cloud Tasks recibe 404 y la tarea queda pendiente."""
    return f"{settings.API_URL.rstrip('/')}/api/tareas/{tarea_id}/ejecutar"


def _encolar_cloud_tasks(tarea_id: int, demora: float = 0):
    from google.cloud import tasks_v2
    from google.protobuf import timestamp_pb2

    cliente = tasks_v2.CloudTasksClient()
    tarea = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": url_ejecutar(tarea_id),
            "headers": {"X-Tarea-Token": settings.TAREA_TOKEN},
        },
        "dispatch_deadline": {"seconds": 1800},
    }
    if demora:  # respiro para la base entre lote y lote
        cuando = timestamp_pb2.Timestamp()
        cuando.FromDatetime(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=demora))
        tarea["schedule_time"] = cuando
    cliente.create_task(parent=settings.TASKS_QUEUE, task=tarea)


def progreso(tarea_id: int | None, hechos: int, total: int | None = None):
    """Actualiza el progreso en una conexión aparte (autocommit) para que se vea en vivo.
    Si la tarea fue cancelada (o borrada junto con su carga), lanza Cancelada."""
    if tarea_id is None:
        return
    with pool().connection() as c:
        c.autocommit = True
        r = c.execute("UPDATE tarea SET progreso = %s, total = coalesce(%s, total), actualizado = now() WHERE id = %s"
                      " AND estado <> 'cancelada' RETURNING id", (hechos, total, tarea_id)).fetchone()
    if r is None:
        raise Cancelada(f"La tarea {tarea_id} fue cancelada")


def mensaje(tarea_id: int | None, texto: str | None):
    """Texto para la pantalla («Lote 12 de 38 · …»), en una conexión aparte (autocommit) como el progreso: dentro de la
    transacción del paso dejaría la fila de la tarea bloqueada y el progreso se quedaría esperando."""
    if tarea_id is None:
        return
    with pool().connection() as c:
        c.autocommit = True
        c.execute("UPDATE tarea SET mensaje = %s, actualizado = now() WHERE id = %s", (texto, tarea_id))


def cancelar(condicion: str, args: tuple, motivo: str) -> list[int]:
    """Cancela las tareas pendientes o corriendo que cumplen la condición (SQL sobre tarea).
    Usa su propia conexión con autocommit para que la vea enseguida la tarea que está corriendo."""
    with pool().connection() as c:
        c.autocommit = True
        return [r["id"] for r in c.execute(
            f"UPDATE tarea SET estado = 'cancelada', error = %s, terminado = now()"
            f" WHERE estado IN ('pendiente', 'corriendo') AND ({condicion}) RETURNING id", (motivo, *args))]


def _estado(tarea_id: int) -> str | None:
    with pool().connection() as c:
        r = c.execute("SELECT estado FROM tarea WHERE id = %s", (tarea_id,)).fetchone()
    return r["estado"] if r else None


def ejecutar(tarea_id: int) -> dict | None:
    with pool().connection() as c:
        c.autocommit = True
        t = c.execute(
            "UPDATE tarea SET estado = 'corriendo', actualizado = now() WHERE id = %s AND estado IN ('pendiente','error')"
            " RETURNING *", (tarea_id,),
        ).fetchone()
    if t is None:
        return None  # ya corrió o está corriendo (Cloud Tasks puede reintentar)
    pendientes = []
    token = _despues.set(pendientes)
    try:
        with conexion() as conn:
            resultado = _HANDLERS[t["tipo"]](conn, t["payload"], tarea_id)
        if isinstance(resultado, Continuar):
            # Paso hecho (ya hizo commit): la misma tarea vuelve a la cola para el paso siguiente
            with pool().connection() as c:
                c.autocommit = True
                sigue = c.execute("UPDATE tarea SET estado = 'pendiente', mensaje = coalesce(%s, mensaje), actualizado = now()"
                                  " WHERE id = %s AND estado = 'corriendo' RETURNING id", (resultado.mensaje, tarea_id)).fetchone()
            _despues.reset(token)
            token = None
            for tid in pendientes:
                despachar(tid)
            if sigue:
                despachar(tarea_id, resultado.demora)
            return None
        with pool().connection() as c:
            c.autocommit = True
            c.execute("UPDATE tarea SET estado='ok', resultado=%s, terminado=now(), actualizado = now() WHERE id=%s",
                      (Jsonb(resultado), tarea_id))
        _despues.reset(token)
        token = None
        for tid in pendientes:
            despachar(tid)
        return resultado
    except Exception as e:
        if token is not None:
            _despues.reset(token)
            token = None
        if isinstance(e, Cancelada) or _estado(tarea_id) in ("cancelada", None):
            # Cancelada (o borrada con su carga) mientras corría: la transacción ya se revirtió.
            # No es un error y no marca la carga ni la ingesta como «error».
            log.info("Tarea %s cancelada: no se aplicó el paso en curso", tarea_id)
            _cortada(t, "Cancelada", True)
            return None
        # se registra y se muestra en la UI
        log.error("Tarea %s falló: %s", tarea_id, traceback.format_exc())
        with pool().connection() as c:
            c.autocommit = True
            c.execute("UPDATE tarea SET estado='error', error=%s, terminado=now() WHERE id=%s",
                      (str(getattr(e, "detail", e)), tarea_id))
            _marcar_error_objeto(c, t, e)
        if settings.TASKS_MODE == "inline":
            raise
        return None


def _marcar_error_objeto(c, t, e):
    p = t["payload"]
    msg = str(getattr(e, "detail", e))
    if t["tipo"] in _AL_CORTARSE:  # cargas por lotes: «interrumpida», con lo aplicado hasta ahí
        siguientes = _AL_CORTARSE[t["tipo"]](c, t, msg, False) or []
        for tid in siguientes:
            despachar(tid)
        return
    if "carga_id" in p:
        c.execute("UPDATE carga SET estado='error', error=%s WHERE id=%s", (msg, p["carga_id"]))
    if "ingesta_id" in p:
        c.execute("UPDATE sav_ingesta SET estado='error', error=%s WHERE id=%s", (msg, p["ingesta_id"]))
    if "corrida_id" in p:
        c.execute("UPDATE enriquecimiento_corrida SET estado='error', error=%s, terminada=now() WHERE id=%s"
                  " AND estado IN ('en_curso','preview')", (msg, p["corrida_id"]))


def obtener(conn, tarea_id: int) -> dict | None:
    return conn.execute("SELECT * FROM tarea WHERE id = %s", (tarea_id,)).fetchone()
