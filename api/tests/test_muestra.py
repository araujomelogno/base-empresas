"""Iteración 2 — Muestra: R1.5, R1.6 y R1.7 (más el control de exclusiones del R1.4)."""
import csv
import io

from conftest import cargar, rut_valido


def base(api, n=40, **extra):
    filas = []
    for i in range(n):
        filas.append({"RUT": rut_valido(i), "Razón social": f"Empresa {i}", "Teléfono": f"2900{i:04d} / 099{i:06d}",
                      "Tamaño": "Grande" if i % 4 == 0 else "Pyme", "Departamento": "Montevideo" if i % 2 else "Canelones",
                      "Naturaleza": "SA", "CIIU": "4711" if i % 3 else "5610", "Contacto": f"Persona {i}",
                      "Cargo": "Gerente RRHH" if i % 2 else "Contador"})
    return cargar(api, filas, **extra)


def estudio(api, partes=None):
    partes = partes or [{"nombre": "Parte A", "survey_id": "8000001", "link_base": "https://s.alchemer.com/s3/8000001/a",
                         "respondente_objetivo": "RRHH"},
                        {"nombre": "Parte B", "survey_id": "8000002", "link_base": "https://s.alchemer.com/s3/8000002/b?lang=es"}]
    r = api.post("/estudios", rol="jefe", json={"nombre": "Clima 2026", "cliente": "Cliente X", "campo_desde": "2026-10-01",
                                                "campo_hasta": "2026-12-31", "partes": partes})
    assert r.status_code == 200, r.text
    return api.get(f"/estudios/{r.json()['id']}").json()


def muestra(api, est, criterios, semilla=None, nombre="Muestra 1"):
    m = api.post("/muestras", rol="jefe", json={"estudio_id": est["id"], "nombre": nombre, "criterios": criterios})
    assert m.status_code == 200, m.text
    r = api.post(f"/muestras/{m.json()['id']}/sortear", rol="jefe", json={"semilla": semilla})
    assert r.status_code == 200, r.text
    return m.json()["id"], r.json()


# ─── R1.5 Estudios y partes ───

def test_estudio_con_partes(api):
    e = estudio(api)
    assert [p["nombre"] for p in e["partes"]] == ["Parte A", "Parte B"]
    assert e["partes"][0]["survey_id"] == "8000001"
    r = api.post(f"/estudios/{e['id']}/partes", rol="jefe", json={"nombre": "Parte C", "survey_id": "3"})
    assert r.status_code == 200


# ─── R1.6 Sorteo ───

def test_sorteo_estratificado_con_reemplazos(api, sql):
    base(api)
    e = estudio(api)
    mid, r = muestra(api, e, {"estratificar_por": ["tamano"],
                              "estratos": [{"estrato": "Grande", "n": 4, "reemplazos": 2},
                                           {"estrato": "Pyme", "n": 10, "reemplazos": 5}]}, semilla=123)
    assert r["semilla"] == 123 and r["config_version"] == 1 and r["snapshot_id"]
    items = sql.execute("SELECT estrato, rol, liberado FROM muestra_item WHERE muestra_id = %s", (mid,)).fetchall()
    assert sum(1 for i in items if i["estrato"] == "Grande" and i["rol"] == "titular") == 4
    assert sum(1 for i in items if i["estrato"] == "Pyme" and i["rol"] == "reemplazo") == 5
    assert all(i["liberado"] == (i["rol"] == "titular") for i in items)
    # cada titular liberado tiene estado pendiente en cada parte
    n = sql.execute("SELECT count(*) AS n FROM item_parte_estado ps JOIN muestra_item i ON i.id = ps.item_id"
                    " WHERE i.muestra_id = %s", (mid,)).fetchone()["n"]
    assert n == 14 * 2


def test_sorteo_reproducible(api, sql):
    base(api)
    e = estudio(api)
    mid, _ = muestra(api, e, {"estratificar_por": ["departamento"], "n_por_estrato": 5, "reemplazos_por_estrato": 3})
    v = api.post(f"/muestras/{mid}/verificar").json()
    assert v["reproducible"] is True and v["items"] == 16
    # aunque la base cambie después, el snapshot reproduce la misma lista
    base(api, n=60)
    assert api.post(f"/muestras/{mid}/verificar").json()["reproducible"] is True


