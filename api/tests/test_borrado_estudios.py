"""Borrar estudios y muestras, borrar cargas en cualquier estado y verificar la reproducibilidad
después de borrados (SPEC_borrado_estudios_muestras_y_cargas_en_curso, E1–E4 y V1)."""
import threading
import time

from conftest import cargar, csv_bytes, rut_valido
from test_base import fila
from test_borrado import borrar_carga, cuenta
from test_campo import fila_sav, hacer_sav, ingerir, lote, preparar
from test_muestra import estudio, muestra

LLAMADA = {"cdr_id": "1", "inicio": "2026-10-26T11:00:00-03:00", "destino": "29000000", "duracion": 30}


def tarea(api, tid):
    return api.get(f"/tareas/{tid}").json()


def borrar(api, url, rol="admin"):
    r = api.delete(url, rol=rol)
    assert r.status_code == 200, r.text
    t = tarea(api, r.json()["tarea_id"])
    assert t["estado"] == "ok", t
    return t["resultado"]


def con_campo(api, sql, n=4):
    """Muestra con una llamada del CDR y una respuesta del .sav (completa, con contacto y teléfono nuevo)."""
    e, mid, items = preparar(api, sql, n=n)
    lote(api, [LLAMADA])
    ingerir(api, e["partes"][0]["id"], hacer_sav([fila_sav(101, items[0], EC_TEL_USADO="29000000", EC_RESP_NOMBRE="Ana Pérez",
                                                           EC_RESP_CARGO="Gerente", EC_TEL_ALT="099123456")]))
    return e, mid, items


# ─── E1 · Borrar muestra ───

def test_borrar_muestra_conserva_lo_aprendido_y_libera_empresas(api, sql):
    e, mid, items = con_campo(api, sql)
    rut0 = items[0]["rut"]
    antes = api.get(f"/empresas/{rut0}").json()
    assert antes["ultimo_contacto_efectivo"] and antes["contactos"]
    assert {t["e164"] for t in antes["telefonos"]} >= {"+59899123456"}
    # vista previa y permisos
    c = api.get(f"/muestras/{mid}/borrado").json()
    assert (c["items"], c["intentos"], c["filas_sav"]) == (4, 1, 1)
    assert api.get(f"/muestras/{mid}/borrado", rol="jefe").status_code == 403
    assert api.delete(f"/muestras/{mid}", rol="jefe").status_code == 403
    r = borrar(api, f"/muestras/{mid}")
    assert (r["items"], r["intentos"], r["filas_sav"]) == (4, 1, 1)
    assert api.get(f"/muestras/{mid}").status_code == 404
    assert cuenta(sql, "muestra_item") == 0 and cuenta(sql, "intento") == 0 and cuenta(sql, "sav_fila") == 0
    assert cuenta(sql, "marco_snapshot") == 0 and cuenta(sql, "marco_snapshot_item") == 0
    # Lo aprendido por el campo se conserva: contacto, teléfono alternativo, historia y enfriamiento
    despues = api.get(f"/empresas/{rut0}").json()
    assert despues["ultimo_contacto_efectivo"] == antes["ultimo_contacto_efectivo"]
    assert [k["nombre"] for k in despues["contactos"]] == [k["nombre"] for k in antes["contactos"]]
    assert {t["e164"] for t in despues["telefonos"]} == {t["e164"] for t in antes["telefonos"]}
    assert len(despues["historia"]) == len(antes["historia"])
    # Las empresas vuelven a estar disponibles, salvo la que está en enfriamiento
    marco = api.post("/muestras/marco", rol="jefe", json={"n_por_estrato": 0}).json()
    assert marco["marco"] == 3 and marco["exclusiones"].get("enfriamiento") == 1
    assert "muestra_activa" not in marco["exclusiones"]
    a = sql.execute("SELECT * FROM auditoria WHERE accion = 'muestra.borrar'").fetchone()
    assert a["objeto_id"] == str(mid) and a["detalle"]["estudio_id"] == e["id"] and a["detalle"]["semilla"]


