"""Tablero de calidad de la base por dimensión DMBOK (SPEC_fase2_enriquecimiento, A1; D48).

Cada indicador se calcula sobre la base definitiva (salvo «Base provisoria»), tiene una meta y un estado
(cumple · cerca · no_cumple · informativo) y abre la lista de lo que lo incumple, que es la lista de trabajo
del data steward. Un job diario (POST /api/jobs/calidad) guarda una foto en calidad_medicion para la evolución.
"""
import datetime as dt

from fastapi import HTTPException

from . import auditoria, config, provisorias, rut as rutmod

# Base de cada regla: empresas de la base definitiva, activas (no fusionadas ni anuladas)
DEFINITIVA = "e.base = 'definitiva' AND e.baja IS NULL"

# Naturaleza que sugiere la razón social (consistencia). El orden importa: SAS antes que SA.
_NATURALEZA_SUGERIDA = r"""
CASE
  WHEN lower(e.razon_social) ~ '\ms\.?\s?a\.?\s?s\.?(\s|$|[^a-z0-9])' THEN 'SAS'
  WHEN lower(e.razon_social) ~ '(\ms\.?\s?r\.?\s?l\.?(\s|$|[^a-z0-9]))|(\mltda\.?(\s|$))|responsabilidad limitada' THEN 'SRL'
  WHEN lower(e.razon_social) ~ '(\ms\.?\s?a\.?(\s|$|[^a-z0-9]))|sociedad an[oó]nima' THEN 'SA'
  WHEN lower(e.razon_social) ~ '\mcooperativa' THEN 'COOP'
  WHEN lower(e.razon_social) ~ '\mfundaci[oó]n' THEN 'FUND'
  WHEN lower(e.razon_social) ~ 'asociaci[oó]n civil' THEN 'AC'
END"""

_ALERTAS_SQL = f"""
SELECT e.id, e.codigo, e.razon_social, n.codigo AS naturaleza, x.sugerida,
       n.codigo || '|' || e.razon_social AS firma
FROM empresa e JOIN naturaleza_juridica n ON n.id = e.naturaleza_id
CROSS JOIN LATERAL (SELECT {_NATURALEZA_SUGERIDA} AS sugerida) x
WHERE {DEFINITIVA} AND x.sugerida IS NOT NULL AND x.sugerida <> n.codigo
"""
_ALERTAS_PENDIENTES = (_ALERTAS_SQL + " AND NOT EXISTS (SELECT 1 FROM calidad_alerta_revisada r WHERE r.empresa_id = e.id"
                       " AND r.regla = 'naturaleza' AND r.firma = n.codigo || '|' || e.razon_social)")

# Empresas «disponibles» para la completitud: activas, que se pueden llamar y de naturaleza no excluida
# (no se usa la regla «sin teléfono discable», que es justamente lo que se mide)
_DISPONIBLES = f"""
{DEFINITIVA} AND e.estado <> 'cerrada'
AND NOT EXISTS (SELECT 1 FROM no_llamar nl WHERE nl.activo AND nl.alcance = 'empresa' AND nl.objeto_id = e.id)
AND (e.naturaleza_id IS NULL OR e.naturaleza_id NOT IN (SELECT id FROM naturaleza_juridica WHERE codigo = ANY(%(excluidas)s)))
"""
_DISCABLES_DEF = ("FROM v_vinculo_discable d JOIN empresa e ON e.id = d.empresa_id"
                  " JOIN telefono_vinculo v ON v.id = d.vinculo_id WHERE " + DEFINITIVA)

DIMENSIONES = [
    ("validez", "Validez", "RUT con dígito verificador correcto y teléfonos en E.164 válidos para Uruguay"),
    ("unicidad", "Unicidad", "Una empresa por RUT, un teléfono por número y los posibles duplicados resueltos"),
    ("completitud", "Completitud", "Empresas disponibles con al menos 1 teléfono discable, CIIU y departamento"),
    ("exactitud", "Exactitud", "Teléfonos verificados por la sala sobre el total de discables"),
    ("actualidad", "Actualidad", "Teléfonos discables verificados en los últimos 24 meses"),
    ("consistencia", "Consistencia", "Naturaleza jurídica coherente con la razón social (SA, SRL, SAS…)"),
    ("provisoria", "Base provisoria", "Empresas sin RUT y cuántas tienen candidata en la base definitiva"),
]

