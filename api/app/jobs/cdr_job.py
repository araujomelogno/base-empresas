"""Job del CDR (R1.8 y SPEC_job_cdr_en_cloud R4–R5): lee las llamadas nuevas de la base MySQL
de uContact y las procesa con cdr.procesar_lote, en el mismo proceso.

Corre como Cloud Run job `empresas-cdr` con la misma imagen de la API; Cloud Scheduler lo
ejecuta todos los días a las 4:00 (hora de Montevideo) y "Correr ahora" lo lanza desde la
pantalla Configuración. La conexión sale del bloque `cdr` de la configuración y la contraseña
de Secret Manager. Toma TODAS las llamadas, de campañas y del marcador manual: el cruce es por
número destino. Es incremental: el estado (última calldate y los uniqueid de ese segundo) vive
en la tabla cdr_estado y avanza en la misma transacción que cada lote, nunca hacia atrás.
Re-procesar un período es seguro porque los intentos son idempotentes por cdr_id.

    python -m app.jobs.cdr_job                                    # incremental
    python -m app.jobs.cdr_job --desde 2026-10-01 --hasta 2026-10-02   # reproceso
    python -m app.jobs.cdr_job --dry-run                          # no escribe intentos
"""
import argparse
import datetime as dt
import json
import logging
import sys
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

from .. import cdr, cdr_mysql, config, secretos, storage
from ..db import conexion, pool

log = logging.getLogger("cdr_job")
ACTOR = "job:cdr"
ORIGEN = "uContact"
FORMATO_FECHA = cdr_mysql.FORMATO_FECHA
CANDADO = 727001  # pg_advisory_lock: una sola corrida a la vez


# ─── Fila del CDR → llamada ───

def _fecha(v) -> dt.datetime:
    return cdr_mysql._fecha(v)


def _texto_fecha(v) -> str:
    return _fecha(v).strftime(FORMATO_FECHA)


