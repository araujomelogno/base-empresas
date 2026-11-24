"""Cargas grandes por lotes (SPEC_cargas_grandes_por_lotes; D50).

Una carga deja de ser «todo o nada». El archivo se parsea una vez, al analizarlo (archivo_fila, D51), y el primer paso
del preview reparte sus filas en lotes (carga_fila): todas las filas con el mismo RUT caen en el mismo lote, y las que no traen un RUT válido van al final. El
preview, la confirmación y el deshacer corren como tareas por pasos (tareas.Continuar): cada lote o tanda es una
transacción corta y una ejecución de la tarea, muy lejos del límite de 30 minutos de Cloud Run y Cloud Tasks.

- Preview: cada lote corre en un savepoint que se descarta y guarda sus conteos; al final se suman.
- Confirmación: cada lote se aplica en su transacción y queda «aplicado» en carga_lote (idempotente: un lote
  aplicado no se vuelve a aplicar). Los intermediarios se detectan por lote, sobre los teléfonos que tocó.
- Si la cadena se corta (error, cancelación o una tarea trabada), la carga queda «interrumpida» con lo aplicado
  hasta ahí, y se puede reanudar, deshacer o borrar.
- Una carga pesada a la vez (confirmar, deshacer, borrar): las demás esperan en cola y arrancan solas.
"""
import gc
import logging
import time
from collections import Counter

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, cargas, config, contactos, empresas, intermediarios, mantenimiento, medicion, memoria, rut as rutmod, tareas
from .db import conexion
from .util import celda_json, texto

log = logging.getLogger(__name__)
PESADAS = ("en_proceso", "deshaciendo", "borrando")
TANDA_BORRADO = 20000      # filas por sentencia al quitar lo que aportó una carga
TANDA_EMPRESAS = 2000      # empresas por paso al recalcular
GC_DESDE = 1000           # después de un lote de al menos estas filas se libera la memoria (gc.collect)
ALARMA_SEGUNDOS = 600      # un lote que tarda más que esto deja una alarma en el log


# ─────────────────────────────────────────────────────────────
# L1 · Filas guardadas una vez, repartidas en lotes por RUT
# ─────────────────────────────────────────────────────────────

_celda = celda_json


def armar_lotes(filas: list[dict], mapeo: dict, tamano: int, cortos: bool = False) -> list[int]:
    """Número de lote de cada fila. Las filas con el mismo RUT válido van juntas (en el orden en que aparece el RUT
    por primera vez), sin partir un grupo; las que no traen un RUT válido van en los últimos lotes."""
    col = mapeo.get("rut")
    grupos: dict[str, list[int]] = {}
    sin_rut: list[int] = []
    for i, f in enumerate(filas):
        r = rutmod.validar(texto(f.get(col)), cortos)[0] if col and texto(f.get(col)) else None
        if r:
            grupos.setdefault(r, []).append(i)
        else:
            sin_rut.append(i)
    lote_de = [0] * len(filas)
    lote, ocupado = 1, 0
    for idx in grupos.values():
        if ocupado and ocupado + len(idx) > tamano:
            lote, ocupado = lote + 1, 0
        for i in idx:
            lote_de[i] = lote
        ocupado += len(idx)
    if sin_rut:
        if ocupado:
            lote, ocupado = lote + 1, 0
        for i in sin_rut:
            if ocupado >= tamano:
                lote, ocupado = lote + 1, 0
            lote_de[i] = lote
            ocupado += 1
    return lote_de


def preparar_lotes(conn, carga: dict, tarea_id: int | None = None) -> dict:
    """Reparte las filas del archivo (archivo_fila, guardadas al analizarlo) en lotes por RUT: carga_fila guarda solo el
    lote de cada fila. Lo hace el primer paso del preview (D51), con «Preparando los lotes…» en la pantalla."""
    archivo = cargas.asegurar_filas(conn, carga["archivo_id"])
    n = archivo["n_filas"] or 0
    tareas.mensaje(tarea_id, f"Preparando los lotes… {n:,} filas".replace(",", "."))
    col = (carga["mapeo"] or {}).get("rut")
    filas = conn.execute("SELECT fila, datos -> %s AS rut FROM archivo_fila WHERE archivo_id = %s ORDER BY fila",
                         (col or "", archivo["id"])).fetchall()
    _, params = config.vigente(conn)
    lote_de = armar_lotes([{col: f["rut"]} if col else {} for f in filas], carga["mapeo"] or {},
                          config.cargas(params)["tamano_lote"], config.rut_cortos(params))
    conn.execute("DELETE FROM carga_fila WHERE carga_id = %s", (carga["id"],))
    conn.execute("DELETE FROM carga_lote WHERE carga_id = %s", (carga["id"],))
    with conn.cursor() as cur:
        with cur.copy("COPY carga_fila (carga_id, fila, lote) FROM STDIN") as cp:
            for f, lote in zip(filas, lote_de):
                cp.write_row((carga["id"], f["fila"], lote))
    conn.execute(
        "INSERT INTO carga_lote (carga_id, numero, filas, fila_desde, fila_hasta)"
        " SELECT carga_id, lote, count(*), min(fila), max(fila) FROM carga_fila WHERE carga_id = %s GROUP BY carga_id, lote",
        (carga["id"],))
    n_lotes = max(lote_de, default=0)
    conn.execute("UPDATE carga SET lotes = %s, n_filas = %s WHERE id = %s", (n_lotes, len(filas), carga["id"]))
    return {**carga, "lotes": n_lotes, "n_filas": len(filas)}


