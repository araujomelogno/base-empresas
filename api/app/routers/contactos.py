"""Contactos: alta, edición y borrado manual desde la ficha (F3.1) y sus atributos (F3.3).
Solo administrador y data steward. El borrado es definitivo (dato personal, Ley 18.331)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import catalogos, contactos, empresas
from ..auth import Usuario, requiere
from ..db import get_conn
from ..util import razon_normalizada

router = APIRouter()


class Contacto(BaseModel):
    nombre: str | None = None
    cargo: str | None = None
    area: str | None = None
    email: str | None = None
    sucursal_id: int | None = None
    telefonos: list[int] | None = None          # teléfonos de la empresa (telefono_id)
    telefonos_nuevos: list[str] | None = None   # números nuevos: se vinculan a la empresa como «manual»
    atributos: dict[str, str | None] | None = None
    forzar: bool = False                        # crear aunque haya otro con el mismo nombre


def _contacto(conn, contacto_id: int) -> tuple[dict, dict]:
    c = conn.execute("SELECT * FROM contacto WHERE id = %s FOR UPDATE", (contacto_id,)).fetchone()
    if c is None:
        raise HTTPException(404, "Contacto inexistente")
    emp = conn.execute("SELECT * FROM empresa WHERE id = %s", (c["empresa_id"],)).fetchone()
    return c, emp


def _limpio(v):
    v = (v or "").strip() if isinstance(v, str) else v
    return v or None


def _sucursal(conn, empresa_id: int, sucursal_id):
    if sucursal_id and not conn.execute("SELECT 1 FROM sucursal WHERE id = %s AND empresa_id = %s",
                                        (sucursal_id, empresa_id)).fetchone():
        raise HTTPException(422, "La sucursal no es de esta empresa")


def _telefonos(conn, emp: dict, contacto: dict, ids: list[int] | None, nuevos: list[str] | None, actor: str):
    """Deja como «números del contacto» los elegidos (y los nuevos); la relación «se habló» del .sav no se toca."""
    if ids is None and not nuevos:
        return
    prefijos = []
    ids = list(ids or [])
    for numero in nuevos or []:
        fila, n, _ = empresas.telefono(conn, numero, prefijos)
        if fila is None or not n.e164:
            raise HTTPException(422, f"El número «{numero}» no es válido: {n.motivo or 'no se pudo normalizar'}")
        empresas.vincular(conn, fila["id"], emp["id"], "manual", None, actor, origen="manual")
        ids.append(fila["id"])
    validos = {r["telefono_id"] for r in conn.execute(
        "SELECT telefono_id FROM telefono_vinculo WHERE empresa_id = %s AND telefono_id = ANY(%s)", (emp["id"], ids))}
    if set(ids) - validos:
        raise HTTPException(422, "Algún teléfono elegido no es de esta empresa")
    actuales = {r["telefono_id"]: r for r in conn.execute(
        "SELECT ct.telefono_id, t.e164 FROM contacto_telefono ct JOIN telefono t ON t.id = ct.telefono_id"
        " WHERE ct.contacto_id = %s AND ct.relacion = 'del_contacto'", (contacto["id"],))}
    for tid in set(ids) - set(actuales):
        contactos.relacionar_telefono(conn, contacto["id"], tid, "del_contacto", "manual", None)
        e164 = conn.execute("SELECT e164 FROM telefono WHERE id = %s", (tid,)).fetchone()["e164"]
        contactos.historia(conn, contacto, "telefono", e164, "manual", None, actor)
    if ids is not None:
        for tid in set(actuales) - set(ids):
            conn.execute("DELETE FROM contacto_telefono WHERE contacto_id = %s AND telefono_id = %s AND relacion = 'del_contacto'",
                         (contacto["id"], tid))
            contactos.historia(conn, contacto, "telefono", None, "manual", None, actor,
                               {"quitado": actuales[tid]["e164"]})


def _atributos(conn, contacto: dict, valores: dict | None, actor: str):
    for clave, valor in (valores or {}).items():
        if _limpio(valor) is None:
            catalogos.quitar_atributo_contacto(conn, contacto, clave, "manual", None, actor)
            continue
        a = conn.execute("SELECT * FROM atributo WHERE clave = %s AND ambito = 'contacto'", (clave,)).fetchone()
        if a is None:
            raise HTTPException(422, f"Atributo de contacto desconocido: {clave}")
        v = catalogos.interpretar(a, valor)
        if not v["valido"]:
            raise HTTPException(422, f"«{valor}» no es un valor válido para {a['nombre']}")
        catalogos.aplicar_atributo_contacto(conn, contacto, clave, valor, "manual", None, actor)


@router.post("/empresas/{rut}/contactos")
def crear(rut: str, body: Contacto, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    emp = empresas.obtener_o_404(conn, rut)
    nombre = _limpio(body.nombre)
    if not nombre:
        raise HTTPException(422, "El nombre del contacto es obligatorio")
    email = contactos.validar_email(body.email)
    _sucursal(conn, emp["id"], body.sucursal_id)
    if not body.forzar:
        clave = razon_normalizada(nombre)
        for c in conn.execute("SELECT id, nombre FROM contacto WHERE empresa_id = %s", (emp["id"],)).fetchall():
            if razon_normalizada(c["nombre"]) == clave:
                raise HTTPException(409, {"mensaje": f"Ya hay un contacto con ese nombre en la empresa: {c['nombre']}",
                                          "duplicado": c["id"]})
    c = conn.execute(
        "INSERT INTO contacto (empresa_id, sucursal_id, nombre, cargo, area, email, fuente_tipo, fuente_id)"
        " VALUES (%s,%s,%s,%s,%s,%s,'manual',NULL) RETURNING *",
        (emp["id"], body.sucursal_id, nombre, _limpio(body.cargo), _limpio(body.area), email)).fetchone()
    contactos.historia(conn, c, "alta", nombre, "manual", None, u.email)
    for k in ("cargo", "area", "email", "sucursal_id"):
        if c[k]:
            contactos.historia(conn, c, k, c[k], "manual", None, u.email)
    _telefonos(conn, emp, c, body.telefonos, body.telefonos_nuevos, u.email)
    _atributos(conn, c, body.atributos, u.email)
    return {"id": c["id"]}


@router.patch("/contactos/{contacto_id}")
def editar(contacto_id: int, body: Contacto, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    c, emp = _contacto(conn, contacto_id)
    d = body.model_dump(exclude_unset=True)
    nuevos = {}
    if "nombre" in d:
        if not _limpio(d["nombre"]):
            raise HTTPException(422, "El nombre del contacto es obligatorio")
        nuevos["nombre"] = _limpio(d["nombre"])
    for k in ("cargo", "area"):
        if k in d:
            nuevos[k] = _limpio(d[k])
    if "email" in d:
        nuevos["email"] = contactos.validar_email(d["email"])
    if "sucursal_id" in d:
        _sucursal(conn, emp["id"], d["sucursal_id"])
        nuevos["sucursal_id"] = d["sucursal_id"]
    cambios = {k: v for k, v in nuevos.items() if v != c[k]}
    if cambios:
        conn.execute(f"UPDATE contacto SET {', '.join(f'{k} = %s' for k in cambios)}, actualizado = now() WHERE id = %s",
                     (*cambios.values(), contacto_id))
        for k, v in cambios.items():  # cada campo que cambia queda en la historia, con fuente manual y el usuario
            contactos.historia(conn, c, k, v, "manual", None, u.email)
    _telefonos(conn, emp, c, d.get("telefonos"), d.get("telefonos_nuevos"), u.email)
    _atributos(conn, c, d.get("atributos"), u.email)
    if cambios or d.get("telefonos") is not None or d.get("telefonos_nuevos") or d.get("atributos"):
        conn.execute("UPDATE contacto SET actualizado = now() WHERE id = %s", (contacto_id,))
    return {"id": contacto_id, "cambios": list(cambios)}


@router.delete("/contactos/{contacto_id}")
def borrar(contacto_id: int, motivo: str | None = None, conn=Depends(get_conn), u: Usuario = Depends(requiere("steward"))):
    """Borrado definitivo: el contacto, su historia, sus teléfonos, sus atributos y su «no llamar».
    En Auditoría queda el RUT y el id del contacto, sin el nombre."""
    c, emp = _contacto(conn, contacto_id)
    contactos.borrar(conn, [contacto_id])
    contactos.registrar_borrado(conn, u.email, emp["rut"], contacto_id, motivo)
    return {"borrado": contacto_id}
