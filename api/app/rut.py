"""Validación del RUT uruguayo (R1.1).

El RUT tiene 12 dígitos: 2 de registro (01–22), 6 de número, "001" y el dígito
verificador. El verificador se calcula con módulo 11 y pesos 4,3,2,9,8,7,6,5,4,3,2;
si el resultado da 10 el RUT es inválido.
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


def validar(valor) -> tuple[str | None, str | None]:
    """Devuelve (rut_compacto, None) si es válido o (None, motivo) si no."""
    s = compactar(valor)
    if not s:
        return None, "sin RUT"
    if not s.isdigit():
        return None, "RUT con caracteres no numéricos"
    if len(s) != 12:
        return None, f"RUT con {len(s)} dígitos (se esperan 12)"
    if not ("01" <= s[:2] <= "22"):
        return None, "RUT con registro inválido (dígitos 1–2)"
    if s[2:8] == "000000":
        return None, "RUT con número en cero"
    if s[8:11] != "001":
        return None, "RUT sin el 001 en las posiciones 9–11"
    dv = digito_verificador(s[:11])
    if dv is None or int(s[11]) != dv:
        return None, "dígito verificador incorrecto"
    return s, None


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
