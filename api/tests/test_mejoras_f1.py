"""SPEC_mejoras_sav_contactos_atributos_identidad — Fase 1: contadores, paginación, búsqueda por ítem y clave automática."""
from conftest import rut_valido
from test_base import fila
from test_muestra import base, estudio, muestra

from conftest import cargar


def inicio(api):
    return api.get("/inicio").json()


# ─── F1.2 Contador de intermediarios ───

def test_sospechoso_retirado_al_borrar_una_empresa(api, sql):
    compartido = "2600 0000"
    cargar(api, [fila(i, **{"Teléfono": f"{compartido} / 2900{i:04d}"}) for i in range(5)])  # umbral 5
    assert inicio(api)["sospechosos"] == 1
    tid = sql.execute("SELECT id FROM telefono WHERE e164 = '+59826000000'").fetchone()["id"]
    assert api.delete(f"/empresas/{rut_valido(0)}").status_code == 200
    t = sql.execute("SELECT intermediario FROM telefono WHERE id = %s", (tid,)).fetchone()
    assert t["intermediario"] is None
    assert inicio(api)["sospechosos"] == 0
    aud = sql.execute("SELECT detalle FROM auditoria WHERE accion = 'telefono.sospechoso_retirado'").fetchone()
    assert aud and aud["detalle"]["ids"] == [tid] and aud["detalle"]["umbral"] == 5


def test_contador_usa_el_criterio_de_la_lista(api, sql):
    # un teléfono marcado sin empresas activas (datos anteriores a este cambio) no cuenta
    cargar(api, [fila(0)])
    sql.execute("UPDATE telefono SET intermediario = 'sospechoso'")
    sql.execute("UPDATE empresa SET baja = 'anulada'")
    assert inicio(api)["sospechosos"] == 0
    assert api.get("/telefonos/sospechosos").json()["telefonos"] == []


def test_confirmados_no_se_tocan_y_deshacer_reevalua(api, sql):
    compartido = "2600 0000"
    c1 = cargar(api, [fila(i, **{"Teléfono": compartido}) for i in range(3)])
    c2 = cargar(api, [fila(i, **{"Teléfono": compartido}) for i in range(3, 5)])
    tid = sql.execute("SELECT id FROM telefono WHERE e164 = '+59826000000'").fetchone()["id"]
    assert sql.execute("SELECT intermediario FROM telefono WHERE id = %s", (tid,)).fetchone()["intermediario"] == "sospechoso"
    # deshacer la segunda carga deja 3 empresas (< umbral 5): vuelve a «sin marca»
    assert api.delete(f"/cargas/{c2['id']}", rol="steward").status_code == 200
    assert sql.execute("SELECT intermediario FROM telefono WHERE id = %s", (tid,)).fetchone()["intermediario"] is None
    # uno confirmado sigue confirmado aunque se borren empresas
    cargar(api, [fila(i, **{"Teléfono": compartido}) for i in range(3, 5)])
    api.post(f"/telefonos/{tid}/resolver", rol="steward", json={"accion": "confirmar"})
    api.delete(f"/empresas/{rut_valido(4)}")
    assert sql.execute("SELECT intermediario FROM telefono WHERE id = %s", (tid,)).fetchone()["intermediario"] == "confirmado"
    assert c1["estado"] == "confirmada"


def test_fusion_reevalua_sospechosos(api, sql):
    compartido = "2600 0000"
    cargar(api, [fila(i, **{"Teléfono": compartido}) for i in range(5)])
    tid = sql.execute("SELECT id FROM telefono WHERE e164 = '+59826000000'").fetchone()["id"]
    r = api.post(f"/empresas/{rut_valido(0)}/fusionar", rol="steward", json={"rut_absorbida": rut_valido(1), "motivo": "duplicada"})
    assert r.status_code == 200, r.text
    assert sql.execute("SELECT intermediario FROM telefono WHERE id = %s", (tid,)).fetchone()["intermediario"] is None


# ─── F1.1 Muestras activas ───

