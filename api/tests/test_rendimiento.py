"""SPEC_rendimiento_base_grande (D55): disponibilidad guardada, resumen precalculado, buscador por clave, límites de
tiempo y mantenimiento al terminar cada operación grande."""
import logging
import os
import time

import psycopg
import pytest

from conftest import cargar, reiniciar_base, rut_valido
from test_campo import fila_sav, hacer_sav, ingerir
from test_muestra import estudio, muestra
from app import db as appdb, disponibilidad, mantenimiento, resumen, settings


def fila(i, **extra):
    return {"RUT": rut_valido(i), "Razón social": f"Empresa {i:03d} SRL", "Teléfono": f"2900{i:04d}",
            "Departamento": ["Salto", "Rivera", "Montevideo"][i % 3], "Tamaño": "Pyme", "Naturaleza": "SA",
            "CIIU": "4711", **extra}


def guardada(sql) -> dict:
    return {r["empresa_id"]: (r["disponible"], list(r["reglas"]), r["hasta"], r["telefonos_discables"])
            for r in sql.execute("SELECT * FROM empresa_disponibilidad")}


def calculada(sql) -> dict:
    """La referencia: la vista de siempre (bloqueos con la configuración vigente) y el conteo de vínculos discables."""
    tels = {r["empresa_id"]: r["n"] for r in sql.execute(
        "SELECT empresa_id, count(*) AS n FROM v_vinculo_discable GROUP BY empresa_id")}
    return {r["empresa_id"]: (r["disponible"], list(r["reglas"]), r["hasta"], tels.get(r["empresa_id"], 0))
            for r in sql.execute("SELECT * FROM v_empresa_disponible")}


def al_dia(api, sql):
    """Abre el buscador (deja la tabla al día si es poco trabajo) y compara con el cálculo de siempre."""
    r = api.get("/empresas", params={"base": "ambas"})
    assert r.status_code == 200, r.text
    assert r.json()["disponibilidad_al_dia"] is True
    g, c = guardada(sql), calculada(sql)
    assert g == c, {k: (g.get(k), c.get(k)) for k in set(g) | set(c) if g.get(k) != c.get(k)}
    return g


# ─── P-2 · Equivalencia con bloqueos(cfg) después de cada operación ───

def test_equivalencia_despues_de_cada_operacion(api, sql):
    cargar(api, [fila(i) for i in range(8)])
    g = al_dia(api, sql)
    assert len(g) == 8 and all(v[0] for v in g.values()) and all(v[3] == 1 for v in g.values())

    # «No llamar» por empresa y por teléfono
    assert api.post("/no-llamar", json={"alcance": "empresa", "rut": rut_valido(0), "motivo": "pidió", "solicitante": "x"}).status_code == 200
    assert api.post("/no-llamar", json={"alcance": "telefono", "telefono": "29000001", "motivo": "m", "solicitante": "x"}).status_code == 200
    g = al_dia(api, sql)
    assert "no_llamar" in g[sql.execute("SELECT id FROM empresa WHERE rut = %s", (rut_valido(0),)).fetchone()["id"]][1]

    # Muestra sorteada (muestra activa) y su .sav (enfriamiento por contacto efectivo)
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 3})
    g = al_dia(api, sql)
    assert sum("muestra_activa" in v[1] for v in g.values()) >= 3
    items = sql.execute("SELECT i.id, e.rut FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id"
                        " WHERE i.muestra_id = %s AND i.liberado ORDER BY i.id LIMIT 2", (mid,)).fetchall()
    ingerir(api, e["partes"][0]["id"], hacer_sav([fila_sav(k + 1, it) for k, it in enumerate(items)]))
    g = al_dia(api, sql)
    assert sum("enfriamiento" in v[1] for v in g.values()) == 2

    # Cerrar la muestra libera la regla «muestra activa»
    assert api.post(f"/muestras/{mid}/cerrar", rol="jefe").status_code == 200
    g = al_dia(api, sql)
    assert not any("muestra_activa" in v[1] for v in g.values())

    # Configuración: meses de enfriamiento y naturaleza excluida (incremental), regla sin teléfono (recálculo completo)
    cfg = api.get("/config").json()["parametros"]
    cfg["meses_enfriamiento"] = 0
    assert api.put("/config", json={"parametros": cfg}).status_code == 200
    # la tabla sigue lista: el cambio afectó a pocas empresas (no hace falta el recálculo completo)
    with psycopg.connect(sql.info.dsn, row_factory=psycopg.rows.dict_row, options="-c search_path=empresas,public") as c:
        assert disponibilidad.lista(c) is True
    g = al_dia(api, sql)
    assert not any("enfriamiento" in v[1] for v in g.values())
    cfg["naturalezas_excluidas"] = ["SA"]
    assert api.put("/config", json={"parametros": cfg}).status_code == 200
    g = al_dia(api, sql)
    assert all("naturaleza_excluida" in v[1] for v in g.values())
    cfg["naturalezas_excluidas"] = []
    cfg["reglas_disponibilidad"]["sin_telefono_discable"] = False
    assert api.put("/config", json={"parametros": cfg}).status_code == 200
    al_dia(api, sql)

    # Un teléfono que pasa a inexistente o a intermediario, y el deshacer de la carga
    sql.execute("UPDATE telefono SET estado = 'inexistente' WHERE e164 LIKE %s", ("%29000002",))
    sql.execute("UPDATE telefono SET intermediario = 'confirmado' WHERE e164 LIKE %s", ("%29000003",))
    al_dia(api, sql)
    cfg["reglas_disponibilidad"]["sin_telefono_discable"] = True
    assert api.put("/config", json={"parametros": cfg}).status_code == 200
    g = al_dia(api, sql)
    # el inexistente, el intermediario y el que está en «no llamar»
    assert sum("sin_telefono_discable" in v[1] for v in g.values()) == 3
    c2 = cargar(api, [fila(i) for i in range(20, 23)])   # la primera tiene empresas en una muestra: no se deshace
    al_dia(api, sql)
    r = api.delete(f"/cargas/{c2['id']}", rol="admin")
    assert r.status_code == 200, r.text
    g = al_dia(api, sql)
    assert sum("baja" in v[1] for v in g.values()) >= 1


