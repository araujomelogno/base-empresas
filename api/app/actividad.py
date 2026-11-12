"""Indicadores de actividad, rendimiento por origen, empresas llamadas y línea de tiempo (R1.11, D38).

Los filtros de estudio y de muestra seleccionan las llamadas **por empresa**, no por ítem (D38):
cuenta toda llamada a una empresa que pertenece a una muestra de ese estudio (o a esa muestra),
aunque la llamada no haya quedado asociada al ítem (antes del campo, en Conciliación…). Sin esos
filtros cuentan todas las llamadas a empresas del período, estén o no en una muestra.
"""
import csv
import io

from .util import TZ


def _filtros(f: dict, alias_intento="i"):
    w, a = ["TRUE"], []
    i = alias_intento
    if f.get("estudio_id"):
        w.append(f"EXISTS (SELECT 1 FROM muestra_item mi JOIN muestra m ON m.id = mi.muestra_id"
                 f" WHERE m.estudio_id = %s AND mi.empresa_id = ANY({i}.empresas))")
        a.append(f["estudio_id"])
    if f.get("muestra_id"):
        w.append(f"EXISTS (SELECT 1 FROM muestra_item mi WHERE mi.muestra_id = %s AND mi.empresa_id = ANY({i}.empresas))")
        a.append(f["muestra_id"])
    if f.get("corrida_id"):
        # Las llamadas a empresas de esa corrida; para corridas anteriores a 0009, por el lote
        w.append(f"({i}.id IN (SELECT intento_id FROM cdr_corrida_intento WHERE corrida_id = %s)"
                 f" OR {i}.lote_id IN (SELECT id FROM cdr_lote WHERE corrida_id = %s))")
        a += [f["corrida_id"], f["corrida_id"]]
    if f.get("encuestador"):
        w.append(f"{alias_intento}.encuestador = %s")
        a.append(f["encuestador"])
    if f.get("desde"):
        w.append(f"{alias_intento}.inicio >= %s::date")
        a.append(f["desde"])
    if f.get("hasta"):
        w.append(f"{alias_intento}.inicio < %s::date + 1")
        a.append(f["hasta"])
    return " AND ".join(w), a


def _filtros_estado(f: dict):
    w, a = ["ps.estado IN ('completa','rechazo','en_curso')"], []
    if f.get("estudio_id"):
        w.append("m.estudio_id = %s")
        a.append(f["estudio_id"])
    if f.get("muestra_id"):
        w.append("m.id = %s")
        a.append(f["muestra_id"])
    if f.get("encuestador"):
        w.append("ps.encuestador = %s")
        a.append(f["encuestador"])
    if f.get("desde"):
        w.append("ps.fecha >= %s::date")
        a.append(f["desde"])
    if f.get("hasta"):
        w.append("ps.fecha < %s::date + 1")
        a.append(f["hasta"])
    return " AND ".join(w), a