def test_muestras_activas_lista_y_contador(api, sql):
    base(api, 12)
    est = estudio(api)
    m1, _ = muestra(api, est, {"n_por_estrato": 2, "reemplazos": 0}, semilla=1)
    m2, _ = muestra(api, est, {"n_por_estrato": 1, "reemplazos": 0}, semilla=2, nombre="Muestra 2")
    assert inicio(api)["muestras_activas"] == 2
    activas = api.get("/muestras", params={"estado": "activa"}).json()
    assert {m["id"] for m in activas} == {m1, m2} and all(m["n_items"] > 0 for m in activas)
    # Causa A: se borran todas las empresas de m2 → sigue activa con 0 ítems y aparece en la lista
    for rut in [r["rut"] for r in sql.execute(
            "SELECT e.rut FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id WHERE i.muestra_id = %s", (m2,))]:
        assert api.delete(f"/empresas/{rut}").status_code == 200
    sin = {m["id"]: m for m in api.get("/muestras", params={"estado": "activa"}).json()}[m2]
    assert sin["n_items"] == 0 and sin["estado"] == "activa"
    # Causa B: la tarea de borrado no terminó → el detalle lo indica
    sql.execute("INSERT INTO tarea (tipo, payload, estado, error, creado_por) VALUES"
                " ('muestra.borrar', jsonb_build_object('borrar_muestra_id', %s), 'error', 'se cortó', 'x')", (m1,))
    assert api.get(f"/muestras/{m1}").json()["borrado_fallido"]["estado"] == "error"
    assert api.get(f"/muestras/{m2}").json()["borrado_fallido"] is None
    # Borrar muestra (tarea ok) baja el contador
    assert api.delete(f"/muestras/{m2}").status_code == 200
    assert inicio(api)["muestras_activas"] == 1


# ─── F1.3 Empresas de la muestra, paginada ───

def _muestra_grande(api, sql, n=1200):
    est = estudio(api)
    mid = api.post("/muestras", rol="jefe", json={"estudio_id": est["id"], "nombre": "Grande", "criterios": {"n_por_estrato": 1, "reemplazos": 0}}).json()["id"]
    sql.execute("INSERT INTO empresa (rut, razon_social) SELECT '9' || lpad(g::text, 11, '0'), 'Empresa ' || g"
                " FROM generate_series(1, %s) g", (n,))
    sql.execute("INSERT INTO muestra_item (muestra_id, empresa_id, estrato, rol, orden, liberado)"
                " SELECT %s, id, CASE WHEN id %% 2 = 0 THEN 'Par' ELSE 'Impar' END,"
                "        CASE WHEN id %% 10 = 0 THEN 'reemplazo' ELSE 'titular' END, id, id %% 10 <> 0 FROM empresa",
                (mid,))
    sql.execute("UPDATE muestra SET estado = 'activa' WHERE id = %s", (mid,))
    return mid, est


def test_empresas_de_la_muestra_paginada(api, sql):
    mid, est = _muestra_grande(api, sql)
    vistos, pagina = set(), 1
    while True:
        r = api.get(f"/muestras/{mid}/items", params={"pagina": pagina}).json()
        assert r["total"] == 1200 and r["paginas"] == 24 and len(r["items"]) <= 50
        vistos |= {i["id"] for i in r["items"]}
        if pagina == r["paginas"]:
            break
        pagina += 1
    assert pagina == 24 and len(vistos) == 1200
    # los filtros se mantienen al cambiar de página
    f = {"estrato": "Par", "rol": "titular"}
    p1 = api.get(f"/muestras/{mid}/items", params={**f, "pagina": 1}).json()
    p2 = api.get(f"/muestras/{mid}/items", params={**f, "pagina": 2}).json()
    assert p1["total"] == 480 and p2["total"] == 480
    assert all(i["estrato"] == "Par" and i["rol"] == "titular" for i in p1["items"] + p2["items"])
    assert not {i["id"] for i in p1["items"]} & {i["id"] for i in p2["items"]}
    assert api.get(f"/muestras/{mid}/items", params={"liberado": "false"}).json()["total"] == 120
    # estado por parte: «pendiente» incluye los ítems sin estado en esa parte
    parte = est["partes"][0]["id"]
    item = p1["items"][0]["id"]
    sql.execute("INSERT INTO item_parte_estado (item_id, parte_id, estado) VALUES (%s, %s, 'completa')", (item, parte))
    r = api.get(f"/muestras/{mid}/items", params={"parte_id": parte, "estado": "completa"}).json()
    assert r["total"] == 1 and r["items"][0]["id"] == item
    assert api.get(f"/muestras/{mid}/items", params={"parte_id": parte, "estado": "pendiente"}).json()["total"] == 1199
    # búsqueda por EC_ID_ITEM, RUT y razón social
    assert api.get(f"/muestras/{mid}/items", params={"q": f"#{item}"}).json()["items"][0]["id"] == item
    assert api.get(f"/muestras/{mid}/items", params={"q": "Empresa 1199"}).json()["total"] == 1
    rut = p1["items"][0]["rut"]
    assert rut in [i["rut"] for i in api.get(f"/muestras/{mid}/items", params={"q": rut}).json()["items"]]


