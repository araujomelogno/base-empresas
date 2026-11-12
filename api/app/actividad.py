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


SIN_ENCUESTADOR = "(sin encuestador)"


def _filtros_sav(f: dict):
    """Filas del .sav (D39: cada una es una encuesta completa), sin depender del ítem: el estudio por la parte,
    el período por la fecha de la fila. Con una muestra elegida cuentan las filas asociadas a sus ítems."""
    w, a = ["TRUE"], []
    if f.get("estudio_id"):
        w.append("p.estudio_id = %s")
        a.append(f["estudio_id"])
    if f.get("muestra_id"):
        w.append("EXISTS (SELECT 1 FROM muestra_item mi WHERE mi.id = s.item_id AND mi.muestra_id = %s)")
        a.append(f["muestra_id"])
    if f.get("encuestador"):
        if f["encuestador"] == SIN_ENCUESTADOR:
            w.append("s.encuestador IS NULL")
        else:
            w.append("s.encuestador = %s")
            a.append(f["encuestador"])
    if f.get("desde"):
        w.append("coalesce(s.fecha, g.fecha) >= %s::date")
        a.append(f["desde"])
    if f.get("hasta"):
        w.append("coalesce(s.fecha, g.fecha) < %s::date + 1")
        a.append(f["hasta"])
    return " AND ".join(w), a


SAV_FROM = "sav_fila s JOIN parte p ON p.id = s.parte_id JOIN sav_ingesta g ON g.id = s.ingesta_id"