def test_misma_semilla_mismo_resultado_en_otra_base(api, sql):
    base(api)
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 8}, semilla=777)
    lista1 = [r["empresa_id"] for r in sql.execute("SELECT empresa_id FROM muestra_item WHERE muestra_id = %s ORDER BY orden", (mid,))]
    api.post(f"/muestras/{mid}/cerrar", rol="jefe")
    mid2, _ = muestra(api, e, {"n_por_estrato": 8}, semilla=777, nombre="Muestra 2")
    lista2 = [r["empresa_id"] for r in sql.execute("SELECT empresa_id FROM muestra_item WHERE muestra_id = %s ORDER BY orden", (mid2,))]
    assert lista1 == lista2


def test_exclusiones_por_regla_y_aviso(api, sql):
    base(api, n=12)
    api.post("/naturalezas", json={"codigo": "SA", "nombre": "Sociedad anónima", "excluida": False})
    api.post("/no-llamar", json={"alcance": "empresa", "rut": rut_valido(1), "motivo": "baja", "solicitante": "x"})
    sql.execute("UPDATE empresa SET ultimo_contacto_efectivo = now() - interval '1 month' WHERE rut = %s", (rut_valido(2),))
    e = estudio(api)
    mid, r = muestra(api, e, {"estratificar_por": ["tamano"], "estratos": [{"estrato": "Grande", "n": 10, "reemplazos": 0}]})
    assert r["exclusiones"]["no_llamar"] == 1
    assert r["exclusiones"]["enfriamiento"] == 1
    assert any("no alcanza" in a for a in r["avisos"])
    assert r["universo"] == 12


def test_bloqueo_por_muestra_activa(api, sql):
    base(api, n=10)
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 6, "reemplazos_por_estrato": 2})
    mid2, r2 = muestra(api, e, {"n_por_estrato": 6}, nombre="Otra")
    assert r2["exclusiones"]["muestra_activa"] == 8
    ids1 = {r["empresa_id"] for r in sql.execute("SELECT empresa_id FROM muestra_item WHERE muestra_id = %s", (mid,))}
    ids2 = {r["empresa_id"] for r in sql.execute("SELECT empresa_id FROM muestra_item WHERE muestra_id = %s", (mid2,))}
    assert not ids1 & ids2


def test_liberar_reemplazos_en_orden(api, sql):
    base(api)
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 5, "reemplazos_por_estrato": 4})
    orden = [r["id"] for r in sql.execute("SELECT id FROM muestra_item WHERE muestra_id = %s AND rol = 'reemplazo'"
                                          " ORDER BY orden", (mid,))]
    r = api.post(f"/muestras/{mid}/liberar", rol="jefe", json={"estrato": "Total", "cantidad": 2, "motivo": "rechazos"})
    assert r.json()["items"] == orden[:2]
    lib = sql.execute("SELECT liberado_por, liberado_motivo FROM muestra_item WHERE id = %s", (orden[0],)).fetchone()
    assert lib == {"liberado_por": "jefe@equipos.com.uy", "liberado_motivo": "rechazos"}
    assert api.post(f"/muestras/{mid}/liberar", rol="coordinador",
                    json={"estrato": "Total", "cantidad": 1, "motivo": "x"}).status_code == 403


# ─── R1.7 CSV ───

def leer_csv(r):
    return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))


def test_csv_ucontact(api, sql):
    base(api, n=10)
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 3})
    parte = e["partes"][0]
    r = api.get(f"/muestras/{mid}/csv?parte_id={parte['id']}", rol="coordinador")
    assert r.status_code == 200
    filas = leer_csv(r)
    assert len(filas) == 6  # 3 empresas × 2 teléfonos
    f = filas[0]
    assert set(f) == {"id_item", "telefono", "rut", "razon_social", "contacto", "link"}
    assert "EC_ID_ITEM=" + f["id_item"] in f["link"] and "EC_RUT=" + f["rut"] in f["link"]
    assert "EC_TEL_USADO=598" in f["link"]
    assert f["contacto"].startswith("Persona")
    # parte con link que ya tiene query string
    r2 = leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={e['partes'][1]['id']}", rol="coordinador"))
    assert "?lang=es&EC_ID_ITEM=" in r2[0]["link"]
    assert any(a["accion"] == "muestra.exportar_csv" for a in api.get("/auditoria").json())


