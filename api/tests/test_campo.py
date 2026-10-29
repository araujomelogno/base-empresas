"""Iteraciones 3 y 4 — Campo: R1.8 a R1.11."""
import os
import tempfile

import pandas as pd
import pyreadstat

from conftest import cargar, rut_valido
from test_muestra import base, estudio, muestra

JOB = {"X-Job-Token": "token-job"}


def preparar(api, sql, n=10):
    base(api, n=n)
    e = estudio(api)
    mid, _ = muestra(api, e, {"n_por_estrato": n})
    items = sql.execute("SELECT i.id, e.rut, e.id AS empresa_id FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id"
                        " WHERE i.muestra_id = %s ORDER BY e.rut", (mid,)).fetchall()
    return e, mid, items


def lote(api, llamadas):
    r = api.c.post("/api/intentos/lote", headers=JOB, json={"origen": "test", "llamadas": llamadas})
    assert r.status_code == 200, r.text
    return r.json()


# ─── R1.8 CDR por número destino ───

def test_cdr_cruza_por_destino_e_ignora_internos(api, sql):
    e, mid, items = preparar(api, sql, n=4)
    ll = [
        {"cdr_id": "1", "inicio": "2026-10-26T11:00:00-03:00", "destino": "29000000", "encuestador": "SIP/ana",
         "duracion": 40, "userfield": "ATENDIO|COMPLETA", "campania": "Clima"},
        {"cdr_id": "2", "inicio": "2026-10-26T17:00:00-03:00", "destino": "099000001", "encuestador": "SIP/beto", "duracion": 5},
        {"cdr_id": "3", "inicio": "2026-10-26T12:00:00-03:00", "destino": "4501"},                      # interno
        {"cdr_id": "4", "inicio": "2026-10-26T12:00:00-03:00", "destino": "098765432"},                 # fuera de la base
        {"cdr_id": "5", "inicio": "2026-09-01T12:00:00-03:00", "destino": "29000002"},                  # fuera de campo
    ]
    r = lote(api, ll)
    assert (r["recibidas"], r["internas"], r["no_cruzan"], r["intentos_nuevos"], r["asociados_a_item"]) == (5, 1, 1, 3, 2)
    i1 = sql.execute("SELECT * FROM intento WHERE cdr_id = '1'").fetchone()
    assert i1["franja"] == "mañana" and i1["disposicion"] == "ATENDIO" and i1["disposicion_encuesta"] == "COMPLETA"
    assert i1["encuestador"] == "SIP/ana" and i1["campania"] == "Clima" and i1["item_id"] is not None
    assert sql.execute("SELECT franja FROM intento WHERE cdr_id = '2'").fetchone()["franja"] == "tarde"
    assert sql.execute("SELECT item_id FROM intento WHERE cdr_id = '5'").fetchone()["item_id"] is None
    # idempotente
    r2 = lote(api, ll)
    assert r2["intentos_nuevos"] == 0 and r2["duplicados"] == 3
    assert sql.execute("SELECT count(*) AS n FROM intento").fetchone()["n"] == 3


def test_cdr_token(api):
    assert api.c.post("/api/intentos/lote", json={"llamadas": []}).status_code == 401


def test_cdr_dos_muestras_activas_va_a_conciliacion(api, sql):
    e, mid, items = preparar(api, sql, n=2)
    # forzamos el caso que el bloqueo evita: la misma empresa en otra muestra activa
    m2 = sql.execute("INSERT INTO muestra (estudio_id, nombre, criterios, estado, creado_por) VALUES (%s, 'x', '{}', 'activa', 't')"
                     " RETURNING id", (e["id"],)).fetchone()["id"]
    sql.execute("INSERT INTO muestra_item (muestra_id, empresa_id, estrato, rol, orden, liberado) VALUES (%s, %s, 'Total', 'titular', 1, true)",
                (m2, items[0]["empresa_id"]))
    r = lote(api, [{"cdr_id": "9", "inicio": "2026-10-26T11:00:00-03:00", "destino": "29000000"}])
    assert r["a_conciliacion"] == 1
    c = api.get("/conciliacion?tipo=intento").json()
    assert len(c) == 1 and len(c[0]["candidatos_detalle"]) == 2
    item = c[0]["candidatos_detalle"][0]["id"]
    assert api.post(f"/conciliacion/{c[0]['id']}", rol="coordinador", json={"accion": "asociar", "item_id": item}).status_code == 200
    assert sql.execute("SELECT item_id FROM intento WHERE cdr_id = '9'").fetchone()["item_id"] == item


