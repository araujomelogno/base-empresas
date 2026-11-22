"""SPEC_crear_carga_asincrona (D51): el archivo se parsea una vez al analizarlo, un archivo grande se lee en segundo
plano, «valores» y «crear» no vuelven a leerlo, y «Siguiente» dos veces no crea dos cargas."""
import os
import time

import pytest

from conftest import cargar, csv_bytes, rut_valido


def fila(i, **extra):
    return {"RUT": rut_valido(i), "Razón social": f"Empresa {i}", "Teléfono": f"2900{i:04d}", "Departamento": "Salto",
            **extra}


def cuenta(sql, tabla, where="TRUE"):
    return sql.execute(f"SELECT count(*) AS n FROM {tabla} WHERE {where}").fetchone()["n"]


def body(a, **extra):
    return {"archivo_id": a["archivo_id"], "fuente": "x", "tipo_fuente": "x", "licencia": "interna",
            "mapeo": {**a["mapeo"], "origen_defecto": "sin_dato"}, **extra}


def sin_leer(monkeypatch):
    """Desde acá, leer el archivo es un error: todo tiene que salir de las filas guardadas."""
    from app import lectores

    def leer(*a, **k):
        raise AssertionError("se volvió a leer el archivo")
    monkeypatch.setattr(lectores, "leer_tabla", leer)


# ─── A1 · Analizar ───

def test_analizar_chico_es_sincronico_y_guarda_las_filas(api, sql):
    a = api.subir("/cargas/analizar", "b.csv", csv_bytes([fila(i) for i in range(5)]), rol="steward").json()
    assert "tarea_id" not in a and a["n_filas"] == 5 and a["columnas"][0] == "RUT"
    assert [e["RUT"] for e in a["ejemplos"]] == [rut_valido(i) for i in range(5)]
    assert cuenta(sql, "archivo_fila", f"archivo_id = {a['archivo_id']}") == 5
    x = sql.execute("SELECT n_filas, columnas, filas_guardadas FROM archivo WHERE id = %s", (a["archivo_id"],)).fetchone()
    assert x["n_filas"] == 5 and x["columnas"] == ["RUT", "Razón social", "Teléfono", "Departamento"] and x["filas_guardadas"]


def test_analizar_grande_va_en_segundo_plano(api, sql, monkeypatch):
    from app import settings

    monkeypatch.setattr(settings, "ARCHIVO_FILAS_SINCRONICO", 3)
    r = api.subir("/cargas/analizar", "grande.csv", csv_bytes([fila(i) for i in range(8)]), rol="steward").json()
    assert set(r) == {"archivo_id", "nombre", "tarea_id"}          # responde enseguida, sin parsear
    t = api.get(f"/tareas/{r['tarea_id']}").json()
    assert t["tipo"] == "archivo.leer" and t["estado"] == "ok"
    a = t["resultado"]                                             # el mismo análisis de siempre
    assert a["archivo_id"] == r["archivo_id"] and a["n_filas"] == 8 and a["mapeo"]["rut"] == "RUT"
    assert "atributos" in a and "origenes" in a
    c = cargar(api, [fila(i) for i in range(8)])                   # el flujo completo, con el análisis en segundo plano
    assert c["estado"] == "confirmada" and cuenta(sql, "empresa") == 8


def test_estimar_filas_de_un_excel_sin_parsearlo():
    import io

    from openpyxl import Workbook

    from app import lectores

    wb = Workbook()
    ws = wb.active
    ws.append(["RUT", "Razón social"])
    for i in range(1234):
        ws.append([f"21{i:010d}", f"Empresa {i}"])
    buf = io.BytesIO()
    wb.save(buf)
    assert lectores.estimar_filas(buf.getvalue(), "xlsx") == 1234
    wb = Workbook(write_only=True)                     # sin la dimensión de la hoja: se cuentan las filas del XML
    ws = wb.create_sheet()
    for i in range(1235):
        ws.append([f"21{i:010d}", f"Empresa {i}"])
    buf = io.BytesIO()
    wb.save(buf)
    assert lectores.estimar_filas(buf.getvalue(), "xlsx") == 1234
    assert lectores.estimar_filas(b"a;b\n1;2\n3;4\n", "csv") == 2


# ─── A2 · Valores sin volver a leer el archivo ───

def test_valores_y_crear_no_vuelven_a_leer_el_archivo(api, sql, monkeypatch):
    filas = [fila(i, Origen=["Guía", "Web", "Guía", ""][i % 4]) for i in range(8)]
    a = api.subir("/cargas/analizar", "b.csv", csv_bytes(filas), rol="steward").json()
    sin_leer(monkeypatch)
    m = {**a["mapeo"], "origenes_telefono": {"Teléfono": {"columna": "Origen"}}, "origen_defecto": "sin_dato"}
    v = api.post("/cargas/valores", rol="steward", json={"archivo_id": a["archivo_id"], "mapeo": m}).json()
    assert {x["valor"]: x["filas"] for x in v["origen"]} == {"Guía": 4, "Web": 2} and v["pendientes"] == 2
    m["traducciones"] = {"origen": {"Guía": "sin_dato", "Web": "sin_dato"}}
    r = api.post("/cargas", rol="steward", json={**body(a), "mapeo": m})
    assert r.status_code == 200, r.text
    c = api.get(f"/cargas/{r.json()['carga_id']}").json()
    assert c["estado"] == "preview" and c["conteos"]["altas"] == 8