# indicador → (dimensión, nombre, tipo de meta, meta, unidad)
#   tipo: minimo (valor ≥ meta), maximo (valor ≤ meta), sube (≥ que hace 90 días), info
INDICADORES = {
    "rut_valido": ("validez", "RUT válido", "minimo", 100, "%"),
    # D54: identificadores de 6 a 11 dígitos aceptados sin validar; no cuentan como RUT inválido
    "rut_no_verificado": ("validez", "Empresas con RUT no verificado", "info", None, ""),
    "telefono_valido": ("validez", "Teléfonos E.164 de Uruguay", "minimo", 100, "%"),
    "rut_unico": ("unicidad", "Una empresa por RUT", "minimo", 100, "%"),
    "telefono_unico": ("unicidad", "Un teléfono por número", "minimo", 100, "%"),
    "duplicados_pendientes": ("unicidad", "Posibles duplicados sin resolver", "maximo", 0, ""),
    "completitud": ("completitud", "Disponibles con teléfono, CIIU y departamento", "minimo", 90, "%"),
    "exactitud": ("exactitud", "Discables verificados", "sube", None, "%"),
    "actualidad": ("actualidad", "Verificados en los últimos 24 meses", "minimo", 70, "%"),
    "consistencia": ("consistencia", "Alertas de naturaleza sin revisar", "maximo", 0, ""),
    "provisorias": ("provisoria", "Empresas en la base provisoria", "info", None, ""),
    "provisorias_con_candidata": ("provisoria", "Provisorias con candidata en la definitiva", "info", None, "%"),
}
CERCA = 5  # puntos porcentuales (o unidades) para «cerca»


def _pct(num, den):
    return None if not den else round(100.0 * num / den, 1)


def _valor(clave, num, den):
    unidad = INDICADORES[clave][4]
    return _pct(num, den) if unidad == "%" else num


def calcular(conn) -> dict[str, dict]:
    """Valor actual de cada indicador: {clave: {valor, numerador, denominador}}."""
    _, cfg = config.vigente(conn)
    excluidas = cfg.get("naturalezas_excluidas") or []
    out = {}
    ruts = [r["rut"] for r in conn.execute(f"SELECT e.rut FROM empresa e WHERE {DEFINITIVA}")]
    de12 = [r for r in ruts if r and len(r) == 12]
    out["rut_valido"] = (sum(1 for r in de12 if rutmod.es_valido(r)), len(de12))
    out["rut_no_verificado"] = (len(ruts) - len(de12), len(ruts))
    out["rut_unico"] = (len(set(ruts)), len(ruts))
    t = conn.execute(
        f"SELECT count(DISTINCT t.id) AS den, count(DISTINCT t.id) FILTER (WHERE t.e164 LIKE '+598%%') AS num,"
        f" count(DISTINCT coalesce(t.e164, t.crudo)) AS distintos"
        f" FROM telefono t JOIN telefono_vinculo v ON v.telefono_id = t.id JOIN empresa e ON e.id = v.empresa_id"
        f" WHERE {DEFINITIVA}").fetchone()
    out["telefono_valido"] = (t["num"], t["den"])
    out["telefono_unico"] = (t["distintos"], t["den"])
    d = conn.execute("SELECT count(*) AS n FROM duplicado_par WHERE estado = 'pendiente'").fetchone()["n"]
    out["duplicados_pendientes"] = (d, None)
    c = conn.execute(
        f"SELECT count(*) AS den, count(*) FILTER (WHERE e.ciiu IS NOT NULL AND e.ciiu <> '' AND e.departamento IS NOT NULL"
        f" AND e.departamento <> '' AND EXISTS (SELECT 1 FROM v_vinculo_discable x WHERE x.empresa_id = e.id)) AS num"
        f" FROM empresa e WHERE {_DISPONIBLES}", {"excluidas": excluidas}).fetchone()
    out["completitud"] = (c["num"], c["den"])
    x = conn.execute(
        "SELECT count(*) AS den, count(*) FILTER (WHERE v.estado = 'verificado') AS verif,"
        " count(*) FILTER (WHERE v.estado = 'verificado' AND v.fecha > now() - interval '24 months') AS recientes "
        + _DISCABLES_DEF).fetchone()
    out["exactitud"] = (x["verif"], x["den"])
    out["actualidad"] = (x["recientes"], x["den"])
    out["consistencia"] = (conn.execute(f"SELECT count(*) AS n FROM ({_ALERTAS_PENDIENTES}) a").fetchone()["n"], None)
    p = conn.execute("SELECT count(*) AS n FROM empresa WHERE base = 'provisoria' AND baja IS NULL").fetchone()["n"]
    out["provisorias"] = (p, None)
    out["provisorias_con_candidata"] = (provisorias.contar_con_candidatas(conn) if p else 0, p)
    return {k: {"valor": _valor(k, n, den), "numerador": n, "denominador": den} for k, (n, den) in out.items()}


