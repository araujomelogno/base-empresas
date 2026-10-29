"""Carga de bases y reglas de fusión (R1.3).

Flujo: analizar (columnas y mapeo sugerido) → crear (preview con conteos, sin escribir) →
confirmar (corre en diferido) → deshacer (mientras ninguna empresa haya entrado a una muestra).

El preview corre exactamente el mismo código que la confirmación dentro de un savepoint
que se descarta, así los conteos del preview son los que después se aplican.
"""
import re
from collections import Counter

import psycopg
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, config, empresas, intermediarios, lectores, rut as rutmod, storage, tareas
from . import telefonos as telmod
from .util import dominio, razon_normalizada, sin_tildes, texto

CAMPOS_MAPEO = (
    "rut", "razon_social", "fantasia", "naturaleza", "ciiu", "tamano", "departamento", "localidad",
    "direccion", "web", "email", "estado", "telefonos",
    "contacto_nombre", "contacto_cargo", "contacto_area", "contacto_email", "contacto_telefono",
    "sucursal_direccion", "sucursal_departamento", "sucursal_localidad",
)

SINONIMOS = {
    "rut": ["rut", "ruc", "nro rut", "numero rut", "rut empresa", "n rut", "num rut", "ec rut"],
    "razon_social": ["razon social", "razon", "denominacion", "nombre empresa", "empresa", "nombre"],
    "fantasia": ["nombre fantasia", "fantasia", "nombre comercial"],
    "naturaleza": ["naturaleza", "naturaleza juridica", "forma juridica", "tipo sociedad", "tipo societario"],
    "ciiu": ["ciiu", "rubro", "actividad", "codigo actividad", "giro"],
    "tamano": ["tamano", "tamano empresa", "tramo", "tramo personal", "tamanio"],
    "departamento": ["departamento", "depto", "dpto"],
    "localidad": ["localidad", "ciudad", "barrio"],
    "direccion": ["direccion", "domicilio", "calle", "domicilio fiscal"],
    "web": ["web", "sitio web", "pagina web", "url", "sitio"],
    "email": ["email", "mail", "correo", "e mail", "correo electronico"],
    "estado": ["estado", "situacion"],
    "contacto_nombre": ["contacto", "nombre contacto", "responsable", "persona contacto"],
    "contacto_cargo": ["cargo", "cargo contacto"],
    "contacto_area": ["area", "area contacto", "sector"],
    "contacto_email": ["email contacto", "mail contacto"],
    "contacto_telefono": ["telefono contacto", "celular contacto", "tel contacto"],
}
_TEL = re.compile(r"^(tel|telefono|telefonos|celular|cel|movil|fono|phone|tel fijo|telefono fijo)( ?\d+)?$")


def _norm_col(c: str) -> str:
    c = sin_tildes(str(c).lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]", " ", c)).strip()


def sugerir_mapeo(columnas: list[str]) -> dict:
    mapeo: dict = {"telefonos": []}
    norm = {c: _norm_col(c) for c in columnas}
    usadas = set()
    for campo, sinos in SINONIMOS.items():
        for s in sinos:  # el orden de sinónimos marca la preferencia
            col = next((c for c in columnas if norm[c] == s and c not in usadas), None)
            if col:
                mapeo[campo] = col
                usadas.add(col)
                break
    for c in columnas:
        if c not in usadas and _TEL.match(norm[c]):
            mapeo["telefonos"].append(c)
    return mapeo


def _validar_mapeo(mapeo: dict, columnas: list[str]):
    if not mapeo.get("rut"):
        raise HTTPException(422, "El mapeo tiene que indicar la columna del RUT")
    for campo, col in mapeo.items():
        if campo not in CAMPOS_MAPEO:
            raise HTTPException(422, f"Campo de destino desconocido: {campo}")
        for c in (col if isinstance(col, list) else [col]):
            if c and c not in columnas:
                raise HTTPException(422, f"La columna '{c}' no está en el archivo")