def test_crear_con_valores_sin_traducir_avisa_sin_leer(api, monkeypatch):
    a = api.subir("/cargas/analizar", "b.csv", csv_bytes([fila(i, Origen="Guía") for i in range(3)]), rol="steward").json()
    sin_leer(monkeypatch)
    m = {**a["mapeo"], "origenes_telefono": {"Teléfono": {"columna": "Origen"}}, "origen_defecto": "sin_dato"}
    r = api.post("/cargas", rol="steward", json={**body(a), "mapeo": m})
    assert r.status_code == 422 and "sin traducir" in r.json()["detail"]


# ─── A3 · Crear responde enseguida; los lotes los arma el preview ───

def test_crear_no_arma_lotes_y_el_preview_si(api, sql, monkeypatch):
    from app import tareas

    a = api.subir("/cargas/analizar", "b.csv", csv_bytes([fila(i) for i in range(5)]), rol="steward").json()
    monkeypatch.setattr(tareas, "despachar", lambda tid, demora=0: None)
    r = api.post("/cargas", rol="steward", json=body(a)).json()
    monkeypatch.undo()
    assert r["lotes"] is None and r["n_filas"] == 5
    assert cuenta(sql, "carga_fila", f"carga_id = {r['carga_id']}") == 0
    t = api.get(f"/tareas/{r['tarea_id']}").json()
    assert t["mensaje"] == "Creando la carga…"
    tareas.despachar(r["tarea_id"])
    c = api.get(f"/cargas/{r['carga_id']}").json()
    assert c["estado"] == "preview" and c["lotes"] == 3 and c["n_filas"] == 5
    assert sql.execute("SELECT count(*) AS n FROM carga_fila WHERE carga_id = %s AND datos IS NULL",
                       (r["carga_id"],)).fetchone()["n"] == 5          # solo el lote: los datos están en archivo_fila


def test_si_se_liberaron_las_filas_se_leen_otra_vez(api, sql):
    c = cargar(api, [fila(i) for i in range(4)], confirmar=False)
    sql.execute("DELETE FROM archivo_fila WHERE archivo_id = %s", (c["archivo_id"],))
    sql.execute("UPDATE archivo SET filas_guardadas = NULL WHERE id = %s", (c["archivo_id"],))
    assert api.post(f"/cargas/{c['id']}/confirmar", rol="steward").status_code == 200
    assert api.get(f"/cargas/{c['id']}").json()["estado"] == "confirmada" and cuenta(sql, "empresa") == 4


def test_carga_de_la_version_anterior_con_datos_en_carga_fila(api, sql):
    """Una carga creada antes de D51 tiene los datos en carga_fila (y su archivo, sin filas guardadas)."""
    c = cargar(api, [fila(i) for i in range(4)], confirmar=False)
    sql.execute("UPDATE carga_fila cf SET datos = af.datos FROM archivo_fila af"
                " WHERE af.archivo_id = %s AND af.fila = cf.fila AND cf.carga_id = %s", (c["archivo_id"], c["id"]))
    sql.execute("DELETE FROM archivo_fila WHERE archivo_id = %s", (c["archivo_id"],))
    sql.execute("UPDATE archivo SET filas_guardadas = NULL WHERE id = %s", (c["archivo_id"],))
    api.post(f"/cargas/{c['id']}/confirmar", rol="steward")
    assert api.get(f"/cargas/{c['id']}").json()["estado"] == "confirmada" and cuenta(sql, "empresa") == 4


# ─── A4 · Sin cargas duplicadas ───

def test_siguiente_dos_veces_crea_una_carga(api, sql):
    a = api.subir("/cargas/analizar", "b.csv", csv_bytes([fila(i) for i in range(3)]), rol="steward").json()
    r1 = api.post("/cargas", rol="steward", json=body(a, clave="abc-123")).json()
    r2 = api.post("/cargas", rol="steward", json=body(a, clave="abc-123")).json()
    assert r2["carga_id"] == r1["carga_id"] and r2["existente"] is True and "existente" not in r1
    assert cuenta(sql, "carga") == 1
    r3 = api.post("/cargas", rol="steward", json=body(a, clave="otra")).json()   # otra clave: otra carga
    assert r3["carga_id"] != r1["carga_id"]