def _estado(clave, valor, previo) -> str:
    _, _, tipo, meta, _ = INDICADORES[clave]
    if tipo == "info":
        return "informativo"
    if valor is None:
        return "sin_datos"
    if tipo == "minimo":
        return "cumple" if valor >= meta else "cerca" if valor >= meta - CERCA else "no_cumple"
    if tipo == "maximo":
        return "cumple" if valor <= meta else "cerca" if valor <= meta + CERCA else "no_cumple"
    # «sube cada trimestre»: contra la medición de hace 90 días (o la más vieja de ese período)
    if previo is None:
        return "sin_historia"
    return "cumple" if valor > previo else "cerca" if valor == previo else "no_cumple"


def _meta_texto(clave) -> str:
    _, _, tipo, meta, unidad = INDICADORES[clave]
    if tipo == "minimo":
        return f"≥ {meta:g}{' %' if unidad else ''}" if meta != 100 else "100 %"
    if tipo == "maximo":
        return f"{meta:g} pendientes" if clave == "duplicados_pendientes" else "Alertas revisadas" if clave == "consistencia" else f"≤ {meta:g}"
    if tipo == "sube":
        return "Sube cada trimestre"
    return "Sin meta (informativo)"


def _series(conn, dias: int = 183) -> dict[str, list]:
    series: dict[str, list] = {}
    for r in conn.execute("SELECT fecha, indicador, valor FROM calidad_medicion WHERE fecha > current_date - %s"
                          " ORDER BY fecha", (dias,)):
        series.setdefault(r["indicador"], []).append({"fecha": r["fecha"], "valor": float(r["valor"]) if r["valor"] is not None else None})
    return series


def _hace_un_trimestre(conn, indicador) -> float | None:
    r = conn.execute("SELECT valor FROM calidad_medicion WHERE indicador = %s AND fecha <= current_date - 90"
                     " ORDER BY fecha DESC LIMIT 1", (indicador,)).fetchone()
    if r is None:
        r = conn.execute("SELECT valor FROM calidad_medicion WHERE indicador = %s AND fecha < current_date"
                         " ORDER BY fecha LIMIT 1", (indicador,)).fetchone()
    return float(r["valor"]) if r and r["valor"] is not None else None


ORDEN_ESTADO = ("no_cumple", "cerca", "sin_historia", "sin_datos", "cumple", "informativo")


def tablero(conn) -> dict:
    valores = calcular(conn)
    series = _series(conn)
    dims = []
    for clave, nombre, regla in DIMENSIONES:
        inds = []
        for k, (dim, nom, tipo, meta, unidad) in INDICADORES.items():
            if dim != clave:
                continue
            v = valores[k]
            previo = _hace_un_trimestre(conn, k) if tipo == "sube" else None
            inds.append({"clave": k, "nombre": nom, **v, "unidad": unidad, "meta": meta, "meta_texto": _meta_texto(k),
                         "estado": _estado(k, v["valor"], previo), "trimestre_anterior": previo,
                         "serie": series.get(k, [])})
        estado = min((i["estado"] for i in inds), key=ORDEN_ESTADO.index)
        dims.append({"clave": clave, "nombre": nombre, "regla": regla, "estado": estado, "indicadores": inds})
    ultima = conn.execute("SELECT max(fecha) AS f FROM calidad_medicion").fetchone()["f"]
    from . import enriquecimiento  # import circular: enriquecimiento usa config y empresas

    return {"dimensiones": dims, "enriquecimiento": enriquecimiento.resumen_gasto(conn), "ultima_medicion": ultima}


