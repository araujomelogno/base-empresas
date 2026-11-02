"""Job del CDR en Google Cloud (SPEC_job_cdr_en_cloud, R8).

MySQL se simula: la lectura con una función `leer` y la conexión de "Probar conexión" con un
conectar falso. Secret Manager se reemplaza por secretos en memoria.
"""
import datetime as dt
import json
import logging
from zoneinfo import ZoneInfo

import pymysql
import pytest

from app import cdr_mysql, secretos
from app.jobs import cdr_job

TZ = ZoneInfo("America/Montevideo")
CLAVE = "clave-mysql-super-secreta"
CONEXION = {"host": "mysql.ucontact.ejemplo", "puerto": 3306, "base": "uc", "usuario": "lector", "tabla": "cdr",
            "tls": "preferido", "zona_horaria": "America/Montevideo", "lote_tamano": 2}


def fila(uid, calldate, dst="29011234", billsec=30, **extra):
    return {"uniqueid": uid, "calldate": dt.datetime.fromisoformat(calldate), "src": "201", "dst": dst,
            "duration": billsec + 10, "billsec": billsec, "disposition": "ANSWERED", "userfield": "Contesta|Completa",
            "peeraccount": "SIP/enc01", "accountcode": "EMP-2609", **extra}


@pytest.fixture
def sec(monkeypatch):
    s = secretos.SecretosMemoria()
    monkeypatch.setattr(secretos, "_proveedor", s)
    return s


@pytest.fixture
def activo(api, sec):
    """CDR configurado y activo, con la contraseña guardada."""
    p = api.get("/config").json()["parametros"]
    p["cdr"] = {**CONEXION, "activo": True}
    assert api.put("/config", json={"parametros": p}).status_code == 200
    assert api.put("/config/cdr/password", json={"password": CLAVE}).status_code == 200
    return p


def correr(*argv, leer=None):
    return cdr_job.ejecutar(cdr_job.parser().parse_args(list(argv)), leer=leer)


def ultima_corrida(sql):
    return sql.execute("SELECT * FROM cdr_corrida ORDER BY id DESC LIMIT 1").fetchone()


# ─── Lógica del job: lotes, deduplicación y avance del estado ───

def test_fila_a_llamada():
    ll = cdr_job.fila_a_llamada(fila("1730.5", "2026-10-28 10:15:00", dst=" 099123456 "), TZ)
    assert ll == {"cdr_id": "1730.5", "inicio": "2026-10-28T10:15:00-03:00", "destino": "099123456",
                  "encuestador": "SIP/enc01", "duracion": 30, "userfield": "Contesta|Completa",
                  "disposicion": "ANSWERED", "campania": "EMP-2609"}
    f = fila("2", "2026-10-28 22:00:00", accountcode="", userfield="")
    f["billsec"] = None
    ll = cdr_job.fila_a_llamada(f, TZ)
    assert ll["campania"] is None and ll["userfield"] is None and ll["duracion"] == f["duration"]


def test_lotes_y_deduplicar():
    assert [len(x) for x in cdr_job.lotes(list(range(5)), 2)] == [2, 2, 1]
    filas = [fila("1", "2026-10-28 10:00:00", billsec=0), fila("2", "2026-10-28 10:00:01"),
             fila("1", "2026-10-28 10:00:02", billsec=50)]
    d = cdr_job.deduplicar(filas)
    assert [f["uniqueid"] for f in d] == ["1", "2"] and d[0]["billsec"] == 50


def test_mismo_segundo_entre_lotes_acumula_uniqueids():
    e = cdr_job.avanzar({}, [fila("a", "2026-10-28 10:00:05")])
    e = cdr_job.avanzar(e, [fila("b", "2026-10-28 10:00:05")])
    assert e["uniqueids_en_ultima"] == ["a", "b"]
    assert cdr_job.ya_enviada(fila("a", "2026-10-28 10:00:05"), e)
    assert not cdr_job.ya_enviada(fila("c", "2026-10-28 10:00:05"), e)


# ─── Corridas con estado en Postgres ───

def test_procesa_en_lotes_y_avanza_el_estado(api, sql, activo):
    filas = [fila(str(i), f"2026-10-28 10:00:0{i}") for i in range(5)]
    assert correr(leer=lambda p, c, d, h: filas) == 0
    c = ultima_corrida(sql)
    assert (c["estado"], c["origen"]) == ("ok", "programada")
    assert c["conteos"]["filas_leidas"] == 5 and c["conteos"]["recibidas"] == 5
    assert sql.execute("SELECT count(*) AS n FROM cdr_lote WHERE corrida_id = %s", (c["id"],)).fetchone()["n"] == 3
    e = sql.execute("SELECT * FROM cdr_estado").fetchone()
    assert e["ultima_calldate"] == dt.datetime(2026, 10, 28, 10, 0, 4) and e["uniqueids"] == ["4"]
    assert c["leido_desde"] == dt.datetime(2026, 10, 28, 10, 0, 0)


