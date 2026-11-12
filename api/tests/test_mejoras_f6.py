"""SPEC_mejoras_sav_contactos_atributos_identidad — Fase 6: base provisoria y reglas de fusión en cascada (F6.1, F6.2)."""
from conftest import cargar, csv_bytes, rut_valido
from test_base import fila
from test_campo import fila_sav, hacer_sav, ingerir, lote
from test_muestra import estudio, leer_csv, muestra


def sin_rut(n, **kw):
    f = {"Razón social": f"Comercio sin RUT {n}", "Teléfono": f"2400{n:04d}", "Departamento": "Montevideo"}
    f.update(kw)
    return f


def provisorias(sql):
    return sql.execute("SELECT * FROM empresa WHERE base = 'provisoria' AND baja IS NULL ORDER BY id").fetchall()


# ─── F6.1 Base provisoria ───

def test_carga_a_la_base_provisoria(api, sql):
    cargar(api, [fila(0, **{"Razón social": "Ferretería El Tornillo SA"})])          # ya está en la definitiva
    filas = [sin_rut(i) for i in range(99)] + [sin_rut(99, **{"Razón social": "Ferretería El Tornillo S.A."})]
    c = cargar(api, filas, destino="provisoria", reglas=[{"criterio": "rut", "tipo": "exacta"},
                                                         {"criterio": "razon_social", "tipo": "exacta"}])
    k = c["conteos"]
    assert c["estado"] == "confirmada" and k["altas_provisoria"] == 99 and k.get("rechazos", 0) == 0
    assert k["fusion_por_razon_social"] == 1 and k.get("altas_definitiva", 0) == 0
    ps = provisorias(sql)
    assert len(ps) == 99 and all(p["rut"] is None and p["codigo"] == f"P-{p['id']:06d}" for p in ps)
    # la que coincidió actualizó la empresa de la definitiva en lugar de crear una provisoria
    assert sql.execute("SELECT count(*) AS n FROM empresa WHERE base = 'definitiva'").fetchone()["n"] == 1
    # la ficha se abre por el código provisorio y el buscador la encuentra
    cod = ps[0]["codigo"]
    f = api.get(f"/empresas/{cod}").json()
    assert f["base"] == "provisoria" and f["codigo"] == cod and f["razon_social"] == "Comercio sin RUT 0"
    assert [e["rut"] for e in api.get("/empresas", params={"q": cod}).json()["empresas"]] == [cod]
    assert api.get("/empresas", params={"q": "Comercio sin RUT"}).json()["total"] == 0          # por defecto, definitiva
    assert api.get("/empresas", params={"q": "Comercio sin RUT", "base": "provisoria"}).json()["total"] == 99
    assert api.get("/empresas", params={"q": "Comercio", "base": "ambas"}).json()["total"] == 99
    # Inicio: «Empresas» cuenta solo la definitiva; la provisoria tiene su contador
    i = api.get("/inicio").json()
    assert i["empresas"] == 1 and i["provisorias"] == 99


def test_fila_con_rut_va_a_la_definitiva(api, sql):
    filas = [{"RUT": "", **sin_rut(0)}, {"RUT": rut_valido(5), **sin_rut(1)}, {"RUT": "1234567", **sin_rut(2)}]
    c = cargar(api, filas, destino="provisoria")
    assert (c["conteos"]["altas_provisoria"], c["conteos"]["altas_definitiva"]) == (2, 1)
    assert sql.execute("SELECT base FROM empresa WHERE rut = %s", (rut_valido(5),)).fetchone()["base"] == "definitiva"
    # el «RUT con 7 dígitos» no se pierde: queda como id_informado
    v = sql.execute("SELECT ea.valor_texto FROM empresa_atributo ea JOIN atributo a ON a.id = ea.atributo_id"
                    " WHERE a.clave = 'id_informado'").fetchall()
    assert [x["valor_texto"] for x in v] == ["1234567"]
    # opción para dejar todo en la provisoria
    c2 = cargar(api, [{"RUT": rut_valido(6), **sin_rut(3)}], destino="provisoria", tipo_fuente="otra",
                opciones={"con_rut_a_definitiva": False})
    assert c2["conteos"]["altas_provisoria"] == 1
    assert sql.execute("SELECT base FROM empresa WHERE rut = %s", (rut_valido(6),)).fetchone()["base"] == "provisoria"