def tablero(conn, f: dict) -> dict:
    w, a = _filtros(f)
    tot = conn.execute(
        f"SELECT count(*) AS intentos, count(DISTINCT i.telefono_id) AS telefonos_marcados,"
        f" (SELECT count(DISTINCT e) FROM intento i2, unnest(i2.empresas) e WHERE i2.id IN"
        f"   (SELECT i.id FROM intento i WHERE {w})) AS empresas_llamadas,"
        f" count(DISTINCT i.encuestador) AS encuestadores, count(*) FILTER (WHERE i.item_id IS NOT NULL) AS asociados_a_item"
        f" FROM intento i WHERE {w}", a + a).fetchone()
    por_franja = conn.execute(
        f"SELECT coalesce(i.franja, 'sin franja') AS franja, count(*) AS intentos, count(DISTINCT i.telefono_id) AS telefonos"
        f" FROM intento i WHERE {w} GROUP BY 1 ORDER BY 2 DESC", a).fetchall()
    por_dia = conn.execute(
        f"SELECT (i.inicio AT TIME ZONE current_setting('TimeZone'))::date AS dia, count(*) AS intentos"
        f" FROM intento i WHERE {w} GROUP BY 1 ORDER BY 1", a).fetchall()
    por_disposicion = conn.execute(
        f"SELECT coalesce(i.disposicion, 'sin dato') AS disposicion, count(*) AS intentos FROM intento i WHERE {w}"
        f" GROUP BY 1 ORDER BY 2 DESC LIMIT 15", a).fetchall()
    we, ae = _filtros_estado(f)
    estados = conn.execute(
        f"SELECT ps.estado, count(*) AS n, count(DISTINCT i.empresa_id) AS empresas FROM item_parte_estado ps"
        f" JOIN muestra_item i ON i.id = ps.item_id JOIN muestra m ON m.id = i.muestra_id WHERE {we} GROUP BY 1",
        ae).fetchall()
    est = {r["estado"]: r["n"] for r in estados}
    por_encuestador = conn.execute(
        f"""
        WITH it AS (SELECT i.encuestador, count(*) AS intentos, count(DISTINCT i.telefono_id) AS telefonos
                    FROM intento i WHERE {w} GROUP BY 1),
             res AS (SELECT ps.encuestador, count(*) FILTER (WHERE ps.estado = 'completa') AS completas,
                            count(*) FILTER (WHERE ps.estado IN ('completa','rechazo')) AS efectivos
                     FROM item_parte_estado ps JOIN muestra_item i ON i.id = ps.item_id JOIN muestra m ON m.id = i.muestra_id
                     WHERE {we} GROUP BY 1)
        SELECT coalesce(it.encuestador, res.encuestador, 'sin dato') AS encuestador,
               coalesce(it.intentos, 0) AS intentos, coalesce(it.telefonos, 0) AS telefonos,
               coalesce(res.completas, 0) AS completas, coalesce(res.efectivos, 0) AS contactos_efectivos
        FROM it FULL JOIN res ON res.encuestador = it.encuestador
        ORDER BY 2 DESC, 4 DESC
        """, a + ae).fetchall()
    return {
        **tot,
        "completas": est.get("completa", 0),
        "contactos_efectivos": est.get("completa", 0) + est.get("rechazo", 0),
        "en_curso": est.get("en_curso", 0),
        "por_franja": por_franja, "por_dia": por_dia, "por_encuestador": por_encuestador,
        "por_disposicion": por_disposicion,
        "encuestadores_lista": [r["encuestador"] for r in conn.execute(
            "SELECT DISTINCT encuestador FROM intento WHERE encuestador IS NOT NULL ORDER BY 1")],
    }


# Llamada atendida (pregunta abierta del spec, decisión D34): la disposición del CDR manda
# (ANSWER/ANSWERED sí; BUSY, NO ANSWER, FAILED… no); si la disposición no es una de esas
# (por ejemplo, viene del userfield del marcador), cuenta la duración facturada (billsec) > 0.
ATENDIDA = ("(upper(coalesce(i.disposicion, '')) LIKE 'ANSWER%%' OR (coalesce(i.duracion, 0) > 0 AND"
            " upper(coalesce(i.disposicion, '')) NOT IN ('BUSY', 'NO ANSWER', 'NOANSWER', 'FAILED', 'CONGESTION', 'CANCEL')))")


def _alcance_empresas(f: dict) -> tuple[str, list]:
    """Empresas del estudio o la muestra filtrados (para contar teléfonos discables)."""
    if f.get("muestra_id"):
        return "d.empresa_id IN (SELECT empresa_id FROM muestra_item WHERE muestra_id = %s)", [f["muestra_id"]]
    if f.get("estudio_id"):
        return ("d.empresa_id IN (SELECT mi.empresa_id FROM muestra_item mi JOIN muestra m ON m.id = mi.muestra_id"
                " WHERE m.estudio_id = %s)", [f["estudio_id"]])
    return "TRUE", []


