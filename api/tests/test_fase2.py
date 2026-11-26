"""SPEC_fase2_enriquecimiento: tablero de calidad (A1), enriquecimiento bajo demanda (B1–B3), duplicados difusos y
grupo económico (B4) y descubrimiento (B5). Los proveedores se simulan: ningún test hace llamadas pagas."""
import datetime as dt

import pytest

from conftest import cargar, rut_valido
from test_muestra import estudio, leer_csv

from app import proveedores as prov
from app import secretos


@pytest.fixture(autouse=True)
def _secretos_limpios():
    secretos._proveedor = None   # las claves en memoria no pasan de un test a otro
    yield
    secretos._proveedor = None


class Falso:
    """Proveedores simulados. places: {fragmento de la consulta: [Lugar]}; registra cada llamada."""

    def __init__(self, monkeypatch, places=None, brave=None, sitios=None, claude=None, al_llamar=None):
        self.llamadas = []
        self.places, self.brave, self.sitios, self.claude = places or {}, brave or {}, sitios or {}, claude
        self.al_llamar = al_llamar
        monkeypatch.setattr(prov, "places_buscar", self._places)
        monkeypatch.setattr(prov, "brave_buscar", self._brave)
        monkeypatch.setattr(prov, "leer_sitio", self._sitio)
        monkeypatch.setattr(prov, "claude_api", self._claude)

    def _registrar(self, p):
        self.llamadas.append(p)
        if self.al_llamar:
            self.al_llamar(p, len(self.llamadas))

    def _places(self, consulta, pagina=None):
        self._registrar("google_places")
        for k, v in self.places.items():
            if k.lower() in consulta.lower():
                return v, None
        return [], None

    def _brave(self, consulta):
        self._registrar("brave")
        for k, v in self.brave.items():
            if k.lower() in consulta.lower():
                return [prov.Resultado(url=u) for u in v]
        return []

    def _sitio(self, url):
        for k, v in self.sitios.items():
            if k in url:
                return v, [url]
        raise prov.ProveedorError("no responde")

    def _claude(self, texto, empresa, modelo):
        self._registrar("claude")
        return (self.claude(texto) if self.claude else {}), 6000, 300

    def pagas(self, p=None):
        return sum(1 for x in self.llamadas if p is None or x == p)


def claves(api, *proveedores):
    for p in proveedores:
        r = api.put("/config/enriquecimiento/clave", json={"proveedor": p, "clave": f"clave-secreta-{p}"})
        assert r.status_code == 200, r.text


def configurar(api, **enr):
    cfg = api.get("/config").json()["parametros"]
    cfg["enriquecimiento"] = {**cfg["enriquecimiento"], **enr}
    r = api.put("/config", json={"parametros": cfg, "comentario": "prueba"})
    assert r.status_code == 200, r.text


def empresas_sin_telefono(api, n, desde=0, **extra):
    filas = [{"RUT": rut_valido(desde + i), "Razón social": f"Imprenta Número {desde + i} S.A.", "Teléfono": "",
              "Departamento": "Salto", **{k: (v(i) if callable(v) else v) for k, v in extra.items()}} for i in range(n)]
    return cargar(api, filas)


def lugar(nombre, tel=None, web=None, dep="Salto", pid=None, direccion=None):
    return prov.Lugar(place_id=pid or f"pid-{nombre}", nombre=nombre, telefono=tel, web=web, departamento=dep,
                      direccion=direccion)


def correr(api, rol="steward", limite=None, **body):
    r = api.post("/enriquecimiento/estimar", rol=rol, json=body)
    assert r.status_code == 200, r.text
    est = r.json()
    r = api.post(f"/enriquecimiento/{est['id']}/aprobar", rol=rol, json={"limite": limite})
    assert r.status_code == 200, r.text
    return est, api.get(f"/enriquecimiento/{est['id']}", rol=rol).json()


def emp_id(sql, n):
    return sql.execute("SELECT id FROM empresa WHERE rut = %s", (rut_valido(n),)).fetchone()["id"]


# ─── A1 · Tablero de calidad ───

def test_tablero_siete_dimensiones_y_listas(api, sql):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Uno SA", "Teléfono": "29001234", "CIIU": "1811", "Departamento": "Salto"},
                 {"RUT": rut_valido(1), "Razón social": "Dos SRL", "Teléfono": "", "Departamento": "Salto"}])
    r = api.get("/calidad", rol="steward")
    assert r.status_code == 200, r.text
    t = r.json()
    assert [d["clave"] for d in t["dimensiones"]] == ["validez", "unicidad", "completitud", "exactitud", "actualidad",
                                                       "consistencia", "provisoria"]
    for d in t["dimensiones"]:
        assert d["estado"] and d["indicadores"]
        for i in d["indicadores"]:
            assert "valor" in i and i["meta_texto"] and i["estado"]
            lista = api.get(f"/calidad/{i['clave']}", rol="steward")
            assert lista.status_code == 200, (i["clave"], lista.text)
    comp = next(i for d in t["dimensiones"] for i in d["indicadores"] if i["clave"] == "completitud")
    assert comp["valor"] == 50.0 and comp["estado"] == "no_cumple"
    falta = api.get("/calidad/completitud", rol="steward").json()
    assert falta["total"] == 1 and "sin teléfono discable" in falta["filas"][0]["problema"]
    assert "enriquecimiento" in t and t["enriquecimiento"]["tope_mensual"] == 100
    assert api.get("/calidad", rol="coordinador").status_code == 403


