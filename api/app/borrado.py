"""Borrado definitivo de empresas, cargas, muestras y estudios (solo administrador).

A diferencia de deshacer una carga (que anula y conserva la historia), esto elimina las filas:
la empresa con su historia, teléfonos vinculados, sucursales, contactos, atributos, su paso por
muestras y su actividad de campo (intentos del CDR y filas del .sav). Lo único que queda es el
registro en Auditoría. Sirve para limpiar pruebas y para pedidos de supresión (Ley 18.331).

Borrar una muestra o un estudio (D37) elimina la muestra, sus ítems, sus intentos del CDR y sus
filas del .sav (y, para un estudio, sus partes e ingestas), pero conserva lo que el campo dejó en
la base: contactos, teléfonos, calidad de los números, historia y último contacto efectivo.

El marco congelado de cada sorteo no se toca nunca (V1): los ítems de muestra que se van con una
empresa o una carga se copian a muestra_item_borrado para que la verificación siga funcionando.

Cualquier carga se puede borrar, aunque esté «analizando» o «en proceso»: sus tareas se cancelan
(tareas.cancelar) y el borrado espera a que la tarea cancelada suelte la carga, con un tope.
"""
import logging

import psycopg
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


ESPERA_LOCK = "120s"   # tope para esperar que una tarea cancelada suelte lo que está por borrarse


def _esperar_locks(conn):
    conn.execute(f"SET LOCAL lock_timeout = '{ESPERA_LOCK}'")


def _ocupado(que: str) -> HTTPException:
    return HTTPException(409, f"{que} sigue ocupada por una tarea que todavía no terminó de detenerse."
                              " Esperá unos minutos y volvé a borrar.")


def borrar_empresas(conn, ids: list[int], accion: str = "empresa.borrar", actor: str = "sistema") -> dict:
    """Elimina las empresas y todo lo que cuelga de ellas. Devuelve los conteos.
    Los ítems de muestra se copian antes a muestra_item_borrado (n["_items_borrados"] tiene sus ids)."""
    ids = _con_absorbidas(conn, ids)
    if not ids:
        return {"empresas": 0, "_items_borrados": []}
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
    # El marco congelado no se toca: los ítems se registran para que la verificación los cuente
    n["_items_borrados"] = _ids(conn, """
        INSERT INTO muestra_item_borrado (muestra_id, item_id, empresa_id, estrato, rol, orden, liberado, accion, borrado_por)
        SELECT muestra_id, id, empresa_id, estrato, rol, orden, liberado, %s, %s FROM muestra_item WHERE id = ANY(%s)
        RETURNING id""", (accion, actor, items))
    x("DELETE FROM muestra_item WHERE id = ANY(%s)", (items,))
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


def _vincular_auditoria(conn, items_borrados: list[int], auditoria_id: int):
    if items_borrados:
        conn.execute("UPDATE muestra_item_borrado SET auditoria_id = %s WHERE id = ANY(%s)", (auditoria_id, items_borrados))


def borrar_empresa(conn, rut: str, actor: str) -> dict:
    emp = empresas.obtener_o_404(conn, rut)
    conn.execute("SELECT id FROM empresa WHERE id = %s FOR UPDATE", (emp["id"],))
    n = borrar_empresas(conn, [emp["id"]], "empresa.borrar", actor)
    items_borrados = n.pop("_items_borrados")
    detalle = {"rut": emp["rut"], "razon_social": emp["razon_social"], **n}
    _vincular_auditoria(conn, items_borrados, auditoria.registrar(conn, actor, "empresa.borrar", "empresa", emp["rut"], detalle))
    return detalle


# ─────────────────────────────────────────────────────────────
# Cargas
# ─────────────────────────────────────────────────────────────

def conteos_carga(conn, carga_id: int) -> dict:
    """Vista previa para el modal de confirmación (P1.1)."""
    from .cargas import empresas_de_carga

    carga = conn.execute("SELECT id, fuente, estado FROM carga WHERE id = %s", (carga_id,)).fetchone()
    if carga is None:
        raise HTTPException(404, "Carga inexistente")
    ids = empresas_de_carga(conn, carga_id)
    activas = conn.execute(
        "SELECT id, tipo, estado, creado FROM tarea WHERE estado IN ('pendiente','corriendo')"
        " AND (payload->>'carga_id')::int = %s ORDER BY id", (carga_id,)).fetchall()
    return {**carga, "empresas": len(ids), "solo_de_esta_carga": len(_sin_respaldo_previo(conn, carga_id, ids)),
            "en_muestras": conn.execute("SELECT count(DISTINCT empresa_id) AS n FROM muestra_item WHERE empresa_id = ANY(%s)",
                                        (ids,)).fetchone()["n"],
            "tareas_a_cancelar": activas}