def filas_lote(conn, carga_id: int, lote: int) -> list[tuple[int, dict]]:
    """Las filas de un lote. Los datos están en archivo_fila (cargas desde D51) o en carga_fila (cargas anteriores)."""
    sql = ("SELECT cf.fila, coalesce(cf.datos, af.datos) AS datos FROM carga_fila cf"
           " LEFT JOIN archivo_fila af ON af.archivo_id = (SELECT archivo_id FROM carga WHERE id = cf.carga_id)"
           "  AND af.fila = cf.fila WHERE cf.carga_id = %s AND cf.lote = %s ORDER BY cf.fila")
    filas = conn.execute(sql, (carga_id, lote)).fetchall()
    if any(f["datos"] is None for f in filas):  # las filas del archivo se liberaron: se vuelven a leer una vez
        aid = conn.execute("SELECT archivo_id FROM carga WHERE id = %s", (carga_id,)).fetchone()["archivo_id"]
        cargas.asegurar_filas(conn, aid)
        filas = conn.execute(sql, (carga_id, lote)).fetchall()
    return [(f["fila"], f["datos"]) for f in filas]


# ─────────────────────────────────────────────────────────────
# Conteos: los de cada lote se suman
# ─────────────────────────────────────────────────────────────

LIMITES = {"coincidencias_a_decidir": 500, "conflictos_ejemplos": 30}


def sumar_conteos(total: dict, parte: dict) -> dict:
    for k, v in (parte or {}).items():
        if isinstance(v, bool) or isinstance(v, str):
            total[k] = v
        elif isinstance(v, (int, float)):
            total[k] = total.get(k, 0) + v
        elif isinstance(v, dict):
            total[k] = sumar_conteos(dict(total.get(k) or {}), v)
        elif isinstance(v, list):
            total[k] = (list(total.get(k) or []) + v)[:LIMITES.get(k, 1000)]
        else:
            total[k] = v
    return total


def _total_conteos(conn, carga_id: int, columna: str) -> dict:
    total: dict = {}
    for r in conn.execute(f"SELECT {columna} AS c FROM carga_lote WHERE carga_id = %s ORDER BY numero", (carga_id,)):
        sumar_conteos(total, r["c"] or {})
    return total


# ─────────────────────────────────────────────────────────────
# Una carga pesada a la vez (confirmar, deshacer, borrar)
# ─────────────────────────────────────────────────────────────

def ocupada(conn, carga_id: int) -> int | None:
    """La carga pesada que está corriendo (otra que esta), si hay."""
    r = conn.execute(
        "SELECT c.id FROM carga c JOIN tarea t ON t.id = c.tarea_id WHERE c.estado = ANY(%s) AND c.cola IS NULL"
        " AND t.estado IN ('pendiente', 'corriendo') AND c.id <> %s ORDER BY c.id LIMIT 1",
        (list(PESADAS), carga_id)).fetchone()
    return r["id"] if r else None


def iniciar_pesada(conn, carga: dict, operacion: str, estado: str, tipo: str, actor: str,
                   payload: dict | None = None) -> dict:
    """Crea la tarea de la operación. Si otra carga pesada está corriendo, la deja en cola (no hay que despacharla:
    arranca sola cuando la otra termina). Devuelve {tarea_id, en_cola, esperando}."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('cargas_pesadas'))")
    otra = ocupada(conn, carga["id"])
    tid = tareas.crear(conn, tipo, payload or {"carga_id": carga["id"]}, actor)
    conn.execute("UPDATE carga SET estado = %s, operacion = %s, tarea_id = %s, cola = CASE WHEN %s THEN now() END,"
                 " error = NULL, paso = CASE WHEN operacion = %s THEN paso END WHERE id = %s",
                 (estado, operacion, tid, otra is not None, operacion, carga["id"]))
    if otra:
        conn.execute("UPDATE tarea SET mensaje = %s WHERE id = %s", (f"Esperando a que termine la carga #{otra}", tid))
    auditoria.registrar(conn, actor, f"carga.{operacion}.iniciar", "carga", carga["id"],
                        {"tarea_id": tid, "en_cola_detras_de": otra})
    return {"tarea_id": tid, "en_cola": otra is not None, "esperando": otra}


def siguiente_en_cola(conn) -> int | None:
    """Si no queda ninguna carga pesada corriendo, saca de la cola la más vieja y devuelve su tarea para despacharla."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('cargas_pesadas'))") if not conn.autocommit else None
    if ocupada(conn, 0):
        return None
    r = conn.execute("SELECT id, tarea_id FROM carga WHERE cola IS NOT NULL ORDER BY cola LIMIT 1").fetchone()
    if r is None:
        return None
    conn.execute("UPDATE carga SET cola = NULL WHERE id = %s", (r["id"],))
    conn.execute("UPDATE tarea SET mensaje = NULL, actualizado = now() WHERE id = %s", (r["tarea_id"],))
    return r["tarea_id"]


def _liberar_al_terminar(conn):
    tid = siguiente_en_cola(conn)
    if tid:
        tareas.despues(tid)


