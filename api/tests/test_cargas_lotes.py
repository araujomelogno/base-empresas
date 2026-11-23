"""SPEC_cargas_grandes_por_lotes (D50): preview, confirmación, deshacer y borrado por lotes; cargas interrumpidas,
reanudar y una carga pesada a la vez. Los tests corren con lotes de 2 filas (conftest), así toda carga tiene varios."""
import os
import time

import pytest

from conftest import cargar, csv_bytes, rut_valido


def fila(i, **extra):
    return {"RUT": rut_valido(i), "Razón social": f"Empresa {i}", "Teléfono": f"2900{i:04d}", "Departamento": "Salto",
            **extra}


def cuenta(sql, tabla, where="TRUE"):
    return sql.execute(f"SELECT count(*) AS n FROM {tabla} WHERE {where}").fetchone()["n"]


def carga(api, cid):
    return api.get(f"/cargas/{cid}").json()


CLAVES = ("altas", "actualizaciones", "sin_cambios", "rechazos", "telefonos_nuevos", "vinculos_nuevos", "filas",
          "conflictos", "rut_repetido_en_archivo")


# ─── L1 · El archivo se lee una sola vez ───

def test_el_archivo_se_parsea_una_vez_y_se_libera(api, sql, monkeypatch):
    from app import lectores

    llamadas = []
    original = lectores.iterar_tabla
    monkeypatch.setattr(lectores, "iterar_tabla", lambda *x, **k: llamadas.append(1) or original(*x, **k))
    a = api.subir("/cargas/analizar", "b.csv", csv_bytes([fila(i) for i in range(7)]), rol="steward").json()
    r = api.post("/cargas", rol="steward", json={"archivo_id": a["archivo_id"], "fuente": "x", "tipo_fuente": "x",
                                                 "licencia": "interna", "mapeo": {**a["mapeo"], "origen_defecto": "sin_dato"}})
    cid = r.json()["carga_id"]
    assert carga(api, cid)["lotes"] == 4                        # 7 filas en lotes de 2, armados por el preview
    assert cuenta(sql, "carga_fila", f"carga_id = {cid}") == 7  # se conserva mientras está en preview
    assert cuenta(sql, "archivo_fila", f"archivo_id = {a['archivo_id']}") == 7
    api.post(f"/cargas/{cid}/confirmar", rol="steward")
    assert len(llamadas) == 1                                   # analizar + crear + preview + confirmación: una lectura
    assert carga(api, cid)["estado"] == "confirmada"
    assert cuenta(sql, "carga_fila", f"carga_id = {cid}") == 0  # al confirmar se libera
    assert cuenta(sql, "archivo_fila", f"archivo_id = {a['archivo_id']}") == 0


# ─── L2 / L3 · Preview y confirmación por lotes ───

def test_mismo_rut_lejos_cuenta_una_alta_y_el_preview_coincide(api, sql):
    filas = [fila(i) for i in range(9)] + [fila(0, **{"Razón social": "Empresa 0 (repetida)"})]
    c = cargar(api, filas, confirmar=False)
    preview = c["conteos"]
    assert preview["altas"] == 9 and preview["rut_repetido_en_archivo"] == 1
    lotes = sql.execute("SELECT cf.lote FROM carga_fila cf JOIN archivo_fila af ON af.fila = cf.fila"
                        " AND af.archivo_id = (SELECT archivo_id FROM carga WHERE id = cf.carga_id)"
                        " WHERE cf.carga_id = %s AND af.datos->>'RUT' = %s ORDER BY cf.fila", (c["id"], rut_valido(0))).fetchall()
    assert len(lotes) == 2 and len({l["lote"] for l in lotes}) == 1   # la fila 2 y la fila 11 van en el mismo lote
    api.post(f"/cargas/{c['id']}/confirmar", rol="steward")
    final = carga(api, c["id"])
    assert final["estado"] == "confirmada" and final["conteos"]["lotes"] == c["lotes"]
    assert {k: final["conteos"].get(k) for k in CLAVES} == {k: preview.get(k) for k in CLAVES}
    assert cuenta(sql, "empresa") == 9
    assert final["lotes_detalle"]["aplicados"] == final["lotes_detalle"]["total"] == c["lotes"]
    assert sql.execute("SELECT count(*) AS n FROM auditoria WHERE accion = 'carga.confirmar'").fetchone()["n"] == 1


