"""SPEC_descubrimiento_que_aporta (D58): qué aporta cada coincidencia del descubrimiento, antes y después de confirmar.
Google Places se simula: ningún test hace llamadas pagas."""
from conftest import cargar, rut_valido
from test_fase2 import Falso, claves, configurar, lugar

from app import descubrimiento, enriquecimiento as enr

# Lo que el preview dice y lo que pasó al confirmar, con los nombres de cada lado (A3)
REAL = {"nuevo": "nuevo", "igual": "igual", "reemplaza": "reemplazo", "solo_historia": "historia", "sin_dato": None}
REAL_TEL = {"nuevo": "nuevo", "igual": "ya_tenia", "sin_dato": None}


def buscar(api, monkeypatch, lugares, consulta="imprentas en Salto"):
    claves(api, "google_places")
    Falso(monkeypatch, places={consulta: lugares})
    est = api.post("/descubrimiento/estimar", rol="steward", json={"consulta": consulta}).json()
    r = api.post(f"/descubrimiento/{est['id']}/buscar", rol="steward")
    assert r.status_code == 200, r.text
    return est["id"], r.json()["resultado"]


def aporte(fila, dato):
    return next(a for a in fila["aporta"] if a["dato"] == dato)


def coincide_con_lo_confirmado(prev, conf):
    """El preview anticipó exactamente lo que pasó (criterio de aceptación)."""
    por_i = {d["i"]: d for d in conf["detalle"]}
    for f in prev["resultados"]:
        if f["i"] not in por_i:
            continue
        d = por_i[f["i"]]
        assert REAL_TEL[aporte(f, "telefono")["estado"]] == d["telefono"], (f, d)
        assert REAL[aporte(f, "web")["estado"]] == d["web"], (f, d)
        assert REAL[aporte(f, "direccion")["estado"]] == d["direccion"], (f, d)


def test_no_aporta_nada_queda_en_no_guardar(api, sql, monkeypatch):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Imprenta Salteña SA", "Teléfono": "47331111",
                  "Web": "http://imprentasaltena.com.uy", "Dirección": "Avda. Uruguay 100, Salto", "Departamento": "Salto"}])
    cid, prev = buscar(api, monkeypatch, [lugar("Imprenta Salteña", tel="4733 1111", pid="p1",
                                                web="https://www.imprentasaltena.com.uy/", direccion="Avenida Uruguay 100, Salto")])
    f = prev["resultados"][0]
    assert f["caso"] == "coincide" and f["regla"] == "telefono"
    assert {a["dato"]: a["estado"] for a in f["aporta"]} == {"telefono": "igual", "web": "igual", "direccion": "igual",
                                                              "place_id": "nuevo"}
    assert f["aporta_algo"] is False and f["marcada"] is False   # regla exacta, pero no aporta: «No guardar»
    assert prev["resumen"]["coincide"] == 1 and prev["resumen"]["aportan"] == 0
    # Completarla igual: nada cambia y el detalle lo dice
    r = api.post(f"/descubrimiento/{cid}/confirmar", rol="steward", json={"seleccion": {"0": "completar"}})
    conf = r.json()["resultado"]["confirmado"]
    assert conf["completadas"] == 1 and conf["sin_cambios"] == 1 and conf["telefonos"] == 0
    assert conf["detalle"] == [{"i": 0, "empresa_id": f["empresa"]["id"], "telefono": "ya_tenia", "web": "igual",
                                "direccion": "igual"}]
    coincide_con_lo_confirmado(prev, conf)


def test_sitio_nuevo_queda_en_completar(api, sql, monkeypatch):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Imprenta Salteña SA", "Teléfono": "47331111", "Departamento": "Salto"}])
    cid, prev = buscar(api, monkeypatch, [lugar("Imprenta Salteña", tel="47331111", pid="p1", web="https://www.salt.com.uy")])
    f = prev["resultados"][0]
    assert aporte(f, "web")["estado"] == "nuevo" and aporte(f, "direccion")["estado"] == "sin_dato"
    assert f["aporta_algo"] and f["marcada"] and prev["resumen"]["aportan"] == 1
    conf = api.post(f"/descubrimiento/{cid}/confirmar", rol="steward", json={}).json()["resultado"]["confirmado"]
    assert conf["detalle"][0]["web"] == "nuevo" and conf["sin_cambios"] == 0
    assert sql.execute("SELECT web FROM empresa").fetchone()["web"] == "https://www.salt.com.uy"
    coincide_con_lo_confirmado(prev, conf)


