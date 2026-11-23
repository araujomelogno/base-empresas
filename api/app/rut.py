"""Validación del RUT uruguayo (R1.1).

El RUT tiene 12 dígitos: 2 de registro (01–22), 6 de número, "001" y el dígito
verificador. El verificador se calcula con módulo 11 y pesos 4,3,2,9,8,7,6,5,4,3,2;
si el resultado da 10 el RUT es inválido.

D54 (SPEC_rut_sin_control_de_largo): con «cortos», un identificador de 6 a 11 dígitos (por ejemplo, la cédula de una
unipersonal) se acepta sin validar el registro ni el dígito verificador: queda como RUT «no verificado». Un valor de
12 dígitos se valida siempre como RUT de la DGI.
"""
import re

PESOS = (4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def compactar(valor) -> str:
    """Saca puntos, guiones, espacios y el prefijo 'UY'. Repone ceros a la izquierda
    que Excel suele comer (un RUT de 11 dígitos que empieza con 1–9)."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    s = re.sub(r"[\s.\-/]", "", str(valor)).upper()
    if s.startswith("UY"):
        s = s[2:]
    if len(s) == 11 and s.isdigit():
        s = "0" + s
    return s


def digito_verificador(primeros11: str) -> int | None:
    total = sum(int(d) * p for d, p in zip(primeros11, PESOS))
    dv = (11 - total % 11) % 11
    return None if dv == 10 else dv


CORTO_MIN, CORTO_MAX = 6, 11


def _validar12(s: str) -> str | None:
    """El motivo por el que un valor de 12 dígitos no es un RUT válido, o None si lo es."""
    if not ("01" <= s[:2] <= "22"):
        return "RUT con registro inválido (dígitos 1–2)"
    if s[2:8] == "000000":
        return "RUT con número en cero"
    if s[8:11] != "001":
        return "RUT sin el 001 en las posiciones 9–11"
    dv = digito_verificador(s[:11])
    if dv is None or int(s[11]) != dv:
        return "dígito verificador incorrecto"
    return None


def validar(valor, cortos: bool = False) -> tuple[str | None, str | None]:
    """Devuelve (rut_compacto, None) si se acepta o (None, motivo) si no.
    cortos=True (D54): un identificador de 6 a 11 dígitos se acepta tal como vino, «no verificado»."""
    s = compactar(valor)
    if not s:
        return None, "sin RUT"
    if not s.isdigit():
        return None, "RUT con caracteres no numéricos"
    if len(s) == 12:
        motivo = _validar12(s)
        if motivo is None:
            return s, None
        original = re.sub(r"[\s.\-/]", "", str(int(valor) if isinstance(valor, float) and valor.is_integer() else valor)).upper()
        original = original[2:] if original.startswith("UY") else original
        # 11 dígitos a los que se les repuso el 0 de adelante y no dan un RUT válido: se aceptan como vinieron
        if cortos and len(original) == 11 and original.isdigit():
            return original, None
        return None, motivo
    if cortos and CORTO_MIN <= len(s) <= CORTO_MAX:
        return s, None
    return None, f"RUT con {len(s)} dígitos (se esperan 12)"


def verificado(rut: str | None) -> bool | None:
    """True: RUT de 12 dígitos validado; False: identificador aceptado sin validar (D54); None: sin RUT."""
    return None if not rut else len(rut) == 12


def es_valido(valor) -> bool:
    return validar(valor)[0] is not None


def con_verificador(primeros11: str) -> str:
    """Completa un RUT con su dígito verificador (útil para datos de prueba)."""
    dv = digito_verificador(primeros11)
    if dv is None:
        raise ValueError("Ese número no admite dígito verificador")
    return primeros11 + str(dv)


def formatear(rut: str) -> str:
    return f"{rut[:2]}.{rut[2:5]}.{rut[5:8]}.{rut[8:11]}-{rut[11]}" if rut and len(rut) == 12 else rut
