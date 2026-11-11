"""Borrado definitivo de empresas y cargas (solo administrador)."""
import pytest

from conftest import cargar, rut_valido
from test_base import fila
from test_campo import fila_sav, hacer_sav, ingerir, lote, preparar


def cuenta(sql, tabla, where="true", args=()):
    return sql.execute(f"SELECT count(*) AS n FROM {tabla} WHERE {where}", args).fetchone()["n"]


def test_borrar_empresa_solo_admin(api, sql):
    cargar(api, [fila(0), fila(1)])
    assert api.delete(f"/empresas/{rut_valido(0)}", rol="steward").status_code == 403
    r = api.delete(f"/empresas/{rut_valido(0)}", rol="admin")
    assert r.status_code == 200, r.text
    assert r.json()["empresas"] == 1
    assert api.get(f"/empresas/{rut_valido(0)}").status_code == 404
    assert api.get(f"/empresas/{rut_valido(1)}").status_code == 200
    assert cuenta(sql, "empresa_campo_historia h JOIN empresa e ON e.id = h.empresa_id", "e.rut = %s", (rut_valido(0),)) == 0
    # el teléfono que solo era de esa empresa también se fue; la auditoría queda
    assert cuenta(sql, "telefono", "crudo LIKE %s", ("29000000%",)) == 0
    a = sql.execute("SELECT * FROM auditoria WHERE accion = 'empresa.borrar'").fetchone()
    assert a["objeto_id"] == rut_valido(0)


def test_historia_sigue_append_only_fuera_del_borrado(api, sql):
    cargar(api, [fila(0)])
    with pytest.raises(Exception):
        sql.execute("DELETE FROM empresa_campo_historia")
    sql.execute("BEGIN")
    sql.execute("SET LOCAL empresas.purga = 'on'")
    with pytest.raises(Exception):
        sql.execute("DELETE FROM auditoria")  # la auditoría nunca se borra
    sql.execute("ROLLBACK")


def test_borrar_empresa_en_muestra_con_campo(api, sql):
    e, mid, items = preparar(api, sql, n=4)
    lote(api, [{"cdr_id": "1", "inicio": "2026-10-26T11:00:00-03:00", "destino": "29000000", "duracion": 30}])
    parte = e["partes"][0]
    ingerir(api, parte["id"], hacer_sav([fila_sav(101, items[0], EC_TEL_USADO="29000000")]))
    assert cuenta(sql, "intento") == 1 and cuenta(sql, "sav_fila") == 1
    r = api.delete(f"/empresas/{items[0]['rut']}")
    assert r.status_code == 200, r.text
    k = r.json()
    assert (k["items_de_muestra"], k["intentos"], k["filas_sav"]) == (1, 1, 1)
    assert cuenta(sql, "muestra_item", "muestra_id = %s", (mid,)) == len(items) - 1
    assert cuenta(sql, "intento") == 0 and cuenta(sql, "sav_fila") == 0


def test_borrar_empresa_arrastra_las_fusionadas(api, sql):
    cargar(api, [fila(0), fila(1, **{"Teléfono": "29001111"})])
    r = api.post(f"/empresas/{rut_valido(0)}/fusionar", rol="steward", json={"rut_absorbida": rut_valido(1), "motivo": "misma"})
    assert r.status_code == 200, r.text
    r = api.delete(f"/empresas/{rut_valido(0)}")
    assert r.json()["empresas"] == 2
    assert cuenta(sql, "empresa") == 0 and cuenta(sql, "empresa_fusion") == 0


def borrar_carga(api, cid, rol="admin"):
    r = api.delete(f"/cargas/{cid}/definitivo", rol=rol)
    assert r.status_code == 200, r.text
    t = api.get(f"/tareas/{r.json()['tarea_id']}").json()
    assert t["estado"] == "ok", t
    return t["resultado"]


def test_borrar_carga_confirmada(api, sql):
    c1 = cargar(api, [fila(0)], confianza=50)
    c2 = cargar(api, [fila(0, **{"Razón social": "Cambiada SA"}), fila(1)], confianza=60)
    assert api.delete(f"/cargas/{c2['id']}/definitivo", rol="steward").status_code == 403
    r = borrar_carga(api, c2["id"])
    assert (r["empresas_borradas"], r["empresas_recalculadas"]) == (1, 1)
    assert api.get(f"/cargas/{c2['id']}").status_code == 404
    assert api.get(f"/empresas/{rut_valido(1)}").status_code == 404
    e0 = api.get(f"/empresas/{rut_valido(0)}").json()
    assert e0["razon_social"] == "Empresa 0 SA"
    assert all(h["fuente_id"] == c1["id"] for h in e0["historia"] if h["fuente_tipo"] == "carga")
    assert cuenta(sql, "carga") == 1


def test_borrar_carga_con_empresas_en_muestra(api, sql):
    """Deshacer queda bloqueado; borrar la elimina junto con su paso por la muestra."""
    e, mid, items = preparar(api, sql, n=4)
    cid = sql.execute("SELECT max(id) AS id FROM carga").fetchone()["id"]
    r = api.delete(f"/cargas/{cid}", rol="steward")
    assert r.status_code == 409 and "Borrar carga" in r.json()["detail"]
    lote(api, [{"cdr_id": "1", "inicio": "2026-10-26T11:00:00-03:00", "destino": "29000000", "duracion": 30}])
    res = borrar_carga(api, cid)
    assert res["empresas_borradas"] == 4 and res["intentos"] == 1
    assert cuenta(sql, "empresa") == 0 and cuenta(sql, "muestra_item") == 0 and cuenta(sql, "telefono") == 0
    assert cuenta(sql, "archivo a JOIN carga c ON c.archivo_id = a.id") == 0


def test_borrar_carga_en_preview_y_deshecha(api, sql):
    c = cargar(api, [fila(0)], confirmar=False)
    borrar_carga(api, c["id"])
    assert cuenta(sql, "carga") == 0 and cuenta(sql, "empresa") == 0
    c = cargar(api, [fila(0)])
    assert api.delete(f"/cargas/{c['id']}", rol="steward").status_code == 200
    assert sql.execute("SELECT baja FROM empresa").fetchone()["baja"] == "anulada"
    borrar_carga(api, c["id"])
    assert cuenta(sql, "empresa") == 0 and cuenta(sql, "carga") == 0
