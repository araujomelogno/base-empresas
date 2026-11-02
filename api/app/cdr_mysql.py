"""Conexión a la base MySQL del CDR de uContact (SPEC_job_cdr_en_cloud, R3 y R4).

Los parámetros vienen del bloque `cdr` de la configuración y la contraseña de Secret Manager.
La base es accesible desde internet: el job corre en Google Cloud. Si el servidor filtra por IP,
"Probar conexión" lo muestra como "no responde el puerto" (ver docs/despliegue.md, IP fija).
"""
import datetime as dt
import re
import ssl

FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"
# Columnas que el job necesita (con AS si en la tabla se llaman distinto). src y accountcode son opcionales.
COLUMNAS = ("uniqueid", "calldate", "dst", "duration", "billsec", "disposition", "userfield", "peeraccount")
OPCIONALES = ("src", "accountcode", "campania")
LEJANO = dt.datetime(9999, 1, 1)


def consulta_de(p: dict) -> str:
    if p.get("consulta"):
        return p["consulta"]
    return ("SELECT uniqueid, calldate, src, dst, duration, billsec, disposition, userfield, peeraccount, accountcode"
            f" FROM {p['tabla']} WHERE calldate >= %s AND calldate < %s ORDER BY calldate, uniqueid")


def _parametros_consulta(consulta: str, desde: dt.datetime, hasta: dt.datetime | None) -> list[str]:
    params = [desde.strftime(FORMATO_FECHA)]
    if len(re.findall(r"(?<!%)%s", consulta)) >= 2:
        params.append((hasta or LEJANO).strftime(FORMATO_FECHA))
    return params


def conectar(p: dict, password: str, timeout: int = 10):
    import pymysql
    import pymysql.cursors

    opciones = {}
    if p["tls"] == "desactivado":
        opciones["ssl_disabled"] = True
    else:
        # El certificado de un MySQL propio suele ser autofirmado: se cifra sin validar la CA.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        opciones["ssl"] = ctx
    return pymysql.connect(host=p["host"], port=int(p["puerto"]), user=p["usuario"], password=password,
                           database=p["base"], charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
                           connect_timeout=timeout, read_timeout=max(timeout, 600), write_timeout=60, **opciones)


