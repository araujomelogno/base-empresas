"""CSV para uContact (R1.7).

Un renglón por teléfono discable de cada ítem liberado. Nunca incluye teléfonos
intermediarios (sospechosos o confirmados), inexistentes, que no corresponden o en no
llamar, ni empresas excluidas por naturaleza, en no llamar, cerradas o dadas de baja: esas
reglas se vuelven a evaluar al exportar aunque la muestra ya las haya aplicado al sortear.
"""
import csv
import io
from urllib.parse import urlencode, urlsplit

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, config, telefonos as telmod
from .auth import Usuario

ESTADOS_EXPORTABLES = ("pendiente", "en_curso")


def link_alchemer(link_base: str | None, id_item: int, rut: str, e164: str) -> str:
    if not link_base:
        return ""
    params = urlencode({"EC_ID_ITEM": id_item, "EC_RUT": rut, "EC_TEL_USADO": e164.lstrip("+")})
    sep = "&" if urlsplit(link_base).query else ("" if link_base.endswith("?") else "?")
    return f"{link_base}{sep}{params}"


def filas_csv(conn, muestra_id: int, parte_id: int, con_contactos: bool) -> tuple[list[dict], dict]:
    m = conn.execute("SELECT * FROM muestra WHERE id = %s", (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Muestra inexistente")
    if m["estado"] != "activa":
        raise HTTPException(409, "Solo se exporta una muestra activa")
    p = conn.execute("SELECT * FROM parte WHERE id = %s AND estudio_id = %s", (parte_id, m["estudio_id"])).fetchone()
    if p is None:
        raise HTTPException(404, "La parte no pertenece al estudio de la muestra")
    _, cfg = config.vigente(conn)
    rows = conn.execute(
        """
        WITH excluidas AS (
          SELECT empresa_id, regla FROM bloqueos(%(cfg)s)
          WHERE regla IN ('naturaleza_excluida','no_llamar','baja','cerrada')
        )
        SELECT i.id AS id_item, i.estrato, e.id AS empresa_id, e.rut, e.razon_social, e.fantasia, e.departamento,
               e.localidad, d.e164, d.estado AS estado_vinculo, d.contacto_id
        FROM muestra_item i
        JOIN empresa e ON e.id = i.empresa_id
        LEFT JOIN item_parte_estado ps ON ps.item_id = i.id AND ps.parte_id = %(parte)s
        JOIN v_vinculo_discable d ON d.empresa_id = e.id
        WHERE i.muestra_id = %(muestra)s AND i.liberado
          AND coalesce(ps.estado, 'pendiente') = ANY(%(estados)s)
          AND NOT EXISTS (SELECT 1 FROM excluidas x WHERE x.empresa_id = e.id)
        ORDER BY i.estrato, i.orden, (d.estado = 'verificado') DESC, d.e164
        """,
        {"cfg": Jsonb(cfg), "parte": parte_id, "muestra": muestra_id, "estados": list(ESTADOS_EXPORTABLES)},
    ).fetchall()
    contactos = _contactos_sugeridos(conn, {r["empresa_id"] for r in rows}, p["respondente_objetivo"]) if con_contactos else {}
    salida = []
    for r in rows:
        c = contactos.get(r["empresa_id"]) or {}
        salida.append({
            "id_item": r["id_item"], "tel_e164": r["e164"], "tel_nacional": telmod.nacional(r["e164"]),
            "tel_sin_mas": r["e164"].lstrip("+"), "rut": r["rut"], "razon_social": r["razon_social"] or "",
            "fantasia": r["fantasia"] or "", "contacto": c.get("nombre", ""), "contacto_cargo": c.get("cargo", ""),
            "departamento": r["departamento"] or "", "localidad": r["localidad"] or "", "estrato": r["estrato"],
            "link": link_alchemer(p["link_base"], r["id_item"], r["rut"], r["e164"]), "parte": p["nombre"],
            "muestra": m["nombre"],
        })
    # Ítems que deberían ir a campo en esta parte (liberados y pendientes o en curso) sin ningún teléfono discable
    exportables = conn.execute(
        """
        SELECT count(*) AS n, count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM v_vinculo_discable d WHERE d.empresa_id = i.empresa_id)) AS sin_tel
        FROM muestra_item i LEFT JOIN item_parte_estado ps ON ps.item_id = i.id AND ps.parte_id = %s
        WHERE i.muestra_id = %s AND i.liberado AND coalesce(ps.estado, 'pendiente') = ANY(%s)
        """, (parte_id, muestra_id, list(ESTADOS_EXPORTABLES))).fetchone()
    resumen = {"renglones": len(salida), "items": len({s["id_item"] for s in salida}),
               "items_pendientes": exportables["n"], "items_sin_telefono": exportables["sin_tel"],
               "con_contactos": con_contactos}
    return salida, {"cfg": cfg, "parte": p, "muestra": m, "resumen": resumen}


def _contactos_sugeridos(conn, empresa_ids: set[int], objetivo: str | None) -> dict:
    """Contacto que coincide con el respondente objetivo de la parte (área o cargo) o el más reciente."""
    if not empresa_ids:
        return {}
    filas = conn.execute(
        """
        SELECT DISTINCT ON (c.empresa_id) c.empresa_id, c.nombre, c.cargo, c.area
        FROM contacto c
        WHERE c.empresa_id = ANY(%s)
          AND NOT EXISTS (SELECT 1 FROM no_llamar n WHERE n.activo AND n.alcance = 'contacto' AND n.objeto_id = c.id)
        ORDER BY c.empresa_id,
                 (%s::text IS NOT NULL AND (c.area ILIKE '%%' || %s || '%%' OR c.cargo ILIKE '%%' || %s || '%%')) DESC,
                 c.actualizado DESC
        """, (list(empresa_ids), objetivo, objetivo, objetivo)).fetchall()
    return {f["empresa_id"]: f for f in filas}


def generar_csv(conn, muestra_id: int, parte_id: int, usuario: Usuario) -> tuple[str, str, dict]:
    con_contactos = usuario.exportar_contactos
    filas, ctx = filas_csv(conn, muestra_id, parte_id, con_contactos)
    formato = ctx["cfg"]["csv_ucontact"]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=formato.get("separador", ";"), lineterminator="\r\n")
    w.writerow([c["columna"] for c in formato["columnas"]])
    for f in filas:
        w.writerow([f.get(c["campo"], "") for c in formato["columnas"]])
    nombre = f"ucontact_muestra{muestra_id}_parte{parte_id}.csv"
    auditoria.registrar(conn, usuario.email, "muestra.exportar_csv", "muestra", muestra_id,
                        {"parte_id": parte_id, **ctx["resumen"]})
    return nombre, buf.getvalue(), ctx["resumen"]
