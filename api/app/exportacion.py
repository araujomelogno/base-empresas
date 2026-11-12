"""CSV para uContact (R1.7) y planilla de la muestra (F5.1).

Formatos:
- «ucontact»: un renglón por teléfono, con las columnas configuradas más las elegidas en «Qué incluir»
  (atributos de empresa atr_<clave>; contactos en contacto_1_*, contacto_2_*… hasta
  contactos_por_empresa_csv, solo para quien tiene el permiso de exportar contactos).
- «planilla»: un renglón por empresa, con los teléfonos en tel_1…tel_n y sus orígenes.

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

from . import auditoria, catalogos, config, contactos as contmod, muestras, telefonos as telmod
from .auth import Usuario

ESTADOS_EXPORTABLES = ("pendiente", "en_curso")


def link_alchemer(link_base: str | None, id_item: int, rut: str, e164: str) -> str:
    if not link_base:
        return ""
    params = urlencode({"EC_ID_ITEM": id_item, "EC_RUT": rut, "EC_TEL_USADO": e164.lstrip("+")})
    sep = "&" if urlsplit(link_base).query else ("" if link_base.endswith("?") else "?")
    return f"{link_base}{sep}{params}"


FORMATOS = ("ucontact", "planilla")


def filas_csv(conn, muestra_id: int, parte_id: int, con_contactos: bool, formato: str = "ucontact") -> tuple[list[dict], dict]:
    m = conn.execute("SELECT * FROM muestra WHERE id = %s", (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Muestra inexistente")
    if m["estado"] != "activa":
        raise HTTPException(409, "Solo se exporta una muestra activa")
    p = conn.execute("SELECT * FROM parte WHERE id = %s AND estudio_id = %s", (parte_id, m["estudio_id"])).fetchone()
    if p is None:
        raise HTTPException(404, "La parte no pertenece al estudio de la muestra")
    _, cfg = config.vigente(conn)
    opciones = muestras.opciones_exportacion(m)
    origenes = opciones["origenes"] or None
    orden_tel = ("coalesce(og.prioridad, 1000), (d.estado = 'verificado') DESC, d.e164" if opciones["orden"] == "prioridad"
                 else "(d.estado = 'verificado') DESC, d.e164")
    rows = conn.execute(
        """
        WITH excluidas AS (
          SELECT empresa_id, regla FROM bloqueos(%(cfg)s)
          WHERE regla IN ('naturaleza_excluida','no_llamar','baja','cerrada')
        )
        SELECT i.id AS id_item, i.estrato, e.id AS empresa_id, e.rut, e.codigo, e.razon_social, e.fantasia, e.departamento,
               e.localidad, d.e164, d.estado AS estado_vinculo, d.contacto_id, og.origen_nombre, og.prioridad
        FROM muestra_item i
        JOIN empresa e ON e.id = i.empresa_id
        LEFT JOIN item_parte_estado ps ON ps.item_id = i.id AND ps.parte_id = %(parte)s
        JOIN v_vinculo_discable d ON d.empresa_id = e.id
        LEFT JOIN LATERAL (
          -- un teléfono con varios orígenes ordena por el de mayor prioridad y pasa el filtro con cualquiera
          SELECT min(o.prioridad) AS prioridad, (array_agg(o.nombre ORDER BY o.prioridad, o.id))[1] AS origen_nombre,
                 array_agg(o.codigo) AS codigos
          FROM telefono_vinculo_origen x JOIN origen_telefono o ON o.id = x.origen_id WHERE x.vinculo_id = d.vinculo_id
        ) og ON true
        WHERE i.muestra_id = %(muestra)s AND i.liberado
          AND coalesce(ps.estado, 'pendiente') = ANY(%(estados)s)
          AND NOT EXISTS (SELECT 1 FROM excluidas x WHERE x.empresa_id = e.id)
          AND (%(origenes)s::text[] IS NULL OR og.codigos && %(origenes)s::text[])
          AND (NOT %(solo_ver)s OR d.estado = 'verificado')
        ORDER BY i.estrato, i.orden, """ + orden_tel,
        {"cfg": Jsonb(cfg), "parte": parte_id, "muestra": muestra_id, "estados": list(ESTADOS_EXPORTABLES),
         "origenes": origenes, "solo_ver": opciones["numeros"] == "verificados"},
    ).fetchall()
    contactos = _contactos_sugeridos(conn, {r["empresa_id"] for r in rows}, p["respondente_objetivo"]) if con_contactos else {}
    ids = {r["empresa_id"] for r in rows}
    if formato == "planilla":  # una fila por empresa: también las que no tienen teléfono exportable
        ids |= {r["empresa_id"] for r in _items_planilla(conn, muestra_id, parte_id, cfg)}
    extra, columnas_extra = _incluir(conn, ids, opciones, cfg, p["respondente_objetivo"], con_contactos)
    salida = []
    for r in rows:
        c = contactos.get(r["empresa_id"]) or {}
        salida.append({**extra.get(r["empresa_id"], {}), "EC_ID_EMPRESA": r["codigo"],
            "id_item": r["id_item"], "tel_e164": r["e164"], "tel_nacional": telmod.nacional(r["e164"]),
            "tel_sin_mas": r["e164"].lstrip("+"), "rut": r["rut"] or "", "razon_social": r["razon_social"] or "",
            "fantasia": r["fantasia"] or "", "contacto": c.get("nombre", ""), "contacto_cargo": c.get("cargo", ""),
            "departamento": r["departamento"] or "", "localidad": r["localidad"] or "", "estrato": r["estrato"],
            "link": link_alchemer(p["link_base"], r["id_item"], r["rut"] or "", r["e164"]), "parte": p["nombre"],
            "muestra": m["nombre"], "origen_telefono": r["origen_nombre"] or "",
        })
    # Ítems que deberían ir a campo en esta parte (liberados y pendientes o en curso) sin ningún teléfono discable
    exportables = conn.execute(
        """
        SELECT count(*) AS n,
               count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM v_vinculo_discable d WHERE d.empresa_id = i.empresa_id)) AS sin_tel,
               count(*) FILTER (WHERE %(origenes)s::text[] IS NOT NULL
                 AND EXISTS (SELECT 1 FROM v_vinculo_discable d WHERE d.empresa_id = i.empresa_id)
                 AND NOT EXISTS (SELECT 1 FROM v_vinculo_discable d JOIN telefono_vinculo_origen x ON x.vinculo_id = d.vinculo_id
                                 JOIN origen_telefono o ON o.id = x.origen_id
                                 WHERE d.empresa_id = i.empresa_id AND o.codigo = ANY(%(origenes)s::text[]))) AS sin_tel_origen
        FROM muestra_item i LEFT JOIN item_parte_estado ps ON ps.item_id = i.id AND ps.parte_id = %(parte)s
        WHERE i.muestra_id = %(muestra)s AND i.liberado AND coalesce(ps.estado, 'pendiente') = ANY(%(estados)s)
        """, {"parte": parte_id, "muestra": muestra_id, "estados": list(ESTADOS_EXPORTABLES), "origenes": origenes}).fetchone()
    resumen = {"renglones": len(salida), "items": len({s["id_item"] for s in salida}),
               "items_pendientes": exportables["n"], "items_sin_telefono": exportables["sin_tel"],
               "items_sin_telefono_por_origen": exportables["sin_tel_origen"], "exportacion": opciones,
               "con_contactos": con_contactos and opciones["contactos"], "columnas_extra": columnas_extra}
    ctx = {"cfg": cfg, "parte": p, "muestra": m, "resumen": resumen, "columnas_extra": columnas_extra}
    if formato == "planilla":
        salida, columnas = _planilla(conn, muestra_id, parte_id, cfg, salida, extra, columnas_extra, p, m)
        ctx["columnas_planilla"] = columnas
        resumen.update(renglones=len(salida), items=len(salida))
    return salida, ctx


def _incluir(conn, empresa_ids: set[int], opciones: dict, cfg: dict, objetivo, con_contactos: bool) -> tuple[dict, list[str]]:
    """Columnas elegidas en «Qué incluir» (F5.1): atributos de empresa y, con permiso, contactos numerados."""
    extra: dict[int, dict] = {eid: {} for eid in empresa_ids}
    atrs = [a for a in catalogos.atributos(conn, True, "empresa") if a["clave"] not in opciones["atributos_excluidos"]]
    # F6.1: EC_ID_EMPRESA = RUT en la definitiva, código P- en la provisoria (EC_RUT va vacío)
    columnas = ["EC_ID_EMPRESA"] + [f"atr_{a['clave']}" for a in atrs]
    if empresa_ids and atrs:
        for r in conn.execute(
                "SELECT ea.empresa_id, a.clave, coalesce(ea.valor_texto, ea.valor_crudo) AS v FROM empresa_atributo ea"
                " JOIN atributo a ON a.id = ea.atributo_id WHERE ea.empresa_id = ANY(%s) AND a.id = ANY(%s)",
                (list(empresa_ids), [a["id"] for a in atrs])):
            extra[r["empresa_id"]][f"atr_{r['clave']}"] = r["v"] or ""
    if not (con_contactos and opciones["contactos"]):
        return extra, columnas
    n = int(cfg.get("contactos_por_empresa_csv", 3))
    campos = opciones["contacto_campos"]
    atrs_c = [a for a in catalogos.atributos(conn, True, "contacto") if a["clave"] not in opciones["atributos_contacto_excluidos"]]
    for k in range(1, n + 1):
        columnas += [f"contacto_{k}_{c}" for c in campos] + [f"contacto_{k}_atr_{a['clave']}" for a in atrs_c]
    if not empresa_ids or n == 0:
        return extra, columnas
    filas = conn.execute(
        """
        SELECT c.* FROM contacto c
        WHERE c.empresa_id = ANY(%s)
          AND NOT EXISTS (SELECT 1 FROM no_llamar n WHERE n.activo AND n.alcance = 'contacto' AND n.objeto_id = c.id)
        ORDER BY c.empresa_id,
                 (%s::text IS NOT NULL AND (c.area ILIKE '%%' || %s || '%%' OR c.cargo ILIKE '%%' || %s || '%%')) DESC,
                 c.actualizado DESC, c.id
        """, (list(empresa_ids), objetivo, objetivo, objetivo)).fetchall()
    por_empresa: dict[int, list] = {}
    for c in filas:
        if len(por_empresa.setdefault(c["empresa_id"], [])) < n:
            por_empresa[c["empresa_id"]].append(c)
    elegidos = [c["id"] for cs in por_empresa.values() for c in cs]
    tels = contmod.telefonos(conn, elegidos) if "telefonos" in campos else {}
    vals = catalogos.atributos_de_contactos(conn, elegidos) if atrs_c else {}
    for eid, cs in por_empresa.items():
        for k, c in enumerate(cs, 1):
            d = extra.setdefault(eid, {})
            for campo in campos:
                if campo == "telefonos":
                    d[f"contacto_{k}_telefonos"] = " / ".join(dict.fromkeys(
                        telmod.nacional(t["e164"]) or t["crudo"] for t in tels.get(c["id"], [])))
                else:
                    d[f"contacto_{k}_{campo}"] = c[campo] or ""
            for v in vals.get(c["id"], []):
                if any(a["clave"] == v["clave"] for a in atrs_c):
                    d[f"contacto_{k}_atr_{v['clave']}"] = v["valor_texto"] or v["crudo"] or ""
    return extra, columnas


def _items_planilla(conn, muestra_id: int, parte_id: int, cfg: dict) -> list[dict]:
    return conn.execute(
        """
        SELECT i.id AS id_item, i.estrato, i.rol, e.id AS empresa_id, e.rut, e.codigo, e.razon_social, e.fantasia, e.departamento,
               e.localidad, coalesce(ps.estado, 'pendiente') AS estado_parte
        FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id
        LEFT JOIN item_parte_estado ps ON ps.item_id = i.id AND ps.parte_id = %(parte)s
        WHERE i.muestra_id = %(muestra)s AND i.liberado AND coalesce(ps.estado, 'pendiente') = ANY(%(estados)s)
          AND NOT EXISTS (SELECT 1 FROM bloqueos(%(cfg)s) b WHERE b.empresa_id = e.id
                          AND b.regla IN ('naturaleza_excluida','no_llamar','baja','cerrada'))
        ORDER BY i.estrato, i.orden
        """, {"muestra": muestra_id, "parte": parte_id, "estados": list(ESTADOS_EXPORTABLES), "cfg": Jsonb(cfg)}).fetchall()


def _planilla(conn, muestra_id, parte_id, cfg, renglones, extra, columnas_extra, p, m) -> tuple[list[dict], list[str]]:
    """«Planilla de la muestra»: un renglón por empresa, con sus teléfonos exportables en tel_1…tel_n."""
    por_item: dict[int, list] = {}
    for r in renglones:
        por_item.setdefault(r["id_item"], []).append(r)
    n = max((len(v) for v in por_item.values()), default=0)
    filas = []
    for it in _items_planilla(conn, muestra_id, parte_id, cfg):
        tels = por_item.get(it["id_item"], [])
        f = {"id_item": it["id_item"], "rut": it["rut"] or "", "razon_social": it["razon_social"] or "",
             "fantasia": it["fantasia"] or "", "departamento": it["departamento"] or "", "localidad": it["localidad"] or "",
             "estrato": it["estrato"], "rol": it["rol"], "estado_parte": it["estado_parte"], "parte": p["nombre"],
             "muestra": m["nombre"], "link": tels[0]["link"] if tels else link_alchemer(p["link_base"], it["id_item"], it["rut"] or "", ""),
             **extra.get(it["empresa_id"], {}), "EC_ID_EMPRESA": it["codigo"]}
        for k, t in enumerate(tels, 1):
            f[f"tel_{k}"] = t["tel_nacional"]
            f[f"tel_{k}_origen"] = t["origen_telefono"]
        filas.append(f)
    columnas = ["id_item", "rut", "razon_social", "fantasia", "departamento", "localidad", "estrato", "rol", "estado_parte",
                "parte", "muestra", "link"]
    for k in range(1, n + 1):
        columnas += [f"tel_{k}", f"tel_{k}_origen"]
    return filas, columnas + columnas_extra


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


def generar_csv(conn, muestra_id: int, parte_id: int, usuario: Usuario, formato: str = "ucontact") -> tuple[str, str, dict]:
    if formato not in FORMATOS:
        raise HTTPException(422, "formato: ucontact | planilla")
    con_contactos = usuario.exportar_contactos  # sin el permiso, los contactos no salen aunque estén elegidos
    filas, ctx = filas_csv(conn, muestra_id, parte_id, con_contactos, formato)
    fmt = ctx["cfg"]["csv_ucontact"]
    if formato == "planilla":
        columnas = [(c, c) for c in ctx["columnas_planilla"]]
        nombre = f"planilla_muestra{muestra_id}_parte{parte_id}.csv"
    else:
        columnas = [(c["columna"], c["campo"]) for c in fmt["columnas"]] + [(c, c) for c in ctx["columnas_extra"]]
        nombre = f"ucontact_muestra{muestra_id}_parte{parte_id}.csv"
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=fmt.get("separador", ";"), lineterminator="\r\n")
    w.writerow([c for c, _ in columnas])
    for f in filas:
        w.writerow([f.get(campo, "") for _, campo in columnas])
    # Auditoría: qué columnas salieron (F5.1), sin datos personales
    auditoria.registrar(conn, usuario.email, "muestra.exportar_csv", "muestra", muestra_id,
                        {"parte_id": parte_id, "formato": formato, **{k: v for k, v in ctx["resumen"].items() if k != "columnas_extra"},
                         "columnas": [c for c, _ in columnas]})
    return nombre, buf.getvalue(), ctx["resumen"]