def _sin_respaldo_previo(conn, carga_id: int, ids: list[int]) -> list[int]:
    """Empresas que quedarían sin ningún dato si se borrara la carga (estimación para el modal)."""
    if not ids:
        return []
    return _ids(conn, """
        SELECT e.id FROM empresa e WHERE e.id = ANY(%s)
          AND NOT EXISTS (SELECT 1 FROM empresa_campo_historia h LEFT JOIN carga c ON h.fuente_tipo = 'carga' AND c.id = h.fuente_id
                          WHERE h.empresa_id = e.id AND NOT (h.fuente_tipo = 'carga' AND h.fuente_id = %s)
                            AND (c.id IS NULL OR c.estado NOT IN ('deshecha', 'descartada')))
          AND NOT EXISTS (SELECT 1 FROM telefono_vinculo v WHERE v.empresa_id = e.id
                          AND NOT (v.fuente_tipo = 'carga' AND v.fuente_id = %s))
          AND NOT EXISTS (SELECT 1 FROM contacto k WHERE k.empresa_id = e.id
                          AND NOT (k.fuente_tipo = 'carga' AND k.fuente_id = %s))""", (ids, carga_id, carga_id, carga_id))


def pedir_borrado_carga(conn, carga_id: int, actor: str) -> int:
    """Se puede borrar cualquier carga, en cualquier estado (E3). Sin FOR UPDATE: si una tarea la está
    procesando, el pedido no la espera; la cancela y la tarea de borrado espera a que la suelte."""
    carga = conn.execute("SELECT id FROM carga WHERE id = %s", (carga_id,)).fetchone()
    if carga is None:
        raise HTTPException(404, "Carga inexistente")
    tareas.cancelar("(tipo IN ('carga.preview', 'carga.confirmar') AND (payload->>'carga_id')::int = %s)"
                    " OR (tipo = 'carga.borrar' AND (payload->>'borrar_carga_id')::int = %s)",
                    (carga_id, carga_id), "Cancelada: se pidió borrar la carga")
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
    cid = payload["borrar_carga_id"]
    _esperar_locks(conn)
    try:
        carga = conn.execute("SELECT * FROM carga WHERE id = %s FOR UPDATE", (cid,)).fetchone()
        if carga is None:
            return {"ya_borrada": True}
        return _borrar_carga(conn, carga, tarea_id)
    except psycopg.errors.LockNotAvailable as e:
        raise _ocupado(f"La carga #{cid}") from e


def _borrar_carga(conn, carga, tarea_id):
    from .cargas import empresas_de_carga

    cid = carga["id"]
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
    actor = tareas_actor(conn, tarea_id)
    n = borrar_empresas(conn, huerfanas, "carga.borrar", actor)
    items_borrados = n.pop("_items_borrados")
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
    # Las tareas canceladas quedan como registro; si Cloud Tasks las entrega tarde, no hacen nada
    x("DELETE FROM tarea WHERE (payload->>'carga_id')::int = %s AND estado <> 'cancelada'", (cid,))
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
    _vincular_auditoria(conn, items_borrados, auditoria.registrar(conn, actor, "carga.borrar", "carga", cid, resumen))
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


# ─────────────────────────────────────────────────────────────
# Muestras y estudios (E1, E2)
# ─────────────────────────────────────────────────────────────

def _conteos_muestras(conn, muestra_ids: list[int]) -> dict:
    r = conn.execute("""
        SELECT count(*) AS items,
               (SELECT count(*) FROM intento t WHERE t.item_id IN (SELECT id FROM muestra_item WHERE muestra_id = ANY(%(m)s))) AS intentos,
               (SELECT count(*) FROM sav_fila f WHERE f.item_id IN (SELECT id FROM muestra_item WHERE muestra_id = ANY(%(m)s))) AS filas_sav
        FROM muestra_item WHERE muestra_id = ANY(%(m)s)""", {"m": muestra_ids}).fetchone()
    return dict(r)


