"""Conteo de llamadas del CDR, rendimiento por origen sin depender de muestras y lista de empresas
llamadas (SPEC_conteo_llamadas_cdr_y_rendimiento_por_origen, R1–R4)."""
import csv
import io

from app import telefonos as telmod
from conftest import cargar, rut_valido
from test_cdr_job import activo, correr, fila, sec, ultima_corrida  # noqa: F401 (fixtures)
from test_muestra import estudio, muestra

JOB = {"X-Job-Token": "token-job"}


def base(api, n=6, origen="sin_dato", tipo_fuente=None, desde=0):
    """Empresas i con teléfono 2900000i."""
    return cargar(api, [{"RUT": rut_valido(i), "Razón social": f"Empresa {i}", "Teléfono": f"2900{i:04d}",
                         "Departamento": "Montevideo"} for i in range(desde, desde + n)],
                  origen_defecto=origen, tipo_fuente=tipo_fuente)


def cdr_de_ejemplo():
    """Un CDR como el del dashboard de productividad: tramos repetidos, un interno, una llamada sin
    campaña y un número que no está en la base."""
    return [
        fila("1", "2026-10-28 10:00:00", dst="29000000", billsec=0),
        fila("1", "2026-10-28 10:00:05", dst="29000000", billsec=40),        # mismo uniqueid: 3 tramos
        fila("1", "2026-10-28 10:00:09", dst="29000000", billsec=10),
        fila("2", "2026-10-28 10:01:00", dst="4501"),                        # anexo interno
        fila("3", "2026-10-28 10:02:00", dst="29000001", accountcode=""),    # sin campaña
        fila("4", "2026-10-28 10:03:00", dst="098765432"),                   # no está en la base
        fila("5", "2026-10-28 10:04:00", dst="29000002", billsec=0, disposition="NO ANSWER"),
        fila("6", "2026-10-28 10:05:00", dst="29000000"),                    # otra llamada a la empresa 0
    ]


def llamadas_del_dashboard(filas, internos):
    """Criterio del dashboard de productividad: una llamada por uniqueid con destino externo, sin filtro de campaña."""
    return len({f["uniqueid"] for f in filas if not telmod.es_interno(f["dst"], internos)})


# ─── R1 · Llamadas con los criterios del dashboard ───

def test_llamadas_como_el_dashboard(api, sql, activo):  # noqa: F811
    base(api)
    filas = cdr_de_ejemplo()
    assert correr(leer=lambda p, c, d, h: filas) == 0
    k = ultima_corrida(sql)["conteos"]
    internos = api.get("/config").json()["parametros"]["destinos_internos"]
    assert k["llamadas"] == llamadas_del_dashboard(filas, internos) == 5      # 1, 3, 4, 5 y 6
    assert k["filas_leidas"] == 8 and k["internas"] == 1 and k["no_cruzan"] == 1
    # R2: llamadas a empresas, teléfonos y empresas distintas, y el embudo
    assert (k["llamadas_a_empresas"], k["telefonos_marcados"], k["empresas_llamadas"]) == (4, 3, 3)
    assert (k["nuevas"], k["ya_registradas"]) == (4, 0)
    assert k["asociadas_a_muestra"] + k["en_conciliacion"] + k["sin_muestra"] == k["llamadas_a_empresas"]
    assert k["sin_muestra"] == 4 and k["conteo_version"] == 2


def test_filas_releidas_no_cuentan_dos_veces(api, sql, activo):  # noqa: F811
    base(api)
    sql.execute("INSERT INTO cdr_estado (id, ultima_calldate, uniqueids) VALUES (1, '2026-10-28 10:00:00', '{1}')")
    filas = [fila("1", "2026-10-28 10:00:00", dst="29000000"),       # ya procesada en la corrida anterior
             fila("7", "2026-10-28 10:00:00", dst="29000001"), fila("8", "2026-10-28 11:00:00", dst="29000002")]
    assert correr(leer=lambda p, c, d, h: filas) == 0
    k = ultima_corrida(sql)["conteos"]
    assert (k["filas_leidas"], k["llamadas"], k["llamadas_a_empresas"]) == (3, 2, 2)


def test_reproceso_repite_llamadas_a_empresas(api, sql, activo):  # noqa: F811
    base(api)
    filas = cdr_de_ejemplo()
    correr(leer=lambda p, c, d, h: filas)
    assert correr("--desde", "2026-10-28", "--hasta", "2026-10-29", leer=lambda p, c, d, h: filas) == 0
    k = ultima_corrida(sql)["conteos"]
    assert (k["llamadas"], k["llamadas_a_empresas"], k["nuevas"], k["ya_registradas"]) == (5, 4, 0, 4)