def test_medicion_diaria_y_evolucion(api, sql):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Uno SA", "Teléfono": "29001234"}])
    r = api.c.post("/api/jobs/calidad", headers={"X-Job-Token": "token-job"})
    assert r.status_code == 200, r.text
    assert sql.execute("SELECT count(DISTINCT indicador) AS n FROM calidad_medicion").fetchone()["n"] == 12
    # Seis días más de mediciones: la evolución muestra 7 puntos
    from app import calidad
    from app.db import conexion

    hoy = sql.execute("SELECT (now() AT TIME ZONE 'America/Montevideo')::date AS d").fetchone()["d"]  # el día de la app
    for i in range(1, 7):
        with conexion() as c:
            calidad.medir(c, hoy - dt.timedelta(days=i))
    serie = next(i for d in api.get("/calidad", rol="steward").json()["dimensiones"] for i in d["indicadores"]
                 if i["clave"] == "rut_valido")["serie"]
    assert len(serie) == 7
    # El job puede correr dos veces el mismo día: reemplaza la foto
    api.c.post("/api/jobs/calidad", headers={"X-Job-Token": "token-job"})
    assert sql.execute("SELECT count(*) AS n FROM calidad_medicion WHERE fecha = %s AND indicador = 'rut_valido'",
                       (hoy,)).fetchone()["n"] == 1


def test_consistencia_naturaleza_y_razon_social(api, sql):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Imprenta del Norte S.A.", "Naturaleza": "SRL"},
                 {"RUT": rut_valido(1), "Razón social": "Gráfica Sur S.R.L.", "Naturaleza": "SRL"},
                 {"RUT": rut_valido(2), "Razón social": "Papeles SAS", "Naturaleza": "SAS"}])
    lista = api.get("/calidad/consistencia", rol="steward").json()
    assert [f["razon_social"] for f in lista["filas"]] == ["Imprenta del Norte S.A."]
    assert lista["filas"][0]["sugerida"] == "SA" and lista["filas"][0]["naturaleza"] == "SRL"
    eid = lista["filas"][0]["id"]
    assert api.post(f"/calidad/alertas/{eid}/revisar", rol="steward").status_code == 200
    assert api.get("/calidad/consistencia", rol="steward").json()["total"] == 0
    assert sql.execute("SELECT count(*) AS n FROM auditoria WHERE accion = 'calidad.revisar_alerta'").fetchone()["n"] == 1
    # Si la razón social cambia, la alerta vuelve
    sql.execute("UPDATE empresa SET razon_social = 'Imprenta del Norte Sociedad Anónima' WHERE id = %s", (eid,))
    assert api.get("/calidad/consistencia", rol="steward").json()["total"] == 1


# ─── B1 · Configuración ───

def test_proveedor_sin_clave_no_configurado_y_se_saltea(api, sql, monkeypatch):
    empresas_sin_telefono(api, 2)
    cfg = api.get("/config/enriquecimiento").json()
    assert {k: v["estado"] for k, v in cfg["proveedores"].items()} == {
        "google_places": "no configurado", "brave": "no configurado", "claude": "no configurado"}
    claves(api, "google_places")
    estado = api.get("/config/enriquecimiento").json()["proveedores"]
    assert estado["google_places"]["estado"] == "activo" and estado["google_places"]["por"] == "admin@equipos.com.uy"
    assert "clave-secreta" not in str(estado)
    falso = Falso(monkeypatch, brave={"Imprenta": ["https://www.imprentanumero.com.uy"]})
    correr(api, origen="lista", filtros={"departamento": "Salto"})
    assert falso.pagas("google_places") == 2 and falso.pagas("brave") == 0 and falso.pagas("claude") == 0
    # La clave nunca queda en la auditoría
    audit = sql.execute("SELECT detalle FROM auditoria WHERE accion = 'config.clave_proveedor'").fetchone()["detalle"]
    assert audit == {"secreto": "empresas-places-key"}


