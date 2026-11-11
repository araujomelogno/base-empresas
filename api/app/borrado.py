"""Borrado definitivo de empresas y de cargas (solo administrador).

A diferencia de deshacer una carga (que anula y conserva la historia), esto elimina las filas:
la empresa con su historia, teléfonos vinculados, sucursales, contactos, atributos, su paso por
muestras y su actividad de campo (intentos del CDR y filas del .sav). Lo único que queda es el
registro en Auditoría. Sirve para limpiar pruebas y para pedidos de supresión (Ley 18.331).
"""
import logging

from fastapi import HTTPException

from . import auditoria, empresas, storage, tareas

log = logging.getLogger(__name__)


def _habilitar(conn):
    """Habilita el DELETE en las tablas de historia solo dentro de esta transacción (migración 0007)."""
    conn.execute("SET LOCAL empresas.purga = 'on'")


def _ids(conn, sql, args) -> list[int]:
    return [r["id"] for r in conn.execute(sql, args)]


def _con_absorbidas(conn, ids: list[int]) -> list[int]:
    """Las empresas fusionadas dentro de las que se borran son la misma empresa: se borran también."""
    if not ids:
        return []
    return _ids(conn, """
        WITH RECURSIVE t(id) AS (
          SELECT unnest(%s::int[])
          UNION SELECT e.id FROM empresa e JOIN t ON e.fusionada_en = t.id
        ) SELECT DISTINCT id FROM t""", (ids,))


def borrar_empresas(conn, ids: list[int]) -> dict:
    """Elimina las empresas y todo lo que cuelga de ellas. Devuelve los conteos."""
    ids = _con_absorbidas(conn, ids)
    if not ids:
        return {"empresas": 0}
    _habilitar(conn)
    x = conn.execute
    items = _ids(conn, "SELECT id FROM muestra_item WHERE empresa_id = ANY(%s)", (ids,))
    contactos = _ids(conn, "SELECT id FROM contacto WHERE empresa_id = ANY(%s)", (ids,))
    tels = [r["telefono_id"] for r in x(
        "SELECT DISTINCT telefono_id FROM telefono_vinculo WHERE empresa_id = ANY(%s)", (ids,))]
    n = {"empresas": len(ids), "items_de_muestra": len(items), "contactos": len(contactos)}

    # Campo: filas del .sav, intentos del CDR y estados por parte de sus ítems de muestra
    sav = _ids(conn, "SELECT id FROM sav_fila WHERE item_id = ANY(%s)", (items,))
    x("DELETE FROM telefono_vinculo WHERE empresa_id = ANY(%s)", (ids,))  # el origen cae en cascada
    intentos = _ids(conn, """
        SELECT i.id FROM intento i WHERE i.item_id = ANY(%s)
           OR (i.telefono_id = ANY(%s) AND NOT EXISTS (SELECT 1 FROM telefono_vinculo v WHERE v.telefono_id = i.telefono_id))""",
        (items, tels))
    x("DELETE FROM conciliacion WHERE (tipo = 'sav_fila' AND objeto_id = ANY(%s))"
      " OR (tipo = 'intento' AND objeto_id = ANY(%s))", (sav, intentos))
    x("DELETE FROM sav_fila WHERE id = ANY(%s)", (sav,))
    x("DELETE FROM intento WHERE id = ANY(%s)", (intentos,))
    x("DELETE FROM item_parte_estado WHERE item_id = ANY(%s)", (items,))
    x("DELETE FROM muestra_item WHERE id = ANY(%s)", (items,))
    x("DELETE FROM marco_snapshot_item WHERE empresa_id = ANY(%s)", (ids,))
    n.update(intentos=len(intentos), filas_sav=len(sav))

    # Base: revisión, fusiones, atributos, historia, contactos, sucursales, no llamar
    x("DELETE FROM revision_fusion WHERE candidata_id = ANY(%s)", (ids,))
    x("DELETE FROM empresa_fusion WHERE absorbente_id = ANY(%s) OR absorbida_id = ANY(%s)", (ids, ids))
    x("DELETE FROM empresa_atributo WHERE empresa_id = ANY(%s)", (ids,))
    x("DELETE FROM telefono_vinculo_historia WHERE empresa_id = ANY(%s)", (ids,))
    x("DELETE FROM empresa_campo_historia WHERE empresa_id = ANY(%s)", (ids,))
    x("DELETE FROM contacto WHERE id = ANY(%s)", (contactos,))
    x("DELETE FROM sucursal WHERE empresa_id = ANY(%s)", (ids,))
    x("DELETE FROM no_llamar WHERE (alcance = 'empresa' AND objeto_id = ANY(%s))"
      " OR (alcance = 'contacto' AND objeto_id = ANY(%s))", (ids, contactos))
    x("UPDATE empresa SET fusionada_en = NULL WHERE id = ANY(%s)", (ids,))
    x("DELETE FROM empresa WHERE id = ANY(%s)", (ids,))

    # Teléfonos que quedaron sin empresa y sin rastro (un «no llamar» por número se conserva)
    huerfanos = _ids(conn, """
        DELETE FROM telefono t WHERE t.id = ANY(%s)
          AND NOT EXISTS (SELECT 1 FROM telefono_vinculo v WHERE v.telefono_id = t.id)
          AND NOT EXISTS (SELECT 1 FROM intento i WHERE i.telefono_id = t.id)
          AND NOT EXISTS (SELECT 1 FROM item_parte_estado p WHERE p.telefono_id = t.id)
          AND NOT EXISTS (SELECT 1 FROM no_llamar l WHERE l.alcance = 'telefono' AND l.objeto_id = t.id)
        RETURNING t.id""", (tels,))
    n["telefonos"] = len(huerfanos)
    return n