def test_embudo_con_muestra_y_conciliacion(api, sql, activo):  # noqa: F811
    base(api, n=3)
    # la empresa 1 comparte el número de la empresa 2: una llamada a ese número va a Conciliación
    cargar(api, [{"RUT": rut_valido(1), "Teléfono": "29000002"}], tipo_fuente="compartido")
    e = estudio(api)
    muestra(api, e, {"n_por_estrato": 3})
    filas = [fila("1", "2026-10-28 10:00:00", dst="29000000"),             # en campo: se asocia al ítem
             fila("2", "2026-09-01 10:00:00", dst="29000001"),             # antes del campo: sin ítem
             fila("3", "2026-10-28 11:00:00", dst="29000002")]             # dos ítems posibles: Conciliación
    assert correr("--desde", "2026-09-01", leer=lambda p, c, d, h: filas) == 0
    k = ultima_corrida(sql)["conteos"]
    assert (k["asociadas_a_muestra"], k["en_conciliacion"], k["sin_muestra"]) == (1, 1, 1)
    assert k["asociadas_a_muestra"] + k["en_conciliacion"] + k["sin_muestra"] == k["llamadas_a_empresas"] == 3


# ─── R3 · Rendimiento por origen con todas las llamadas a empresas ───

def lote(api, llamadas):
    r = api.c.post("/api/intentos/lote", headers=JOB, json={"origen": "test", "llamadas": llamadas})
    assert r.status_code == 200, r.text
    return r.json()


def llamada(n, destino, inicio="2026-10-26T11:00:00-03:00", duracion=30, **kw):
    return {"cdr_id": str(n), "inicio": inicio, "destino": destino, "duracion": duracion, **kw}


def test_rendimiento_cuenta_llamadas_sin_muestra(api, sql, activo):  # noqa: F811
    base(api)
    filas = cdr_de_ejemplo()
    correr(leer=lambda p, c, d, h: filas)
    k = ultima_corrida(sql)["conteos"]
    r = api.get("/actividad/origenes", rol="jefe", params={"desde": "2026-10-28", "hasta": "2026-10-28"}).json()
    t = r["total"]
    assert t["llamadas"] == k["llamadas_a_empresas"] == 4                       # ninguna está en una muestra
    assert (t["telefonos_llamados"], t["empresas_llamadas"]) == (3, 3)
    tablero = api.get("/actividad", rol="jefe", params={"desde": "2026-10-28", "hasta": "2026-10-28"}).json()
    assert t["llamadas"] == tablero["intentos"]
    assert {o["codigo"]: o["llamadas"] for o in r["origenes"]} == {"sin_dato": 4}


def test_filtro_por_estudio_es_por_empresa(api, sql):
    base(api, n=6)
    e = estudio(api)                                        # campo del 2026-10-01 al 2026-12-31
    mid, _ = muestra(api, e, {"n_por_estrato": 3}, semilla=1)
    en_muestra = [r["rut"] for r in sql.execute(
        "SELECT e.rut FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id WHERE i.muestra_id = %s ORDER BY e.rut", (mid,))]
    fuera = [rut_valido(i) for i in range(6) if rut_valido(i) not in en_muestra]
    tel = {rut_valido(i): f"2900{i:04d}" for i in range(6)}
    lote(api, [llamada(1, tel[en_muestra[0]], inicio="2026-09-15T11:00:00-03:00"),     # antes del campo: sin ítem
               llamada(2, tel[en_muestra[1]]),                                         # en campo: con ítem
               llamada(3, tel[fuera[0]])])                                             # empresa fuera de la muestra
    assert sql.execute("SELECT count(*) AS n FROM intento WHERE item_id IS NULL").fetchone()["n"] == 2
    r = api.get("/actividad/origenes", rol="jefe", params={"estudio_id": e["id"]}).json()
    assert r["total"]["llamadas"] == 2 and r["total"]["empresas_llamadas"] == 2
    assert api.get("/actividad", rol="jefe", params={"estudio_id": e["id"]}).json()["intentos"] == 2
    assert api.get("/actividad/origenes", rol="jefe", params={"muestra_id": mid}).json()["total"]["llamadas"] == 2
    assert api.get("/actividad/origenes", rol="jefe").json()["total"]["llamadas"] == 3


# ─── R4 · Lista de empresas llamadas y CSV ───

def leer_csv(r):
    return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))