def test_borrar_muestra_en_borrador_y_cerrada(api, sql):
    preparar(api, sql, n=2)
    e = estudio(api)
    m = api.post("/muestras", rol="jefe", json={"estudio_id": e["id"], "nombre": "B", "criterios": {"n_por_estrato": 1}}).json()
    assert borrar(api, f"/muestras/{m['id']}")["items"] == 0
    mid, _ = muestra(api, e, {"n_por_estrato": 1}, nombre="C")
    api.post(f"/muestras/{mid}/cerrar", rol="jefe")
    assert borrar(api, f"/muestras/{mid}")["estado"] == "cerrada"


# ─── E2 · Borrar estudio ───

def test_borrar_estudio_completo(api, sql):
    e, mid, items = con_campo(api, sql)
    rut0, rut1 = items[0]["rut"], items[1]["rut"]
    # otra ingesta: la sala informa que la empresa 1 cerró (deja historia con fuente «sala»)
    ingerir(api, e["partes"][1]["id"], hacer_sav([fila_sav(201, items[1], EC_CALIDAD_TEL=4, EC_RESULTADO=2)]))
    contactos = api.get(f"/empresas/{rut0}").json()["contactos"]
    c = api.get(f"/estudios/{e['id']}/borrado").json()
    assert (c["muestras"], c["partes"], c["ingestas_sav"], c["filas_sav"], c["intentos"]) == (1, 2, 2, 2, 1)
    assert api.delete(f"/estudios/{e['id']}", rol="jefe").status_code == 403
    r = borrar(api, f"/estudios/{e['id']}")
    assert r["muestras"] == ["Muestra 1"] and r["ingestas_sav"] == 2 and r["archivos"] == 2
    assert api.get(f"/estudios/{e['id']}").status_code == 404
    assert all(x["id"] != e["id"] for x in api.get("/estudios").json())
    for t in ("parte", "sav_ingesta", "sav_fila", "muestra", "muestra_item", "intento"):
        assert cuenta(sql, t) == 0, t
    assert cuenta(sql, "archivo a JOIN sav_ingesta s ON s.archivo_id = a.id") == 0
    assert cuenta(sql, "archivo") == 1                        # queda solo el de la carga
    ficha = api.get(f"/empresas/{rut0}").json()
    assert ficha["contactos"] == contactos and ficha["ultimo_contacto_efectivo"]
    f1 = api.get(f"/empresas/{rut1}").json()
    assert f1["estado"] == "cerrada"                           # lo aprendido por el campo se conserva
    sala = [h for h in f1["historia"] if h["fuente_tipo"] in ("sala", "sav")]
    assert sala and all(h["ingesta_borrada"] for h in sala)    # el linaje sigue, la ficha no falla
    assert sql.execute("SELECT * FROM auditoria WHERE accion = 'estudio.borrar'").fetchone()["objeto_id"] == str(e["id"])


def test_borrar_estudio_vacio(api, sql):
    r = api.post("/estudios", rol="jefe", json={"nombre": "Prueba", "campo_desde": "2026-10-01", "campo_hasta": "2026-10-31"})
    eid = r.json()["id"]
    assert borrar(api, f"/estudios/{eid}")["muestras"] == []
    assert api.get(f"/estudios/{eid}").status_code == 404
    assert cuenta(sql, "auditoria", "accion = 'estudio.borrar'") == 1


def test_borrar_estudio_cancela_la_ingesta_pendiente(api, sql, monkeypatch):
    from app import tareas

    e, mid, items = preparar(api, sql, n=2)
    parte = e["partes"][0]["id"]
    a = api.subir(f"/partes/{parte}/sav/analizar", "r.sav", hacer_sav([fila_sav(1, items[0])]), rol="coordinador").json()
    monkeypatch.setattr(tareas, "despachar", lambda tid: None)       # Cloud Tasks no la ejecuta
    r = api.post(f"/partes/{parte}/sav", rol="coordinador", json={"ingesta_id": a["ingesta_id"], "mapeo": a["mapeo"]})
    tid = r.json()["tarea_id"]
    monkeypatch.undo()
    borrar(api, f"/estudios/{e['id']}")
    assert tarea(api, tid)["estado"] == "cancelada"
    assert tareas.ejecutar(tid) is None                           # si llega tarde, no hace nada
    assert cuenta(sql, "sav_ingesta") == 0


