"""Iteración 1 — Base: R1.1 a R1.4, R1.12 y R1.13."""
import psycopg
import pytest

from conftest import cargar, csv_bytes, rut_valido


def fila(n, **kw):
    base = {"RUT": rut_valido(n), "Razón social": f"Empresa {n} SA", "Teléfono": f"2900{n:04d}",
            "Departamento": "Montevideo", "Tamaño": "Pequeña", "Naturaleza": "SA", "CIIU": "4711"}
    base.update(kw)
    return base


# ─── R1.1 Registro maestro por RUT ───

def test_rut_invalido_rechazado_con_motivo(api, sql):
    c = cargar(api, [fila(0), fila(1, RUT="210000000019"), fila(2, RUT="")])
    assert c["estado"] == "confirmada"
    assert c["conteos"]["altas"] == 1
    assert c["conteos"]["rechazos"] == 2
    motivos = {r["motivo"] for r in c["rechazos"]}
    assert "sin RUT" in motivos
    assert sql.execute("SELECT count(*) AS n FROM empresa").fetchone()["n"] == 1


def test_una_empresa_por_rut(api, sql):
    cargar(api, [fila(0)])
    cargar(api, [fila(0, **{"Razón social": "Empresa Cero SA"})])
    assert sql.execute("SELECT count(*) AS n FROM empresa").fetchone()["n"] == 1
    with pytest.raises(psycopg.errors.UniqueViolation):
        sql.execute("INSERT INTO empresa (rut) VALUES (%s)", (rut_valido(0),))


def test_historia_por_campo_y_supervivencia(api, sql):
    cargar(api, [fila(0)], confianza=50, fuente="Padrón")
    cargar(api, [fila(0, **{"Razón social": "Nombre de fuente débil"})], confianza=30, fuente="Directorio")
    e = api.get(f"/empresas/{rut_valido(0)}").json()
    assert e["razon_social"] == "Empresa 0 SA"  # gana la de mayor confianza
    hist = [h for h in e["historia"] if h["campo"] == "razon_social"]
    assert {h["valor"] for h in hist} == {"Empresa 0 SA", "Nombre de fuente débil"}
    assert all({"fuente_tipo", "fecha", "actor", "confianza"} <= set(h) for h in hist)
    # a igual confianza gana la más reciente
    cargar(api, [fila(0, **{"Razón social": "Nombre nuevo SA"})], confianza=50)
    assert api.get(f"/empresas/{rut_valido(0)}").json()["razon_social"] == "Nombre nuevo SA"


def test_dato_de_sala_no_lo_pisa_una_carga(api, sql):
    cargar(api, [fila(0)])
    eid = sql.execute("SELECT id FROM empresa").fetchone()["id"]
    sql.execute("INSERT INTO empresa_campo_historia (empresa_id, campo, valor, fuente_tipo, confianza, actor)"
                " VALUES (%s, 'estado', 'cerrada', 'sala', 10, 'encuestador')", (eid,))
    sql.execute("UPDATE empresa SET estado = 'cerrada' WHERE id = %s", (eid,))
    c = cargar(api, [fila(0, Estado="Activa")], confianza=99)
    assert api.get(f"/empresas/{rut_valido(0)}").json()["estado"] == "cerrada"
    assert c["conteos"]["conflictos"] == 1


def test_historia_es_append_only(api, sql):
    cargar(api, [fila(0)])
    with pytest.raises(psycopg.errors.RaiseException):
        sql.execute("UPDATE empresa_campo_historia SET valor = 'x'")
    with pytest.raises(psycopg.errors.RaiseException):
        sql.execute("DELETE FROM auditoria")


def test_fusion_reversible(api, sql):
    cargar(api, [fila(0), fila(1, **{"Teléfono": "099 111 222", "Razón social": None})])
    r = api.post(f"/empresas/{rut_valido(0)}/fusionar", rol="steward", json={"rut_absorbida": rut_valido(1), "motivo": "misma empresa"})
    assert r.status_code == 200, r.text
    fid = r.json()["fusion_id"]
    a = api.get(f"/empresas/{rut_valido(0)}").json()
    assert {t["e164"] for t in a["telefonos"]} == {"+59829000000", "+59899111222"}
    b = api.get(f"/empresas/{rut_valido(1)}").json()
    assert b["baja"] == "fusionada"  # el registro absorbido se guarda
    assert api.post(f"/fusiones/{fid}/deshacer", rol="steward").status_code == 200
    b = api.get(f"/empresas/{rut_valido(1)}").json()
    assert b["baja"] is None and [t["e164"] for t in b["telefonos"]] == ["+59899111222"]
    a = api.get(f"/empresas/{rut_valido(0)}").json()
    assert [t["e164"] for t in a["telefonos"]] == ["+59829000000"]


