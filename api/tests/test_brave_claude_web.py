"""SPEC_brave_pais_y_errores_visibles (D57): parámetros de Brave, motivo de los errores a la vista y búsqueda web con
Claude como último paso. Los proveedores se simulan: ningún test hace llamadas pagas."""
import httpx
import pytest

from conftest import rut_valido
from test_fase2 import Falso, claves, configurar, correr, emp_id, empresas_sin_telefono, lugar
from app import proveedores as prov
from app import secretos, settings

BRAVE_REAL = prov.brave_buscar   # Falso lo reemplaza; estos tests usan el real contra un HTTP simulado


@pytest.fixture(autouse=True)
def _secretos_limpios():
    secretos._proveedor = None
    yield
    secretos._proveedor = None


# ─── B1 · Parámetros de Brave ───

class HttpFalso:
    """Reemplaza httpx.get de Brave: responde lo que se le pide, en orden, y guarda los parámetros."""

    def __init__(self, monkeypatch, respuestas):
        self.respuestas, self.llamadas = list(respuestas), []
        monkeypatch.setattr(prov.httpx, "get", self.get)
        monkeypatch.setattr(prov.time, "sleep", lambda s: self.llamadas.append(("espera", s)))
        monkeypatch.setattr(prov, "clave", lambda p: "clave-secreta-brave")
        monkeypatch.setattr(settings, "PROVEEDORES_MODO", "real")

    def get(self, url, params=None, headers=None, timeout=None):
        self.llamadas.append(("get", dict(params or {})))
        codigo, cuerpo = self.respuestas.pop(0)
        return httpx.Response(codigo, json=cuerpo, request=httpx.Request("GET", url))


ERROR_422 = {"type": "ErrorResponse", "error": {
    "id": "x", "status": 422, "code": "VALIDATION", "detail": "Unable to validate request parameter(s)",
    "meta": {"errors": [{"type": "enum", "loc": ["query", "country"],
                         "msg": "Input should be 'AR', 'AU', 'AT', 'BE', 'BR' or 'ALL'"}]}}}
OK = {"web": {"results": [{"url": "https://www.4cabezas.com.uy", "title": "4 Cabezas"}]}}


def test_brave_manda_pais_all_y_sin_ui_lang(monkeypatch):
    h = HttpFalso(monkeypatch, [(200, OK)])
    r = prov.brave_buscar("4 Cabezas SAS Uruguay Montevideo")
    assert [x.url for x in r] == ["https://www.4cabezas.com.uy"]
    params = h.llamadas[0][1]
    assert params["country"] == "ALL" and params["search_lang"] == "es" and "ui_lang" not in params


def test_brave_422_trae_el_detalle_sin_la_clave(monkeypatch):
    cuerpo = {**ERROR_422, "error": {**ERROR_422["error"], "detail": "token clave-secreta-brave inválido para country"}}
    cuerpo["error"]["meta"] = {}
    HttpFalso(monkeypatch, [(422, cuerpo)])
    with pytest.raises(prov.ProveedorError) as e:
        prov.brave_buscar("x")
    assert "422" in str(e.value) and "clave-secreta-brave" not in str(e.value) and "***" in str(e.value)
    HttpFalso(monkeypatch, [(422, ERROR_422)])
    with pytest.raises(prov.ProveedorError) as e:
        prov.brave_buscar("x")
    assert str(e.value).startswith("Brave Search respondió 422: country: Input should be 'AR'")
    assert not e.value.clave_invalida and not e.value.cobrada


def test_brave_429_reintenta_una_vez(monkeypatch):
    h = HttpFalso(monkeypatch, [(429, {"error": {"detail": "Too many requests"}}), (200, OK)])
    assert len(prov.brave_buscar("x")) == 1
    assert [x[0] for x in h.llamadas] == ["get", "espera", "get"] and h.llamadas[1][1] == prov.BRAVE_ESPERA_429
    HttpFalso(monkeypatch, [(429, {"error": {"detail": "Too many requests"}})] * 2)
    with pytest.raises(prov.ProveedorError) as e:
        prov.brave_buscar("x")
    assert "429" in str(e.value) and "Too many requests" in str(e.value)


