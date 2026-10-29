"""Estudios, partes, sorteo de muestras y reemplazos (R1.5, R1.6).

El sorteo es reproducible: al sortear se congela un snapshot del marco (empresas
disponibles con su estrato) y se guarda la semilla y la versión de configuración. El
orden dentro de cada estrato es el de sha256("semilla:empresa_id"), que no depende del
orden en que la base devuelve las filas ni de la versión de Postgres o de Python.
"""
import hashlib
import secrets
from collections import Counter, defaultdict

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, config

FILTROS = ("ciiu", "tamano", "departamento", "naturaleza")
ESTRATIFICADORES = ("tamano", "departamento", "naturaleza", "ciiu2", "ciiu1")
SIN_DATO = "(sin dato)"
ESTADOS_PARTE = ("pendiente", "en_curso", "completa", "rechazo", "no_contactable", "fuera_de_marco")


# ─────────────────────────────────────────────────────────────
# Estudios y partes
# ─────────────────────────────────────────────────────────────

def crear_estudio(conn, datos: dict, actor: str) -> dict:
    e = conn.execute(
        "INSERT INTO estudio (nombre, cliente, campo_desde, campo_hasta, creado_por) VALUES (%s,%s,%s,%s,%s) RETURNING *",
        (datos["nombre"], datos.get("cliente"), datos["campo_desde"], datos["campo_hasta"], actor),
    ).fetchone()
    for p in datos.get("partes") or []:
        crear_parte(conn, e["id"], p, actor)
    auditoria.registrar(conn, actor, "estudio.crear", "estudio", e["id"], {"nombre": e["nombre"]})
    return e


def actualizar_estudio(conn, estudio_id: int, datos: dict, actor: str) -> dict:
    e = conn.execute(
        "UPDATE estudio SET nombre = coalesce(%s, nombre), cliente = coalesce(%s, cliente),"
        " campo_desde = coalesce(%s, campo_desde), campo_hasta = coalesce(%s, campo_hasta) WHERE id = %s RETURNING *",
        (datos.get("nombre"), datos.get("cliente"), datos.get("campo_desde"), datos.get("campo_hasta"), estudio_id),
    ).fetchone()
    if e is None:
        raise HTTPException(404, "Estudio inexistente")
    auditoria.registrar(conn, actor, "estudio.editar", "estudio", estudio_id, datos)
    return e


def crear_parte(conn, estudio_id: int, datos: dict, actor: str) -> dict:
    if conn.execute("SELECT 1 FROM estudio WHERE id = %s", (estudio_id,)).fetchone() is None:
        raise HTTPException(404, "Estudio inexistente")
    p = conn.execute(
        "INSERT INTO parte (estudio_id, nombre, survey_id, link_base, respondente_objetivo) VALUES (%s,%s,%s,%s,%s) RETURNING *",
        (estudio_id, datos["nombre"], datos.get("survey_id"), datos.get("link_base"), datos.get("respondente_objetivo")),
    ).fetchone()
    # Los ítems ya liberados de muestras del estudio quedan pendientes en la parte nueva
    conn.execute(
        "INSERT INTO item_parte_estado (item_id, parte_id) SELECT i.id, %s FROM muestra_item i"
        " JOIN muestra m ON m.id = i.muestra_id WHERE m.estudio_id = %s AND i.liberado ON CONFLICT DO NOTHING",
        (p["id"], estudio_id),
    )
    auditoria.registrar(conn, actor, "parte.crear", "parte", p["id"], {"estudio_id": estudio_id, "nombre": p["nombre"]})
    return p


def actualizar_parte(conn, parte_id: int, datos: dict, actor: str) -> dict:
    p = conn.execute(
        "UPDATE parte SET nombre = coalesce(%s, nombre), survey_id = coalesce(%s, survey_id),"
        " link_base = coalesce(%s, link_base), respondente_objetivo = coalesce(%s, respondente_objetivo)"
        " WHERE id = %s RETURNING *",
        (datos.get("nombre"), datos.get("survey_id"), datos.get("link_base"), datos.get("respondente_objetivo"), parte_id),
    ).fetchone()
    if p is None:
        raise HTTPException(404, "Parte inexistente")
    auditoria.registrar(conn, actor, "parte.editar", "parte", parte_id, datos)
    return p


