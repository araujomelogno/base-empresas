"""SPEC_mejoras_sav_contactos_atributos_identidad — Fase 4: normalización y fusión de atributos (F4.1, F4.2, D41)."""
from conftest import cargar, csv_bytes, rut_valido
from test_base import fila
from test_muestra import estudio


def attr(api, **kw):
    r = api.post("/atributos", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def analizar(api, filas, tipo="nueva"):
    r = api.subir("/cargas/analizar", "base.csv", csv_bytes(filas), rol="steward", tipo_fuente=tipo)
    assert r.status_code == 200, r.text
    return r.json()


# ─── F4.1 Atributos parecidos ───

def test_columna_parecida_sugiere_el_atributo_existente(api, sql):
    emp = attr(api, nombre="Cantidad de empleados", tipo="numero")
    a = analizar(api, [fila(0, **{"Cant. Empleados": "12"})])
    assert "atributos" not in a["mapeo"] or "cantidad_de_empleados" not in a["mapeo"]["atributos"]
    sug = {s["columna"]: s for s in a["sugerencias_atributos"]}
    assert sug["Cant. Empleados"]["clave"] == "cantidad_de_empleados" and sug["Cant. Empleados"]["similitud"] >= 0.6
    # al aceptar, el nombre de la columna queda como sinónimo: la próxima base lo mapea sola
    assert api.post(f"/atributos/{emp['id']}/sinonimo", rol="steward", json={"texto": "Cant. Empleados"}).status_code == 200
    a2 = analizar(api, [fila(1, **{"Cant. Empleados": "8"})], tipo="otra")
    assert a2["mapeo"]["atributos"]["cantidad_de_empleados"] == "Cant. Empleados"
    assert "cant empleados" in api.get("/atributos").json()[0]["sinonimos"]
    # nada parecido: sin sugerencia
    assert not any(s["columna"] == "Departamento" for s in a["sugerencias_atributos"])


def test_aviso_al_crear_un_atributo_parecido(api):
    attr(api, nombre="Cantidad de empleados", tipo="numero")
    p = api.get("/atributos/parecidos", params={"texto": "Cant. de empleados"}).json()
    assert p and p[0]["clave"] == "cantidad_de_empleados"
    assert api.get("/atributos/parecidos", params={"texto": "Exporta"}).json() == []
    # el aviso es por ámbito
    assert api.get("/atributos/parecidos", params={"texto": "Cant. de empleados", "ambito": "contacto"}).json() == []


def test_valores_de_lista_sin_mayusculas_ni_tildes(api, sql):
    attr(api, nombre="Exporta", tipo="lista", opciones=["Sí", "No"])
    filas = [fila(0, Exporta="SI"), fila(1, Exporta="si"), fila(2, Exporta="Sí "), fila(3, Exporta="no")]
    v = api.post("/cargas/valores", rol="steward", json={"archivo_id": analizar(api, filas)["archivo_id"],
                                                         "mapeo": {"rut": "RUT", "atributos": {"exporta": "Exporta"}}}).json()
    assert v["pendientes"] == 0
    c = cargar(api, filas, mapeo={"atributos": {"exporta": "Exporta"}})
    assert c["estado"] == "confirmada"
    vals = sorted(r["valor_texto"] for r in sql.execute("SELECT valor_texto FROM empresa_atributo"))
    assert vals == ["No", "Sí", "Sí", "Sí"]


def test_valor_parecido_se_sugiere_en_la_traduccion(api):
    attr(api, nombre="Perfil", tipo="lista", opciones=["Exportador", "Importador"])
    a = analizar(api, [fila(0, Perfil="Exportadora")])
    v = api.post("/cargas/valores", rol="steward", json={"archivo_id": a["archivo_id"],
                                                         "mapeo": {"rut": "RUT", "atributos": {"perfil": "Perfil"}}}).json()
    p = v["atributos"][0]["valores"][0]
    assert p["valor"] == "Exportadora" and p["sugerido"] == "Exportador" and not p["traducido"]


def test_normalizar_texto(api, sql):
    attr(api, nombre="Cámara", tipo="texto", normalizar_texto="mayusculas")
    attr(api, nombre="Rubro libre", tipo="texto", normalizar_texto="capital")
    cargar(api, [fila(0, **{"Cámara": "  cámara  de   comercio ", "Rubro libre": "VENTA de AUTOS"})],
           mapeo={"atributos": {"camara": "Cámara", "rubro_libre": "Rubro libre"}})
    v = {r["clave"]: r["valor_texto"] for r in sql.execute(
        "SELECT a.clave, ea.valor_texto FROM empresa_atributo ea JOIN atributo a ON a.id = ea.atributo_id")}
    assert v == {"camara": "CÁMARA DE COMERCIO", "rubro_libre": "Venta de autos"}
    assert api.post("/atributos", json={"nombre": "X", "tipo": "texto", "normalizar_texto": "rara"}).status_code == 422


# ─── F4.2 Fusionar atributos ───

def test_fusionar_atributos(api, sql):
    b = attr(api, nombre="Cantidad de empleados", tipo="numero")
    a = attr(api, nombre="Empleados", tipo="numero", sinonimos=["personal"])
    cargar(api, [fila(0, Empleados="10"), fila(1, Empleados="20")], mapeo={"atributos": {"empleados": "Empleados"}},
           tipo_fuente="base vieja")
    cargar(api, [fila(1, **{"Cantidad de empleados": "25"})], mapeo={"atributos": {"cantidad_de_empleados": "Cantidad de empleados"}})
    r = api.post(f"/atributos/{a['id']}/fusionar", json={"destino_id": b["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["empresas"] == 2
    def valores(rut):
        return {x["clave"]: x["valor_numero"] for x in api.get(f"/empresas/{rut}").json()["atributos"]}
    # la empresa que solo tenía «Empleados» lo muestra en «Cantidad de empleados»
    assert float(valores(rut_valido(0))["cantidad_de_empleados"]) == 10 and "empleados" not in valores(rut_valido(0))
    assert float(valores(rut_valido(1))["cantidad_de_empleados"]) == 25  # la más reciente gana
    h = sql.execute("SELECT detalle, fuente_tipo FROM empresa_campo_historia WHERE campo = 'atributo.cantidad_de_empleados'"
                    " AND fuente_tipo = 'fusion' LIMIT 1").fetchone()
    assert h["detalle"]["fusionado_de"] == "empleados"
    cat = {x["clave"]: x for x in api.get("/atributos").json()}
    assert not cat["empleados"]["activo"] and cat["empleados"]["nota"] == "fusionado en Cantidad de empleados"
    assert {"empleados", "personal"} <= set(cat["cantidad_de_empleados"]["sinonimos"])
    # una carga nueva con la columna «Empleados» se mapea sola a B, y la plantilla vieja también
    assert analizar(api, [fila(5, Empleados="3")], tipo="nueva base")["mapeo"]["atributos"] == {"cantidad_de_empleados": "Empleados"}
    assert analizar(api, [fila(0, Empleados="3")], tipo="base vieja")["mapeo"]["atributos"] == {"cantidad_de_empleados": "Empleados"}
    # recalcular la empresa no revive el atributo fusionado
    from app import empresas as emod, db as appdb  # noqa: F401
    assert sql.execute("SELECT count(*) AS n FROM empresa_atributo WHERE atributo_id = %s", (a["id"],)).fetchone()["n"] == 0
    assert sql.execute("SELECT accion FROM auditoria WHERE accion = 'atributo.fusionar'").fetchone()
    assert api.post(f"/atributos/{a['id']}/fusionar", json={"destino_id": b["id"]}).status_code == 409


def test_fusionar_listas_unifica_opciones_y_bloqueos(api, sql):
    b = attr(api, nombre="Exporta", tipo="lista", opciones=["Sí", "No"], estratificable=True, filtrable=True)
    a = attr(api, nombre="Exportadora", tipo="lista", opciones=["SI", "NO", "A veces"], filtrable=True)
    t = attr(api, nombre="Fecha alta", tipo="fecha")
    c = attr(api, nombre="Decisor", tipo="lista", opciones=["Sí"], ambito="contacto")
    assert api.post(f"/atributos/{t['id']}/fusionar", json={"destino_id": b["id"]}).status_code == 422   # tipos
    assert api.post(f"/atributos/{c['id']}/fusionar", json={"destino_id": b["id"]}).status_code == 422   # ámbito
    assert api.post(f"/atributos/{a['id']}/fusionar", rol="steward", json={"destino_id": b["id"]}).status_code == 403
    # usado como filtro de una muestra activa: se bloquea y se dice cuál
    cargar(api, [fila(i, Exportadora="SI") for i in range(3)], mapeo={"atributos": {"exportadora": "Exportadora"}})
    est = estudio(api)
    m = api.post("/muestras", rol="jefe", json={"estudio_id": est["id"], "nombre": "Con filtro",
                                                "criterios": {"n_por_estrato": 1, "atributos": {"exportadora": {"valores": ["SI"]}}}}).json()
    sql.execute("UPDATE muestra SET estado = 'activa' WHERE id = %s", (m["id"],))
    r = api.post(f"/atributos/{a['id']}/fusionar", json={"destino_id": b["id"]})
    assert r.status_code == 409 and "Con filtro" in r.json()["detail"]
    sql.execute("UPDATE muestra SET estado = 'cerrada' WHERE id = %s", (m["id"],))
    assert api.post(f"/atributos/{a['id']}/fusionar", json={"destino_id": b["id"]}).status_code == 200
    assert {x["clave"]: x for x in api.get("/atributos").json()}["exporta"]["opciones"] == ["Sí", "No", "A veces"]
    vals = {r["valor_texto"] for r in sql.execute("SELECT valor_texto FROM empresa_atributo ea JOIN atributo x ON x.id = ea.atributo_id"
                                                  " WHERE x.clave = 'exporta'")}
    assert vals == {"Sí"}


def test_fusionar_atributos_de_contacto(api, sql):
    b = attr(api, nombre="Decisor", tipo="lista", opciones=["Sí", "No"], ambito="contacto")
    a = attr(api, nombre="Decide", tipo="lista", opciones=["Sí", "No"], ambito="contacto")
    cargar(api, [fila(0, Contacto="Ana", Decide="No")], mapeo={"contacto_atributos": {"decide": "Decide"}})
    assert api.post(f"/atributos/{a['id']}/fusionar", json={"destino_id": b["id"]}).json()["contactos"] == 1
    ana = api.get(f"/empresas/{rut_valido(0)}").json()["contactos"][0]
    assert [(x["clave"], x["valor_texto"]) for x in ana["atributos"]] == [("decisor", "No")]