def test_cambiar_precio_y_tope_queda_en_historial_y_auditoria(api, sql):
    antes = api.get("/config").json()["version"]
    configurar(api, precio_places=0.04, tope_mensual=150)
    cfg = api.get("/config").json()
    assert cfg["version"] == antes + 1 and cfg["parametros"]["enriquecimiento"]["precio_places"] == 0.04
    cambio = sql.execute("SELECT detalle FROM auditoria WHERE accion = 'config.cambiar' ORDER BY id DESC LIMIT 1").fetchone()
    assert cambio["detalle"]["cambios"]["enriquecimiento"]["despues"]["tope_mensual"] == 150
    # Un tope por corrida mayor que el mensual no se acepta
    c = cfg["parametros"]
    c["enriquecimiento"]["tope_corrida"] = 500
    assert api.put("/config", json={"parametros": c}).status_code == 422


# ─── B2 · Corrida ───

def test_corrida_de_50_empresas(api, sql, monkeypatch):
    empresas_sin_telefono(api, 50)
    claves(api, "google_places", "brave", "claude")
    # Places encuentra 30 de 50 (60 %); para el resto la web no trae nada
    places = {f"Imprenta Número {i} S.A.": [lugar(f"Imprenta Número {i}", tel=f"4733{i:04d}")] for i in range(30)}
    falso = Falso(monkeypatch, places=places)
    r = api.post("/enriquecimiento/estimar", json={"origen": "lista", "filtros": {"departamento": "Salto"}})
    est = r.json()
    assert est["estimacion"]["empresas"] == 50 and est["estimacion"]["maximo"] > 0 and est["estimacion"]["esperado"] > 0
    assert est["estimacion"]["places_gratis"] == 50          # dentro de las 1.000 gratis del mes
    assert falso.pagas() == 0                                  # nada se gasta antes de aprobar
    assert sql.execute("SELECT count(*) AS n FROM enriquecimiento_paso").fetchone()["n"] == 0
    r = api.post(f"/enriquecimiento/{est['id']}/aprobar", json={})
    assert r.status_code == 200, r.text
    c = api.get(f"/enriquecimiento/{est['id']}").json()
    assert c["estado"] == "terminada"
    res = c["resultado"]
    assert res["con_telefono_nuevo"] == 30 and res["sin_resultado"] == 20 and res["tasa_telefono"] == 60.0
    assert set(res["gasto_por_proveedor"]) >= {"Google Places", "Brave Search"}
    assert falso.pagas("google_places") == 50 and falso.pagas("brave") == 20
    sin = api.get(f"/enriquecimiento/{est['id']}/empresas?resultado=sin_resultado").json()
    assert sin["total"] == 20
    assert sql.execute("SELECT count(*) AS n FROM auditoria WHERE accion = 'enriquecimiento.aprobar'").fetchone()["n"] == 1


def test_empresa_con_telefono_no_genera_llamadas_pagas(api, sql, monkeypatch):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Con Teléfono SA", "Teléfono": "29001234"}])
    claves(api, "google_places", "brave", "claude")
    falso = Falso(monkeypatch, places={"Con Teléfono": [lugar("Con Teléfono", tel="29005555")]})
    r = api.post("/enriquecimiento/estimar", json={"origen": "ficha", "rut": rut_valido(0)})
    est = r.json()["estimacion"]
    assert est["empresas"] == 0 and est["salteadas"]["tiene_telefono"]["cantidad"] == 1 and est["maximo"] == 0
    # Aunque la lista la incluya («todas»), la cascada no gasta en ella
    from app import enriquecimiento as enr

    run = enr.Corrida({"id": 500, "estimacion": {"permitido": 20}}, enr.config.ConfigEnriquecimiento().model_dump(),
                      {p: {"activo": True, "configurado": True} for p in enr.PROVEEDORES}, "test")
    sql.execute("INSERT INTO enriquecimiento_corrida (id, origen, creado_por, estado) VALUES (500, 'ficha', 'test', 'en_curso')")
    assert enr.procesar_empresa(run, emp_id(sql, 0))["resultado"] == "ya_tenia"
    assert falso.pagas() == 0