def test_reintentar_una_tarea_terminada_no_duplica(api, sql):
    from app import tareas

    c = cargar(api, [fila(i) for i in range(5)])
    tid = c["tarea"]["id"]
    antes = (cuenta(sql, "empresa_campo_historia"), cuenta(sql, "telefono_vinculo"))
    sql.execute("UPDATE tarea SET estado = 'pendiente' WHERE id = %s", (tid,))   # Cloud Tasks la vuelve a entregar
    tareas.ejecutar(tid)
    assert (cuenta(sql, "empresa_campo_historia"), cuenta(sql, "telefono_vinculo")) == antes


# ─── L4 · Interrumpida, reanudar, deshacer ───

def _falla_en_lote(monkeypatch, rut_que_falla):
    from app import cargas as cargas_mod

    original = cargas_mod.procesar
    estado = {"fallo": False}

    def procesar(conn, carga, filas, *a, **k):
        if k.get("real", a[2] if len(a) > 2 else False) and not estado["fallo"] and any(
                f.get("RUT") == rut_que_falla for _, f in filas):
            estado["fallo"] = True
            raise RuntimeError("falla forzada en el lote 5")
        return original(conn, carga, filas, *a, **k)

    monkeypatch.setattr(cargas_mod, "procesar", procesar)


def test_interrumpida_y_reanudar(api, sql, monkeypatch):
    c = cargar(api, [fila(i) for i in range(20)], confirmar=False)   # 10 lotes
    assert c["lotes"] == 10
    _falla_en_lote(monkeypatch, rut_valido(8))                         # filas 8 y 9: lote 5
    with pytest.raises(RuntimeError):
        api.post(f"/cargas/{c['id']}/confirmar", rol="steward")
    x = carga(api, c["id"])
    assert x["estado"] == "interrumpida" and x["operacion"] == "confirmar"
    assert x["lotes_detalle"]["aplicados"] == 4 and "falla forzada" in x["lotes_detalle"]["error_lote"]
    assert cuenta(sql, "empresa") == 8                                 # lo de los 4 lotes aplicados queda
    r = api.post(f"/cargas/{c['id']}/reanudar", rol="steward")
    assert r.status_code == 200, r.text
    x = carga(api, c["id"])
    assert x["estado"] == "confirmada" and x["lotes_detalle"]["aplicados"] == 10
    assert cuenta(sql, "empresa") == 20 and cuenta(sql, "telefono_vinculo") == 20
    assert {k: x["conteos"].get(k) for k in CLAVES} == {k: c["conteos"].get(k) for k in CLAVES}


def test_deshacer_una_interrumpida_deja_la_base_como_antes(api, sql, monkeypatch):
    cargar(api, [fila(100)])                                           # una empresa de antes, que no se toca
    antes = {t: cuenta(sql, t) for t in ("empresa", "telefono_vinculo", "telefono_vinculo_origen")}
    c = cargar(api, [fila(i) for i in range(10)], confirmar=False)
    _falla_en_lote(monkeypatch, rut_valido(6))
    with pytest.raises(RuntimeError):
        api.post(f"/cargas/{c['id']}/confirmar", rol="steward")
    assert carga(api, c["id"])["estado"] == "interrumpida"
    r = api.delete(f"/cargas/{c['id']}", rol="steward")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "deshecha" and r.json()["empresas_anuladas"] == 6
    assert cuenta(sql, "empresa", "baja IS NULL") == antes["empresa"]
    assert cuenta(sql, "telefono_vinculo") == antes["telefono_vinculo"]
    assert cuenta(sql, "telefono_vinculo_origen") == antes["telefono_vinculo_origen"]
    assert cuenta(sql, "carga_fila", f"carga_id = {c['id']}") == 0


