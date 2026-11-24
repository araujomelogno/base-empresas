"""Mantenimiento de la base al terminar cada operación grande (SPEC_rendimiento_base_grande, P-1, P-2 y P-4; D55).

Una tarea «base.mantenimiento», por pasos y en el servicio de tareas:
1. ANALYZE de las tablas que tocó la operación, de a una y fuera de la transacción de los lotes, con la duración en
   el log («ANALYZE empresa_campo_historia 42 s»): Postgres vuelve a tener estadísticas al día sin entrar a psql.
2. La disponibilidad guardada: el recálculo completo si hace falta, y si no las empresas anotadas, de a 5.000.
3. Los resúmenes (valores de los filtros, contadores de Inicio, uso de las naturalezas).

La encolan el final de una confirmación, un deshacer o un borrado de carga, un borrado de muestra o de estudio, una
ingesta de .sav, una corrida de enriquecimiento o de descubrimiento y un sorteo; el job cada 10 minutos si quedó algo
pendiente; y el job diario, con las tablas que cambiaron más del 10 % desde su último análisis. Si ya hay una
esperando, se le suman las tablas en lugar de crear otra. Mientras corre una carga pesada, la disponibilidad y los
resúmenes esperan: al terminar, esa carga encola su propio mantenimiento.
"""
import logging
import time

from psycopg.types.json import Jsonb

from . import config, disponibilidad, resumen, settings, tareas
from .db import pool, sin_limite

log = logging.getLogger(__name__)

TIPO = "base.mantenimiento"
TABLAS = ("empresa", "empresa_campo_historia", "empresa_atributo", "telefono", "telefono_vinculo",
          "telefono_vinculo_origen", "contacto", "sucursal", "muestra_item", "intento", "sav_fila")
# Las que toca cada operación
CARGA = ("empresa", "empresa_campo_historia", "empresa_atributo", "telefono", "telefono_vinculo",
         "telefono_vinculo_origen", "contacto", "sucursal")
MUESTRA = ("muestra_item", "intento", "sav_fila")
SAV = ("sav_fila", "empresa", "empresa_campo_historia", "telefono", "telefono_vinculo", "contacto")
ENRIQUECIMIENTO = ("empresa", "empresa_campo_historia", "empresa_atributo", "telefono", "telefono_vinculo",
                   "telefono_vinculo_origen", "contacto")
UMBRAL_DIARIO = 0.10   # el job diario analiza las que cambiaron más del 10 % desde su último análisis


def analizar(tablas) -> list[dict]:
    """ANALYZE de cada tabla por separado, cada una en su propia transacción corta (no frena al resto)."""
    hechas = []
    for t in dict.fromkeys(tablas):
        if t not in TABLAS:
            continue
        t0 = time.monotonic()
        with pool().connection() as c:
            c.autocommit = True
            with c.transaction():
                sin_limite(c)
                c.execute(f"ANALYZE empresas.{t}")
        seg = round(time.monotonic() - t0, 1)
        log.info("ANALYZE %s %s s", t, seg)
        hechas.append({"tabla": t, "segundos": seg})
    return hechas


def tablas_a_analizar(conn, umbral: float = UMBRAL_DIARIO) -> list[str]:
    """Las tablas que cambiaron más que el umbral desde su último análisis (pg_stat_user_tables.n_mod_since_analyze)."""
    return [r["relname"] for r in conn.execute(
        "SELECT relname FROM pg_stat_user_tables WHERE schemaname = 'empresas' AND relname = ANY(%s)"
        " AND n_mod_since_analyze > 0 AND (n_mod_since_analyze > n_live_tup * %s"
        "   OR coalesce(last_analyze, last_autoanalyze) IS NULL) ORDER BY relname", (list(TABLAS), umbral))]


def estadisticas(conn) -> dict:
    """«Estadísticas de la base actualizadas: hace N minutos»: el análisis más viejo entre empresa y su historia."""
    filas = conn.execute(
        "SELECT relname AS tabla, greatest(last_analyze, last_autoanalyze) AS analizada, n_live_tup AS filas,"
        " n_mod_since_analyze AS cambios FROM pg_stat_user_tables WHERE schemaname = 'empresas' AND relname = ANY(%s)"
        " ORDER BY relname", (list(TABLAS),)).fetchall()
    claves = [f["analizada"] for f in filas if f["tabla"] in ("empresa", "empresa_campo_historia")]
    return {"actualizadas": None if not claves or None in claves else min(claves), "tablas": filas}


def _carga_pesada(conn) -> bool:
    from . import lotes

    return lotes.ocupada(conn, 0) is not None


def encolar(motivo: str, analizar_tablas=(), demora: float = 0) -> int | None:
    """Pide un mantenimiento. Usa su propia conexión (queda confirmado enseguida, aunque el pedido que lo llama
    todavía no terminó). Si ya hay uno esperando, le suma las tablas. Devuelve la tarea nueva, si creó una."""
    tablas = [t for t in dict.fromkeys(analizar_tablas) if t in TABLAS]
    if settings.TASKS_MODE == "inline" and not tareas.en_tarea():
        return None  # tests: a mitad de un pedido no se corre (los pedidos chicos recalculan en el momento)
    with pool().connection() as c:
        c.autocommit = True
        with c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (TIPO,))
            r = c.execute("SELECT id, payload FROM tarea WHERE tipo = %s AND estado = 'pendiente' ORDER BY id LIMIT 1"
                          " FOR UPDATE", (TIPO,)).fetchone()
            if r is not None:
                p = r["payload"]
                juntas = list(dict.fromkeys((p.get("analizar") or []) + tablas))
                if juntas != (p.get("analizar") or []):
                    c.execute("UPDATE tarea SET payload = payload || %s WHERE id = %s",
                              (Jsonb({"analizar": juntas}), r["id"]))
                return None
            tid = tareas.crear(c, TIPO, {"motivo": motivo, "analizar": tablas}, "sistema")
            c.execute("UPDATE tarea SET mensaje = %s WHERE id = %s", (f"En cola: {motivo}", tid))
    if tareas.en_tarea():
        tareas.despues(tid)          # dentro de una tarea: después de su commit
    elif settings.TASKS_MODE != "inline":
        tareas.despachar(tid, demora)  # en los tests (inline) no se corre a mitad de un pedido
    return tid