# ─────────────────────────────────────────────────────────────
# Cortes: error, cancelación o tarea trabada → «interrumpida»
# ─────────────────────────────────────────────────────────────

def _interrumpir(c, carga_id: int, tarea_id: int, mensaje: str) -> list[int]:
    carga = c.execute("SELECT * FROM carga WHERE id = %s", (carga_id,)).fetchone()
    if carga is None or carga["tarea_id"] != tarea_id:
        return []  # la carga ya pasó a otra operación (por ejemplo, se pidió borrarla)
    # Cada UPDATE vuelve a exigir la misma tarea: si entre la lectura y la escritura se pidió borrar la carga (y ese
    # pedido hizo commit mientras esperábamos su bloqueo), no se pisa el «borrando» del pedido nuevo.
    if carga["operacion"] == "borrar":
        # El borrado queda «borrando»: volver a tocar «Borrar carga» lo retoma
        hecho = c.execute("UPDATE carga SET error = %s WHERE id = %s AND tarea_id = %s RETURNING id",
                          (mensaje, carga_id, tarea_id)).fetchone()
    else:
        hecho = c.execute("UPDATE carga SET estado = 'interrumpida', error = %s, cola = NULL WHERE id = %s AND tarea_id = %s"
                          " RETURNING id", (mensaje, carga_id, tarea_id)).fetchone()
    if hecho is None:
        return []
    if carga["operacion"] != "borrar":
        c.execute("UPDATE carga_lote SET estado = 'error', error = %s WHERE carga_id = %s AND numero ="
                  " (SELECT min(numero) FROM carga_lote WHERE carga_id = %s AND estado <> 'aplicado')"
                  " AND %s = 'confirmar'", (mensaje, carga_id, carga_id, carga["operacion"]))
    log.warning("Carga %s interrumpida (%s): %s", carga_id, carga["operacion"], mensaje)
    tid = siguiente_en_cola(c)
    return [tid] if tid else []


def _al_cortarse(c, t, mensaje, cancelada):
    cid = t["payload"].get("carga_id") or t["payload"].get("borrar_carga_id")
    return _interrumpir(c, cid, t["id"], "Cancelada" if cancelada else mensaje)


for _tipo in ("carga.preview", "carga.confirmar", "carga.deshacer", "carga.borrar"):
    tareas.al_cortarse(_tipo)(_al_cortarse)


def revisar_trabadas() -> list[int]:
    """Respaldo de la reanudación automática (D52). Una tarea de carga que no avanza hace más que el plazo configurado
    (10 minutos; una tarea viva late cada 30 s) se dio por cortada: la primera vez se vuelve a encolar sola, desde el
    lote o paso que no se terminó; si se vuelve a cortar, la carga queda «interrumpida» para que una persona decida.
    Cubre también una tarea «pendiente» cuyo aviso de Cloud Tasks se perdió. La llaman la pantalla de cargas y el
    job diario. Despacha lo que estaba en cola. Devuelve las cargas que quedaron interrumpidas."""
    despachar, interrumpidas = [], []
    with conexion() as conn:
        _, params = config.vigente(conn)
        mins = config.cargas(params)["minutos_trabada"]
        trabadas = conn.execute(
            "SELECT c.id AS carga_id, t.id AS tarea_id, t.reintentos_auto FROM carga c JOIN tarea t ON t.id = c.tarea_id"
            " WHERE t.estado IN ('corriendo', 'pendiente') AND c.cola IS NULL"
            " AND t.actualizado < now() - make_interval(mins => %s)"
            " AND c.estado IN ('analizando', 'en_proceso', 'deshaciendo', 'borrando')", (mins,)).fetchall()
        for r in trabadas:
            if r["reintentos_auto"] < 1:
                conn.execute("UPDATE tarea SET estado = 'pendiente', dueno = NULL, reintentos_auto = reintentos_auto + 1,"
                             " actualizado = now(), mensaje = 'Retomando: el proceso anterior se cortó' WHERE id = %s",
                             (r["tarea_id"],))
                log.warning("Carga %s: la tarea %s no avanzó en %s minutos; se retoma sola", r["carga_id"], r["tarea_id"], mins)
                despachar.append(r["tarea_id"])
                continue
            msg = (f"Se cortó: la tarea no avanzó en más de {mins} minutos, tampoco después de retomarla sola "
                   "(probablemente se reinició el servidor)")
            conn.execute("UPDATE tarea SET estado = 'error', error = %s, terminado = now(), dueno = NULL WHERE id = %s",
                         (msg, r["tarea_id"]))
            despachar += _interrumpir(conn, r["carga_id"], r["tarea_id"], msg)
            interrumpidas.append(r["carga_id"])
        if not despachar:
            tid = siguiente_en_cola(conn)  # una cola que quedó sin dueño
            despachar += [tid] if tid else []
    for tid in despachar:
        tareas.despachar(tid)
    return interrumpidas


