"""SPEC_rut_sin_control_de_largo (D54): identificadores de 6 a 11 dígitos aceptados como «RUT no verificado»."""
from conftest import cargar, rut_valido
from test_campo import hacer_sav, ingerir
from test_muestra import estudio, leer_csv, muestra
from app import rut as rutmod


def fila(rut, i=0, **extra):
    return {"RUT": rut, "Razón social": f"Mypes {i}", "Teléfono": f"2900{i:04d}", "Departamento": "Salto",
            "Tamaño": "Pyme", "Naturaleza": "SA", "CIIU": "4711", **extra}


# ─── R1 · Validación en dos niveles ───

def test_validar_dos_niveles():
    v = lambda x, c=True: rutmod.validar(x, cortos=c)  # noqa: E731
    assert v("1234567") == ("1234567", None) and v("12.345.678") == ("12345678", None)
    assert v("UY 123456") == ("123456", None) and v(1234567.0) == ("1234567", None)
    assert v("00123456") == ("00123456", None)                     # 6 a 10 dígitos: sin agregar ceros
    assert v(rut_valido(0)) == (rut_valido(0), None)                # 12 dígitos: se valida como siempre
    assert v(rut_valido(0)[:11] + str((int(rut_valido(0)[11]) + 1) % 10))[1] == "dígito verificador incorrecto"
    r01 = rutmod.con_verificador("01123456001")                     # un RUT del registro 01 sin su 0 de adelante
    assert v(r01[1:]) == (r01, None)                                 # 11 que repone el 0 y da un RUT válido
    assert v("21100000001") == ("21100000001", None)                 # 11 que no da un RUT válido: no verificado
    for malo in ("", "12345", "12a4567", "1234567890123"):
        assert v(malo)[0] is None
    assert v("1234567", c=False) == (None, "RUT con 7 dígitos (se esperan 12)")
    assert rutmod.verificado("1234567") is False and rutmod.verificado(rut_valido(0)) is True
    assert rutmod.formatear("1234567") == "1234567"


# ─── Carga ───

def test_carga_da_de_alta_los_de_7_y_8_digitos(api, sql):
    filas = [fila("1234567", 1), fila("12.345.678", 2), fila(rut_valido(3), 3),
             fila(rut_valido(4)[:11] + "0" if rut_valido(4)[11] != "0" else rut_valido(4)[:11] + "1", 4),  # DV incorrecto
             fila("12a4567", 5), fila("", 6), fila("1234567890123", 7), fila("87654321", 8), fila("87.654.321", 9)]
    c = cargar(api, filas)
    k = c["conteos"]
    assert k["altas"] == 4 and k["actualizaciones"] == 1 and k["rechazos"] == 4      # el 8 dígitos repetido, una actualización
    assert set(k["rechazos_por_motivo"]) == {"dígito verificador incorrecto", "RUT con caracteres no numéricos", "sin RUT",
                                             "RUT con 13 dígitos (se esperan 12)"}
    emp = {r["rut"]: r for r in sql.execute("SELECT rut, base, rut_verificado, codigo FROM empresa")}
    assert emp["1234567"] == {"rut": "1234567", "base": "definitiva", "rut_verificado": False, "codigo": "1234567"}
    assert emp["87654321"]["rut_verificado"] is False and emp[rut_valido(3)]["rut_verificado"] is True
    # La ficha abre por URL, con la marca
    f = api.get("/empresas/1234567").json()
    assert f["razon_social"] == "Mypes 1" and f["rut_verificado"] is False
    assert api.get("/empresas/1.234.567").status_code == 200
    # El buscador la encuentra y el filtro separa verificados de no verificados
    assert "1234567" in [e["rut"] for e in api.get("/empresas", params={"q": "1234567"}).json()["empresas"]]
    no = api.get("/empresas", params={"rut_verificado": "false"}).json()["empresas"]
    assert sorted(e["rut"] for e in no) == ["1234567", "12345678", "87654321"] and all(e["rut_verificado"] is False for e in no)
    assert {e["rut"] for e in api.get("/empresas", params={"rut_verificado": "true"}).json()["empresas"]} == {rut_valido(3)}