# ─── E3 · Borrar cargas en cualquier estado ───

def carga_sin_ejecutar(api, monkeypatch, filas, confirmar=False):
    """Carga cuya tarea quedó pendiente (Cloud Tasks caído). confirmar=True: el preview corre y la
    confirmación queda pendiente («en proceso»)."""
    from app import tareas

    if confirmar:
        c = cargar(api, filas, confirmar=False)
        monkeypatch.setattr(tareas, "despachar", lambda tid: None)
        tid = api.post(f"/cargas/{c['id']}/confirmar", rol="steward").json()["tarea_id"]
    else:
        monkeypatch.setattr(tareas, "despachar", lambda tid: None)
        a = api.subir("/cargas/analizar", "b.csv", csv_bytes(filas), rol="steward").json()
        r = api.post("/cargas", rol="steward", json={"archivo_id": a["archivo_id"], "fuente": "x", "tipo_fuente": "x",
                                                     "licencia": "interna", "mapeo": {**a["mapeo"], "origen_defecto": "sin_dato"}})
        c, tid = {"id": r.json()["carga_id"]}, r.json()["tarea_id"]
    monkeypatch.undo()
    return c["id"], tid


def test_borrar_carga_analizando_con_tarea_pendiente(api, sql, monkeypatch):
    from app import tareas

    cid, tid = carga_sin_ejecutar(api, monkeypatch, [fila(0)])
    assert api.get(f"/cargas/{cid}").json()["estado"] == "analizando"
    c = api.get(f"/cargas/{cid}/borrado").json()
    assert [t["id"] for t in c["tareas_a_cancelar"]] == [tid]
    borrar_carga(api, cid)
    assert api.get(f"/cargas/{cid}").status_code == 404
    assert tarea(api, tid)["estado"] == "cancelada"
    assert tareas.ejecutar(tid) is None and cuenta(sql, "empresa") == 0


def test_borrar_carga_en_proceso_con_tarea_huerfana(api, sql, monkeypatch):
    cid, tid = carga_sin_ejecutar(api, monkeypatch, [fila(0), fila(1)], confirmar=True)
    sql.execute("UPDATE tarea SET estado = 'corriendo' WHERE id = %s", (tid,))   # la instancia murió
    assert api.get(f"/cargas/{cid}").json()["estado"] == "en_proceso"
    t0 = time.monotonic()
    borrar_carga(api, cid)
    assert time.monotonic() - t0 < 10                                            # no espera nada
    assert tarea(api, tid)["estado"] == "cancelada"
    assert cuenta(sql, "carga") == 0 and cuenta(sql, "empresa") == 0


def test_cancelar_confirmacion_que_esta_corriendo(api, sql, monkeypatch):
    """La confirmación de una carga grande corre en otro hilo; se borra la carga a mitad de camino:
    la confirmación se detiene sin aplicar nada y la carga termina borrada."""
    from app import tareas

    filas = [{"RUT": rut_valido(i), "Razón social": f"Empresa {i}", "Teléfono": f"29{i:06d}"} for i in range(2500)]
    cid, tid = carga_sin_ejecutar(api, monkeypatch, filas, confirmar=True)
    hilo = threading.Thread(target=tareas.ejecutar, args=(tid,))
    hilo.start()
    limite = time.monotonic() + 60
    while sql.execute("SELECT progreso FROM tarea WHERE id = %s", (tid,)).fetchone()["progreso"] < 200:
        assert time.monotonic() < limite, "la confirmación no avanzó"
        time.sleep(0.05)
    assert hilo.is_alive()
    res = borrar_carga(api, cid)         # cancela y espera a que la confirmación suelte la carga
    hilo.join(60)
    assert not hilo.is_alive()
    assert tarea(api, tid)["estado"] == "cancelada"
    assert res["empresas_borradas"] == 0                     # la confirmación no dejó nada que borrar
    assert cuenta(sql, "empresa") == 0 and cuenta(sql, "empresa_campo_historia") == 0
    assert cuenta(sql, "telefono_vinculo") == 0 and cuenta(sql, "carga") == 0


