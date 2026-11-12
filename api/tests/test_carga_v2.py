"""Carga de bases v2: atributos administrables y origen del teléfono (SPEC_carga_v2, C11)."""
import csv
import io

import psycopg

from conftest import DSN, cargar, csv_bytes, rut_valido
from test_muestra import estudio, muestra

JOB = {"X-Job-Token": "token-job"}


def atributo(api, **kw):
    datos = {"clave": "empleados", "nombre": "Cantidad de empleados", "tipo": "numero", "filtrable": True}
    datos.update(kw)
    r = api.post("/atributos", json=datos)
    assert r.status_code == 200, r.text
    return r.json()


def origen(api, codigo, nombre, prioridad=None):
    r = api.post("/origenes-telefono", json={"codigo": codigo, "nombre": nombre, "prioridad": prioridad})
    assert r.status_code == 200, r.text
    return r.json()


def ficha(api, n):
    return api.get(f"/empresas/{rut_valido(n)}").json()


def origenes_de(api, n):
    """{e164: [códigos de origen]} de la ficha."""
    return {t["e164"]: sorted(o["codigo"] for o in t["origenes"]) for t in ficha(api, n)["telefonos"]}


# ─── C1 · Catálogo de atributos ───

def test_catalogo_de_atributos(api):
    a = atributo(api)
    assert a["clave"] == "empleados" and a["activo"]
    assert api.post("/atributos", rol="steward", json={"clave": "x", "nombre": "X", "tipo": "texto"}).status_code == 403
    assert api.post("/atributos", json={"clave": "Con Espacios", "nombre": "X", "tipo": "texto"}).status_code == 422
    assert api.post("/atributos", json={"clave": "empleados", "nombre": "Otro", "tipo": "texto"}).status_code == 409
    # F1.5: una lista puede crearse sin opciones (se completan en la carga)
    sin_op = api.post("/atributos", json={"clave": "exporta", "nombre": "Exporta", "tipo": "lista"})
    assert sin_op.status_code == 200 and sin_op.json()["opciones"] == []
    assert api.post("/atributos", json={"clave": "zona", "nombre": "Zona", "tipo": "texto",
                                        "estratificable": True}).status_code == 422
    # la clave es inmutable
    assert api.put(f"/atributos/{a['id']}", json={"clave": "otra"}).status_code == 422
    r = api.put(f"/atributos/{a['id']}", json={"nombre": "Empleados", "sinonimos": ["Cant. empleados", "personal"]})
    assert r.json()["nombre"] == "Empleados" and r.json()["sinonimos"] == ["cant empleados", "personal"]
    assert api.get("/atributos", rol="lectura").status_code == 200
    acciones = [x["accion"] for x in api.get("/auditoria").json()]
    assert "atributo.crear" in acciones and "atributo.editar" in acciones


def test_carga_con_atributos_de_cada_tipo(api, sql):
    atributo(api, sinonimos=["cant empleados"])
    atributo(api, clave="exporta", nombre="Exporta", tipo="lista", opciones=["Sí", "No"], estratificable=True)
    atributo(api, clave="fundacion", nombre="Fecha de fundación", tipo="fecha")
    atributo(api, clave="camara", nombre="Cámara", tipo="texto")
    filas = [
        {"RUT": rut_valido(0), "Cant. empleados": "1.234", "Exporta": "Sí", "Fecha de fundación": "05/03/2020",
         "Cámara": "CIU", "Teléfono": "29001111"},
        {"RUT": rut_valido(1), "Cant. empleados": "muchos", "Exporta": "No", "Fecha de fundación": "2019-12-31",
         "Cámara": "", "Teléfono": "29002222"},
    ]
    c = cargar(api, filas, confirmar=False)
    assert c["mapeo"]["atributos"] == {"empleados": "Cant. empleados", "exporta": "Exporta",
                                       "fundacion": "Fecha de fundación", "camara": "Cámara"}
    k = c["conteos"]["atributos"]
    assert k["empleados"] == {"cargados": 1, "invalidos": 1, "sin_dato": 0}
    assert k["camara"]["cargados"] == 1 and k["fundacion"]["cargados"] == 2
    assert sql.execute("SELECT count(*) AS n FROM empresa_atributo").fetchone()["n"] == 0  # el preview no escribe
    api.post(f"/cargas/{c['id']}/confirmar", rol="steward")
    v = {a["clave"]: a for a in ficha(api, 0)["atributos"]}
    assert float(v["empleados"]["valor_numero"]) == 1234 and v["exporta"]["valor_texto"] == "Sí"
    assert v["fundacion"]["valor_fecha"] == "2020-03-05" and v["camara"]["valor_texto"] == "CIU"
    w = {a["clave"]: a for a in ficha(api, 1)["atributos"]}
    assert w["empleados"]["invalido"] and w["empleados"]["valor_crudo"] == "muchos"  # valor inválido queda crudo
    assert "camara" not in w
    # la historia usa empresa_campo_historia con campo = 'atributo.<clave>'
    assert any(h["campo"] == "atributo.empleados" for h in ficha(api, 0)["historia"])