# ─── R1.9 Ingesta del .sav ───

def hacer_sav(filas: list[dict], etiquetas=True) -> bytes:
    df = pd.DataFrame(filas)
    labels = {}
    if etiquetas:
        labels = {"EC_CALIDAD_TEL": {1: "Corresponde", 2: "No es de la empresa", 3: "Estudio contable o jurídico",
                                     4: "La empresa cerró", 5: "Inexistente"},
                  "EC_RESULTADO": {1: "Completa", 2: "Rechazo", 3: "No corresponde", 4: "Agendada"}}
    fd, ruta = tempfile.mkstemp(suffix=".sav")
    os.close(fd)
    pyreadstat.write_sav(df, ruta, variable_value_labels={k: v for k, v in labels.items() if k in df.columns})
    with open(ruta, "rb") as f:
        datos = f.read()
    os.unlink(ruta)
    return datos


def fila_sav(rid, item, **kw):
    f = {"responseid": rid, "EC_ID_ITEM": item["id"], "EC_RUT": item["rut"], "EC_TEL_USADO": "", "EC_CALIDAD_TEL": 1,
         "EC_TEL_ALT": "", "EC_RESP_NOMBRE": "", "EC_RESP_CARGO": "", "EC_RESP_AREA": "", "EC_RESULTADO": 1,
         "status": "Complete", "datesubmitted": "2026-10-27 15:30:00"}
    f.update(kw)
    return f


def ingerir(api, parte_id, contenido, rol="coordinador", mapeo_mod=None):
    a = api.subir(f"/partes/{parte_id}/sav/analizar", "resultados.sav", contenido, rol=rol)
    assert a.status_code == 200, a.text
    a = a.json()
    mapeo = a["mapeo"]
    if mapeo_mod:
        mapeo_mod(mapeo)
    r = api.post(f"/partes/{parte_id}/sav", rol=rol, json={"ingesta_id": a["ingesta_id"], "mapeo": mapeo})
    assert r.status_code == 200, r.text
    return a, api.get(f"/sav/{a['ingesta_id']}").json()


def test_sav_propuesta_conteos_y_aplicacion(api, sql):
    e, mid, items = preparar(api, sql, n=4)
    parte = e["partes"][0]
    filas = [
        fila_sav(101, items[0], EC_TEL_USADO="29000000", EC_RESP_NOMBRE="Ana Gómez", EC_RESP_CARGO="Gerenta", EC_RESP_AREA="RRHH"),
        fila_sav(102, items[1], EC_TEL_USADO="29000001", EC_CALIDAD_TEL=3, EC_RESULTADO=3, EC_TEL_ALT="099 777 888"),
        fila_sav(103, items[2], EC_TEL_USADO="29000002", EC_CALIDAD_TEL=99, EC_RESULTADO=2),
        fila_sav(104, {"id": 99999, "rut": "123"}),
    ]
    a = api.subir(f"/partes/{parte['id']}/sav/analizar", "r.sav", hacer_sav(filas), rol="coordinador").json()
    m = a["mapeo"]
    assert m["response_id"] == "responseid"
    assert m["identificador"] == {"variable": "EC_ID_ITEM", "tipo": "id_item"}
    assert m["variables"]["calidad_tel"] == "EC_CALIDAD_TEL" and m["variables"]["fecha"] == "datesubmitted"
    assert m["valores"]["calidad_tel"]["3"] == "intermediario" and m["valores"]["calidad_tel"]["2"] == "no_corresponde"
    assert m["valores"]["resultado"]["1"] == "completa"
    k = a["conteos"]
    assert (k["asociadas"], k["sin_asociar"]) == (3, 1)
    assert "calidad_tel: el 99 quedó sin mapear: 1 filas" in k["avisos"]
    # nada se aplicó todavía
    assert sql.execute("SELECT count(*) AS n FROM sav_fila").fetchone()["n"] == 0
    # el coordinador mapea el 99 a "ignorar" y recuenta
    m["valores"]["calidad_tel"]["99"] = "ignorar"
    k2 = api.post(f"/sav/{a['ingesta_id']}/contar", rol="coordinador", json={"ingesta_id": a["ingesta_id"], "mapeo": m}).json()
    assert k2["avisos"] == []
    r = api.post(f"/partes/{parte['id']}/sav", rol="coordinador", json={"ingesta_id": a["ingesta_id"], "mapeo": m})
    assert r.status_code == 200
    ing = api.get(f"/sav/{a['ingesta_id']}").json()
    assert ing["estado"] == "confirmada" and ing["conteos"]["asociadas"] == 3
    # R1.10: contacto, intermediario confirmado, teléfono alternativo, estado por parte, último contacto
    ficha0 = api.get(f"/empresas/{items[0]['rut']}").json()
    assert ficha0["contactos"][0]["nombre"] == "Ana Gómez" and ficha0["contactos"][0]["area"] == "RRHH"
    assert {t["e164"]: t["estado"] for t in ficha0["telefonos"]}["+59829000000"] == "verificado"
    assert ficha0["ultimo_contacto_efectivo"].startswith("2026-10-27")
    ficha1 = api.get(f"/empresas/{items[1]['rut']}").json()
    tel1 = {t["e164"]: t for t in ficha1["telefonos"]}
    assert tel1["+59829000001"]["estado"] == "intermediario" and tel1["+59829000001"]["intermediario"] == "confirmado"
    assert tel1["+59899777888"]["estado"] == "sin_verificar" and tel1["+59899777888"]["fuente_tipo"] == "sala"
    estados = {r["item_id"]: r["estado"] for r in sql.execute("SELECT item_id, estado FROM item_parte_estado WHERE parte_id = %s",
                                                               (parte["id"],))}
    assert estados[items[0]["id"]] == "completa" and estados[items[1]["id"]] == "fuera_de_marco"
    assert estados[items[2]["id"]] == "rechazo"
    # linaje del cambio de vínculo: estudio, parte, encuestador, fecha
    h = sql.execute("SELECT detalle FROM telefono_vinculo_historia WHERE fuente_tipo = 'sala' AND estado = 'intermediario'").fetchone()
    assert h["detalle"]["estudio_id"] == e["id"] and h["detalle"]["parte_id"] == parte["id"]
    # fila sin asociar → conciliación, con el crudo guardado
    c = api.get("/conciliacion?tipo=sav_fila").json()
    assert len(c) == 1 and c[0]["objeto"]["valores"]["responseid"] == 104
    # el mapeo quedó como plantilla de la parte
    assert sql.execute("SELECT plantilla_mapeo FROM parte WHERE id = %s", (parte["id"],)).fetchone()["plantilla_mapeo"] == m