def medir(conn, fecha: dt.date | None = None, actor: str = "job:calidad") -> dict:
    """Guarda la foto del día (si ya había una, la reemplaza: el job puede correr dos veces)."""
    fecha = fecha or conn.execute("SELECT current_date AS d").fetchone()["d"]
    valores = calcular(conn)
    for k, v in valores.items():
        conn.execute(
            "INSERT INTO calidad_medicion (fecha, dimension, indicador, valor, numerador, denominador)"
            " VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (fecha, indicador) DO UPDATE SET valor = EXCLUDED.valor,"
            " numerador = EXCLUDED.numerador, denominador = EXCLUDED.denominador, creado = now()",
            (fecha, INDICADORES[k][0], k, v["valor"], v["numerador"], v["denominador"]))
    auditoria.registrar(conn, actor, "calidad.medir", "calidad", str(fecha), {"indicadores": len(valores)})
    return {"fecha": fecha, "indicadores": len(valores)}


# ─────────────────────────────────────────────────────────────
# Lo que incumple cada indicador (lista de trabajo)
# ─────────────────────────────────────────────────────────────

POR_PAGINA = 50


def _pagina(conn, sql: str, args, pagina: int) -> dict:
    total = conn.execute(f"SELECT count(*) AS n FROM ({sql}) q", args).fetchone()["n"]
    filas = conn.execute(f"{sql} LIMIT {POR_PAGINA} OFFSET %(off)s", {**(args or {}), "off": (pagina - 1) * POR_PAGINA}).fetchall()
    return {"total": total, "pagina": pagina, "por_pagina": POR_PAGINA, "filas": filas}