def reanudar(conn, carga_id: int, actor: str) -> dict:
    """«Reanudar» una carga interrumpida: sigue la operación desde el primer lote (o paso) que no se hizo."""
    carga = conn.execute("SELECT * FROM carga WHERE id = %s FOR UPDATE", (carga_id,)).fetchone()
    if carga is None:
        raise HTTPException(404, "Carga inexistente")
    if carga["estado"] != "interrumpida":
        raise HTTPException(409, f"Solo se reanuda una carga interrumpida (está {carga['estado']})")
    op = carga["operacion"]
    if op == "preview":
        tid = tareas.crear(conn, "carga.preview", {"carga_id": carga_id}, actor)
        conn.execute("UPDATE carga SET estado = 'analizando', tarea_id = %s, error = NULL WHERE id = %s", (tid, carga_id))
        auditoria.registrar(conn, actor, "carga.reanudar", "carga", carga_id, {"operacion": op})
        return {"tarea_id": tid, "en_cola": False, "esperando": None}
    if op == "confirmar":
        conn.execute("UPDATE carga_lote SET estado = 'pendiente', error = NULL WHERE carga_id = %s AND estado <> 'aplicado'",
                     (carga_id,))
        r = iniciar_pesada(conn, carga, "confirmar", "en_proceso", "carga.confirmar", actor)
    elif op == "deshacer":
        r = iniciar_pesada(conn, carga, "deshacer", "deshaciendo", "carga.deshacer", actor)
    else:
        raise HTTPException(409, "No hay nada para reanudar")
    auditoria.registrar(conn, actor, "carga.reanudar", "carga", carga_id, {"operacion": op})
    return r


# ─────────────────────────────────────────────────────────────
# L2 · Preview por lotes
# ─────────────────────────────────────────────────────────────

class _Descartar(Exception):
    pass


def _sigue_vigente(conn, carga_id: int, tarea_id: int, estado: str):
    """Antes del commit de cada paso: la carga sigue en esta operación. Bloquea su fila hasta el commit, así un pedido
    de borrado (o una cancelación) que llegó a mitad del lote lo revierte en lugar de dejarlo aplicado a medias."""
    r = conn.execute("SELECT estado, tarea_id FROM carga WHERE id = %s FOR NO KEY UPDATE", (carga_id,)).fetchone()
    if r is None or r["estado"] != estado or r["tarea_id"] != tarea_id:
        raise tareas.Cancelada(f"La carga #{carga_id} pasó a otra operación")
    tareas.sigo_siendo_dueno(conn, tarea_id)  # D52: si otro proceso la retomó, este paso no se confirma
    tareas.progreso(tarea_id, *conn.execute("SELECT progreso, total FROM tarea WHERE id = %s", (tarea_id,)).fetchone().values())


# Tablas que crecen al aplicar una carga
_TABLAS_CARGA = ("empresa", "empresa_campo_historia", "empresa_atributo", "telefono", "telefono_vinculo",
                 "telefono_vinculo_origen", "contacto", "sucursal")


ANALIZAR_CADA = 5          # V1 (D53): al confirmar, las estadísticas se actualizan antes de los lotes 1, 6, 11…
LENTO_FILAS_S = 20         # V3: un lote más lento que esto deja un warning


def analizar_tablas():
    """ANALYZE de las tablas que toca una carga, en una conexión aparte (fuera de la transacción del lote): con las
    estadísticas viejas («0 filas»), Postgres recorre tablas enteras en lugar de usar los índices. D55: de a una tabla,
    con la duración en el log."""
    mantenimiento.analizar(_TABLAS_CARGA)


def planes_correctos(conn):
    """V1 (D53): dentro del lote, un plan por consulta con las estadísticas actuales (psycopg prepara las consultas
    que se repiten y Postgres fijaría un plan genérico) y los índices aunque las estadísticas digan «tabla vacía»."""
    conn.execute("SET LOCAL plan_cache_mode = force_custom_plan")
    conn.execute("SET LOCAL enable_seqscan = off")
    # Con los recorridos «deshabilitados», Postgres les pone un costo enorme y cualquier lectura de una tabla chica
    # (los catálogos) pasa el umbral del JIT: compilaría cada consulta (~100 ms). Medido: 7 veces más lento.
    conn.execute("SET LOCAL jit = off")


ANALIZAR_DESDE = 500       # un lote más chico no lo justifica (autovacuum alcanza; y los tests usan lotes de 2 filas)


# Las que miran las consultas del preview (intermediarios y coincidencias)
_TABLAS_PREVIEW = ("empresa", "telefono", "telefono_vinculo")


def analizar_en_el_lote(conn, numero: int, filas: int, preview: bool = False):
    """Después de escribir el primer lote, ANALYZE dentro de su transacción: ve las filas recién insertadas. Sin
    esto, con la base vacía al empezar, Postgres cree que las tablas tienen 0 filas y arma planes que recorren tablas
    enteras por cada fila (medido: la detección de intermediarios, de 1 s a 46 s en el tercer lote de 5.000).
    D55: en el preview, en cada lote. Lo que escribe se descarta, así que un ANALYZE de afuera (autovacuum) ve las
    tablas vacías y deja «0 filas»: medido, de 1,2 s a 6 s por lote desde el segundo."""
    if filas < ANALIZAR_DESDE:
        return
    if numero == 1:
        conn.execute("ANALYZE " + ", ".join(_TABLAS_CARGA))
    elif preview:
        conn.execute("ANALYZE " + ", ".join(_TABLAS_PREVIEW))