def _por_origen(conn, sql: str, args: list) -> dict:
    """Ejecuta una consulta agrupada por GROUPING SETS ((codigo), ()) y devuelve {codigo | None: fila}."""
    return {r["codigo"]: r for r in conn.execute(sql, args)}


SIN_VINCULO = "_sin_vinculo"   # llamadas cuyo teléfono ya no está vinculado a la empresa (no tienen origen)
_CON_ORIGEN = ("EXISTS (SELECT 1 FROM telefono_vinculo v JOIN telefono_vinculo_origen x ON x.vinculo_id = v.id"
               " WHERE v.telefono_id = it.telefono_id AND v.empresa_id = ANY(it.empresas))")


def rendimiento_origen(conn, f: dict) -> dict:
    """Rendimiento de cada origen de teléfono (C9, D38). Cuenta todas las llamadas a empresas de la base
    (con o sin ítem de muestra). Un teléfono con varios orígenes cuenta en cada uno; la fila Total sale de
    todas las llamadas filtradas, así coincide con el tablero. Llamada atendida: ver ATENDIDA."""
    w, a = _filtros(f)
    alc, aa = _alcance_empresas(f)
    discables = _por_origen(conn, f"""
        SELECT o.codigo, count(DISTINCT d.vinculo_id) AS discables
        FROM v_vinculo_discable d JOIN telefono_vinculo_origen x ON x.vinculo_id = d.vinculo_id
        JOIN origen_telefono o ON o.id = x.origen_id WHERE {alc}
        GROUP BY GROUPING SETS ((o.codigo), ())""", aa)
    base = f"""
        WITH it AS (SELECT i.id, i.telefono_id, i.empresas, {ATENDIDA} AS atendida
                    FROM intento i WHERE {w}),
             vo AS (SELECT it.id AS intento_id, it.telefono_id, it.atendida, v.id AS vinculo_id, v.empresa_id, o.codigo
                    FROM it JOIN telefono_vinculo v ON v.telefono_id = it.telefono_id AND v.empresa_id = ANY(it.empresas)
                    JOIN telefono_vinculo_origen x ON x.vinculo_id = v.id JOIN origen_telefono o ON o.id = x.origen_id)"""
    llamadas = {r["codigo"]: r for r in conn.execute(base + """
        SELECT codigo, count(DISTINCT telefono_id) AS llamados, count(DISTINCT intento_id) AS intentos,
               count(DISTINCT telefono_id) FILTER (WHERE atendida) AS atendidos, count(DISTINCT empresa_id) AS empresas
        FROM vo GROUP BY codigo""", a)}
    # Total y llamadas sin origen: desde todas las llamadas filtradas (cada teléfono y empresa una vez)
    for clave, cond in ((None, "TRUE"), (SIN_VINCULO, f"NOT {_CON_ORIGEN}")):
        llamadas[clave] = conn.execute(base + f"""
            SELECT count(*) AS intentos, count(DISTINCT it.telefono_id) AS llamados,
                   count(DISTINCT it.telefono_id) FILTER (WHERE it.atendida) AS atendidos,
                   (SELECT count(DISTINCT e) FROM it, unnest(it.empresas) e
                     WHERE {cond} AND EXISTS (SELECT 1 FROM empresa x WHERE x.id = e)) AS empresas
            FROM it WHERE {cond}""", a).fetchone()
    calidad = _por_origen(conn, base + """
        SELECT o.codigo,
               count(DISTINCT h.vinculo_id) FILTER (WHERE h.estado = 'no_corresponde') AS no_corresponde,
               count(DISTINCT h.vinculo_id) FILTER (WHERE h.estado = 'inexistente') AS inexistente,
               count(DISTINCT h.vinculo_id) FILTER (WHERE h.estado = 'intermediario') AS intermediario
        FROM telefono_vinculo_historia h JOIN telefono_vinculo_origen x ON x.vinculo_id = h.vinculo_id
        JOIN origen_telefono o ON o.id = x.origen_id
        WHERE h.fuente_tipo IN ('sala', 'sav') AND h.vinculo_id IN (SELECT vinculo_id FROM vo)
        GROUP BY GROUPING SETS ((o.codigo), ())""", a)
    we, ae = _filtros_estado(f)
    efectivos = _por_origen(conn, f"""
        SELECT o.codigo, count(DISTINCT ps.item_id) AS efectivos
        FROM item_parte_estado ps JOIN muestra_item i ON i.id = ps.item_id JOIN muestra m ON m.id = i.muestra_id
        JOIN telefono_vinculo v ON v.telefono_id = ps.telefono_id AND v.empresa_id = i.empresa_id
        JOIN telefono_vinculo_origen x ON x.vinculo_id = v.id JOIN origen_telefono o ON o.id = x.origen_id
        WHERE {we} AND ps.estado IN ('completa', 'rechazo')
        GROUP BY GROUPING SETS ((o.codigo), ())""", ae)

    def fila(codigo, nombre, prioridad):
        d = discables.get(codigo) or {}
        ll = llamadas.get(codigo) or {}
        ca = calidad.get(codigo) or {}
        ef = efectivos.get(codigo) or {}
        llamados = ll.get("llamados", 0)
        n_ef = ef.get("efectivos", 0)
        pct = (lambda n: round(100 * n / llamados, 1) if llamados else None)
        return {
            "codigo": codigo, "nombre": nombre, "prioridad": prioridad,
            "discables": d.get("discables", 0),
            "telefonos_llamados": llamados, "llamadas": ll.get("intentos", 0), "empresas_llamadas": ll.get("empresas", 0),
            "llamados": llamados, "intentos": ll.get("intentos", 0),   # nombres anteriores, por compatibilidad
            "atendidos": ll.get("atendidos", 0), "contactabilidad": pct(ll.get("atendidos", 0)),
            "contactos_efectivos": n_ef,
            "no_corresponde": ca.get("no_corresponde", 0), "pct_no_corresponde": pct(ca.get("no_corresponde", 0)),
            "inexistente": ca.get("inexistente", 0), "pct_inexistente": pct(ca.get("inexistente", 0)),
            "intermediario": ca.get("intermediario", 0), "pct_intermediario": pct(ca.get("intermediario", 0)),
            "intentos_por_efectivo": round(ll.get("intentos", 0) / n_ef, 1) if n_ef else None,
        }

    usados = set(discables) | {k for k, v in llamadas.items() if k and v.get("intentos")} | set(calidad) | set(efectivos)
    filas = [fila(o["codigo"], o["nombre"], o["prioridad"]) for o in conn.execute(
        "SELECT codigo, nombre, prioridad FROM origen_telefono ORDER BY prioridad, nombre") if o["codigo"] in usados]
    if llamadas[SIN_VINCULO]["intentos"]:
        filas.append(fila(SIN_VINCULO, "Sin vínculo vigente", None))
    return {"origenes": filas, "total": fila(None, "Total", None),
            "definicion_atendida": "disposición ANSWERED en el CDR o, si la disposición no lo dice, duración facturada mayor a 0"}