def test_supervivencia_y_deshacer_anulan_atributos(api, sql):
    atributo(api)
    cargar(api, [{"RUT": rut_valido(0), "Empleados": "10"}], confianza=60, tipo_fuente="a")
    c2 = cargar(api, [{"RUT": rut_valido(0), "Empleados": "20"}], confianza=40, tipo_fuente="b")
    assert c2["conteos"]["conflictos"] == 1                       # menor confianza: no gana
    assert float({a["clave"]: a for a in ficha(api, 0)["atributos"]}["empleados"]["valor_numero"]) == 10
    c3 = cargar(api, [{"RUT": rut_valido(0), "Empleados": "30"}], confianza=60, tipo_fuente="c")
    assert float({a["clave"]: a for a in ficha(api, 0)["atributos"]}["empleados"]["valor_numero"]) == 30  # igual: la más reciente
    r = api.delete(f"/cargas/{c3['id']}", rol="steward")
    assert r.json()["estado"] == "deshecha"
    assert float({a["clave"]: a for a in ficha(api, 0)["atributos"]}["empleados"]["valor_numero"]) == 10


def test_desactivar_y_borrar_atributo(api, sql):
    a = atributo(api)
    sin_valores = atributo(api, clave="otro", nombre="Otro", tipo="texto")
    cargar(api, [{"RUT": rut_valido(0), "Empleados": "10"}])
    assert api.delete(f"/atributos/{a['id']}").status_code == 409      # tiene valores
    assert api.delete(f"/atributos/{sin_valores['id']}").status_code == 200
    api.put(f"/atributos/{a['id']}", json={"activo": False})
    r = api.subir("/cargas/analizar", "x.csv", csv_bytes([{"RUT": rut_valido(1), "Empleados": "3"}]), rol="steward")
    assert "atributos" not in r.json()["mapeo"]                         # sale del mapeo
    assert ficha(api, 0)["atributos"][0]["valor_texto"] == "10"         # conserva los valores
    body = {"archivo_id": r.json()["archivo_id"], "fuente": "x", "tipo_fuente": "x", "licencia": "interna",
            "mapeo": {"rut": "RUT", "atributos": {"empleados": "Empleados"}}}
    assert api.post("/cargas", rol="steward", json=body).status_code == 422


def test_no_se_borra_atributo_usado_en_muestra_activa(api, sql):
    a = atributo(api, clave="exporta", nombre="Exporta", tipo="lista", opciones=["Sí", "No"], estratificable=True)
    cargar(api, [{"RUT": rut_valido(i), "Teléfono": f"2900{i:04d}"} for i in range(3)])
    e = estudio(api)
    muestra(api, e, {"n_por_estrato": 1, "estratificar_por": ["atributo.exporta"]})
    assert api.delete(f"/atributos/{a['id']}").status_code == 409


# ─── C3 · Mapeo ───

def test_mapeo_con_contactos_y_plantilla_vieja(api, sql):
    """D-d (SPEC_mejoras_sav_contactos, F3.2): los contactos pueden venir en una carga; las plantillas viejas los usan."""
    filas = [{"RUT": rut_valido(0), "Razón social": "X SA", "Contacto": "Ana", "Cargo": "Gerente", "Teléfono": "29001111"}]
    a = api.subir("/cargas/analizar", "x.csv", csv_bytes(filas), rol="steward", tipo_fuente="vieja").json()
    assert (a["mapeo"]["contacto_nombre"], a["mapeo"]["contacto_cargo"]) == ("Contacto", "Cargo")
    assert "contacto_nombre" in a["campos"]["contacto"]
    sql.execute("INSERT INTO carga_plantilla (tipo_fuente, mapeo, autor) VALUES ('vieja', %s, 'x')",
                (psycopg.types.json.Jsonb({"rut": "RUT", "razon_social": "Razón social", "contacto_nombre": "Contacto",
                                           "telefonos": ["Teléfono"]}),))
    b = api.subir("/cargas/analizar", "x.csv", csv_bytes(filas), rol="steward", tipo_fuente="vieja").json()
    assert b["origen_mapeo"] == "plantilla" and b["mapeo"]["contacto_nombre"] == "Contacto" and b["avisos"] == []
    c = cargar(api, filas, tipo_fuente="vieja", mapeo={"contacto_nombre": "Contacto"})
    assert c["estado"] == "confirmada" and c["conteos"]["contactos_nuevos"] == 1
    assert sql.execute("SELECT nombre FROM contacto").fetchone()["nombre"] == "Ana"