def estudio_detalle(conn, estudio_id: int) -> dict:
    e = conn.execute("SELECT * FROM estudio WHERE id = %s", (estudio_id,)).fetchone()
    if e is None:
        raise HTTPException(404, "Estudio inexistente")
    e["partes"] = conn.execute(
        """SELECT p.*, (p.plantilla_mapeo IS NOT NULL) AS tiene_plantilla,
                  (SELECT json_object_agg(estado, n) FROM (SELECT estado, count(*) AS n FROM item_parte_estado
                    WHERE parte_id = p.id GROUP BY estado) x) AS estados
           FROM parte p WHERE p.estudio_id = %s ORDER BY p.id""", (estudio_id,)).fetchall()
    e["muestras"] = conn.execute(
        "SELECT id, nombre, estado, semilla, config_version, sorteada, (SELECT count(*) FROM muestra_item WHERE muestra_id = m.id) AS n_items"
        " FROM muestra m WHERE estudio_id = %s ORDER BY id", (estudio_id,)).fetchall()
    return e


# ─────────────────────────────────────────────────────────────
# Sorteo
# ─────────────────────────────────────────────────────────────

def clave_orden(semilla: int, empresa_id: int) -> str:
    return hashlib.sha256(f"{semilla}:{empresa_id}".encode()).hexdigest()


def estrato_de(fila: dict, por: list[str]) -> str:
    if not por:
        return "Total"
    partes = []
    for campo in por:
        if campo == "ciiu2":
            v = (fila.get("ciiu") or "")[:2]
        elif campo == "ciiu1":
            v = (fila.get("ciiu") or "")[:1]
        else:
            v = fila.get(campo)
        partes.append(str(v) if v not in (None, "") else SIN_DATO)
    return " | ".join(partes)


def sortear_snapshot(marco: list[tuple[int, str]], semilla: int, definicion: dict[str, tuple[int, int]]):
    """Función pura del sorteo. marco: [(empresa_id, estrato)].
    definicion: {estrato: (n_titulares, n_reemplazos)}. Devuelve [(empresa_id, estrato, rol, orden)]."""
    por_estrato = defaultdict(list)
    for empresa_id, estrato in marco:
        por_estrato[estrato].append(empresa_id)
    salida = []
    for estrato in sorted(definicion):
        n, r = definicion[estrato]
        ordenados = sorted(por_estrato.get(estrato, []), key=lambda eid: (clave_orden(semilla, eid), eid))
        for k, eid in enumerate(ordenados[: n + r]):
            salida.append((eid, estrato, "titular" if k < n else "reemplazo", k + 1))
    return salida


def _validar_criterios(c: dict) -> dict:
    c = dict(c or {})
    filtros = {k: v for k, v in (c.get("filtros") or {}).items() if v}
    for k in filtros:
        if k not in FILTROS:
            raise HTTPException(422, f"Filtro desconocido: {k}")
    por = c.get("estratificar_por") or []
    for k in por:
        if k not in ESTRATIFICADORES:
            raise HTTPException(422, f"No se puede estratificar por {k}")
    estratos = c.get("estratos") or []
    for e in estratos:
        if int(e.get("n", 0)) < 0 or int(e.get("reemplazos", 0)) < 0:
            raise HTTPException(422, "Tamaños y reemplazos no pueden ser negativos")
    if not estratos and c.get("n_por_estrato") is None:
        raise HTTPException(422, "Indicá el tamaño por estrato (lista de estratos o n_por_estrato)")
    return {"filtros": filtros, "estratificar_por": por, "estratos": estratos,
            "n_por_estrato": c.get("n_por_estrato"), "reemplazos_por_estrato": c.get("reemplazos_por_estrato", 0)}


def crear_muestra(conn, estudio_id: int, nombre: str, criterios: dict, actor: str) -> dict:
    if conn.execute("SELECT 1 FROM estudio WHERE id = %s", (estudio_id,)).fetchone() is None:
        raise HTTPException(404, "Estudio inexistente")
    criterios = _validar_criterios(criterios)
    m = conn.execute("INSERT INTO muestra (estudio_id, nombre, criterios, creado_por) VALUES (%s,%s,%s,%s) RETURNING *",
                     (estudio_id, nombre, Jsonb(criterios), actor)).fetchone()
    auditoria.registrar(conn, actor, "muestra.crear", "muestra", m["id"], {"criterios": criterios})
    return m