# ─── R1.2 Teléfonos e intermediarios ───

def test_telefono_normalizado_y_crudo_invalido(api, sql):
    cargar(api, [fila(0, **{"Teléfono": "098 123 456 / 12"}), fila(1, **{"Teléfono": "+598 98 123 456"})])
    tels = sql.execute("SELECT e164, tipo, estado FROM telefono ORDER BY id").fetchall()
    assert tels[0] == {"e164": "+59898123456", "tipo": "celular", "estado": "valido"}
    assert sql.execute("SELECT count(*) AS n FROM telefono WHERE e164 = '+59898123456'").fetchone()["n"] == 1
    assert sql.execute("SELECT count(*) AS n FROM telefono_vinculo").fetchone()["n"] == 2
    cargar(api, [fila(2, **{"Teléfono": "9011234"})])
    inval = sql.execute("SELECT * FROM telefono WHERE e164 IS NULL").fetchone()
    assert inval["crudo"] == "9011234" and inval["estado"] == "invalido"


def test_intermediario_sospechoso_y_resolucion(api, sql):
    compartido = "2600 0000"
    filas = [fila(i, **{"Teléfono": f"{compartido} / 2900{i:04d}"}) for i in range(5)]
    c = cargar(api, filas)
    assert c["conteos"]["nuevos_sospechosos"] == 1
    s = api.get("/telefonos/sospechosos").json()["telefonos"]
    assert len(s) == 1 and s[0]["e164"] == "+59826000000" and s[0]["n_empresas"] == 5
    # sale de toda exportación: no es discable
    assert sql.execute("SELECT count(*) AS n FROM v_vinculo_discable WHERE e164 = '+59826000000'").fetchone()["n"] == 0
    tid = s[0]["id"]
    r = api.post(f"/telefonos/{tid}/resolver", rol="steward", json={"accion": "liberar", "motivo": "central de un grupo"})
    assert r.status_code == 200
    assert sql.execute("SELECT count(*) AS n FROM v_vinculo_discable WHERE e164 = '+59826000000'").fetchone()["n"] == 5
    # un teléfono liberado no vuelve a marcarse salvo que sume RUTs nuevos
    cargar(api, [fila(0, **{"Teléfono": compartido})])
    assert sql.execute("SELECT intermediario FROM telefono WHERE id = %s", (tid,)).fetchone()["intermediario"] == "liberado"
    cargar(api, [fila(9, **{"Teléfono": compartido})])
    assert sql.execute("SELECT intermediario FROM telefono WHERE id = %s", (tid,)).fetchone()["intermediario"] == "sospechoso"
    api.post(f"/telefonos/{tid}/resolver", rol="steward", json={"accion": "confirmar"})
    estados = {r["estado"] for r in sql.execute("SELECT estado FROM telefono_vinculo WHERE telefono_id = %s", (tid,))}
    assert estados == {"intermediario"}


def test_umbral_intermediario_configurable(api, sql):
    cfg = api.get("/config").json()["parametros"]
    cfg["umbral_intermediario"] = 3
    assert api.put("/config", json={"parametros": cfg, "comentario": "umbral 3"}).status_code == 200
    c = cargar(api, [fila(i, **{"Teléfono": "2600 0000"}) for i in range(3)])
    assert c["conteos"]["nuevos_sospechosos"] == 1


# ─── R1.3 Cargas y reglas de fusión ───

def test_preview_no_escribe_y_cuenta(api, sql):
    cargar(api, [fila(0)])
    c = cargar(api, [fila(0, **{"Razón social": "Otra SA"}), fila(1), fila(2, RUT="123")], confirmar=False)
    assert c["estado"] == "preview"
    k = c["conteos"]
    assert (k["altas"], k["actualizaciones"], k["rechazos"]) == (1, 1, 1)
    assert sql.execute("SELECT count(*) AS n FROM empresa").fetchone()["n"] == 1
    assert sql.execute("SELECT razon_social FROM empresa").fetchone()["razon_social"] == "Empresa 0 SA"


