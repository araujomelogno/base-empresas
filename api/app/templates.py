"""Templates de sorteo (SPEC_templates_sorteo, R2; D44).

Un template guarda los pasos 1 a 3 del asistente de «Nueva muestra»: filtros (de campo, por atributo,
orígenes, base provisoria y empresas sin teléfono), estratos (con sus tramos y agrupamientos) y tamaños
por estrato. No guarda la semilla, el estudio, el nombre ni las opciones de exportación.

Los templates son copias, no referencias vivas: la muestra guarda su propia copia de los criterios y su
template_id. Editar el template después no cambia las muestras ya creadas ni sorteadas.
"""
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, criterios as crit

CLAVES_PASOS = ("filtros", "campos", "atributos", "origenes", "incluir_provisoria", "incluir_sin_telefono",
                "estratificar_por", "estratos_def", "estratos", "n_por_estrato", "reemplazos_por_estrato",
                "estratos_descartados")


def _solo_pasos(c: dict) -> dict:
    return {k: v for k, v in (c or {}).items() if k in CLAVES_PASOS}


def _validar(conn, criterios: dict) -> dict:
    return crit.validar(conn, _solo_pasos(criterios), tamanos=False)


def _nombre(conn, nombre: str | None, excluir: int | None = None) -> str:
    n = (nombre or "").strip()
    if not n:
        raise HTTPException(422, "Indicá el nombre del template")
    if conn.execute("SELECT 1 FROM muestra_template WHERE lower(nombre) = lower(%s) AND id IS DISTINCT FROM %s",
                    (n, excluir)).fetchone():
        raise HTTPException(409, f"Ya hay un template con el nombre «{n}»")
    return n


def obtener(conn, template_id: int) -> dict:
    t = conn.execute("SELECT * FROM muestra_template WHERE id = %s", (template_id,)).fetchone()
    if t is None:
        raise HTTPException(404, "Template inexistente")
    return t


def resumen(c: dict, defs: dict) -> dict:
    """Resumen legible: filtros, estratos y tamaño total."""
    nombre = lambda k: (defs.get(k) or {}).get("nombre", k)  # noqa: E731
    filtros = [nombre(k) for k in (c.get("filtros") or {})] + [nombre(k) for k in (c.get("campos") or {})]
    filtros += [nombre(crit.PREFIJO + k) for k in (c.get("atributos") or {})]
    if c.get("origenes"):
        filtros.append("origen de los teléfonos")
    if c.get("incluir_provisoria"):
        filtros.append("incluye la base provisoria")
    if c.get("incluir_sin_telefono"):
        filtros.append("incluye empresas sin teléfono")
    if c.get("estratos"):
        total = sum(int(e.get("n", 0)) for e in c["estratos"])
        tamano = f"{total} titulares en {len(c['estratos'])} estratos"
    elif c.get("n_por_estrato") is not None:
        tamano = f"{c['n_por_estrato']} por estrato"
    else:
        tamano = "sin tamaños"
    return {"filtros": filtros, "estratos": [nombre(k) for k in c.get("estratificar_por") or []], "tamano": tamano}


def listar(conn, activos: bool | None = None) -> list[dict]:
    defs = crit.definiciones(conn)
    filas = conn.execute(
        "SELECT t.*, u.id AS ultima_muestra_id, u.nombre AS ultima_muestra, u.estudio_nombre AS ultima_muestra_estudio,"
        " (SELECT count(*) FROM muestra m WHERE m.template_id = t.id) AS n_muestras"
        " FROM muestra_template t LEFT JOIN LATERAL (SELECT m.id, m.nombre, e.nombre AS estudio_nombre FROM muestra m"
        "   JOIN estudio e ON e.id = m.estudio_id WHERE m.template_id = t.id ORDER BY m.id DESC LIMIT 1) u ON true"
        " WHERE (%s::bool IS NULL OR t.activo = %s) ORDER BY t.activo DESC, lower(t.nombre)", (activos, activos)).fetchall()
    for f in filas:
        f["resumen"] = resumen(f["criterios"], defs)
    return filas


