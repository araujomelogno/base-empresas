"""SPEC_mejoras_sav_contactos_atributos_identidad — Fase 2: lo que trae el .sav (F2.1–F2.4, D39)."""
from test_campo import fila_sav, hacer_sav, ingerir, preparar


def fila(rid, item, **kw):
    """Fila del .sav sin variable de resultado ni status de Alchemer (D39)."""
    f = {k: v for k, v in fila_sav(rid, item, **kw).items() if k not in ("EC_RESULTADO", "status")}
    return f


def vinculo(sql, e164, empresa_id):
    return sql.execute("SELECT v.* FROM telefono_vinculo v JOIN telefono t ON t.id = v.telefono_id"
                       " WHERE t.e164 = %s AND v.empresa_id = %s", (e164, empresa_id)).fetchone()


def origenes(sql, vinculo_id):
    return {r["codigo"] for r in sql.execute(
        "SELECT o.codigo FROM telefono_vinculo_origen x JOIN origen_telefono o ON o.id = x.origen_id WHERE x.vinculo_id = %s",
        (vinculo_id,))}


# ─── F2.1 Número usado y número adicional verificados ───

def test_tel_usado_nuevo_y_existente_quedan_verificados(api, sql):
    e, mid, items = preparar(api, sql, n=3)
    parte = e["partes"][0]
    # items[0]: un número que no está en la base; items[1]: su número de la carga, «sin verificar»
    assert vinculo(sql, "+59829000001", items[1]["empresa_id"])["estado"] == "sin_verificar"
    _, ing = ingerir(api, parte["id"], hacer_sav([
        fila(1, items[0], EC_TEL_USADO="2477 1234", EC_CALIDAD_TEL=""),
        fila(2, items[1], EC_TEL_USADO="29000001", EC_CALIDAD_TEL=""),
        fila(3, items[2], EC_TEL_ALT="098 765 432", EC_CALIDAD_TEL=""),
    ]))
    v0 = vinculo(sql, "+59824771234", items[0]["empresa_id"])
    assert v0 and v0["estado"] == "verificado" and v0["fuente_tipo"] == "sala" and origenes(sql, v0["id"]) == {"sala"}
    v1 = vinculo(sql, "+59829000001", items[1]["empresa_id"])
    assert v1["estado"] == "verificado" and "sala" in origenes(sql, v1["id"])
    h = sql.execute("SELECT * FROM telefono_vinculo_historia WHERE vinculo_id = %s AND estado = 'verificado'",
                    (v1["id"],)).fetchone()
    assert h["fuente_tipo"] == "sala" and h["detalle"]["response_id"] == "2" and h["detalle"]["parte_id"] == parte["id"]
    v2 = vinculo(sql, "+59898765432", items[2]["empresa_id"])
    assert v2["estado"] == "verificado" and origenes(sql, v2["id"]) == {"sala"}
    # el detalle de la ingesta explica lo que no se aplicó
    motivos = {a["motivo"]: a["n"] for a in ing["avisos_filas"]}
    assert motivos == {"EC_TEL_ALT vacío": 2, "EC_TEL_USADO vacío": 1}


def test_calidad_negativa_gana_q1(api, sql):
    e, mid, items = preparar(api, sql, n=1)
    ingerir(api, e["partes"][0]["id"], hacer_sav([fila(1, items[0], EC_TEL_USADO="29000000", EC_CALIDAD_TEL=2)]))
    assert vinculo(sql, "+59829000000", items[0]["empresa_id"])["estado"] == "no_corresponde"


def test_prefijos_y_numero_no_normalizable(api, sql):
    cfg = api.get("/config").json()["parametros"]
    cfg["prefijos_salida"] = ["0"]
    assert api.put("/config", json={"parametros": cfg, "comentario": "prefijo de salida"}).status_code == 200
    e, mid, items = preparar(api, sql, n=2)
    _, ing = ingerir(api, e["partes"][0]["id"], hacer_sav([
        fila(1, items[0], EC_TEL_USADO="0099123456", EC_TEL_ALT="99123457"),
        fila(2, items[1], EC_TEL_USADO="xxxx"),
    ]))
    assert vinculo(sql, "+59899123456", items[0]["empresa_id"])["estado"] == "verificado"
    assert vinculo(sql, "+59899123457", items[0]["empresa_id"])["estado"] == "verificado"
    av = {a["motivo"]: a for a in ing["avisos_filas"]}
    assert av["EC_TEL_USADO no normalizable"]["n"] == 1
    assert av["EC_TEL_USADO no normalizable"]["ejemplos"][0] == {"response_id": "2", "valor": "xxxx"}


