"""Tests de la fase 0 con los datos sintéticos (sin base de datos)."""
import json

import pytest

import cargar_excluidos
import comun
import exp_a_cdr
import exp_b_sav
import exp_d_bases
import generar
import informe


@pytest.fixture(scope="module")
def datos(tmp_path_factory):
    d = tmp_path_factory.mktemp("ejemplo")
    r = generar.generar(d)
    r["dir"] = d
    r["salida"] = tmp_path_factory.mktemp("salida")
    return r


def test_generador_deterministico(tmp_path, datos):
    otra = generar.generar(tmp_path)
    assert (tmp_path / "cdr_septiembre.csv").read_bytes() == datos["rutas"]["cdr"].read_bytes()
    assert otra["conteos"]["cdr"] == datos["conteos"]["cdr"]


def test_config_seed_y_destinos_internos():
    cfg = comun.config_seed()
    assert cfg["destinos_internos"] == [r"^\d{1,5}$", r"^\*", r"^#"]
    assert cfg["umbral_intermediario"] == 5
    assert comun.destinos_internos()[:3] == cfg["destinos_internos"]


def test_exp_a_cruza_mas_del_95(datos):
    r = exp_a_cdr.ejecutar(datos["rutas"]["lista"], datos["rutas"]["cdr"], detalle=datos["salida"] / "nc.csv")
    esperado = datos["conteos"]["cdr"]
    c = r["conteos"]
    assert c["tramos_duplicados"] == esperado["tramos_duplicados"]
    assert c["internas"] == esperado["interno"]
    assert r["por_categoria"]["cruza"] == esperado["lista"]
    assert r["por_categoria"]["especial"] == esperado["especial"]
    assert r["por_categoria"]["internacional"] == esperado["internacional"]
    assert r["por_categoria"]["fuera_fijo"] + r["por_categoria"]["fuera_celular"] == esperado["fuera_de_lista"]
    assert r["porcentaje"] >= 95 and r["go"] is True
    assert r["prefijos_sugeridos"][0][0] == "9"
    assert set(r["por_origen"]) == {"campaña", "manual"}
    assert (datos["salida"] / "nc.csv").exists()
    assert "Experimento A" in r["markdown"]


def test_exp_a_prefijo_de_salida_recupera_llamadas(datos):
    sin = exp_a_cdr.ejecutar(datos["rutas"]["lista"], datos["rutas"]["cdr"])
    con = exp_a_cdr.ejecutar(datos["rutas"]["lista"], datos["rutas"]["cdr"], prefijos=["9"])
    assert con["por_categoria"]["cruza"] == sin["por_categoria"]["cruza"] + datos["conteos"]["cdr"]["prefijo_9"]


def test_exp_a_no_go_si_la_lista_no_corresponde(datos, tmp_path):
    otra = tmp_path / "otra.csv"
    comun.escribir_tabla(otra, ["rut", "telefono"], [("211234560019", "29000000")])
    r = exp_a_cdr.ejecutar(otra, datos["rutas"]["cdr"])
    assert r["go"] is False and "EC_TEL_USADO" in r["markdown"]


def test_exp_b_asocia_parte_a_y_b(datos):
    r = exp_b_sav.ejecutar(datos["rutas"]["lista"], [datos["rutas"]["sav_a"], datos["rutas"]["sav_b"]],
                           dir_salida=datos["salida"])
    a, b = r["partes"]
    assert a["mapeo"]["identificador"] == {"variable": "EC_ID_ITEM", "tipo": "id_item"}
    assert a["porcentaje"] >= 95 and a["metodos"]["id_item"] >= 110 and a["metodos"]["RUT"] == 2
    assert all(estado == "presente" for _, estado in a["bloque"])
    assert a["sin_mapear"] == {"calidad_tel=9": 3}
    # parte B: sin EC_ID_ITEM, se asocia por RUT y, con el RUT mal tipeado, por teléfono
    assert b["mapeo"]["identificador"]["tipo"] == "rut" and b["falta_id_item"]
    assert b["porcentaje"] >= 95 and b["metodos"]["teléfono"] == 2
    assert dict(b["bloque"])["EC_RESP_AREA"] == "falta"
    assert r["go"] is True and r["falta_id_item"] == ["parteB.sav"]
    mapeo = json.loads((datos["salida"] / "exp_b_mapeo_parteA.json").read_text())
    assert mapeo["valores"]["resultado"]["1"] == "completa"