def _leer(conn, archivo_id: int):
    archivo = conn.execute("SELECT * FROM archivo WHERE id = %s", (archivo_id,)).fetchone()
    if archivo is None:
        raise HTTPException(404, "Archivo inexistente")
    columnas, filas, meta = lectores.leer_tabla(storage.leer(archivo), archivo["tipo"])
    return archivo, columnas, filas


def analizar(conn, archivo: dict, tipo_fuente: str | None) -> dict:
    columnas, filas, _ = lectores.leer_tabla(storage.leer(archivo), archivo["tipo"])
    plantilla = None
    if tipo_fuente:
        plantilla = conn.execute("SELECT mapeo FROM carga_plantilla WHERE tipo_fuente = %s", (tipo_fuente,)).fetchone()
    if plantilla and all(c in columnas for v in plantilla["mapeo"].values() for c in (v if isinstance(v, list) else [v]) if c):
        mapeo, origen = plantilla["mapeo"], "plantilla"
    else:
        mapeo, origen = sugerir_mapeo(columnas), "sugerido"
    return {
        "archivo_id": archivo["id"], "nombre": archivo["nombre"], "tipo": archivo["tipo"],
        "columnas": columnas, "n_filas": len(filas), "ejemplos": filas[:8],
        "mapeo": mapeo, "origen_mapeo": origen, "campos": CAMPOS_MAPEO,
        "plantillas": [r["tipo_fuente"] for r in conn.execute("SELECT tipo_fuente FROM carga_plantilla ORDER BY 1")],
    }


def _valor(fila: dict, mapeo: dict, campo: str):
    col = mapeo.get(campo)
    return texto(fila.get(col)) if col else None


def _buscar_candidata(conn, regla: str, datos: dict, tels: list) -> dict | None:
    if regla == "telefono":
        e164s = [t.e164 for t in tels if t.e164]
        if not e164s:
            return None
        return conn.execute(
            "SELECT e.* FROM empresa e JOIN telefono_vinculo v ON v.empresa_id = e.id JOIN telefono t ON t.id = v.telefono_id"
            " WHERE t.e164 = ANY(%s) AND e.baja IS NULL ORDER BY e.id LIMIT 1", (e164s,)).fetchone()
    if regla == "razon_social":
        clave = razon_normalizada(datos.get("razon_social"))
        if not clave:
            return None
        for e in conn.execute("SELECT * FROM empresa WHERE baja IS NULL AND translate(lower(razon_social), 'áéíóúüñ', 'aeiouun') LIKE %s",
                              (f"%{clave.split(' ')[0]}%",)).fetchall():
            if razon_normalizada(e["razon_social"]) == clave:
                return e
        return None
    if regla == "dominio":
        d = dominio(datos.get("web")) or dominio(datos.get("email"))
        if not d:
            return None
        return conn.execute("SELECT * FROM empresa WHERE baja IS NULL AND web IS NOT NULL AND"
                            " (lower(web) LIKE %s) ORDER BY id LIMIT 1", (f"%{d}%",)).fetchone()
    return None