def test_tope_mensual_detiene_la_corrida(api, sql, monkeypatch):
    empresas_sin_telefono(api, 10)
    claves(api, "google_places")
    configurar(api, tope_mensual=1.0, tope_corrida=1.0, places_gratis_mes=0)
    sql.execute("INSERT INTO enriquecimiento_corrida (id, origen, creado_por, estado) VALUES (999, 'lista', 'otro', 'terminada')")
    sql.execute("INSERT INTO enriquecimiento_paso (corrida_id, proveedor, costo, resultado) VALUES (999, 'google_places', 0.8, 'ok')")

    def otra_corrida(p, n):   # mientras tanto, otra corrida gasta US$0,10
        if n == 1:
            sql.execute("INSERT INTO enriquecimiento_paso (corrida_id, proveedor, costo, resultado)"
                        " VALUES (999, 'google_places', 0.1, 'ok')")

    falso = Falso(monkeypatch, al_llamar=otra_corrida)
    r = api.post("/enriquecimiento/estimar", json={"origen": "lista", "filtros": {"departamento": "Salto"}}).json()
    assert r["estimacion"]["excede"] and r["estimacion"]["max_empresas_permitidas"] == 5
    assert api.post(f"/enriquecimiento/{r['id']}/aprobar", json={}).status_code == 409   # hay que reducir
    assert api.post(f"/enriquecimiento/{r['id']}/aprobar", json={"limite": 5}).status_code == 200
    c = api.get(f"/enriquecimiento/{r['id']}").json()
    assert c["estado"] == "detenida_tope"
    # 0,8 + 0,035 + 0,1 (otra) + 0,035 = 0,97; la tercera llamada (1,005) no se hace
    assert falso.pagas("google_places") == 2
    assert sql.execute("SELECT count(*) AS n FROM enriquecimiento_paso WHERE corrida_id = %s AND resultado = 'tope'",
                       (r["id"],)).fetchone()["n"] == 1
    assert float(sql.execute("SELECT sum(costo) AS g FROM enriquecimiento_paso WHERE fecha >= date_trunc('month', now())"
                             ).fetchone()["g"]) <= 1.0


def test_cancelar_conserva_lo_conseguido(api, sql, monkeypatch):
    empresas_sin_telefono(api, 6)
    claves(api, "google_places")
    places = {f"Imprenta Número {i} S.A.": [lugar(f"Imprenta Número {i}", tel=f"4733{i:04d}")] for i in range(6)}

    def cancelar_en_la_tercera(p, n):
        if n == 3:
            sql.execute("UPDATE tarea SET estado = 'cancelada' WHERE tipo = 'enriquecimiento'")

    Falso(monkeypatch, places=places, al_llamar=cancelar_en_la_tercera)
    r = api.post("/enriquecimiento/estimar", json={"origen": "lista", "filtros": {"departamento": "Salto"}}).json()
    api.post(f"/enriquecimiento/{r['id']}/aprobar", json={})
    c = api.get(f"/enriquecimiento/{r['id']}").json()
    assert c["estado"] == "cancelada" and c["resultado"]["procesadas"] == 3
    assert sql.execute("SELECT count(*) AS n FROM telefono_vinculo WHERE fuente_tipo = 'enriquecimiento'").fetchone()["n"] == 3


def test_la_extraccion_no_guarda_datos_personales(api, sql, monkeypatch):
    empresas_sin_telefono(api, 1)
    claves(api, "google_places", "brave", "claude")
    sitio = ("Imprenta Número 0 · Contacto\nTel. 4733 2211 · info@imprentanumero.com.uy\n"
             "Gerente comercial: Martín Rodríguez 099 123 456 · martin.rodriguez@imprentanumero.com.uy\nAv. Artigas 1234, Salto")

    def respuesta(texto):   # el modelo devuelve de más: la validación tiene que descartarlo
        return {"telefonos": [{"numero": "4733 2211", "asociado_a_persona": False},
                              {"numero": "099 123 456", "asociado_a_persona": False}],
                "emails": ["info@imprentanumero.com.uy", "martin.rodriguez@imprentanumero.com.uy"],
                "direccion": "Av. Artigas 1234, Salto", "es_estudio_contable_juridico": False, "confianza": 0.9}

    falso = Falso(monkeypatch, brave={"Imprenta": ["https://www.facebook.com/imprenta", "https://www.imprentanumero.com.uy"]},
                  sitios={"imprentanumero": sitio}, claude=respuesta)
    _, c = correr(api, origen="ficha", rut=rut_valido(0))
    assert c["estado"] == "terminada" and falso.pagas("claude") == 1
    tels = [r["e164"] for r in sql.execute("SELECT t.e164 FROM telefono t JOIN telefono_vinculo v ON v.telefono_id = t.id")]
    assert tels == ["+59847332211"]
    assert sql.execute("SELECT count(*) AS n FROM telefono WHERE e164 = '+59899123456'").fetchone()["n"] == 0
    e = sql.execute("SELECT web, direccion FROM empresa").fetchone()
    assert e["web"] == "https://www.imprentanumero.com.uy" and e["direccion"] == "Av. Artigas 1234, Salto"
    email = sql.execute("SELECT ea.valor_texto FROM empresa_atributo ea JOIN atributo a ON a.id = ea.atributo_id"
                        " WHERE a.clave = 'email_institucional'").fetchone()["valor_texto"]
    assert email == "info@imprentanumero.com.uy"
    # Ni el nombre ni el celular ni el email personal quedan en ninguna parte
    for tabla in ("enriquecimiento_paso", "empresa_campo_historia", "auditoria", "enriquecimiento_corrida"):
        volcado = str(sql.execute(f"SELECT * FROM {tabla}").fetchall())
        assert "Rodr" not in volcado and "099 123" not in volcado and "martin.rodriguez" not in volcado, tabla
    paso = sql.execute("SELECT detalle FROM enriquecimiento_paso WHERE proveedor = 'claude'").fetchone()["detalle"]
    assert paso["datos_personales_descartados"] == 2


