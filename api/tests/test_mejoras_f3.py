"""SPEC_mejoras_sav_contactos_atributos_identidad — Fase 3: contactos completos y atributos de contacto (F3.1–F3.3, D40)."""
import os
import tempfile

import pandas as pd
import pyreadstat

from conftest import cargar, rut_valido
from test_base import fila
from test_campo import fila_sav, ingerir, preparar


def ficha(api, rut, rol="admin"):
    return api.get(f"/empresas/{rut}", rol=rol).json()


# ─── F3.1 Alta, edición y borrado manual ───

def test_steward_agrega_edita_y_borra_un_contacto(api, sql):
    cargar(api, [fila(0, **{"Teléfono": "2900 0000 / 099 000 111"})])
    rut = rut_valido(0)
    tels = {t["e164"]: t["telefono_id"] for t in ficha(api, rut)["telefonos"]}
    r = api.post(f"/empresas/{rut}/contactos", rol="steward", json={
        "nombre": "Ana Gómez", "cargo": "Gerenta", "email": "ana@empresa.com.uy",
        "telefonos": [tels["+59829000000"]], "telefonos_nuevos": ["098 123 456"]})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    c = ficha(api, rut)["contactos"][0]
    assert c["nombre"] == "Ana Gómez" and c["email"] == "ana@empresa.com.uy"
    assert {(t["e164"], t["relacion"]) for t in c["telefonos"]} == {("+59829000000", "del_contacto"),
                                                                     ("+59898123456", "del_contacto")}
    # el número nuevo quedó vinculado a la empresa como manual
    nuevo = {t["e164"]: t for t in ficha(api, rut)["telefonos"]}["+59898123456"]
    assert [o["codigo"] for o in nuevo["origenes"]] == ["manual"]
    # email inválido → 422; duplicado por nombre normalizado → 409 con el id del existente
    assert api.post(f"/empresas/{rut}/contactos", rol="steward", json={"nombre": "X", "email": "no-es-mail"}).status_code == 422
    dup = api.post(f"/empresas/{rut}/contactos", rol="steward", json={"nombre": "ana  GOMEZ"})
    assert dup.status_code == 409 and dup.json()["detail"]["duplicado"] == cid
    assert api.post(f"/empresas/{rut}/contactos", rol="steward", json={"nombre": "Ana Gomez", "forzar": True}).status_code == 200
    # edición: cada campo que cambia queda en la historia con fuente manual y el usuario
    r = api.patch(f"/contactos/{cid}", rol="steward", json={"cargo": "Directora", "area": "RRHH",
                                                             "telefonos": [tels["+59829000000"]]})
    assert r.status_code == 200 and set(r.json()["cambios"]) == {"cargo", "area"}
    h = sql.execute("SELECT campo, valor, fuente_tipo, actor FROM contacto_historia WHERE contacto_id = %s ORDER BY id",
                    (cid,)).fetchall()
    assert ("cargo", "Directora", "manual", "steward@equipos.com.uy") in [tuple(x.values()) for x in h]
    assert ("telefono", None, "manual", "steward@equipos.com.uy") in [tuple(x.values()) for x in h]
    assert [t["e164"] for c in ficha(api, rut)["contactos"] if c["id"] == cid for t in c["telefonos"]] == ["+59829000000"]
    # la línea de tiempo muestra el alta y la edición
    tl = [x["descripcion"] for x in ficha(api, rut)["linea_de_tiempo"]]
    assert "alta de Ana Gómez" in tl and "Ana Gómez: cargo = Directora" in tl
    # no llamar por contacto, y borrado definitivo: Auditoría sin el nombre
    sql.execute("INSERT INTO no_llamar (alcance, objeto_id, motivo, solicitante, registrado_por)"
                " VALUES ('contacto', %s, 'pidió', 'Ana', 'x')", (cid,))
    assert api.delete(f"/contactos/{cid}", rol="steward").status_code == 200
    for t, w in (("contacto", "id = %s"), ("contacto_historia", "contacto_id = %s"), ("contacto_telefono", "contacto_id = %s"),
                 ("no_llamar", "alcance = 'contacto' AND objeto_id = %s")):
        assert sql.execute(f"SELECT count(*) AS n FROM {t} WHERE {w}", (cid,)).fetchone()["n"] == 0, t
    a = sql.execute("SELECT * FROM auditoria WHERE accion = 'contacto.borrar'").fetchone()
    assert a["objeto_id"] == rut and a["detalle"]["contacto_id"] == cid and "Ana" not in str(a["detalle"])
    # la historia sigue siendo append-only fuera del borrado
    otro = sql.execute("SELECT id FROM contacto_historia LIMIT 1").fetchone()["id"]
    try:
        sql.execute("DELETE FROM contacto_historia WHERE id = %s", (otro,))
        assert False, "debería ser append-only"
    except Exception as e:  # noqa: BLE001
        assert "append-only" in str(e)