def procesar(conn, carga: dict, filas: list[dict], cfg: dict, actor: str, real: bool,
             tarea_id: int | None = None) -> tuple[dict, list]:
    """Aplica las filas. Devuelve (conteos, rechazos). Si real=False lo corre el preview."""
    mapeo, cid, confianza = carga["mapeo"], carga["id"], carga["confianza"]
    prefijos = cfg.get("prefijos_salida") or []
    c = Counter()
    rechazos, conflictos_muestra, ruts_vistos = [], [], set()
    telefonos_tocados: set[int] = set()
    total = len(filas)
    for i, fila in enumerate(filas):
        nfila = i + 2
        if tarea_id and i % 200 == 0:
            tareas.progreso(tarea_id, i, total)
        r, motivo = rutmod.validar(fila.get(mapeo["rut"]))
        if r is None:
            rechazos.append((nfila, motivo, fila))
            c["rechazos"] += 1
            continue
        if r in ruts_vistos:
            c["conflictos"] += 1
            c["rut_repetido_en_archivo"] += 1
        ruts_vistos.add(r)
        datos = {k: _valor(fila, mapeo, k) for k in CAMPOS_MAPEO if k != "telefonos"}
        if datos.get("naturaleza"):
            cod = empresas.resolver_naturaleza(conn, datos["naturaleza"])
            if cod is None:
                c["naturaleza_desconocida"] += 1
            datos["naturaleza"] = cod
        if datos.get("estado"):
            est = sin_tildes(datos["estado"].lower())
            datos["estado"] = "activa" if est.startswith("activ") else "cerrada" if est.startswith(("cerr", "baja", "clausur")) else None
        if datos.get("web"):
            datos["web"] = dominio(datos["web"]) or datos["web"]
        tels = []
        for col in mapeo.get("telefonos") or []:
            for crudo in telmod.separar(fila.get(col)):
                tels.append(telmod.normalizar(crudo, prefijos))

        emp = conn.execute("SELECT * FROM empresa WHERE rut = %s", (r,)).fetchone()
        while emp and emp["baja"] == "fusionada" and emp["fusionada_en"]:
            emp = conn.execute("SELECT * FROM empresa WHERE id = %s", (emp["fusionada_en"],)).fetchone()
        es_alta = False
        if emp is None:
            if carga["regla_fusion"] != "rut":
                cand = _buscar_candidata(conn, carga["regla_fusion"], datos, tels)
                if cand is not None:
                    c["revision"] += 1
                    if real:
                        conn.execute(
                            "INSERT INTO revision_fusion (carga_id, fila, datos, criterio, candidata_id)"
                            " VALUES (%s,%s,%s,%s,%s)",
                            (cid, nfila, Jsonb({"rut": r, **{k: v for k, v in datos.items() if v},
                                                "telefonos": [t.crudo for t in tels]}),
                             carga["regla_fusion"], cand["id"]),
                        )
                    continue
            emp = conn.execute("INSERT INTO empresa (rut, carga_alta_id) VALUES (%s, %s) RETURNING *",
                               (r, cid)).fetchone()
            es_alta = True
        elif emp["baja"] == "anulada":
            conn.execute("UPDATE empresa SET baja = NULL, carga_alta_id = %s WHERE id = %s", (cid, emp["id"]))
            es_alta = True

        hubo_cambio = aplicar_fila(conn, emp, datos, tels, cid, confianza, actor, c, conflictos_muestra,
                                   telefonos_tocados)
        if es_alta:
            c["altas"] += 1
        elif hubo_cambio:
            c["actualizaciones"] += 1
        else:
            c["sin_cambios"] += 1

    umbral = cfg["umbral_intermediario"]
    ids = sorted(telefonos_tocados)
    if real:
        c["nuevos_sospechosos"] = len(intermediarios.detectar(conn, umbral, ids, actor)) if ids else 0
        tareas.progreso(tarea_id, total, total)
    else:
        c["nuevos_sospechosos"] = intermediarios.contar_nuevos(conn, umbral, ids) if ids else 0
    c["filas"] = total
    motivos = Counter(m for _, m, _ in rechazos)
    conteos = dict(c)
    conteos["rechazos_por_motivo"] = dict(motivos)
    conteos["conflictos_ejemplos"] = conflictos_muestra[:30]
    return conteos, rechazos