# ─────────────────────────────────────────────────────────────
# Empresas llamadas (R4)
# ─────────────────────────────────────────────────────────────

def empresas_llamadas(conn, f: dict, origen: str | None = None, solo_sin_muestra: bool = False) -> tuple[list[dict], int]:
    """Una fila por empresa llamada con los filtros de Actividad (y, opcionalmente, una corrida y un origen).
    Con origen, cuenta solo las llamadas a teléfonos de ese origen. No incluye contactos (personas).
    Devuelve (filas, llamadas distintas): una llamada a un número compartido por varias empresas
    aparece en la fila de cada una, así que la suma de las filas puede ser mayor que el total."""
    w, a = _filtros(f)
    args = list(a)
    cond_origen = ""
    if origen == SIN_VINCULO:
        cond_origen = ("WHERE NOT EXISTS (SELECT 1 FROM telefono_vinculo v JOIN telefono_vinculo_origen x ON x.vinculo_id = v.id"
                       " WHERE v.telefono_id = ie.telefono_id AND v.empresa_id = ie.empresa_id)")
    elif origen:
        cond_origen = ("WHERE EXISTS (SELECT 1 FROM telefono_vinculo v JOIN telefono_vinculo_origen x ON x.vinculo_id = v.id"
                       " JOIN origen_telefono o ON o.id = x.origen_id"
                       " WHERE v.telefono_id = ie.telefono_id AND v.empresa_id = ie.empresa_id AND o.codigo = %s)")
        args.append(origen)
    alcance, aa = "TRUE", []
    if f.get("muestra_id"):
        alcance, aa = "m.id = %s", [f["muestra_id"]]
    elif f.get("estudio_id"):
        alcance, aa = "m.estudio_id = %s", [f["estudio_id"]]
    sin_muestra = "AND NOT EXISTS (SELECT 1 FROM muestra_item mi WHERE mi.empresa_id = e.id)" if solo_sin_muestra else ""
    ctes = f"""
        WITH it AS (SELECT i.id, i.telefono_id, i.empresas, i.inicio, i.encuestador, {ATENDIDA} AS atendida
                    FROM intento i WHERE {w}),
             ie AS (SELECT * FROM (SELECT it.*, e AS empresa_id FROM it, unnest(it.empresas) e) ie {cond_origen})"""
    total = conn.execute(ctes + f"""
        SELECT count(DISTINCT ie.id) AS n FROM ie JOIN empresa e ON e.id = ie.empresa_id WHERE TRUE {sin_muestra}""",
        args).fetchone()["n"]
    filas = conn.execute(ctes + f""",
             ag AS (SELECT empresa_id, count(DISTINCT id) AS llamadas, count(DISTINCT id) FILTER (WHERE atendida) AS atendidas,
                           min(inicio) AS primera, max(inicio) AS ultima,
                           array_remove(array_agg(DISTINCT encuestador), NULL) AS encuestadores,
                           array_agg(DISTINCT telefono_id) AS tels
                    FROM ie GROUP BY empresa_id)
        SELECT e.id, e.rut, e.razon_social, e.departamento, ag.llamadas, ag.atendidas, ag.primera, ag.ultima, ag.encuestadores,
               (SELECT json_agg(json_build_object('numero', coalesce(t.e164, t.crudo), 'origenes',
                         (SELECT coalesce(json_agg(o.nombre ORDER BY o.prioridad), '[]'::json) FROM telefono_vinculo v
                          JOIN telefono_vinculo_origen x ON x.vinculo_id = v.id JOIN origen_telefono o ON o.id = x.origen_id
                          WHERE v.telefono_id = t.id AND v.empresa_id = e.id)) ORDER BY t.e164)
                  FROM telefono t WHERE t.id = ANY(ag.tels)) AS telefonos,
               (SELECT json_agg(json_build_object('estudio', s.nombre, 'muestra', m.nombre, 'muestra_id', m.id,
                         'estado_muestra', m.estado, 'rol', mi.rol, 'liberado', mi.liberado,
                         'estados', (SELECT json_object_agg(p.nombre, ps.estado) FROM item_parte_estado ps
                                     JOIN parte p ON p.id = ps.parte_id WHERE ps.item_id = mi.id)) ORDER BY m.id DESC)
                  FROM muestra_item mi JOIN muestra m ON m.id = mi.muestra_id JOIN estudio s ON s.id = m.estudio_id
                  WHERE mi.empresa_id = e.id AND {alcance}) AS muestras
        FROM ag JOIN empresa e ON e.id = ag.empresa_id
        WHERE TRUE {sin_muestra}
        ORDER BY ag.llamadas DESC, e.razon_social NULLS LAST, e.rut""", args + aa).fetchall()
    return filas, total