def test_progreso_sin_cancelacion_no_cambia(api, sql):
    c = cargar(api, [fila(i) for i in range(5)])
    assert c["estado"] == "confirmada" and c["tarea"]["estado"] == "ok"


# ─── V1 · Verificar reproducibilidad con borrados ───

def test_verificar_con_empresa_borrada(api, sql):
    e, mid, items = preparar(api, sql, n=6)
    assert api.post(f"/muestras/{mid}/verificar").json()["resultado"] == "reproducible"
    snap = cuenta(sql, "marco_snapshot_item")
    titular = sql.execute("SELECT e.rut FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id"
                          " WHERE i.muestra_id = %s AND i.rol = 'titular' ORDER BY i.orden LIMIT 1", (mid,)).fetchone()["rut"]
    assert api.delete(f"/empresas/{titular}").status_code == 200
    assert cuenta(sql, "marco_snapshot_item") == snap               # el marco congelado no se toca
    v = api.post(f"/muestras/{mid}/verificar").json()
    assert v["reproducible"] and v["resultado"] == "reproducible_con_borrados"
    assert [(b["rut"], b["accion"]) for b in v["items_borrados"]] == [(titular, "empresa.borrar")]
    assert api.get(f"/muestras/{mid}").json()["n_items_borrados"] == 1


def test_verificar_con_carga_borrada(api, sql):
    cargar(api, [fila(i) for i in range(4)], tipo_fuente="a")
    c2 = cargar(api, [fila(i) for i in range(10, 13)], tipo_fuente="b")
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 7}, semilla=5)
    borrar_carga(api, c2["id"])
    v = api.post(f"/muestras/{mid}/verificar").json()
    assert v["resultado"] == "reproducible_con_borrados" and len(v["items_borrados"]) == 3
    assert {b["carga_id"] for b in v["items_borrados"]} == {str(c2["id"])}


def test_verificar_detecta_alteracion_real(api, sql):
    e, mid, items = preparar(api, sql, n=6)
    a, b = sql.execute("SELECT id, orden FROM muestra_item WHERE muestra_id = %s ORDER BY orden LIMIT 2", (mid,)).fetchall()
    sql.execute("UPDATE muestra_item SET orden = -1 WHERE id = %s", (a["id"],))
    sql.execute("UPDATE muestra_item SET orden = %s WHERE id = %s", (a["orden"], b["id"]))
    sql.execute("UPDATE muestra_item SET orden = %s WHERE id = %s", (b["orden"], a["id"]))
    v = api.post(f"/muestras/{mid}/verificar").json()
    assert not v["reproducible"] and v["resultado"] == "no_coincide"


def test_verificar_snapshot_incompleto(api, sql):
    e, mid, items = preparar(api, sql, n=4)
    sql.execute("DELETE FROM marco_snapshot_item WHERE empresa_id = %s", (items[0]["empresa_id"],))  # versión anterior
    v = api.post(f"/muestras/{mid}/verificar").json()
    assert v["snapshot_incompleto"] and v["resultado"] == "no_verificable"


def test_borrar_muestra_borra_sus_items_borrados(api, sql):
    e, mid, items = preparar(api, sql, n=4)
    api.delete(f"/empresas/{items[0]['rut']}")
    assert cuenta(sql, "muestra_item_borrado") == 1
    borrar(api, f"/muestras/{mid}")
    assert cuenta(sql, "muestra_item_borrado") == 0