def aplicar_fila(conn, emp, datos, tels, cid, confianza, actor, c, conflictos_muestra, telefonos_tocados) -> bool:
    cambios, conflictos = empresas.aplicar_valores(conn, emp["id"], datos, "carga", cid, confianza, actor)
    hubo = bool(cambios)
    if conflictos:
        c["conflictos"] += 1
        if len(conflictos_muestra) < 30:
            conflictos_muestra.append({"rut": emp["rut"], "campos": conflictos})
    sucursal_id = None
    if datos.get("sucursal_direccion") or datos.get("sucursal_localidad"):
        dir_ = datos.get("sucursal_direccion")
        existe = conn.execute(
            "SELECT id FROM sucursal WHERE empresa_id = %s AND lower(coalesce(direccion,'')) = lower(coalesce(%s,''))",
            (emp["id"], dir_)).fetchone()
        if existe:
            sucursal_id = existe["id"]
        else:
            sucursal_id = conn.execute(
                "INSERT INTO sucursal (empresa_id, direccion, departamento, localidad, fuente_tipo, fuente_id)"
                " VALUES (%s,%s,%s,%s,'carga',%s) RETURNING id",
                (emp["id"], dir_, datos.get("sucursal_departamento"), datos.get("sucursal_localidad"), cid),
            ).fetchone()["id"]
            c["sucursales_nuevas"] += 1
            hubo = True
    for t in tels:
        if t.tipo == "interno":
            c["telefonos_invalidos"] += 1
            continue
        fila_tel, n, creado = empresas.telefono(conn, t.crudo)
        if fila_tel is None:
            continue
        if not n.e164:
            c["telefonos_invalidos"] += 1
        if creado:
            c["telefonos_nuevos"] += 1
        _, nuevo = empresas.vincular(conn, fila_tel["id"], emp["id"], "carga", cid, actor, sucursal_id=sucursal_id)
        if nuevo:
            c["vinculos_nuevos"] += 1
            hubo = True
            telefonos_tocados.add(fila_tel["id"])
    if datos.get("contacto_nombre"):
        contacto, nuevo = empresas.contacto(conn, emp["id"], datos["contacto_nombre"], datos.get("contacto_cargo"),
                                            datos.get("contacto_area"), datos.get("contacto_email"), "carga", cid,
                                            sucursal_id=sucursal_id)
        if nuevo:
            c["contactos_nuevos"] += 1
            hubo = True
        for crudo in telmod.separar(datos.get("contacto_telefono")):
            fila_tel, n, creado = empresas.telefono(conn, crudo)
            if fila_tel is None:
                continue
            if creado:
                c["telefonos_nuevos"] += 1
            _, nuevo_v = empresas.vincular(conn, fila_tel["id"], emp["id"], "carga", cid, actor,
                                           contacto_id=contacto["id"])
            if nuevo_v:
                c["vinculos_nuevos"] += 1
                telefonos_tocados.add(fila_tel["id"])
    return hubo


class _Preview(Exception):
    pass


def crear(conn, archivo_id: int, fuente: str, tipo_fuente: str, licencia: str, regla_fusion: str,
          confianza: int | None, mapeo: dict, guardar_plantilla: bool, actor: str) -> dict:
    version, cfg = config.vigente(conn)
    if regla_fusion not in cfg["reglas_fusion"]:
        raise HTTPException(422, f"La regla de fusión '{regla_fusion}' no está habilitada en la configuración")
    if not licencia or not licencia.strip():
        raise HTTPException(422, "Indicá la licencia de uso de la fuente")
    archivo, columnas, filas = _leer(conn, archivo_id)
    mapeo = {k: v for k, v in mapeo.items() if v}
    _validar_mapeo(mapeo, columnas)
    if confianza is None:
        confianza = cfg["confianza_fuentes"].get("carga", 50)
    carga = conn.execute(
        "INSERT INTO carga (archivo_id, fuente, tipo_fuente, licencia, responsable, regla_fusion, confianza, mapeo, config_version)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (archivo_id, fuente, tipo_fuente, licencia, actor, regla_fusion, confianza, Jsonb(mapeo), version),
    ).fetchone()
    if guardar_plantilla:
        conn.execute(
            "INSERT INTO carga_plantilla (tipo_fuente, mapeo, autor) VALUES (%s,%s,%s)"
            " ON CONFLICT (tipo_fuente) DO UPDATE SET mapeo = EXCLUDED.mapeo, autor = EXCLUDED.autor, actualizado = now()",
            (tipo_fuente, Jsonb(mapeo), actor),
        )
    auditoria.registrar(conn, actor, "carga.crear", "carga", carga["id"],
                        {"archivo": archivo["nombre"], "fuente": fuente, "regla_fusion": regla_fusion})
    tarea_id = tareas.crear(conn, "carga.preview", {"carga_id": carga["id"]}, actor)
    return {"carga_id": carga["id"], "tarea_id": tarea_id, "n_filas": len(filas)}