def test_coordinador_y_lectura_no_editan_contactos(api, sql):
    cargar(api, [fila(0)])
    rut = rut_valido(0)
    cid = api.post(f"/empresas/{rut}/contactos", rol="admin", json={"nombre": "Luis"}).json()["id"]
    for rol in ("coordinador", "lectura", "jefe"):
        assert api.post(f"/empresas/{rut}/contactos", rol=rol, json={"nombre": "X"}).status_code == 403
        assert api.patch(f"/contactos/{cid}", rol=rol, json={"cargo": "X"}).status_code == 403
        assert api.delete(f"/contactos/{cid}", rol=rol).status_code == 403
    assert ficha(api, rut, "lectura")["contactos"][0]["nombre"] == "(dato personal oculto)"


# ─── F3.2 Contactos en la carga ───

def test_contactos_en_la_carga_y_deshacer(api, sql):
    filas = [fila(0, Contacto="Ana Gómez", Cargo="Gerenta", Email="ana@a.com", **{"Tel. contacto": "099 555 001"}),
             fila(1, Contacto="Beto Ruiz", Cargo="", Email="", **{"Tel. contacto": ""}),
             fila(2, Contacto="", Cargo="Contador", Email="", **{"Tel. contacto": ""})]
    r = api.subir("/cargas/analizar", "base.csv", __import__("conftest").csv_bytes(filas), rol="steward", tipo_fuente="x")
    m = r.json()["mapeo"]
    assert (m["contacto_nombre"], m["contacto_cargo"], m["contacto_email"], m["contacto_telefono"]) == \
        ("Contacto", "Cargo", "Email", "Tel. contacto")
    assert not m.get("email")
    c = cargar(api, filas)
    k = c["conteos"]
    assert (k["contactos_nuevos"], k["contactos_sin_nombre"]) == (2, 1)
    ana = ficha(api, rut_valido(0))["contactos"][0]
    assert (ana["nombre"], ana["cargo"], ana["email"]) == ("Ana Gómez", "Gerenta", "ana@a.com")
    assert [(t["e164"], t["relacion"]) for t in ana["telefonos"]] == [("+59899555001", "del_contacto")]
    tel = {t["e164"]: t for t in ficha(api, rut_valido(0))["telefonos"]}["+59899555001"]
    assert [o["codigo"] for o in tel["origenes"]] == ["sin_dato"]
    # una segunda carga completa solo los campos vacíos
    c2 = cargar(api, [fila(0, Contacto="ana gomez", Cargo="Directora", Email="", **{"Tel. contacto": ""}),
                      fila(1, Contacto="Beto Ruiz", Cargo="Jefe", Email="", **{"Tel. contacto": ""})])
    assert c2["conteos"]["contactos_actualizados"] == 1
    assert ficha(api, rut_valido(0))["contactos"][0]["cargo"] == "Gerenta"
    assert ficha(api, rut_valido(1))["contactos"][0]["cargo"] == "Jefe"
    # deshacer la primera carga quita los contactos que trajo
    assert api.delete(f"/cargas/{c['id']}", rol="steward").status_code == 200
    assert sql.execute("SELECT count(*) AS n FROM contacto").fetchone()["n"] == 0
    assert sql.execute("SELECT count(*) AS n FROM contacto_telefono").fetchone()["n"] == 0
    assert sql.execute("SELECT count(*) AS n FROM contacto_historia").fetchone()["n"] == 0


def test_plantilla_vieja_con_campos_de_contacto_los_usa(api, sql):
    filas = [fila(0, Responsable="Ana")]
    cargar(api, filas, tipo_fuente="vieja", mapeo={"contacto_nombre": "Responsable"})
    r = api.subir("/cargas/analizar", "base.csv", __import__("conftest").csv_bytes(filas), rol="steward", tipo_fuente="vieja")
    assert r.json()["mapeo"]["contacto_nombre"] == "Responsable" and r.json()["avisos"] == []
    # sin columna de nombre no se pueden cargar contactos
    a = r.json()
    m = {**a["mapeo"], "contacto_nombre": None, "contacto_cargo": "Responsable", "origen_defecto": "sin_dato"}
    x = api.post("/cargas", rol="steward", json={"archivo_id": a["archivo_id"], "fuente": "x", "tipo_fuente": "vieja",
                                                 "licencia": "propia", "mapeo": m})
    assert x.status_code == 422 and "nombre del contacto" in x.text