def preparar_lote(conn, numero: int, filas: int, cada: int = 0):
    """Antes del primer lote de una operación (y cada «cada» lotes) se actualizan las estadísticas."""
    if filas >= ANALIZAR_DESDE and (numero == 1 or (cada and (numero - 1) % cada == 0)):
        analizar_tablas()
    planes_correctos(conn)


def medir_lote(cid, operacion, numero, total_lotes, n_filas, seg, med, rss0, rss1, extra=""):
    """V3: «carga=9 preview lote=1/40 filas=4812 segundos=38 filas_s=126 consultas=410 base_s=12.1 rss_mb=…»."""
    filas_s = round(n_filas / seg) if seg else n_filas
    lento = n_filas >= 100 and filas_s < LENTO_FILAS_S
    nivel = logging.WARNING if (seg > ALARMA_SEGUNDOS or lento) else logging.INFO
    log.log(nivel, "carga=%s %s lote=%s/%s filas=%s segundos=%s filas_s=%s consultas=%s base_s=%.1f rss_mb=%s→%s%s%s",
            cid, operacion, numero, total_lotes, n_filas, seg, filas_s, med.consultas, med.segundos, rss0, rss1, extra,
            " ALARMA: lote lento" if nivel == logging.WARNING else "")



def _carga_de_tarea(conn, payload, tarea_id, estados, preparar: bool = True) -> dict | None:
    # Sin bloquear la fila durante todo el lote: se bloquea al final (_sigue_vigente), para no hacer esperar a la web
    carga = conn.execute("SELECT * FROM carga WHERE id = %s", (payload["carga_id"],)).fetchone()
    if carga is None or carga["estado"] not in estados:
        return None
    if carga["tarea_id"] is None:  # carga creada antes de D50
        conn.execute("UPDATE carga SET tarea_id = %s WHERE id = %s", (tarea_id, carga["id"]))
        carga["tarea_id"] = tarea_id
    if carga["tarea_id"] != tarea_id:
        return None  # una tarea vieja (la carga ya pasó a otra operación)
    if not carga["lotes"] and preparar:
        carga = preparar_lotes(conn, carga, tarea_id)
    return carga


def _mensaje(conn, carga, numero, hechas, columna_hecho) -> str:
    total_lotes = carga["lotes"]
    return f"Lote {numero} de {total_lotes} · {hechas:,} de {carga['n_filas']:,} filas".replace(",", ".")


@tareas.handler("carga.preview")
def _tarea_preview(conn, payload, tarea_id):
    carga = _carga_de_tarea(conn, payload, tarea_id, ("analizando",), preparar=False)
    if carga is None:
        return {"omitida": True}
    if not carga["lotes"]:  # primer paso (D51): repartir las filas del archivo en lotes, con su propio aviso
        carga = preparar_lotes(conn, carga, tarea_id)
        _sigue_vigente(conn, carga["id"], tarea_id, "analizando")
        tareas.progreso(tarea_id, 0, carga["n_filas"])
        return tareas.Continuar(f"Lotes listos: {carga['lotes']} · calculando el preview")
    cid = carga["id"]
    _, cfg = config.vigente(conn)
    lote = conn.execute("SELECT * FROM carga_lote WHERE carga_id = %s AND NOT preview_hecho ORDER BY numero LIMIT 1",
                        (cid,)).fetchone()
    hechas = conn.execute("SELECT coalesce(sum(filas), 0) AS n FROM carga_lote WHERE carga_id = %s AND preview_hecho",
                          (cid,)).fetchone()["n"]
    if lote is not None:
        tareas.mensaje(tarea_id, _mensaje(conn, carga, lote["numero"], hechas, "preview_hecho"))
        preparar_lote(conn, lote["numero"], lote["filas"])
        filas = filas_lote(conn, cid, lote["numero"])
        t0, rss0 = time.monotonic(), memoria.rss_mb()
        res = {}
        with medicion.Medicion(conn) as med:
            try:
                with conn.transaction():  # savepoint que se descarta: los conteos son los reales
                    res["conteos"], res["rechazos"], tocados = cargas.procesar(
                        conn, carga, filas, cfg, carga["responsable"], real=False, tarea_id=tarea_id, hechos=hechas,
                        total=carga["n_filas"], mensaje_lote=f"Lote {lote['numero']} de {carga['lotes']}")
                    analizar_en_el_lote(conn, lote["numero"], len(filas), preview=True)
                    ids = sorted(tocados)
                    res["conteos"]["nuevos_sospechosos"] = intermediarios.contar_nuevos(conn, cfg["umbral_intermediario"], ids) if ids else 0
                    raise _Descartar()
            except _Descartar:
                pass
            _sigue_vigente(conn, cid, tarea_id, "analizando")
            cargas.guardar_rechazos(conn, cid, res["rechazos"], [f for f, _ in filas])
        seg = round(time.monotonic() - t0, 1)
        conn.execute("UPDATE carga_lote SET preview_hecho = true, preview_conteos = %s, preview_segundos = %s,"
                     " preview_consultas = %s WHERE carga_id = %s AND numero = %s",
                     (Jsonb(res["conteos"]), seg, med.consultas, cid, lote["numero"]))
        n_lote = len(filas)
        del filas, res
        if n_lote >= GC_DESDE:
            gc.collect()   # R1 (D52): lo del lote no queda ocupando memoria hasta el siguiente
        rss1 = memoria.revisar(f"carga={cid} preview lote={lote['numero']}")
        medir_lote(cid, "preview", lote["numero"], carga["lotes"], n_lote, seg, med, rss0, rss1)
        tareas.progreso(tarea_id, hechas + n_lote, carga["n_filas"])
        return tareas.Continuar(_mensaje(conn, carga, lote["numero"], hechas + n_lote, "preview_hecho"))
    _sigue_vigente(conn, cid, tarea_id, "analizando")
    conteos = _total_conteos(conn, cid, "preview_conteos")
    conteos["lotes"] = carga["lotes"]
    if any(c.get("altas_provisoria") for c in [conteos]) or conteos.get("rechazos_por_motivo", {}).get("sin RUT"):
        conteos["aproximado_sin_rut"] = True  # filas sin RUT de un mismo archivo podrían coincidir entre sí
    conn.execute("UPDATE carga SET conteos = %s, estado = 'preview' WHERE id = %s", (Jsonb(conteos), cid))
    return {"carga_id": cid, "conteos": conteos}