def test_enfriamiento_vencido_se_recalcula_solo(api, sql):
    cargar(api, [fila(i) for i in range(3)])
    al_dia(api, sql)
    eid = sql.execute("SELECT id FROM empresa ORDER BY id LIMIT 1").fetchone()["id"]
    # contacto efectivo hace 6 meses menos 2 segundos (enfriamiento de 6 meses): vence enseguida
    sql.execute("UPDATE empresa SET ultimo_contacto_efectivo = now() - interval '6 months' + interval '2 seconds'"
                " WHERE id = %s", (eid,))
    g = al_dia(api, sql)
    assert g[eid][1] == ["enfriamiento"] and g[eid][0] is False
    time.sleep(2.5)
    g = al_dia(api, sql)   # nada cambió en la base, pero el «hasta» pasó
    assert g[eid][0] is True and g[eid][2] is None


def test_bloqueos_ids_coincide_con_bloqueos(api, sql):
    cargar(api, [fila(i) for i in range(6)])
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": 2})
    sql.execute("UPDATE empresa SET estado = 'cerrada' WHERE id = (SELECT min(id) FROM empresa)")
    cfg = sql.execute("SELECT config_vigente() AS c").fetchone()["c"]
    ids = [r["id"] for r in sql.execute("SELECT id FROM empresa")]
    for excluir in (None, mid):
        a = sorted(tuple(r.values()) for r in sql.execute("SELECT * FROM bloqueos(%s, %s)", (psycopg.types.json.Jsonb(cfg), excluir)))
        b = sorted(tuple(r.values()) for r in sql.execute("SELECT * FROM bloqueos_ids(%s, %s, %s)",
                                                           (psycopg.types.json.Jsonb(cfg), ids, excluir)))
        assert a == b


def test_mientras_no_esta_lista_usa_el_calculo_anterior(api, sql, monkeypatch):
    cargar(api, [fila(i) for i in range(4)])
    monkeypatch.setattr(disponibilidad, "BASE_CHICA", 2)            # se comporta como una base grande
    encoladas = []
    monkeypatch.setattr(mantenimiento, "encolar", lambda motivo, *a, **k: encoladas.append(motivo))
    sql.execute("UPDATE disponibilidad_control SET completo = false, cfg = NULL")
    r = api.get("/empresas").json()
    assert r["disponibilidad_al_dia"] is False and r["total"] == 4 and all(e["disponible"] for e in r["empresas"])
    assert encoladas and "recálculo completo" in encoladas[0]
    assert api.get("/inicio").json()["disponibles"] in (None, 4)
    # la tarea de mantenimiento la completa por pasos, con progreso
    with appdb.conexion() as c:
        params = sql.execute("SELECT config_vigente() AS c").fetchone()["c"]
        assert disponibilidad.paso_completo(c, params, tanda=3) == (False, 3, 4)
    with appdb.conexion() as c:
        assert disponibilidad.paso_completo(c, params, tanda=3) == (False, 4, 4)
    with appdb.conexion() as c:
        assert disponibilidad.paso_completo(c, params, tanda=3)[0] is True
    assert api.get("/empresas").json()["disponibilidad_al_dia"] is True
    assert guardada(sql) == calculada(sql)