@tareas.handler("carga.preview")
def _tarea_preview(conn, payload, tarea_id):
    """Corre la carga en un savepoint que se descarta: los conteos son los reales."""
    carga = conn.execute("SELECT * FROM carga WHERE id = %s", (payload["carga_id"],)).fetchone()
    _, _, filas = _leer(conn, carga["archivo_id"])
    _, cfg = config.vigente(conn)
    resultado = {}
    try:
        with conn.transaction():
            resultado["conteos"], resultado["rechazos"] = procesar(conn, carga, filas, cfg, carga["responsable"],
                                                                   real=False, tarea_id=tarea_id)
            raise _Preview()
    except _Preview:
        pass
    tareas.progreso(tarea_id, len(filas), len(filas))
    _guardar_rechazos(conn, carga["id"], resultado["rechazos"])
    conn.execute("UPDATE carga SET conteos = %s, estado = 'preview' WHERE id = %s",
                 (Jsonb(resultado["conteos"]), carga["id"]))
    return {"carga_id": carga["id"], "conteos": resultado["conteos"]}


def _guardar_rechazos(conn, carga_id, rechazos):
    conn.execute("DELETE FROM carga_rechazo WHERE carga_id = %s", (carga_id,))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO carga_rechazo (carga_id, fila, motivo, datos) VALUES (%s,%s,%s,%s)",
                        [(carga_id, n, m, Jsonb(f)) for n, m, f in rechazos])


def confirmar(conn, carga_id: int, actor: str) -> int:
    carga = conn.execute("SELECT * FROM carga WHERE id = %s FOR UPDATE", (carga_id,)).fetchone()
    if carga is None:
        raise HTTPException(404, "Carga inexistente")
    if carga["estado"] != "preview":
        raise HTTPException(409, f"La carga está en estado {carga['estado']}")
    conn.execute("UPDATE carga SET estado = 'en_proceso' WHERE id = %s", (carga_id,))
    return tareas.crear(conn, "carga.confirmar", {"carga_id": carga_id}, actor)


@tareas.handler("carga.confirmar")
def _tarea_confirmar(conn, payload, tarea_id):
    carga = conn.execute("SELECT * FROM carga WHERE id = %s", (payload["carga_id"],)).fetchone()
    _, columnas, filas = _leer(conn, carga["archivo_id"])
    _, cfg = config.vigente(conn)
    conteos, rechazos = procesar(conn, carga, filas, cfg, carga["responsable"], real=True, tarea_id=tarea_id)
    _guardar_rechazos(conn, carga["id"], rechazos)
    conn.execute("UPDATE carga SET estado = 'confirmada', conteos = %s, confirmada = now() WHERE id = %s",
                 (Jsonb(conteos), carga["id"]))
    auditoria.registrar(conn, carga["responsable"], "carga.confirmar", "carga", carga["id"], {"conteos": conteos})
    return {"carga_id": carga["id"], "conteos": conteos}


def empresas_de_carga(conn, carga_id: int) -> list[int]:
    return [r["empresa_id"] for r in conn.execute(
        "SELECT DISTINCT empresa_id FROM empresa_campo_historia WHERE fuente_tipo = 'carga' AND fuente_id = %s"
        " UNION SELECT DISTINCT empresa_id FROM telefono_vinculo WHERE fuente_tipo = 'carga' AND fuente_id = %s"
        " UNION SELECT id FROM empresa WHERE carga_alta_id = %s",
        (carga_id, carga_id, carga_id))]