def test_sav_idempotente(api, sql):
    e, mid, items = preparar(api, sql, n=2)
    parte = e["partes"][0]
    contenido = hacer_sav([fila_sav(1, items[0], EC_TEL_ALT="099 123 999"), fila_sav(2, items[1])])
    ingerir(api, parte["id"], contenido)
    _, ing2 = ingerir(api, parte["id"], contenido)
    assert ing2["conteos"]["ya_ingeridas"] == 2
    assert sql.execute("SELECT count(*) AS n FROM sav_fila").fetchone()["n"] == 2
    assert sql.execute("SELECT count(*) AS n FROM telefono WHERE e164 = '+59899123999'").fetchone()["n"] == 1
    hist = sql.execute("SELECT count(*) AS n FROM telefono_vinculo_historia WHERE fuente_tipo = 'sala'").fetchone()["n"]
    _, ing3 = ingerir(api, parte["id"], contenido)
    assert sql.execute("SELECT count(*) AS n FROM telefono_vinculo_historia WHERE fuente_tipo = 'sala'").fetchone()["n"] == hist


def test_sav_plantilla_precargada_y_remapeo(api, sql):
    e, mid, items = preparar(api, sql, n=2)
    parte = e["partes"][0]
    # sin etiquetas en el archivo: el mapeo declarado gana
    filas = [fila_sav(1, items[0], EC_RESULTADO=7), fila_sav(2, items[1], EC_RESULTADO=8)]
    a, ing = ingerir(api, parte["id"], hacer_sav(filas, etiquetas=False))
    assert ing["conteos"]["sin_mapear"]["resultado"] == {"7": 1, "8": 1}
    # el crudo quedó guardado: se corrige el mapeo sin volver a subir el archivo
    m = ing["mapeo"]
    m["valores"]["resultado"] = {"7": "completa", "8": "rechazo"}
    r = api.post(f"/sav/{a['ingesta_id']}/remapear", rol="coordinador", json={"ingesta_id": a["ingesta_id"], "mapeo": m})
    assert r.status_code == 200, r.text
    estados = {r["estado"] for r in sql.execute("SELECT estado FROM item_parte_estado WHERE parte_id = %s", (parte["id"],))}
    assert estados == {"completa", "rechazo"}
    # la próxima ola trae el mapeo precargado
    a2 = api.subir(f"/partes/{parte['id']}/sav/analizar", "ola2.sav", hacer_sav([fila_sav(3, items[0], EC_RESULTADO=7)], etiquetas=False),
                   rol="coordinador").json()
    assert a2["origen_mapeo"] == "plantilla de la parte" and a2["mapeo"]["valores"]["resultado"]["7"] == "completa"