def borrar_empresa(conn, rut: str, actor: str) -> dict:
    emp = empresas.obtener_o_404(conn, rut)
    conn.execute("SELECT id FROM empresa WHERE id = %s FOR UPDATE", (emp["id"],))
    n = borrar_empresas(conn, [emp["id"]])
    detalle = {"rut": emp["rut"], "razon_social": emp["razon_social"], **n}
    auditoria.registrar(conn, actor, "empresa.borrar", "empresa", emp["rut"], detalle)
    return detalle


# ─────────────────────────────────────────────────────────────
# Cargas
# ─────────────────────────────────────────────────────────────

def pedir_borrado_carga(conn, carga_id: int, actor: str) -> int:
    carga = conn.execute("SELECT * FROM carga WHERE id = %s FOR UPDATE", (carga_id,)).fetchone()
    if carga is None:
        raise HTTPException(404, "Carga inexistente")
    corriendo = conn.execute(
        "SELECT id FROM tarea WHERE estado = 'corriendo' AND creado > now() - interval '30 minutes'"
        " AND ((payload->>'carga_id')::int = %s OR (payload->>'borrar_carga_id')::int = %s)",
        (carga_id, carga_id)).fetchone()
    if corriendo:
        raise HTTPException(409, "La carga se está procesando: esperá a que termine para borrarla")
    # borrar_carga_id (y no carga_id) para que un error no deje la carga en estado «error»
    return tareas.crear(conn, "carga.borrar", {"borrar_carga_id": carga_id}, actor)


def _sin_respaldo(conn, ids: list[int]) -> list[int]:
    """Empresas a las que no les queda ningún dato vigente de otra fuente."""
    if not ids:
        return []
    return _ids(conn, """
        SELECT e.id FROM empresa e WHERE e.id = ANY(%s)
          AND NOT EXISTS (SELECT 1 FROM empresa_campo_historia h LEFT JOIN carga c
                            ON h.fuente_tipo = 'carga' AND c.id = h.fuente_id
                          WHERE h.empresa_id = e.id AND (c.id IS NULL OR c.estado NOT IN ('deshecha', 'descartada')))
          AND NOT EXISTS (SELECT 1 FROM telefono_vinculo v WHERE v.empresa_id = e.id)
          AND NOT EXISTS (SELECT 1 FROM contacto k WHERE k.empresa_id = e.id)""", (ids,))


