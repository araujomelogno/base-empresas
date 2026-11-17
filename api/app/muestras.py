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

from . import auditoria, catalogos, config, criterios as crit

# Filtros y estratos: ver criterios.py (R4: todo dato de la empresa sirve)
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
                    WHERE parte_id = p.id GROUP BY estado) x) AS estados,
                  (SELECT count(*) FROM sav_fila s WHERE s.parte_id = p.id) AS completas_sav,
                  (SELECT count(*) FROM sav_fila s WHERE s.parte_id = p.id AND s.item_id IS NULL) AS completas_sin_asociar
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


def _validar_criterios(conn, c: dict, avisos: list | None = None, tamanos: bool = True) -> dict:
    """R4: todo dato de la empresa sirve como filtro y estrato (criterios.validar)."""
    return crit.validar(conn, c, avisos, tamanos)


def crear_muestra(conn, estudio_id: int, nombre: str, criterios: dict, actor: str,
                  template_id: int | None = None) -> dict:
    if conn.execute("SELECT 1 FROM estudio WHERE id = %s", (estudio_id,)).fetchone() is None:
        raise HTTPException(404, "Estudio inexistente")
    criterios = _validar_criterios(conn, criterios)
    if template_id is not None:  # R2: la muestra guarda su propia copia de los criterios y de dónde salió
        if conn.execute("UPDATE muestra_template SET veces_usado = veces_usado + 1 WHERE id = %s RETURNING id",
                        (template_id,)).fetchone() is None:
            raise HTTPException(404, "Template inexistente")
    m = conn.execute("INSERT INTO muestra (estudio_id, nombre, criterios, creado_por, template_id) VALUES (%s,%s,%s,%s,%s)"
                     " RETURNING *", (estudio_id, nombre, Jsonb(criterios), actor, template_id)).fetchone()
    auditoria.registrar(conn, actor, "muestra.crear", "muestra", m["id"], {"criterios": criterios, "template_id": template_id})
    return m


def _universo(conn, criterios: dict, defs: dict | None = None) -> list[dict]:
    """Empresas que cumplen los filtros, con una columna "e:<dato>" por cada dato de estratificación."""
    defs = defs or crit.definiciones(conn)
    q = crit.Consulta(defs)
    filtros = criterios.get("filtros") or {}
    where, args = ["TRUE"], []
    if not criterios.get("incluir_provisoria"):
        where.append("e.base = 'definitiva'")
    # Formato anterior de filtros (listas y prefijos de CIIU)
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
    for campo, spec in (criterios.get("campos") or {}).items():
        where.append(q.condicion(campo, spec, args))
    for clave, spec in (criterios.get("atributos") or {}).items():
        where.append(q.condicion(crit.PREFIJO + clave, spec, args))
    cols = "".join(f', {q.expr(k)} AS "e:{k}"' for k in criterios.get("estratificar_por") or [])
    return conn.execute(
        f"SELECT e.id, e.rut, e.ciiu, e.tamano, e.departamento, n.codigo AS naturaleza{cols} FROM empresa e"
        " LEFT JOIN naturaleza_juridica n ON n.id = e.naturaleza_id " + " ".join(q.joins.values())
        + " WHERE " + " AND ".join(where), args).fetchall()


def _con_telefono(conn) -> set[int]:
    return {r["empresa_id"] for r in conn.execute("SELECT DISTINCT empresa_id FROM v_vinculo_discable")}


def _sin_telefono_permitido(criterios: dict, bloqueos: dict) -> None:
    """R3: con «Incluir empresas sin teléfono discable» esa regla no se aplica a esta muestra (las demás sí)."""
    if not criterios.get("incluir_sin_telefono"):
        return
    for eid in list(bloqueos):
        bloqueos[eid].discard("sin_telefono_discable")
        if not bloqueos[eid]:
            del bloqueos[eid]