# ─────────────────────────────────────────────────────────────
# L3 · Confirmación por lotes
# ─────────────────────────────────────────────────────────────

@tareas.handler("carga.confirmar")
def _tarea_confirmar(conn, payload, tarea_id):
    carga = _carga_de_tarea(conn, payload, tarea_id, ("en_proceso",))
    if carga is None:
        return {"omitida": True}
    cid = carga["id"]
    _, params = config.vigente(conn)
    ccfg = config.cargas(params)
    lote = conn.execute("SELECT * FROM carga_lote WHERE carga_id = %s AND estado <> 'aplicado' ORDER BY numero LIMIT 1",
                        (cid,)).fetchone()
    hechas = conn.execute("SELECT coalesce(sum(filas), 0) AS n FROM carga_lote WHERE carga_id = %s AND estado = 'aplicado'",
                          (cid,)).fetchone()["n"]
    if lote is not None:
        n = lote["numero"]
        tareas.mensaje(tarea_id, _mensaje(conn, carga, n, hechas, "aplicado"))
        conn.execute("UPDATE carga_lote SET estado = 'en_proceso', intentos = intentos + 1, inicio = now(), error = NULL"
                     " WHERE carga_id = %s AND numero = %s", (cid, n))
        preparar_lote(conn, n, lote["filas"], ANALIZAR_CADA)
        filas = filas_lote(conn, cid, n)
        t0, rss0 = time.monotonic(), memoria.rss_mb()
        with medicion.Medicion(conn) as med:
            conteos, rechazos, tocados = cargas.procesar(conn, carga, filas, params, carga["responsable"], real=True,
                                                         tarea_id=tarea_id, hechos=hechas, total=carga["n_filas"],
                                                         mensaje_lote=f"Lote {n} de {carga['lotes']}")
            analizar_en_el_lote(conn, n, len(filas))
            ids = sorted(tocados)
            # Intermediarios por lote: el conteo de un teléfono solo cambia cuando un lote lo toca (mismo resultado que al final)
            conteos["nuevos_sospechosos"] = len(intermediarios.detectar(conn, params["umbral_intermediario"], ids,
                                                                        carga["responsable"])) if ids else 0
            _sigue_vigente(conn, cid, tarea_id, "en_proceso")
            cargas.guardar_rechazos(conn, cid, rechazos, [f for f, _ in filas])
        seg = round(time.monotonic() - t0, 1)
        conn.execute("UPDATE carga_lote SET estado = 'aplicado', conteos = %s, fin = now(), segundos = %s, consultas = %s"
                     " WHERE carga_id = %s AND numero = %s", (Jsonb(conteos), seg, med.consultas, cid, n))
        n_lote = len(filas)
        del filas, rechazos, tocados
        if n_lote >= GC_DESDE:
            gc.collect()   # R1 (D52)
        rss1 = memoria.revisar(f"carga={cid} confirmar lote={n}")
        medir_lote(cid, "confirmar", n, carga["lotes"], n_lote, seg, med, rss0, rss1,
                   f" altas={conteos.get('altas', 0)} actualizaciones={conteos.get('actualizaciones', 0)}")
        tareas.progreso(tarea_id, hechas + n_lote, carga["n_filas"])
        return tareas.Continuar(_mensaje(conn, carga, n, hechas + n_lote, "aplicado"), ccfg["pausa_segundos"])
    # Paso final: conteos totales, auditoría y se libera la tabla intermedia
    _sigue_vigente(conn, cid, tarea_id, "en_proceso")
    conteos = _total_conteos(conn, cid, "conteos")
    conteos["lotes"] = carga["lotes"]
    conn.execute("UPDATE carga SET estado = 'confirmada', conteos = %s, confirmada = now() WHERE id = %s",
                 (Jsonb(conteos), cid))
    conn.execute("DELETE FROM carga_fila WHERE carga_id = %s", (cid,))
    cargas.liberar_archivo(conn, carga["archivo_id"])
    auditoria.registrar(conn, carga["responsable"], "carga.confirmar", "carga", cid, {"conteos": conteos})
    _liberar_al_terminar(conn)
    mantenimiento.al_terminar(f"carga #{cid} confirmada", mantenimiento.CARGA)   # D55: ANALYZE, disponibilidad, resumen
    return {"carga_id": cid, "conteos": conteos}