def usa_tls(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
        fila = cur.fetchone() or {}
    return bool((fila.get("Value") or "").strip())


def _verificar_tls(conn, p):
    tls = usa_tls(conn)
    if p["tls"] == "requerido" and not tls:
        raise ErrorCdr("tls", "El servidor no aceptó una conexión cifrada (TLS) y la configuración la exige")
    return tls


class ErrorCdr(Exception):
    def __init__(self, clase: str, mensaje: str):
        super().__init__(mensaje)
        self.clase = clase
        self.mensaje = mensaje


def clasificar(e: Exception, p: dict, password: str | None = None) -> ErrorCdr:
    """Traduce el error de pymysql a un motivo claro. Nunca incluye la contraseña."""
    if isinstance(e, ErrorCdr):
        return e
    codigo = e.args[0] if getattr(e, "args", None) and isinstance(e.args[0], int) else None
    texto = " ".join(str(a) for a in getattr(e, "args", ())) or str(e)
    if password:
        texto = texto.replace(password, "***")
    host = f"{p.get('host')}:{p.get('puerto')}"
    if codigo == 2003 or isinstance(e, OSError):
        if re.search(r"Name or service not known|nodename nor servname|getaddrinfo|name resolution|"
                     r"No address associated|Errno -2\]|Errno -3\]|Errno 8\]", texto, re.I):
            return ErrorCdr("host", f"No se resuelve el host {p.get('host')}: revisá el nombre del servidor")
        return ErrorCdr("puerto", f"No responde el puerto {host}. Si el servidor está prendido, lo más probable es"
                                  " que filtre por IP de origen: hace falta la IP fija (ver docs/despliegue.md)")
    if codigo == 1045:
        return ErrorCdr("credenciales", "Usuario o contraseña incorrectos")
    if codigo == 1049:
        return ErrorCdr("base", f"La base {p.get('base')} no existe en el servidor")
    if codigo == 1146:
        return ErrorCdr("tabla", "La tabla del CDR no existe: revisá la tabla o la consulta en la configuración")
    if codigo in (1044, 1142, 1143):
        return ErrorCdr("permisos", "El usuario no tiene permiso para leer la base o la tabla del CDR")
    if codigo == 3159 or "insecure transport" in texto.lower():
        return ErrorCdr("tls", "El servidor exige una conexión cifrada: poné TLS en «requerido» o «preferido»")
    if codigo in (2026,) or "ssl" in texto.lower():
        return ErrorCdr("tls", "Falló la conexión cifrada (TLS) con el servidor. Probá con TLS «desactivado» si"
                               " el servidor no lo soporta")
    if codigo == 1064:
        return ErrorCdr("consulta", "La consulta del CDR tiene un error de sintaxis")
    if codigo in (1054,):
        return ErrorCdr("consulta", "La consulta usa una columna que no existe en la tabla")
    if codigo in (2013, 2006):
        return ErrorCdr("puerto", f"Se cortó la conexión con {host} (posible firewall o tiempo de espera)")
    return ErrorCdr("otro", f"Error de MySQL{f' {codigo}' if codigo else ''}: {texto[:200]}")


def probar(p: dict, password: str) -> dict:
    """Conecta en 10 s como máximo y corre la consulta de las últimas 24 horas con LIMIT 5."""
    resultado = {"ok": False, "version": None, "tls": None, "filas": 0, "columnas": [], "faltan": []}
    conn = None
    try:
        conn = conectar(p, password, timeout=10)
        resultado["tls"] = _verificar_tls(conn, p)
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION() AS v")
            resultado["version"] = cur.fetchone()["v"]
            consulta = consulta_de(p)
            hasta = dt.datetime.now()
            desde = hasta - dt.timedelta(hours=24)
            cur.execute(f"SELECT * FROM ({consulta}) AS cdr_prueba LIMIT 5", _parametros_consulta(consulta, desde, hasta))
            filas = cur.fetchall()
            columnas = [d[0] for d in cur.description or []]
        resultado.update(filas=len(filas), columnas=columnas, faltan=[c for c in COLUMNAS if c not in columnas])
        if resultado["faltan"]:
            resultado.update(clase="columnas", mensaje=f"Faltan columnas en la consulta: {', '.join(resultado['faltan'])}"
                                                       " (usá AS si en la tabla se llaman distinto)")
        else:
            resultado.update(ok=True, mensaje=f"Conectó. {len(filas)} llamadas de las últimas 24 horas en la muestra.")
    except Exception as e:
        err = clasificar(e, p, password)
        resultado.update(clase=err.clase, mensaje=err.mensaje)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return resultado


def leer(p: dict, password: str, desde: dt.datetime, hasta: dt.datetime | None) -> list[dict]:
    """Llamadas con calldate >= desde (y < hasta), ordenadas por calldate."""
    import pymysql.cursors

    conn = conectar(p, password, timeout=30)
    filas = []
    try:
        _verificar_tls(conn, p)
        consulta = consulta_de(p)
        with conn.cursor(pymysql.cursors.SSDictCursor) as cur:
            cur.execute(consulta, _parametros_consulta(consulta, desde, hasta))
            while True:
                bloque = cur.fetchmany(5000)
                if not bloque:
                    break
                for f in bloque:
                    if hasta and _fecha(f["calldate"]) >= hasta:
                        return filas  # la consulta viene ordenada por calldate
                    filas.append(f)
    finally:
        conn.close()
    return filas


def _fecha(v) -> dt.datetime:
    if isinstance(v, dt.datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, dt.date):
        return dt.datetime.combine(v, dt.time())
    return dt.datetime.fromisoformat(str(v).strip()).replace(tzinfo=None)