def test_ir_a_la_carga_que_se_esta_creando(api, monkeypatch):
    from app import tareas

    a = api.subir("/cargas/analizar", "b.csv", csv_bytes([fila(i) for i in range(3)]), rol="steward").json()
    assert api.get("/cargas/en-curso", rol="steward", params={"archivo_id": a["archivo_id"]}).json() == {"carga": None}
    monkeypatch.setattr(tareas, "despachar", lambda tid, demora=0: None)
    cid = api.post("/cargas", rol="steward", json=body(a, clave="k1")).json()["carga_id"]
    r = api.get("/cargas/en-curso", rol="steward", params={"archivo_id": a["archivo_id"]}).json()
    assert r["carga"]["id"] == cid and r["carga"]["estado"] == "analizando"
    # otra persona no la ve como suya
    assert api.get("/cargas/en-curso", rol="admin", params={"archivo_id": a["archivo_id"]}).json() == {"carga": None}


# ─── Limpieza diaria de las filas intermedias ───

def test_limpieza_diaria_de_archivos_sin_usar(api, sql):
    usado = cargar(api, [fila(i) for i in range(3)], confirmar=False)          # en preview: se conserva
    a = api.subir("/cargas/analizar", "sin_usar.csv", csv_bytes([fila(i) for i in range(10, 13)]), rol="steward").json()
    reciente = api.subir("/cargas/analizar", "reciente.csv", csv_bytes([fila(20)]), rol="steward").json()
    sql.execute("UPDATE archivo SET filas_guardadas = now() - interval '25 hours' WHERE id <> %s", (reciente["archivo_id"],))
    r = api.c.post("/api/jobs/calidad", headers={"X-Job-Token": "token-job"}).json()
    assert r["archivos_liberados"] == 1
    assert cuenta(sql, "archivo_fila", f"archivo_id = {a['archivo_id']}") == 0
    assert cuenta(sql, "archivo_fila", f"archivo_id = {usado['archivo_id']}") == 3
    assert cuenta(sql, "archivo_fila", f"archivo_id = {reciente['archivo_id']}") == 1


def test_descartar_libera_las_filas(api, sql):
    c = cargar(api, [fila(i) for i in range(3)], confirmar=False)
    api.delete(f"/cargas/{c['id']}", rol="steward")
    assert cuenta(sql, "archivo_fila", f"archivo_id = {c['archivo_id']}") == 0


# ─── Volumen (lento: RUN_LENTOS=1) ───

@pytest.mark.skipif(not os.environ.get("RUN_LENTOS"), reason="test de volumen: correr con RUN_LENTOS=1")
def test_valores_y_crear_con_200000_filas_en_menos_de_5_s(api, sql, monkeypatch):
    a = api.subir("/cargas/analizar", "b.csv", csv_bytes([fila(i, Origen="Guía", Tamaño="Pyme") for i in range(3)]),
                  rol="steward").json()
    # 200.000 filas guardadas como si se hubieran analizado (generarlas por SQL evita parsear un archivo enorme)
    sql.execute("DELETE FROM archivo_fila WHERE archivo_id = %s", (a["archivo_id"],))
    sql.execute("""INSERT INTO archivo_fila (archivo_id, fila, datos)
                   SELECT %s, g + 1, jsonb_build_object('RUT', '21' || lpad(g::text, 10, '0'), 'Razón social', 'Empresa ' || g,
                     'Teléfono', '2' || lpad(g::text, 7, '0'), 'Departamento', 'Salto',
                     'Origen', (ARRAY['Guía', 'Web', 'Páginas', ''])[1 + g %% 4], 'Tamaño', (ARRAY['Pyme', 'Grande'])[1 + g %% 2])
                   FROM generate_series(1, 200000) g""", (a["archivo_id"],))
    sql.execute("UPDATE archivo SET n_filas = 200000 WHERE id = %s", (a["archivo_id"],))
    sql.execute("ANALYZE archivo_fila")
    from app import tareas

    m = {**a["mapeo"], "origenes_telefono": {"Teléfono": {"columna": "Origen"}}, "origen_defecto": "sin_dato"}
    t0 = time.monotonic()
    v = api.post("/cargas/valores", rol="steward", json={"archivo_id": a["archivo_id"], "mapeo": m}).json()
    t_valores = time.monotonic() - t0
    assert sum(x["filas"] for x in v["origen"]) == 150000
    m["traducciones"] = {"origen": {x["valor"]: "sin_dato" for x in v["origen"]}}
    monkeypatch.setattr(tareas, "despachar", lambda tid, demora=0: None)
    t0 = time.monotonic()
    r = api.post("/cargas", rol="steward", json={**body(a), "mapeo": m})
    t_crear = time.monotonic() - t0
    assert r.status_code == 200, r.text
    from app import lotes
    from app.db import conexion

    t0 = time.monotonic()
    with conexion() as conn:   # el primer paso del preview: repartir las filas en lotes por RUT
        c = lotes.preparar_lotes(conn, conn.execute("SELECT * FROM carga WHERE id = %s", (r.json()["carga_id"],)).fetchone())
    t_lotes = time.monotonic() - t0
    print(f"\n200.000 filas: valores {t_valores:.1f} s, crear {t_crear:.1f} s, preparar los lotes {t_lotes:.1f} s")
    assert c["n_filas"] == 200000 and cuenta(sql, "carga_fila") == 200000
    assert t_valores < 5 and t_crear < 5 and t_lotes < 60
