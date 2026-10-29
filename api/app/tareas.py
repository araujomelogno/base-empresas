"""Tareas diferidas con progreso visible (cargas grandes, ingestas de .sav).

En producción cada tarea se encola en Cloud Tasks, que llama a POST /tareas/{id}/ejecutar
con el header X-Tarea-Token. En desarrollo corre en un hilo (background) y en los tests
corre en línea (inline), siempre con el mismo código.
"""
import logging
import threading
import traceback

from psycopg.types.json import Jsonb

from . import settings
from .db import conexion, pool

log = logging.getLogger(__name__)
_HANDLERS = {}


def handler(tipo: str):
    def deco(fn):
        _HANDLERS[tipo] = fn
        return fn

    return deco


def crear(conn, tipo: str, payload: dict, actor: str) -> int:
    return conn.execute(
        "INSERT INTO tarea (tipo, payload, creado_por) VALUES (%s, %s, %s) RETURNING id",
        (tipo, Jsonb(payload), actor),
    ).fetchone()["id"]


def despachar(tarea_id: int):
    """Llamar DESPUÉS del commit de la transacción que creó la tarea."""
    modo = settings.TASKS_MODE
    if modo == "inline":
        ejecutar(tarea_id)
    elif modo == "cloudtasks":
        _encolar_cloud_tasks(tarea_id)
    else:
        threading.Thread(target=ejecutar, args=(tarea_id,), daemon=True).start()


def _encolar_cloud_tasks(tarea_id: int):
    from google.cloud import tasks_v2

    cliente = tasks_v2.CloudTasksClient()
    tarea = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{settings.API_URL.rstrip('/')}/tareas/{tarea_id}/ejecutar",
            "headers": {"X-Tarea-Token": settings.TAREA_TOKEN},
        },
        "dispatch_deadline": {"seconds": 1800},
    }
    cliente.create_task(parent=settings.TASKS_QUEUE, task=tarea)


def progreso(tarea_id: int | None, hechos: int, total: int | None = None):
    """Actualiza el progreso en una conexión aparte (autocommit) para que se vea en vivo."""
    if tarea_id is None:
        return
    with pool().connection() as c:
        c.autocommit = True
        c.execute("UPDATE tarea SET progreso = %s, total = coalesce(%s, total) WHERE id = %s",
                  (hechos, total, tarea_id))


def ejecutar(tarea_id: int) -> dict | None:
    with pool().connection() as c:
        c.autocommit = True
        t = c.execute(
            "UPDATE tarea SET estado = 'corriendo' WHERE id = %s AND estado IN ('pendiente','error') RETURNING *",
            (tarea_id,),
        ).fetchone()
    if t is None:
        return None  # ya corrió o está corriendo (Cloud Tasks puede reintentar)
    try:
        with conexion() as conn:
            resultado = _HANDLERS[t["tipo"]](conn, t["payload"], tarea_id)
        with pool().connection() as c:
            c.autocommit = True
            c.execute("UPDATE tarea SET estado='ok', resultado=%s, terminado=now() WHERE id=%s",
                      (Jsonb(resultado), tarea_id))
        return resultado
    except Exception as e:  # se registra y se muestra en la UI
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
    if "carga_id" in p:
        c.execute("UPDATE carga SET estado='error', error=%s WHERE id=%s", (msg, p["carga_id"]))
    if "ingesta_id" in p:
        c.execute("UPDATE sav_ingesta SET estado='error', error=%s WHERE id=%s", (msg, p["ingesta_id"]))


def obtener(conn, tarea_id: int) -> dict | None:
    return conn.execute("SELECT * FROM tarea WHERE id = %s", (tarea_id,)).fetchone()