def _universo(conn, filtros: dict) -> list[dict]:
    where, args = ["TRUE"], []
    if filtros.get("ciiu"):
        where.append("(" + " OR ".join(["e.ciiu LIKE %s"] * len(filtros["ciiu"])) + ")")
        args += [f"{x}%" for x in filtros["ciiu"]]
    if filtros.get("tamano"):
        where.append("e.tamano = ANY(%s)")
        args.append(filtros["tamano"])
    if filtros.get("departamento"):
        where.append("e.departamento = ANY(%s)")
        args.append(filtros["departamento"])
    if filtros.get("naturaleza"):
        where.append("n.codigo = ANY(%s)")
        args.append(filtros["naturaleza"])
    return conn.execute(
        "SELECT e.id, e.rut, e.ciiu, e.tamano, e.departamento, n.codigo AS naturaleza FROM empresa e"
        " LEFT JOIN naturaleza_juridica n ON n.id = e.naturaleza_id WHERE " + " AND ".join(where),
        args).fetchall()


def previsualizar_marco(conn, criterios: dict) -> dict:
    """Cuántas empresas quedan en cada estrato y cuántas excluye cada regla, sin sortear."""
    criterios = _validar_criterios({**criterios, "n_por_estrato": criterios.get("n_por_estrato", 0)})
    _, cfg = config.vigente(conn)
    universo = _universo(conn, criterios["filtros"])
    bloqueos = _bloqueos(conn, cfg, None)
    excl, marco = _aplicar_bloqueos(universo, bloqueos)
    por_estrato = Counter(estrato_de(f, criterios["estratificar_por"]) for f in marco)
    return {"universo": len(universo), "marco": len(marco), "exclusiones": excl,
            "estratos": [{"estrato": k, "disponibles": v} for k, v in sorted(por_estrato.items())]}


def _bloqueos(conn, cfg, muestra_id):
    b = defaultdict(set)
    for r in conn.execute("SELECT empresa_id, regla FROM bloqueos(%s, %s)", (Jsonb(cfg), muestra_id)):
        b[r["empresa_id"]].add(r["regla"])
    return b


def _aplicar_bloqueos(universo, bloqueos):
    excl = Counter()
    marco = []
    for f in universo:
        reglas = bloqueos.get(f["id"])
        if reglas:
            for r in reglas:
                excl[r] += 1
            excl["total_excluidas"] += 1
        else:
            marco.append(f)
    return dict(excl), marco


def sortear(conn, muestra_id: int, actor: str, semilla: int | None = None) -> dict:
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('sorteo_muestras'))")
    m = conn.execute("SELECT * FROM muestra WHERE id = %s FOR UPDATE", (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Muestra inexistente")
    if m["estado"] != "borrador":
        raise HTTPException(409, "La muestra ya fue sorteada")
    criterios = m["criterios"]
    version, cfg = config.vigente(conn)
    universo = _universo(conn, criterios["filtros"])
    excl, marco_filas = _aplicar_bloqueos(universo, _bloqueos(conn, cfg, muestra_id))
    marco = [(f["id"], estrato_de(f, criterios["estratificar_por"])) for f in marco_filas]

    snapshot_id = conn.execute(
        "INSERT INTO marco_snapshot (config_version, criterios, n) VALUES (%s,%s,%s) RETURNING id",
        (version, Jsonb(criterios), len(marco))).fetchone()["id"]
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO marco_snapshot_item (snapshot_id, empresa_id, estrato) VALUES (%s,%s,%s)",
                        [(snapshot_id, eid, est) for eid, est in marco])

    definicion = definicion_estratos(criterios, {e for _, e in marco})
    semilla = semilla if semilla is not None else secrets.randbits(62)
    sorteados = sortear_snapshot(marco, semilla, definicion)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO muestra_item (muestra_id, empresa_id, estrato, rol, orden, liberado, liberado_por, liberado_motivo, liberado_fecha)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s, CASE WHEN %s THEN now() END)",
            [(muestra_id, eid, est, rol, orden, rol == "titular", actor if rol == "titular" else None,
              "titular" if rol == "titular" else None, rol == "titular") for eid, est, rol, orden in sorteados])
    _pendientes_partes(conn, muestra_id)

    disponibles = Counter(e for _, e in marco)
    avisos, por_estrato = [], []
    for est in sorted(definicion):
        n, r = definicion[est]
        d = disponibles.get(est, 0)
        por_estrato.append({"estrato": est, "pedido": n, "reemplazos": r, "disponibles": d,
                            "titulares": min(n, d), "reemplazos_sorteados": max(0, min(r, d - n))})
        if d < n:
            avisos.append(f"El estrato {est} no alcanza: pidió {n} y hay {d} disponibles")
        elif d < n + r:
            avisos.append(f"El estrato {est} tiene solo {d - n} reemplazos de {r} pedidos")
    sin_pedir = sorted(set(disponibles) - set(definicion))
    resultado = {"universo": len(universo), "marco": len(marco), "exclusiones": excl, "estratos": por_estrato,
                 "avisos": avisos, "estratos_no_pedidos": sin_pedir}
    conn.execute(
        "UPDATE muestra SET estado = 'activa', semilla = %s, config_version = %s, snapshot_id = %s, resultado = %s,"
        " sorteada_por = %s, sorteada = now() WHERE id = %s",
        (semilla, version, snapshot_id, Jsonb(resultado), actor, muestra_id))
    auditoria.registrar(conn, actor, "muestra.sortear", "muestra", muestra_id,
                        {"semilla": semilla, "config_version": version, "snapshot_id": snapshot_id,
                         "n_items": len(sorteados), "exclusiones": excl})
    return {"semilla": semilla, "config_version": version, "snapshot_id": snapshot_id, **resultado}