def test_sav_sin_id_item_usa_rut(api, sql):
    e, mid, items = preparar(api, sql, n=2)
    parte = e["partes"][0]
    filas = [{k: v for k, v in fila_sav(1, items[0]).items() if k != "EC_ID_ITEM"}]
    a, ing = ingerir(api, parte["id"], hacer_sav(filas))
    assert a["mapeo"]["identificador"] == {"variable": "EC_RUT", "tipo": "rut"}
    assert ing["conteos"]["asociadas"] == 1


def test_empresa_cerro_desde_sala(api, sql):
    e, mid, items = preparar(api, sql, n=1)
    ingerir(api, e["partes"][0]["id"], hacer_sav([fila_sav(1, items[0], EC_CALIDAD_TEL=4, EC_RESULTADO=3)]))
    assert api.get(f"/empresas/{items[0]['rut']}").json()["estado"] == "cerrada"
    # una carga posterior no lo pisa
    cargar(api, [{"RUT": items[0]["rut"], "Estado": "activa"}], confianza=99)
    assert api.get(f"/empresas/{items[0]['rut']}").json()["estado"] == "cerrada"


def test_conciliacion_sav(api, sql):
    e, mid, items = preparar(api, sql, n=2)
    parte = e["partes"][0]
    filas = [fila_sav(1, {"id": 999, "rut": "1"}, EC_RESP_NOMBRE="Luis")]
    ingerir(api, parte["id"], hacer_sav(filas))
    c = api.get("/conciliacion?tipo=sav_fila").json()[0]
    r = api.post(f"/conciliacion/{c['id']}", rol="coordinador", json={"accion": "asociar", "item_id": items[1]["id"]})
    assert r.status_code == 200, r.text
    assert api.get(f"/empresas/{items[1]['rut']}").json()["contactos"][0]["nombre"] == "Luis"


# ─── R1.11 Actividad ───

def test_tablero_y_linea_de_tiempo(api, sql):
    e, mid, items = preparar(api, sql, n=3)
    lote(api, [{"cdr_id": str(i), "inicio": f"2026-10-2{6 + i % 2}T1{i}:00:00-03:00", "destino": f"2900000{i % 3}",
                "encuestador": "ana" if i % 2 else "beto", "userfield": "ATENDIO|"} for i in range(6)])
    ingerir(api, e["partes"][0]["id"], hacer_sav([fila_sav(1, items[0], encuestador="ana")]))
    t = api.get(f"/actividad?estudio_id={e['id']}").json()
    assert t["intentos"] == 6 and t["telefonos_marcados"] == 3 and t["empresas_llamadas"] == 3
    assert t["completas"] == 1
    assert sum(f["intentos"] for f in t["por_franja"]) == 6
    assert {x["encuestador"] for x in t["por_encuestador"]} >= {"ana", "beto"}
    t2 = api.get("/actividad?encuestador=ana").json()
    assert t2["intentos"] == 3
    tl = api.get(f"/empresas/{items[0]['rut']}").json()["linea_de_tiempo"]
    assert {x["tipo"] for x in tl} >= {"dato", "llamada", "muestra", "teléfono"}


def test_metricas_de_asociacion(api, sql):
    """Métricas de la fase 1: ≥95% de filas del .sav y de llamadas a la muestra asociadas sin trabajo manual."""
    e, mid, items = preparar(api, sql, n=20)
    lote(api, [{"cdr_id": f"c{i}", "inicio": "2026-10-28T11:00:00-03:00", "destino": f"2900{i:04d}"} for i in range(20)])
    ingerir(api, e["partes"][0]["id"], hacer_sav([fila_sav(i, it) for i, it in enumerate(items)]))
    llamadas = sql.execute("SELECT count(*) FILTER (WHERE item_id IS NOT NULL)::float / count(*) AS p FROM intento").fetchone()["p"]
    filas = sql.execute("SELECT count(*) FILTER (WHERE item_id IS NOT NULL)::float / count(*) AS p FROM sav_fila").fetchone()["p"]
    assert llamadas >= 0.95 and filas >= 0.95