def test_mapeo_sugerido_y_plantilla(api):
    contenido = csv_bytes([{"Nro RUT": rut_valido(0), "Denominación": "X SA", "Tel 1": "29001111", "Celular": "099111222"}])
    a = api.subir("/cargas/analizar", "x.csv", contenido, rol="steward", tipo_fuente="directorio").json()
    assert a["mapeo"]["rut"] == "Nro RUT" and a["mapeo"]["razon_social"] == "Denominación"
    assert a["mapeo"]["telefonos"] == ["Tel 1", "Celular"]
    a["mapeo"]["razon_social"] = None
    api.post("/cargas", rol="steward", json={"archivo_id": a["archivo_id"], "fuente": "Dir", "tipo_fuente": "directorio",
                                            "licencia": "uso interno", "mapeo": a["mapeo"]})
    b = api.subir("/cargas/analizar", "y.csv", contenido, rol="steward", tipo_fuente="directorio").json()
    assert b["origen_mapeo"] == "plantilla" and "razon_social" not in b["mapeo"]


def test_xlsx(api, sql):
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["RUT", "Razón social", "Teléfono"])
    ws.append([int(rut_valido(3)), "Planilla SA", 29003333])
    buf = io.BytesIO()
    wb.save(buf)
    c = cargar(api, [], nombre="base.xlsx", contenido=buf.getvalue())
    assert c["conteos"]["altas"] == 1
    assert sql.execute("SELECT e164 FROM telefono").fetchone()["e164"] == "+59829003333"


def test_fusion_por_telefono_va_a_revision(api, sql):
    cargar(api, [fila(0)])
    otra = fila(1, **{"Teléfono": "2900 0000"})  # mismo teléfono que la empresa 0, RUT distinto
    c = cargar(api, [otra], regla="telefono")
    assert c["conteos"]["revision"] == 1 and c["conteos"].get("altas", 0) == 0
    assert sql.execute("SELECT count(*) AS n FROM empresa").fetchone()["n"] == 1
    rev = api.get("/revision").json()
    assert rev[0]["criterio"] == "telefono" and rev[0]["candidata_rut"] == rut_valido(0)
    api.post(f"/revision/{rev[0]['id']}", rol="steward", json={"accion": "alta"})
    assert sql.execute("SELECT count(*) AS n FROM empresa").fetchone()["n"] == 2


def test_fusion_por_razon_social(api):
    cargar(api, [fila(0, **{"Razón social": "Pérez Hnos. S.A."})])
    c = cargar(api, [fila(1, **{"Razón social": "PEREZ HNOS SA", "Teléfono": None})], regla="razon_social")
    assert c["conteos"]["revision"] == 1


def test_deshacer_carga(api, sql):
    c1 = cargar(api, [fila(0)], confianza=50)
    c2 = cargar(api, [fila(0, **{"Razón social": "Cambiada SA"}), fila(1)], confianza=60)
    assert api.get(f"/empresas/{rut_valido(0)}").json()["razon_social"] == "Cambiada SA"
    r = api.delete(f"/cargas/{c2['id']}", rol="steward")
    assert r.status_code == 200, r.text
    assert r.json()["empresas_anuladas"] == 1
    assert api.get(f"/empresas/{rut_valido(0)}").json()["razon_social"] == "Empresa 0 SA"
    assert api.get(f"/empresas/{rut_valido(1)}").json()["baja"] == "anulada"
    # la historia sigue (append-only), anulada
    hist = api.get(f"/empresas/{rut_valido(0)}").json()["historia"]
    assert any(h["anulada"] for h in hist)
    assert c1["estado"] == "confirmada"


def test_no_se_deshace_si_entro_a_muestra(api, sql):
    c = cargar(api, [fila(0)])
    e = api.post("/estudios", rol="jefe", json={"nombre": "E", "campo_desde": "2026-11-01", "campo_hasta": "2026-11-30"}).json()
    m = api.post("/muestras", rol="jefe", json={"estudio_id": e["id"], "nombre": "M", "criterios": {"n_por_estrato": 1}}).json()
    api.post(f"/muestras/{m['id']}/sortear", rol="jefe", json={})
    r = api.delete(f"/cargas/{c['id']}", rol="steward")
    assert r.status_code == 409