def test_csv_sin_permiso_de_contactos(api, sql):
    base(api, n=6)
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 2})
    r = api.get(f"/muestras/{mid}/csv?parte_id={e['partes'][0]['id']}", rol="jefe")
    assert r.headers["X-Contactos-Incluidos"] == "0"
    assert all(f["contacto"] == "" for f in leer_csv(r))


def test_csv_excluye_telefonos_no_discables(api, sql):
    base(api, n=4)
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 4})
    # después del sorteo: un teléfono pasa a no corresponde, otro a no llamar, otro a intermediario
    sql.execute("UPDATE telefono_vinculo SET estado = 'no_corresponde' WHERE telefono_id = (SELECT id FROM telefono WHERE e164 = '+59829000000')")
    sql.execute("INSERT INTO no_llamar (alcance, objeto_id, motivo, solicitante, registrado_por)"
                " SELECT 'telefono', id, 'pidió', 'x', 'y' FROM telefono WHERE e164 = '+59829000001'")
    sql.execute("UPDATE telefono SET intermediario = 'sospechoso' WHERE e164 = '+59829000002'")
    sql.execute("UPDATE telefono_vinculo SET estado = 'inexistente' WHERE telefono_id = (SELECT id FROM telefono WHERE e164 = '+59829000003')")
    tels = {f["telefono"] for f in leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={e['partes'][0]['id']}", rol="coordinador"))}
    assert tels == {"099000000", "099000001", "099000002", "099000003"}


def test_formato_csv_configurable(api):
    base(api, n=3)
    p = api.get("/config").json()["parametros"]
    p["csv_ucontact"] = {"separador": ",", "columnas": [{"columna": "PHONE", "campo": "tel_sin_mas"},
                                                        {"columna": "DATA", "campo": "id_item"}]}
    api.put("/config", json={"parametros": p})
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 1})
    txt = api.get(f"/muestras/{mid}/csv?parte_id={e['partes'][0]['id']}", rol="coordinador").content.decode("utf-8-sig")
    assert txt.splitlines()[0] == "PHONE,DATA" and txt.splitlines()[1].startswith("598")


# ─── Control automático: excluidas, no llamar y enfriamiento nunca en muestras ni en CSV ───

def test_excluidas_nunca_en_marco_ni_csv(api, sql):
    """Métrica de la fase 1: cero empresas excluidas, en no llamar o en enfriamiento dentro de muestras."""
    filas = [{"RUT": rut_valido(i), "Razón social": f"E{i}", "Teléfono": f"2900{i:04d}",
              "Naturaleza": "PUB" if i < 10 else "SA"} for i in range(40)]
    cargar(api, filas)
    api.post("/naturalezas", json={"codigo": "PUB", "nombre": "Organismo público", "excluida": True})
    for i in range(10, 15):
        api.post("/no-llamar", json={"alcance": "empresa", "rut": rut_valido(i), "motivo": "baja", "solicitante": "x"})
    sql.execute("UPDATE empresa SET ultimo_contacto_efectivo = now() - interval '2 months' WHERE rut = ANY(%s)",
                ([rut_valido(i) for i in range(15, 20)],))
    prohibidas = {rut_valido(i) for i in range(20)}
    e = estudio(api)
    mid, r = muestra(api, e, {"n_por_estrato": 40})
    assert r["marco"] == 20
    sorteadas = {x["rut"] for x in sql.execute(
        "SELECT e.rut FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id WHERE i.muestra_id = %s", (mid,))}
    assert not sorteadas & prohibidas
    # si una regla aparece después del sorteo, el CSV igual la respeta
    api.post("/no-llamar", json={"alcance": "empresa", "rut": rut_valido(25), "motivo": "baja", "solicitante": "x"})
    csv_ruts = {f["rut"] for f in leer_csv(api.get(f"/muestras/{mid}/csv?parte_id={e['partes'][0]['id']}", rol="coordinador"))}
    assert not csv_ruts & (prohibidas | {rut_valido(25)})
    assert len(csv_ruts) == 19