def conteos_muestra(conn, muestra_id: int) -> dict:
    m = conn.execute("SELECT m.id, m.nombre, m.estado, m.semilla, m.estudio_id, e.nombre AS estudio FROM muestra m"
                     " JOIN estudio e ON e.id = m.estudio_id WHERE m.id = %s", (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Muestra inexistente")
    return {**m, **_conteos_muestras(conn, [muestra_id])}


def _borrar_muestras(conn, muestra_ids: list[int]) -> dict:
    """Borra las muestras con sus ítems, intentos del CDR y filas del .sav. No toca empresas,
    historia, vínculos, contactos, teléfonos ni el último contacto efectivo."""
    if not muestra_ids:
        return {"muestras": 0, "items": 0, "intentos": 0, "filas_sav": 0}
    x = conn.execute
    items = _ids(conn, "SELECT id FROM muestra_item WHERE muestra_id = ANY(%s)", (muestra_ids,))
    intentos = _ids(conn, "SELECT id FROM intento WHERE item_id = ANY(%s)", (items,))
    sav = _ids(conn, "SELECT id FROM sav_fila WHERE item_id = ANY(%s)", (items,))
    x("DELETE FROM conciliacion WHERE (tipo = 'sav_fila' AND objeto_id = ANY(%s))"
      " OR (tipo = 'intento' AND objeto_id = ANY(%s))", (sav, intentos))
    x("DELETE FROM sav_fila WHERE id = ANY(%s)", (sav,))
    x("DELETE FROM intento WHERE id = ANY(%s)", (intentos,))
    x("DELETE FROM item_parte_estado WHERE item_id = ANY(%s)", (items,))
    x("DELETE FROM muestra_item_borrado WHERE muestra_id = ANY(%s)", (muestra_ids,))
    x("DELETE FROM muestra_item WHERE id = ANY(%s)", (items,))
    snaps = [r["snapshot_id"] for r in x("DELETE FROM muestra WHERE id = ANY(%s) RETURNING snapshot_id", (muestra_ids,))
             if r["snapshot_id"]]
    # El marco congelado se va con la muestra, si ninguna otra lo usa
    libres = _ids(conn, "SELECT s.id FROM marco_snapshot s WHERE s.id = ANY(%s)"
                        " AND NOT EXISTS (SELECT 1 FROM muestra m WHERE m.snapshot_id = s.id)", (snaps,))
    x("DELETE FROM marco_snapshot_item WHERE snapshot_id = ANY(%s)", (libres,))
    x("DELETE FROM marco_snapshot WHERE id = ANY(%s)", (libres,))
    return {"muestras": len(muestra_ids), "items": len(items), "intentos": len(intentos), "filas_sav": len(sav)}


def pedir_borrado_muestra(conn, muestra_id: int, actor: str) -> int:
    conteos_muestra(conn, muestra_id)  # 404 si no existe
    tareas.cancelar("tipo = 'muestra.borrar' AND (payload->>'borrar_muestra_id')::int = %s", (muestra_id,),
                    "Cancelada: se volvió a pedir el borrado")
    return tareas.crear(conn, "muestra.borrar", {"borrar_muestra_id": muestra_id}, actor)


@tareas.handler("muestra.borrar")
def _tarea_borrar_muestra(conn, payload, tarea_id):
    mid = payload["borrar_muestra_id"]
    _esperar_locks(conn)
    try:
        m = conn.execute("SELECT m.*, e.nombre AS estudio_nombre FROM muestra m JOIN estudio e ON e.id = m.estudio_id"
                         " WHERE m.id = %s FOR UPDATE OF m", (mid,)).fetchone()
        if m is None:
            return {"ya_borrada": True}
        tareas.progreso(tarea_id, 0, 1)
        n = _borrar_muestras(conn, [mid])
    except psycopg.errors.LockNotAvailable as e:
        raise _ocupado(f"La muestra #{mid}") from e
    resumen = {"muestra_id": mid, "nombre": m["nombre"], "estudio_id": m["estudio_id"], "estudio": m["estudio_nombre"],
               "estado": m["estado"], "semilla": m["semilla"], **{k: v for k, v in n.items() if k != "muestras"}}
    auditoria.registrar(conn, tareas_actor(conn, tarea_id), "muestra.borrar", "muestra", mid, resumen)
    tareas.progreso(tarea_id, 1, 1)
    return resumen


def _partes_e_ingestas(conn, estudio_id: int) -> tuple[list[int], list[dict]]:
    partes = _ids(conn, "SELECT id FROM parte WHERE estudio_id = %s", (estudio_id,))
    ingestas = conn.execute("SELECT id, archivo_id FROM sav_ingesta WHERE parte_id = ANY(%s)", (partes,)).fetchall()
    return partes, ingestas


def conteos_estudio(conn, estudio_id: int) -> dict:
    e = conn.execute("SELECT id, nombre FROM estudio WHERE id = %s", (estudio_id,)).fetchone()
    if e is None:
        raise HTTPException(404, "Estudio inexistente")
    muestras = _ids(conn, "SELECT id FROM muestra WHERE estudio_id = %s", (estudio_id,))
    partes, ingestas = _partes_e_ingestas(conn, estudio_id)
    n = _conteos_muestras(conn, muestras)
    filas = conn.execute("SELECT count(*) AS n FROM sav_fila WHERE parte_id = ANY(%s)", (partes,)).fetchone()["n"]
    return {**e, "muestras": len(muestras), "partes": len(partes), "items": n["items"], "intentos": n["intentos"],
            "ingestas_sav": len(ingestas), "filas_sav": filas}


def pedir_borrado_estudio(conn, estudio_id: int, actor: str) -> int:
    conteos_estudio(conn, estudio_id)  # 404 si no existe
    _, ingestas = _partes_e_ingestas(conn, estudio_id)
    tareas.cancelar("(tipo IN ('sav.confirmar', 'sav.remapear') AND (payload->>'ingesta_id')::int = ANY(%s))"
                    " OR (tipo = 'estudio.borrar' AND (payload->>'borrar_estudio_id')::int = %s)",
                    ([i["id"] for i in ingestas], estudio_id), "Cancelada: se pidió borrar el estudio")
    return tareas.crear(conn, "estudio.borrar", {"borrar_estudio_id": estudio_id}, actor)


@tareas.handler("estudio.borrar")
def _tarea_borrar_estudio(conn, payload, tarea_id):
    eid = payload["borrar_estudio_id"]
    _esperar_locks(conn)
    try:
        e = conn.execute("SELECT * FROM estudio WHERE id = %s FOR UPDATE", (eid,)).fetchone()
        if e is None:
            return {"ya_borrado": True}
        resumen, archivos = _borrar_estudio(conn, e, tarea_id)
    except psycopg.errors.LockNotAvailable as ex:
        raise _ocupado(f"El estudio «{eid}»") from ex
    auditoria.registrar(conn, tareas_actor(conn, tarea_id), "estudio.borrar", "estudio", eid, resumen)
    for arch in archivos:
        try:
            storage.borrar(arch)
        except Exception:  # el archivo huérfano en el bucket no rompe el borrado
            log.warning("No se pudo borrar el archivo %s del bucket", arch["ruta"], exc_info=True)
    return resumen


def _borrar_estudio(conn, e, tarea_id) -> tuple[dict, list[dict]]:
    x = conn.execute
    muestras = conn.execute("SELECT id, nombre FROM muestra WHERE estudio_id = %s ORDER BY id", (e["id"],)).fetchall()
    partes, ingestas = _partes_e_ingestas(conn, e["id"])
    tareas.progreso(tarea_id, 0, 3)
    n = _borrar_muestras(conn, [m["id"] for m in muestras])
    tareas.progreso(tarea_id, 1, 3)
    # Las ingestas .sav de sus partes, con las filas que no se habían asociado a ningún ítem
    ing_ids = [i["id"] for i in ingestas]
    sav = _ids(conn, "SELECT id FROM sav_fila WHERE ingesta_id = ANY(%s) OR parte_id = ANY(%s)", (ing_ids, partes))
    x("DELETE FROM conciliacion WHERE tipo = 'sav_fila' AND objeto_id = ANY(%s)", (sav,))
    x("DELETE FROM sav_fila WHERE id = ANY(%s)", (sav,))
    x("DELETE FROM tarea WHERE (payload->>'ingesta_id')::int = ANY(%s) AND estado <> 'cancelada'", (ing_ids,))
    x("DELETE FROM sav_ingesta WHERE id = ANY(%s)", (ing_ids,))
    archivos = x("""SELECT * FROM archivo a WHERE a.id = ANY(%s)
                      AND NOT EXISTS (SELECT 1 FROM carga c WHERE c.archivo_id = a.id)
                      AND NOT EXISTS (SELECT 1 FROM sav_ingesta s WHERE s.archivo_id = a.id)""",
                 ([i["archivo_id"] for i in ingestas],)).fetchall()
    x("DELETE FROM archivo WHERE id = ANY(%s)", ([a["id"] for a in archivos],))
    tareas.progreso(tarea_id, 2, 3)
    x("DELETE FROM item_parte_estado WHERE parte_id = ANY(%s)", (partes,))
    x("DELETE FROM parte WHERE id = ANY(%s)", (partes,))
    x("DELETE FROM estudio WHERE id = %s", (e["id"],))
    tareas.progreso(tarea_id, 3, 3)
    resumen = {"estudio_id": e["id"], "nombre": e["nombre"], "cliente": e.get("cliente"),
               "muestras": [m["nombre"] for m in muestras], "partes": len(partes), "items": n["items"],
               "intentos": n["intentos"], "ingestas_sav": len(ing_ids), "filas_sav": n["filas_sav"] + len(sav),
               "archivos": len(archivos)}
    return resumen, archivos