def test_validacion_descarta_celular_junto_a_un_nombre():
    texto = "Ventas: 2901 1234\nContactá a la Cra. Ana Gómez 098 765 432\nWhatsApp 099 111 222"
    ext = prov.validar_extraccion({"telefonos": [{"numero": "2901 1234", "asociado_a_persona": False},
                                                 {"numero": "098 765 432", "asociado_a_persona": False},
                                                 {"numero": "099 111 222", "asociado_a_persona": False}],
                                   "emails": ["ventas@x.com.uy", "ana.gomez@x.com.uy", "agomez@x.com.uy"]}, texto)
    assert ext.telefonos == ["+59829011234", "+59899111222"]
    assert ext.emails == ["ventas@x.com.uy"] and ext.descartados == 3


# ─── B3 · Datos encontrados ───

def test_telefono_de_places_sin_verificar_y_en_el_csv(api, sql, monkeypatch):
    empresas_sin_telefono(api, 3)
    claves(api, "google_places")
    Falso(monkeypatch, places={f"Imprenta Número {i} S.A.": [lugar(f"Imprenta Número {i}", tel=f"4733{i:04d}")] for i in range(3)})
    est = estudio(api)
    cfg = api.get("/config").json()["parametros"]   # D56: solo la regla de Configuración deja sortear sin teléfono
    cfg["reglas_disponibilidad"]["sin_telefono_discable"] = False
    api.put("/config", json={"parametros": cfg})
    m = api.post("/muestras", rol="jefe", json={"estudio_id": est["id"], "nombre": "M", "criterios": {
        "n_por_estrato": 3}}).json()
    api.post(f"/muestras/{m['id']}/sortear", rol="jefe", json={"semilla": 1})
    _, c = correr(api, rol="jefe", origen="muestra", muestra_id=m["id"])   # el jefe puede desde una muestra
    assert c["resultado"]["con_telefono_nuevo"] == 3
    v = sql.execute("SELECT v.estado, o.codigo, x.fuente_tipo, x.fuente_id FROM telefono_vinculo v"
                    " JOIN telefono_vinculo_origen x ON x.vinculo_id = v.id JOIN origen_telefono o ON o.id = x.origen_id").fetchall()
    assert {(r["estado"], r["codigo"], r["fuente_tipo"], r["fuente_id"]) for r in v} == {
        ("sin_verificar", "google_places", "enriquecimiento", c["id"])}
    filas = leer_csv(api.get(f"/muestras/{m['id']}/csv?parte_id={est['partes'][0]['id']}", rol="coordinador"))
    assert len(filas) == 3
    # El jefe no enriquece una lista
    assert api.post("/enriquecimiento/estimar", rol="jefe", json={"origen": "lista", "filtros": {}}).status_code == 403
    # Ficha: de dónde salió cada teléfono enriquecido
    pasos = api.get(f"/empresas/{rut_valido(0)}/enriquecimiento", rol="steward").json()
    assert pasos[0]["proveedor"] == "google_places" and pasos[0]["corrida_id"] == c["id"]
    ficha = api.get(f"/empresas/{rut_valido(0)}", rol="steward").json()
    grupo = next(x for x in ficha["linea_de_tiempo"] if x["tipo"] == "enriquecimiento")
    assert grupo["descripcion"] == f"Enriquecimiento #{c['id']}: 1 teléfono (Google Places)"
    origen = next(t for t in ficha["telefonos"] if t["e164"] == "+59847330000")["origenes"][0]
    assert origen["fuente_tipo"] == "enriquecimiento" and origen["fuente_id"] == c["id"]


def test_web_enriquecido_no_pisa_una_carga(api, sql, monkeypatch):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Imprenta Número 0 S.A.", "Web": "https://www.cargada.com.uy",
                  "Teléfono": "", "Departamento": "Salto"}])
    claves(api, "google_places")
    Falso(monkeypatch, places={"Imprenta Número 0": [lugar("Imprenta Número 0", tel="47330000", web="https://otra.com.uy")]})
    _, c = correr(api, origen="ficha", rut=rut_valido(0))
    assert c["resultado"]["con_telefono_nuevo"] == 1
    assert sql.execute("SELECT web FROM empresa").fetchone()["web"] == "cargada.com.uy"   # la de la carga sigue
    h = sql.execute("SELECT confianza FROM empresa_campo_historia WHERE campo = 'web' AND fuente_tipo = 'enriquecimiento'").fetchone()
    assert h["confianza"] == 30