# ─── B2 y B3 · El motivo del error se guarda y se ve ───

def test_error_de_brave_queda_guardado_y_a_la_vista(api, sql, monkeypatch):
    empresas_sin_telefono(api, 1)
    claves(api, "google_places", "brave")
    Falso(monkeypatch)    # Places sin resultado
    monkeypatch.setattr(prov, "brave_buscar", BRAVE_REAL)
    HttpFalso(monkeypatch, [(422, ERROR_422)])
    _, c = correr(api, origen="ficha", rut=rut_valido(0))
    paso = sql.execute("SELECT resultado, costo, detalle FROM enriquecimiento_paso WHERE proveedor = 'brave'").fetchone()
    assert paso["resultado"] == "error" and float(paso["costo"]) == 0
    assert paso["detalle"]["error"].startswith("Brave Search respondió 422: country: Input should be")
    assert c["errores"]["brave"] == [{"motivo": paso["detalle"]["error"], "n": 1}]
    emp = api.get(f"/enriquecimiento/{c['id']}/empresas", rol="steward").json()["filas"]
    assert emp[0]["resultado"] == "error" and emp[0]["errores"][0]["proveedor"] == "Brave Search"
    assert "422" in emp[0]["errores"][0]["motivo"]
    assert api.get(f"/enriquecimiento/{c['id']}/empresas", rol="steward", params={"resultado": "error"}).json()["total"] == 1
    # ningún registro tiene la clave
    for r in sql.execute("SELECT detalle::text AS t FROM enriquecimiento_paso").fetchall():
        assert "clave-secreta" not in (r["t"] or "")


def test_429_y_despues_200_cobra_una_vez(api, sql, monkeypatch):
    empresas_sin_telefono(api, 1)
    claves(api, "google_places", "brave")
    Falso(monkeypatch)
    monkeypatch.setattr(prov, "brave_buscar", BRAVE_REAL)
    HttpFalso(monkeypatch, [(429, {}), (200, {"web": {"results": []}})])
    correr(api, origen="ficha", rut=rut_valido(0))
    pasos = sql.execute("SELECT resultado, costo FROM enriquecimiento_paso WHERE proveedor = 'brave'").fetchall()
    assert len(pasos) == 1 and pasos[0]["resultado"] == "sin_resultado" and float(pasos[0]["costo"]) == 0.005


# ─── B4 · Búsqueda web con Claude ───

class WebFalsa:
    """claude_buscar_web y leer_pagina simulados. propuestas: [(numero, url)]; paginas: {url: texto}."""

    def __init__(self, monkeypatch, propuestas=(), paginas=None, busquedas=2, entrada=20000, salida=500, confianza=0.8):
        self.llamadas = []
        self.b = prov.BusquedaWeb(telefonos=[{"numero": n, "url": u} for n, u in propuestas], confianza=confianza,
                                  busquedas=busquedas, tokens_entrada=entrada, tokens_salida=salida)
        self.paginas = paginas or {}
        monkeypatch.setattr(prov, "claude_buscar_web", self._buscar)
        monkeypatch.setattr(prov, "leer_pagina", self._pagina)

    def _buscar(self, empresa, modelo, max_usos):
        self.llamadas.append((empresa["razon_social"], modelo, max_usos))
        return self.b

    def _pagina(self, url):
        if url not in self.paginas:
            raise prov.ProveedorError("no responde")
        return self.paginas[url]


def test_desactivada_la_cascada_es_la_de_siempre(api, sql, monkeypatch):
    empresas_sin_telefono(api, 2)
    claves(api, "google_places", "brave", "claude")
    f = Falso(monkeypatch)
    w = WebFalsa(monkeypatch, [("2900 1234", "https://x.com.uy/c")], {"https://x.com.uy/c": "Tel 2900 1234"})
    est, c = correr(api, origen="lista", filtros={})
    assert w.llamadas == [] and f.pagas() == 4   # Places y Brave por empresa, como hoy
    assert "Búsqueda web (Claude)" not in est["estimacion"]["por_proveedor_maximo"]
    assert sql.execute("SELECT count(*) AS n FROM enriquecimiento_paso WHERE proveedor = 'claude_web'").fetchone()["n"] == 0


