"""Job nocturno del CDR (R1.8): lee las llamadas nuevas de la base MySQL de uContact y las
empuja a la API (POST /api/intentos/lote).

Corre a las 4:00 en el servidor Ubuntu que llega a la base `uc` (timer de systemd). Toma
TODAS las llamadas, de campañas y del marcador manual (no filtra por campaña): el cruce por
número destino lo hace la API. Es incremental: guarda en estado.json la última calldate y los
uniqueid de ese segundo, y avanza el estado solo después de un POST exitoso. Re-procesar un
período es seguro porque la API es idempotente por cdr_id.

    python cdr_job.py                       # incremental (primera vez: --desde o --dias)
    python cdr_job.py --desde 2026-10-01 --hasta 2026-10-02   # re-procesar un día
    python cdr_job.py --dry-run             # escribe el payload en un archivo, no envía
    python cdr_job.py --exportar-auditoria  # además dispara el export de auditoría a BigQuery
"""
import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

AQUI = Path(__file__).resolve().parent
SQL_DEFECTO = ("SELECT uniqueid, calldate, src, dst, duration, billsec, disposition, userfield, peeraccount, accountcode"
               " FROM cdr WHERE calldate >= %s ORDER BY calldate, uniqueid")
FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"

log = logging.getLogger("cdr_job")


class ErrorEnvio(Exception):
    """La API rechazó el lote o no respondió después de los reintentos."""


# ─── Configuración ───