# ─── C4 · Origen del teléfono ───

def test_origen_desde_columnas_emparejadas_fijo_y_por_defecto(api, sql):
    origen(api, "guia", "Guía telefónica", 30)
    origen(api, "dgi", "DGI", 40)
    origen(api, "web", "Web de la empresa", 50)
    filas = [
        {"RUT": rut_valido(0), "Tel 1": "29001111 / 29001112", "Origen 1": "guia", "Tel 2": "099111222", "Origen 2": "dgi",
         "Celular": "099333444"},
        {"RUT": rut_valido(1), "Tel 1": "29002222", "Origen 1": "", "Tel 2": "", "Origen 2": "", "Celular": ""},
        {"RUT": rut_valido(2), "Tel 1": "", "Origen 1": "", "Tel 2": "", "Origen 2": "", "Celular": ""},
    ]
    a = api.subir("/cargas/analizar", "x.csv", csv_bytes(filas), rol="steward").json()
    assert a["mapeo"]["telefonos"] == ["Tel 1", "Tel 2", "Celular"]
    assert a["mapeo"]["origenes_telefono"] == {"Tel 1": {"columna": "Origen 1"}, "Tel 2": {"columna": "Origen 2"}}
    c = cargar(api, filas, origen_defecto="web", mapeo={
        "origenes_telefono": {**a["mapeo"]["origenes_telefono"], "Celular": {"fijo": "dgi"}}}, confirmar=False)
    k = c["conteos"]
    assert k["filas_por_telefonos"] == {"0": 1, "1": 1, "2": 0, "3+": 1}
    assert k["telefonos_por_origen"] == {"guia": {"nuevos": 2, "existentes": 0}, "dgi": {"nuevos": 2, "existentes": 0},
                                         "web": {"nuevos": 1, "existentes": 0}}
    api.post(f"/cargas/{c['id']}/confirmar", rol="steward")
    assert origenes_de(api, 0) == {"+59829001111": ["guia"], "+59829001112": ["guia"], "+59899111222": ["dgi"],
                                   "+59899333444": ["dgi"]}
    assert origenes_de(api, 1) == {"+59829002222": ["web"]}       # columna de origen vacía: el origen por defecto
    # la empresa sin teléfono se carga igual
    assert ficha(api, 2)["disponibilidad"]["reglas"] == ["sin_telefono_discable"]


def test_columna_de_origen_compartida_y_mismo_numero_con_dos_origenes(api, sql):
    origen(api, "guia", "Guía telefónica")
    origen(api, "dgi", "DGI")
    filas = [{"RUT": rut_valido(0), "Teléfono": "29001111", "Celular": "099111222", "Fuente": "guia"}]
    c1 = cargar(api, filas)
    assert c1["mapeo"]["origenes_telefono"] == {"Teléfono": {"columna": "Fuente"}, "Celular": {"columna": "Fuente"}}
    filas2 = [{"RUT": rut_valido(0), "Teléfono": "29001111", "Fuente": "DGI"}]   # coincide con el nombre: no hay que traducir
    c2 = cargar(api, filas2)
    assert c2["conteos"]["telefonos_por_origen"] == {"dgi": {"nuevos": 0, "existentes": 1}}
    assert origenes_de(api, 0) == {"+59829001111": ["dgi", "guia"], "+59899111222": ["guia"]}
    assert sql.execute("SELECT count(*) AS n FROM telefono_vinculo").fetchone()["n"] == 2
    # deshacer la segunda carga le quita solo el origen que sumó
    api.delete(f"/cargas/{c2['id']}", rol="steward")
    assert origenes_de(api, 0) == {"+59829001111": ["guia"], "+59899111222": ["guia"]}