def test_carga_a_la_definitiva_rechaza_o_envia_a_provisoria(api, sql):
    filas = [fila(0), fila(1, RUT="1234567"), fila(2, RUT="")]
    c = cargar(api, filas)
    assert c["conteos"]["rechazos"] == 2 and not provisorias(sql)
    c2 = cargar(api, filas, tipo_fuente="con opcion", opciones={"sin_rut_a_provisoria": True})
    assert c2["conteos"].get("rechazos", 0) == 0 and c2["conteos"]["altas_provisoria"] == 2
    ids = sql.execute("SELECT ea.valor_texto FROM empresa_atributo ea JOIN atributo a ON a.id = ea.atributo_id"
                      " WHERE a.clave = 'id_informado'").fetchall()
    assert [x["valor_texto"] for x in ids] == ["1234567"]
    # sin columna RUT en una carga a la definitiva: no se puede
    a = api.subir("/cargas/analizar", "x.csv", csv_bytes([sin_rut(0)]), rol="steward", tipo_fuente="z").json()
    r = api.post("/cargas", rol="steward", json={"archivo_id": a["archivo_id"], "fuente": "x", "tipo_fuente": "z",
                                                 "licencia": "x", "mapeo": {**a["mapeo"], "origen_defecto": "sin_dato"}})
    assert r.status_code == 422


def test_pantalla_provisoria_agregar_rut_y_fusionar(api, sql):
    cargar(api, [fila(0, **{"Razón social": "Panadería La Espiga SRL", "Teléfono": "2900 1111"})])
    cargar(api, [sin_rut(0, **{"Razón social": "Panaderia La Espiga", "Teléfono": "2900 1111"}), sin_rut(1)],
           destino="provisoria")
    lista = api.get("/provisorias").json()
    assert lista["total"] == 2
    con = {p["razon_social"]: p for p in lista["empresas"]}
    cands = con["Panaderia La Espiga"]["candidatas"]
    assert cands and cands[0]["codigo"] == rut_valido(0) and cands[0]["criterio"] == "telefono"
    assert con["Comercio sin RUT 1"]["candidatas"] == []
    assert api.get("/inicio").json()["provisorias_con_candidatas"] == 1
    # «Es otra empresa» descarta la candidata
    p1 = con["Panaderia La Espiga"]
    assert api.post(f"/empresas/{p1['codigo']}/descartar", rol="steward", json={"candidatas": [cands[0]["id"]]}).status_code == 200
    despues = {p["razon_social"]: p for p in api.get("/provisorias").json()["empresas"]}
    assert despues["Panaderia La Espiga"]["candidatas"] == []
    assert api.get("/inicio").json()["provisorias_con_candidatas"] == 0
    # «Agregar RUT» con un RUT nuevo: pasa a la definitiva
    otra = con["Comercio sin RUT 1"]
    r = api.post(f"/empresas/{otra['codigo']}/rut", rol="steward", json={"rut": rut_valido(7)})
    assert r.status_code == 200 and r.json() == {"rut": rut_valido(7), "base": "definitiva"}
    assert api.get(f"/empresas/{rut_valido(7)}").json()["base"] == "definitiva"
    assert sql.execute("SELECT 1 FROM auditoria WHERE accion = 'empresa.promover'").fetchone()
    # con un RUT que ya existe: ofrece fusionar
    r = api.post(f"/empresas/{p1['codigo']}/rut", rol="steward", json={"rut": rut_valido(0)})
    assert r.status_code == 409 and r.json()["detail"]["existente"] == rut_valido(0)
    assert api.post(f"/empresas/{rut_valido(0)}/fusionar", rol="steward",
                    json={"rut_absorbida": p1["codigo"], "motivo": "misma empresa"}).status_code == 200
    assert api.get("/provisorias").json()["total"] == 0
    assert api.post(f"/empresas/{p1['codigo']}/rut", rol="coordinador", json={"rut": rut_valido(9)}).status_code == 403


def test_completar_rut_por_archivo(api, sql):
    cargar(api, [fila(0)])
    cargar(api, [sin_rut(0), sin_rut(1), sin_rut(2)], destino="provisoria")
    ps = provisorias(sql)
    contenido = csv_bytes([{"codigo_provisorio": ps[0]["codigo"], "rut": rut_valido(3)},
                           {"codigo_provisorio": ps[1]["codigo"], "rut": rut_valido(0)},
                           {"codigo_provisorio": "P-999999", "rut": rut_valido(4)}])
    a = api.subir("/provisorias/ruts/analizar", "ruts.csv", contenido, rol="steward")
    assert a.status_code == 200, a.text
    assert a.json()["conteos"] == {"promover": 1, "fusionar": 1, "error": 1}
    assert len(provisorias(sql)) == 3                                     # el preview no cambia nada
    r = api.post("/provisorias/ruts/aplicar", rol="steward", json={"archivo_id": a.json()["archivo_id"], "fusionar": True})
    assert r.json() == {"promovidas": 1, "fusionadas": 1, "errores": 1, "pendientes": 0}
    assert [p["codigo"] for p in provisorias(sql)] == [ps[2]["codigo"]]


