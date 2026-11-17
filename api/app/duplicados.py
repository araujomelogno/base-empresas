"""Duplicados difusos y grupo económico (SPEC_fase2_enriquecimiento, B4; D47).

Detección (diaria, o a mano): pares de empresas de la base definitiva con RUT distinto que comparten un teléfono
discable (sin intermediarios ni teléfonos con 5 o más RUT), el dominio del sitio (sin dominios genéricos), la
dirección normalizada con el departamento, o una razón social muy similar (≥ 0,9 sin forma societaria).
La bandeja ofrece fusionar (la fusión reversible de siempre), «son grupo económico» (quedan relacionadas sin
fusionarse) o «sin relación» (el par no se vuelve a proponer).
"""
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, config, empresas

ESTADOS = ("pendiente", "fusionado", "grupo", "sin_relacion", "obsoleto")
NOMBRES_CRITERIO = {"telefono": "teléfono", "dominio": "sitio web", "direccion": "dirección", "razon_social": "razón social"}
_DEF = "e.base = 'definitiva' AND e.baja IS NULL"

_PARES = {
    "telefono": f"""
        WITH t AS (
          SELECT d.telefono_id, d.e164 FROM v_vinculo_discable d JOIN empresa e ON e.id = d.empresa_id
          WHERE {_DEF} GROUP BY d.telefono_id, d.e164
          HAVING count(DISTINCT e.id) BETWEEN 2 AND %(max_rut)s - 1)
        SELECT DISTINCT least(a.empresa_id, b.empresa_id) AS a, greatest(a.empresa_id, b.empresa_id) AS b, t.e164 AS evidencia
        FROM t JOIN v_vinculo_discable a ON a.telefono_id = t.telefono_id JOIN v_vinculo_discable b ON b.telefono_id = t.telefono_id
        JOIN empresa ea ON ea.id = a.empresa_id JOIN empresa eb ON eb.id = b.empresa_id
        WHERE a.empresa_id < b.empresa_id AND ea.base = 'definitiva' AND ea.baja IS NULL AND eb.base = 'definitiva'
          AND eb.baja IS NULL""",
    "dominio": f"""
        SELECT a.id AS a, b.id AS b, dominio_web(a.web) AS evidencia
        FROM empresa a JOIN empresa b ON dominio_web(b.web) = dominio_web(a.web) AND a.id < b.id
        WHERE a.web IS NOT NULL AND b.web IS NOT NULL AND a.base = 'definitiva' AND a.baja IS NULL
          AND b.base = 'definitiva' AND b.baja IS NULL AND position('.' in dominio_web(a.web)) > 0
          AND NOT (dominio_web(a.web) = ANY(%(genericos)s))
          AND NOT EXISTS (SELECT 1 FROM unnest(%(genericos)s::text[]) g WHERE dominio_web(a.web) LIKE '%%.' || g)""",
    "direccion": f"""
        WITH d AS (SELECT e.id, e.departamento, norm_txt(regexp_replace(lower(e.direccion), '[^a-z0-9áéíóúüñ ]', ' ', 'g')) AS dir
                   FROM empresa e WHERE {_DEF} AND e.direccion IS NOT NULL AND e.departamento IS NOT NULL)
        SELECT a.id AS a, b.id AS b, a.dir || ' (' || a.departamento || ')' AS evidencia
        FROM d a JOIN d b ON b.dir = a.dir AND b.departamento = a.departamento AND a.id < b.id
        WHERE length(a.dir) >= 8 AND a.dir ~ '[0-9]'""",
    "razon_social": f"""
        SELECT a.id AS a, b.id AS b, razon_sin_sufijo(a.razon_social) || ' ≈ ' || razon_sin_sufijo(b.razon_social) AS evidencia
        FROM empresa a JOIN empresa b ON razon_sin_sufijo(b.razon_social) %% razon_sin_sufijo(a.razon_social) AND a.id < b.id
             AND b.base = 'definitiva' AND b.baja IS NULL
        WHERE a.base = 'definitiva' AND a.baja IS NULL AND length(razon_sin_sufijo(a.razon_social)) >= 4
          AND similarity(razon_sin_sufijo(a.razon_social), razon_sin_sufijo(b.razon_social)) >= 0.9""",
}