def test_origen_por_defecto_obligatorio_y_codigo_valido(api):
    filas = [{"RUT": rut_valido(0), "Teléfono": "29001111"}]
    a = api.subir("/cargas/analizar", "x.csv", csv_bytes(filas), rol="steward").json()
    body = {"archivo_id": a["archivo_id"], "fuente": "x", "tipo_fuente": "x", "licencia": "interna", "mapeo": a["mapeo"]}
    assert "origen por defecto" in api.post("/cargas", rol="steward", json=body).json()["detail"]
    body["mapeo"] = {**a["mapeo"], "origen_defecto": "inventado"}
    assert api.post("/cargas", rol="steward", json=body).status_code == 422


def test_origenes_de_sistema_sala_y_manual(api, sql):
    assert {o["codigo"] for o in api.get("/origenes-telefono").json()} >= {"sala", "manual", "sin_dato"}
    sala = next(o for o in api.get("/origenes-telefono").json() if o["codigo"] == "sala")
    assert api.delete(f"/origenes-telefono/{sala['id']}").status_code == 409
    assert api.put(f"/origenes-telefono/{sala['id']}", json={"activo": False}).status_code == 409
    cargar(api, [{"RUT": rut_valido(0), "Teléfono": "29001111"}])
    api.post(f"/empresas/{rut_valido(0)}/telefonos", rol="steward", json={"numero": "099555666"})
    assert origenes_de(api, 0) == {"+59829001111": ["sin_dato"], "+59899555666": ["manual"]}
    o = origen(api, "guia", "Guía")
    assert api.delete(f"/origenes-telefono/{o['id']}").status_code == 200
    r = api.put("/origenes-telefono/orden", json={"codigos": ["manual", "sala"]})
    assert [x["codigo"] for x in r.json()][:2] == ["manual", "sala"] and r.json()[-1]["codigo"] == "sin_dato"


# ─── C5 · Traducción de valores ───

def test_traduccion_sugerida_pero_no_aplicada_sin_confirmar(api, sql):
    origen(api, "guia", "Guía telefónica")
    atributo(api, clave="exporta", nombre="Exporta", tipo="lista", opciones=["Sí", "No"])
    filas = [{"RUT": rut_valido(0), "Teléfono": "29001111", "Origen": "GUIA TELEFONICA", "Exporta": "si"},
             {"RUT": rut_valido(1), "Teléfono": "29002222", "Origen": "Páginas blancas", "Exporta": "NO"},
             {"RUT": rut_valido(2), "Teléfono": "29003333", "Origen": "GUIA TELEFONICA", "Exporta": "s/d"}]
    a = api.subir("/cargas/analizar", "x.csv", csv_bytes(filas), rol="steward", tipo_fuente="dir").json()
    m = {**a["mapeo"], "origen_defecto": "sin_dato"}
    v = api.post("/cargas/valores", rol="steward", json={"archivo_id": a["archivo_id"], "mapeo": m}).json()
    assert v["origen"][0] == {"valor": "GUIA TELEFONICA", "filas": 2, "sugerido": "guia", "traduccion": None,
                              "traducido": False}
    assert v["origen"][1]["sugerido"] is None
    ex = v["atributos"][0]
    assert ex["clave"] == "exporta" and {x["valor"]: x["sugerido"] for x in ex["valores"]} == {"si": "Sí", "NO": "No", "s/d": None}
    assert v["pendientes"] == 5
    body = {"archivo_id": a["archivo_id"], "fuente": "x", "tipo_fuente": "dir", "licencia": "interna", "mapeo": m}
    r = api.post("/cargas", rol="steward", json=body)
    assert r.status_code == 422 and "sin traducir" in r.json()["detail"]   # la sugerencia nunca se aplica sola
    # «crear uno nuevo» es dar de alta el origen (admin) y traducir a él
    origen(api, "paginas_blancas", "Páginas Blancas")
    m["traducciones"] = {"origen": {"GUIA TELEFONICA": "guia", "Páginas blancas": "paginas_blancas"},
                         "atributo.exporta": {"si": "Sí", "NO": "No", "s/d": None}}
    r = api.post("/cargas", rol="steward", json=body)
    assert r.status_code == 200, r.text
    api.post(f"/cargas/{r.json()['carga_id']}/confirmar", rol="steward")
    assert origenes_de(api, 0) == {"+59829001111": ["guia"]} and origenes_de(api, 1) == {"+59829002222": ["paginas_blancas"]}
    assert ficha(api, 0)["atributos"][0]["valor_texto"] == "Sí"
    assert ficha(api, 2)["atributos"] == []                               # «sin dato»
    # la traducción queda en la plantilla y se precarga
    b = api.subir("/cargas/analizar", "y.csv", csv_bytes(filas), rol="steward", tipo_fuente="dir").json()
    assert b["mapeo"]["traducciones"]["origen"]["GUIA TELEFONICA"] == "guia"
    v2 = api.post("/cargas/valores", rol="steward", json={"archivo_id": b["archivo_id"], "mapeo": b["mapeo"]}).json()
    assert v2["pendientes"] == 0


