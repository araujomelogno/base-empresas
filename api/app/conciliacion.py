"""Bandeja de conciliación: filas del .sav y llamadas que no se asociaron solas (R1.8, R1.9)."""
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, config, resultados, sav


def listar(conn, tipo: str | None = None, estado: str = "pendiente") -> list[dict]:
    filas = conn.execute(
        "SELECT * FROM conciliacion WHERE estado = %s AND (%s::text IS NULL OR tipo = %s) ORDER BY id DESC LIMIT 500",
        (estado, tipo, tipo)).fetchall()
    for f in filas:
        if f["tipo"] == "intento":
            f["objeto"] = conn.execute(
                "SELECT i.id, i.cdr_id, i.inicio, i.encuestador, i.disposicion, t.e164 FROM intento i"
                " JOIN telefono t ON t.id = i.telefono_id WHERE i.id = %s", (f["objeto_id"],)).fetchone()
        else:
            f["objeto"] = conn.execute(
                "SELECT s.id, s.response_id, s.ingesta_id, p.nombre AS parte, p.estudio_id, s.valores FROM sav_fila s"
                " JOIN parte p ON p.id = s.parte_id WHERE s.id = %s", (f["objeto_id"],)).fetchone()
        ids = (f["candidatos"] or {}).get("items") or []
        f["candidatos_detalle"] = conn.execute(
            "SELECT i.id, i.estrato, m.nombre AS muestra, e.rut, e.razon_social FROM muestra_item i"
            " JOIN muestra m ON m.id = i.muestra_id JOIN empresa e ON e.id = i.empresa_id WHERE i.id = ANY(%s)",
            (ids,)).fetchall() if ids else []
    return filas


def resolver(conn, conciliacion_id: int, accion: str, item_id: int | None, actor: str) -> dict:
    c = conn.execute("SELECT * FROM conciliacion WHERE id = %s FOR UPDATE", (conciliacion_id,)).fetchone()
    if c is None:
        raise HTTPException(404, "Ítem de conciliación inexistente")
    if c["estado"] != "pendiente":
        raise HTTPException(409, "Ya fue resuelto")
    if accion == "descartar":
        conn.execute("UPDATE conciliacion SET estado = 'descartada', resuelto_por = %s, resuelto = now() WHERE id = %s",
                     (actor, conciliacion_id))
        auditoria.registrar(conn, actor, "conciliacion.descartar", "conciliacion", conciliacion_id)
        return {"id": conciliacion_id, "estado": "descartada"}
    if accion != "asociar" or not item_id:
        raise HTTPException(422, "accion: asociar (con item_id) o descartar")
    item = conn.execute("SELECT * FROM muestra_item WHERE id = %s", (item_id,)).fetchone()
    if item is None:
        raise HTTPException(404, "Ítem de muestra inexistente")
    aplicado = {}
    if c["tipo"] == "intento":
        conn.execute("UPDATE intento SET item_id = %s WHERE id = %s", (item_id, c["objeto_id"]))
    else:
        fila = conn.execute("SELECT * FROM sav_fila WHERE id = %s", (c["objeto_id"],)).fetchone()
        ing = conn.execute("SELECT * FROM sav_ingesta WHERE id = %s", (fila["ingesta_id"],)).fetchone()
        parte = conn.execute("SELECT * FROM parte WHERE id = %s", (fila["parte_id"],)).fetchone()
        estudio_item = conn.execute("SELECT m.estudio_id FROM muestra m WHERE m.id = %s",
                                    (item["muestra_id"],)).fetchone()["estudio_id"]
        if estudio_item != parte["estudio_id"]:
            raise HTTPException(422, "El ítem no pertenece al estudio de la parte")
        _, cfg = config.vigente(conn)
        v, _ = sav.valores_mapeados(fila["valores"], ing["mapeo"])
        fecha = sav._fecha(v.get("fecha"), ing["fecha"])
        linaje = {"estudio_id": parte["estudio_id"], "parte_id": parte["id"], "ingesta_id": ing["id"],
                  "response_id": fila["response_id"], "encuestador": v.get("encuestador"), "fecha": fecha,
                  "conciliado_por": actor}
        aplicado = resultados.aplicar(conn, item, parte, v, linaje, cfg, actor)
        conn.execute("UPDATE sav_fila SET item_id = %s, aplicado = %s, motivo = NULL, actualizado = now() WHERE id = %s",
                     (item_id, Jsonb(aplicado), fila["id"]))
    conn.execute("UPDATE conciliacion SET estado = 'resuelta', resolucion = %s, resuelto_por = %s, resuelto = now()"
                 " WHERE id = %s", (Jsonb({"item_id": item_id}), actor, conciliacion_id))
    auditoria.registrar(conn, actor, "conciliacion.asociar", "conciliacion", conciliacion_id,
                        {"tipo": c["tipo"], "item_id": item_id, "aplicado": aplicado})
    return {"id": conciliacion_id, "estado": "resuelta", "aplicado": aplicado}