def test_fila_sin_item_no_aplica_y_al_conciliar_se_aplica(api, sql):
    e, mid, items = preparar(api, sql, n=2)
    parte = e["partes"][0]
    _, ing = ingerir(api, parte["id"], hacer_sav([
        fila(1, {"id": 9999, "rut": "1"}, EC_TEL_USADO="2477 1234", EC_RESP_NOMBRE="Ana Gómez", EC_TEL_ALT="099 111 222")]))
    assert sql.execute("SELECT count(*) AS n FROM telefono WHERE e164 = '+59824771234'").fetchone()["n"] == 0
    assert sql.execute("SELECT count(*) AS n FROM contacto").fetchone()["n"] == 0
    assert {a["motivo"] for a in ing["avisos_filas"]} == {"fila sin ítem asociado: en Conciliación"}
    c = api.get("/conciliacion?tipo=sav_fila").json()[0]
    assert api.post(f"/conciliacion/{c['id']}", rol="coordinador",
                    json={"accion": "asociar", "item_id": items[1]["id"]}).status_code == 200
    eid = items[1]["empresa_id"]
    assert vinculo(sql, "+59824771234", eid)["estado"] == "verificado"
    assert vinculo(sql, "+59899111222", eid)["estado"] == "verificado"
    ficha = api.get(f"/empresas/{items[1]['rut']}").json()
    ana = ficha["contactos"][0]
    assert ana["nombre"] == "Ana Gómez"
    assert {(t["e164"], t["relacion"]) for t in ana["telefonos"]} == {("+59824771234", "se_hablo"),
                                                                       ("+59899111222", "del_contacto")}
    assert api.get(f"/sav/{ing['id']}").json()["avisos_filas"] == []


def test_reingesta_idempotente(api, sql):
    e, mid, items = preparar(api, sql, n=1)
    contenido = hacer_sav([fila(1, items[0], EC_TEL_USADO="2477 1234", EC_RESP_NOMBRE="Ana", EC_TEL_ALT="099 111 222")])
    a1, ing1 = ingerir(api, e["partes"][0]["id"], contenido)
    cuenta = lambda t: sql.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]  # noqa: E731
    antes = {t: cuenta(t) for t in ("telefono", "telefono_vinculo", "telefono_vinculo_historia", "contacto",
                                    "contacto_historia", "contacto_telefono", "telefono_vinculo_origen")}
    ingerir(api, e["partes"][0]["id"], contenido)
    ingerir(api, e["partes"][0]["id"], contenido)
    assert {t: cuenta(t) for t in antes} == antes
    assert sql.execute("SELECT veces FROM contacto_telefono WHERE relacion = 'se_hablo'").fetchone()["veces"] == 1
    # remapear tampoco duplica
    r = api.post(f"/sav/{ing1['id']}/remapear", rol="coordinador", json={"ingesta_id": ing1["id"], "mapeo": ing1["mapeo"]})
    assert r.status_code == 200, r.text
    assert {t: cuenta(t) for t in antes} == antes


# ─── F2.2 Contacto–teléfono ───

def test_contacto_relacionado_con_el_numero(api, sql):
    e, mid, items = preparar(api, sql, n=1)
    parte = e["partes"][0]
    ingerir(api, parte["id"], hacer_sav([fila(1, items[0], EC_TEL_USADO="29000000", EC_RESP_NOMBRE="Ana Gómez",
                                              datesubmitted="2026-10-27 15:30:00")]))
    ana = api.get(f"/empresas/{items[0]['rut']}").json()["contactos"][0]
    t = ana["telefonos"][0]
    assert t["e164"] == "+59829000000" and t["relacion"] == "se_hablo" and t["ultima_vez"].startswith("2026-10-27")
    assert t["estudio"] == e["nombre"] and t["parte"] == parte["nombre"]
    # el rol de lectura no ve los contactos
    lect = api.get(f"/empresas/{items[0]['rut']}", rol="lectura").json()
    assert lect["contactos"][0]["nombre"] == "(dato personal oculto)" and lect["contactos"][0]["telefonos"] == []


# ─── F2.3 Toda fila es una completa ───