def definicion_estratos(criterios: dict, estratos_marco: set[str]) -> dict[str, tuple[int, int]]:
    if criterios.get("estratos"):
        return {e["estrato"]: (int(e.get("n", 0)), int(e.get("reemplazos", 0))) for e in criterios["estratos"]}
    n = int(criterios.get("n_por_estrato") or 0)
    r = int(criterios.get("reemplazos_por_estrato") or 0)
    return {e: (n, r) for e in (estratos_marco or {"Total"})}


def verificar(conn, muestra_id: int) -> dict:
    """Re-ejecuta el sorteo con semilla, snapshot y configuración guardados y lo compara."""
    m = conn.execute("SELECT * FROM muestra WHERE id = %s", (muestra_id,)).fetchone()
    if m is None or m["snapshot_id"] is None:
        raise HTTPException(409, "La muestra no está sorteada")
    marco = [(r["empresa_id"], r["estrato"]) for r in conn.execute(
        "SELECT empresa_id, estrato FROM marco_snapshot_item WHERE snapshot_id = %s", (m["snapshot_id"],))]
    definicion = definicion_estratos(m["criterios"], {e for _, e in marco})
    nuevo = sortear_snapshot(marco, m["semilla"], definicion)
    guardado = [(r["empresa_id"], r["estrato"], r["rol"], r["orden"]) for r in conn.execute(
        "SELECT empresa_id, estrato, rol, orden FROM muestra_item WHERE muestra_id = %s ORDER BY estrato, orden",
        (muestra_id,))]
    nuevo_ord = sorted(nuevo, key=lambda x: (x[1], x[3]))
    return {"reproducible": nuevo_ord == guardado, "items": len(guardado), "semilla": m["semilla"],
            "snapshot_id": m["snapshot_id"], "config_version": m["config_version"]}


def _pendientes_partes(conn, muestra_id: int):
    conn.execute(
        "INSERT INTO item_parte_estado (item_id, parte_id) SELECT i.id, p.id FROM muestra_item i"
        " JOIN muestra m ON m.id = i.muestra_id JOIN parte p ON p.estudio_id = m.estudio_id"
        " WHERE i.muestra_id = %s AND i.liberado ON CONFLICT DO NOTHING", (muestra_id,))