@tareas.handler("carga.borrar")
def _tarea_borrar_carga(conn, payload, tarea_id):
    from .cargas import empresas_de_carga

    cid = payload["borrar_carga_id"]
    carga = conn.execute("SELECT * FROM carga WHERE id = %s FOR UPDATE", (cid,)).fetchone()
    if carga is None:
        return {"ya_borrada": True}
    _habilitar(conn)
    x = conn.execute
    ids = empresas_de_carga(conn, cid)
    tareas.progreso(tarea_id, 0, len(ids) + 1)

    # 1. Lo que la carga aportó a empresas, teléfonos, contactos y sucursales
    x("DELETE FROM telefono_vinculo_origen WHERE fuente_tipo = 'carga' AND fuente_id = %s", (cid,))
    tels = [r["telefono_id"] for r in x(
        "DELETE FROM telefono_vinculo WHERE fuente_tipo = 'carga' AND fuente_id = %s RETURNING telefono_id", (cid,))]
    x("UPDATE telefono_vinculo SET contacto_id = NULL WHERE contacto_id IN "
      "(SELECT id FROM contacto WHERE fuente_tipo = 'carga' AND fuente_id = %s)", (cid,))
    x("DELETE FROM no_llamar WHERE alcance = 'contacto' AND objeto_id IN "
      "(SELECT id FROM contacto WHERE fuente_tipo = 'carga' AND fuente_id = %s)", (cid,))
    x("DELETE FROM contacto WHERE fuente_tipo = 'carga' AND fuente_id = %s", (cid,))
    x("UPDATE telefono_vinculo SET sucursal_id = NULL WHERE sucursal_id IN "
      "(SELECT id FROM sucursal WHERE fuente_tipo = 'carga' AND fuente_id = %s)", (cid,))
    x("UPDATE contacto SET sucursal_id = NULL WHERE sucursal_id IN "
      "(SELECT id FROM sucursal WHERE fuente_tipo = 'carga' AND fuente_id = %s)", (cid,))
    x("DELETE FROM sucursal WHERE fuente_tipo = 'carga' AND fuente_id = %s", (cid,))
    x("DELETE FROM telefono_vinculo_historia WHERE fuente_tipo = 'carga' AND fuente_id = %s", (cid,))
    x("DELETE FROM empresa_campo_historia WHERE fuente_tipo = 'carga' AND fuente_id = %s", (cid,))
    x("UPDATE empresa SET carga_alta_id = NULL WHERE carga_alta_id = %s", (cid,))

    # 2. Las empresas que solo existían por esta carga se borran; las demás se recalculan
    huerfanas = _sin_respaldo(conn, ids)
    n = borrar_empresas(conn, huerfanas)
    quedan = [r["id"] for r in x("SELECT id FROM empresa WHERE id = ANY(%s) ORDER BY id", (ids,))]
    for i, eid in enumerate(quedan, 1):
        empresas.recalcular(conn, eid)
        if i % 200 == 0:
            tareas.progreso(tarea_id, len(huerfanas) + i)
    x("""DELETE FROM telefono t WHERE t.id = ANY(%s)
          AND NOT EXISTS (SELECT 1 FROM telefono_vinculo v WHERE v.telefono_id = t.id)
          AND NOT EXISTS (SELECT 1 FROM intento i WHERE i.telefono_id = t.id)
          AND NOT EXISTS (SELECT 1 FROM item_parte_estado p WHERE p.telefono_id = t.id)
          AND NOT EXISTS (SELECT 1 FROM no_llamar l WHERE l.alcance = 'telefono' AND l.objeto_id = t.id)""", (tels,))

    # 3. La carga, sus tareas y su archivo
    x("DELETE FROM revision_fusion WHERE carga_id = %s", (cid,))
    x("DELETE FROM tarea WHERE (payload->>'carga_id')::int = %s", (cid,))
    x("DELETE FROM carga WHERE id = %s", (cid,))  # carga_rechazo cae en cascada
    arch = x("SELECT * FROM archivo a WHERE a.id = %s"
             " AND NOT EXISTS (SELECT 1 FROM carga c WHERE c.archivo_id = a.id)"
             " AND NOT EXISTS (SELECT 1 FROM sav_ingesta s WHERE s.archivo_id = a.id)",
             (carga["archivo_id"],)).fetchone()
    if arch:
        x("DELETE FROM archivo WHERE id = %s", (arch["id"],))
    resumen = {"carga_id": cid, "fuente": carga["fuente"], "estado_previo": carga["estado"],
               "empresas_borradas": n.get("empresas", 0), "empresas_recalculadas": len(quedan),
               "items_de_muestra": n.get("items_de_muestra", 0), "intentos": n.get("intentos", 0),
               "filas_sav": n.get("filas_sav", 0)}
    auditoria.registrar(conn, tareas_actor(conn, tarea_id), "carga.borrar", "carga", cid, resumen)
    tareas.progreso(tarea_id, len(ids) + 1, len(ids) + 1)
    if arch:
        try:
            storage.borrar(arch)
        except Exception:  # el archivo huérfano en el bucket no rompe el borrado
            log.warning("No se pudo borrar el archivo %s del bucket", arch["ruta"], exc_info=True)
    return resumen


def tareas_actor(conn, tarea_id) -> str:
    if tarea_id is None:
        return "sistema"
    r = conn.execute("SELECT creado_por FROM tarea WHERE id = %s", (tarea_id,)).fetchone()
    return r["creado_por"] if r else "sistema"