# ─── P-2 / P-3 · El buscador no calcula la disponibilidad de toda la base ───

def test_el_buscador_no_usa_bloqueos_ni_la_vista(api, sql, monkeypatch):
    cargar(api, [fila(i) for i in range(5)])
    api.get("/empresas")   # deja la disponibilidad lista
    consultas = []
    original = psycopg.Connection.execute

    def anotar(self, query, params=None, **kw):
        consultas.append((str(query), params))
        return original(self, query, params, **kw)

    monkeypatch.setattr(psycopg.Connection, "execute", anotar)
    r = api.get("/empresas", params={"disponible": "true", "sin_telefono": "false", "departamento": "Salto"})
    monkeypatch.setattr(psycopg.Connection, "execute", original)
    assert r.status_code == 200 and r.json()["total"] == 2
    principal = [(q, p) for q, p in consultas if "FROM empresa e" in q and "ORDER BY" in q]
    assert len(principal) == 1
    q, p = principal[0]
    assert "v_empresa_disponible" not in q and "bloqueos" not in q and "v_vinculo_discable" not in q
    plan = "\n".join(r["QUERY PLAN"] for r in sql.execute("EXPLAIN " + q, p))
    for nombre in ("bloqueos", "no_llamar", "muestra_item", "telefono_vinculo", "v_empresa_disponible"):
        assert nombre not in plan, plan
    assert "empresa_disponibilidad" in plan


def test_paginacion_por_clave_y_total(api, sql):
    cargar(api, [fila(i) for i in range(120)] + [{**fila(200), "Razón social": ""}])
    r1 = api.get("/empresas").json()
    assert r1["total"] == 121 and r1["aproximado"] is False and len(r1["empresas"]) == 50 and r1["siguiente"]
    todas = list(r1["empresas"])
    r = r1
    while r["siguiente"]:
        r = api.get("/empresas", params={"despues": r["siguiente"]}).json()
        todas += r["empresas"]
    assert len(todas) == 121 and len({e["id"] for e in todas}) == 121
    # mismo orden que la paginación por número (razón social, las sin razón social al final, código)
    por_numero = [e for p in (1, 2, 3) for e in api.get("/empresas", params={"pagina": p}).json()["empresas"]]
    assert [e["id"] for e in todas] == [e["id"] for e in por_numero]
    assert todas[-1]["razon_social"] is None
    # con filtro, también por clave
    r = api.get("/empresas", params={"departamento": "Salto"}).json()
    assert r["total"] == 40 and r["aproximado"] is False
    assert api.get("/empresas", params={"despues": "no-es-un-cursor"}).status_code == 422


def test_total_aproximado_y_exacto(api, sql, monkeypatch):
    from app.routers import empresas as rutas

    cargar(api, [fila(i) for i in range(60)])
    monkeypatch.setattr(rutas, "TOTAL_EXACTO_HASTA", 0)       # todo estimado se considera «caro»
    r = api.get("/empresas", params={"departamento": "Salto"}).json()
    assert r["total"] == 20 and r["aproximado"] is False     # una sola página: exacto
    r = api.get("/empresas").json()
    assert r["aproximado"] is True and r["total"] == 60       # sin filtros: el contador guardado de Inicio
    r = api.get("/empresas", params={"q": "SRL"}).json()
    assert r["aproximado"] is True and r["total"] > 0         # estimado del planificador
    r = api.get("/empresas", params={"q": "SRL", "exacto": "true"}).json()
    assert r["aproximado"] is False and r["total"] == 60


# ─── P-4 · Resumen precalculado ───