def incumplen(conn, indicador: str, pagina: int = 1) -> dict:
    if indicador not in INDICADORES:
        raise HTTPException(404, "Indicador desconocido")
    pagina = max(1, pagina)
    _, cfg = config.vigente(conn)
    tipo_lista = "empresas"
    if indicador == "rut_valido":
        malos = [r for r in conn.execute(f"SELECT e.id, e.codigo, e.rut, e.razon_social, e.departamento FROM empresa e"
                                         f" WHERE {DEFINITIVA} ORDER BY e.razon_social")
                 if r["rut"] and len(r["rut"]) == 12 and not rutmod.es_valido(r["rut"])]
        filas = [{**r, "problema": rutmod.validar(r["rut"])[1]} for r in malos]
        ini = (pagina - 1) * POR_PAGINA
        return {"tipo": tipo_lista, "total": len(filas), "pagina": pagina, "por_pagina": POR_PAGINA,
                "filas": filas[ini:ini + POR_PAGINA]}
    if indicador == "rut_no_verificado":
        filas = conn.execute(f"SELECT e.id, e.codigo, e.rut, e.razon_social, e.departamento,"
                             f" length(e.rut) || ' dígitos' AS problema FROM empresa e"
                             f" WHERE {DEFINITIVA} AND e.rut_verificado = false ORDER BY e.razon_social").fetchall()
        ini = (pagina - 1) * POR_PAGINA
        return {"tipo": tipo_lista, "total": len(filas), "pagina": pagina, "por_pagina": POR_PAGINA,
                "filas": filas[ini:ini + POR_PAGINA]}
    if indicador == "telefono_valido":
        tipo_lista = "telefonos"
        sql = (f"SELECT DISTINCT ON (t.id) t.id, t.crudo, t.e164, t.tipo, e.codigo, e.razon_social,"
               f" CASE WHEN t.e164 IS NULL THEN 'no se pudo normalizar' ELSE 'número internacional' END AS problema"
               f" FROM telefono t JOIN telefono_vinculo v ON v.telefono_id = t.id JOIN empresa e ON e.id = v.empresa_id"
               f" WHERE {DEFINITIVA} AND (t.e164 IS NULL OR t.e164 NOT LIKE '+598%%') ORDER BY t.id")
        r = _pagina(conn, sql, {}, pagina)
    elif indicador in ("rut_unico", "telefono_unico"):
        # Los garantiza la base (índices únicos): la lista queda vacía salvo un error de datos
        r = {"total": 0, "pagina": 1, "por_pagina": POR_PAGINA, "filas": []}
    elif indicador == "duplicados_pendientes":
        tipo_lista = "pares"
        from . import duplicados

        return {"tipo": tipo_lista, **duplicados.bandeja(conn, "pendiente", pagina)}
    elif indicador == "completitud":
        sql = (f"SELECT e.id, e.codigo, e.razon_social, e.departamento, e.ciiu, concat_ws(', ',"
               f" CASE WHEN NOT EXISTS (SELECT 1 FROM v_vinculo_discable x WHERE x.empresa_id = e.id) THEN 'sin teléfono discable' END,"
               f" CASE WHEN coalesce(e.ciiu, '') = '' THEN 'sin CIIU' END,"
               f" CASE WHEN coalesce(e.departamento, '') = '' THEN 'sin departamento' END) AS problema"
               f" FROM empresa e WHERE {_DISPONIBLES} AND NOT (coalesce(e.ciiu, '') <> '' AND coalesce(e.departamento, '') <> ''"
               f" AND EXISTS (SELECT 1 FROM v_vinculo_discable x WHERE x.empresa_id = e.id)) ORDER BY e.razon_social")
        r = _pagina(conn, sql, {"excluidas": cfg.get("naturalezas_excluidas") or []}, pagina)
    elif indicador in ("exactitud", "actualidad"):
        tipo_lista = "telefonos"
        cond = ("v.estado <> 'verificado'" if indicador == "exactitud"
                else "NOT (v.estado = 'verificado' AND v.fecha > now() - interval '24 months')")
        sql = (f"SELECT d.telefono_id AS id, d.e164, e.codigo, e.razon_social, v.estado, v.fecha,"
               f" CASE WHEN v.estado = 'verificado' THEN 'verificado hace más de 24 meses' ELSE 'sin verificar' END AS problema "
               + _DISCABLES_DEF + f" AND {cond} ORDER BY e.razon_social, d.e164")
        r = _pagina(conn, sql, {}, pagina)
    elif indicador == "consistencia":
        sql = (f"SELECT a.id, a.codigo, a.razon_social, a.naturaleza, a.sugerida, a.firma,"
               f" 'la razón social sugiere ' || a.sugerida AS problema FROM ({_ALERTAS_PENDIENTES}) a ORDER BY a.razon_social")
        r = _pagina(conn, sql, {}, pagina)
    else:  # provisorias
        sql = ("SELECT e.id, e.codigo, e.razon_social, e.departamento, NULL AS problema FROM empresa e"
               " WHERE e.base = 'provisoria' AND e.baja IS NULL ORDER BY e.razon_social")
        r = _pagina(conn, sql, {}, pagina)
    return {"tipo": tipo_lista, **r}


def revisar_alerta(conn, empresa_id: int, actor: str) -> dict:
    a = conn.execute(_ALERTAS_SQL + " AND e.id = %s", (empresa_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "La empresa no tiene una alerta de consistencia")
    conn.execute("INSERT INTO calidad_alerta_revisada (empresa_id, regla, firma, revisada_por) VALUES (%s, 'naturaleza', %s, %s)"
                 " ON CONFLICT (empresa_id, regla) DO UPDATE SET firma = EXCLUDED.firma, revisada_por = EXCLUDED.revisada_por,"
                 " fecha = now()", (empresa_id, a["firma"], actor))
    auditoria.registrar(conn, actor, "calidad.revisar_alerta", "empresa", a["codigo"],
                        {"regla": "naturaleza", "naturaleza": a["naturaleza"], "sugerida": a["sugerida"]})
    return {"revisada": a["codigo"]}