def test_direccion_de_la_sala_queda_solo_en_la_historia(api, sql, monkeypatch):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Imprenta Salteña SA", "Teléfono": "47331111", "Departamento": "Salto"}])
    eid = sql.execute("SELECT id FROM empresa").fetchone()["id"]
    sql.execute("INSERT INTO empresa_campo_historia (empresa_id, campo, valor, fuente_tipo, fuente_id, confianza, actor)"
                " VALUES (%s, 'direccion', 'Larrañaga 455, Salto', 'sala', NULL, 80, 'sala')", (eid,))
    sql.execute("UPDATE empresa SET direccion = 'Larrañaga 455, Salto' WHERE id = %s", (eid,))
    cid, prev = buscar(api, monkeypatch, [lugar("Imprenta Salteña", tel="47331111", pid="p1", direccion="Artigas 1200, Salto")])
    d = aporte(prev["resultados"][0], "direccion")
    assert d["estado"] == "solo_historia" and d["actual"] == "Larrañaga 455, Salto" and "sala" in d["motivo"]
    assert prev["resultados"][0]["aporta_algo"] is False
    conf = api.post(f"/descubrimiento/{cid}/confirmar", rol="steward",
                    json={"seleccion": {"0": "completar"}}).json()["resultado"]["confirmado"]
    assert conf["detalle"][0]["direccion"] == "historia"
    assert sql.execute("SELECT direccion FROM empresa").fetchone()["direccion"] == "Larrañaga 455, Salto"
    assert sql.execute("SELECT count(*) AS n FROM empresa_campo_historia WHERE campo = 'direccion'"
                       " AND fuente_tipo = 'descubrimiento'").fetchone()["n"] == 1
    coincide_con_lo_confirmado(prev, conf)


def test_direccion_de_una_carga_reemplazada_por_fecha(api, sql, monkeypatch):
    configurar(api, confianza=50)   # misma confianza que la carga: gana la más reciente
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Imprenta Salteña SA", "Teléfono": "47331111",
                  "Dirección": "Larrañaga 455, Salto", "Departamento": "Salto"}])
    cid, prev = buscar(api, monkeypatch, [lugar("Imprenta Salteña", tel="47331111", pid="p1", direccion="Artigas 1200, Salto")])
    f = prev["resultados"][0]
    assert aporte(f, "direccion")["estado"] == "reemplaza" and f["aporta_algo"] and f["marcada"]
    conf = api.post(f"/descubrimiento/{cid}/confirmar", rol="steward", json={}).json()["resultado"]["confirmado"]
    assert conf["detalle"][0]["direccion"] == "reemplazo"
    assert sql.execute("SELECT direccion FROM empresa").fetchone()["direccion"] == "Artigas 1200, Salto"
    coincide_con_lo_confirmado(prev, conf)


def test_direccion_de_una_carga_con_mas_confianza(api, sql, monkeypatch):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Imprenta Salteña SA", "Teléfono": "47331111",
                  "Dirección": "Larrañaga 455, Salto", "Departamento": "Salto"}])
    cid, prev = buscar(api, monkeypatch, [lugar("Imprenta Salteña", tel="47331111", pid="p1", direccion="Artigas 1200, Salto")])
    d = aporte(prev["resultados"][0], "direccion")
    assert d["estado"] == "solo_historia" and "más confianza (50 contra 30" in d["motivo"]
    conf = api.post(f"/descubrimiento/{cid}/confirmar", rol="steward",
                    json={"seleccion": {"0": "completar"}}).json()["resultado"]["confirmado"]
    coincide_con_lo_confirmado(prev, conf)


def test_lote_mezclado_y_simulacion_igual_a_lo_confirmado(api, sql, monkeypatch):
    configurar(api, confianza=50)
    cargar(api, [
        {"RUT": rut_valido(0), "Razón social": "Uno SA", "Teléfono": "47330001", "Web": "https://uno.com.uy",
         "Dirección": "Uruguay 1, Salto", "Departamento": "Salto"},
        {"RUT": rut_valido(1), "Razón social": "Dos SA", "Teléfono": "47330002", "Web": "https://dos.com.uy",
         "Dirección": "", "Departamento": "Salto"},
        {"RUT": rut_valido(2), "Razón social": "Tres SA", "Teléfono": "47330003", "Web": "",
         "Dirección": "Artigas 3, Salto", "Departamento": "Salto"}])
    cid, prev = buscar(api, monkeypatch, [
        lugar("Uno", tel="47330001", pid="p1", web="https://www.uno.com.uy", direccion="Uruguay 1, Salto"),
        lugar("Dos", tel="47330002", pid="p2", web="https://otro-dos.com.uy", direccion="Sarandí 2, Salto"),
        lugar("Tres", tel="47330003", pid="p3", web="https://tres.com.uy", direccion="Florida 999, Salto"),
        lugar("Nueva", tel="47339999", pid="p4")])
    est = {f["i"]: {a["dato"]: a["estado"] for a in f.get("aporta", [])} for f in prev["resultados"]}
    assert est[0] == {"telefono": "igual", "web": "igual", "direccion": "igual", "place_id": "nuevo"}
    assert est[1] == {"telefono": "igual", "web": "reemplaza", "direccion": "nuevo", "place_id": "nuevo"}
    assert est[2] == {"telefono": "igual", "web": "nuevo", "direccion": "reemplaza", "place_id": "nuevo"}
    assert est[3] == {} and prev["resultados"][3]["caso"] == "nueva"
    assert prev["resumen"]["aportan"] == 2
    sel = {str(f["i"]): "completar" for f in prev["resultados"] if f["caso"] == "coincide"}
    conf = api.post(f"/descubrimiento/{cid}/confirmar", rol="steward", json={"seleccion": sel}).json()["resultado"]["confirmado"]
    assert conf["completadas"] == 3 and conf["sin_cambios"] == 1 and conf["altas"] == 1
    coincide_con_lo_confirmado(prev, conf)
    # Un lote viejo (sin «aporta») se sigue viendo
    assert all("aporta" not in f for f in prev["resultados"] if f["caso"] == "nueva")