def test_valores_inicio_y_naturalezas_desde_el_resumen(api, sql):
    cargar(api, [fila(i, Localidad="Centro") for i in range(6)])
    v = api.get("/empresas/valores").json()
    assert v["departamento"] == ["Montevideo", "Rivera", "Salto"] and v["tamano"] == ["Pyme"] and v["ciiu2"] == ["47"]
    assert v["cantidades"]["departamento"] == {"Montevideo": 2, "Rivera": 2, "Salto": 2} and v["localidad"] == ["Centro"]
    assert v["actualizado"] and v["al_dia"] is True
    ini = api.get("/inicio").json()
    assert (ini["empresas"], ini["disponibles"], ini["con_telefono_discable"], ini["telefonos"]) == (6, 6, 6, 6)
    assert ini["resumen_actualizado"]
    sa = next(n for n in api.get("/naturalezas").json() if n["codigo"] == "SA")
    assert sa["empresas"] == 6 and sa["historia"] == 6 and sa["borrable"] is False
    # una carga nueva se refleja sin acción manual
    cargar(api, [fila(10, Departamento="Paysandú")])
    assert "Paysandú" in api.get("/empresas/valores").json()["departamento"]
    assert api.get("/inicio").json()["empresas"] == 7
    # y una empresa borrada también
    assert api.delete(f"/empresas/{rut_valido(10)}").status_code == 200
    assert "Paysandú" not in api.get("/empresas/valores").json()["departamento"]


def test_resumen_viejo_en_una_base_grande(api, sql, monkeypatch):
    cargar(api, [fila(i) for i in range(3)])
    assert api.get("/inicio").json()["empresas"] == 3
    monkeypatch.setattr(disponibilidad, "BASE_CHICA", 2)
    encoladas = []
    monkeypatch.setattr(mantenimiento, "encolar", lambda motivo, *a, **k: encoladas.append(motivo))
    sql.execute("UPDATE empresa SET baja = 'anulada' WHERE id = (SELECT min(id) FROM empresa)")
    ini = api.get("/inicio").json()
    assert ini["empresas"] == 3 and ini["resumen_al_dia"] is False and "resumen viejo" in encoladas
    with appdb.conexion() as c:
        resumen.recalcular(c)
    assert api.get("/inicio").json()["empresas"] == 2


def test_boton_recalcular(api, sql):
    cargar(api, [fila(0)])
    assert api.post("/mantenimiento/recalcular", rol="steward").status_code == 403
    r = api.post("/mantenimiento/recalcular").json()
    assert r["en_el_momento"] is True and set(r["resumenes"]) == {"valores", "inicio", "naturalezas"}
    m = api.get("/mantenimiento").json()
    assert m["disponibilidad"]["lista"] is True and {x["clave"] for x in m["resumenes"]} == {"valores", "inicio", "naturalezas"}
    assert "consultas_lentas" in m and m["estadisticas"]["actualizadas"] is not None


# ─── P-1 · ANALYZE al terminar ───

def test_analyze_al_terminar_la_carga(api, sql, caplog):
    inicio = sql.execute("SELECT now() AS t").fetchone()["t"]
    with caplog.at_level(logging.INFO, logger="app.mantenimiento"):
        c = cargar(api, [fila(i) for i in range(4)])
    assert c["estado"] == "confirmada"
    st = {r["relname"]: r["last_analyze"] for r in sql.execute(
        "SELECT relname, last_analyze FROM pg_stat_user_tables WHERE schemaname = 'empresas'"
        " AND relname IN ('empresa', 'empresa_campo_historia')")}
    assert all(t is not None and t > inicio for t in st.values()), st
    assert any("ANALYZE empresa_campo_historia" in m for m in caplog.messages)
    t = sql.execute("SELECT * FROM tarea WHERE tipo = 'base.mantenimiento' ORDER BY id DESC LIMIT 1").fetchone()
    assert t["estado"] == "ok" and {a["tabla"] for a in t["payload"]["analizadas"]} >= {"empresa", "empresa_campo_historia"}
    assert sql.execute("SELECT count(*) AS n FROM disponibilidad_pendiente").fetchone()["n"] == 0
    assert {r["clave"] for r in sql.execute("SELECT clave FROM resumen_base")} == {"valores", "inicio", "naturalezas"}


def test_job_diario_analiza_las_tablas_que_cambiaron(api, sql):
    cargar(api, [fila(i) for i in range(3)])
    sql.execute("INSERT INTO empresa (rut, razon_social) SELECT lpad(g::text, 7, '9'), 'X' FROM generate_series(1, 50) g")
    sql.execute("SELECT pg_stat_force_next_flush()")   # que la actividad se publique ya (si no, hasta 10 s después)
    sql.execute("SELECT 1")
    with appdb.conexion() as c:
        assert "empresa" in mantenimiento.tablas_a_analizar(c)