def test_toda_fila_es_una_completa(api, sql):
    e, mid, items = preparar(api, sql, n=25)
    parte = e["partes"][0]
    filas = [fila(i, it, EC_TEL_USADO="", encuestador="ana" if i % 2 else "") for i, it in enumerate(items)]
    filas += [fila(100 + i, {"id": 90000 + i, "rut": "1"}) for i in range(5)]
    a, ing = ingerir(api, parte["id"], hacer_sav(filas))
    # el mapeo ya no pide «resultado» ni «estado de Alchemer»
    assert "resultado" not in a["destinos"] and "estado_alchemer" not in a["destinos"]
    assert ing["completas"] == {"total": 30, "asociadas": 25, "sin_asociar": 5}
    t = api.get(f"/actividad?estudio_id={e['id']}").json()
    assert (t["completas"], t["completas_asociadas"], t["completas_sin_asociar"]) == (30, 25, 5)
    enc = {x["encuestador"]: x["completas"] for x in api.get("/actividad").json()["por_encuestador"]}
    assert enc["ana"] == 12 and enc["(sin encuestador)"] == 18
    estados = sql.execute("SELECT estado, count(*) AS n FROM item_parte_estado WHERE parte_id = %s GROUP BY 1",
                          (parte["id"],)).fetchall()
    assert {r["estado"]: r["n"] for r in estados}.get("completa") == 25
    assert sql.execute("SELECT count(*) AS n FROM empresa WHERE ultimo_contacto_efectivo::date = '2026-10-27'").fetchone()["n"] == 25
    det = api.get(f"/estudios/{e['id']}").json()["partes"][0]
    assert det["completas_sav"] == 30 and det["completas_sin_asociar"] == 5
    # el período toma la fecha de la fila
    assert api.get("/actividad", params={"desde": "2026-10-28"}).json()["completas"] == 0
    # conciliar las 5: el total sigue en 30 y el desglose pasa a 30 + 0
    libres = [r["id"] for r in sql.execute(
        "SELECT i.id FROM muestra_item i WHERE i.muestra_id = %s AND NOT EXISTS"
        " (SELECT 1 FROM sav_fila s WHERE s.item_id = i.id)", (mid,))]
    otros = sql.execute("INSERT INTO muestra (estudio_id, nombre, criterios, estado, creado_por) VALUES (%s,'otra','{}','activa','t')"
                        " RETURNING id", (e["id"],)).fetchone()["id"]
    sql.execute("INSERT INTO empresa (rut, razon_social) SELECT '9' || lpad(g::text, 11, '0'), 'Extra ' || g"
                " FROM generate_series(1, 5) g")
    emp = [r["id"] for r in sql.execute("SELECT id FROM empresa WHERE id NOT IN (SELECT empresa_id FROM muestra_item) LIMIT 5")]
    assert not libres and len(emp) == 5
    if len(libres) < 5:
        for k, eid in enumerate(emp):
            libres.append(sql.execute("INSERT INTO muestra_item (muestra_id, empresa_id, estrato, rol, orden, liberado)"
                                      " VALUES (%s,%s,'Total','titular',%s,true) RETURNING id", (otros, eid, k + 1)).fetchone()["id"])
    for c, item_id in zip(api.get("/conciliacion?tipo=sav_fila").json(), libres):
        assert api.post(f"/conciliacion/{c['id']}", rol="coordinador",
                        json={"accion": "asociar", "item_id": item_id}).status_code == 200
    t = api.get(f"/actividad?estudio_id={e['id']}").json()
    assert (t["completas"], t["completas_asociadas"], t["completas_sin_asociar"]) == (30, 30, 0)


def test_remapeo_marca_completas_las_ingestas_anteriores(api, sql):
    e, mid, items = preparar(api, sql, n=3)
    parte = e["partes"][0]
    a, ing = ingerir(api, parte["id"], hacer_sav([fila(i, it) for i, it in enumerate(items)]))
    # como quedó una ingesta anterior a D39: sin estado por parte ni último contacto efectivo
    sql.execute("DELETE FROM item_parte_estado")
    sql.execute("UPDATE empresa SET ultimo_contacto_efectivo = NULL")
    viejo = dict(ing["mapeo"])
    viejo["variables"] = {**viejo["variables"], "resultado": "EC_ID_ITEM"}
    viejo["valores"] = {**viejo["valores"], "resultado": {"1": "rechazo"}}
    r = api.post(f"/sav/{a['ingesta_id']}/remapear", rol="coordinador", json={"ingesta_id": a["ingesta_id"], "mapeo": viejo})
    assert r.status_code == 200, r.text
    assert sql.execute("SELECT count(*) AS n FROM item_parte_estado WHERE estado = 'completa'").fetchone()["n"] == 3
    assert sql.execute("SELECT count(*) AS n FROM empresa WHERE ultimo_contacto_efectivo IS NOT NULL").fetchone()["n"] == 3
    assert "resultado" not in api.get(f"/sav/{a['ingesta_id']}").json()["mapeo"]["variables"]


# ─── F2.4 Línea de tiempo ───

def test_linea_de_tiempo_agrupa_la_ingesta(api, sql):
    e, mid, items = preparar(api, sql, n=1)
    parte = e["partes"][0]
    a, _ = ingerir(api, parte["id"], hacer_sav([fila(1, items[0], EC_TEL_USADO="2477 1234", EC_RESP_NOMBRE="Ana Gómez",
                                                     EC_RESP_CARGO="Gerenta")]))
    tl = api.get(f"/empresas/{items[0]['rut']}").json()["linea_de_tiempo"]
    grupos = [x for x in tl if x["tipo"] == "ingesta"]
    assert len(grupos) == 1
    g = grupos[0]
    assert g["titulo"] == f"Ingesta .sav #{a['ingesta_id']} ({e['nombre']}, {parte['nombre']})"
    assert "1 contacto nuevo" in g["descripcion"] and "1 teléfono verificado" in g["descripcion"]
    assert "ítem completo" in g["descripcion"]
    desc = [x["descripcion"] for x in g["eventos"]]
    assert "alta de Ana Gómez" in desc and "se habló con Ana Gómez al +59824771234" in desc
    # el rol de lectura no ve el nombre
    tl_l = api.get(f"/empresas/{items[0]['rut']}", rol="lectura").json()["linea_de_tiempo"]
    assert not any("Ana" in x["descripcion"] for g in tl_l if g["tipo"] == "ingesta" for x in g["eventos"])
