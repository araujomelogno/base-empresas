"""Naturalezas jurídicas: editar el nombre y la exclusión, y borrar las que ninguna empresa usa ni usó."""
from conftest import cargar, rut_valido


def nat(api, codigo):
    return next((n for n in api.get("/naturalezas").json() if n["codigo"] == codigo), None)


def test_editar_nombre_y_exclusion(api, sql):
    antes = api.get("/config").json()["version"]
    r = api.put("/naturalezas/srl", json={"nombre": "Sociedad de Responsabilidad Limitada"})
    assert r.status_code == 200, r.text
    assert nat(api, "SRL")["nombre"] == "Sociedad de Responsabilidad Limitada"
    assert api.get("/config").json()["version"] == antes   # cambiar el nombre no crea versión
    r = api.put("/naturalezas/SRL", json={"excluida": True})
    assert r.status_code == 200 and r.json()["config_version"] == antes + 1
    assert nat(api, "SRL")["excluida"] is True
    assert "SRL" in api.get("/config").json()["parametros"]["naturalezas_excluidas"]
    audit = sql.execute("SELECT detalle FROM auditoria WHERE accion = 'naturaleza.editar' ORDER BY id").fetchall()
    assert audit[0]["detalle"]["nombre"]["despues"] == "Sociedad de Responsabilidad Limitada"
    assert audit[1]["detalle"]["excluida"] == {"antes": False, "despues": True}
    # Nombre vacío o repetido
    assert api.put("/naturalezas/SRL", json={"nombre": "  "}).status_code == 422
    assert api.put("/naturalezas/SRL", json={"nombre": "sociedad anónima"}).status_code == 409
    assert api.put("/naturalezas/NOEXISTE", json={"nombre": "X"}).status_code == 404
    # Solo el administrador
    assert api.put("/naturalezas/SRL", rol="steward", json={"nombre": "X"}).status_code == 403


def test_borrar_solo_si_no_se_usa(api, sql):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Uno SA", "Naturaleza": "SA"}])
    lista = {n["codigo"]: n for n in api.get("/naturalezas").json()}
    assert lista["SA"]["borrable"] is False and lista["SA"]["empresas"] == 1
    assert lista["FID"]["borrable"] is True
    r = api.delete("/naturalezas/SA")
    assert r.status_code == 409 and "1 empresas" in r.json()["detail"]
    assert api.delete("/naturalezas/FID", rol="steward").status_code == 403
    r = api.delete("/naturalezas/FID")
    assert r.status_code == 200, r.text
    assert nat(api, "FID") is None
    assert sql.execute("SELECT detalle FROM auditoria WHERE accion = 'naturaleza.borrar'").fetchone()["detalle"]["nombre"] == "Fideicomiso"


def test_no_se_borra_si_figura_en_la_historia(api, sql):
    # La empresa tuvo SAS y después cambió a SA: SAS ya no la tiene nadie, pero figura en la historia
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Uno", "Naturaleza": "SAS"}], confianza=40)
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Uno", "Naturaleza": "SA"}], confianza=60, fuente="Otra base")
    sas = nat(api, "SAS")
    assert sas["empresas"] == 0 and sas["historia"] == 1 and sas["borrable"] is False
    r = api.delete("/naturalezas/SAS")
    assert r.status_code == 409 and "historia" in r.json()["detail"]


def test_borrar_una_excluida_la_saca_de_la_configuracion(api, sql):
    api.put("/naturalezas/GD", json={"excluida": True})
    version = api.get("/config").json()["version"]
    r = api.delete("/naturalezas/GD")
    assert r.status_code == 200 and r.json()["config_version"] == version + 1
    assert "GD" not in api.get("/config").json()["parametros"]["naturalezas_excluidas"]


def test_post_sigue_creando_y_actualizando(api, sql):
    # La pantalla crea con POST; la demo y fase0/cargar_excluidos.py lo usan también para actualizar
    r = api.post("/naturalezas", json={"codigo": "coopsoc", "nombre": "Cooperativa social"})
    assert r.status_code == 200 and nat(api, "COOPSOC")["nombre"] == "Cooperativa social"
    r = api.post("/naturalezas", json={"codigo": "COOPSOC", "nombre": "Cooperativa social (ley 17.978)", "excluida": True})
    assert r.status_code == 200 and nat(api, "COOPSOC")["excluida"] is True
    acciones = [x["accion"] for x in sql.execute("SELECT accion FROM auditoria WHERE objeto = 'naturaleza_juridica' ORDER BY id")]
    assert acciones == ["naturaleza.crear", "naturaleza.guardar"]
    assert api.post("/naturalezas", json={"codigo": " ", "nombre": "X"}).status_code == 422