# ─── C10 · Estados ───

def test_descartar_y_deshacer(api, sql):
    c = cargar(api, [{"RUT": rut_valido(0), "Teléfono": "29001111"}], confirmar=False)
    r = api.delete(f"/cargas/{c['id']}", rol="steward")
    assert r.json()["estado"] == "descartada"
    assert api.get(f"/cargas/{c['id']}").json()["estado"] == "descartada"
    assert api.delete(f"/cargas/{c['id']}", rol="steward").status_code == 409
    c2 = cargar(api, [{"RUT": rut_valido(0), "Teléfono": "29001111"}])
    assert api.delete(f"/cargas/{c2['id']}", rol="steward").json()["estado"] == "deshecha"
    assert {x["estado"] for x in api.get("/cargas").json()} == {"descartada", "deshecha"}


def test_migracion_de_estados_y_origen_sin_dato(sql):
    """Antes de 0006: una carga descartada quedaba 'deshecha' y los vínculos no tenían origen."""
    import migrate

    sql.execute("DROP SCHEMA empresas CASCADE")
    sql.execute("DELETE FROM public.empresas_migraciones")
    previas = [p for p in migrate.migraciones() if p.name < "0006"]
    with psycopg.connect(DSN, autocommit=True) as c:
        for p in previas:
            c.execute(p.read_text(encoding="utf-8"))
            c.execute("INSERT INTO public.empresas_migraciones (nombre) VALUES (%s)", (p.name,))
        c.execute("SET search_path TO empresas")
        c.execute("INSERT INTO archivo (nombre, tipo, sha256, ruta, tamano, subido_por) VALUES ('a', 'csv', 'h', 'r', 1, 'x')")
        for estado, confirmada in (("deshecha", None), ("deshecha", "now()"), ("confirmada", "now()")):
            c.execute(f"INSERT INTO carga (archivo_id, fuente, tipo_fuente, licencia, responsable, mapeo, estado, confirmada,"
                      f" deshecha) VALUES (1, 'f', 't', 'l', 'x', '{{}}', '{estado}', {confirmada or 'NULL'}, now())")
        c.execute("INSERT INTO empresa (rut) VALUES ('210000000001')")
        c.execute("INSERT INTO telefono (e164, crudo, tipo) VALUES ('+59829001111', '29001111', 'fijo')")
        c.execute("INSERT INTO telefono_vinculo (telefono_id, empresa_id, fuente_tipo) VALUES (1, 1, 'carga')")
    migrate.aplicar(DSN, verbose=False)
    assert [r["estado"] for r in sql.execute("SELECT estado FROM carga ORDER BY id")] == ["descartada", "deshecha", "confirmada"]
    assert sql.execute("SELECT o.codigo FROM telefono_vinculo_origen x JOIN origen_telefono o ON o.id = x.origen_id"
                       ).fetchone()["codigo"] == "sin_dato"


# ─── Fusión: los orígenes acompañan al vínculo ───

def test_fusion_hereda_y_devuelve_origenes(api, sql):
    origen(api, "guia", "Guía")
    origen(api, "dgi", "DGI")
    cargar(api, [{"RUT": rut_valido(0), "Teléfono": "29001111"}], origen_defecto="guia", tipo_fuente="a")
    cargar(api, [{"RUT": rut_valido(1), "Teléfono": "29001111 / 29002222"}], origen_defecto="dgi", tipo_fuente="b")
    r = api.post(f"/empresas/{rut_valido(0)}/fusionar", rol="steward", json={"rut_absorbida": rut_valido(1), "motivo": "misma"})
    assert r.status_code == 200, r.text
    assert origenes_de(api, 0) == {"+59829001111": ["dgi", "guia"], "+59829002222": ["dgi"]}
    api.post(f"/fusiones/{r.json()['fusion_id']}/deshacer", rol="steward")
    assert origenes_de(api, 0) == {"+59829001111": ["guia"]}
    assert origenes_de(api, 1) == {"+59829001111": ["dgi"], "+59829002222": ["dgi"]}