COLUMNAS_CSV = ("RUT", "Razón social", "Departamento", "Teléfonos llamados", "Llamadas", "Atendidas",
                "Primera llamada", "Última llamada", "Encuestadores", "Estudio / muestra", "Estado del ítem")


def _hora(d) -> str:
    return d.astimezone(TZ).strftime("%Y-%m-%d %H:%M") if d else ""


def csv_empresas(filas: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(COLUMNAS_CSV)
    for r in filas:
        muestras = r["muestras"] or []
        w.writerow([
            r["rut"], r["razon_social"] or "", r["departamento"] or "",
            " | ".join(f"{t['numero']} ({', '.join(t['origenes']) or 'sin origen'})" for t in (r["telefonos"] or [])),
            r["llamadas"], r["atendidas"], _hora(r["primera"]), _hora(r["ultima"]), ", ".join(r["encuestadores"] or []),
            " | ".join(f"{m['estudio']} / {m['muestra']}" for m in muestras) or "sin muestra",
            " | ".join(", ".join(f"{p}: {e}" for p, e in (m["estados"] or {}).items()) or ("liberado" if m["liberado"] else "no liberado")
                       for m in muestras),
        ])
    return buf.getvalue()


def linea_de_tiempo(conn, empresa_id: int, limite: int = 300) -> list[dict]:
    return conn.execute(
        """
        SELECT * FROM (
          SELECT h.fecha, 'dato' AS tipo,
                 h.campo || ' = ' || coalesce(h.valor, '∅') AS descripcion,
                 h.fuente_tipo || coalesce(' #' || h.fuente_id, '') AS fuente, h.actor
          FROM empresa_campo_historia h WHERE h.empresa_id = %(e)s
          UNION ALL
          SELECT i.inicio, 'llamada', t.e164 || ' · ' || coalesce(i.disposicion, 'sin disposición')
                 || coalesce(' · ' || i.duracion || ' s', ''), coalesce(i.campania, 'marcador manual'), i.encuestador
          FROM intento i JOIN telefono t ON t.id = i.telefono_id WHERE %(e)s = ANY(i.empresas)
          UNION ALL
          SELECT ps.fecha, 'resultado', p.nombre || ': ' || ps.estado || coalesce(' · respondió ' || ps.respondente, ''),
                 s.nombre, ps.encuestador
          FROM item_parte_estado ps JOIN muestra_item mi ON mi.id = ps.item_id JOIN parte p ON p.id = ps.parte_id
          JOIN estudio s ON s.id = p.estudio_id
          WHERE mi.empresa_id = %(e)s AND ps.fecha IS NOT NULL
          UNION ALL
          SELECT vh.fecha, 'teléfono', coalesce(t.e164, t.crudo) || ' → ' || vh.estado, vh.fuente_tipo, vh.actor
          FROM telefono_vinculo_historia vh JOIN telefono t ON t.id = vh.telefono_id WHERE vh.empresa_id = %(e)s
          UNION ALL
          SELECT coalesce(mi.liberado_fecha, m.sorteada), 'muestra',
                 m.nombre || ' · ' || mi.rol || ' · estrato ' || mi.estrato || CASE WHEN mi.liberado THEN '' ELSE ' (no liberado)' END,
                 'sorteo', m.sorteada_por
          FROM muestra_item mi JOIN muestra m ON m.id = mi.muestra_id WHERE mi.empresa_id = %(e)s
          UNION ALL
          SELECT n.fecha, 'no llamar', n.motivo || CASE WHEN n.activo THEN '' ELSE ' (levantado)' END, n.solicitante, n.registrado_por
          FROM no_llamar n WHERE n.alcance = 'empresa' AND n.objeto_id = %(e)s
        ) x WHERE fecha IS NOT NULL ORDER BY fecha DESC LIMIT %(l)s
        """, {"e": empresa_id, "l": limite}).fetchall()