def _filtro_origen(conn, universo: list[dict], origenes: list[str], bloqueos: dict) -> None:
    """Regla del filtro de origen: solo empresas con algún teléfono discable de esos orígenes."""
    if not origenes:
        return
    con = {r["empresa_id"] for r in conn.execute(
        "SELECT DISTINCT d.empresa_id FROM v_vinculo_discable d JOIN telefono_vinculo_origen x ON x.vinculo_id = d.vinculo_id"
        " JOIN origen_telefono o ON o.id = x.origen_id WHERE o.codigo = ANY(%s)", (origenes,))}
    for f in universo:
        if f["id"] not in con:
            bloqueos[f["id"]].add("filtro_origen")


def previsualizar_marco(conn, criterios: dict, avisos: list | None = None) -> dict:
    """Cuántas empresas quedan en cada estrato y cuántas excluye cada regla, sin sortear.
    avisos (aplicar un template): lo que ya no existe se saca con aviso en lugar de rechazar."""
    criterios = _validar_criterios(conn, criterios, avisos, tamanos=False)
    _, cfg = config.vigente(conn)
    defs = crit.definiciones(conn)
    universo = _universo(conn, criterios, defs)
    bloqueos = _bloqueos(conn, cfg, None)
    _sin_telefono_permitido(criterios, bloqueos)
    _filtro_origen(conn, universo, criterios["origenes"], bloqueos)
    excl, marco = _aplicar_bloqueos(universo, bloqueos)
    etiq = crit.etiquetas(marco, criterios, defs)
    con_tel = _con_telefono(conn)
    por_estrato, sin_tel = Counter(etiq), Counter(e for f, e in zip(marco, etiq) if f["id"] not in con_tel)
    return {"universo": len(universo), "marco": len(marco), "exclusiones": excl,
            "estratos": [{"estrato": k, "disponibles": por_estrato[k], "sin_telefono": sin_tel.get(k, 0)}
                         for k in sorted(por_estrato, key=crit.orden_natural)],
            "sin_telefono": sum(sin_tel.values()), "avisos": crit.avisos_estratos(marco, criterios, defs, len(por_estrato)),
            "regla_sin_telefono": bool((cfg.get("reglas_disponibilidad") or {}).get("sin_telefono_discable", True)),
            "criterios": criterios}


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
    defs = crit.definiciones(conn)
    universo = _universo(conn, criterios, defs)
    bloqueos = _bloqueos(conn, cfg, muestra_id)
    _sin_telefono_permitido(criterios, bloqueos)
    _filtro_origen(conn, universo, criterios.get("origenes") or [], bloqueos)
    excl, marco_filas = _aplicar_bloqueos(universo, bloqueos)
    # El estrato de cada empresa se calcula ahora y se congela en el snapshot (R4: tramos, «Otros», textos)
    marco = list(zip([f["id"] for f in marco_filas], crit.etiquetas(marco_filas, criterios, defs)))

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
    con_tel = _con_telefono(conn)
    sin_tel = Counter(est for eid, est, _, _ in sorteados if eid not in con_tel)
    avisos, por_estrato = [], []
    for est in sorted(definicion, key=crit.orden_natural):
        n, r = definicion[est]
        d = disponibles.get(est, 0)
        por_estrato.append({"estrato": est, "pedido": n, "reemplazos": r, "disponibles": d,
                            "titulares": min(n, d), "reemplazos_sorteados": max(0, min(r, d - n)),
                            "sin_telefono": sin_tel.get(est, 0)})
        if d < n:
            avisos.append(f"El estrato {est} no alcanza: pidió {n} y hay {d} disponibles")
        elif d < n + r:
            avisos.append(f"El estrato {est} tiene solo {d - n} reemplazos de {r} pedidos")
    sin_pedir = sorted(set(disponibles) - set(definicion))
    resultado = {"universo": len(universo), "marco": len(marco), "exclusiones": excl, "estratos": por_estrato,
                 "avisos": avisos, "estratos_no_pedidos": sin_pedir, "sin_telefono": sum(sin_tel.values()),
                 "incluir_sin_telefono": bool(criterios.get("incluir_sin_telefono"))}
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


