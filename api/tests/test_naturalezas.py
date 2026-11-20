"""Naturalezas jurídicas: editar el nombre y la exclusión, corregir el código si no se usa, y borrar las que ninguna
empresa usa ni usó. Las rutas van por id: una naturaleza vieja puede tener el código vacío."""
from conftest import cargar, rut_valido


def nat(api, codigo):
    return next((n for n in api.get("/naturalezas").json() if n["codigo"] == codigo), None)


def url(api, codigo):
    return f"/naturalezas/{nat(api, codigo)['id']}"


def sin_codigo(sql, nombre="Sin código (vieja)", excluida=False):
    """Como las que dejó el alta anterior, que no validaba el código (0014 no deja crear más)."""
    sql.execute("ALTER TABLE naturaleza_juridica DROP CONSTRAINT naturaleza_codigo_no_vacio")
    nid = sql.execute("INSERT INTO naturaleza_juridica (codigo, nombre, excluida) VALUES ('', %s, %s) RETURNING id",
                      (nombre, excluida)).fetchone()["id"]
    sql.execute("ALTER TABLE naturaleza_juridica ADD CONSTRAINT naturaleza_codigo_no_vacio CHECK (btrim(codigo) <> '') NOT VALID")
    return nid


def test_editar_nombre_y_exclusion(api, sql):
    antes = api.get("/config").json()["version"]
    r = api.put(url(api, "SRL"), json={"nombre": "Sociedad de Responsabilidad Limitada"})
    assert r.status_code == 200, r.text
    assert nat(api, "SRL")["nombre"] == "Sociedad de Responsabilidad Limitada"
    assert api.get("/config").json()["version"] == antes   # cambiar el nombre no crea versión
    r = api.put(url(api, "SRL"), json={"excluida": True})
    assert r.status_code == 200 and r.json()["config_version"] == antes + 1
    assert nat(api, "SRL")["excluida"] is True
    assert "SRL" in api.get("/config").json()["parametros"]["naturalezas_excluidas"]
    audit = sql.execute("SELECT detalle FROM auditoria WHERE accion = 'naturaleza.editar' ORDER BY id").fetchall()
    assert audit[0]["detalle"]["nombre"]["despues"] == "Sociedad de Responsabilidad Limitada"
    assert audit[1]["detalle"]["excluida"] == {"antes": False, "despues": True}
    # Nombre vacío o repetido
    assert api.put(url(api, "SRL"), json={"nombre": "  "}).status_code == 422
    assert api.put(url(api, "SRL"), json={"nombre": "sociedad anónima"}).status_code == 409
    assert api.put("/naturalezas/999999", json={"nombre": "X"}).status_code == 404
    # Solo el administrador
    assert api.put(url(api, "SRL"), rol="steward", json={"nombre": "X"}).status_code == 403


def test_el_codigo_se_corrige_solo_si_no_se_usa(api, sql):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Uno SA", "Naturaleza": "SA"}])
    r = api.put(url(api, "SA"), json={"codigo": "SOCAN"})
    assert r.status_code == 409 and nat(api, "SA") is not None
    # Una sin uso y excluida: el código nuevo reemplaza al viejo en la configuración
    api.put(url(api, "GD"), json={"excluida": True})
    r = api.put(url(api, "GD"), json={"codigo": "gdep"})
    assert r.status_code == 200, r.text
    assert nat(api, "GD") is None and nat(api, "GDEP")["excluida"] is True
    excl = api.get("/config").json()["parametros"]["naturalezas_excluidas"]
    assert "GDEP" in excl and "GD" not in excl
    assert api.put(url(api, "GDEP"), json={"codigo": "SA"}).status_code == 409   # ya existe