# ─── F1.4 Búsqueda por EC_ID_ITEM ───

def test_busqueda_por_ec_id_item(api, sql):
    base(api, 8)
    est = estudio(api)
    mid, _ = muestra(api, est, {"n_por_estrato": 1, "reemplazos": 0}, semilla=3)
    it = sql.execute("SELECT i.id, e.rut FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id"
                     " WHERE i.muestra_id = %s LIMIT 1", (mid,)).fetchone()
    for q in (f"#{it['id']}", f"item:{it['id']}", f" # {it['id']} ", f"ITEM:{it['id']}"):
        r = api.get("/empresas", params={"q": q}).json()
        assert r["item"] == it["id"] and [e["rut"] for e in r["empresas"]] == [it["rut"]], q
    assert api.get("/empresas", params={"q": "#999999"}).json()["total"] == 0
    # un número sin # sigue buscando por RUT
    r = api.get("/empresas", params={"q": it["rut"][:8]}).json()
    assert r["item"] is None and it["rut"] in [e["rut"] for e in r["empresas"]]
    # si la empresa del ítem se fusionó, lleva a la absorbente, que muestra el ítem en su pestaña Muestras
    otra = sql.execute("SELECT rut FROM empresa WHERE rut <> %s AND id NOT IN (SELECT empresa_id FROM muestra_item)"
                       " LIMIT 1", (it["rut"],)).fetchone()["rut"]
    assert api.post(f"/empresas/{otra}/fusionar", rol="steward",
                    json={"rut_absorbida": it["rut"], "motivo": "duplicada"}).status_code == 200
    r = api.get("/empresas", params={"q": f"#{it['id']}"}).json()
    assert [e["rut"] for e in r["empresas"]] == [otra]
    assert it["id"] in [m["item_id"] for m in api.get(f"/empresas/{otra}").json()["muestras"]]


# ─── F1.5 Clave automática y atributos opcionales ───

def test_clave_automatica(api):
    a = api.post("/atributos", json={"nombre": "Cantidad de empleados", "tipo": "numero"})
    assert a.status_code == 200, a.text
    assert a.json()["clave"] == "cantidad_de_empleados"
    b = api.post("/atributos", json={"nombre": "Cantidad de empleados", "tipo": "texto"}).json()
    assert b["clave"] == "cantidad_de_empleados_2"
    assert api.post("/atributos", json={"nombre": "Cantidad de empleados", "tipo": "texto"}).json()["clave"] \
        == "cantidad_de_empleados_3"
    largo = api.post("/atributos", json={"nombre": "Ñandú " * 20, "tipo": "texto"}).json()["clave"]
    assert largo.startswith("nandu_nandu") and len(largo) <= 40
    assert api.post("/atributos", json={"nombre": "Ñandú " * 20, "tipo": "texto"}).json()["clave"].endswith("_2")
    # la API sigue aceptando una clave explícita
    assert api.post("/atributos", json={"clave": "zona", "nombre": "Zona", "tipo": "texto"}).json()["clave"] == "zona"
    # la clave no cambia aunque cambie el nombre
    r = api.put(f"/atributos/{a.json()['id']}", json={"nombre": "Empleados"}).json()
    assert r["clave"] == "cantidad_de_empleados"
    # solo nombre y tipo son obligatorios
    assert api.post("/atributos", json={"tipo": "texto"}).status_code == 422
    assert api.post("/atributos", json={"nombre": "Algo"}).status_code == 422
    lista = api.post("/atributos", json={"nombre": "Rubro", "tipo": "lista"})
    assert lista.status_code == 200 and lista.json()["opciones"] == []


def test_lista_sin_opciones_se_completa_en_la_carga(api, sql):
    a = api.post("/atributos", json={"nombre": "Exporta", "tipo": "lista", "filtrable": True}).json()
    # sin opciones, ningún valor se interpreta: la carga pide traducirlo y se puede agregar la opción
    api.put(f"/atributos/{a['id']}", json={"opciones": ["Sí", "No"]})
    c = cargar(api, [fila(0, Exporta="Sí"), fila(1, Exporta="")],
               mapeo={"atributos": {"exporta": "Exporta"}})
    assert c["estado"] == "confirmada"
    v = sql.execute("SELECT valor_texto FROM empresa_atributo").fetchall()
    assert [x["valor_texto"] for x in v] == ["Sí"]