def completas_sav(conn, f: dict) -> dict:
    ws, as_ = _filtros_sav(f)
    return conn.execute(
        f"SELECT count(*) AS completas, count(*) FILTER (WHERE s.item_id IS NOT NULL) AS asociadas,"
        f" count(*) FILTER (WHERE s.item_id IS NULL) AS sin_asociar FROM {SAV_FROM} WHERE {ws}", as_).fetchone()


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
    sav = completas_sav(conn, f)
    ws, as_ = _filtros_sav(f)
    por_encuestador = conn.execute(
        f"""
        WITH it AS (SELECT coalesce(i.encuestador, %s) AS encuestador, count(*) AS intentos,
                           count(DISTINCT i.telefono_id) AS telefonos FROM intento i WHERE {w} GROUP BY 1),
             sv AS (SELECT coalesce(s.encuestador, %s) AS encuestador, count(*) AS completas
                    FROM {SAV_FROM} WHERE {ws} GROUP BY 1),
             rz AS (SELECT coalesce(ps.encuestador, %s) AS encuestador, count(*) AS rechazos
                    FROM item_parte_estado ps JOIN muestra_item i ON i.id = ps.item_id JOIN muestra m ON m.id = i.muestra_id
                    WHERE {we} AND ps.estado = 'rechazo' GROUP BY 1)
        SELECT coalesce(it.encuestador, sv.encuestador, rz.encuestador) AS encuestador,
               coalesce(it.intentos, 0) AS intentos, coalesce(it.telefonos, 0) AS telefonos,
               coalesce(sv.completas, 0) AS completas, coalesce(sv.completas, 0) + coalesce(rz.rechazos, 0) AS contactos_efectivos
        FROM it FULL JOIN sv ON sv.encuestador = it.encuestador
        FULL JOIN rz ON rz.encuestador = coalesce(it.encuestador, sv.encuestador)
        ORDER BY 2 DESC, 4 DESC
        """, [SIN_ENCUESTADOR] + a + [SIN_ENCUESTADOR] + as_ + [SIN_ENCUESTADOR] + ae).fetchall()
    return {
        **tot,
        # D39: «Encuestas completas» = filas del .sav, asociadas a un ítem o todavía en Conciliación
        "completas": sav["completas"], "completas_asociadas": sav["asociadas"], "completas_sin_asociar": sav["sin_asociar"],
        "contactos_efectivos": sav["completas"] + est.get("rechazo", 0),
        "en_curso": est.get("en_curso", 0),
        "por_franja": por_franja, "por_dia": por_dia, "por_encuestador": por_encuestador,
        "por_disposicion": por_disposicion,
        "encuestadores_lista": [r["encuestador"] for r in conn.execute(
            "SELECT encuestador FROM (SELECT encuestador FROM intento UNION SELECT encuestador FROM sav_fila) x"
            " WHERE encuestador IS NOT NULL ORDER BY 1")],
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
        SELECT e.id, e.codigo AS rut, e.razon_social, e.departamento, ag.llamadas, ag.atendidas, ag.primera, ag.ultima, ag.encuestadores,
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


TIPO_CONTACTO = {"alta": "contacto nuevo", "nombre": "nombre", "cargo": "cargo", "area": "área", "email": "email",
                 "sucursal_id": "sucursal", "telefono": "teléfono", "borrar": "borrado"}


def linea_de_tiempo(conn, empresa_id: int, limite: int = 300, ver_contactos: bool = True) -> list[dict]:
    """Eventos de la empresa, del más nuevo al más viejo. Lo que trajo una misma ingesta del .sav se agrupa
    en un evento desplegable (tipo 'ingesta') con su resumen y sus eventos (F2.4).
    ver_contactos=False (rol de lectura): los nombres de contactos se ocultan."""
    nombre = "c.nombre" if ver_contactos else "'(dato personal oculto)'"
    # La absorbente ve las llamadas de las empresas que absorbió (por ejemplo, una provisoria fusionada, F6.1)
    ids = [empresa_id] + [r["id"] for r in conn.execute(
        "WITH RECURSIVE f AS (SELECT id FROM empresa WHERE fusionada_en = %s"
        " UNION SELECT e.id FROM empresa e JOIN f ON e.fusionada_en = f.id) SELECT id FROM f", (empresa_id,))]
    filas = conn.execute(
        f"""
        WITH contactos AS (SELECT id FROM contacto WHERE empresa_id = %(e)s)
        SELECT * FROM (
          SELECT h.fecha, 'dato' AS tipo,
                 h.campo || ' = ' || coalesce(h.valor, '∅') AS descripcion,
                 h.fuente_tipo || coalesce(' #' || h.fuente_id, '') AS fuente, h.actor,
                 CASE WHEN h.fuente_tipo = 'sala' THEN h.fuente_id END AS ingesta_id, 'dato' AS clase
          FROM empresa_campo_historia h WHERE h.empresa_id = %(e)s
          UNION ALL
          SELECT i.inicio, 'llamada', t.e164 || ' · ' || coalesce(i.disposicion, 'sin disposición')
                 || coalesce(' · ' || i.duracion || ' s', ''), coalesce(i.campania, 'marcador manual'), i.encuestador,
                 NULL, 'llamada'
          FROM intento i JOIN telefono t ON t.id = i.telefono_id WHERE i.empresas && %(ids)s::int[]
          UNION ALL
          SELECT ps.fecha, 'resultado', p.nombre || ': ' || ps.estado
                 || CASE WHEN %(ver)s THEN coalesce(' · respondió ' || ps.respondente, '') ELSE '' END,
                 s.nombre, ps.encuestador,
                 (SELECT sf.ingesta_id FROM sav_fila sf WHERE sf.item_id = ps.item_id AND sf.parte_id = ps.parte_id
                   ORDER BY sf.actualizado DESC LIMIT 1),
                 'resultado_' || ps.estado
          FROM item_parte_estado ps JOIN muestra_item mi ON mi.id = ps.item_id JOIN parte p ON p.id = ps.parte_id
          JOIN estudio s ON s.id = p.estudio_id
          WHERE (mi.empresa_id = %(e)s OR mi.empresa_id IN (SELECT id FROM empresa WHERE fusionada_en = %(e)s))
            AND ps.fecha IS NOT NULL
          UNION ALL
          SELECT vh.fecha, 'teléfono', coalesce(t.e164, t.crudo) || ' → ' || vh.estado, vh.fuente_tipo, vh.actor,
                 CASE WHEN vh.fuente_tipo = 'sala' THEN vh.fuente_id END, 'telefono_' || vh.estado
          FROM telefono_vinculo_historia vh JOIN telefono t ON t.id = vh.telefono_id WHERE vh.empresa_id = %(e)s
          UNION ALL
          SELECT ch.fecha, 'contacto',
                 CASE WHEN ch.campo = 'alta' THEN 'alta de ' || coalesce({nombre}, 'contacto borrado')
                      ELSE coalesce({nombre}, 'contacto') || ': ' || ch.campo || ' = ' || coalesce(ch.valor, '∅') END,
                 ch.fuente_tipo || coalesce(' #' || ch.fuente_id, ''), ch.actor,
                 CASE WHEN ch.fuente_tipo = 'sala' THEN ch.fuente_id END,
                 CASE WHEN ch.campo = 'alta' THEN 'contacto_alta' ELSE 'contacto_edicion' END
          FROM contacto_historia ch LEFT JOIN contacto c ON c.id = ch.contacto_id
          WHERE (ch.empresa_id = %(e)s OR ch.contacto_id IN (SELECT id FROM contactos))
            AND (ch.campo = 'alta' OR ch.campo NOT IN ('cargo','area','email') OR ch.fuente_tipo <> 'sala'
                 OR NOT EXISTS (SELECT 1 FROM contacto_historia a WHERE a.contacto_id = ch.contacto_id AND a.campo = 'alta'
                                AND a.fuente_tipo = ch.fuente_tipo AND a.fuente_id = ch.fuente_id))
          UNION ALL
          SELECT ct.ultima_vez, 'contacto',
                 'se habló con ' || {nombre} || ' al ' || coalesce(t.e164, t.crudo),
                 ct.fuente_tipo || coalesce(' #' || ct.fuente_id, ''), NULL,
                 CASE WHEN ct.fuente_tipo = 'sala' THEN ct.fuente_id END, 'contacto_se_hablo'
          FROM contacto_telefono ct JOIN contacto c ON c.id = ct.contacto_id JOIN telefono t ON t.id = ct.telefono_id
          WHERE ct.contacto_id IN (SELECT id FROM contactos) AND ct.relacion = 'se_hablo'
          UNION ALL
          SELECT coalesce(mi.liberado_fecha, m.sorteada), 'muestra',
                 m.nombre || ' · ' || mi.rol || ' · estrato ' || mi.estrato || CASE WHEN mi.liberado THEN '' ELSE ' (no liberado)' END,
                 'sorteo', m.sorteada_por, NULL, 'muestra'
          FROM muestra_item mi JOIN muestra m ON m.id = mi.muestra_id WHERE mi.empresa_id = %(e)s
          UNION ALL
          SELECT n.fecha, 'no llamar', n.motivo || CASE WHEN n.activo THEN '' ELSE ' (levantado)' END, n.solicitante,
                 n.registrado_por, NULL, 'no_llamar'
          FROM no_llamar n WHERE n.alcance = 'empresa' AND n.objeto_id = %(e)s
        ) x WHERE fecha IS NOT NULL ORDER BY fecha DESC LIMIT %(l)s
        """, {"e": empresa_id, "l": limite, "ver": ver_contactos, "ids": ids}).fetchall()
    ingestas = sorted({f["ingesta_id"] for f in filas if f["ingesta_id"]})
    nombres = {r["id"]: r for r in conn.execute(
        "SELECT g.id, p.nombre AS parte, s.nombre AS estudio FROM sav_ingesta g JOIN parte p ON p.id = g.parte_id"
        " JOIN estudio s ON s.id = p.estudio_id WHERE g.id = ANY(%s)", (ingestas,))} if ingestas else {}
    salida, grupos = [], {}
    for f in filas:
        gid = f["ingesta_id"] if f["ingesta_id"] in nombres else None
        if gid is None:
            salida.append({k: v for k, v in f.items() if k not in ("ingesta_id", "clase")})
            continue
        if gid not in grupos:
            g = nombres[gid]
            grupos[gid] = {"fecha": f["fecha"], "tipo": "ingesta", "ingesta_id": gid, "fuente": f"ingesta .sav #{gid}",
                           "actor": f["actor"], "titulo": f"Ingesta .sav #{gid} ({g['estudio']}, {g['parte']})",
                           "eventos": [], "_clases": []}
            salida.append(grupos[gid])
        grupos[gid]["eventos"].append({k: v for k, v in f.items() if k not in ("ingesta_id", "clase")})
        grupos[gid]["_clases"].append(f["clase"])
    for g in grupos.values():
        g["descripcion"] = g["titulo"] + ": " + _resumen(g.pop("_clases"))
    return salida


def _resumen(clases: list[str]) -> str:
    def n(texto, k):
        return f"{k} {texto[0] if k == 1 else texto[1]}"
    partes = []
    for clase, texto in (("contacto_alta", ("contacto nuevo", "contactos nuevos")),
                         ("contacto_edicion", ("dato de contacto actualizado", "datos de contacto actualizados")),
                         ("telefono_verificado", ("teléfono verificado", "teléfonos verificados")),
                         ("telefono_sin_verificar", ("teléfono nuevo", "teléfonos nuevos")),
                         ("telefono_intermediario", ("teléfono intermediario", "teléfonos intermediarios")),
                         ("telefono_no_corresponde", ("teléfono que no corresponde", "teléfonos que no corresponden")),
                         ("telefono_inexistente", ("teléfono inexistente", "teléfonos inexistentes")),
                         ("contacto_se_hablo", ("contacto–teléfono", "contactos–teléfonos")),
                         ("dato", ("dato de la empresa", "datos de la empresa"))):
        k = clases.count(clase)
        if k:
            partes.append(n(texto, k))
    if "resultado_completa" in clases:
        partes.append("ítem completo")
    return ", ".join(partes) or "sin cambios"
