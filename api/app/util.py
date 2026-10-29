"""Utilidades comunes: JSON, normalización de texto, fechas."""
import datetime as dt
import decimal
import json
import re
import unicodedata
from zoneinfo import ZoneInfo

from . import settings

TZ = ZoneInfo(settings.TZ)


def _default(o):
    if isinstance(o, (dt.datetime, dt.date, dt.time)):
        return o.isoformat()
    if isinstance(o, decimal.Decimal):
        return float(o)
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if isinstance(o, bytes):
        return o.decode("utf-8", "replace")
    raise TypeError(f"No serializable: {type(o)}")


def json_dumps(o) -> str:
    return json.dumps(o, default=_default, ensure_ascii=False)


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


FORMAS_SOCIETARIAS = r"\b(s\.?\s?a\.?|s\.?\s?r\.?\s?l\.?|s\.?\s?a\.?\s?s\.?|ltda\.?|sociedad anonima|limitada|cia\.?|y cia)\b"


def razon_normalizada(s: str | None) -> str:
    """Razón social comparable: minúsculas, sin tildes, sin forma societaria ni puntuación."""
    if not s:
        return ""
    s = sin_tildes(str(s).lower())
    s = re.sub(FORMAS_SOCIETARIAS, " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def dominio(s: str | None) -> str:
    """Dominio web o de email: 'https://www.Empresa.com.uy/x' -> 'empresa.com.uy'."""
    if not s:
        return ""
    s = str(s).strip().lower()
    if "@" in s:
        s = s.split("@", 1)[1]
    s = re.sub(r"^[a-z]+://", "", s)
    s = s.split("/", 1)[0].split("?", 1)[0]
    s = re.sub(r"^www\d?\.", "", s)
    genericos = ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "adinet.com.uy", "vera.com.uy", "live.com")
    return "" if s in genericos or "." not in s else s


def texto(v) -> str | None:
    """Valor de celda a texto limpio (None si vacío)."""
    if v is None:
        return None
    if isinstance(v, float):
        if v != v:  # NaN
            return None
        if v.is_integer():
            v = int(v)
    s = str(v).strip()
    return s or None


def ahora() -> dt.datetime:
    return dt.datetime.now(TZ)