# ─── P-5 · Tiempo máximo por consulta y pool ───

def test_consulta_lenta_da_503_y_el_pool_sigue(api, sql, monkeypatch):
    from app.routers import admin

    monkeypatch.setattr(settings, "DB_STATEMENT_TIMEOUT_MS", 300)
    appdb.cerrar()
    monkeypatch.setattr(admin.resumen, "leer", lambda conn, clave: conn.execute("SELECT pg_sleep(2)").fetchone())
    t0 = time.monotonic()
    r = api.get("/inicio")
    assert r.status_code == 503 and r.json()["detail"].startswith("La consulta tardó demasiado")
    assert time.monotonic() - t0 < 1.8
    assert api.get("/me").status_code == 200            # el pool sigue disponible
    # Las rutas de jobs no tienen límite
    assert appdb.limite_de_ruta("/api/jobs/calidad") == 0 and appdb.limite_de_ruta("/api/inicio") is None
    monkeypatch.undo()
    appdb.cerrar()


def test_pool_ocupado_da_503_con_reintento(api, sql, monkeypatch):
    monkeypatch.setattr(settings, "DB_POOL_MAX", 2)
    monkeypatch.setattr(settings, "DB_POOL_TIMEOUT", 0.3)
    appdb.cerrar()
    a, b = appdb.pool().getconn(), appdb.pool().getconn()
    try:
        r = api.get("/me")
        assert r.status_code == 503 and r.json() == {"detail": "La base está ocupada; reintentá en unos segundos",
                                                     "codigo": "base_ocupada", "reintentar": True}
    finally:
        appdb.pool().putconn(a)
        appdb.pool().putconn(b)
    assert api.get("/me").status_code == 200
    monkeypatch.undo()
    appdb.cerrar()


def test_estado_con_carga_en_curso(api, sql):
    c = cargar(api, [fila(i) for i in range(3)], confirmar=False)
    assert api.get("/estado").json()["carga"] is None
    tid = sql.execute("INSERT INTO tarea (tipo, payload, creado_por, estado, mensaje) VALUES ('carga.confirmar', %s, 'x',"
                      " 'corriendo', 'Lote 2 de 5') RETURNING id", (psycopg.types.json.Jsonb({"carga_id": c["id"]}),)).fetchone()["id"]
    sql.execute("UPDATE carga SET estado = 'en_proceso', tarea_id = %s, lotes = 5 WHERE id = %s", (tid, c["id"]))
    e = api.get("/estado").json()
    assert e["carga"]["id"] == c["id"] and e["carga"]["lote"] == 1 and e["carga"]["lotes"] == 5


def test_pedido_lento_queda_en_el_log(api, sql, monkeypatch, caplog):
    monkeypatch.setattr(settings, "PEDIDO_LENTO_SEGUNDOS", 0)
    with caplog.at_level(logging.WARNING, logger="pedidos"):
        api.get("/inicio")
    assert any("pedido lento: GET /api/inicio" in m and "usuario=admin@equipos.com.uy" in m for m in caplog.messages)


# ─── P-6 · Volumen (lento): 200.000 empresas sintéticas ───

