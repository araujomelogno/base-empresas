"""Reglas puras: RUT, teléfonos, sorteo, franjas (fase 0 y R1.1, R1.2, R1.6, R1.8)."""
import datetime as dt

import pytest

from app import cdr, muestras, rut, telefonos
from app.util import TZ, dominio, razon_normalizada


def test_rut_valido_e_invalido():
    bueno = rut.con_verificador("21003456001")
    assert rut.validar(bueno) == (bueno, None)
    assert rut.validar(rut.formatear(bueno))[0] == bueno
    malo = bueno[:-1] + str((int(bueno[-1]) + 1) % 10)
    assert rut.validar(malo) == (None, "dígito verificador incorrecto")
    assert rut.validar("")[1] == "sin RUT"
    assert "se esperan 12" in rut.validar("2100345600")[1]
    assert rut.validar("991234560018")[1].startswith("RUT con registro inválido")


def test_rut_excel_come_cero():
    bueno = rut.con_verificador("01003456001")
    assert rut.validar(int(bueno))[0] == bueno
    assert rut.validar(float(int(bueno)))[0] == bueno


@pytest.mark.parametrize("entrada,e164,tipo", [
    ("+598 2901 1234", "+59829011234", "fijo"),
    ("00598 29011234", "+59829011234", "fijo"),
    ("598 29011234", "+59829011234", "fijo"),
    ("2901-1234", "+59829011234", "fijo"),
    ("(02) 901 1234", "+59829011234", "fijo"),
    ("042 22 1234", "+59842221234", "fijo"),
    ("4222 1234", "+59842221234", "fijo"),
    ("098 123 456", "+59898123456", "celular"),
    ("98123456", "+59898123456", "celular"),
    ("+598 98 123 456", "+59898123456", "celular"),
    (98123456.0, "+59898123456", "celular"),
    ("2901 1234 int. 25", "+59829011234", "fijo"),
    ("0800 1234", "+5988001234", "especial"),
    ("+54 11 4321 1234", "+541143211234", "internacional"),
])
def test_normalizacion(entrada, e164, tipo):
    n = telefonos.normalizar(entrada)
    assert (n.e164, n.tipo) == (e164, tipo)


@pytest.mark.parametrize("entrada,tipo", [("123", "especial"), ("4501", "interno"), ("25", "interno"), ("911", "especial"),
                                          ("9011234", "invalido"), ("", "invalido"), ("abc", "invalido"),
                                          ("12345678901234", "invalido")])
def test_no_discables(entrada, tipo):
    n = telefonos.normalizar(entrada)
    assert n.tipo == tipo and n.e164 is None


def test_prefijo_de_salida():
    assert telefonos.normalizar("9098123456", prefijos_salida=["9"]).e164 == "+59898123456"


def test_nacional():
    assert telefonos.nacional("+59829011234") == "29011234"
    assert telefonos.nacional("+59898123456") == "098123456"


def test_separar():
    assert telefonos.separar("2901 1234 / 099 123 456; 4222 1234") == ["2901 1234", "099 123 456", "4222 1234"]
    assert telefonos.separar(None) == []


def test_internos():
    pat = ["^\\d{1,5}$", "^\\*", "8000000"]
    assert telefonos.es_interno("4501", pat)
    assert telefonos.es_interno("*97", pat)
    assert telefonos.es_interno("8000000", pat)
    assert not telefonos.es_interno("098123456", pat)


def test_sorteo_reproducible_y_ordenado():
    marco = [(i, "A" if i % 2 else "B") for i in range(1, 201)]
    d = {"A": (10, 5), "B": (8, 2)}
    s1 = muestras.sortear_snapshot(marco, 42, d)
    s2 = muestras.sortear_snapshot(list(reversed(marco)), 42, d)
    assert s1 == s2
    assert len([x for x in s1 if x[1] == "A" and x[2] == "titular"]) == 10
    assert len([x for x in s1 if x[1] == "A" and x[2] == "reemplazo"]) == 5
    assert muestras.sortear_snapshot(marco, 43, d) != s1


def test_estrato_de():
    f = {"tamano": "Grande", "departamento": None, "ciiu": "4711"}
    assert muestras.estrato_de(f, ["tamano", "departamento"]) == "Grande | (sin dato)"
    assert muestras.estrato_de(f, ["ciiu2"]) == "47"
    assert muestras.estrato_de(f, []) == "Total"


def test_franjas():
    franjas = [{"nombre": "mañana", "dias": [1, 2, 3, 4, 5], "desde": "10:00", "hasta": "16:30"},
               {"nombre": "tarde", "dias": [1, 2, 3, 4, 5], "desde": "16:30", "hasta": "23:59"},
               {"nombre": "fin de semana", "dias": [6, 7], "desde": "00:00", "hasta": "23:59"}]
    lunes = dt.datetime(2026, 10, 26, 11, 0, tzinfo=TZ)
    assert cdr.franja(lunes, franjas) == "mañana"
    assert cdr.franja(lunes.replace(hour=16, minute=30), franjas) == "tarde"
    assert cdr.franja(lunes.replace(hour=23, minute=59, second=30), franjas) == "tarde"
    assert cdr.franja(lunes.replace(hour=9), franjas) == "fuera de franja"
    assert cdr.franja(dt.datetime(2026, 10, 31, 9, 0, tzinfo=TZ), franjas) == "fin de semana"


def test_textos():
    assert razon_normalizada("Pérez Hnos. S.A.") == razon_normalizada("PEREZ HNOS SA")
    assert dominio("https://www.Empresa.com.uy/contacto") == "empresa.com.uy"
    assert dominio("ventas@empresa.com.uy") == "empresa.com.uy"
    assert dominio("fulano@gmail.com") == ""