def test_borrar_solo_si_no_se_usa(api, sql):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Uno SA", "Naturaleza": "SA"}])
    lista = {n["codigo"]: n for n in api.get("/naturalezas").json()}
    assert lista["SA"]["borrable"] is False and lista["SA"]["empresas"] == 1
    assert lista["FID"]["borrable"] is True
    r = api.delete(url(api, "SA"))
    assert r.status_code == 409 and "1 empresas" in r.json()["detail"]
    assert api.delete(url(api, "FID"), rol="steward").status_code == 403
    r = api.delete(url(api, "FID"))
    assert r.status_code == 200, r.text
    assert nat(api, "FID") is None
    assert sql.execute("SELECT detalle FROM auditoria WHERE accion = 'naturaleza.borrar'").fetchone()["detalle"]["nombre"] == "Fideicomiso"


def test_no_se_borra_si_figura_en_la_historia(api, sql):
    # La empresa tuvo SAS y después cambió a SA: SAS ya no la tiene nadie, pero figura en la historia
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Uno", "Naturaleza": "SAS"}], confianza=40)
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Uno", "Naturaleza": "SA"}], confianza=60, fuente="Otra base")
    sas = nat(api, "SAS")
    assert sas["empresas"] == 0 and sas["historia"] == 1 and sas["borrable"] is False
    r = api.delete(url(api, "SAS"))
    assert r.status_code == 409 and "historia" in r.json()["detail"]


def test_borrar_una_excluida_la_saca_de_la_configuracion(api, sql):
    api.put(url(api, "GD"), json={"excluida": True})
    version = api.get("/config").json()["version"]
    r = api.delete(url(api, "GD"))
    assert r.status_code == 200 and r.json()["config_version"] == version + 1
    assert "GD" not in api.get("/config").json()["parametros"]["naturalezas_excluidas"]


def test_una_naturaleza_sin_codigo_se_borra_y_se_corrige(api, sql):
    # Antes, DELETE /naturalezas/ (código vacío) respondía 307 y el navegador cortaba con «Failed to fetch»
    nid = sin_codigo(sql)
    fila = next(n for n in api.get("/naturalezas").json() if n["id"] == nid)
    assert fila["codigo"] == "" and fila["borrable"] is True
    r = api.delete(f"/naturalezas/{nid}")
    assert r.status_code == 200, r.text
    assert all(n["id"] != nid for n in api.get("/naturalezas").json())
    assert sql.execute("SELECT objeto_id FROM auditoria WHERE accion = 'naturaleza.borrar'").fetchone()["objeto_id"] == f"id:{nid}"
    # Otra, excluida: se le pone un código y queda excluida con ese código
    nid = sin_codigo(sql, "Otra vieja", excluida=False)
    r = api.put(f"/naturalezas/{nid}", json={"codigo": "VIEJA", "nombre": "Otra vieja", "excluida": True})
    assert r.status_code == 200, r.text
    assert nat(api, "VIEJA")["excluida"] is True
    assert "VIEJA" in api.get("/config").json()["parametros"]["naturalezas_excluidas"]


def test_no_se_puede_crear_sin_codigo(api, sql):
    assert api.post("/naturalezas", json={"codigo": " ", "nombre": "X"}).status_code == 422
    r = api.put(url(api, "FID"), json={"codigo": " "})
    assert r.status_code == 422
    # La base tampoco lo acepta (0014)
    import psycopg
    try:
        sql.execute("INSERT INTO naturaleza_juridica (codigo, nombre) VALUES ('  ', 'Y')")
        assert False, "tenía que rechazarlo"
    except psycopg.errors.CheckViolation:
        pass


def test_post_sigue_creando_y_actualizando(api, sql):
    # La pantalla crea con POST; la demo y fase0/cargar_excluidos.py lo usan también para actualizar
    r = api.post("/naturalezas", json={"codigo": "coopsoc", "nombre": "Cooperativa social"})
    assert r.status_code == 200 and nat(api, "COOPSOC")["nombre"] == "Cooperativa social"
    r = api.post("/naturalezas", json={"codigo": "COOPSOC", "nombre": "Cooperativa social (ley 17.978)", "excluida": True})
    assert r.status_code == 200 and nat(api, "COOPSOC")["excluida"] is True
    acciones = [x["accion"] for x in sql.execute("SELECT accion FROM auditoria WHERE objeto = 'naturaleza_juridica' ORDER BY id")]
    assert acciones == ["naturaleza.crear", "naturaleza.guardar"]