def deshacer(conn, carga_id: int, actor: str) -> dict:
    carga = conn.execute("SELECT * FROM carga WHERE id = %s FOR UPDATE", (carga_id,)).fetchone()
    if carga is None:
        raise HTTPException(404, "Carga inexistente")
    if carga["estado"] == "deshecha":
        raise HTTPException(409, "La carga ya fue deshecha")
    if carga["estado"] in ("analizando", "preview", "error"):
        conn.execute("UPDATE carga SET estado = 'deshecha', deshecha = now() WHERE id = %s", (carga_id,))
        auditoria.registrar(conn, actor, "carga.descartar", "carga", carga_id)
        return {"empresas_anuladas": 0, "empresas_recalculadas": 0}
    if carga["estado"] != "confirmada":
        raise HTTPException(409, f"No se puede deshacer una carga en estado {carga['estado']}")
    ids = empresas_de_carga(conn, carga_id)
    en_muestra = conn.execute(
        "SELECT count(DISTINCT empresa_id) AS n FROM muestra_item WHERE empresa_id = ANY(%s)", (ids,)).fetchone()["n"]
    if en_muestra:
        raise HTTPException(409, f"No se puede deshacer: {en_muestra} empresas de esta carga ya entraron a una muestra")
    conn.execute("UPDATE carga SET estado = 'deshecha', deshecha = now() WHERE id = %s", (carga_id,))
    vincs = conn.execute("DELETE FROM telefono_vinculo WHERE fuente_tipo = 'carga' AND fuente_id = %s RETURNING id",
                         (carga_id,)).fetchall()
    conn.execute("UPDATE telefono_vinculo SET contacto_id = NULL WHERE contacto_id IN "
                 "(SELECT id FROM contacto WHERE fuente_tipo = 'carga' AND fuente_id = %s)", (carga_id,))
    conn.execute("DELETE FROM contacto WHERE fuente_tipo = 'carga' AND fuente_id = %s", (carga_id,))
    conn.execute("UPDATE telefono_vinculo SET sucursal_id = NULL WHERE sucursal_id IN "
                 "(SELECT id FROM sucursal WHERE fuente_tipo = 'carga' AND fuente_id = %s)", (carga_id,))
    conn.execute("DELETE FROM sucursal WHERE fuente_tipo = 'carga' AND fuente_id = %s", (carga_id,))
    conn.execute("UPDATE revision_fusion SET estado = 'descartada', resuelto_por = %s, resuelto = now()"
                 " WHERE carga_id = %s AND estado = 'pendiente'", (actor, carga_id))
    anuladas = 0
    for eid in ids:
        empresas.recalcular(conn, eid)
        quedan = conn.execute(
            "SELECT (SELECT count(*) FROM empresa_campo_historia h LEFT JOIN carga c ON h.fuente_tipo='carga' AND c.id=h.fuente_id"
            "        WHERE h.empresa_id = %s AND (c.id IS NULL OR c.estado <> 'deshecha'))"
            " + (SELECT count(*) FROM telefono_vinculo WHERE empresa_id = %s)"
            " + (SELECT count(*) FROM contacto WHERE empresa_id = %s) AS n",
            (eid, eid, eid)).fetchone()["n"]
        if quedan == 0:
            conn.execute("UPDATE empresa SET baja = 'anulada' WHERE id = %s", (eid,))
            anuladas += 1
    resumen = {"empresas_anuladas": anuladas, "empresas_recalculadas": len(ids), "vinculos_borrados": len(vincs)}
    auditoria.registrar(conn, actor, "carga.deshacer", "carga", carga_id, resumen)
    return resumen