def detectar(conn, actor: str = "job:duplicados") -> dict:
    """Busca pares nuevos (o con criterios nuevos) y marca obsoletos los pares con alguna empresa dada de baja."""
    _, cfg = config.vigente(conn)
    args = {"max_rut": 5, "genericos": [g.lower() for g in (cfg.get("dominios_genericos") or config.DOMINIOS_GENERICOS)]}
    conn.execute("SET LOCAL pg_trgm.similarity_threshold = 0.9")
    pares: dict[tuple[int, int], list[dict]] = {}
    for criterio, sql in _PARES.items():
        for r in conn.execute(sql, args):
            lista = pares.setdefault((r["a"], r["b"]), [])
            if not any(x["criterio"] == criterio for x in lista):
                lista.append({"criterio": criterio, "evidencia": r["evidencia"]})
    # Pares de un mismo grupo económico: ya están relacionados
    grupos = {r["id"]: r["g"] for r in conn.execute(
        "SELECT id, grupo_economico_id AS g FROM empresa WHERE grupo_economico_id IS NOT NULL")}
    nuevos = actualizados = 0
    for (a, b), crit in pares.items():
        if grupos.get(a) and grupos.get(a) == grupos.get(b):
            continue
        r = conn.execute(
            "INSERT INTO duplicado_par (empresa_a, empresa_b, criterios) VALUES (%s,%s,%s)"
            " ON CONFLICT (empresa_a, empresa_b) DO UPDATE SET criterios = EXCLUDED.criterios, actualizado = now()"
            " WHERE duplicado_par.estado = 'pendiente' AND duplicado_par.criterios IS DISTINCT FROM EXCLUDED.criterios"
            " RETURNING (xmax = 0) AS insertado", (a, b, Jsonb(crit))).fetchone()
        if r:
            nuevos += int(r["insertado"])
            actualizados += int(not r["insertado"])
    obsoletos = conn.execute(
        "UPDATE duplicado_par p SET estado = 'obsoleto', actualizado = now() WHERE estado = 'pendiente' AND EXISTS"
        " (SELECT 1 FROM empresa e WHERE e.id IN (p.empresa_a, p.empresa_b) AND e.baja IS NOT NULL)").rowcount
    pendientes = conn.execute("SELECT count(*) AS n FROM duplicado_par WHERE estado = 'pendiente'").fetchone()["n"]
    res = {"pares_detectados": len(pares), "nuevos": nuevos, "actualizados": actualizados, "obsoletos": obsoletos,
           "pendientes": pendientes}
    auditoria.registrar(conn, actor, "duplicados.detectar", "duplicado_par", None, res)
    return res


_EMP = ("json_build_object('id', {a}.id, 'codigo', {a}.codigo, 'razon_social', {a}.razon_social, 'fantasia', {a}.fantasia,"
        " 'departamento', {a}.departamento, 'localidad', {a}.localidad, 'direccion', {a}.direccion, 'web', {a}.web,"
        " 'ciiu', {a}.ciiu, 'tamano', {a}.tamano, 'grupo', (SELECT nombre FROM grupo_economico g WHERE g.id = {a}.grupo_economico_id),"
        " 'telefonos', (SELECT count(*) FROM v_vinculo_discable d WHERE d.empresa_id = {a}.id))")


def bandeja(conn, estado: str = "pendiente", pagina: int = 1, por_pagina: int = 50) -> dict:
    if estado not in ESTADOS:
        raise HTTPException(422, f"Estado desconocido: {estado}")
    pagina = max(1, pagina)
    total = conn.execute("SELECT count(*) AS n FROM duplicado_par WHERE estado = %s", (estado,)).fetchone()["n"]
    filas = conn.execute(
        f"SELECT p.id, p.criterios, p.estado, p.detectado, p.resuelto_por, p.resuelto,"
        f" (now() - p.detectado) > interval '14 days' AS vencido,"
        f" {_EMP.format(a='a')} AS a, {_EMP.format(a='b')} AS b"
        f" FROM duplicado_par p JOIN empresa a ON a.id = p.empresa_a JOIN empresa b ON b.id = p.empresa_b"
        f" WHERE p.estado = %s ORDER BY jsonb_array_length(p.criterios) DESC, p.detectado, p.id LIMIT %s OFFSET %s",
        (estado, por_pagina, (pagina - 1) * por_pagina)).fetchall()
    vencidos = conn.execute("SELECT count(*) AS n FROM duplicado_par WHERE estado = 'pendiente'"
                            " AND now() - detectado > interval '14 days'").fetchone()["n"]
    return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "filas": filas, "vencidos": vencidos}


def _par(conn, par_id: int) -> dict:
    p = conn.execute("SELECT * FROM duplicado_par WHERE id = %s FOR UPDATE", (par_id,)).fetchone()
    if p is None:
        raise HTTPException(404, "Par inexistente")
    if p["estado"] != "pendiente":
        raise HTTPException(409, "El par ya se resolvió")
    return p