# ─── C7 · Sorteo con atributos y origen ───

def base_v2(api):
    origen(api, "guia", "Guía telefónica", 30)
    origen(api, "dgi", "DGI", 40)
    atributo(api)
    atributo(api, clave="exporta", nombre="Exporta", tipo="lista", opciones=["Sí", "No"], estratificable=True,
             filtrable=True)
    filas = [{"RUT": rut_valido(i), "Teléfono": f"2900{i:04d}", "Origen": "guia" if i % 2 else "dgi",
              "Celular": f"099{i:06d}" if i < 4 else "", "Origen cel": "dgi",
              "Empleados": str(10 * i), "Exporta": "Sí" if i % 3 == 0 else "No"} for i in range(12)]
    return cargar(api, filas, mapeo={"origenes_telefono": {"Teléfono": {"columna": "Origen"},
                                                           "Celular": {"columna": "Origen cel"}}})


def test_sorteo_filtra_por_atributo_y_origen_y_estratifica(api, sql):
    base_v2(api)
    criterios = {"atributos": {"empleados": {"desde": "30"}}, "origenes": ["guia"],
                 "estratificar_por": ["atributo.exporta"], "n_por_estrato": 0}
    r = api.post("/muestras/marco", rol="jefe", json=criterios).json()
    assert r["universo"] == 9                                   # empleados >= 30: i = 3..11
    assert r["exclusiones"]["filtro_origen"] == 4               # sin teléfono de la guía: i = 4, 6, 8, 10
    assert {x["estrato"]: x["disponibles"] for x in r["estratos"]} == {"No": 3, "Sí": 2}   # con guía: 3, 5, 7, 9, 11
    e = estudio(api)
    mid, res = muestra(api, e, {**criterios, "n_por_estrato": 2}, semilla=42)
    assert res["exclusiones"]["filtro_origen"] == 4
    assert api.post(f"/muestras/{mid}/verificar").json()["reproducible"]
    m = api.get(f"/muestras/{mid}").json()
    assert m["criterios"]["origenes"] == ["guia"] and m["criterios"]["atributos"] == {"empleados": {"desde": "30"}}
    # filtro de lista y validaciones
    r2 = api.post("/muestras/marco", rol="jefe", json={"atributos": {"exporta": {"valores": ["Sí"]}}}).json()
    assert r2["universo"] == 4
    assert api.post("/muestras/marco", rol="jefe", json={"atributos": {"exporta": {"valores": ["Quizás"]}}}).status_code == 422
    assert api.post("/muestras/marco", rol="jefe", json={"estratificar_por": ["atributo.empleados"]}).status_code == 422


def test_sorteo_reproducible_con_filtros_nuevos(api, sql):
    base_v2(api)
    criterios = {"atributos": {"exporta": {"valores": ["No"]}}, "origenes": ["guia", "dgi"],
                 "estratificar_por": ["atributo.exporta"], "n_por_estrato": 3}
    e = estudio(api)
    m1, _ = muestra(api, e, criterios, semilla=7, nombre="A")
    lista1 = [i["rut"] for i in api.get(f"/muestras/{m1}/items").json()["items"]]
    api.post(f"/muestras/{m1}/cerrar", rol="jefe")
    m2, _ = muestra(api, e, criterios, semilla=7, nombre="B")
    assert [i["rut"] for i in api.get(f"/muestras/{m2}/items").json()["items"]] == lista1


# ─── C8 · CSV con origen ───

def leer_csv(r):
    return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))


