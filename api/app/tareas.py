"""Tareas diferidas con progreso visible (cargas grandes, ingestas de .sav).

En producción cada tarea se encola en Cloud Tasks, que llama a POST /tareas/{id}/ejecutar
con el header X-Tarea-Token. En desarrollo corre en un hilo (background) y en los tests
corre en línea (inline), siempre con el mismo código.

Cancelación (al borrar la carga, la muestra o el estudio): cancelar() marca la tarea
«cancelada» en una conexión con autocommit. Una tarea cancelada no arranca, y una que está
corriendo lo nota la próxima vez que informa progreso: progreso() lanza Cancelada, que revierte
toda su transacción. No se aplica nada y la tarea termina «cancelada», no en error.

Robustez (D52): mientras corre, la tarea deja un latido cada 30 s (tarea.actualizado) con su marca de dueño. Si el
proceso muere (falta de memoria, una instancia que se apaga), el latido se detiene y, pasados 3 minutos, el próximo
intento la retoma desde el paso que no se terminó; mientras tanto, un intento que la encuentra viva responde
«ocupada» (503) para que Cloud Tasks reintente más tarde. Al recibir SIGTERM, el paso en curso se revierte y la
tarea vuelve a la cola enseguida, para que la tome otra instancia.
"""
import contextvars
import datetime as dt
import logging
import threading
import time
import traceback
import uuid
from dataclasses import dataclass

from psycopg.types.json import Jsonb

from . import settings
from .db import conexion, pool, sin_limite

log = logging.getLogger(__name__)
_HANDLERS = {}
ACTIVAS = ("pendiente", "corriendo")
TRABADA_MINUTOS = 30   # más que el dispatch_deadline de Cloud Tasks (1800 s)


class Cancelada(Exception):
    """La tarea se canceló mientras corría: su transacción se revierte entera."""


class Apagando(Exception):
    """La instancia recibió SIGTERM (despliegue o cierre): el paso en curso se revierte y la tarea vuelve a la cola."""


class Desplazada(Exception):
    """Otro proceso retomó la tarea (este dejó de latir): el paso en curso se revierte sin tocar nada más."""


# ejecutar() la devuelve si la tarea está corriendo en otro proceso vivo: Cloud Tasks tiene que reintentar más tarde
OCUPADA = object()

_apagando = threading.Event()
_dueno: contextvars.ContextVar[str | None] = contextvars.ContextVar("tarea_dueno", default=None)


def apagar():
    """SIGTERM: no se toman tareas nuevas y la que está corriendo se devuelve a la cola en su próximo aviso."""
    _apagando.set()


def _si_apaga():
    if _apagando.is_set() and _dueno.get():
        raise Apagando("La instancia se está apagando")


def sigo_siendo_dueno(conn, tarea_id: int):
    """Al final de un paso: si otro proceso retomó la tarea mientras tanto, este paso no se confirma."""
    yo = _dueno.get()
    if yo is None:
        return
    r = conn.execute("SELECT dueno FROM tarea WHERE id = %s", (tarea_id,)).fetchone()
    if r is None or r["dueno"] != yo:
        raise Desplazada(f"La tarea {tarea_id} la retomó otro proceso")


def _latir(tarea_id: int, dueno: str, alto: threading.Event):
    while not alto.wait(settings.TAREA_LATIDO_SEGUNDOS):
        try:
            with pool().connection() as c:
                c.autocommit = True
                c.execute("UPDATE tarea SET actualizado = now() WHERE id = %s AND dueno = %s AND estado = 'corriendo'",
                          (tarea_id, dueno))
        except Exception:
            log.warning("No se pudo registrar el latido de la tarea %s", tarea_id)


@dataclass
class Continuar:
    """Lo devuelve un handler por pasos (cargas por lotes, D50): el paso hecho se confirma y la misma tarea se
    vuelve a encolar para el paso siguiente, después de «demora» segundos. Cada paso es una transacción corta."""
    mensaje: str | None = None
    demora: float = 0


# Tareas a despachar cuando la transacción del paso en curso haga commit (p. ej. la carga que esperaba en cola)
_despues: contextvars.ContextVar[list | None] = contextvars.ContextVar("tareas_despues", default=None)


def en_tarea() -> bool:
    """Si el código corre dentro del paso de una tarea (las que encola se despachan después de su commit)."""
    return _despues.get() is not None


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
    return f"{(settings.TAREAS_URL or settings.API_URL).rstrip('/')}/api/tareas/{tarea_id}/ejecutar"


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
    _si_apaga()
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
    _si_apaga()
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


