"""Normalización de teléfonos uruguayos a E.164 (reglas de la fase 0, R1.2).

Plan de numeración vigente (desde 2010), número nacional de 8 dígitos:
  - fijos:     2XXXXXXX (Montevideo) y 4XXXXXXX (interior)
  - celulares: 9XXXXXXX, que se discan 09XXXXXXX
  - especiales: 0800, 0900, 0901, 0905, 0909 y números cortos (911, 1XX…)

Formas de entrada aceptadas para el mismo número:
  +598 2901 1234 · 00598 29011234 · 598 29011234 · 2901-1234 · (02) 901 1234
  098 123 456 · 98123456 · +598 98 123 456 · 042 22 1234 (formato anterior con 0)

Lo que tiene 5 dígitos o menos se considera interno (extensiones, conferencias).
Los números de 7 dígitos son del formato anterior a 2010 y no se completan solos.
"""
import re
from dataclasses import dataclass

PAIS = "598"
ESPECIALES = ("0800", "0900", "0901", "0905", "0909", "0904")


@dataclass(frozen=True)
class Telefono:
    e164: str | None
    tipo: str            # fijo | celular | especial | internacional | interno | invalido
    crudo: str
    motivo: str | None = None

    @property
    def discable(self) -> bool:
        return self.tipo in ("fijo", "celular")

    @property
    def nacional(self) -> str | None:
        return nacional(self.e164)


def _limpiar(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    s = str(valor).strip()
    # Saca el interno escrito a mano: "2901 1234 int. 25", "interno 25", "ext 25"
    s = re.split(r"(?i)\b(int(erno)?|ext(ensi[oó]n)?)\b\.?", s)[0]
    return s


def _nacional(d: str, crudo: str) -> Telefono:
    """Clasifica un número sin código de país."""
    if len(d) == 9 and d[0] == "0" and d[1] in "24":
        d = d[1:]                      # formato con 0 de larga distancia: 042221234, 029011234
    if len(d) == 9 and d.startswith("09") and d[2] != "0":
        return Telefono(f"+{PAIS}{d[1:]}", "celular", crudo)
    if len(d) == 8:
        if d[0] in "24":
            return Telefono(f"+{PAIS}{d}", "fijo", crudo)
        if d[0] == "9" and d[1] != "0":
            return Telefono(f"+{PAIS}{d}", "celular", crudo)
        if d.startswith(ESPECIALES):
            return Telefono(f"+{PAIS}{d[1:]}", "especial", crudo)
    if d.startswith(ESPECIALES) and len(d) in (7, 8):
        return Telefono(f"+{PAIS}{d[1:]}", "especial", crudo)
    if len(d) <= 5:
        if len(d) in (3, 4) and d[0] == "1" or d == "911":
            return Telefono(None, "especial", crudo, "número corto de servicio")
        return Telefono(None, "interno", crudo, "5 dígitos o menos")
    if len(d) == 7:
        return Telefono(None, "invalido", crudo, "7 dígitos: formato anterior a 2010")
    return Telefono(None, "invalido", crudo, f"{len(d)} dígitos sin formato reconocido")


def normalizar(valor, prefijos_salida=()) -> Telefono:
    crudo = _limpiar(valor)
    if not crudo:
        return Telefono(None, "invalido", "", "vacío")
    mas = crudo.lstrip().startswith("+")
    d = re.sub(r"\D", "", crudo)
    if not d:
        return Telefono(None, "invalido", crudo, "sin dígitos")
    # Prefijos que agrega la central para tomar línea (configurables)
    for p in prefijos_salida or ():
        if p and d.startswith(p) and len(d) - len(p) >= 8:
            d = d[len(p):]
            break
    if mas or d.startswith("00"):
        d = d[2:] if d.startswith("00") and not mas else d
        if d.startswith(PAIS):
            return _nacional(d[len(PAIS):], crudo)
        if len(d) < 8:
            return Telefono(None, "invalido", crudo, "internacional demasiado corto")
        return Telefono(f"+{d}", "internacional", crudo)
    if d.startswith(PAIS) and len(d) == len(PAIS) + 8:
        return _nacional(d[len(PAIS):], crudo)
    return _nacional(d, crudo)


def nacional(e164: str | None) -> str | None:
    """Formato para discar desde Uruguay: 29011234 o 098123456."""
    if not e164 or not e164.startswith("+" + PAIS):
        return None
    n = e164[1 + len(PAIS):]
    return "0" + n if n[0] in "9" or n.startswith(tuple(e[1:] for e in ESPECIALES)) else n


def separar(valor) -> list[str]:
    """Separa una celda con varios teléfonos: '2901 1234 / 099 123 456; 4222 1234'."""
    s = _limpiar_multi(valor)
    if not s:
        return []
    partes = re.split(r"\s*(?:/|;|,|\||\by\b|\bo\b)\s*", s)
    return [p for p in (x.strip() for x in partes) if re.search(r"\d", p)]


def _limpiar_multi(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def es_interno(destino: str, patrones) -> bool:
    """Destinos internos del CDR: patrones regex (si empiezan con ^) o números exactos."""
    d = re.sub(r"\s", "", str(destino or ""))
    for p in patrones or ():
        if p.startswith("^"):
            if re.search(p, d):
                return True
        elif d == p:
            return True
    return False
