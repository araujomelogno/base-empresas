"""Indicadores de actividad y línea de tiempo de la empresa (R1.11)."""


def _filtros(f: dict, alias_intento="i"):
    w, a = ["TRUE"], []
    if f.get("estudio_id"):
        w.append(f"{alias_intento}.item_id IN (SELECT mi.id FROM muestra_item mi JOIN muestra m ON m.id = mi.muestra_id"
                 " WHERE m.estudio_id = %s)")
        a.append(f["estudio_id"])
    if f.get("muestra_id"):
        w.append(f"{alias_intento}.item_id IN (SELECT id FROM muestra_item WHERE muestra_id = %s)")
        a.append(f["muestra_id"])
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