def crear(conn, nombre: str, descripcion: str | None, criterios: dict, actor: str) -> dict:
    n = _nombre(conn, nombre)
    c = _validar(conn, criterios)
    t = conn.execute(
        "INSERT INTO muestra_template (nombre, descripcion, criterios, creado_por) VALUES (%s,%s,%s,%s) RETURNING *",
        (n, (descripcion or "").strip() or None, Jsonb(c), actor)).fetchone()
    auditoria.registrar(conn, actor, "muestra_template.crear", "muestra_template", t["id"], {"nombre": n, "criterios": c})
    return t


def editar(conn, template_id: int, datos: dict, actor: str) -> dict:
    t = obtener(conn, template_id)
    cambios = {}
    if "nombre" in datos and datos["nombre"] is not None:
        cambios["nombre"] = _nombre(conn, datos["nombre"], template_id)
    if "descripcion" in datos:
        cambios["descripcion"] = (datos["descripcion"] or "").strip() or None
    if datos.get("criterios") is not None:
        cambios["criterios"] = Jsonb(_validar(conn, datos["criterios"]))
    if datos.get("activo") is not None:
        cambios["activo"] = bool(datos["activo"])
    if not cambios:
        return t
    t = conn.execute(
        f"UPDATE muestra_template SET {', '.join(f'{k} = %s' for k in cambios)}, actualizado_por = %s, actualizado = now()"
        " WHERE id = %s RETURNING *", (*cambios.values(), actor, template_id)).fetchone()
    auditoria.registrar(conn, actor, "muestra_template.editar", "muestra_template", template_id,
                        {k: (v.obj if isinstance(v, Jsonb) else v) for k, v in cambios.items()})
    return t


def duplicar(conn, template_id: int, actor: str) -> dict:
    t = obtener(conn, template_id)
    base, k = f"{t['nombre']} (copia)", 1
    nombre = base
    while conn.execute("SELECT 1 FROM muestra_template WHERE lower(nombre) = lower(%s)", (nombre,)).fetchone():
        k += 1
        nombre = f"{base} {k}"
    return crear(conn, nombre, t["descripcion"], t["criterios"], actor)


def borrar(conn, template_id: int, actor: str) -> dict:
    t = obtener(conn, template_id)
    usado = conn.execute("SELECT count(*) AS n FROM muestra WHERE template_id = %s", (template_id,)).fetchone()["n"]
    if t["veces_usado"] or usado:
        raise HTTPException(409, f"El template «{t['nombre']}» ya se usó en {max(t['veces_usado'], usado)} muestras:"
                                 " desactivalo en lugar de borrarlo")
    conn.execute("DELETE FROM muestra_template WHERE id = %s", (template_id,))
    auditoria.registrar(conn, actor, "muestra_template.borrar", "muestra_template", template_id, {"nombre": t["nombre"]})
    return {"borrado": template_id}


def aplicar(conn, template_id: int) -> dict:
    """Revalida los criterios con las reglas actuales: lo que ya no existe se saca y se avisa, sin bloquear.
    Devuelve también el marco por estrato, para marcar en el paso 3 los estratos del template sin empresas
    y los estratos nuevos del marco."""
    from . import muestras

    t = obtener(conn, template_id)
    avisos: list[str] = []
    prev = muestras.previsualizar_marco(conn, _solo_pasos(t["criterios"]), avisos)
    criterios = prev.pop("criterios")
    en_marco = {e["estrato"] for e in prev["estratos"]}
    del_template = {e["estrato"] for e in criterios.get("estratos") or []}
    return {"template": {k: t[k] for k in ("id", "nombre", "descripcion")}, "criterios": criterios, "avisos": avisos,
            "marco": prev, "estratos_sin_empresas": sorted(del_template - en_marco, key=crit.orden_natural),
            "estratos_nuevos": sorted(en_marco - del_template, key=crit.orden_natural) if del_template else []}


def desde_muestra(conn, muestra_id: int, nombre: str, descripcion: str | None, actor: str) -> dict:
    m = conn.execute("SELECT * FROM muestra WHERE id = %s", (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Muestra inexistente")
    c = _solo_pasos(m["criterios"])
    avisos: list[str] = []
    c = crit.validar(conn, c, avisos, tamanos=False)  # una muestra vieja puede usar algo que ya no existe
    t = crear(conn, nombre, descripcion, c, actor)
    return {**t, "avisos": avisos}