def test_el_estado_solo_avanza_con_lotes_procesados(api, sql, activo, monkeypatch):
    filas = [fila(str(i), f"2026-10-28 10:00:0{i}") for i in range(5)]
    original = cdr_job.cdr.procesar_lote
    llamadas = []

    def procesar(conn, ll, origen, actor):
        llamadas.append(1)
        if len(llamadas) == 2:
            raise RuntimeError("se cayó la base")
        return original(conn, ll, origen, actor)

    monkeypatch.setattr(cdr_job.cdr, "procesar_lote", procesar)
    assert correr(leer=lambda p, c, d, h: filas) == 1
    assert sql.execute("SELECT ultima_calldate FROM cdr_estado").fetchone()["ultima_calldate"] == dt.datetime(2026, 10, 28, 10, 0, 1)
    c = ultima_corrida(sql)
    assert c["estado"] == "error" and "se cayó la base" in c["mensaje"]


def test_incremental_desde_el_estado(api, sql, activo):
    sql.execute("INSERT INTO cdr_estado (id, ultima_calldate, uniqueids) VALUES (1, '2026-10-28 10:00:05', '{a,b}')")
    pedidos = []

    def leer(p, clave, desde, hasta):
        pedidos.append((desde, hasta, clave))
        return [fila("a", "2026-10-28 10:00:05"), fila("b", "2026-10-28 10:00:05"), fila("c", "2026-10-28 10:00:05"),
                fila("d", "2026-10-28 11:00:00")]

    assert correr(leer=leer) == 0
    assert pedidos == [(dt.datetime(2026, 10, 28, 10, 0, 5), None, CLAVE)]
    assert ultima_corrida(sql)["conteos"]["llamadas"] == 2  # c y d
    e = sql.execute("SELECT * FROM cdr_estado").fetchone()
    assert e["ultima_calldate"] == dt.datetime(2026, 10, 28, 11, 0, 0) and e["uniqueids"] == ["d"]


def test_reproceso_no_retrocede_el_estado(api, sql, activo):
    sql.execute("INSERT INTO cdr_estado (id, ultima_calldate, uniqueids) VALUES (1, '2026-10-28 23:00:00', '{z}')")
    pedidos = []

    def leer(p, clave, desde, hasta):
        pedidos.append((desde, hasta))
        return [fila("x", "2026-10-01 10:00:00")]

    assert correr("--desde", "2026-10-01", "--hasta", "2026-10-02", leer=leer) == 0
    assert pedidos == [(dt.datetime(2026, 10, 1), dt.datetime(2026, 10, 2))]
    assert sql.execute("SELECT ultima_calldate FROM cdr_estado").fetchone()["ultima_calldate"] == dt.datetime(2026, 10, 28, 23)
    c = ultima_corrida(sql)
    assert c["pedido_desde"] == dt.date(2026, 10, 1) and c["conteos"]["recibidas"] == 1


def test_dry_run_no_escribe_intentos(api, sql, activo):
    sql.execute("INSERT INTO empresa (rut) VALUES ('211000000017') ")
    assert correr("--dry-run", leer=lambda p, c, d, h: [fila("1", "2026-10-28 10:00:00")]) == 0
    c = ultima_corrida(sql)
    assert c["estado"] == "ok" and c["dry_run"] and "Dry-run" in c["mensaje"]
    assert c["conteos"]["recibidas"] == 1
    assert sql.execute("SELECT count(*) AS n FROM cdr_lote").fetchone()["n"] == 0
    assert sql.execute("SELECT count(*) AS n FROM cdr_estado").fetchone()["n"] == 0
    ruta = c["mensaje"].split("Payload en ")[1]
    assert json.loads(open(ruta).read())["llamadas"][0]["cdr_id"] == "1"


def test_inactivo_queda_omitida(api, sql, sec):
    assert correr(leer=lambda *a: pytest.fail("no tenía que leer")) == 0
    c = ultima_corrida(sql)
    assert c["estado"] == "omitida" and "no está activo" in c["mensaje"]


def test_sin_contrasena_queda_omitida(api, sql, sec):
    p = api.get("/config").json()["parametros"]
    p["cdr"] = {**CONEXION, "activo": True}
    api.put("/config", json={"parametros": p})
    assert correr(leer=lambda *a: pytest.fail("no tenía que leer")) == 0
    assert "contraseña" in ultima_corrida(sql)["mensaje"]