def test_solo_las_que_siguen_sin_telefono_y_solo_lo_verificado(api, sql, monkeypatch):
    empresas_sin_telefono(api, 3)
    claves(api, "google_places", "brave", "claude")
    configurar(api, claude_web_activo=True)
    # la 0 consigue teléfono en Places; la 1 y la 2 no
    Falso(monkeypatch, places={"Imprenta Número 0 S.A.": [lugar("Imprenta Número 0", tel="4733 0000")]})
    w = WebFalsa(monkeypatch, [("4733 1111", "https://www.imprenta.com.uy/contacto")],
                 {"https://www.imprenta.com.uy/contacto": "Imprenta Número · Contacto: (+598) 4733-1111"})
    est, c = correr(api, origen="lista", filtros={})
    assert est["estimacion"]["busqueda_web"]["maximo"] > 0
    assert sorted(x[0] for x in w.llamadas) == ["Imprenta Número 1 S.A.", "Imprenta Número 2 S.A."]
    assert w.llamadas[0][1:] == ("claude-haiku-5-5", 3)
    v = sql.execute("SELECT o.codigo, v.empresa_id FROM telefono_vinculo v JOIN telefono t ON t.id = v.telefono_id"
                    " JOIN telefono_vinculo_origen x ON x.vinculo_id = v.id JOIN origen_telefono o ON o.id = x.origen_id"
                    " WHERE t.e164 = '+59847331111'").fetchall()
    assert {r["codigo"] for r in v} == {"claude_web"} and {r["empresa_id"] for r in v} == {emp_id(sql, 1), emp_id(sql, 2)}
    paso = sql.execute("SELECT * FROM enriquecimiento_paso WHERE proveedor = 'claude_web' ORDER BY id LIMIT 1").fetchone()
    assert paso["resultado"] == "ok" and paso["url"] == "https://www.imprenta.com.uy/contacto"
    assert paso["detalle"]["propuestos"] == 1 and paso["detalle"]["verificados"] == 1
    # costo = búsquedas × precio + tokens reales, sin pasar la reserva
    esperado = 2 * 0.01 + (20000 * 0.10 + 500 * 0.50) / 1_000_000
    assert float(paso["costo"]) == pytest.approx(esperado) and float(paso["costo"]) <= paso["detalle"]["reserva"]
    # pantalla: la fila del paso y el origen con la página fuente en la ficha
    fila = next(p for p in c["pasos"] if p["proveedor"] == "claude_web" and p["resultado"] == "ok")
    assert (fila["propuestos"], fila["verificados"], fila["busquedas"]) == (2, 2, 4)
    tel = next(t for t in api.get(f"/empresas/{rut_valido(1)}", rol="steward").json()["telefonos"]
               if t["e164"] == "+59847331111")
    assert tel["origenes"][0]["codigo"] == "claude_web" and tel["origenes"][0]["url"] == "https://www.imprenta.com.uy/contacto"
    # deshacer saca los teléfonos de este origen
    assert api.post(f"/enriquecimiento/{c['id']}/deshacer", rol="steward").status_code == 200
    assert sql.execute("SELECT count(*) AS n FROM telefono_vinculo_origen x JOIN origen_telefono o ON o.id = x.origen_id"
                       " WHERE o.codigo = 'claude_web'").fetchone()["n"] == 0


def test_numero_que_no_esta_en_la_pagina_se_descarta(api, sql, monkeypatch):
    empresas_sin_telefono(api, 1)
    claves(api, "google_places", "brave", "claude")
    configurar(api, claude_web_activo=True)
    Falso(monkeypatch)
    WebFalsa(monkeypatch, [("2901 5555", "https://www.otra.com.uy/contacto"), ("2901 6666", "")],
             {"https://www.otra.com.uy/contacto": "Contacto: 2901 7777"})
    _, c = correr(api, origen="ficha", rut=rut_valido(0))
    paso = sql.execute("SELECT * FROM enriquecimiento_paso WHERE proveedor = 'claude_web'").fetchone()
    assert paso["resultado"] == "sin_resultado" and paso["detalle"]["no_verificados"] == 2
    assert set(paso["detalle"]["motivos_no_verificados"]) == {"el número no aparece en la página", "sin la página donde aparece"}
    assert "2901" not in str(paso["detalle"])    # los números propuestos no quedan en el registro
    assert sql.execute("SELECT count(*) AS n FROM telefono_vinculo").fetchone()["n"] == 0