def test_interruptor_apagado_vuelve_a_rechazar(api, sql):
    cfg = api.get("/config").json()["parametros"]
    assert cfg["cargas"]["aceptar_rut_no_verificado"] is True
    cfg["cargas"]["aceptar_rut_no_verificado"] = False
    assert api.put("/config", json={"parametros": cfg}).status_code == 200
    c = cargar(api, [fila("1234567"), fila(rut_valido(1), 1)])
    assert c["conteos"]["altas"] == 1 and c["conteos"]["rechazos_por_motivo"] == {"RUT con 7 dígitos (se esperan 12)": 1}
    r = api.post("/empresas", rol="steward", json={"rut": "7654321", "razon_social": "X"})
    assert r.status_code == 422 and "7 dígitos" in r.json()["detail"]


def test_volver_a_cargar_el_archivo_suma_los_rechazados(api, sql):
    """R4: con la misma plantilla, las que ya entraron quedan sin cambios y las cortas entran como altas."""
    filas = [fila(rut_valido(0), 0), fila("1234567", 1)]
    cfg = api.get("/config").json()["parametros"]
    cfg["cargas"]["aceptar_rut_no_verificado"] = False
    api.put("/config", json={"parametros": cfg})
    assert cargar(api, filas)["conteos"]["rechazos"] == 1
    cfg["cargas"]["aceptar_rut_no_verificado"] = True
    api.put("/config", json={"parametros": cfg})
    k = cargar(api, filas)["conteos"]
    assert (k["altas"], k.get("sin_cambios"), k.get("rechazos", 0)) == (1, 1, 0)


# ─── Alta manual y base provisoria ───

def test_alta_manual_y_agregar_rut_a_una_provisoria(api, sql):
    r = api.post("/empresas", rol="steward", json={"rut": "765.4321", "razon_social": "Unipersonal"})
    assert r.status_code == 200, r.text
    assert sql.execute("SELECT rut_verificado FROM empresa WHERE rut = '7654321'").fetchone()["rut_verificado"] is False
    cargar(api, [{"Razón social": "Sin RUT", "Teléfono": "29001111", "Departamento": "Salto"}], destino="provisoria")
    p = sql.execute("SELECT codigo FROM empresa WHERE base = 'provisoria'").fetchone()["codigo"]
    r = api.post(f"/empresas/{p}/rut", rol="steward", json={"rut": "11223344"})
    assert r.status_code == 200, r.text
    e = sql.execute("SELECT base, rut, rut_verificado FROM empresa WHERE rut = '11223344'").fetchone()
    assert e == {"base": "definitiva", "rut": "11223344", "rut_verificado": False}


# ─── Muestra, CSV y .sav ───

def test_csv_y_sav_con_rut_no_verificado(api, sql):
    cargar(api, [fila("1234567", 1), fila("7654321", 2)])
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 5})
    parte = e["partes"][0]
    filas = leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={parte['id']}", rol="coordinador"))
    assert {f["rut"] for f in filas} == {"1234567", "7654321"}
    assert all("EC_RUT=" + f["rut"] in f["link"] for f in filas)
    # el .sav sin EC_ID_ITEM se asocia por su EC_RUT
    sav = [{"responseid": 1, "EC_RUT": "1234567", "EC_TEL_USADO": "", "EC_CALIDAD_TEL": 1, "EC_TEL_ALT": "",
            "EC_RESP_NOMBRE": "", "EC_RESP_CARGO": "", "EC_RESP_AREA": "", "EC_RESULTADO": 1, "status": "Complete",
            "datesubmitted": "2026-10-27 15:30:00"}]
    a, ing = ingerir(api, parte["id"], hacer_sav(sav))
    assert a["mapeo"]["identificador"] == {"variable": "EC_RUT", "tipo": "rut"}
    assert ing["conteos"]["asociadas"] == 1


# ─── Tablero de calidad ───

def test_calidad_cuenta_los_no_verificados_aparte(api, sql):
    cargar(api, [fila("1234567", 1), fila(rut_valido(2), 2), fila(rut_valido(3), 3)])
    ind = {i["clave"]: i for d in api.get("/calidad").json()["dimensiones"] for i in d["indicadores"]}
    assert ind["rut_valido"]["valor"] == 100.0                       # el no verificado no cuenta como incumplimiento
    assert ind["rut_no_verificado"]["valor"] == 1 and ind["rut_no_verificado"]["estado"] == "informativo"
    lista = api.get("/calidad/rut_no_verificado").json()
    assert [f["rut"] for f in lista["filas"]] == ["1234567"] and lista["filas"][0]["problema"] == "7 dígitos"


def test_dos_empresas_no_pueden_tener_el_mismo_identificador(api, sql):
    cargar(api, [fila("1234567", 1)])
    r = api.post("/empresas", rol="steward", json={"rut": "1.234.567", "razon_social": "Otra"})
    assert r.status_code == 409