def test_sorteo_con_provisorias_csv_y_sav(api, sql):
    cargar(api, [fila(i) for i in range(3)])
    cargar(api, [sin_rut(i) for i in range(3)], destino="provisoria")
    e = estudio(api)
    m1, r1 = muestra(api, e, {"n_por_estrato": 10}, semilla=1)
    assert r1["marco"] == 3                                               # Q2: por defecto no entra la provisoria
    sql.execute("UPDATE muestra SET estado = 'cerrada' WHERE id = %s", (m1,))
    m2, r2 = muestra(api, e, {"n_por_estrato": 10, "incluir_provisoria": True}, semilla=1, nombre="Con provisoria")
    assert r2["marco"] == 6
    filas = leer_csv(api.get(f"/muestras/{m2}/csv?parte_id={e['partes'][0]['id']}", rol="coordinador"))
    prov = [f for f in filas if f["EC_ID_EMPRESA"].startswith("P-")]
    assert len(prov) == 3 and all(f["rut"] == "" and "EC_RUT=&" in f["link"] for f in prov)
    # el .sav se asocia por EC_ID_ITEM; un EC_RUT válido para una provisoria queda propuesto, no aplicado
    item = sql.execute("SELECT i.id, e.id AS empresa_id, e.codigo FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id"
                       " WHERE i.muestra_id = %s AND e.base = 'provisoria' LIMIT 1", (m2,)).fetchone()
    _, ing = ingerir(api, e["partes"][0]["id"], hacer_sav([fila_sav(1, {"id": item["id"], "rut": rut_valido(8)})]))
    assert ing["conteos"]["asociadas"] == 1
    assert sql.execute("SELECT base FROM empresa WHERE id = %s", (item["empresa_id"],)).fetchone()["base"] == "provisoria"
    prop = sql.execute("SELECT rut, estado FROM provisoria_rut_propuesto").fetchone()
    assert (prop["rut"], prop["estado"]) == (rut_valido(8), "pendiente")
    lst = {p["codigo"]: p for p in api.get("/provisorias").json()["empresas"]}
    assert lst[item["codigo"]]["ruts_propuestos"][0]["rut"] == rut_valido(8)


def test_fusion_provisoria_muestra_items_y_llamadas_en_la_definitiva(api, sql):
    cargar(api, [fila(0, **{"Teléfono": "2900 0000"})])
    cargar(api, [sin_rut(0, **{"Teléfono": "2400 0000"})], destino="provisoria")
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 5, "incluir_provisoria": True}, semilla=2)
    prov = provisorias(sql)[0]
    lote(api, [{"cdr_id": "p1", "inicio": "2026-10-26T11:00:00-03:00", "destino": "24000000", "encuestador": "ana"}])
    assert api.post(f"/empresas/{rut_valido(0)}/fusionar", rol="steward",
                    json={"rut_absorbida": prov["codigo"], "motivo": "es la misma"}).status_code == 200
    f = api.get(f"/empresas/{rut_valido(0)}").json()
    item_prov = sql.execute("SELECT id FROM muestra_item WHERE empresa_id = %s", (prov["id"],)).fetchone()["id"]
    assert item_prov in [m["item_id"] for m in f["muestras"]]
    assert any(x["tipo"] == "llamada" and "+59824000000" in x["descripcion"] for x in f["linea_de_tiempo"])
    a = sql.execute("SELECT detalle FROM auditoria WHERE accion = 'empresa.fusionar'").fetchone()
    assert a["detalle"]["absorbida"] == prov["codigo"] and a["detalle"]["base_absorbida"] == "provisoria"


# ─── F6.2 Reglas en cascada ───

REGLAS = [{"criterio": "rut", "tipo": "exacta"}, {"criterio": "razon_social", "tipo": "flexible", "umbral": 0.85},
          {"criterio": "direccion", "tipo": "exacta"}]