def test_tarea_trabada_se_retoma_sola_una_vez_y_despues_queda_interrumpida(api, sql, monkeypatch):
    """D52: una tarea sin latido más que el plazo (10 min) se vuelve a encolar sola; si se corta de nuevo, la carga
    queda «interrumpida» y ofrece Reanudar."""
    from app import tareas

    c = cargar(api, [fila(i) for i in range(4)], confirmar=False)
    monkeypatch.setattr(tareas, "despachar", lambda tid, demora=0: None)   # la instancia murió a mitad de camino
    tid = api.post(f"/cargas/{c['id']}/confirmar", rol="steward").json()["tarea_id"]
    monkeypatch.undo()
    sql.execute("UPDATE tarea SET estado = 'corriendo', actualizado = now() - interval '15 minutes' WHERE id = %s", (tid,))
    x = carga(api, c["id"])                                            # la pantalla revisa las trabadas: la retoma
    assert x["estado"] == "confirmada" and cuenta(sql, "empresa") == 4

    c = cargar(api, [fila(i) for i in range(10, 14)], confirmar=False)
    monkeypatch.setattr(tareas, "despachar", lambda tid, demora=0: None)
    tid = api.post(f"/cargas/{c['id']}/confirmar", rol="steward").json()["tarea_id"]
    monkeypatch.undo()
    sql.execute("UPDATE tarea SET estado = 'corriendo', reintentos_auto = 1, actualizado = now() - interval '15 minutes'"
                " WHERE id = %s", (tid,))                              # ya se retomó una vez y se volvió a cortar
    x = carga(api, c["id"])
    assert x["estado"] == "interrumpida" and "no avanzó" in x["error"]
    assert api.post(f"/cargas/{c['id']}/reanudar", rol="steward").status_code == 200
    assert carga(api, c["id"])["estado"] == "confirmada" and cuenta(sql, "empresa") == 8


def test_cancelar_deja_la_carga_interrumpida(api, sql, monkeypatch):
    from app import cargas as cargas_mod, tareas

    c = cargar(api, [fila(i) for i in range(8)], confirmar=False)
    original = cargas_mod.procesar
    vistos = []

    def procesar(conn, carga, filas, *a, **k):
        vistos.append(1)
        if len(vistos) == 3:   # en el tercer lote se pide cancelar: ese lote se revierte
            tareas.cancelar("tipo = 'carga.confirmar'", (), "Cancelada por la persona")
        return original(conn, carga, filas, *a, **k)

    monkeypatch.setattr(cargas_mod, "procesar", procesar)
    api.post(f"/cargas/{c['id']}/confirmar", rol="steward")
    x = carga(api, c["id"])
    assert x["estado"] == "interrumpida" and x["lotes_detalle"]["aplicados"] == 2
    assert cuenta(sql, "empresa") == 4


# ─── Una carga pesada a la vez ───

def test_una_carga_pesada_a_la_vez(api, sql, monkeypatch):
    from app import tareas

    c1 = cargar(api, [fila(i) for i in range(4)], confirmar=False, nombre="a.csv")
    c2 = cargar(api, [fila(i) for i in range(10, 14)], confirmar=False, nombre="b.csv")
    monkeypatch.setattr(tareas, "despachar", lambda tid, demora=0: None)
    t1 = api.post(f"/cargas/{c1['id']}/confirmar", rol="steward").json()
    monkeypatch.undo()
    r2 = api.post(f"/cargas/{c2['id']}/confirmar", rol="steward").json()
    assert r2["en_cola"] is True and r2["esperando"] == c1["id"]
    x2 = carga(api, c2["id"])
    assert x2["estado"] == "en_proceso" and x2["tarea"]["mensaje"] == f"Esperando a que termine la carga #{c1['id']}"
    assert cuenta(sql, "empresa") == 0
    tareas.despachar(t1["tarea_id"])     # termina la primera y arranca sola la segunda
    assert carga(api, c1["id"])["estado"] == "confirmada"
    assert carga(api, c2["id"])["estado"] == "confirmada" and cuenta(sql, "empresa") == 8


# ─── L5 · Deshacer y borrar por pasos ───

def test_deshacer_por_pasos(api, sql):
    c = cargar(api, [fila(i) for i in range(6)])
    r = api.delete(f"/cargas/{c['id']}", rol="steward").json()
    assert r["estado"] == "deshecha" and r["empresas_anuladas"] == 6 and r["vinculos_borrados"] == 6
    t = api.get(f"/tareas/{r['tarea_id']}").json()
    assert t["estado"] == "ok" and t["tipo"] == "carga.deshacer"
    assert cuenta(sql, "empresa", "baja IS NULL") == 0 and cuenta(sql, "telefono_vinculo") == 0


