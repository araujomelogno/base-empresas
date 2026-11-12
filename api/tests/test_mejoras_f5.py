"""SPEC_mejoras_sav_contactos_atributos_identidad — Fase 5: exportación configurable (F5.1)."""
from test_muestra import base, contactos, estudio, leer_csv, muestra

BASICAS = {"id_item", "telefono", "rut", "razon_social", "contacto", "link"}
CONTACTO = {"nombre", "cargo", "area", "email", "telefonos"}


def preparar(api, sql, n=6):
    api.post("/atributos", json={"nombre": "Exporta", "tipo": "lista", "opciones": ["Sí", "No"]})
    api.post("/atributos", json={"nombre": "Empleados", "tipo": "numero"})
    api.post("/atributos", json={"nombre": "Decisor", "tipo": "lista", "opciones": ["Sí", "No"], "ambito": "contacto"})
    base(api, n=n)
    sql.execute("INSERT INTO empresa_atributo (empresa_id, atributo_id, valor_texto, valor_crudo, fuente_tipo, confianza, fecha)"
                " SELECT e.id, a.id, 'Sí', 'Sí', 'carga', 50, now() FROM empresa e, atributo a WHERE a.clave = 'exporta'")
    contactos(sql)
    sql.execute("INSERT INTO contacto (empresa_id, nombre, cargo, email, fuente_tipo)"
                " SELECT id, 'Segunda ' || id, 'Asistente', 'seg' || id || '@x.com', 'manual' FROM empresa")
    sql.execute("INSERT INTO contacto_atributo (contacto_id, atributo_id, valor_texto, crudo, fuente_tipo)"
                " SELECT c.id, a.id, 'Sí', 'Sí', 'manual' FROM contacto c, atributo a WHERE a.clave = 'decisor'")
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 2})
    return e, mid, e["partes"][0]["id"]


def test_por_defecto_incluye_atributos_y_contactos(api, sql):
    e, mid, parte = preparar(api, sql)
    filas = leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={parte}", rol="coordinador"))
    cols = set(filas[0])
    assert BASICAS | {"atr_exporta", "atr_empleados"} <= cols
    for k in (1, 2, 3):  # hasta 3 contactos por defecto (configurable)
        assert {f"contacto_{k}_{c}" for c in CONTACTO} | {f"contacto_{k}_atr_decisor"} <= cols
    assert "contacto_4_nombre" not in cols
    f = filas[0]
    assert f["atr_exporta"] == "Sí" and f["contacto_1_nombre"] and f["contacto_2_nombre"] and f["contacto_3_nombre"] == ""
    assert f["contacto_1_atr_decisor"] == "Sí"
    # Auditoría registra las columnas incluidas
    a = sql.execute("SELECT detalle FROM auditoria WHERE accion = 'muestra.exportar_csv' ORDER BY id DESC LIMIT 1").fetchone()
    assert "atr_exporta" in a["detalle"]["columnas"] and "contacto_1_nombre" in a["detalle"]["columnas"]
    assert "Persona" not in str(a["detalle"])


def test_desmarcar_queda_guardado(api, sql):
    e, mid, parte = preparar(api, sql)
    r = api.put(f"/muestras/{mid}/exportacion", rol="coordinador",
                json={"atributos_excluidos": ["empleados"], "contacto_campos": ["nombre", "cargo"],
                      "atributos_contacto_excluidos": ["decisor"]})
    assert r.status_code == 200, r.text
    # la elección queda guardada para la próxima exportación de esa muestra (y no pisa el orden ni los orígenes)
    d = api.get(f"/muestras/{mid}").json()["exportacion"]
    assert d["atributos_excluidos"] == ["empleados"] and d["orden"] == "prioridad" and d["contactos"] is True
    cols = set(leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={parte}", rol="coordinador"))[0])
    assert "atr_exporta" in cols and "atr_empleados" not in cols
    assert "contacto_1_cargo" in cols and "contacto_1_email" not in cols and "contacto_1_atr_decisor" not in cols
    # un atributo nuevo entra solo (se guardan los excluidos, no los elegidos)
    api.post("/atributos", json={"nombre": "Cámara", "tipo": "texto"})
    assert "atr_camara" in set(leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={parte}", rol="coordinador"))[0])
    # sin contactos
    api.put(f"/muestras/{mid}/exportacion", rol="coordinador", json={"contactos": False})
    assert not any(c.startswith("contacto_") for c in leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={parte}", rol="coordinador"))[0])
    assert api.put(f"/muestras/{mid}/exportacion", rol="coordinador", json={"atributos_excluidos": ["nada"]}).status_code == 422


def test_sin_permiso_no_salen_contactos(api, sql):
    e, mid, parte = preparar(api, sql)
    r = api.get(f"/muestras/{mid}/csv?parte_id={parte}", rol="jefe")  # el jefe de la prueba no tiene el permiso
    filas = leer_csv(r)
    assert not any(c.startswith("contacto_") for c in filas[0]) and all(f["contacto"] == "" for f in filas)
    assert "atr_exporta" in filas[0]
    assert api.get(f"/muestras/{mid}/csv/resumen?parte_id={parte}", rol="jefe").json()["puede_exportar_contactos"] is False


def test_solo_verificados_y_cantidad_de_contactos(api, sql):
    e, mid, parte = preparar(api, sql)
    cfg = api.get("/config").json()["parametros"]
    cfg["contactos_por_empresa_csv"] = 1
    assert api.put("/config", json={"parametros": cfg, "comentario": "1 contacto"}).status_code == 200
    todos = leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={parte}", rol="coordinador"))
    assert "contacto_1_nombre" in todos[0] and "contacto_2_nombre" not in todos[0]
    sql.execute("UPDATE telefono_vinculo v SET estado = 'verificado' FROM telefono t WHERE t.id = v.telefono_id AND t.tipo = 'fijo'")
    api.put(f"/muestras/{mid}/exportacion", rol="coordinador", json={"numeros": "verificados"})
    solo = leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={parte}", rol="coordinador"))
    assert len(solo) == len(todos) // 2 and all(f["telefono"].startswith("2") for f in solo)


def test_planilla_de_la_muestra(api, sql):
    e, mid, parte = preparar(api, sql)
    r = api.get(f"/muestras/{mid}/csv?parte_id={parte}&formato=planilla", rol="coordinador")
    assert r.status_code == 200 and "planilla_muestra" in r.headers["content-disposition"]
    filas = leer_csv(r)
    n_items = sql.execute("SELECT count(*) AS n FROM muestra_item WHERE muestra_id = %s AND liberado", (mid,)).fetchone()["n"]
    assert len(filas) == n_items                                   # un renglón por empresa
    f = filas[0]
    assert f["tel_1"] and f["tel_2"] and f["tel_1_origen"] is not None and "tel_3" not in f
    assert f["atr_exporta"] == "Sí" and f["contacto_1_nombre"]
    assert len({x["id_item"] for x in filas}) == len(filas)
    assert api.get(f"/muestras/{mid}/csv?parte_id={parte}&formato=otro", rol="coordinador").status_code == 422