def test_omitir_las_que_no_aportan_cambia_solo_esas(api, sql, monkeypatch):
    """«Omitir las que no aportan» es de la pantalla: acá se verifica que la selección por defecto ya las omite y que
    una selección explícita respeta el resto."""
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Uno SA", "Teléfono": "47330001", "Web": "", "Departamento": "Salto"},
                 {"RUT": rut_valido(1), "Razón social": "Dos SA", "Teléfono": "47330002", "Web": "https://dos.com.uy",
                  "Departamento": "Salto"}])
    cid, prev = buscar(api, monkeypatch, [lugar("Uno", tel="47330001", pid="p1", web="https://uno.com.uy"),
                                          lugar("Dos", tel="47330002", pid="p2", web="https://dos.com.uy")])
    marcadas = {f["i"]: f["marcada"] for f in prev["resultados"]}
    assert marcadas == {0: True, 1: False}
    conf = api.post(f"/descubrimiento/{cid}/confirmar", rol="steward", json={}).json()["resultado"]["confirmado"]
    assert conf["completadas"] == 1 and conf["omitidas"] == 1 and [d["i"] for d in conf["detalle"]] == [0]


def test_aportes_de_60_filas_con_pocas_consultas(api, sql):
    """Un lote de 60 filas calcula «Qué aporta» con 5 consultas como máximo (se cuentan las de agregar_aportes)."""
    cargar(api, [{"RUT": rut_valido(i), "Razón social": f"Empresa {i} SA", "Teléfono": f"4733{i:04d}",
                  "Dirección": f"Calle {i} 100, Salto", "Departamento": "Salto"} for i in range(60)])
    ids = [r["id"] for r in sql.execute("SELECT id FROM empresa ORDER BY id")]
    filas = [{"i": i, "caso": "coincide", "marcada": True, "place_id": f"p{i}", "telefono": f"+5984733{i:04d}",
              "web": f"https://e{i}.com.uy", "direccion": f"Otra calle {i} 200, Salto", "empresa": {"id": ids[i]}}
             for i in range(60)]

    class Contador:
        def __init__(self, conn):
            self.conn, self.n = conn, 0

        def execute(self, *a, **k):
            self.n += 1
            return self.conn.execute(*a, **k)

    c = Contador(sql)
    cfg, _ = enr.cfg_vigente(sql)
    descubrimiento.agregar_aportes(c, filas, cfg)
    assert c.n <= 5, c.n
    assert all(aporte(f, "telefono")["estado"] == "igual" and aporte(f, "web")["estado"] == "nuevo"
               and aporte(f, "direccion")["estado"] == "solo_historia" for f in filas)


def test_csv_del_preview(api, sql, monkeypatch):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Uno SA", "Teléfono": "47330001", "Departamento": "Salto"}])
    cid, prev = buscar(api, monkeypatch, [lugar("Uno", tel="47330001", pid="p1", web="https://uno.com.uy"),
                                          lugar("Nueva", tel="47339999", pid="p2")])
    r = api.get(f"/descubrimiento/{cid}/preview.csv", rol="steward")
    assert r.status_code == 200, r.text
    lineas = r.content.decode("utf-8-sig").strip().splitlines()
    assert lineas[0].startswith("caso;nombre_places;") and "que_aporta" in lineas[0]
    assert "Sitio nuevo" in lineas[1] and rut_valido(0) in lineas[1]
    assert lineas[2].startswith("nueva;Nueva;")