def test_coincidencia_flexible_se_decide_en_el_preview(api, sql):
    cargar(api, [fila(0, **{"Razón social": "Pérez Hnos. S.A."})])
    c = cargar(api, [sin_rut(0, **{"Razón social": "PEREZ HNOS SA", "Teléfono": "2400 5555"})],
               destino="provisoria", reglas=REGLAS, confirmar=False)
    co = c["conteos"]["coincidencias_a_decidir"]
    assert len(co) == 1 and co[0]["criterio"] == "razon_social" and co[0]["tipo"] == "flexible"
    assert co[0]["candidata"]["codigo"] == rut_valido(0) and 0.85 <= co[0]["similitud"] <= 1
    r = api.put(f"/cargas/{c['id']}/decisiones", rol="steward", json={"decisiones": {str(co[0]["fila"]): "fusionar"}})
    assert r.status_code == 200
    assert api.put(f"/cargas/{c['id']}/decisiones", rol="steward", json={"decisiones": {"99": "fusionar"}}).status_code == 422
    assert api.post(f"/cargas/{c['id']}/confirmar", rol="steward").status_code == 200
    f = api.get(f"/empresas/{rut_valido(0)}").json()
    assert "+59824005555" in [t["e164"] for t in f["telefonos"]] and not provisorias(sql)
    # deshacer la carga revierte también lo que se fusionó en ella
    assert api.delete(f"/cargas/{c['id']}", rol="steward").status_code == 200
    assert "+59824005555" not in [t["e164"] for t in api.get(f"/empresas/{rut_valido(0)}").json()["telefonos"]]


def test_rut_coincidente_se_fusiona_sin_consultar(api, sql):
    cargar(api, [fila(0, **{"Razón social": "Pérez Hnos. S.A."})])
    c = cargar(api, [fila(0, **{"Razón social": "PEREZ HNOS SA"})], reglas=REGLAS, tipo_fuente="x")
    assert c["conteos"]["coincidencias_a_decidir"] == [] and c["conteos"]["actualizaciones"] == 1


def test_pendientes_van_a_revision_y_otra_empresa_da_de_alta(api, sql):
    cargar(api, [fila(0, **{"Razón social": "Pérez Hnos. S.A."}), fila(1, **{"Razón social": "Gómez y Cía SRL"})])
    c = cargar(api, [sin_rut(0, **{"Razón social": "PEREZ HNOS SA"}), sin_rut(1, **{"Razón social": "GOMEZ Y CIA"})],
               destino="provisoria", reglas=REGLAS, confirmar=False)
    co = {x["datos"]["razon_social"]: x for x in c["conteos"]["coincidencias_a_decidir"]}
    api.put(f"/cargas/{c['id']}/decisiones", rol="steward",
            json={"decisiones": {str(co["GOMEZ Y CIA"]["fila"]): "otra", str(co["PEREZ HNOS SA"]["fila"]): "despues"}})
    api.post(f"/cargas/{c['id']}/confirmar", rol="steward")
    rev = api.get("/revision").json()
    assert len(rev) == 1 and rev[0]["criterio"] == "razon_social (flexible)" and float(rev[0]["similitud"]) >= 0.85
    assert [p["razon_social"] for p in provisorias(sql)] == ["GOMEZ Y CIA"]
    # resolver la revisión como alta crea la provisoria
    assert api.post(f"/revision/{rev[0]['id']}", rol="steward", json={"accion": "alta"}).status_code == 200
    assert len(provisorias(sql)) == 2
    assert sql.execute("SELECT reglas, decisiones FROM carga WHERE id = %s", (c["id"],)).fetchone()["reglas"][1]["umbral"] == 0.85


def test_exacta_con_una_sola_candidata_se_fusiona_sola_y_cargas_viejas_migradas(api, sql):
    cargar(api, [fila(0, **{"Teléfono": "2900 7777"})])
    reglas = [{"criterio": "rut", "tipo": "exacta"}, {"criterio": "telefono", "tipo": "exacta"}]
    c = cargar(api, [sin_rut(0, **{"Teléfono": "2900 7777", "Localidad": "Centro"})], destino="provisoria", reglas=reglas)
    assert c["conteos"]["fusion_por_telefono"] == 1 and not provisorias(sql)
    assert api.get(f"/empresas/{rut_valido(0)}").json()["localidad"] == "Centro"
    # una carga con la regla vieja queda como lista de reglas
    assert sql.execute("SELECT reglas FROM carga ORDER BY id LIMIT 1").fetchone()["reglas"] == [{"criterio": "rut", "tipo": "exacta"}]
    assert api.post("/cargas", rol="steward", json={"archivo_id": 1, "fuente": "x", "tipo_fuente": "x", "licencia": "x",
                                                    "mapeo": {}, "reglas": [{"criterio": "rut", "tipo": "flexible"}]}).status_code == 422