def obtener(conn, carga_id: int) -> dict:
    carga = conn.execute(
        "SELECT c.*, a.nombre AS archivo_nombre, a.tipo AS archivo_tipo FROM carga c JOIN archivo a ON a.id = c.archivo_id"
        " WHERE c.id = %s", (carga_id,)).fetchone()
    if carga is None:
        raise HTTPException(404, "Carga inexistente")
    carga["rechazos"] = conn.execute(
        "SELECT fila, motivo, datos FROM carga_rechazo WHERE carga_id = %s ORDER BY fila LIMIT 200", (carga_id,)).fetchall()
    carga["revision_pendiente"] = conn.execute(
        "SELECT count(*) AS n FROM revision_fusion WHERE carga_id = %s AND estado = 'pendiente'", (carga_id,)).fetchone()["n"]
    carga["tarea"] = conn.execute(
        "SELECT id, estado, progreso, total, error FROM tarea WHERE tipo = 'carga.confirmar'"
        " AND (payload->>'carga_id')::int = %s ORDER BY id DESC LIMIT 1", (carga_id,)).fetchone()
    return carga


def listar(conn) -> list[dict]:
    return conn.execute(
        "SELECT c.id, c.fuente, c.tipo_fuente, c.licencia, c.responsable, c.regla_fusion, c.estado, c.conteos, c.fecha,"
        " c.confirmada, c.deshecha, a.nombre AS archivo_nombre FROM carga c JOIN archivo a ON a.id = c.archivo_id"
        " ORDER BY c.id DESC LIMIT 200").fetchall()


# ─────────────────────────────────────────────────────────────
# Bandeja de revisión (coincidencias que no son por RUT)
# ─────────────────────────────────────────────────────────────

def revision_pendiente(conn) -> list[dict]:
    return conn.execute(
        "SELECT r.*, e.rut AS candidata_rut, e.razon_social AS candidata_razon, e.web AS candidata_web,"
        " c.fuente FROM revision_fusion r JOIN empresa e ON e.id = r.candidata_id JOIN carga c ON c.id = r.carga_id"
        " WHERE r.estado = 'pendiente' ORDER BY r.id").fetchall()


def resolver_revision(conn, revision_id: int, accion: str, actor: str) -> dict:
    r = conn.execute("SELECT * FROM revision_fusion WHERE id = %s FOR UPDATE", (revision_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "Ítem de revisión inexistente")
    if r["estado"] != "pendiente":
        raise HTTPException(409, "Ya fue resuelto")
    carga = conn.execute("SELECT * FROM carga WHERE id = %s", (r["carga_id"],)).fetchone()
    datos = dict(r["datos"])
    tels = [telmod.normalizar(t) for t in datos.pop("telefonos", [])]
    c = Counter()
    if accion == "alta":
        emp = conn.execute("INSERT INTO empresa (rut, carga_alta_id) VALUES (%s, %s) ON CONFLICT (rut) DO NOTHING"
                           " RETURNING *", (datos["rut"], carga["id"])).fetchone()
        emp = emp or conn.execute("SELECT * FROM empresa WHERE rut = %s", (datos["rut"],)).fetchone()
    elif accion == "actualizar_candidata":
        emp = conn.execute("SELECT * FROM empresa WHERE id = %s", (r["candidata_id"],)).fetchone()
    elif accion == "descartada":
        emp = None
    else:
        raise HTTPException(422, "accion: alta | actualizar_candidata | descartada")
    if emp is not None:
        tocados: set[int] = set()
        aplicar_fila(conn, emp, datos, tels, carga["id"], carga["confianza"], actor, c, [], tocados)
        _, cfg = config.vigente(conn)
        if tocados:
            intermediarios.detectar(conn, cfg["umbral_intermediario"], sorted(tocados), actor)
    conn.execute("UPDATE revision_fusion SET estado = %s, resuelto_por = %s, resuelto = now() WHERE id = %s",
                 (accion, actor, revision_id))
    auditoria.registrar(conn, actor, f"revision.{accion}", "revision_fusion", revision_id,
                        {"rut": datos.get("rut"), "candidata_id": r["candidata_id"]})
    return {"id": revision_id, "estado": accion}