@pytest.mark.skipif(os.environ.get("RUN_LENTOS") != "1", reason="test de volumen: RUN_LENTOS=1")
def test_volumen_200k(api, sql):
    n = int(os.environ.get("VOLUMEN_EMPRESAS", 200000))
    reiniciar_base()
    sql.execute("SELECT 1")
    x = sql.execute
    x("INSERT INTO naturaleza_juridica (codigo, nombre) VALUES ('SRL', 'Sociedad de Responsabilidad Limitada')"
      " ON CONFLICT DO NOTHING")
    x("""INSERT INTO empresa (rut, razon_social, fantasia, departamento, tamano, ciiu, localidad, naturaleza_id, estado)
         SELECT (100000000 + g)::text,
                (ARRAY['Pérez','García','Rodríguez','López','Martínez','Fernández'])[1 + g %% 6] || ' ' || g ||
                (ARRAY[' SRL',' SA',' SAS',''])[1 + g %% 4],
                CASE WHEN g %% 5 = 0 THEN 'Fantasía ' || g END,
                (ARRAY['Montevideo','Canelones','Salto','Paysandú','Rivera','Maldonado','Colonia','Tacuarembó'])[1 + g %% 8],
                (ARRAY['Micro','Pequeña','Mediana','Grande'])[1 + g %% 4], lpad((g %% 97)::text, 4, '1'),
                'Localidad ' || (g %% 60), (SELECT id FROM naturaleza_juridica ORDER BY id LIMIT 1 OFFSET g %% 2),
                CASE WHEN g %% 50 = 0 THEN 'cerrada' ELSE 'activa' END
         FROM generate_series(1, %s) g""", (n,))
    x("INSERT INTO telefono (e164, crudo, tipo) SELECT '+5982' || lpad(g::text, 7, '0'), g::text, 'fijo'"
      " FROM generate_series(1, %s) g WHERE g %% 10 <> 0", (n,))
    x("INSERT INTO telefono_vinculo (telefono_id, empresa_id, fuente_tipo, fuente_id)"
      " SELECT t.id, e.id, 'manual', NULL FROM telefono t JOIN empresa e ON e.rut = (100000000 + t.crudo::int)::text")
    x("INSERT INTO empresa_campo_historia (empresa_id, campo, valor, fuente_tipo, confianza, actor)"
      " SELECT e.id, c, CASE WHEN c = 'naturaleza' THEN n.codigo ELSE 'v' END, 'manual', 50, 'test'"
      " FROM empresa e JOIN naturaleza_juridica n ON n.id = e.naturaleza_id CROSS JOIN unnest(ARRAY['razon_social',"
      " 'departamento', 'tamano', 'ciiu', 'naturaleza', 'localidad', 'telefono', 'direccion', 'web', 'fantasia']) c")
    mantenimiento.analizar(mantenimiento.TABLAS)
    # La tarea de mantenimiento llena la disponibilidad y los resúmenes (como después del despliegue)
    t0 = time.monotonic()
    with appdb.conexion() as c:
        tid = __import__("app.tareas", fromlist=["crear"]).crear(c, mantenimiento.TIPO, {"motivo": "test"}, "test")
    from app import tareas
    tareas.despachar(tid)
    llenado = time.monotonic() - t0
    assert sql.execute("SELECT estado FROM tarea WHERE id = %s", (tid,)).fetchone()["estado"] == "ok"
    assert sql.execute("SELECT count(*) AS n FROM empresa_disponibilidad").fetchone()["n"] == n
    sql.execute("ANALYZE empresas.empresa_disponibilidad")

    def medir(url, **params):
        api.get(url, params=params)                      # una vez para calentar
        t = time.monotonic()
        r = api.get(url, params=params)
        assert r.status_code == 200, r.text
        return time.monotonic() - t, r.json()

    tiempos = {}
    tiempos["pagina1"], r = medir("/empresas")
    assert r["aproximado"] is True and r["total"] == n
    tiempos["departamento"], _ = medir("/empresas", departamento="Salto")
    tiempos["srl"], _ = medir("/empresas", q="SRL")
    tiempos["perez"], _ = medir("/empresas", q="pérez")
    tiempos["disponibles"], _ = medir("/empresas", disponible="true", departamento="Rivera")
    cursor = r["siguiente"]
    for _ in range(48):
        cursor = api.get("/empresas", params={"despues": cursor}).json()["siguiente"]
    tiempos["pagina50"], _ = medir("/empresas", despues=cursor)
    tiempos["valores"], _ = medir("/empresas/valores")
    tiempos["naturalezas"], _ = medir("/naturalezas")
    tiempos["inicio"], _ = medir("/inicio")
    print(f"\nllenado inicial: {llenado:.1f} s · " + " · ".join(f"{k}={v * 1000:.0f} ms" for k, v in tiempos.items()))
    for k in ("pagina1", "departamento", "srl", "perez", "disponibles", "pagina50"):
        assert tiempos[k] < 1.5, (k, tiempos[k])
    assert tiempos["pagina50"] < max(3 * tiempos["pagina1"], 0.3)
    assert tiempos["valores"] < 0.3 and tiempos["naturalezas"] < 1 and tiempos["inicio"] < 1
    # Con las estadísticas al día, buscar por RUT usa el índice
    plan = "\n".join(r["QUERY PLAN"] for r in sql.execute("EXPLAIN SELECT * FROM empresa WHERE rut = '100000123'"))
    assert "Index" in plan