def test_deshacer_quita_lo_no_verificado_y_conserva_lo_verificado(api, sql, monkeypatch):
    empresas_sin_telefono(api, 2)
    claves(api, "google_places")
    Falso(monkeypatch, places={f"Imprenta Número {i} S.A.": [lugar(f"Imprenta Número {i}", tel=f"4733{i:04d}",
                                                                    direccion=f"Calle {i}")] for i in range(2)})
    _, c = correr(api, origen="lista", filtros={"departamento": "Salto"})
    verificado = sql.execute("SELECT v.id FROM telefono_vinculo v WHERE empresa_id = %s", (emp_id(sql, 0),)).fetchone()["id"]
    sql.execute("UPDATE telefono_vinculo SET estado = 'verificado' WHERE id = %s", (verificado,))
    assert sql.execute("SELECT direccion FROM empresa WHERE id = %s", (emp_id(sql, 1),)).fetchone()["direccion"] == "Calle 1"
    r = api.post(f"/enriquecimiento/{c['id']}/deshacer", rol="steward")
    assert r.status_code == 200, r.text
    assert r.json()["vinculos_quitados"] == 1 and r.json()["verificados_conservados"] == 1
    quedan = sql.execute("SELECT empresa_id, estado FROM telefono_vinculo").fetchall()
    assert [(q["empresa_id"], q["estado"]) for q in quedan] == [(emp_id(sql, 0), "verificado")]
    assert sql.execute("SELECT direccion FROM empresa WHERE id = %s", (emp_id(sql, 1),)).fetchone()["direccion"] is None
    assert api.get(f"/enriquecimiento/{c['id']}").json()["estado"] == "deshecha"


def test_sitio_de_estudio_contable_marca_intermediario(api, sql, monkeypatch):
    empresas_sin_telefono(api, 1)
    claves(api, "brave", "claude")
    Falso(monkeypatch, brave={"Imprenta": ["https://www.imprentanumero.com.uy"]}, sitios={"imprentanumero": "Estudio contable"},
          claude=lambda t: {"telefonos": [{"numero": "4733 9999", "asociado_a_persona": False}], "emails": [],
                            "direccion": None, "es_estudio_contable_juridico": True, "confianza": 0.7})
    correr(api, origen="ficha", rut=rut_valido(0))
    t = sql.execute("SELECT intermediario, intermediario_motivo FROM telefono").fetchone()
    assert t["intermediario"] == "sospechoso" and "estudio contable" in t["intermediario_motivo"]
    sosp = api.get("/telefonos/sospechosos", rol="steward").json()["telefonos"]
    assert len(sosp) == 1 and "estudio contable" in sosp[0]["intermediario_motivo"]


# ─── B4 · Duplicados difusos y grupo económico ───

def dos_con_el_mismo_telefono(api, mas=()):
    filas = [{"RUT": rut_valido(0), "Razón social": "Alfa SA", "Teléfono": "29001234", "Tamaño": "Grande"},
             {"RUT": rut_valido(1), "Razón social": "Beta SRL", "Teléfono": "29001234", "Tamaño": "Grande"}, *mas]
    columnas = list(dict.fromkeys(k for f in filas for k in f))
    cargar(api, [{k: f.get(k, "") for k in columnas} for f in filas])


def test_par_por_telefono(api, sql):
    dos_con_el_mismo_telefono(api)
    r = api.post("/duplicados/detectar", rol="steward")
    assert r.status_code == 200 and r.json()["nuevos"] == 1
    b = api.get("/duplicados", rol="steward").json()
    assert b["total"] == 1 and b["filas"][0]["criterios"] == [{"criterio": "telefono", "evidencia": "+59829001234"}]
    assert {b["filas"][0]["a"]["razon_social"], b["filas"][0]["b"]["razon_social"]} == {"Alfa SA", "Beta SRL"}
    tablero = api.get("/calidad", rol="steward").json()
    assert next(i for d in tablero["dimensiones"] for i in d["indicadores"] if i["clave"] == "duplicados_pendientes")["valor"] == 1


def test_otros_criterios_de_duplicado(api, sql):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Gráfica Oriental S.A.", "Web": "https://www.grafor.com.uy",
                  "Dirección": "Av. Italia 3456", "Departamento": "Montevideo"},
                 {"RUT": rut_valido(1), "Razón social": "Grafica Oriental SRL", "Web": "http://grafor.com.uy/contacto",
                  "Dirección": "AV. ITALIA 3456", "Departamento": "Montevideo"},
                 {"RUT": rut_valido(2), "Razón social": "Otra Cosa SA", "Web": "https://www.facebook.com/otra"},
                 {"RUT": rut_valido(3), "Razón social": "Distinta SA", "Web": "https://facebook.com/distinta"}])
    api.post("/duplicados/detectar", rol="steward")
    filas = api.get("/duplicados", rol="steward").json()["filas"]
    assert len(filas) == 1   # facebook.com es un dominio genérico
    assert {c["criterio"] for c in filas[0]["criterios"]} == {"dominio", "direccion", "razon_social"}