def test_baja_confianza_o_directorio_lejos_del_nombre(api, sql, monkeypatch):
    empresas_sin_telefono(api, 2)
    claves(api, "google_places", "brave", "claude")
    configurar(api, claude_web_activo=True)
    Falso(monkeypatch)
    relleno = "x " * 400
    WebFalsa(monkeypatch, [("2901 5555", "https://www.paginasamarillas.com.uy/a")],
             {"https://www.paginasamarillas.com.uy/a": f"Otra empresa 2901 5555 {relleno} Imprenta Número"})
    correr(api, origen="lista", filtros={})
    motivos = [m for r in sql.execute("SELECT detalle FROM enriquecimiento_paso WHERE proveedor = 'claude_web'").fetchall()
               for m in r["detalle"]["motivos_no_verificados"]]
    assert motivos == ["en un directorio, lejos del nombre de la empresa"] * 2


def test_confianza_baja_no_entra(api, sql, monkeypatch):
    empresas_sin_telefono(api, 1)
    claves(api, "google_places", "brave", "claude")
    configurar(api, claude_web_activo=True)
    Falso(monkeypatch)
    WebFalsa(monkeypatch, [("2901 5555", "https://www.imp.com.uy/c")], {"https://www.imp.com.uy/c": "Tel 2901 5555"},
             confianza=0.3)
    correr(api, origen="ficha", rut=rut_valido(0))
    assert sql.execute("SELECT resultado FROM enriquecimiento_paso WHERE proveedor = 'claude_web'").fetchone()["resultado"] \
        == "sin_resultado"
    assert sql.execute("SELECT count(*) AS n FROM telefono_vinculo").fetchone()["n"] == 0


def test_tope_detiene_antes_de_llamar(api, sql, monkeypatch):
    """Si la reserva del paso 5 no entra en el tope, la corrida se detiene sin llamar y lo hecho queda guardado."""
    empresas_sin_telefono(api, 1)
    claves(api, "google_places", "brave", "claude")
    configurar(api, claude_web_activo=True, tope_corrida=20.0)

    def gastar(proveedor, n):   # al llamar a Places, otra parte de la corrida ya gastó casi todo el tope
        if proveedor == "google_places":
            cid = sql.execute("SELECT max(id) AS id FROM enriquecimiento_corrida").fetchone()["id"]
            sql.execute("INSERT INTO enriquecimiento_paso (corrida_id, proveedor, costo, resultado)"
                        " VALUES (%s, 'propias', 19.99, 'ok')", (cid,))
    Falso(monkeypatch, al_llamar=gastar)
    w = WebFalsa(monkeypatch, [("4733 1111", "https://x.com.uy/c")], {"https://x.com.uy/c": "4733 1111"})
    _, c = correr(api, origen="ficha", rut=rut_valido(0))
    assert w.llamadas == [] and c["estado"] == "detenida_tope"
    pasos = {r["proveedor"]: r["resultado"] for r in sql.execute(
        "SELECT proveedor, resultado FROM enriquecimiento_paso WHERE proveedor <> 'propias'")}
    assert pasos == {"google_places": "sin_resultado", "brave": "sin_resultado", "claude_web": "tope"}


def test_estimacion_y_reserva_web(api, sql):
    from app import config, enriquecimiento as enr

    cfg = config.ConfigEnriquecimiento().model_dump()
    assert cfg["claude_web_activo"] is False and cfg["claude_web_busquedas"] == 3 and cfg["precio_busqueda_web"] == 0.01
    assert enr.reserva_web(cfg) == pytest.approx(3 * 0.01 + (30000 * 0.10 + 2000 * 0.50) / 1_000_000)


