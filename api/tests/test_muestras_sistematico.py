"""SPEC_muestras_marco_excel_sistematico (D56): marco completo (total, sorteables y no sorteables por estrato), sin la
opción «Incluir empresas sin teléfono», Excel de tamaños y sorteo sistemático por CIIU."""
import io
import json
from collections import Counter

import pytest
from openpyxl import load_workbook

from conftest import rut_valido
from test_muestra import estudio
from test_templates_sorteo import marco, sortear
from app import muestras as mu


# ─── R4 · Algoritmo sistemático (función pura) ───

def lista_ordenada(marco_, ciiu, semilla):
    return sorted([e for e, _ in marco_], key=lambda eid: (ciiu.get(eid) is None, ciiu.get(eid) or "",
                                                         mu.clave_orden(semilla, eid), eid))


def test_posiciones_y_vecinos_n10_n3_r3():
    marco_ = [(100 + i, "A") for i in range(10)]
    ciiu = {100 + i: f"{(9 - i):04d}" for i in range(10)}           # el orden por CIIU invierte los ids
    vecinos = {}
    salida = mu.sortear_sistematico(marco_, 42, {"A": (3, 3)}, ciiu, vecinos=vecinos)
    lista = lista_ordenada(marco_, ciiu, 42)
    a = mu.arranque(42, "A", 10)
    esperadas = [(a + i * 10) // 3 for i in range(3)]
    tit = [e for e, _, rol, _ in salida if rol == "titular"]
    assert tit == [lista[p] for p in esperadas]
    # cada reemplazo es la siguiente posición libre después de su titular, en el orden sha256(semilla:titular)
    orden_t = sorted(esperadas, key=lambda p: (mu.clave_orden(42, lista[p]), lista[p]))
    tomadas, esperados_r = set(esperadas), []
    for p in orden_t:
        j = (p + 1) % 10
        while j in tomadas:
            j = (j + 1) % 10
        tomadas.add(j)
        esperados_r.append((lista[j], lista[p]))
    rem = [(e, o) for e, _, rol, o in salida if rol == "reemplazo"]
    assert [e for e, _ in rem] == [e for e, _ in esperados_r] and [o for _, o in rem] == [4, 5, 6]
    assert vecinos == dict(esperados_r)
    assert [o for _, _, rol, o in salida if rol == "titular"] == [1, 2, 3]


def test_intervalo_menor_a_dos_n7_n5_r2():
    marco_ = [(i, "A") for i in range(1, 8)]
    ciiu = {i: f"{i:04d}" for i in range(1, 8)}
    for semilla in range(30):
        s = mu.sortear_sistematico(marco_, semilla, {"A": (5, 2)}, ciiu)
        tit = {e for e, _, rol, _ in s if rol == "titular"}
        rem = {e for e, _, rol, _ in s if rol == "reemplazo"}
        assert len(tit) == 5 and len(rem) == 2 and not (tit & rem)


def test_cada_ciiu_recibe_su_parte():
    marco_ = [(i, "A") for i in range(1000)]
    ciiu = {i: f"{10 + i // 100}11" for i in range(1000)}           # 10 CIIU de 100 empresas
    for semilla in (1, 7, 12345):
        s = mu.sortear_sistematico(marco_, semilla, {"A": (50, 10)}, ciiu)
        por_ciiu = Counter(ciiu[e] for e, _, rol, _ in s if rol == "titular")
        assert sorted(por_ciiu.values()) == [5] * 10


def test_todas_titulares_si_no_alcanza_y_sin_ciiu_al_final():
    marco_ = [(1, "A"), (2, "A"), (3, "A")]
    s = mu.sortear_sistematico(marco_, 3, {"A": (5, 2)}, {1: None, 2: "4711", 3: "0111"})
    assert [(e, rol, o) for e, _, rol, o in s] == [(3, "titular", 1), (2, "titular", 2), (1, "titular", 3)]


def test_una_por_grupo_sin_repetir_y_sin_perder_cuota():
    marco_ = [(i, "A") for i in range(40)] + [(100 + i, "B") for i in range(20)]
    ciiu = {e: f"{e % 7:04d}" for e, _ in marco_}
    grupos = {e: e % 15 for e, _ in marco_ if e % 2 == 0}   # muchos repetidos entre los pares
    for semilla in range(10):
        s = mu.sortear_sistematico(marco_, semilla, {"A": (10, 5), "B": (4, 4)}, ciiu, grupos)
        g = [grupos[e] for e, _, _, _ in s if e in grupos]
        assert len(g) == len(set(g))
        assert Counter(est for _, est, rol, _ in s if rol == "titular") == {"A": 10, "B": 4}


def test_reproducible_misma_semilla():
    marco_ = [(i, "A" if i % 2 else "B") for i in range(200)]
    ciiu = {i: f"{i % 13:04d}" for i in range(200)}
    d = {"A": (12, 6), "B": (7, 3)}
    assert mu.sortear_snapshot(marco_, 99, d, None, "sistematico_ciiu", ciiu) == \
        mu.sortear_snapshot(list(reversed(marco_)), 99, d, None, "sistematico_ciiu", dict(reversed(list(ciiu.items()))))


def test_aleatorio_como_antes():
    """El aleatorio no cambia: orden sha256(semilla:empresa_id) dentro del estrato."""
    marco_ = [(i, "A") for i in range(30)]
    s = mu.sortear_snapshot(marco_, 5, {"A": (4, 3)})
    esperado = sorted(range(30), key=lambda e: (mu.clave_orden(5, e), e))[:7]
    assert [e for e, _, _, _ in s] == esperado and [o for *_, o in s] == list(range(1, 8))


# ─── R3 · Marco completo ───

def escenario(sql, n=100, sin_tel=20, enfriadas=5, ambas=1):
    """n empresas en un estrato: las primeras sin_tel sin teléfono; enfriadas en enfriamiento (ambas de ellas,
    también sin teléfono)."""
    x = sql.execute
    for i in range(n):
        eid = x("INSERT INTO empresa (rut, razon_social, departamento, ciiu, ultimo_contacto_efectivo) VALUES (%s, %s,"
                " 'Salto', %s, CASE WHEN %s THEN now() END) RETURNING id",
                (rut_valido(i), f"Empresa {i:03d}", f"{(i % 10) + 10}11",
                 (sin_tel - ambas) <= i < (sin_tel - ambas + enfriadas))).fetchone()["id"]
        if i >= sin_tel:
            t = x("INSERT INTO telefono (e164, crudo, tipo) VALUES (%s, %s, 'fijo') RETURNING id",
                  (f"+5982900{i:04d}", f"2900{i:04d}")).fetchone()["id"]
            x("INSERT INTO telefono_vinculo (telefono_id, empresa_id, fuente_tipo) VALUES (%s, %s, 'manual')", (t, eid))


def test_marco_total_sorteables_y_motivos(api, sql):
    escenario(sql)
    r = marco(api, {"estratificar_por": ["departamento"]})
    e = r["estratos"][0]
    assert (e["estrato"], e["total"], e["sorteables"], e["no_sorteables"]) == ("Salto", 100, 76, 24)
    assert e["motivos"] == {"sin_telefono_discable": 20, "enfriamiento": 5} and e["disponibles"] == 76
    assert sum(x["sorteables"] for x in r["estratos"]) == r["marco"] == 76
    assert sum(x["total"] for x in r["estratos"]) == r["universo"] == 100 and r["no_sorteables"] == 24
    # CSV de no sorteables, con estrato y motivo
    c = api.post("/muestras/marco/no-sorteables.csv", rol="jefe", json={"estratificar_por": ["departamento"]})
    lineas = c.content.decode("utf-8-sig").strip().splitlines()
    assert lineas[0] == "rut;razon_social;departamento;ciiu;estrato;motivo" and len(lineas) == 25
    assert sum("enfriamiento" in x for x in lineas) == 5 and sum("sin teléfono discable" in x for x in lineas) == 20
    # el sorteo nunca incluye una no sorteable, aunque pida más de las que hay
    est = estudio(api)
    mid, s = sortear(api, est, {"estratificar_por": ["departamento"], "estratos": [{"estrato": "Salto", "n": 90, "reemplazos": 5}]})
    no = {r["id"] for r in sql.execute("SELECT empresa_id AS id FROM empresa_disponibilidad WHERE NOT disponible")}
    elegidas = {r["empresa_id"] for r in sql.execute("SELECT empresa_id FROM muestra_item WHERE muestra_id = %s", (mid,))}
    assert len(elegidas) == 76 and not (elegidas & no)
    assert s["estratos"][0]["total"] == 100 and s["estratos"][0]["no_sorteables"] == 24


def test_estratos_sobre_todo_el_universo(api, sql):
    """Un estrato sin ninguna sorteable igual aparece, con su total."""
    escenario(sql, n=10, sin_tel=4, enfriadas=0, ambas=0)
    sql.execute("UPDATE empresa SET departamento = 'Rivera' WHERE razon_social IN ('Empresa 000', 'Empresa 001')")
    r = marco(api, {"estratificar_por": ["departamento"]})
    riv = next(x for x in r["estratos"] if x["estrato"] == "Rivera")
    assert (riv["total"], riv["sorteables"], riv["no_sorteables"]) == (2, 0, 2)


def test_template_con_la_opcion_vieja(api, sql):
    escenario(sql, n=6, sin_tel=2, enfriadas=0, ambas=0)
    t = api.post("/muestra-templates", rol="jefe", json={"nombre": "Viejo", "criterios": {"n_por_estrato": 2}}).json()
    sql.execute("UPDATE muestra_template SET criterios = criterios || '{\"incluir_sin_telefono\": true}' WHERE id = %s", (t["id"],))
    ap = api.post(f"/muestra-templates/{t['id']}/aplicar", rol="jefe").json()
    assert any("ya no existe" in a for a in ap["avisos"]) and "incluir_sin_telefono" not in ap["criterios"]
    assert ap["marco"]["marco"] == 4
    r = api.put(f"/muestra-templates/{t['id']}", rol="jefe", json={"criterios": {**ap["criterios"], "incluir_sin_telefono": True}})
    assert "incluir_sin_telefono" not in r.json()["criterios"]


def test_muestra_vieja_sigue_siendo_reproducible(api, sql):
    escenario(sql, n=12, sin_tel=0, enfriadas=0, ambas=0)
    est = estudio(api)
    mid, _ = sortear(api, est, {"n_por_estrato": 4, "reemplazos_por_estrato": 2})
    # como una muestra sorteada antes de D56: con la opción vieja y sin el CIIU congelado
    sql.execute("UPDATE muestra SET criterios = criterios || '{\"incluir_sin_telefono\": true}' WHERE id = %s", (mid,))
    sql.execute("UPDATE marco_snapshot SET ciiu_congelado = false WHERE id = (SELECT snapshot_id FROM muestra WHERE id = %s)", (mid,))
    assert api.post(f"/muestras/{mid}/verificar", rol="jefe").json()["resultado"] == "reproducible"


def test_borrador_con_la_opcion_vieja_avisa_y_la_ignora(api, sql):
    escenario(sql, n=8, sin_tel=3, enfriadas=0, ambas=0)
    est = estudio(api)
    m = api.post("/muestras", rol="jefe", json={"estudio_id": est["id"], "nombre": "B", "criterios": {"n_por_estrato": 8}}).json()
    sql.execute("UPDATE muestra SET criterios = criterios || '{\"incluir_sin_telefono\": true}' WHERE id = %s", (m["id"],))
    assert "ya no existe" in api.get(f"/muestras/{m['id']}").json()["avisos"][0]
    r = api.post(f"/muestras/{m['id']}/sortear", rol="jefe", json={"semilla": 3}).json()
    assert r["marco"] == 5 and "ya no existe" in r["avisos"][0]


# ─── R4 · Sorteo sistemático por la API ───

def test_sistematico_de_punta_a_punta(api, sql):
    escenario(sql, n=40, sin_tel=0, enfriadas=0, ambas=0)
    est = estudio(api)
    c = {"metodo": "sistematico_ciiu", "estratificar_por": ["departamento"],
         "estratos": [{"estrato": "Salto", "n": 8, "reemplazos": 4}]}
    mid, s = sortear(api, est, c, semilla=11)
    assert s["metodo"] == "sistematico_ciiu"
    m = api.get(f"/muestras/{mid}").json()
    assert m["criterios"]["metodo"] == "sistematico_ciiu" and m["criterios"]["orden_sistematico"] == ["ciiu"]
    items = api.get(f"/muestras/{mid}/items", params={"por_pagina": 100}).json()["items"]
    tit = [i for i in items if i["rol"] == "titular"]
    rem = [i for i in items if i["rol"] == "reemplazo"]
    assert len(tit) == 8 and len(rem) == 4 and all(i["vecino_de"] for i in rem) and not any(i["vecino_de"] for i in tit)
    # cada CIIU (4 empresas de cada uno de 10) recibe a lo sumo un titular por cada 5 posiciones: exactamente 8 distintos
    assert len({i["ciiu"] for i in tit}) == 8
    assert sql.execute("SELECT bool_and(ciiu IS NOT NULL) AS ok FROM marco_snapshot_item WHERE snapshot_id ="
                       " (SELECT snapshot_id FROM muestra WHERE id = %s)", (mid,)).fetchone()["ok"]
    assert api.post(f"/muestras/{mid}/verificar", rol="jefe").json()["resultado"] == "reproducible"
    # P1: liberar el reemplazo de un titular puntual
    t = next(i for i in tit if i["reemplazo_libre"])
    r = api.post(f"/muestras/{mid}/liberar-vecino", rol="jefe", json={"item_id": t["id"], "motivo": "rechazó"})
    assert r.status_code == 200 and r.json()["items"] == [t["reemplazo_libre"]]
    assert api.post(f"/muestras/{mid}/liberar-vecino", rol="jefe", json={"item_id": t["id"], "motivo": "x"}).status_code == 409
    # el CIIU cambia después del sorteo: la verificación usa el congelado
    sql.execute("UPDATE empresa SET ciiu = '9999'")
    assert api.post(f"/muestras/{mid}/verificar", rol="jefe").json()["resultado"] == "reproducible"
    # sin el CIIU congelado no se puede verificar
    sql.execute("UPDATE marco_snapshot SET ciiu_congelado = false WHERE id = (SELECT snapshot_id FROM muestra WHERE id = %s)", (mid,))
    assert api.post(f"/muestras/{mid}/verificar", rol="jefe").json()["resultado"] == "no_verificable"


def test_sistematico_sin_titulares_no_acepta_reemplazos(api, sql):
    escenario(sql, n=4, sin_tel=0, enfriadas=0, ambas=0)
    est = estudio(api)
    r = api.post("/muestras", rol="jefe", json={"estudio_id": est["id"], "nombre": "S", "criterios": {
        "metodo": "sistematico_ciiu", "estratos": [{"estrato": "Total", "n": 0, "reemplazos": 2}]}})
    assert r.status_code == 422 and "sin titulares" in r.json()["detail"]
    r = api.post("/muestras", rol="jefe", json={"estudio_id": est["id"], "nombre": "S", "criterios": {"metodo": "otro", "n_por_estrato": 1}})
    assert r.status_code == 422


def test_template_guarda_el_metodo(api, sql):
    escenario(sql, n=4, sin_tel=0, enfriadas=0, ambas=0)
    t = api.post("/muestra-templates", rol="jefe", json={"nombre": "Sis", "criterios": {"metodo": "sistematico_ciiu",
                                                                                      "n_por_estrato": 2}}).json()
    ap = api.post(f"/muestra-templates/{t['id']}/aplicar", rol="jefe").json()
    assert ap["criterios"]["metodo"] == "sistematico_ciiu"
    assert next(x for x in api.get("/muestra-templates", rol="jefe").json() if x["id"] == t["id"])["resumen"]["metodo"] == \
        "Sistemático por CIIU"


# ─── R2 · Excel de tamaños ───

def tres_estratos(sql):
    escenario(sql, n=30, sin_tel=6, enfriadas=0, ambas=0)
    sql.execute("UPDATE empresa SET departamento = CASE WHEN razon_social < 'Empresa 010' THEN 'Artigas'"
                " WHEN razon_social < 'Empresa 020' THEN 'Rivera' ELSE 'Salto' END")


def bajar(api, criterios, **kw):
    r = api.post("/muestras/marco/tamanos.xlsx", rol="jefe", json={"criterios": criterios, **kw})
    assert r.status_code == 200, r.text
    return r


def subir(api, contenido, criterios):
    return api.c.post("/api/muestras/tamanos/importar", headers={"X-Dev-User": "jefe@equipos.com.uy"},
                      files={"archivo": ("t.xlsx", io.BytesIO(contenido))}, data={"criterios": json.dumps(criterios)})


def test_excel_descarga_e_importacion(api, sql, tmp_path):
    tres_estratos(sql)
    est = estudio(api)
    c = {"estratificar_por": ["departamento"], "estratos": [{"estrato": "Rivera", "n": 3, "reemplazos": 1}]}
    r = bajar(api, c, estudio_id=est["id"])
    assert r.headers["content-disposition"].endswith('.xlsx"') and "tamanos_clima_2026_nueva_" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Tamaños", "Instrucciones", "_meta"] and wb["_meta"].sheet_state == "hidden"
    ws = wb["Tamaños"]
    assert ws.protection.sheet is True
    filas = list(ws.iter_rows(values_only=True))
    assert filas[0][:7] == ("Estrato", "Total en el marco", "Sorteables", "No sorteables", "Titulares", "Reemplazos", "¿Alcanza?")
    assert [f[0] for f in filas[1:]] == ["Artigas", "Rivera", "Salto", "Total"]
    assert filas[1][1:3] == (10, 4) and filas[2][4:6] == (3, 1) and filas[1][4] is None
    assert str(filas[1][3]).startswith("=B2-C2") and str(filas[1][6]).startswith("=IF(")
    assert ws.cell(2, 5).protection.locked is False and ws.cell(2, 1).protection.locked is True
    (tmp_path / "t.xlsx").write_bytes(r.content)
    # se completan tamaños (como lo haría el usuario) y se importa: no se guarda nada
    ws.cell(2, 5, 4), ws.cell(2, 6, 1), ws.cell(3, 5, 5), ws.cell(4, 5, 4), ws.cell(4, 6, 1)
    ws.cell(3, 6).value = None              # celda vacía: cuenta como 0
    salida = io.BytesIO()
    wb.save(salida)
    imp = subir(api, salida.getvalue(), c)
    assert imp.status_code == 200, imp.text
    j = imp.json()
    assert j["tamanos"] == [{"estrato": "Artigas", "n": 4, "reemplazos": 1}, {"estrato": "Rivera", "n": 5, "reemplazos": 0},
                            {"estrato": "Salto", "n": 4, "reemplazos": 1}]
    assert j["errores"] == [] and [a for a in j["avisos"] if "no alcanza" in a] == [
        "El estrato Artigas no alcanza: pide 5 y tiene 4 sorteables"]
    assert sql.execute("SELECT count(*) AS n FROM muestra").fetchone()["n"] == 0


def test_excel_errores_por_fila_y_estratos_que_no_estan(api, sql):
    tres_estratos(sql)
    c = {"estratificar_por": ["departamento"]}
    wb = load_workbook(io.BytesIO(bajar(api, c).content))
    ws = wb["Tamaños"]
    ws.cell(2, 5, -3)                       # Artigas: negativo
    ws.cell(3, 5, 2.5)                      # Rivera: decimales
    ws.cell(4, 1, "Salto renombrado")       # Salto: ya no está
    ws.cell(4, 5, 1)
    salida = io.BytesIO()
    wb.save(salida)
    j = subir(api, salida.getvalue(), c).json()
    assert j["tamanos"] == [] and len(j["errores"]) == 2
    assert "negativo" in j["errores"][0] and "decimales" in j["errores"][1]
    assert any("Salto renombrado no está en el marco" in a for a in j["avisos"])
    assert any("Salto no está en el Excel" in a for a in j["avisos"])
    # con otros filtros: aviso
    j = subir(api, salida.getvalue(), {"estratificar_por": ["departamento"], "campos": {"ciiu": {"contiene": "11"}}}).json()
    assert any("otros filtros o estratos" in a for a in j["avisos"])


def test_excel_invalido(api, sql):
    tres_estratos(sql)
    assert subir(api, b"no es un excel", {}).status_code == 422
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "Otra"
    s = io.BytesIO()
    wb.save(s)
    r = subir(api, s.getvalue(), {})
    assert r.status_code == 422 and "hoja «Tamaños»" in r.json()["detail"]


def test_excel_de_una_muestra_sorteada(api, sql):
    tres_estratos(sql)
    est = estudio(api)
    mid, _ = sortear(api, est, {"estratificar_por": ["departamento"], "n_por_estrato": 2})
    r = api.get(f"/muestras/{mid}/tamanos.xlsx", rol="jefe")
    assert r.status_code == 200
    filas = list(load_workbook(io.BytesIO(r.content))["Tamaños"].iter_rows(values_only=True))
    assert [(f[0], f[1], f[2], f[4]) for f in filas[1:4]] == [("Artigas", 10, 4, 2), ("Rivera", 10, 10, 2), ("Salto", 10, 10, 2)]


@pytest.mark.parametrize("n", [50])
def test_excel_con_50_estratos(api, sql, n):
    """Criterio de R2: 50 estratos, se cambian todos y vuelven los 50 valores."""
    escenario(sql, n=n, sin_tel=0, enfriadas=0, ambas=0)
    c = {"estratificar_por": ["razon_social"]}
    wb = load_workbook(io.BytesIO(bajar(api, c).content))
    ws = wb["Tamaños"]
    for i in range(2, n + 2):
        ws.cell(i, 5, 1)
        ws.cell(i, 6, 0)
    s = io.BytesIO()
    wb.save(s)
    j = subir(api, s.getvalue(), c).json()
    assert j["importados"] == n and all(x["n"] == 1 for x in j["tamanos"]) and not j["errores"]