def test_csv_filtrado_y_ordenado_por_origen(api, sql):
    base_v2(api)
    c = api.get("/config").json()["parametros"]
    c["csv_ucontact"]["columnas"].append({"columna": "origen", "campo": "origen_telefono"})
    c["csv_ucontact"]["columnas"].append({"columna": "tel", "campo": "tel_e164"})
    assert api.put("/config", json={"parametros": c}).status_code == 200
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 12}, semilla=1)
    parte = e["partes"][0]["id"]
    # por defecto: todos los orígenes, ordenados por prioridad (guía 30 antes que DGI 40)
    filas = leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={parte}", rol="coordinador"))
    assert len(filas) == 16
    rut3 = [f for f in filas if f["rut"] == rut_valido(3)]
    assert [f["origen"] for f in rut3] == ["Guía telefónica", "DGI"]
    # orden "verificados" (el anterior): por número
    api.put(f"/muestras/{mid}/exportacion", rol="coordinador", json={"orden": "verificados"})
    rut3 = [f for f in leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={parte}", rol="coordinador")) if f["rut"] == rut_valido(3)]
    assert [f["tel"] for f in rut3] == sorted(f["tel"] for f in rut3)
    # solo la guía
    r = api.put(f"/muestras/{mid}/exportacion", rol="coordinador", json={"origenes": ["guia"], "orden": "prioridad"})
    assert r.json() == {"origenes": ["guia"], "orden": "prioridad"}
    filas = leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={parte}", rol="coordinador"))
    assert {f["origen"] for f in filas} == {"Guía telefónica"} and len(filas) == 6
    s = api.get(f"/muestras/{mid}/csv/resumen?parte_id={parte}", rol="coordinador").json()
    assert s["items_sin_telefono_por_origen"] == 6 and s["items_sin_telefono"] == 0
    assert api.get(f"/muestras/{mid}").json()["exportacion"] == {"origenes": ["guia"], "orden": "prioridad"}
    assert api.put(f"/muestras/{mid}/exportacion", rol="lectura", json={}).status_code == 403
    assert sum(1 for a in api.get("/auditoria").json() if a["accion"] == "muestra.exportacion") == 2


# ─── C9 · Rendimiento por origen ───

def test_rendimiento_por_origen(api, sql):
    origen(api, "guia", "Guía telefónica", 30)
    origen(api, "dgi", "DGI", 40)
    cargar(api, [{"RUT": rut_valido(0), "Teléfono": "29001111", "Celular": "099111222"},
                 {"RUT": rut_valido(1), "Teléfono": "29002222"}], origen_defecto="guia", tipo_fuente="a")
    cargar(api, [{"RUT": rut_valido(0), "Teléfono": "29001111"}], origen_defecto="dgi", tipo_fuente="b")  # dos orígenes
    ll = [{"cdr_id": "1", "inicio": "2026-10-26T11:00:00-03:00", "destino": "29001111", "duracion": 40},
          {"cdr_id": "2", "inicio": "2026-10-26T12:00:00-03:00", "destino": "29001111", "duracion": 25,
           "disposicion": "NO ANSWER"},                               # la disposición manda sobre la duración
          {"cdr_id": "3", "inicio": "2026-10-26T13:00:00-03:00", "destino": "099111222", "duracion": 0},
          {"cdr_id": "4", "inicio": "2026-10-26T14:00:00-03:00", "destino": "29002222", "duracion": 12}]
    assert api.c.post("/api/intentos/lote", headers=JOB, json={"origen": "t", "llamadas": ll}).status_code == 200
    v = sql.execute("SELECT v.id FROM telefono_vinculo v JOIN telefono t ON t.id = v.telefono_id WHERE t.e164 = '+59899111222'"
                    ).fetchone()["id"]
    sql.execute("UPDATE telefono_vinculo SET estado = 'no_corresponde' WHERE id = %s", (v,))
    sql.execute("INSERT INTO telefono_vinculo_historia (vinculo_id, telefono_id, empresa_id, estado, fuente_tipo, actor)"
                " SELECT id, telefono_id, empresa_id, 'no_corresponde', 'sala', 'x' FROM telefono_vinculo WHERE id = %s", (v,))
    r = api.get("/actividad/origenes", rol="jefe").json()
    o = {x["codigo"]: x for x in r["origenes"]}
    assert (o["guia"]["llamados"], o["guia"]["intentos"], o["guia"]["atendidos"]) == (3, 4, 2)
    assert (o["dgi"]["llamados"], o["dgi"]["intentos"], o["dgi"]["atendidos"]) == (1, 2, 1)
    assert o["guia"]["no_corresponde"] == 1 and o["guia"]["pct_no_corresponde"] == 33.3
    assert o["dgi"]["discables"] == 1 and o["guia"]["discables"] == 2           # el no corresponde dejó de ser discable
    t = r["total"]
    assert (t["llamados"], t["intentos"], t["atendidos"], t["contactabilidad"]) == (3, 4, 2, 66.7)  # cada teléfono una vez