# ─────────────────────────────────────────────────────────────
# L5 · Deshacer por pasos
# ─────────────────────────────────────────────────────────────

def _quitar_tanda(conn, cid: int) -> int:
    """Quita una tanda de lo que aportó la carga a teléfonos, contactos y sucursales. Devuelve cuántas filas tocó."""
    x = conn.execute
    n = 0
    r = x("DELETE FROM telefono_vinculo_origen WHERE ctid IN (SELECT ctid FROM telefono_vinculo_origen"
          " WHERE fuente_tipo = 'carga' AND fuente_id = %s LIMIT %s)", (cid, TANDA_BORRADO))
    n += r.rowcount
    vincs = x("DELETE FROM telefono_vinculo WHERE id IN (SELECT id FROM telefono_vinculo WHERE fuente_tipo = 'carga'"
              " AND fuente_id = %s LIMIT %s) RETURNING telefono_id, empresa_id", (cid, TANDA_BORRADO)).fetchall()
    n += len(vincs)
    if vincs:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO carga_trabajo (carga_id, tipo, objeto_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                            [(cid, "telefono", v["telefono_id"]) for v in vincs])
    ids = [r["id"] for r in x("SELECT id FROM contacto WHERE fuente_tipo = 'carga' AND fuente_id = %s LIMIT 2000", (cid,))]
    if ids:
        contactos.borrar(conn, ids)
        n += len(ids)
    n += x("DELETE FROM contacto_telefono WHERE ctid IN (SELECT ctid FROM contacto_telefono WHERE fuente_tipo = 'carga'"
           " AND fuente_id = %s LIMIT %s)", (cid, TANDA_BORRADO)).rowcount
    n += x("DELETE FROM contacto_atributo WHERE ctid IN (SELECT ctid FROM contacto_atributo WHERE fuente_tipo = 'carga'"
           " AND fuente_id = %s LIMIT %s)", (cid, TANDA_BORRADO)).rowcount
    if not n:  # las sucursales, cuando ya no queda nada que las use
        x("UPDATE telefono_vinculo SET sucursal_id = NULL WHERE sucursal_id IN "
          "(SELECT id FROM sucursal WHERE fuente_tipo = 'carga' AND fuente_id = %s)", (cid,))
        n += x("DELETE FROM sucursal WHERE fuente_tipo = 'carga' AND fuente_id = %s", (cid,)).rowcount
    return n