def resolver(conn, par_id: int, accion: str, actor: str, absorbente: int | None = None, nombre_grupo: str | None = None) -> dict:
    p = _par(conn, par_id)
    a = conn.execute("SELECT * FROM empresa WHERE id = %s", (p["empresa_a"],)).fetchone()
    b = conn.execute("SELECT * FROM empresa WHERE id = %s", (p["empresa_b"],)).fetchone()
    if accion == "fusionar":
        if absorbente not in (a["id"], b["id"]):
            raise HTTPException(422, "Elegí qué empresa queda (la otra se fusiona en ella)")
        queda, se_va = (a, b) if absorbente == a["id"] else (b, a)
        fusion_id = empresas.fusionar(conn, queda, se_va, actor, f"Posible duplicado #{par_id}")
        estado, extra = "fusionado", {"fusion_id": fusion_id, "queda": queda["codigo"], "se_fusiona": se_va["codigo"]}
    elif accion == "grupo":
        extra = {"grupo_id": relacionar(conn, [a, b], actor, nombre_grupo)}
        estado = "grupo"
    elif accion == "sin_relacion":
        estado, extra = "sin_relacion", {}
    else:
        raise HTTPException(422, "Acción: fusionar, grupo o sin_relacion")
    conn.execute("UPDATE duplicado_par SET estado = %s, resuelto_por = %s, resuelto = now(), actualizado = now() WHERE id = %s",
                 (estado, actor, par_id))
    auditoria.registrar(conn, actor, f"duplicado.{accion}", "duplicado_par", par_id,
                        {"empresas": [a["codigo"], b["codigo"]], "criterios": [c["criterio"] for c in p["criterios"]], **extra})
    return {"par_id": par_id, "estado": estado, **extra}


def relacionar(conn, emps: list[dict], actor: str, nombre: str | None = None) -> int:
    """Pone las empresas en el mismo grupo económico. Si alguna ya está en un grupo, las demás se suman a ese."""
    existentes = [e["grupo_economico_id"] for e in emps if e["grupo_economico_id"]]
    if existentes:
        gid = existentes[0]
        # Si estaban en dos grupos distintos, se juntan en el primero
        otros = sorted(set(existentes) - {gid})
        if otros:
            conn.execute("UPDATE empresa SET grupo_economico_id = %s WHERE grupo_economico_id = ANY(%s)", (gid, otros))
            conn.execute("DELETE FROM grupo_economico WHERE id = ANY(%s)", (otros,))
        if nombre and nombre.strip():
            conn.execute("UPDATE grupo_economico SET nombre = %s WHERE id = %s", (nombre.strip(), gid))
    else:
        gid = conn.execute("INSERT INTO grupo_economico (nombre, creado_por) VALUES (%s, %s) RETURNING id",
                           ((nombre or "").strip() or f"Grupo {emps[0]['razon_social'] or emps[0]['codigo']}", actor)
                           ).fetchone()["id"]
    conn.execute("UPDATE empresa SET grupo_economico_id = %s, actualizado = now() WHERE id = ANY(%s)",
                 (gid, [e["id"] for e in emps]))
    return gid


# ─────────────────────────────────────────────────────────────
# Grupos económicos
# ─────────────────────────────────────────────────────────────

def grupo(conn, grupo_id: int) -> dict:
    g = conn.execute("SELECT * FROM grupo_economico WHERE id = %s", (grupo_id,)).fetchone()
    if g is None:
        raise HTTPException(404, "Grupo inexistente")
    g = dict(g)
    g["empresas"] = conn.execute("SELECT id, codigo, razon_social, departamento FROM empresa WHERE grupo_economico_id = %s"
                                 " AND baja IS NULL ORDER BY razon_social", (grupo_id,)).fetchall()
    return g


def renombrar(conn, grupo_id: int, nombre: str, actor: str) -> dict:
    if not nombre or not nombre.strip():
        raise HTTPException(422, "El nombre está vacío")
    r = conn.execute("UPDATE grupo_economico SET nombre = %s WHERE id = %s RETURNING id", (nombre.strip(), grupo_id)).fetchone()
    if r is None:
        raise HTTPException(404, "Grupo inexistente")
    auditoria.registrar(conn, actor, "grupo.renombrar", "grupo_economico", grupo_id, {"nombre": nombre.strip()})
    return grupo(conn, grupo_id)


def quitar(conn, empresa_id: int, actor: str) -> dict:
    """Saca una empresa de su grupo (si el grupo queda con una sola, se disuelve)."""
    e = conn.execute("SELECT * FROM empresa WHERE id = %s", (empresa_id,)).fetchone()
    if e is None or not e["grupo_economico_id"]:
        raise HTTPException(409, "La empresa no está en un grupo económico")
    gid = e["grupo_economico_id"]
    conn.execute("UPDATE empresa SET grupo_economico_id = NULL WHERE id = %s", (empresa_id,))
    quedan = conn.execute("SELECT id FROM empresa WHERE grupo_economico_id = %s", (gid,)).fetchall()
    if len(quedan) <= 1:
        conn.execute("UPDATE empresa SET grupo_economico_id = NULL WHERE grupo_economico_id = %s", (gid,))
        conn.execute("DELETE FROM grupo_economico WHERE id = %s", (gid,))
    auditoria.registrar(conn, actor, "grupo.quitar", "empresa", e["codigo"], {"grupo_id": gid})
    return {"quitada": e["codigo"], "grupo_disuelto": len(quedan) <= 1}