def _tomar(tarea_id: int, dueno: str) -> tuple[dict | None, str | None]:
    """Toma la tarea si está pendiente, en error, o «corriendo» sin latido hace más de 3 minutos (su proceso murió).
    Devuelve (tarea, estado anterior) o (None, estado actual)."""
    with pool().connection() as c:
        c.autocommit = True
        t = c.execute(
            "WITH antes AS (SELECT id, estado FROM tarea WHERE id = %s FOR UPDATE)"
            " UPDATE tarea t SET estado = 'corriendo', dueno = %s, paso_inicio = now(), actualizado = now() FROM antes"
            " WHERE t.id = antes.id AND (antes.estado IN ('pendiente', 'error')"
            "   OR (antes.estado = 'corriendo' AND t.actualizado < now() - make_interval(secs => %s)))"
            " RETURNING t.*, antes.estado AS estado_antes",
            (tarea_id, dueno, settings.TAREA_RETOMAR_SEGUNDOS)).fetchone()
        if t is None:
            r = c.execute("SELECT estado FROM tarea WHERE id = %s", (tarea_id,)).fetchone()
            return None, (r["estado"] if r else None)
    return t, t.pop("estado_antes")


def ejecutar(tarea_id: int):
    """Corre la tarea (o su paso siguiente). Devuelve el resultado, None si no había nada que hacer, u OCUPADA si
    está corriendo en otro proceso vivo (o esta instancia se está apagando): Cloud Tasks reintenta más tarde."""
    if _apagando.is_set():
        return OCUPADA
    dueno = uuid.uuid4().hex
    t, antes = _tomar(tarea_id, dueno)
    if t is None:
        return OCUPADA if antes == "corriendo" else None  # ya terminó, se canceló o no existe
    if antes == "corriendo":
        log.warning("Tarea %s retomada: el proceso que la corría dejó de responder (sin latido hace más de %s s)",
                    tarea_id, settings.TAREA_RETOMAR_SEGUNDOS)
    pendientes = []
    token = _despues.set(pendientes)
    token_dueno = _dueno.set(dueno)
    alto = threading.Event()
    threading.Thread(target=_latir, args=(tarea_id, dueno, alto), daemon=True).start()
    try:
        with conexion() as conn:
            sin_limite(conn)  # D55: el límite de 15 s es para la web, no para las tareas
            resultado = _HANDLERS[t["tipo"]](conn, t["payload"], tarea_id)
        if isinstance(resultado, Continuar):
            # Paso hecho (ya hizo commit): la misma tarea vuelve a la cola para el paso siguiente
            with pool().connection() as c:
                c.autocommit = True
                sigue = c.execute("UPDATE tarea SET estado = 'pendiente', mensaje = coalesce(%s, mensaje), actualizado = now(),"
                                  " dueno = NULL, reintentos_auto = 0 WHERE id = %s AND estado = 'corriendo' AND dueno = %s"
                                  " RETURNING id", (resultado.mensaje, tarea_id, dueno)).fetchone()
            _despues.reset(token)
            token = None
            for tid in pendientes:
                despachar(tid)
            if sigue:
                despachar(tarea_id, resultado.demora)
            return None
        with pool().connection() as c:
            c.autocommit = True
            c.execute("UPDATE tarea SET estado='ok', resultado=%s, terminado=now(), actualizado = now(), dueno = NULL"
                      " WHERE id=%s AND dueno = %s", (Jsonb(resultado), tarea_id, dueno))
        _despues.reset(token)
        token = None
        for tid in pendientes:
            despachar(tid)
        return resultado
    except Exception as e:
        if token is not None:
            _despues.reset(token)
            token = None
        if isinstance(e, Apagando):
            # Despliegue o cierre de la instancia: el paso se revirtió; la tarea vuelve a la cola ya mismo
            log.warning("Tarea %s devuelta a la cola: la instancia se apaga (el paso en curso se revirtió)", tarea_id)
            with pool().connection() as c:
                c.autocommit = True
                # «pendiente» y sin dueño: el próximo intento (de otra instancia) la toma enseguida
                c.execute("UPDATE tarea SET estado = 'pendiente', dueno = NULL, actualizado = now()"
                          " WHERE id = %s AND dueno = %s", (tarea_id, dueno))
            try:
                despachar(tarea_id)
            except Exception:
                log.error("No se pudo volver a encolar la tarea %s: la retoma el chequeo de trabadas", tarea_id)
            return None
        if isinstance(e, Desplazada):
            log.warning("Tarea %s: otro proceso la retomó; este paso se revirtió", tarea_id)
            return None
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
            c.execute("UPDATE tarea SET estado='error', error=%s, terminado=now(), dueno = NULL WHERE id=%s",
                      (str(getattr(e, "detail", e)), tarea_id))
            _marcar_error_objeto(c, t, e)
        if settings.TASKS_MODE == "inline":
            raise
        return None
    finally:
        alto.set()
        _dueno.reset(token_dueno)


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
    # segundos_paso: hace cuánto empezó el paso (o lote) en curso, medido en la base (sin depender del reloj del navegador)
    return conn.execute("SELECT *, CASE WHEN estado = 'corriendo' THEN extract(epoch FROM now() - paso_inicio)::int END"
                        " AS segundos_paso FROM tarea WHERE id = %s", (tarea_id,)).fetchone()