def cargar_env(ruta: Path) -> None:
    """Carga KEY=VALOR de un archivo .env sin pisar variables ya definidas en el entorno."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        os.environ.setdefault(clave.strip(), valor)


def config() -> dict:
    e = os.environ
    return {
        "mysql": {"host": e.get("MYSQL_HOST", "localhost"), "port": int(e.get("MYSQL_PORT", "3306")),
                  "user": e.get("MYSQL_USER", ""), "password": e.get("MYSQL_PASSWORD", ""), "database": e.get("MYSQL_DB", "uc")},
        "api_url": e.get("API_URL", "").rstrip("/"),
        "token": e.get("JOB_TOKEN", ""),
        "sql": e.get("CDR_SQL") or SQL_DEFECTO,
        "lote": int(e.get("LOTE_TAMANO", "2000")),
        "tz": ZoneInfo(e.get("CDR_TZ", "America/Montevideo")),
        "origen": e.get("CDR_ORIGEN", "uContact"),
        "timeout": int(e.get("HTTP_TIMEOUT", "120")),
        "reintentos": int(e.get("HTTP_REINTENTOS", "5")),
    }


# ─── Estado incremental ───

def leer_estado(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_estado(ruta: Path, estado: dict) -> None:
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ruta)          # escritura atómica: nunca queda un estado a medias


def avanzar(estado: dict, filas: list[dict]) -> dict:
    """Nuevo estado tras enviar `filas` (ordenadas). Nunca retrocede."""
    if not filas:
        return estado
    ultima = max(_texto_fecha(f["calldate"]) for f in filas)
    previa = estado.get("ultima_calldate")
    if previa and previa > ultima:
        return estado
    del_segundo = {str(f["uniqueid"]) for f in filas if _texto_fecha(f["calldate"]) == ultima}
    if previa == ultima:
        del_segundo |= set(estado.get("uniqueids_en_ultima") or [])
    ids = sorted(del_segundo)
    return {"ultima_calldate": ultima, "ultimo_uniqueid": ids[-1], "uniqueids_en_ultima": ids,
            "actualizado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


def ya_enviada(fila: dict, estado: dict) -> bool:
    """La consulta trae desde la última calldate inclusive; se saltean las de ese segundo ya enviadas."""
    previa = estado.get("ultima_calldate")
    if not previa:
        return False
    f = _texto_fecha(fila["calldate"])
    return f < previa or (f == previa and str(fila["uniqueid"]) in set(estado.get("uniqueids_en_ultima") or []))


def _fecha(v) -> dt.datetime:
    if isinstance(v, dt.datetime):
        return v
    if isinstance(v, dt.date):
        return dt.datetime.combine(v, dt.time())
    return dt.datetime.fromisoformat(str(v).strip())


def _texto_fecha(v) -> str:
    """calldate local (sin zona) como texto comparable."""
    return _fecha(v).replace(tzinfo=None).strftime(FORMATO_FECHA)


# ─── CDR → payload ───

def _vacio_a_none(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def fila_a_llamada(fila: dict, tz: ZoneInfo) -> dict:
    """Una fila de la tabla cdr al formato de POST /api/intentos/lote."""
    inicio = _fecha(fila["calldate"])
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


# ─── MySQL ───

def leer_cdr(cfg: dict, desde: dt.datetime, hasta: dt.datetime | None) -> list[dict]:
    """Llamadas con calldate >= desde (y < hasta). pymysql se importa acá: los tests no lo necesitan."""
    import pymysql
    import pymysql.cursors

    conn = pymysql.connect(**cfg["mysql"], charset="utf8mb4", cursorclass=pymysql.cursors.SSDictCursor,
                           connect_timeout=30, read_timeout=600)
    filas = []
    try:
        with conn.cursor() as cur:
            # CDR_SQL puede tener un %s (desde) o dos (desde, hasta) para no leer de más al re-procesar
            params = [desde.strftime(FORMATO_FECHA)]
            if cfg["sql"].count("%s") >= 2:
                params.append((hasta or dt.datetime(9999, 1, 1)).strftime(FORMATO_FECHA))
            cur.execute(cfg["sql"], params)
            while True:
                bloque = cur.fetchmany(5000)
                if not bloque:
                    break
                for f in bloque:
                    if hasta and _fecha(f["calldate"]) >= hasta:
                        return filas      # la consulta viene ordenada por calldate
                    filas.append(f)
    finally:
        conn.close()
    return filas


# ─── HTTP ───

def post_json(url: str, cuerpo: dict | None, token: str, timeout: int, reintentos: int) -> dict:
    """POST con X-Job-Token. Reintenta con espera exponencial ante errores de red y 5xx/429."""
    datos = json.dumps(cuerpo or {}, ensure_ascii=False).encode("utf-8")
    espera = 5
    for intento in range(1, reintentos + 1):
        req = urllib.request.Request(url, data=datos, method="POST",
                                     headers={"Content-Type": "application/json", "X-Job-Token": token})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", "replace")[:500]
            if e.code < 500 and e.code != 429:
                raise ErrorEnvio(f"{url}: HTTP {e.code} {detalle}") from e
            motivo = f"HTTP {e.code} {detalle}"
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            motivo = str(getattr(e, "reason", e))
        if intento == reintentos:
            raise ErrorEnvio(f"{url}: {motivo} (después de {reintentos} intentos)")
        log.warning("Intento %d/%d falló (%s); reintento en %ds", intento, reintentos, motivo, espera)
        time.sleep(espera)
        espera = min(espera * 2, 300)
    raise ErrorEnvio(url)


def sumar(total: dict, resp: dict) -> dict:
    """Acumula los conteos que devuelve la API lote a lote (números y dicts de números)."""
    for k, v in resp.items():
        if isinstance(v, bool) or k == "lote_id":
            continue
        if isinstance(v, (int, float)):
            total[k] = total.get(k, 0) + v
        elif isinstance(v, dict):
            sumar(total.setdefault(k, {}), v)
    return total


# ─── Ejecución ───

def ejecutar(args, cfg: dict, leer=leer_cdr, post=post_json) -> int:
    ruta_estado = Path(args.estado)
    estado = leer_estado(ruta_estado)
    hasta = _fecha(args.hasta) if args.hasta else None
    if args.desde:
        desde = _fecha(args.desde)
    elif estado.get("ultima_calldate"):
        desde = _fecha(estado["ultima_calldate"])
    else:
        desde = dt.datetime.combine(dt.date.today() - dt.timedelta(days=args.dias), dt.time())
        log.info("Primera corrida sin estado: se toman los últimos %d días", args.dias)
    log.info("Leyendo CDR desde %s%s", desde, f" hasta {hasta}" if hasta else "")
    filas = leer(cfg, desde, hasta)
    leidas = len(filas)
    if not args.desde:
        filas = [f for f in filas if not ya_enviada(f, estado)]
    filas = deduplicar(filas)
    llamadas = [fila_a_llamada(f, cfg["tz"]) for f in filas]
    log.info("Leídas %d filas; %d llamadas a enviar", leidas, len(llamadas))

    if args.dry_run:
        salida = Path(args.salida or AQUI / f"cdr_payload_{dt.datetime.now():%Y%m%d_%H%M%S}.json")
        salida.write_text(json.dumps({"origen": cfg["origen"], "llamadas": llamadas}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        log.info("Dry-run: payload en %s (no se envió ni se movió el estado)", salida)
        return 0
    if not cfg["api_url"] or not cfg["token"]:
        log.error("Faltan API_URL o JOB_TOKEN (ver cdr_job.env)")
        return 2

    total: dict = {}
    url = f"{cfg['api_url']}/api/intentos/lote"
    try:
        for n, (lote_f, lote_ll) in enumerate(zip(lotes(filas, cfg["lote"]), lotes(llamadas, cfg["lote"])), 1):
            resp = post(url, {"origen": cfg["origen"], "llamadas": lote_ll}, cfg["token"], cfg["timeout"], cfg["reintentos"])
            sumar(total, resp)
            log.info("Lote %d (%d llamadas): %s", n, len(lote_ll), json.dumps(resp, ensure_ascii=False))
            if not args.no_estado:
                nuevo = avanzar(estado, lote_f)
                if nuevo is not estado:
                    guardar_estado(ruta_estado, nuevo)
                    estado = nuevo
    except ErrorEnvio as e:
        log.error("No se pudo enviar el lote: %s. El estado quedó en %s", e, estado.get("ultima_calldate"))
        return 1
    print(json.dumps({"llamadas_enviadas": len(llamadas), **total}, ensure_ascii=False))

    if args.exportar_auditoria:
        try:
            resp = post(f"{cfg['api_url']}/api/jobs/auditoria-bq", {}, cfg["token"], cfg["timeout"], cfg["reintentos"])
            log.info("Export de auditoría a BigQuery: %s", json.dumps(resp, ensure_ascii=False))
        except ErrorEnvio as e:
            log.error("Falló el export de auditoría: %s", e)
            return 3
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--desde", help="Fecha u hora inicial (AAAA-MM-DD[ HH:MM:SS]); ignora el estado para leer")
    p.add_argument("--hasta", help="Fecha u hora final, exclusiva (re-proceso de un período)")
    p.add_argument("--dias", type=int, default=1, help="Primera corrida sin estado ni --desde: días hacia atrás")
    p.add_argument("--dry-run", action="store_true", help="Escribe el payload en un archivo y no envía")
    p.add_argument("--salida", help="Archivo del payload en --dry-run")
    p.add_argument("--exportar-auditoria", action="store_true", help="Después, POST /api/jobs/auditoria-bq")
    p.add_argument("--no-estado", action="store_true", help="No actualizar estado.json")
    p.add_argument("--env", default=str(AQUI / "cdr_job.env"), help="Archivo de variables de entorno")
    p.add_argument("--estado", default=str(AQUI / "estado.json"), help="Archivo de estado incremental")
    return p


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    args = parser().parse_args(argv)
    cargar_env(Path(args.env))
    try:
        return ejecutar(args, config())
    except Exception:
        log.exception("Error inesperado en el job del CDR")
        return 1


if __name__ == "__main__":
    sys.exit(main())
