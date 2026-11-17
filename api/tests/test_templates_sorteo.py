"""SPEC_templates_sorteo_sin_telefono_formatos_csv: formatos del CSV (R1), templates (R2), empresas sin teléfono (R3)
y filtros y estratos con todos los datos de la empresa (R4)."""
import pytest

from conftest import cargar, rut_valido
from test_muestra import estudio, leer_csv


def attr(api, **kw):
    r = api.post("/atributos", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def base(api, n=24, sin_telefono=0):
    """n empresas con teléfono y atributos variados; las últimas sin_telefono no tienen ningún número."""
    attr(api, nombre="Exporta", tipo="lista", opciones=["Sí", "No"])          # sin marcar «filtro» ni «estrato»
    attr(api, nombre="Cámara", tipo="texto")
    attr(api, nombre="Empleados", tipo="numero")
    filas = []
    for i in range(n):
        filas.append({"RUT": rut_valido(i), "Razón social": f"Empresa {i}",
                      "Teléfono": "" if i >= n - sin_telefono else f"2900{i:04d}",
                      "Tamaño": "Grande" if i % 3 == 0 else "Pyme", "Departamento": ["Montevideo", "Canelones", "Salto"][i % 3],
                      "Localidad": ["Centro", "Pocitos", "pocitos ", "Cordón"][i % 4], "Estado": "activa" if i % 5 else "",
                      "Exporta": "Sí" if i % 2 else "No", "Cámara": ["Cámara de Industrias", "CAMARA DE INDUSTRIAS", "Comercio",
                                                                   "Rural", "Turismo", "Software"][i % 6],
                      "Empleados": "" if i % 7 == 0 else str([2, 4, 6, 15, 30, 99, 150][i % 7])})
    return cargar(api, filas, mapeo={"atributos": {"exporta": "Exporta", "camara": "Cámara", "empleados": "Empleados"}})


def marco(api, criterios, rol="jefe"):
    r = api.post("/muestras/marco", rol=rol, json=criterios)
    assert r.status_code == 200, r.text
    return r.json()


def sortear(api, est, criterios, nombre="M", semilla=7, template_id=None):
    m = api.post("/muestras", rol="jefe", json={"estudio_id": est["id"], "nombre": nombre, "criterios": criterios,
                                                "template_id": template_id})
    assert m.status_code == 200, m.text
    r = api.post(f"/muestras/{m.json()['id']}/sortear", rol="jefe", json={"semilla": semilla})
    assert r.status_code == 200, r.text
    return m.json()["id"], r.json()


# ─── R1 Formatos del CSV ───

def test_nombres_de_archivo_por_formato(api, sql):
    base(api, 6)
    est = estudio(api)
    mid, _ = sortear(api, est, {"n_por_estrato": 6})
    parte = est["partes"][0]["id"]
    por_numero = api.get(f"/muestras/{mid}/csv?parte_id={parte}", rol="coordinador")
    por_empresa = api.get(f"/muestras/{mid}/csv?parte_id={parte}&formato=planilla", rol="coordinador")
    assert f"muestra{mid}_parte{parte}_por_numero.csv" in por_numero.headers["content-disposition"]
    assert f"muestra{mid}_parte{parte}_por_empresa.csv" in por_empresa.headers["content-disposition"]
    # el contenido no cambia: una fila por número y una fila por empresa
    assert len(leer_csv(por_numero)) == 6 and len(leer_csv(por_empresa)) == 6 and "tel_1" in leer_csv(por_empresa)[0]


# ─── R4 Filtros y estratos con todos los datos ───

def test_atributo_de_texto_sin_casilla_filtra_y_estratifica_con_otros(api, sql):
    base(api)
    assert not [a for a in api.get("/atributos").json() if a["clave"] == "camara"][0]["filtrable"]
    # «Es uno de…» compara sin mayúsculas ni tildes
    r = marco(api, {"atributos": {"camara": {"valores": ["camara de industrias"]}}})
    assert r["marco"] == 8
    vals = {v["valor"]: v["empresas"] for v in api.get("/muestras/valores-dato", params={"dato": "atributo.camara"}).json()}
    assert sum(vals.values()) == 24 and len(vals) == 5                       # dos formas de «Cámara de Industrias» = 1
    # estrato por valor normalizado, con «Otros» para los de menos de 5 empresas
    r = marco(api, {"estratificar_por": ["atributo.camara"],
                    "estratos_def": {"atributo.camara": {"agrupar": "min", "n": 5}}})
    assert {e["estrato"]: e["disponibles"] for e in r["estratos"]} == {"Cámara de Industrias": 8, "Otros": 16}
    r = marco(api, {"estratificar_por": ["atributo.camara"], "estratos_def": {"atributo.camara": {"agrupar": "top", "n": 2}}})
    assert len(r["estratos"]) == 3 and r["estratos"][-1]["estrato"] == "Otros"
    # «tiene dato» / «no tiene dato» e «incluir empresas sin dato»
    assert marco(api, {"atributos": {"empleados": {"tiene_dato": False}}})["marco"] == 4
    assert marco(api, {"atributos": {"empleados": {"desde": 100}}})["marco"] == 3
    assert marco(api, {"atributos": {"empleados": {"desde": 100, "incluir_sin_dato": True}}})["marco"] == 7


def test_tramos_de_un_atributo_numerico(api, sql):
    base(api)
    cortes = {"atributo.empleados": {"cortes": [1, 5, 20, 100]}}
    r = marco(api, {"estratificar_por": ["atributo.empleados"], "estratos_def": cortes})
    assert [e["estrato"] for e in r["estratos"]] == ["1–4", "5–19", "20–99", "100 o más", "(sin dato)"]
    assert [e["disponibles"] for e in r["estratos"]] == [4, 7, 6, 3, 4]
    # sin tramos, se pide definirlos; los sugeridos salen del marco
    r = api.post("/muestras/marco", rol="jefe", json={"estratificar_por": ["atributo.empleados"]})
    assert r.status_code == 422 and "tramos" in r.text
    t = api.post("/muestras/tramos", rol="jefe", json={"dato": "atributo.empleados"}).json()
    assert t["min"] == "4" and t["max"] == "150" and len(t["cuartiles"]) >= 3 and t["n"] == 20


def test_localidad_y_estado_como_filtro_y_estrato(api, sql):
    base(api)
    datos = {d["clave"]: d for d in api.get("/muestras/datos-sorteo", rol="jefe").json()["datos"]}
    assert {"localidad", "estado", "razon_social", "web", "ciiu2", "atributo.camara", "atributo.empleados"} <= set(datos)
    assert datos["estado"]["opciones"] == ["activa", "cerrada", "desconocida"]
    r = marco(api, {"campos": {"localidad": {"valores": ["POCITOS"]}}, "estratificar_por": ["localidad", "estado"]})
    assert r["marco"] == 12
    assert {e["estrato"] for e in r["estratos"]} == {"Pocitos | activa", "Pocitos | desconocida"}
    assert marco(api, {"campos": {"estado": {"valores": ["activa"]}}})["marco"] == 19


def test_atributos_de_contacto_no_se_usan(api, sql):
    base(api, 3)
    attr(api, nombre="Decisor", tipo="lista", opciones=["Sí"], ambito="contacto")
    datos = {d["clave"] for d in api.get("/muestras/datos-sorteo", rol="jefe").json()["datos"]}
    assert "atributo.decisor" not in datos
    r = api.post("/muestras/marco", rol="jefe", json={"atributos": {"decisor": {"valores": ["Sí"]}}})
    assert r.status_code == 422 and "contacto" in r.text
    r = api.post("/muestras/marco", rol="jefe", json={"estratificar_por": ["atributo.decisor"]})
    assert r.status_code == 422 and "contacto" in r.text


def test_cambiar_un_atributo_despues_no_altera_la_reproducibilidad(api, sql):
    base(api)
    est = estudio(api)
    mid, _ = sortear(api, est, {"estratificar_por": ["atributo.empleados", "atributo.camara"], "n_por_estrato": 1,
                                "reemplazos_por_estrato": 1,
                                "estratos_def": {"atributo.empleados": {"cortes": [1, 5, 20, 100]},
                                                 "atributo.camara": {"agrupar": "min", "n": 5}}})
    sql.execute("UPDATE empresa_atributo SET valor_numero = 5000, valor_texto = '5000', valor_crudo = '5000'"
                " WHERE atributo_id = (SELECT id FROM atributo WHERE clave = 'empleados')")
    v = api.post(f"/muestras/{mid}/verificar", rol="jefe").json()
    assert v["resultado"] == "reproducible"


def test_casillas_filtro_y_estrato_no_restringen(api, sql):
    base(api, 3)
    a = attr(api, nombre="Fundación", tipo="fecha")
    assert not a["filtrable"] and not a["estratificable"]
    r = marco(api, {"atributos": {"fundacion": {"desde": "2000-01-01", "incluir_sin_dato": True}},
                    "estratificar_por": ["atributo.fundacion", "atributo.exporta"],
                    "estratos_def": {"atributo.fundacion": {"por": "semestre"}}})
    assert r["marco"] == 3 and {e["estrato"] for e in r["estratos"]} == {"(sin dato) | No", "(sin dato) | Sí"}


# ─── R3 Empresas sin teléfono ───

def test_empresas_sin_telefono_por_muestra(api, sql):
    base(api, 12, sin_telefono=3)
    est = estudio(api)
    sin = marco(api, {"estratificar_por": ["tamano"]})
    con = marco(api, {"estratificar_por": ["tamano"], "incluir_sin_telefono": True})
    assert sin["marco"] == 9 and sin["exclusiones"]["sin_telefono_discable"] == 3
    assert con["marco"] == 12 and con["sin_telefono"] == 3 and "sin_telefono_discable" not in con["exclusiones"]
    mid, r = sortear(api, est, {"n_por_estrato": 12, "incluir_sin_telefono": True})
    assert r["sin_telefono"] == 3 and r["estratos"][0]["sin_telefono"] == 3
    assert api.get(f"/muestras/{mid}").json()["criterios"]["incluir_sin_telefono"] is True
    parte = est["partes"][0]["id"]
    planilla = leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={parte}&formato=planilla", rol="coordinador"))
    sin_tel = [f for f in planilla if not f.get("tel_1")]
    assert len(planilla) == 12 and len(sin_tel) == 3
    assert len(leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={parte}", rol="coordinador"))) == 9
    res = api.get(f"/muestras/{mid}/csv/resumen?parte_id={parte}", rol="coordinador").json()
    assert res["items_sin_telefono"] == 3
    # «Sin teléfono» en Empresas de la muestra
    lista = api.get(f"/muestras/{mid}/items", params={"sin_telefono": "true"}).json()
    assert lista["total"] == 3 and all(i["sin_telefono"] for i in lista["items"])
    # se le agrega un teléfono en la ficha: la próxima exportación lo incluye
    rut = lista["items"][0]["rut"]
    api.post(f"/empresas/{rut}/telefonos", rol="steward", json={"numero": "2477 9999"})
    assert len(leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={parte}", rol="coordinador"))) == 10
    assert api.post(f"/muestras/{mid}/verificar", rol="jefe").json()["resultado"] == "reproducible"


def test_sin_telefono_desmarcado_como_hoy(api, sql):
    base(api, 6, sin_telefono=2)
    est = estudio(api)
    mid, r = sortear(api, est, {"n_por_estrato": 6})
    assert r["marco"] == 4 and r["sin_telefono"] == 0 and "incluir_sin_telefono" not in api.get(f"/muestras/{mid}").json()["criterios"]


# ─── R2 Templates de sorteo ───

CRITERIOS = {"campos": {"departamento": {"valores": ["Montevideo", "Canelones"]}},
             "atributos": {"exporta": {"valores": ["Sí"]}},
             "estratificar_por": ["tamano", "departamento"],
             "estratos": [{"estrato": "Grande | Montevideo", "n": 1, "reemplazos": 1},
                          {"estrato": "Pyme | Canelones", "n": 2, "reemplazos": 0}],
             "estratos_descartados": ["Grande | Salto"]}


def test_guardar_y_aplicar_template_en_otro_estudio(api, sql):
    base(api)
    est = estudio(api)
    mid, _ = sortear(api, est, CRITERIOS)
    t = api.post(f"/muestras/{mid}/template", rol="jefe", json={"nombre": "Ola clima", "descripcion": "Exportadoras"})
    assert t.status_code == 200, t.text
    tid = t.json()["id"]
    # aplicado en otro estudio: los tres pasos con los mismos valores
    otro = api.post("/estudios", rol="jefe", json={"nombre": "Otro", "campo_desde": "2026-12-01", "campo_hasta": "2026-12-31"}).json()
    ap = api.post(f"/muestra-templates/{tid}/aplicar", rol="jefe").json()
    assert ap["avisos"] == [] and ap["criterios"] == {**api.get(f"/muestras/{mid}").json()["criterios"]}
    assert ap["estratos_sin_empresas"] == [] and ap["marco"]["marco"] > 0
    m2, _ = sortear(api, otro, ap["criterios"], semilla=8, template_id=tid)
    assert sql.execute("SELECT template_id FROM muestra WHERE id = %s", (m2,)).fetchone()["template_id"] == tid
    lst = {x["id"]: x for x in api.get("/muestra-templates", rol="jefe").json()}[tid]
    assert lst["veces_usado"] == 1 and lst["ultima_muestra_id"] == m2
    assert lst["resumen"]["estratos"] == ["Tamaño", "Departamento"] and lst["resumen"]["tamano"] == "3 titulares en 2 estratos"
    a = sql.execute("SELECT detalle FROM auditoria WHERE accion = 'muestra.crear' AND objeto_id = %s", (str(m2),)).fetchone()
    assert a["detalle"]["template_id"] == tid
    # editar el template no cambia la muestra que lo usó, y su reproducibilidad sigue OK
    antes = api.get(f"/muestras/{m2}").json()["criterios"]
    r = api.put(f"/muestra-templates/{tid}", rol="jefe", json={"criterios": {**ap["criterios"], "estratificar_por": ["tamano"],
                                                                             "estratos": []}})
    assert r.status_code == 200
    assert api.get(f"/muestras/{m2}").json()["criterios"] == antes
    assert api.post(f"/muestras/{m2}/verificar", rol="jefe").json()["resultado"] == "reproducible"
    for accion in ("muestra_template.crear", "muestra_template.editar"):
        assert sql.execute("SELECT 1 FROM auditoria WHERE accion = %s", (accion,)).fetchone(), accion


def test_template_con_atributo_desactivado_avisa_y_sigue(api, sql):
    base(api)
    t = api.post("/muestra-templates", rol="jefe", json={"nombre": "Con exporta", "criterios": CRITERIOS}).json()
    exporta = [a for a in api.get("/atributos").json() if a["clave"] == "exporta"][0]
    api.put(f"/atributos/{exporta['id']}", json={"activo": False})
    ap = api.post(f"/muestra-templates/{t['id']}/aplicar", rol="jefe").json()
    assert "Se quitó el filtro por Exporta: el atributo ya no está activo" in ap["avisos"]
    assert "exporta" not in ap["criterios"]["atributos"] and ap["criterios"]["campos"] == CRITERIOS["campos"]


def test_estrato_del_template_sin_empresas_en_el_marco(api, sql):
    base(api)
    c = {**CRITERIOS, "estratos": CRITERIOS["estratos"][:1] + [{"estrato": "Grande | Rivera", "n": 1, "reemplazos": 0}]}
    t = api.post("/muestra-templates", rol="jefe", json={"nombre": "Rivera", "criterios": c}).json()
    ap = api.post(f"/muestra-templates/{t['id']}/aplicar", rol="jefe").json()
    assert ap["estratos_sin_empresas"] == ["Grande | Rivera"]
    assert ap["estratos_nuevos"] == ["Pyme | Canelones"]          # del marco, no estaba en el template


def test_tramos_se_conservan_en_el_template(api, sql):
    base(api)
    c = {"estratificar_por": ["atributo.empleados"], "estratos_def": {"atributo.empleados": {"cortes": [1, 5, 20, 100]}},
         "n_por_estrato": 1}
    t = api.post("/muestra-templates", rol="jefe", json={"nombre": "Tramos", "criterios": c}).json()
    otro = api.post("/estudios", rol="jefe", json={"nombre": "Otro", "campo_desde": "2026-12-01", "campo_hasta": "2026-12-31"}).json()
    ap = api.post(f"/muestra-templates/{t['id']}/aplicar", rol="jefe").json()
    assert ap["criterios"]["estratos_def"] == {"atributo.empleados": {"cortes": ["1", "5", "20", "100"]}}
    assert [e["estrato"] for e in ap["marco"]["estratos"]] == ["1–4", "5–19", "20–99", "100 o más", "(sin dato)"]
    mid, r = sortear(api, otro, ap["criterios"], template_id=t["id"])
    assert len(r["estratos"]) == 5


def test_permisos_duplicar_desactivar_y_borrar(api, sql):
    base(api, 3)
    t = api.post("/muestra-templates", rol="jefe", json={"nombre": "Simple", "criterios": {"n_por_estrato": 1}}).json()
    for rol in ("coordinador", "lectura", "steward"):
        assert api.get("/muestra-templates", rol=rol).status_code == 403
        assert api.post("/muestra-templates", rol=rol, json={"nombre": "x", "criterios": {}}).status_code == 403
    assert api.post("/muestra-templates", rol="jefe", json={"nombre": "simple", "criterios": {}}).status_code == 409
    d = api.post(f"/muestra-templates/{t['id']}/duplicar", rol="jefe").json()
    assert d["nombre"] == "Simple (copia)" and d["criterios"] == t["criterios"]
    # borrar: solo si nunca se usó; si no, desactivar
    est = estudio(api)
    sortear(api, est, t["criterios"], template_id=t["id"])
    r = api.delete(f"/muestra-templates/{t['id']}", rol="jefe")
    assert r.status_code == 409 and "desactivalo" in r.json()["detail"]
    assert api.put(f"/muestra-templates/{t['id']}", rol="jefe", json={"activo": False}).json()["activo"] is False
    assert [x["id"] for x in api.get("/muestra-templates", rol="jefe", params={"activos": True}).json()] == [d["id"]]
    assert api.delete(f"/muestra-templates/{d['id']}", rol="jefe").status_code == 200
    assert sql.execute("SELECT 1 FROM auditoria WHERE accion = 'muestra_template.borrar'").fetchone()
    # al borrar un template, la muestra conserva sus criterios (template_id queda NULL)


@pytest.mark.parametrize("criterio", [{"estratificar_por": ["inexistente"]}, {"campos": {"inexistente": {"valores": ["x"]}}}])
def test_criterios_desconocidos(api, sql, criterio):
    assert api.post("/muestras/marco", rol="jefe", json=criterio).status_code == 422