def test_plantilla_json_coincide_con_lo_que_reconoce_app_sav():
    from app import sav

    tpl = json.loads(exp_b_sav.PLANTILLA.read_text(encoding="utf-8"))
    assert set(tpl["variables"]) <= set(sav.DESTINOS)
    assert tpl["identificador"]["variable"] in sav.ID_ITEM
    columnas = ["responseid", "status", "datesubmitted", "EC_ID_ITEM"] + list(tpl["variables"].values())
    sav.validar_mapeo(tpl, columnas)
    propuesta = sav.proponer(columnas, [], {}, None)
    for clave in ("response_id", "identificador", "variables"):
        assert propuesta[clave] == tpl[clave]
    for destino, mapa in sav.ESTANDAR_CALIDAD.items():
        assert tpl["valores"]["calidad_tel"][destino] == mapa


def test_exp_d_detecta_telefonos_compartidos(datos):
    r = exp_d_bases.ejecutar(datos["rutas"]["bases"], detalle_dir=datos["salida"])
    assert len(r["bases"]) == 3 and r["filas"] == sum(v for k, v in datos["conteos"]["bases"].items() if k != "compartidos")
    assert r["sin_rut"] > 0 and r["rut_invalido"] > 0 and r["ruts_en_varias_bases"] > 0
    assert r["ruts_duplicados_en_base"] > 0 and r["conflictos_razon"] > 0
    assert len(r["sospechosos"]) == 3
    assert max(n for _, n in r["sospechosos"]) >= 25 and min(n for _, n in r["sospechosos"]) >= 5
    assert r["por_umbral"][3] > r["por_umbral"][5]
    assert (datos["salida"] / "exp_d_telefonos_compartidos.csv").exists()


def test_cargar_excluidos(datos, tmp_path):
    r = cargar_excluidos.ejecutar(datos["rutas"]["excluidos"], salida=tmp_path / "nat.sql")
    codigos = {f["codigo"]: f for f in r["filas"]}
    assert set(codigos) == {"PUB", "GD", "PPNE", "EOI", "SUCES"}
    assert codigos["SUCES"]["origen_codigo"] == "catálogo base" and all(f["excluida"] for f in r["filas"])
    sql = (tmp_path / "nat.sql").read_text()
    assert "INSERT INTO empresas.naturaleza_juridica (codigo, nombre)" in sql and "ON CONFLICT (codigo)" in sql
    assert "naturalezas_excluidas" in sql


def test_cargar_excluidos_api(monkeypatch):
    enviados = []

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"codigo": "PUB", "config_version": 2}'

    def falso(req, timeout):
        enviados.append((req.full_url, dict(req.header_items()), json.loads(req.data)))
        return Resp()

    monkeypatch.setattr(cargar_excluidos.urllib.request, "urlopen", falso)
    res = cargar_excluidos.enviar_api([{"codigo": "PUB", "nombre": "Organismo público", "excluida": True}],
                                      "http://api/", dev_user="admin@equipos.com.uy")
    assert res[0][1] == 200
    url, cab, cuerpo = enviados[0]
    assert url == "http://api/api/naturalezas" and cab["X-dev-user"] == "admin@equipos.com.uy"
    assert cuerpo == {"codigo": "PUB", "nombre": "Organismo público", "excluida": True}


def test_informe_completo(datos, tmp_path):
    rt = datos["rutas"]
    r = informe.generar(rt["lista"], rt["cdr"], [rt["sav_a"], rt["sav_b"]], rt["bases"], rt["excluidos"],
                        salida=tmp_path / "informe.md", dir_detalle=tmp_path)
    assert r["decision"] == "GO"
    texto = (tmp_path / "informe.md").read_text()
    for titulo in ("Experimento A", "Experimento B", "Experimento C", "Experimento D", "naturalezas excluidas"):
        assert titulo in texto


def test_informe_ajustes_si_falla():
    a = {"go": False}
    b = {"go": False, "falla_por_url_variables": True}
    decision, ajustes = informe.decidir(a, b)
    assert decision.startswith("GO con ajustes")
    assert any("EC_TEL_USADO" in x for x in ajustes) and any("RUT + teléfono" in x for x in ajustes)
    assert informe.decidir({"go": None}, {"go": True})[0].startswith("INCOMPLETA")