def test_grupo_economico_y_una_empresa_por_grupo(api, sql):
    dos_con_el_mismo_telefono(api, [{"RUT": rut_valido(2), "Razón social": "Gama SA", "Teléfono": "29005678", "Tamaño": "Grande"}])
    api.post("/duplicados/detectar", rol="steward")
    par = api.get("/duplicados", rol="steward").json()["filas"][0]
    r = api.post(f"/duplicados/{par['id']}/resolver", rol="steward", json={"accion": "grupo", "nombre_grupo": "Grupo Alfa"})
    assert r.status_code == 200, r.text
    g = sql.execute("SELECT grupo_economico_id AS g, baja FROM empresa ORDER BY id").fetchall()
    assert g[0]["g"] and g[0]["g"] == g[1]["g"] and g[2]["g"] is None and g[0]["baja"] is None   # no se fusionan
    assert [e["razon_social"] for e in api.get(f"/grupos/{g[0]['g']}", rol="lectura").json()["empresas"]] == ["Alfa SA", "Beta SRL"]
    est = estudio(api)
    for semilla in range(5):
        m = api.post("/muestras", rol="jefe", json={"estudio_id": est["id"], "nombre": f"M{semilla}", "criterios": {
            "n_por_estrato": 3, "una_por_grupo": True}}).json()
        r = api.post(f"/muestras/{m['id']}/sortear", rol="jefe", json={"semilla": semilla})
        assert r.status_code == 200, r.text
        ids = {x["empresa_id"] for x in sql.execute("SELECT empresa_id FROM muestra_item WHERE muestra_id = %s", (m["id"],))}
        assert len(ids) == 2
        en_grupo = sql.execute("SELECT count(*) AS n FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id"
                               " WHERE i.muestra_id = %s AND e.grupo_economico_id IS NOT NULL", (m["id"],)).fetchone()["n"]
        assert en_grupo == 1
        v = api.post(f"/muestras/{m['id']}/verificar", rol="jefe").json()
        assert v["resultado"] == "reproducible"
        api.post(f"/muestras/{m['id']}/cerrar", rol="jefe")
    # La opción se guarda en los criterios y en los templates
    t = api.post("/muestra-templates", rol="jefe", json={"nombre": "Con grupo", "criterios": {"n_por_estrato": 3, "una_por_grupo": True}})
    assert t.status_code == 200, t.text
    assert t.json()["criterios"]["una_por_grupo"] is True
    # Detectar otra vez no propone el par que ya es grupo
    api.post("/duplicados/detectar", rol="steward")
    assert api.get("/duplicados", rol="steward").json()["total"] == 0


def test_sin_relacion_no_vuelve_y_fusionar(api, sql):
    dos_con_el_mismo_telefono(api, [{"RUT": rut_valido(2), "Razón social": "Gama SA", "Dirección": "Rivera 1234 bis",
                                     "Departamento": "Salto"},
                                    {"RUT": rut_valido(3), "Razón social": "Delta SA", "Dirección": "Rivera 1234 Bis",
                                     "Departamento": "Salto"}])
    api.post("/duplicados/detectar", rol="steward")
    pares = api.get("/duplicados", rol="steward").json()["filas"]
    assert len(pares) == 2
    tel = next(p for p in pares if p["criterios"][0]["criterio"] == "telefono")
    dirc = next(p for p in pares if p["criterios"][0]["criterio"] == "direccion")
    assert api.post(f"/duplicados/{tel['id']}/resolver", rol="steward", json={"accion": "sin_relacion"}).status_code == 200
    r = api.post(f"/duplicados/{dirc['id']}/resolver", rol="steward", json={"accion": "fusionar", "absorbente_id": dirc["a"]["id"]})
    assert r.status_code == 200 and r.json()["fusion_id"]
    api.post("/duplicados/detectar", rol="steward")
    assert api.get("/duplicados", rol="steward").json()["total"] == 0
    assert sql.execute("SELECT count(*) AS n FROM auditoria WHERE accion LIKE 'duplicado.%%'").fetchone()["n"] == 2


# ─── B5 · Descubrimiento ───

