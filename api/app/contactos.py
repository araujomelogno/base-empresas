"""Contactos como entidad (SPEC_mejoras_sav_contactos, F2.2, F2.4, F3.1–F3.3; D40).

- contacto_historia: cada alta y cada cambio de campo, con fuente y actor (append-only).
- contacto_telefono: con qué número se habló con el contacto (.sav) y cuáles son sus números.
- Borrar un contacto es definitivo (dato personal, Ley 18.331): se va con su historia, sus
  relaciones con teléfonos, sus atributos y su «no llamar».
"""
import re

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria
from .util import razon_normalizada

CAMPOS = ("nombre", "cargo", "area", "email", "sucursal_id")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def historia(conn, contacto: dict, campo: str, valor, fuente_tipo: str, fuente_id, actor: str | None, detalle=None):
    conn.execute(
        "INSERT INTO contacto_historia (contacto_id, empresa_id, campo, valor, fuente_tipo, fuente_id, actor, detalle)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (contacto["id"], contacto["empresa_id"], campo, None if valor is None else str(valor), fuente_tipo, fuente_id,
         actor, Jsonb(_json(detalle)) if detalle else None))


def _json(d):
    if isinstance(d, dict):
        return {k: _json(v) for k, v in d.items()}
    if isinstance(d, (list, tuple)):
        return [_json(v) for v in d]
    if hasattr(d, "isoformat"):
        return d.isoformat()
    return d


def normalizar_email(email) -> str | None:
    e = str(email or "").strip().lower()
    return e or None


def validar_email(email) -> str | None:
    e = normalizar_email(email)
    if e and not EMAIL.match(e):
        raise HTTPException(422, f"El email «{email}» no tiene un formato válido")
    return e


def buscar(conn, empresa_id: int, nombre: str | None, email: str | None = None) -> dict | None:
    """El contacto de la empresa con el mismo nombre normalizado o el mismo email."""
    clave = razon_normalizada(nombre) if nombre else None
    email = normalizar_email(email)
    for c in conn.execute("SELECT * FROM contacto WHERE empresa_id = %s ORDER BY id", (empresa_id,)).fetchall():
        if (clave and razon_normalizada(c["nombre"]) == clave) or (email and normalizar_email(c["email"]) == email):
            return c
    return None


def relacionar_telefono(conn, contacto_id: int, telefono_id: int, relacion: str, fuente_tipo: str, fuente_id,
                        fecha=None, clave: str | None = None) -> bool:
    """Registra (o actualiza) la relación contacto–teléfono. clave: identifica la evidencia (una fila del .sav),
    para que volver a aplicar lo mismo no sume «veces». Devuelve True si la relación es nueva."""
    claves = [clave] if clave else []
    r = conn.execute(
        "INSERT INTO contacto_telefono (contacto_id, telefono_id, relacion, fuente_tipo, fuente_id, primera_vez, ultima_vez,"
        " claves) VALUES (%(c)s, %(t)s, %(r)s, %(ft)s, %(fi)s, coalesce(%(f)s, now()), coalesce(%(f)s, now()), %(k)s)"
        " ON CONFLICT (contacto_id, telefono_id, relacion) DO NOTHING RETURNING id",
        {"c": contacto_id, "t": telefono_id, "r": relacion, "ft": fuente_tipo, "fi": fuente_id, "f": fecha,
         "k": claves}).fetchone()
    if r:
        return True
    if clave:
        conn.execute(
            "UPDATE contacto_telefono SET claves = array_append(claves, %(k)s), veces = veces + 1,"
            " fuente_tipo = CASE WHEN coalesce(%(f)s, now()) >= ultima_vez THEN %(ft)s ELSE fuente_tipo END,"
            " fuente_id = CASE WHEN coalesce(%(f)s, now()) >= ultima_vez THEN %(fi)s ELSE fuente_id END,"
            " ultima_vez = greatest(ultima_vez, coalesce(%(f)s, now())),"
            " primera_vez = least(primera_vez, coalesce(%(f)s, now()))"
            " WHERE contacto_id = %(c)s AND telefono_id = %(t)s AND relacion = %(r)s AND NOT (%(k)s = ANY(claves))",
            {"c": contacto_id, "t": telefono_id, "r": relacion, "ft": fuente_tipo, "fi": fuente_id, "f": fecha, "k": clave})
    return False


def telefonos(conn, contacto_ids: list[int]) -> dict[int, list[dict]]:
    """Números de cada contacto, con la leyenda de dónde salen (estudio y parte cuando vienen del .sav)."""
    out: dict[int, list[dict]] = {}
    if not contacto_ids:
        return out
    for r in conn.execute(
            "SELECT ct.contacto_id, ct.telefono_id, ct.relacion, ct.fuente_tipo, ct.fuente_id, ct.primera_vez, ct.ultima_vez,"
            " ct.veces, t.e164, t.crudo, p.nombre AS parte, s.nombre AS estudio"
            " FROM contacto_telefono ct JOIN telefono t ON t.id = ct.telefono_id"
            " LEFT JOIN sav_ingesta i ON ct.fuente_tipo = 'sala' AND i.id = ct.fuente_id"
            " LEFT JOIN parte p ON p.id = i.parte_id LEFT JOIN estudio s ON s.id = p.estudio_id"
            " WHERE ct.contacto_id = ANY(%s) ORDER BY ct.relacion DESC, ct.ultima_vez DESC", (contacto_ids,)):
        out.setdefault(r["contacto_id"], []).append(r)
    return out


def borrar(conn, ids: list[int]) -> int:
    """Borra definitivamente los contactos con su historia, sus teléfonos, sus atributos y su «no llamar».
    Habilita la purga de la historia solo para este DELETE y deja el ajuste como estaba."""
    ids = sorted({i for i in ids or [] if i is not None})
    if not ids:
        return 0
    antes = conn.execute("SELECT coalesce(current_setting('empresas.purga', true), '') AS v").fetchone()["v"]
    conn.execute("SET LOCAL empresas.purga = 'on'")
    conn.execute("DELETE FROM contacto_historia WHERE contacto_id = ANY(%s)", (ids,))
    if antes != "on":
        conn.execute("SET LOCAL empresas.purga = 'off'")
    conn.execute("UPDATE telefono_vinculo SET contacto_id = NULL WHERE contacto_id = ANY(%s)", (ids,))
    conn.execute("DELETE FROM no_llamar WHERE alcance = 'contacto' AND objeto_id = ANY(%s)", (ids,))
    conn.execute("DELETE FROM contacto_telefono WHERE contacto_id = ANY(%s)", (ids,))
    conn.execute("DELETE FROM contacto_atributo WHERE contacto_id = ANY(%s)", (ids,))
    return conn.execute("DELETE FROM contacto WHERE id = ANY(%s) RETURNING id", (ids,)).rowcount


def registrar_borrado(conn, actor: str, rut: str, contacto_id: int, motivo: str | None = None):
    """Auditoría del borrado de un contacto: el RUT y el id, nunca el nombre (dato personal)."""
    auditoria.registrar(conn, actor, "contacto.borrar", "empresa", rut, {"contacto_id": contacto_id, "motivo": motivo})