# ─── F3.3 Atributos de contacto ───

def test_atributo_de_contacto_desde_el_sav(api, sql):
    dec = api.post("/atributos", json={"nombre": "Decisor", "tipo": "lista", "opciones": ["Sí", "No"], "ambito": "contacto",
                                        "filtrable": True})
    assert dec.status_code == 200 and dec.json()["ambito"] == "contacto" and dec.json()["filtrable"] is False
    assert [a["clave"] for a in api.get("/atributos", params={"ambito": "contacto"}).json()] == ["decisor"]
    assert [a["clave"] for a in api.get("/atributos", params={"ambito": "empresa"}).json()] == ["id_informado"]  # de sistema
    e, mid, items = preparar(api, sql, n=1)
    df = pd.DataFrame([{**{k: v for k, v in fila_sav(1, items[0], EC_RESP_NOMBRE="Ana Gómez").items()
                           if k not in ("EC_RESULTADO", "status")}, "Q12": 1}])
    fd, ruta = tempfile.mkstemp(suffix=".sav")
    os.close(fd)
    pyreadstat.write_sav(df, ruta, variable_value_labels={"Q12": {1: "Sí", 2: "No"}})
    contenido = open(ruta, "rb").read()
    os.unlink(ruta)

    def mapear(m):
        m["atributos_contacto"] = {"decisor": "Q12"}
        m["traducciones"] = {"atributo.decisor": {"1": "Sí", "2": "No"}}
    a, ing = ingerir(api, e["partes"][0]["id"], contenido, mapeo_mod=mapear)
    assert ing["estado"] == "confirmada"
    ana = ficha(api, items[0]["rut"])["contactos"][0]
    assert [(x["clave"], x["valor_texto"]) for x in ana["atributos"]] == [("decisor", "Sí")]
    h = sql.execute("SELECT valor, fuente_tipo FROM contacto_historia WHERE campo = 'atributo.decisor'").fetchone()
    assert (h["valor"], h["fuente_tipo"]) == ("Sí", "sala")
    # un atributo de contacto desconocido o una traducción inválida no pasan
    malo = api.post(f"/sav/{a['ingesta_id']}/remapear", rol="coordinador", json={
        "ingesta_id": a["ingesta_id"], "mapeo": {**ing["mapeo"], "traducciones": {"atributo.decisor": {"1": "Quizás"}}}})
    assert malo.status_code == 422


def test_atributo_de_contacto_en_la_carga_y_la_ficha(api, sql):
    api.post("/atributos", json={"nombre": "Decisor", "tipo": "lista", "opciones": ["Sí", "No"], "ambito": "contacto"})
    api.post("/atributos", json={"nombre": "Antigüedad", "tipo": "numero", "ambito": "contacto"})
    c = cargar(api, [fila(0, Contacto="Ana", Decisor="Sí", **{"Antigüedad": "4"})])
    assert c["conteos"]["atributos"]["decisor"]["cargados"] == 1
    ana = ficha(api, rut_valido(0))["contactos"][0]
    assert {x["clave"]: x["valor_texto"] for x in ana["atributos"]} == {"decisor": "Sí", "antiguedad": "4"}
    # desde la ficha (steward)
    r = api.patch(f"/contactos/{ana['id']}", rol="steward", json={"atributos": {"decisor": "No", "antiguedad": None}})
    assert r.status_code == 200, r.text
    ana = ficha(api, rut_valido(0))["contactos"][0]
    assert {x["clave"]: x["valor_texto"] for x in ana["atributos"]} == {"decisor": "No"}
    assert api.patch(f"/contactos/{ana['id']}", rol="steward", json={"atributos": {"decisor": "Tal vez"}}).status_code == 422
    # no se usan para filtrar ni estratificar el sorteo, ni entran en los atributos de la empresa
    assert all(a["clave"] not in ("decisor", "antiguedad") for a in ficha(api, rut_valido(0))["atributos"])
    assert api.post("/muestras/marco", rol="jefe", json={"n_por_estrato": 1, "atributos": {"decisor": {"valores": ["Sí"]}}}).status_code == 422
    # el ámbito no se cambia y un atributo con valores no se borra
    assert api.put(f"/atributos/{ana['atributos'][0]['atributo_id']}", json={"ambito": "empresa"}).status_code == 422
    assert api.delete(f"/atributos/{ana['atributos'][0]['atributo_id']}").status_code == 409