def items_borrados(conn, muestra_id: int) -> list[dict]:
    """Ítems que se fueron con un borrado de empresa o de carga después del sorteo (V1)."""
    return conn.execute(
        "SELECT b.item_id, b.empresa_id, b.estrato, b.rol, b.orden, b.accion, b.borrado_por, b.fecha, b.auditoria_id,"
        " CASE WHEN b.accion = 'empresa.borrar' THEN a.objeto_id END AS rut,"
        " CASE WHEN b.accion = 'carga.borrar' THEN a.objeto_id END AS carga_id"
        " FROM muestra_item_borrado b LEFT JOIN auditoria a ON a.id = b.auditoria_id"
        " WHERE b.muestra_id = %s ORDER BY b.estrato, b.orden", (muestra_id,)).fetchall()


def verificar(conn, muestra_id: int) -> dict:
    """Re-ejecuta el sorteo con semilla, snapshot y configuración guardados y lo compara.

    El marco congelado no se toca nunca, así que el re-sorteo se compara contra los ítems que
    quedan más los que se borraron después (muestra_item_borrado). Resultados:
    reproducible · reproducible_con_borrados · no_coincide · no_verificable (el snapshot perdió
    filas con un borrado anterior a que el sistema los registrara)."""
    m = conn.execute("SELECT m.*, s.n AS snapshot_n FROM muestra m LEFT JOIN marco_snapshot s ON s.id = m.snapshot_id"
                     " WHERE m.id = %s", (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Muestra inexistente")
    if m["snapshot_id"] is None:
        raise HTTPException(409, "La muestra no está sorteada")
    marco = [(r["empresa_id"], r["estrato"]) for r in conn.execute(
        "SELECT empresa_id, estrato FROM marco_snapshot_item WHERE snapshot_id = %s", (m["snapshot_id"],))]
    borrados = items_borrados(conn, muestra_id)
    base = {"semilla": m["semilla"], "snapshot_id": m["snapshot_id"], "config_version": m["config_version"],
            "items_borrados": borrados, "snapshot_incompleto": len(marco) < m["snapshot_n"]}
    guardado = [(r["empresa_id"], r["estrato"], r["rol"], r["orden"]) for r in conn.execute(
        "SELECT empresa_id, estrato, rol, orden FROM muestra_item WHERE muestra_id = %s", (muestra_id,))]
    base["items"] = len(guardado)
    if base["snapshot_incompleto"]:
        return {**base, "reproducible": False, "resultado": "no_verificable"}
    definicion = definicion_estratos(m["criterios"], {e for _, e in marco})
    nuevo = sorted(sortear_snapshot(marco, m["semilla"], definicion), key=lambda x: (x[1], x[3]))
    completo = sorted(guardado + [(b["empresa_id"], b["estrato"], b["rol"], b["orden"]) for b in borrados],
                      key=lambda x: (x[1], x[3]))
    ok = nuevo == completo
    resultado = "no_coincide" if not ok else "reproducible_con_borrados" if borrados else "reproducible"
    return {**base, "reproducible": ok, "resultado": resultado}


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
    m["exportacion"] = opciones_exportacion(m)
    m["contactos_por_empresa_csv"] = int(config.vigente(conn)[1].get("contactos_por_empresa_csv", 3))
    m["n_items_borrados"] = conn.execute("SELECT count(*) AS n FROM muestra_item_borrado WHERE muestra_id = %s",
                                         (muestra_id,)).fetchone()["n"]
    m["partes"] = conn.execute("SELECT id, nombre FROM parte WHERE estudio_id = %s ORDER BY id", (m["estudio_id"],)).fetchall()
    # F1.1: un «Borrar muestra» que quedó en error o cancelado se avisa en el detalle
    m["borrado_fallido"] = conn.execute(
        "SELECT id, estado, error, creado, terminado FROM tarea WHERE tipo = 'muestra.borrar'"
        " AND (payload->>'borrar_muestra_id')::int = %s ORDER BY id DESC LIMIT 1", (muestra_id,)).fetchone()
    if m["borrado_fallido"] and m["borrado_fallido"]["estado"] not in ("error", "cancelada"):
        m["borrado_fallido"] = None
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


CAMPOS_CONTACTO_CSV = ("nombre", "cargo", "area", "email", "telefonos")
NUMEROS = ("discables", "verificados")


def opciones_exportacion(m: dict) -> dict:
    """Qué incluir al exportar (C8 y F5.1). Por defecto, todo: los atributos se guardan como excluidos, así un
    atributo nuevo entra solo. «numeros»: todos los discables (verificados y sin verificar, como siempre) o solo
    los verificados."""
    e = m.get("exportacion") or {}
    return {"origenes": e.get("origenes") or [], "orden": e.get("orden") or "prioridad",
            "numeros": e.get("numeros") if e.get("numeros") in NUMEROS else "discables",
            "atributos_excluidos": e.get("atributos_excluidos") or [],
            "contactos": e.get("contactos", True) is not False,
            "contacto_campos": [c for c in (e.get("contacto_campos") or CAMPOS_CONTACTO_CSV) if c in CAMPOS_CONTACTO_CSV],
            "atributos_contacto_excluidos": e.get("atributos_contacto_excluidos") or []}


def guardar_exportacion(conn, muestra_id: int, datos: dict, actor: str) -> dict:
    """Orígenes, orden de los teléfonos (C8) y qué incluir (F5.1). Queda guardado en la muestra."""
    m = conn.execute("SELECT * FROM muestra WHERE id = %s FOR UPDATE", (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Muestra inexistente")
    antes = opciones_exportacion(m)
    datos = {**antes, **{k: v for k, v in datos.items() if v is not None}}
    orden = datos.get("orden") or "prioridad"
    if orden not in ("prioridad", "verificados"):
        raise HTTPException(422, "orden: prioridad | verificados")
    if datos.get("numeros") not in NUMEROS:
        raise HTTPException(422, "numeros: discables | verificados")
    origenes = sorted({o for o in (datos.get("origenes") or []) if o})
    conocidos = {o["codigo"] for o in catalogos.origenes(conn)}
    if set(origenes) - conocidos:
        raise HTTPException(422, f"Orígenes de teléfono desconocidos: {', '.join(sorted(set(origenes) - conocidos))}")
    claves = {a["clave"]: a["ambito"] for a in catalogos.atributos(conn)}
    for k, ambito in (("atributos_excluidos", "empresa"), ("atributos_contacto_excluidos", "contacto")):
        malos = [c for c in datos.get(k) or [] if claves.get(c) != ambito]
        if malos:
            raise HTTPException(422, f"Atributos de {ambito} desconocidos: {', '.join(malos)}")
    campos = [c for c in CAMPOS_CONTACTO_CSV if c in (datos.get("contacto_campos") or [])]
    nuevo = {"origenes": origenes, "orden": orden, "numeros": datos["numeros"],
             "atributos_excluidos": sorted(set(datos.get("atributos_excluidos") or [])),
             "contactos": bool(datos.get("contactos")), "contacto_campos": campos or list(CAMPOS_CONTACTO_CSV),
             "atributos_contacto_excluidos": sorted(set(datos.get("atributos_contacto_excluidos") or []))}
    if nuevo != antes:
        conn.execute("UPDATE muestra SET exportacion = %s WHERE id = %s", (Jsonb(nuevo), muestra_id))
        auditoria.registrar(conn, actor, "muestra.exportacion", "muestra", muestra_id, {"antes": antes, "despues": nuevo})
    return nuevo


POR_PAGINA = 50


def items(conn, muestra_id: int, estrato: str | None = None, rol: str | None = None, liberado: bool | None = None,
          parte_id: int | None = None, estado: str | None = None, q: str | None = None,
          pagina: int = 1, por_pagina: int = POR_PAGINA, sin_telefono: bool | None = None) -> dict:
    """«Empresas de la muestra», paginada del lado del servidor (F1.3).
    estado se mira en la parte elegida (o en cualquiera); «pendiente» incluye a los ítems sin estado en esa parte.
    q busca por RUT, razón social o EC_ID_ITEM (el id del ítem, con o sin «#»)."""
    pagina, por_pagina = max(1, pagina), min(max(1, por_pagina), 500)
    q = (q or "").strip() or None
    digitos = q.lstrip("#").strip() if q else None
    p = {"sin_tel": sin_telefono, "m": muestra_id, "estrato": estrato or None, "rol": rol or None, "liberado": liberado, "parte": parte_id,
         "estado": estado or None, "q": q, "q_like": f"%{q}%" if q else None,
         "rut": "".join(ch for ch in q if ch.isdigit()) if q else None,
         "item": int(digitos) if digitos and digitos.isdigit() and len(digitos) <= 9 else None}
    where = """
        WHERE i.muestra_id = %(m)s
          AND (%(estrato)s::text IS NULL OR i.estrato = %(estrato)s)
          AND (%(rol)s::text IS NULL OR i.rol = %(rol)s)
          AND (%(liberado)s::bool IS NULL OR i.liberado = %(liberado)s)
          AND (%(sin_tel)s::bool IS NULL OR %(sin_tel)s = NOT EXISTS (
                 SELECT 1 FROM v_vinculo_discable d WHERE d.empresa_id = i.empresa_id))
          AND (%(estado)s::text IS NULL
               OR EXISTS (SELECT 1 FROM item_parte_estado ps WHERE ps.item_id = i.id AND ps.estado = %(estado)s
                          AND (%(parte)s::int IS NULL OR ps.parte_id = %(parte)s))
               OR (%(estado)s = 'pendiente' AND NOT EXISTS (
                     SELECT 1 FROM item_parte_estado ps WHERE ps.item_id = i.id
                     AND (%(parte)s::int IS NULL OR ps.parte_id = %(parte)s))))
          AND (%(q)s::text IS NULL OR e.razon_social ILIKE %(q_like)s
               OR (%(rut)s <> '' AND e.rut LIKE %(rut)s || '%%') OR i.id = %(item)s OR e.codigo = upper(%(q)s))"""
    total = conn.execute(f"SELECT count(*) AS n FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id {where}",
                         p).fetchone()["n"]
    filas = conn.execute(
        f"""
        SELECT i.id, i.estrato, i.rol, i.orden, i.liberado, i.liberado_por, i.liberado_motivo, i.liberado_fecha,
               e.codigo AS rut, e.base, e.razon_social, e.departamento, e.tamano,
               NOT EXISTS (SELECT 1 FROM v_vinculo_discable d WHERE d.empresa_id = i.empresa_id) AS sin_telefono,
               (SELECT count(*) FROM intento t WHERE t.item_id = i.id) AS intentos,
               (SELECT json_object_agg(p.nombre, ps.estado) FROM item_parte_estado ps JOIN parte p ON p.id = ps.parte_id
                 WHERE ps.item_id = i.id) AS estados
        FROM muestra_item i JOIN empresa e ON e.id = i.empresa_id
        {where}
        ORDER BY i.estrato, i.orden LIMIT %(lim)s OFFSET %(off)s
        """, {**p, "lim": por_pagina, "off": (pagina - 1) * por_pagina}).fetchall()
    return {"total": total, "pagina": pagina, "por_pagina": por_pagina,
            "paginas": max(1, -(-total // por_pagina)), "items": filas}