def al_terminar(motivo: str, tablas=CARGA):
    """Gancho del final de una operación grande. Nunca la hace fallar."""
    try:
        encolar(motivo, tablas, demora=0 if tareas.en_tarea() else 5)
    except Exception:
        log.warning("No se pudo encolar el mantenimiento de la base (%s)", motivo, exc_info=True)


@tareas.handler(TIPO)
def _tarea(conn, payload, tarea_id):
    tablas = payload.get("analizar") or []
    if tablas:
        tareas.mensaje(tarea_id, "Actualizando las estadísticas de la base: " + ", ".join(tablas))
        hechas = analizar(tablas)
        conn.execute("UPDATE tarea SET payload = payload || jsonb_build_object('analizar', '[]'::jsonb,"
                     " 'analizadas', coalesce(payload->'analizadas', '[]'::jsonb) || %s) WHERE id = %s",
                     (Jsonb(hechas), tarea_id))
        return tareas.Continuar("Estadísticas al día")
    if _carga_pesada(conn) and not payload.get("forzar"):
        return {"motivo": payload.get("motivo"), "analizadas": payload.get("analizadas") or [],
                "omitido": "Hay una carga pesada en curso: al terminar encola su propio mantenimiento"}
    _, params = config.vigente(conn)
    if not disponibilidad.lista(conn, params):
        r = disponibilidad.paso_completo(conn, params)
        if r is None:
            return tareas.Continuar("Esperando a otro recálculo de la disponibilidad", demora=10)
        terminado, hechas, total = r
        tareas.progreso(tarea_id, hechas, total)
        texto = (f"Disponibilidad: {hechas:,} de {total:,} empresas" if not terminado
                 else "Disponibilidad lista").replace(",", ".")
        return tareas.Continuar(texto)
    disponibilidad.marcar_vencidos(conn)
    n = disponibilidad.procesar(conn, params, disponibilidad.TANDA)
    if n:
        return tareas.Continuar(f"Disponibilidad: {n:,} empresas recalculadas".replace(",", "."))
    tareas.mensaje(tarea_id, "Recalculando valores de los filtros y contadores")
    hechos = resumen.recalcular(conn)
    return {"motivo": payload.get("motivo"), "analizadas": payload.get("analizadas") or [],
            "resumen": {k: float(v["segundos"] or 0) for k, v in hechos.items()}}


def pendiente(conn) -> dict:
    """Lo que falta hacer (para el job cada 10 minutos y la pantalla)."""
    return {"disponibilidad_lista": disponibilidad.lista(conn),
            "disponibilidad_pendientes": disponibilidad.pendientes(conn, 10000),
            "resumenes_viejos": resumen.viejos(conn)}


def job(conn, diario: bool = False) -> dict:
    """Job cada 10 minutos (y el diario): si quedó algo por hacer, encola el mantenimiento. El diario además analiza
    las tablas que cambiaron más del 10 % y anota los enfriamientos vencidos."""
    sin_limite(conn)
    estado = pendiente(conn)
    tablas = tablas_a_analizar(conn) if diario else []
    if diario:
        estado["vencidos"] = disponibilidad.marcar_vencidos(conn)
        estado["consultas_reiniciadas"] = _consultas_de_la_semana(conn)
    _reencolar_perdidas(conn)
    hace_falta = (tablas or diario or not estado["disponibilidad_lista"] or estado["disponibilidad_pendientes"]
                  or estado["resumenes_viejos"])
    if hace_falta and not _carga_pesada(conn):
        estado["tarea_id"] = encolar("job diario" if diario else "job de mantenimiento", tablas)
    estado["analizar"] = tablas
    return estado


def _consultas_de_la_semana(conn) -> bool:
    """P-6: las consultas lentas que se muestran son las de los últimos 7 días: pg_stat_statements se reinicia una vez
    por semana (si la extensión está y el usuario puede hacerlo)."""
    try:
        with conn.transaction():
            r = conn.execute("SELECT stats_reset < now() - interval '7 days' AS vieja FROM pg_stat_statements_info").fetchone()
            if r and r["vieja"]:
                conn.execute("SELECT pg_stat_statements_reset()")
                return True
    except Exception:
        pass
    return False


def _reencolar_perdidas(conn):
    """Un mantenimiento que quedó «pendiente» sin que nadie lo despache (más de 15 minutos) vuelve a la cola."""
    for r in conn.execute("SELECT id FROM tarea WHERE tipo = %s AND estado = 'pendiente'"
                          " AND actualizado < now() - interval '15 minutes'", (TIPO,)).fetchall():
        if settings.TASKS_MODE != "inline":
            tareas.despachar(r["id"])


def en_curso(conn) -> dict | None:
    """La tarea de mantenimiento que está corriendo o en cola (para la pantalla)."""
    return conn.execute("SELECT id, estado, mensaje, progreso, total, creado FROM tarea WHERE tipo = %s"
                        " AND estado IN ('pendiente', 'corriendo') ORDER BY id LIMIT 1", (TIPO,)).fetchone()