def test_error_de_conexion_queda_en_la_corrida_sin_la_clave(api, sql, activo, caplog):
    caplog.set_level(logging.DEBUG)

    def leer(p, clave, desde, hasta):
        raise pymysql.err.OperationalError(1045, f"Access denied for user 'lector' (using password: {clave})")

    assert correr(leer=leer) == 1
    c = ultima_corrida(sql)
    assert c["estado"] == "error" and c["mensaje"] == "Usuario o contraseña incorrectos"
    assert CLAVE not in caplog.text


# ─── Correr ahora (R6) ───

def test_correr_ahora_y_reprocesar_desde_la_api(api, sql, activo, monkeypatch):
    monkeypatch.setattr(cdr_mysql, "leer", lambda p, c, d, h: [fila("1", "2026-10-28 10:00:00")])
    r = api.post("/config/cdr/correr", json={})
    assert r.status_code == 200, r.text
    c = api.get(f"/cdr/corridas/{r.json()['corrida_id']}").json()
    assert (c["estado"], c["origen"], c["solicitada_por"]) == ("ok", "manual", "admin@equipos.com.uy")
    r = api.post("/config/cdr/correr", json={"desde": "2026-10-01", "hasta": "2026-10-02"})
    c = api.get(f"/cdr/corridas/{r.json()['corrida_id']}").json()
    assert c["pedido_desde"] == "2026-10-01" and c["estado"] == "ok"
    assert len(api.get("/cdr/corridas").json()) == 2
    assert api.post("/config/cdr/correr", json={"hasta": "2026-10-02"}).status_code == 422


def test_no_se_lanza_con_otra_en_curso(api, sql, activo):
    sql.execute("INSERT INTO cdr_corrida (origen, estado) VALUES ('programada', 'en_curso')")
    r = api.post("/config/cdr/correr", json={})
    assert r.status_code == 409 and "en curso" in r.json()["detail"]
    # una corrida colgada hace más de 2 horas se da por interrumpida
    sql.execute("UPDATE cdr_corrida SET inicio = now() - interval '3 hours'")
    assert api.post("/config/cdr/correr", json={}).status_code == 200
    assert sql.execute("SELECT estado FROM cdr_corrida WHERE id = 1").fetchone()["estado"] == "error"


def test_aviso_en_inicio(api, sql, activo):
    assert "No hubo ninguna corrida" in api.get("/inicio").json()["cdr"]["aviso"]
    sql.execute("INSERT INTO cdr_corrida (origen, estado, mensaje, fin) VALUES ('programada', 'error', 'No responde el puerto', now())")
    r = api.get("/inicio").json()["cdr"]
    assert "falló: No responde el puerto" in r["aviso"] and r["ultima"]["estado"] == "error"
    sql.execute("INSERT INTO cdr_corrida (origen, estado, fin) VALUES ('programada', 'ok', now())")
    assert api.get("/inicio").json()["cdr"]["aviso"] is None


# ─── Configuración y contraseña (R1, R2) ───

def test_config_valida_la_consulta(api, sec):
    p = api.get("/config").json()["parametros"]
    assert p["cdr"]["puerto"] == 3306 and p["cdr"]["activo"] is False  # valores por defecto
    for consulta, error in [("DELETE FROM cdr WHERE calldate >= %s", "SELECT"),
                            ("SELECT * FROM cdr WHERE calldate >= %s; DROP TABLE cdr", "sola sentencia"),
                            ("SELECT * FROM cdr", "%s")]:
        p["cdr"] = {**CONEXION, "consulta": consulta}
        r = api.put("/config", json={"parametros": p})
        assert r.status_code == 422 and error in r.json()["detail"]
    p["cdr"] = {**CONEXION, "host": "", "activo": True}
    assert "faltan: host" in api.put("/config", json={"parametros": p}).json()["detail"]


def test_la_contrasena_nunca_se_devuelve(api, sql, sec, caplog):
    caplog.set_level(logging.DEBUG)
    assert api.get("/config").json()["cdr_password"]["configurada"] is False
    r = api.put("/config/cdr/password", json={"password": CLAVE})
    assert r.status_code == 200 and CLAVE not in r.text and r.json()["configurada"] is True
    assert sec.leer("empresas-cdr-mysql-password") == CLAVE
    cfg = api.get("/config")
    assert CLAVE not in cfg.text and cfg.json()["cdr_password"]["por"] == "admin@equipos.com.uy"
    assert CLAVE not in json.dumps(sql.execute("SELECT * FROM auditoria").fetchall(), default=str)
    assert CLAVE not in json.dumps(sql.execute("SELECT parametros FROM config_version").fetchall(), default=str)
    assert CLAVE not in caplog.text
    assert "cdr_password" not in api.get("/config", rol="coordinador").json()