@tareas.handler("carga.deshacer")
def _tarea_deshacer(conn, payload, tarea_id):
    carga = _carga_de_tarea(conn, payload, tarea_id, ("deshaciendo",), preparar=False)
    if carga is None:
        return {"omitida": True}
    cid, actor = carga["id"], tareas_actor(conn, tarea_id)
    _sigue_vigente(conn, cid, tarea_id, "deshaciendo")  # el deshacer actualiza la carga en cada paso: la bloquea de entrada
    if (carga["paso"] or "preparar") == "preparar":
        analizar_tablas()                                # V1 (D53): antes del primer paso
    planes_correctos(conn)
    _, params = config.vigente(conn)
    pausa = config.cargas(params)["pausa_segundos"]
    paso = carga["paso"] or "preparar"
    resumen = dict(carga["resumen_op"] or {})
    if paso == "preparar":
        # Las empresas a recalcular, antes de quitar nada (después ya no se sabe cuáles tocó)
        conn.execute("DELETE FROM carga_trabajo WHERE carga_id = %s", (cid,))
        conn.execute(
            "INSERT INTO carga_trabajo (carga_id, tipo, objeto_id) SELECT %s, 'empresa', empresa_id FROM ("
            " SELECT empresa_id FROM empresa_campo_historia WHERE fuente_tipo = 'carga' AND fuente_id = %s"
            " UNION SELECT empresa_id FROM telefono_vinculo WHERE fuente_tipo = 'carga' AND fuente_id = %s"
            " UNION SELECT id FROM empresa WHERE carga_alta_id = %s) e ON CONFLICT DO NOTHING", (cid, cid, cid, cid))
        n = conn.execute("SELECT count(*) AS n FROM carga_trabajo WHERE carga_id = %s AND tipo = 'empresa'", (cid,)).fetchone()["n"]
        # Las provisorias que esta carga pasó a la definitiva (agregó el RUT) vuelven a la provisoria
        for p in conn.execute("SELECT * FROM carga_promocion WHERE carga_id = %s ORDER BY id DESC", (cid,)).fetchall():
            conn.execute("UPDATE empresa SET rut = %s, base = %s WHERE id = %s", (p["rut_anterior"], p["base_anterior"], p["empresa_id"]))
        conn.execute("UPDATE revision_fusion SET estado = 'descartada', resuelto_por = %s, resuelto = now()"
                     " WHERE carga_id = %s AND estado = 'pendiente'", (actor, cid))
        resumen = {"empresas_recalculadas": n, "empresas_anuladas": 0, "vinculos_borrados": 0}
        conn.execute("UPDATE carga SET paso = 'quitar', resumen_op = %s WHERE id = %s", (Jsonb(resumen), cid))
        tareas.progreso(tarea_id, 0, n + 2)
        return tareas.Continuar(f"Preparando: {n:,} empresas a recalcular".replace(",", "."))
    if paso == "quitar":
        antes = conn.execute("SELECT count(*) AS n FROM carga_trabajo WHERE carga_id = %s AND tipo = 'telefono'", (cid,)).fetchone()["n"]
        tocadas = _quitar_tanda(conn, cid)
        despues = conn.execute("SELECT count(*) AS n FROM carga_trabajo WHERE carga_id = %s AND tipo = 'telefono'", (cid,)).fetchone()["n"]
        resumen["vinculos_borrados"] = resumen.get("vinculos_borrados", 0) + (despues - antes)
        if tocadas == 0:
            conn.execute("UPDATE carga SET paso = 'recalcular', resumen_op = %s WHERE id = %s", (Jsonb(resumen), cid))
        else:
            conn.execute("UPDATE carga SET resumen_op = %s WHERE id = %s", (Jsonb(resumen), cid))
        return tareas.Continuar("Quitando teléfonos, contactos y sucursales de la carga", pausa)
    if paso == "recalcular":
        ids = [r["objeto_id"] for r in conn.execute(
            "SELECT objeto_id FROM carga_trabajo WHERE carga_id = %s AND tipo = 'empresa' ORDER BY objeto_id LIMIT %s",
            (cid, TANDA_EMPRESAS))]
        if ids:
            empresas.recalcular_varias(conn, ids)   # D53: una tanda de consultas, no cinco por empresa
            anuladas = [r["id"] for r in conn.execute(
                "UPDATE empresa e SET baja = 'anulada' WHERE e.id = ANY(%s) AND e.baja IS NULL"
                " AND NOT EXISTS (SELECT 1 FROM empresa_campo_historia h LEFT JOIN carga c ON h.fuente_tipo = 'carga'"
                "   AND c.id = h.fuente_id WHERE h.empresa_id = e.id AND (c.id IS NULL OR NOT " + empresas.CARGA_SIN_EFECTO + "))"
                " AND NOT EXISTS (SELECT 1 FROM telefono_vinculo v WHERE v.empresa_id = e.id)"
                " AND NOT EXISTS (SELECT 1 FROM contacto k WHERE k.empresa_id = e.id) RETURNING e.id", (ids,))]
            # sus teléfonos que quedan también se reevalúan como intermediarios
            conn.execute("INSERT INTO carga_trabajo (carga_id, tipo, objeto_id) SELECT DISTINCT %s, 'telefono', telefono_id"
                         " FROM telefono_vinculo WHERE empresa_id = ANY(%s) ON CONFLICT DO NOTHING", (cid, ids))
            conn.execute("DELETE FROM carga_trabajo WHERE carga_id = %s AND tipo = 'empresa' AND objeto_id = ANY(%s)", (cid, ids))
            resumen["empresas_anuladas"] = resumen.get("empresas_anuladas", 0) + len(anuladas)
            hechas = resumen["empresas_recalculadas"] - conn.execute(
                "SELECT count(*) AS n FROM carga_trabajo WHERE carga_id = %s AND tipo = 'empresa'", (cid,)).fetchone()["n"]
            conn.execute("UPDATE carga SET resumen_op = %s WHERE id = %s", (Jsonb(resumen), cid))
            tareas.progreso(tarea_id, hechas, resumen["empresas_recalculadas"] + 2)
            return tareas.Continuar(f"Recalculando empresas · {hechas:,} de {resumen['empresas_recalculadas']:,}"
                                    .replace(",", "."), pausa)
        conn.execute("UPDATE carga SET paso = 'intermediarios' WHERE id = %s", (cid,))
        return tareas.Continuar("Reevaluando intermediarios")
    # intermediarios (en tandas) y final
    tels = [r["objeto_id"] for r in conn.execute(
        "SELECT objeto_id FROM carga_trabajo WHERE carga_id = %s AND tipo = 'telefono' ORDER BY objeto_id LIMIT 10000", (cid,))]
    if tels:
        intermediarios.reevaluar(conn, tels, actor)
        conn.execute("DELETE FROM carga_trabajo WHERE carga_id = %s AND tipo = 'telefono' AND objeto_id = ANY(%s)", (cid, tels))
        return tareas.Continuar("Reevaluando intermediarios", pausa)
    resumen["estado"] = "deshecha"
    conn.execute("UPDATE carga SET estado = 'deshecha', deshecha = now(), paso = NULL, resumen_op = %s WHERE id = %s",
                 (Jsonb(resumen), cid))
    conn.execute("DELETE FROM carga_fila WHERE carga_id = %s", (cid,))
    cargas.liberar_archivo(conn, carga["archivo_id"])
    conn.execute("DELETE FROM carga_trabajo WHERE carga_id = %s", (cid,))
    auditoria.registrar(conn, actor, "carga.deshacer", "carga", cid, resumen)
    tareas.progreso(tarea_id, resumen["empresas_recalculadas"] + 2, resumen["empresas_recalculadas"] + 2)
    _liberar_al_terminar(conn)
    mantenimiento.al_terminar(f"carga #{cid} deshecha", mantenimiento.CARGA)
    return resumen


def tareas_actor(conn, tarea_id) -> str:
    r = conn.execute("SELECT creado_por FROM tarea WHERE id = %s", (tarea_id,)).fetchone()
    return r["creado_por"] if r else "sistema"


def contar(**k) -> Counter:  # pragma: no cover - ayuda para depurar
    return Counter(k)