def test_verificar_reconoce_formatos_del_numero(monkeypatch):
    b = prov.BusquedaWeb(telefonos=[{"numero": "+598 2900 1234", "url": "https://a.uy/c"},
                                    {"numero": "099 123 456", "url": "https://a.uy/c"}], confianza=0.9)
    monkeypatch.setattr(prov, "leer_pagina", lambda url: (_ for _ in ()).throw(prov.ProveedorError("no responde")))
    v = prov.verificar_telefonos(b, "Empresa Ejemplo", [])
    assert v.telefonos == [] and [x["motivo"] for x in v.no_verificados] == ["no responde", "la página no responde"]
    monkeypatch.setattr(prov, "leer_pagina", lambda url: "Central: (2) 900-1234 · Lic. Juan Pérez 099 123 456")
    v = prov.verificar_telefonos(b, "Empresa Ejemplo", [])
    assert v.telefonos == [("+59829001234", "https://a.uy/c")] and v.personales == 1


def test_llamada_a_claude_con_busqueda_web(monkeypatch):
    """El camino real con un cliente de Anthropic simulado: herramienta, pause_turn, búsquedas y JSON de la respuesta."""
    import types

    import anthropic

    pedidos = []

    def respuesta(stop, bloques, ent, sal, busq):
        uso = types.SimpleNamespace(input_tokens=ent, output_tokens=sal,
                                    server_tool_use=types.SimpleNamespace(web_search_requests=busq))
        return types.SimpleNamespace(stop_reason=stop, content=bloques, usage=uso)

    texto = types.SimpleNamespace(type="text", text='Encontré esto:\n```json\n{"telefonos": [{"numero": "2900 1234",'
                                                    ' "url": "https://e.com.uy/c"}], "web": "https://e.com.uy",'
                                                    ' "email": "info@e.com.uy", "direccion": null, "confianza": 0.9}\n```')
    respuestas = [respuesta("pause_turn", [types.SimpleNamespace(type="server_tool_use")], 9000, 100, 2),
                  respuesta("end_turn", [texto], 11000, 300, 1)]

    class Cliente:
        def __init__(self, **kw):
            assert kw["api_key"] == "clave-claude"
            self.messages = types.SimpleNamespace(create=self.create)

        def create(self, **kw):
            pedidos.append(kw)
            return respuestas.pop(0)

    monkeypatch.setattr(settings, "PROVEEDORES_MODO", "real")
    monkeypatch.setattr(prov, "clave", lambda p: "clave-claude")
    monkeypatch.setattr(anthropic, "Anthropic", Cliente)
    b = prov.claude_buscar_web({"razon_social": "Empresa SA", "localidad": "Salto"}, "claude-sonnet-5-5", 3)
    assert (b.busquedas, b.tokens_entrada, b.tokens_salida, b.confianza) == (3, 20000, 400, 0.9)
    assert b.telefonos == [{"numero": "2900 1234", "url": "https://e.com.uy/c"}] and b.email == "info@e.com.uy"
    herramienta = pedidos[0]["tools"][0]
    assert herramienta == {"type": "web_search_20260209", "name": "web_search", "max_uses": 3,
                           "user_location": {"type": "approximate", "country": "UY", "timezone": "America/Montevideo"}}
    assert len(pedidos[1]["messages"]) == 2 and pedidos[1]["messages"][1]["role"] == "assistant"   # continuó la pausa
    assert prov.herramienta_busqueda("claude-haiku-5-5", 2)["type"] == "web_search_20250305"


def test_leer_pagina_no_entra_a_direcciones_internas(monkeypatch):
    """La URL la eligió el modelo: ni metadatos de la nube ni servicios internos, tampoco por una redirección."""
    monkeypatch.setattr(settings, "PROVEEDORES_MODO", "real")
    for url in ("http://169.254.169.254/computeMetadata/v1/", "http://localhost:8080/api", "http://10.0.0.5/",
                "http://metadata.google.internal/", "http://[::1]/"):
        with pytest.raises(prov.ProveedorError, match="dirección interna"):
            prov.leer_pagina(url)
    assert not prov.host_publico("127.0.0.1") and not prov.host_publico("192.168.1.1")
    monkeypatch.setattr(prov.socket, "getaddrinfo", lambda h, p: [(None, None, None, "", ("8.8.8.8", 0))])
    assert prov.host_publico("www.ejemplo.com.uy")