def test_exportar_empresas_de_una_corrida(api, sql, activo):  # noqa: F811
    base(api)
    filas = cdr_de_ejemplo()
    correr(leer=lambda p, c, d, h: filas)
    c = ultima_corrida(sql)
    r = api.get("/actividad/empresas-llamadas", rol="coordinador", params={"corrida_id": c["id"]}).json()
    assert r["total"] == c["conteos"]["empresas_llamadas"] == 3
    assert r["llamadas"] == c["conteos"]["llamadas_a_empresas"] == 4               # 4 llamadas a 3 empresas
    e0 = next(x for x in r["empresas"] if x["rut"] == rut_valido(0))
    assert (e0["llamadas"], e0["atendidas"]) == (2, 2)
    assert e0["telefonos"] == [{"numero": "+59829000000", "origenes": ["Sin dato"]}] and e0["muestras"] is None
    e2 = next(x for x in r["empresas"] if x["rut"] == rut_valido(2))
    assert e2["atendidas"] == 0                                                     # NO ANSWER (D35)
    # CSV con BOM, separador ; y tildes
    resp = api.get("/actividad/empresas-llamadas", rol="coordinador", params={"corrida_id": c["id"], "formato": "csv"})
    assert resp.status_code == 200 and resp.content.startswith(b"\xef\xbb\xbf")
    filas_csv = leer_csv(resp)
    assert len(filas_csv) == 3 and sum(int(f["Llamadas"]) for f in filas_csv) == 4
    assert set(filas_csv[0]) >= {"RUT", "Razón social", "Teléfonos llamados", "Estudio / muestra", "Estado del ítem"}
    assert filas_csv[0]["Estudio / muestra"] == "sin muestra"
    a = sql.execute("SELECT * FROM auditoria WHERE accion = 'actividad.exportar_empresas'").fetchone()
    assert a["actor"] == "coord@equipos.com.uy" and a["detalle"]["filas"] == 3
    assert a["detalle"]["filtros"] == {"corrida_id": c["id"]}
    # un reproceso exporta las mismas empresas aunque los intentos ya estuvieran registrados
    correr("--desde", "2026-10-28", "--hasta", "2026-10-29", leer=lambda p, c, d, h: filas)
    c2 = ultima_corrida(sql)
    assert api.get("/actividad/empresas-llamadas", params={"corrida_id": c2["id"]}).json()["total"] == 3


def test_lista_por_origen_y_permisos(api, sql):
    api.post("/origenes-telefono", json={"codigo": "guia", "nombre": "Guía telefónica"})
    base(api, n=2, origen="guia", tipo_fuente="a")                     # empresas 0 y 1, origen guía
    base(api, n=2, origen="sin_dato", tipo_fuente="b", desde=2)        # empresas 2 y 3
    lote(api, [llamada(i, f"2900{i:04d}") for i in range(4)] + [llamada(9, "29000000", inicio="2026-10-27T11:00:00-03:00")])
    r = api.get("/actividad/empresas-llamadas", rol="jefe", params={"origen": "guia"}).json()
    assert sorted(x["rut"] for x in r["empresas"]) == [rut_valido(0), rut_valido(1)] and r["llamadas"] == 3
    ori = {o["codigo"]: o for o in api.get("/actividad/origenes", rol="jefe").json()["origenes"]}
    assert (ori["guia"]["llamadas"], ori["guia"]["empresas_llamadas"]) == (3, 2) == (r["llamadas"], r["total"])
    assert api.get("/actividad/empresas-llamadas", rol="lectura").status_code == 403
    assert api.get("/actividad/empresas-llamadas", rol="steward").status_code == 403


def test_lista_solo_sin_muestra(api, sql):
    base(api, n=4)
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 2}, semilla=3)
    lote(api, [llamada(i, f"2900{i:04d}") for i in range(4)])
    todas = api.get("/actividad/empresas-llamadas").json()
    sin = api.get("/actividad/empresas-llamadas", params={"solo_sin_muestra": True}).json()
    assert todas["total"] == 4 and sin["total"] == 2
    con = [x for x in todas["empresas"] if x["muestras"]]
    assert len(con) == 2 and con[0]["muestras"][0]["muestra"] == "Muestra 1"
    # con filtro de estudio solo aparecen las empresas de sus muestras
    assert api.get("/actividad/empresas-llamadas", params={"estudio_id": e["id"]}).json()["total"] == 2


def test_llamada_a_numero_compartido_cuenta_una_vez_en_el_total(api, sql):
    base(api, n=2)
    cargar(api, [{"RUT": rut_valido(1), "Teléfono": "29000000"}], tipo_fuente="compartido")   # 0 y 1 comparten número
    lote(api, [llamada(1, "29000000")])
    r = api.get("/actividad/empresas-llamadas").json()
    assert r["total"] == 2 and r["llamadas"] == 1 and [x["llamadas"] for x in r["empresas"]] == [1, 1]
    assert api.get("/actividad/origenes").json()["total"]["llamadas"] == 1