def test_descubrimiento_preview_y_confirmar(api, sql, monkeypatch):
    claves(api, "google_places")
    falso = Falso(monkeypatch, places={"imprentas en Salto": [
        lugar("Imprenta del Litoral", tel="47331111", pid="p1", direccion="Uruguay 100, Salto"),
        lugar("Gráfica Norte", tel="47332222", pid="p2", direccion="Artigas 200, Salto"),
        lugar("Copias Ya", tel=None, pid="p3")]})
    est = api.post("/descubrimiento/estimar", rol="steward", json={"consulta": "imprentas en Salto", "paginas": 1}).json()
    assert est["estimacion"]["paginas"] == 1 and est["estimacion"]["places_gratis"] == 1 and falso.pagas() == 0
    r = api.post(f"/descubrimiento/{est['id']}/buscar", rol="steward")
    assert r.status_code == 200, r.text
    prev = r.json()["resultado"]
    assert prev["resumen"] == {"ya_guardado": 0, "coincide": 0, "nueva": 3, "aportan": 0}
    assert sql.execute("SELECT count(*) AS n FROM empresa").fetchone()["n"] == 0   # nada hasta confirmar
    r = api.post(f"/descubrimiento/{est['id']}/confirmar", rol="steward", json={"seleccion": {"2": "omitir"}})
    assert r.status_code == 200, r.text
    emps = sql.execute("SELECT e.codigo, e.base, e.razon_social, e.departamento FROM empresa e ORDER BY id").fetchall()
    assert [e["razon_social"] for e in emps] == ["Imprenta del Litoral", "Gráfica Norte"]
    assert all(e["codigo"].startswith("P-") and e["base"] == "provisoria" for e in emps)
    v = sql.execute("SELECT v.estado, o.codigo FROM telefono_vinculo v JOIN telefono_vinculo_origen x ON x.vinculo_id = v.id"
                    " JOIN origen_telefono o ON o.id = x.origen_id").fetchall()
    assert {(x["estado"], x["codigo"]) for x in v} == {("sin_verificar", "google_places")} and len(v) == 2
    rubro = sql.execute("SELECT DISTINCT ea.valor_texto FROM empresa_atributo ea JOIN atributo a ON a.id = ea.atributo_id"
                        " WHERE a.clave = 'rubro_descubrimiento'").fetchall()
    assert [x["valor_texto"] for x in rubro] == ["imprentas"]
    # Una segunda búsqueda igual ya conoce esos place_id
    est2 = api.post("/descubrimiento/estimar", rol="steward", json={"consulta": "imprentas en Salto"}).json()
    prev2 = api.post(f"/descubrimiento/{est2['id']}/buscar", rol="steward").json()["resultado"]
    assert prev2["resumen"]["ya_guardado"] == 2


def test_descubrimiento_no_duplica_una_empresa_existente(api, sql, monkeypatch):
    cargar(api, [{"RUT": rut_valido(0), "Razón social": "Imprenta Salteña SA", "Teléfono": "47331111", "Departamento": "Salto"}])
    claves(api, "google_places")
    Falso(monkeypatch, places={"imprentas en Salto": [lugar("Imprenta Salteña", tel="4733 1111", pid="p1",
                                                            web="https://salteña.com.uy", direccion="Uruguay 100, Salto")]})
    est = api.post("/descubrimiento/estimar", rol="steward", json={"rubro": "imprentas", "departamento": "Salto"}).json()
    prev = api.post(f"/descubrimiento/{est['id']}/buscar", rol="steward").json()["resultado"]
    f = prev["resultados"][0]
    assert f["caso"] == "coincide" and f["regla"] == "telefono" and f["marcada"] and f["empresa"]["codigo"] == rut_valido(0)
    api.post(f"/descubrimiento/{est['id']}/confirmar", rol="steward", json={})
    assert sql.execute("SELECT count(*) AS n FROM empresa").fetchone()["n"] == 1
    e = sql.execute("SELECT web, direccion FROM empresa").fetchone()
    assert e["web"] == "https://salteña.com.uy" and e["direccion"] == "Uruguay 100, Salto"


def test_deshacer_un_lote_de_descubrimiento(api, sql, monkeypatch):
    claves(api, "google_places")
    Falso(monkeypatch, places={"imprentas en Salto": [lugar("Imprenta del Litoral", tel="47331111", pid="p1")]})
    est = api.post("/descubrimiento/estimar", rol="steward", json={"consulta": "imprentas en Salto"}).json()
    api.post(f"/descubrimiento/{est['id']}/buscar", rol="steward")
    api.post(f"/descubrimiento/{est['id']}/confirmar", rol="steward", json={})
    r = api.post(f"/descubrimiento/{est['id']}/deshacer", rol="steward")
    assert r.status_code == 200, r.text
    assert r.json()["provisorias_anuladas"] == 1
    assert sql.execute("SELECT baja FROM empresa").fetchone()["baja"] == "anulada"
    assert sql.execute("SELECT count(*) AS n FROM telefono_vinculo").fetchone()["n"] == 0
    assert api.get("/empresas?base=provisoria", rol="steward").json()["total"] == 0