def test_borrar_interrumpido_se_retoma(api, sql, monkeypatch):
    from app import borrado

    c = cargar(api, [fila(i) for i in range(6)])
    original = borrado.borrar_empresas
    estado = {"fallo": False}

    def borrar_empresas(conn, ids, *a, **k):
        if not estado["fallo"]:
            estado["fallo"] = True
            raise RuntimeError("se cortó el borrado")
        return original(conn, ids, *a, **k)

    monkeypatch.setattr(borrado, "borrar_empresas", borrar_empresas)
    with pytest.raises(RuntimeError):
        api.delete(f"/cargas/{c['id']}/definitivo")
    x = carga(api, c["id"])
    assert x["estado"] == "borrando" and "se cortó" in x["error"]
    r = api.delete(f"/cargas/{c['id']}/definitivo")                   # volver a pedirlo retoma
    assert r.status_code == 200, r.text
    t = api.get(f"/tareas/{r.json()['tarea_id']}").json()
    assert t["estado"] == "ok" and t["resultado"]["empresas_borradas"] == 6
    assert api.get(f"/cargas/{c['id']}").status_code == 404
    assert cuenta(sql, "empresa") == 0 and cuenta(sql, "empresa_campo_historia") == 0


# ─── L6 · Configuración ───

def test_configuracion_de_cargas(api, sql):
    cfg = api.get("/config").json()["parametros"]
    assert cfg["cargas"] == {"tamano_lote": 5000, "pausa_segundos": 1.0, "minutos_trabada": 10,
                             "aceptar_rut_no_verificado": True}
    cfg["cargas"]["tamano_lote"] = 100
    assert api.put("/config", json={"parametros": cfg}).status_code == 422          # mínimo 500
    cfg["cargas"]["tamano_lote"] = 2000
    assert api.put("/config", json={"parametros": cfg}).status_code == 200


# ─── Volumen (lento: RUN_LENTOS=1) ───

@pytest.mark.skipif(not os.environ.get("RUN_LENTOS"), reason="test de volumen: correr con RUN_LENTOS=1")
def test_volumen_50000_filas(api, sql, monkeypatch):
    from app import settings

    monkeypatch.setattr(settings, "CARGAS_TAMANO_LOTE", 5000)
    from app import rut as rutmod

    def ruts(n):   # rut_valido(i) recorre desde el principio cada vez: acá se generan en una sola pasada
        i = 100000
        while n:
            base = f"21{i:06d}001"
            dv = rutmod.digito_verificador(base)
            if dv is not None:
                n -= 1
                yield base + str(dv)
            i += 1

    filas = [{"RUT": r, "Razón social": f"Empresa {i}", "Teléfono": f"2{i:07d}", "Departamento": "Salto",
              "Tamaño": "Pyme"} for i, r in enumerate(ruts(50000))]
    t0 = time.monotonic()
    c = cargar(api, filas)
    total = time.monotonic() - t0
    lotes = sql.execute("SELECT numero, filas, segundos, preview_segundos, consultas, preview_consultas FROM carga_lote"
                        " WHERE carga_id = %s ORDER BY numero", (c["id"],)).fetchall()
    filas_s = lambda seg: [round(l["filas"] / float(l[seg])) for l in lotes]   # noqa: E731
    print(f"\n50.000 filas: {total:.0f} s en total; segundos por lote: preview {[float(l['preview_segundos']) for l in lotes]},"
          f" confirmación {[float(l['segundos']) for l in lotes]}; filas por segundo: preview {filas_s('preview_segundos')},"
          f" confirmación {filas_s('segundos')}; consultas por fila: preview "
          f"{sum(l['preview_consultas'] for l in lotes) / 50000:.3f}, confirmación {sum(l['consultas'] for l in lotes) / 50000:.3f}")
    assert c["estado"] == "confirmada" and cuenta(sql, "empresa") == 50000
    assert max(max(float(l["segundos"]), float(l["preview_segundos"])) for l in lotes) < 180   # meta: < 3 min por lote
    assert sum(l["consultas"] for l in lotes) / 50000 < 0.1                                    # D53: < 0,1 por fila