def test_solo_administradores(api, sec):
    for rol in ("steward", "jefe", "coordinador", "lectura"):
        assert api.put("/config/cdr/password", rol=rol, json={"password": "x"}).status_code == 403
        assert api.post("/config/cdr/probar", rol=rol, json={}).status_code == 403
        assert api.post("/config/cdr/correr", rol=rol, json={}).status_code == 403
    assert api.get("/cdr/corridas", rol="coordinador").status_code == 200


# ─── Probar conexión (R3) ───

class ConexionFalsa:
    def __init__(self, filas, columnas, ssl=True):
        self.filas, self.columnas, self.ssl = filas, columnas, ssl
        self.consultas = []

    def cursor(self, *a):
        return CursorFalso(self)

    def close(self):
        pass


class CursorFalso:
    def __init__(self, c):
        self.c = c
        self.description = None
        self.resultado = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, q, params=None):
        self.c.consultas.append((q, params))
        if "Ssl_cipher" in q:
            self.resultado = [{"Variable_name": "Ssl_cipher", "Value": "TLS_AES_256_GCM_SHA384" if self.c.ssl else ""}]
        elif "VERSION()" in q:
            self.resultado = [{"v": "8.0.36"}]
        else:
            self.resultado = self.c.filas
            self.description = [(col,) for col in self.c.columnas]

    def fetchone(self):
        return self.resultado[0] if self.resultado else None

    def fetchall(self):
        return self.resultado


def test_probar_conexion_ok(api, sec, monkeypatch):
    con = ConexionFalsa([fila("1", "2026-10-28 10:00:00")], list(fila("1", "2026-10-28 10:00:00")))
    monkeypatch.setattr(cdr_mysql, "conectar", lambda p, clave, timeout=10: con)
    r = api.post("/config/cdr/probar", json={"parametros": CONEXION, "password": CLAVE}).json()
    assert r["ok"] is True and r["version"] == "8.0.36" and r["tls"] is True and r["filas"] == 1 and r["faltan"] == []
    q, params = con.consultas[-1]
    assert "LIMIT 5" in q and len(params) == 2


def test_probar_conexion_columnas_faltantes_y_tls_requerido(api, sec, monkeypatch):
    con = ConexionFalsa([], ["uniqueid", "calldate", "dst"], ssl=False)
    monkeypatch.setattr(cdr_mysql, "conectar", lambda p, clave, timeout=10: con)
    r = api.post("/config/cdr/probar", json={"parametros": CONEXION, "password": CLAVE}).json()
    assert r["ok"] is False and r["clase"] == "columnas" and "billsec" in r["faltan"]
    r = api.post("/config/cdr/probar", json={"parametros": {**CONEXION, "tls": "requerido"}, "password": CLAVE}).json()
    assert r["clase"] == "tls"


@pytest.mark.parametrize("error,clase,texto", [
    (pymysql.err.OperationalError(2003, "Can't connect to MySQL server on 'x' ([Errno -2] Name or service not known)"),
     "host", "No se resuelve el host"),
    (pymysql.err.OperationalError(2003, "Can't connect to MySQL server on 'x' (timed out)"), "puerto", "No responde el puerto"),
    (pymysql.err.OperationalError(1045, f"Access denied for user 'lector'@'1.2.3.4' (using password: {CLAVE})"),
     "credenciales", "Usuario o contraseña incorrectos"),
    (pymysql.err.OperationalError(1049, "Unknown database 'uc'"), "base", "no existe"),
    (pymysql.err.ProgrammingError(1146, "Table 'uc.cdr' doesn't exist"), "tabla", "La tabla del CDR no existe"),
    (pymysql.err.OperationalError(3159, "Connections using insecure transport are prohibited"), "tls", "exige"),
])
def test_probar_conexion_clasifica_errores(api, sec, monkeypatch, caplog, error, clase, texto):
    caplog.set_level(logging.DEBUG)

    def conectar(p, clave, timeout=10):
        raise error

    monkeypatch.setattr(cdr_mysql, "conectar", conectar)
    r = api.post("/config/cdr/probar", json={"parametros": CONEXION, "password": CLAVE})
    assert r.status_code == 200
    assert r.json()["ok"] is False and r.json()["clase"] == clase and texto in r.json()["mensaje"]
    assert CLAVE not in r.text and CLAVE not in caplog.text


def test_probar_usa_la_contrasena_guardada(api, sec, monkeypatch):
    usadas = []

    def conectar(p, clave, timeout=10):
        usadas.append(clave)
        raise pymysql.err.OperationalError(1045, "Access denied")

    monkeypatch.setattr(cdr_mysql, "conectar", conectar)
    assert api.post("/config/cdr/probar", json={"parametros": CONEXION}).status_code == 422  # no hay ninguna
    api.put("/config/cdr/password", json={"password": CLAVE})
    api.post("/config/cdr/probar", json={"parametros": CONEXION})
    assert usadas == [CLAVE]