# ─── R1.4 Exclusiones y no llamar ───

def test_naturaleza_excluida_se_guarda_pero_no_es_disponible(api, sql):
    cargar(api, [fila(0, Naturaleza="PUB"), fila(1)])
    r = api.post("/naturalezas", json={"codigo": "PUB", "nombre": "Organismo público o ente estatal", "excluida": True})
    assert r.json()["config_version"] == 2
    d = {x["rut"]: x for x in api.get("/empresas").json()["empresas"]}
    assert "naturaleza_excluida" in d[rut_valido(0)]["reglas"]
    assert d[rut_valido(1)]["disponible"]
    # se sigue actualizando
    cargar(api, [fila(0, Naturaleza="PUB", **{"Razón social": "Ente Actualizado"})], confianza=70)
    assert api.get(f"/empresas/{rut_valido(0)}").json()["razon_social"] == "Ente Actualizado"


def test_no_llamar(api, sql):
    cargar(api, [fila(0), fila(1, **{"Teléfono": "099 555 666"})])
    r = api.post("/no-llamar", json={"alcance": "empresa", "rut": rut_valido(0), "motivo": "pidió la baja",
                                     "solicitante": "Gerente"})
    assert r.status_code == 200
    api.post("/no-llamar", json={"alcance": "telefono", "telefono": "099555666", "motivo": "celular personal",
                                 "solicitante": "Titular"})
    d = {x["rut"]: x for x in api.get("/empresas").json()["empresas"]}
    assert "no_llamar" in d[rut_valido(0)]["reglas"]
    assert "sin_telefono_discable" in d[rut_valido(1)]["reglas"]
    assert api.post("/no-llamar", rol="coordinador", json={"alcance": "empresa", "rut": rut_valido(1), "motivo": "x",
                                                           "solicitante": "y"}).status_code == 403


# ─── R1.12 Configuración ───

def test_config_versionada_y_validada(api):
    c = api.get("/config").json()
    assert c["version"] == 1
    p = c["parametros"]
    p["meses_enfriamiento"] = 12
    r = api.put("/config", json={"parametros": p, "comentario": "12 meses"})
    assert r.json()["version"] == 2
    h = api.get("/config").json()["historial"]
    assert h[0]["autor"] == "admin@equipos.com.uy" and h[0]["comentario"] == "12 meses"
    assert api.get("/config/1").json()["parametros"]["meses_enfriamiento"] == 6
    p["reglas_disponibilidad"]["inventada"] = True
    assert api.put("/config", json={"parametros": p}).status_code == 422
    p.pop("reglas_disponibilidad")
    assert api.put("/config", json={"parametros": p}).status_code == 422
    assert api.put("/config", rol="jefe", json={"parametros": c["parametros"]}).status_code == 403


# ─── R1.13 Roles y auditoría ───

def test_roles(api):
    assert api.get("/me", rol="lectura").json()["rol"] == "lectura"
    assert api.post("/estudios", rol="lectura", json={"nombre": "x", "campo_desde": "2026-01-01",
                                                      "campo_hasta": "2026-01-02"}).status_code == 403
    assert api.post("/estudios", rol="coordinador", json={"nombre": "x", "campo_desde": "2026-01-01",
                                                          "campo_hasta": "2026-01-02"}).status_code == 403
    assert api.get("/usuarios", rol="steward").status_code == 403
    r = api.c.get("/api/me", headers={"X-Dev-User": "desconocido@x.com"})
    assert r.status_code == 403


def test_auditoria(api):
    cargar(api, [fila(0)])
    acciones = {a["accion"] for a in api.get("/auditoria").json()}
    assert {"carga.crear", "carga.confirmar"} <= acciones


def test_contactos_ocultos_para_lectura(api):
    cargar(api, [fila(0, Contacto="Ana Pérez", Cargo="Gerente")])
    assert api.get(f"/empresas/{rut_valido(0)}", rol="steward").json()["contactos"][0]["nombre"] == "Ana Pérez"
    assert api.get(f"/empresas/{rut_valido(0)}", rol="lectura").json()["contactos"][0]["nombre"] == "(dato personal oculto)"