def _vacio_a_none(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def fila_a_llamada(fila: dict, tz: ZoneInfo) -> dict:
    """Una fila de la tabla cdr al formato que recibe cdr.procesar_lote."""
    inicio = fila["calldate"] if isinstance(fila["calldate"], dt.datetime) else _fecha(fila["calldate"])
    inicio = inicio.replace(tzinfo=tz) if inicio.tzinfo is None else inicio.astimezone(tz)
    billsec, duration = fila.get("billsec"), fila.get("duration")
    duracion = billsec if billsec is not None and str(billsec).strip() != "" else duration
    return {
        "cdr_id": str(fila["uniqueid"]).strip(),
        "inicio": inicio.isoformat(),
        "destino": _vacio_a_none(fila.get("dst")),
        "encuestador": _vacio_a_none(fila.get("peeraccount")),
        "duracion": int(float(duracion)) if duracion is not None and str(duracion).strip() != "" else None,
        "userfield": _vacio_a_none(fila.get("userfield")),
        "disposicion": _vacio_a_none(fila.get("disposition")),
        "campania": _vacio_a_none(fila.get("campania", fila.get("accountcode"))),
    }


def deduplicar(filas: list[dict]) -> list[dict]:
    """Varios tramos con el mismo uniqueid: queda uno (el de más billsec), en el orden original."""
    mejor: dict[str, dict] = {}
    orden = []
    for f in filas:
        uid = str(f.get("uniqueid") or "").strip()
        if not uid:
            continue
        if uid not in mejor:
            orden.append(uid)
            mejor[uid] = f
        elif (f.get("billsec") or 0) > (mejor[uid].get("billsec") or 0):
            mejor[uid] = f
    return [mejor[u] for u in orden]


def lotes(items: list, tamano: int):
    for i in range(0, len(items), max(1, tamano)):
        yield items[i:i + tamano]


# ─── Estado incremental (tabla cdr_estado) ───

def leer_estado(conn) -> dict:
    r = conn.execute("SELECT ultima_calldate, uniqueids FROM cdr_estado WHERE id = 1").fetchone()
    if not r or r["ultima_calldate"] is None:
        return {}
    return {"ultima_calldate": r["ultima_calldate"].strftime(FORMATO_FECHA), "uniqueids_en_ultima": list(r["uniqueids"])}


def guardar_estado(conn, estado: dict) -> None:
    conn.execute(
        "INSERT INTO cdr_estado (id, ultima_calldate, uniqueids, actualizado) VALUES (1, %s, %s, now())"
        " ON CONFLICT (id) DO UPDATE SET ultima_calldate = EXCLUDED.ultima_calldate, uniqueids = EXCLUDED.uniqueids,"
        " actualizado = now()", (estado["ultima_calldate"], estado["uniqueids_en_ultima"]))


def avanzar(estado: dict, filas: list[dict]) -> dict:
    """Nuevo estado tras procesar `filas` (ordenadas). Nunca retrocede."""
    if not filas:
        return estado
    ultima = max(_texto_fecha(f["calldate"]) for f in filas)
    previa = estado.get("ultima_calldate")
    if previa and previa > ultima:
        return estado
    del_segundo = {str(f["uniqueid"]) for f in filas if _texto_fecha(f["calldate"]) == ultima}
    if previa == ultima:
        del_segundo |= set(estado.get("uniqueids_en_ultima") or [])
    return {"ultima_calldate": ultima, "uniqueids_en_ultima": sorted(del_segundo)}


def ya_enviada(fila: dict, estado: dict) -> bool:
    """La consulta trae desde la última calldate inclusive; se saltean las de ese segundo ya procesadas."""
    previa = estado.get("ultima_calldate")
    if not previa:
        return False
    f = _texto_fecha(fila["calldate"])
    return f < previa or (f == previa and str(fila["uniqueid"]) in set(estado.get("uniqueids_en_ultima") or []))


def sumar(total: dict, resp: dict) -> dict:
    """Acumula los conteos de procesar_lote (números y dicts de números)."""
    for k, v in resp.items():
        if isinstance(v, bool) or k == "lote_id":
            continue
        if isinstance(v, (int, float)):
            total[k] = total.get(k, 0) + v
        elif isinstance(v, dict):
            sumar(total.setdefault(k, {}), v)
    return total


# ─── Corridas (tabla cdr_corrida) ───

def crear_corrida(conn, origen: str, solicitada_por: str | None = None, desde=None, hasta=None,
                  dry_run: bool = False) -> int:
    return conn.execute(
        "INSERT INTO cdr_corrida (origen, solicitada_por, pedido_desde, pedido_hasta, dry_run)"
        " VALUES (%s,%s,%s,%s,%s) RETURNING id", (origen, solicitada_por, desde, hasta, dry_run)).fetchone()["id"]


def _actualizar(corrida_id: int, **campos):
    """En su propia transacción, para que el avance se vea mientras corre."""
    sets, vals = [], []
    for k, v in campos.items():
        sets.append(f"{k} = %s")
        vals.append(Jsonb(v) if k == "conteos" else v)
    with conexion() as c:
        c.execute(f"UPDATE cdr_corrida SET {', '.join(sets)} WHERE id = %s", (*vals, corrida_id))


def _terminar(corrida_id: int, estado: str, mensaje: str | None = None, **campos):
    _actualizar(corrida_id, estado=estado, mensaje=mensaje, fin=dt.datetime.now(dt.timezone.utc), **campos)


class _DryRun(Exception):
    pass


# ─── Ejecución ───

def ejecutar(args, leer=None) -> int:
    """Devuelve el código de salida: 0 bien u omitida, 1 error. `leer` reemplaza la lectura de MySQL en los tests."""
    leer = leer or cdr_mysql.leer
    with conexion() as conn:
        _, params = config.vigente(conn)
        p = config.cdr(params)
        corrida_id = args.corrida or crear_corrida(conn, "programada", None, args.desde, args.hasta, args.dry_run)

    # Una sola corrida a la vez: el candado se mantiene en una conexión aparte durante todo el job
    with pool().connection() as candado:
        candado.autocommit = True
        if not candado.execute("SELECT pg_try_advisory_lock(%s) AS ok", (CANDADO,)).fetchone()["ok"]:
            _terminar(corrida_id, "omitida", "Había otra corrida del CDR en curso")
            return 0
        try:
            return _ejecutar(args, p, corrida_id, leer)
        finally:
            candado.execute("SELECT pg_advisory_unlock(%s)", (CANDADO,))


def _ejecutar(args, p: dict, corrida_id: int, leer) -> int:
    faltan = [c for c in ("host", "base", "usuario") if not p[c]]
    if not p["activo"]:
        _terminar(corrida_id, "omitida", "El job del CDR no está activo (Configuración → CDR)")
        return 0
    if faltan:
        _terminar(corrida_id, "omitida", f"Faltan parámetros de conexión: {', '.join(faltan)}")
        return 0
    password = None
    try:
        password = secretos.leer_cdr()
        if not password:
            _terminar(corrida_id, "omitida", "La contraseña de MySQL del CDR no está configurada")
            return 0
        tz = ZoneInfo(p["zona_horaria"])
        with conexion() as conn:
            estado = leer_estado(conn)
        hasta = _fecha(args.hasta) if args.hasta else None
        if args.desde:
            desde = _fecha(args.desde)
        elif estado.get("ultima_calldate"):
            desde = _fecha(estado["ultima_calldate"])
        else:
            desde = dt.datetime.combine(dt.date.today() - dt.timedelta(days=1), dt.time())
            log.info("Primera corrida sin estado: se toma desde ayer")
        log.info("Corrida %s: leyendo CDR desde %s%s", corrida_id, desde, f" hasta {hasta}" if hasta else "")
        filas = leer(p, password, desde, hasta)
        leidas = len(filas)
        if not args.desde:
            filas = [f for f in filas if not ya_enviada(f, estado)]
        filas = deduplicar(filas)
        llamadas = [fila_a_llamada(f, tz) for f in filas]
        total = {"filas_leidas": leidas, "llamadas": len(llamadas)}
        rango = {}
        if filas:
            fechas = [_fecha(f["calldate"]) for f in filas]
            rango = {"leido_desde": min(fechas), "leido_hasta": max(fechas)}
        log.info("Corrida %s: %d filas leídas, %d llamadas a procesar", corrida_id, leidas, len(llamadas))

        if args.dry_run:
            # Mismo procesamiento dentro de un savepoint que se descarta: conteos reales, nada escrito
            with conexion() as conn:
                try:
                    with conn.transaction():
                        for lote_ll in lotes(llamadas, p["lote_tamano"]):
                            sumar(total, cdr.procesar_lote(conn, lote_ll, ORIGEN, ACTOR))
                        raise _DryRun()
                except _DryRun:
                    pass
                ruta = f"cdr/dry-run/corrida-{corrida_id}.json"
                ubicacion = storage.escribir(ruta, json.dumps({"origen": ORIGEN, "llamadas": llamadas},
                                                              ensure_ascii=False).encode())
            _terminar(corrida_id, "ok", f"Dry-run: no se guardaron intentos. Payload en {ubicacion}", conteos=total,
                      **rango)
            return 0

        for n, (lote_f, lote_ll) in enumerate(zip(lotes(filas, p["lote_tamano"]), lotes(llamadas, p["lote_tamano"])), 1):
            with conexion() as conn:  # lote y estado en la misma transacción
                resp = cdr.procesar_lote(conn, lote_ll, ORIGEN, ACTOR)
                conn.execute("UPDATE cdr_lote SET corrida_id = %s WHERE id = %s", (corrida_id, resp["lote_id"]))
                nuevo = avanzar(estado, lote_f)
                if nuevo is not estado:
                    guardar_estado(conn, nuevo)
            estado = nuevo
            sumar(total, resp)
            _actualizar(corrida_id, conteos=total)
            log.info("Corrida %s, lote %d: %s", corrida_id, n, json.dumps(resp, ensure_ascii=False, default=str))
        _terminar(corrida_id, "ok", None, conteos=total, **rango)
        return 0
    except Exception as e:
        err = cdr_mysql.clasificar(e, p, password) if _es_de_mysql(e) else None
        mensaje = err.mensaje if err else f"{type(e).__name__}: {e}"
        if password:
            mensaje = mensaje.replace(password, "***")
        log.error("Corrida %s falló: %s", corrida_id, mensaje)
        _terminar(corrida_id, "error", mensaje[:1000])
        return 1


def _es_de_mysql(e: Exception) -> bool:
    return isinstance(e, cdr_mysql.ErrorCdr) or type(e).__module__.startswith("pymysql") or isinstance(e, OSError)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--desde", help="Fecha inicial AAAA-MM-DD (reproceso; ignora el estado para leer)")
    p.add_argument("--hasta", help="Fecha final AAAA-MM-DD, exclusiva")
    p.add_argument("--dry-run", action="store_true", help="No guarda intentos: deja el payload en el bucket")
    p.add_argument("--corrida", type=int, help="Id de la corrida creada por «Correr ahora» (uso interno)")
    return p


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    args = parser().parse_args(argv)
    try:
        return ejecutar(args)
    except psycopg.Error:
        log.exception("Error de base de datos en el job del CDR")
        return 1


if __name__ == "__main__":
    sys.exit(main())