def liberar(conn, muestra_id: int, estrato: str, cantidad: int, motivo: str, actor: str) -> dict:
    if cantidad < 1:
        raise HTTPException(422, "La cantidad tiene que ser al menos 1")
    if not motivo or not motivo.strip():
        raise HTTPException(422, "Indicá el motivo de la liberación")
    m = conn.execute("SELECT * FROM muestra WHERE id = %s FOR UPDATE", (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Muestra inexistente")
    if m["estado"] != "activa":
        raise HTTPException(409, "Solo se liberan reemplazos de una muestra activa")
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM muestra_item WHERE muestra_id = %s AND estrato = %s AND rol = 'reemplazo' AND NOT liberado"
        " ORDER BY orden LIMIT %s", (muestra_id, estrato, cantidad))]
    if not ids:
        raise HTTPException(409, f"No quedan reemplazos sin liberar en el estrato {estrato}")
    conn.execute("UPDATE muestra_item SET liberado = true, liberado_por = %s, liberado_motivo = %s, liberado_fecha = now()"
                 " WHERE id = ANY(%s)", (actor, motivo, ids))
    _pendientes_partes(conn, muestra_id)
    auditoria.registrar(conn, actor, "muestra.liberar_reemplazos", "muestra", muestra_id,
                        {"estrato": estrato, "items": ids, "motivo": motivo})
    return {"liberados": len(ids), "items": ids, "pedidos": cantidad}


def cerrar(conn, muestra_id: int, actor: str) -> dict:
    m = conn.execute("UPDATE muestra SET estado = 'cerrada' WHERE id = %s AND estado = 'activa' RETURNING id",
                     (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(409, "Solo se cierra una muestra activa")
    auditoria.registrar(conn, actor, "muestra.cerrar", "muestra", muestra_id)
    return {"id": muestra_id, "estado": "cerrada"}


def detalle(conn, muestra_id: int) -> dict:
    m = conn.execute("SELECT m.*, e.nombre AS estudio_nombre FROM muestra m JOIN estudio e ON e.id = m.estudio_id"
                     " WHERE m.id = %s", (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Muestra inexistente")
    m["partes"] = conn.execute("SELECT id, nombre FROM parte WHERE estudio_id = %s ORDER BY id", (m["estudio_id"],)).fetchall()
    m["avance"] = conn.execute(
        """
        SELECT i.estrato,
               count(*) FILTER (WHERE i.rol = 'titular') AS titulares,
               count(*) FILTER (WHERE i.rol = 'reemplazo') AS reemplazos,
               count(*) FILTER (WHERE i.rol = 'reemplazo' AND i.liberado) AS reemplazos_liberados,
               count(*) FILTER (WHERE i.liberado) AS liberados,
               count(*) FILTER (WHERE i.liberado AND EXISTS (SELECT 1 FROM intento t WHERE t.item_id = i.id)) AS llamados,
               count(*) FILTER (WHERE ps.completa) AS completas,
               count(*) FILTER (WHERE ps.rechazo) AS rechazos,
               count(*) FILTER (WHERE ps.contactado) AS contactados,
               count(*) FILTER (WHERE ps.fuera) AS fuera_de_marco
        FROM muestra_item i
        LEFT JOIN LATERAL (
          SELECT bool_or(estado = 'completa') AS completa, bool_or(estado = 'rechazo') AS rechazo,
                 bool_or(estado IN ('completa','rechazo','en_curso')) AS contactado,
                 bool_or(estado = 'fuera_de_marco') AS fuera
          FROM item_parte_estado WHERE item_id = i.id) ps ON true
        WHERE i.muestra_id = %s
        GROUP BY i.estrato ORDER BY i.estrato
        """, (muestra_id,)).fetchall()
    return m


def items(conn, muestra_id: int, estrato: str | None = None, limite: int = 500) -> list[dict]:
    return conn.execute(
        """
        SELECT i.id, i.estrato, i.rol, i.orden, i.liberado, i.liberado_por, i.liberado_motivo, i.liberado_fecha,
               e.rut, e.razon_social, e.departamento, e.tamano,
               (SELECT count(*) FROM intento t WHERE t.item_id = i.id) AS intentos,
               (SELECT json_object_agg(p.nombre, ps.estado) FROM item_parte_estado ps JOIN parte p ON p.id = ps.parte_id
                 WHERE ps.item_id = i.id) AS estados
        FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id
        WHERE i.muestra_id = %s AND (%s::text IS NULL OR i.estrato = %s)
        ORDER BY i.estrato, i.orden LIMIT %s
        """, (muestra_id, estrato, estrato, limite)).fetchall()
