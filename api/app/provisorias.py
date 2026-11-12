"""Base provisoria (empresas sin RUT) y reglas de fusión en cascada (SPEC_mejoras_sav_contactos, F6.1, F6.2; D42, D43).

Las dos bases comparten la tabla empresa (columna base). Una empresa provisoria no tiene RUT y se
identifica por su código P-000123. Pasa a la definitiva cuando se le agrega un RUT válido que no
existe (empresa.promover) o cuando se fusiona con una empresa de la definitiva (empresa.fusionar).

Reglas de fusión: una lista ordenada de {criterio, tipo, umbral}. El RUT siempre se prueba primero.
- exacta: coincidencia después de normalizar; con una sola candidata se fusiona sola;
- flexible: similitud de trigramas (pg_trgm) ≥ umbral; siempre se consulta.
Una coincidencia que no es por RUT nunca une dos RUT válidos distintos: eso siempre se consulta.
"""
import re

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, catalogos, config, empresas, lectores, rut as rutmod, storage
from .util import dominio, razon_normalizada, sin_tildes, texto

CRITERIOS = ("rut", "razon_social", "telefono", "dominio_web", "direccion", "email")
TIPOS = ("exacta", "flexible")
REGLAS_DEFECTO = [{"criterio": "rut", "tipo": "exacta"}]
LEGADO = {"rut": "rut", "telefono": "telefono", "razon_social": "razon_social", "dominio": "dominio_web"}


def normalizar_reglas(reglas, umbral_defecto: float = 0.85) -> list[dict]:
    """Valida la lista ordenada de reglas. La regla de RUT es exacta y, si no está, se agrega primera."""
    salida, vistos = [], set()
    for r in reglas or []:
        criterio, tipo = r.get("criterio"), r.get("tipo") or "exacta"
        if criterio not in CRITERIOS:
            raise HTTPException(422, f"Criterio de fusión desconocido: {criterio}. Posibles: {', '.join(CRITERIOS)}")
        if tipo not in TIPOS:
            raise HTTPException(422, "Tipo de regla: exacta o flexible")
        if criterio == "rut" and tipo != "exacta":
            raise HTTPException(422, "La regla de RUT es siempre exacta")
        if (criterio, tipo) in vistos:
            continue
        vistos.add((criterio, tipo))
        regla = {"criterio": criterio, "tipo": tipo}
        if tipo == "flexible":
            umbral = float(r.get("umbral") or umbral_defecto)
            if not 0.5 <= umbral <= 1:
                raise HTTPException(422, "El umbral de una regla flexible va de 0,5 a 1")
            regla["umbral"] = umbral
        salida.append(regla)
    if not any(r["criterio"] == "rut" for r in salida):
        salida.insert(0, {"criterio": "rut", "tipo": "exacta"})
    return salida


def direccion_normalizada(s) -> str:
    s = sin_tildes(str(s or "").lower())
    s = re.sub(r"\b(avda|av|avenida)\b\.?", "avenida", s)
    s = re.sub(r"\b(esq|esquina)\b\.?", "esquina", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _resumen(e: dict) -> dict:
    return {"id": e["id"], "codigo": e["codigo"], "base": e["base"], "razon_social": e["razon_social"],
            "departamento": e["departamento"], "direccion": e["direccion"], "web": e["web"]}


def candidatos(conn, regla: dict, datos: dict, e164s: list[str], email: str | None = None,
               excluir: set | None = None) -> list[tuple[dict, float]]:
    """Empresas activas (de las dos bases) que coinciden con la fila según la regla: [(empresa, similitud)]."""
    criterio, tipo = regla["criterio"], regla["tipo"]
    umbral = regla.get("umbral", 1.0)
    excluir = excluir or set()
    out: list[tuple[dict, float]] = []
    if criterio == "telefono":
        if e164s:
            out = [(e, 1.0) for e in conn.execute(
                "SELECT DISTINCT e.* FROM empresa e JOIN telefono_vinculo v ON v.empresa_id = e.id JOIN telefono t ON t.id = v.telefono_id"
                " WHERE t.e164 = ANY(%s) AND e.baja IS NULL AND (t.intermediario IS NULL OR t.intermediario = 'liberado')"
                " ORDER BY e.id LIMIT 20", (e164s,))]
    elif criterio == "email":
        mail = (email or "").strip().lower()
        if mail:
            out = [(e, 1.0) for e in conn.execute(
                "SELECT DISTINCT e.* FROM empresa e JOIN contacto c ON c.empresa_id = e.id"
                " WHERE lower(c.email) = %s AND e.baja IS NULL ORDER BY e.id LIMIT 20", (mail,))]
    elif criterio == "razon_social":
        n = razon_normalizada(datos.get("razon_social"))
        if n:
            filas = conn.execute(
                "SELECT e.*, similarity(lower(e.razon_social), lower(%s)) AS s0 FROM empresa e"
                " WHERE e.baja IS NULL AND (lower(e.razon_social) %% lower(%s)"
                "  OR translate(lower(e.razon_social), 'áéíóúüñ', 'aeiouun') LIKE %s)"
                " ORDER BY s0 DESC LIMIT 25", (datos["razon_social"], datos["razon_social"], f"%{n.split(' ')[0]}%")).fetchall()
            out = _por_similitud(conn, filas, n, lambda e: razon_normalizada(e["razon_social"]), tipo, umbral)
    elif criterio == "direccion":
        n = direccion_normalizada(datos.get("direccion"))
        if n:
            filas = conn.execute(
                "SELECT e.* FROM empresa e WHERE e.baja IS NULL AND e.direccion IS NOT NULL"
                " AND (%s::text IS NULL OR e.departamento IS NULL OR e.departamento = %s)"
                " AND lower(e.direccion) %% lower(%s) ORDER BY similarity(lower(e.direccion), lower(%s)) DESC LIMIT 25",
                (datos.get("departamento"), datos.get("departamento"), datos["direccion"], datos["direccion"])).fetchall()
            out = _por_similitud(conn, filas, n, lambda e: direccion_normalizada(e["direccion"]), tipo, umbral)
    elif criterio == "dominio_web":
        d = dominio(datos.get("web")) or dominio(datos.get("email"))
        if d:
            if tipo == "exacta":
                out = [(e, 1.0) for e in conn.execute(
                    "SELECT * FROM empresa WHERE baja IS NULL AND web IS NOT NULL AND lower(web) LIKE %s ORDER BY id LIMIT 20",
                    (f"%{d}%",)) if dominio(e["web"]) == d]
            else:
                filas = conn.execute("SELECT * FROM empresa WHERE baja IS NULL AND web IS NOT NULL AND lower(web) %% %s"
                                     " LIMIT 25", (d,)).fetchall()
                out = _por_similitud(conn, filas, d, lambda e: dominio(e["web"]), tipo, umbral)
    return [(e, s) for e, s in out if e["id"] not in excluir]


def _por_similitud(conn, filas, n, normalizar, tipo, umbral) -> list[tuple[dict, float]]:
    if tipo == "exacta":
        return [(e, 1.0) for e in filas if normalizar(e) == n]
    sim = catalogos.similitudes(conn, [n], [normalizar(e) for e in filas])
    out = []
    for e in filas:
        s = 1.0 if normalizar(e) == n else sim.get((n, normalizar(e)), 0.0)
        if s >= umbral:
            out.append((e, round(s, 3)))
    return sorted(out, key=lambda x: -x[1])


def cascada(conn, reglas: list[dict], rut_fila: str | None, datos: dict, e164s: list[str], email=None) -> dict | None:
    """Prueba las reglas (sin la de RUT, que va antes) en orden; gana la primera que da resultado.
    {"accion": "fusionar"|"consultar", "candidata", "regla", "similitud", "candidatas"} o None."""
    for regla in reglas:
        if regla["criterio"] == "rut":
            continue
        cands = candidatos(conn, regla, datos, e164s, email)
        if not cands:
            continue
        mejor, sim = cands[0]
        conflicto_rut = bool(rut_fila and mejor["rut"] and mejor["rut"] != rut_fila)
        unica = len(cands) == 1
        accion = "fusionar" if regla["tipo"] == "exacta" and unica and not conflicto_rut else "consultar"
        return {"accion": accion, "candidata": mejor, "regla": regla, "similitud": sim,
                "candidatas": [_resumen(e) | {"similitud": s} for e, s in cands[:5]]}
    return None


# ─────────────────────────────────────────────────────────────
# Pasar a la base definitiva
# ─────────────────────────────────────────────────────────────

def promover(conn, emp: dict, rut: str, actor: str, fuente_tipo: str = "manual", fuente_id=None,
             carga_id: int | None = None) -> dict:
    """Agrega el RUT a una provisoria: si es válido y no existe, pasa a la definitiva (empresa.promover).
    Si ya existe, 409 con la empresa que lo tiene, para ofrecer la fusión."""
    r, motivo = rutmod.validar(rut)
    if r is None:
        raise HTTPException(422, f"RUT inválido: {motivo}")
    if emp["base"] != "provisoria":
        raise HTTPException(409, "La empresa ya está en la base definitiva")
    otra = conn.execute("SELECT * FROM empresa WHERE rut = %s", (r,)).fetchone()
    if otra is not None and otra["id"] != emp["id"]:
        raise HTTPException(409, {"mensaje": f"El RUT {r} ya es de otra empresa ({otra['razon_social'] or otra['codigo']}).",
                                  "existente": otra["codigo"], "existente_razon_social": otra["razon_social"],
                                  "existente_baja": otra["baja"]})
    codigo_antes = emp["codigo"]
    if carga_id is not None:
        conn.execute("INSERT INTO carga_promocion (carga_id, empresa_id, rut_anterior, base_anterior) VALUES (%s,%s,%s,%s)",
                     (carga_id, emp["id"], emp["rut"], emp["base"]))
    conn.execute("UPDATE empresa SET rut = %s, base = 'definitiva', actualizado = now() WHERE id = %s", (r, emp["id"]))
    conn.execute("UPDATE provisoria_rut_propuesto SET estado = CASE WHEN rut = %s THEN 'aplicado' ELSE 'descartado' END"
                 " WHERE empresa_id = %s AND estado = 'pendiente'", (r, emp["id"]))
    # La historia admite carga, sala o manual: un RUT por archivo queda como manual, con el archivo en el detalle
    hist = fuente_tipo if fuente_tipo in ("carga", "sav", "sala", "manual") else "manual"
    conn.execute(
        "INSERT INTO empresa_campo_historia (empresa_id, campo, valor, fuente_tipo, fuente_id, confianza, actor, detalle)"
        " VALUES (%s, 'rut', %s, %s, %s, 100, %s, %s)",
        (emp["id"], r, hist, fuente_id if hist == fuente_tipo else None, actor,
         Jsonb({"codigo_provisorio": codigo_antes, **({} if hist == fuente_tipo else {fuente_tipo + "_id": fuente_id})})))
    auditoria.registrar(conn, actor, "empresa.promover", "empresa", r, {"codigo_provisorio": codigo_antes,
                                                                         "fuente": fuente_tipo, "fuente_id": fuente_id})
    return conn.execute("SELECT * FROM empresa WHERE id = %s", (emp["id"],)).fetchone()


def descartar(conn, emp: dict, candidata_ids: list[int], actor: str) -> int:
    """«Es otra empresa»: esas candidatas no se vuelven a proponer para esta provisoria."""
    n = 0
    for cid in candidata_ids:
        n += conn.execute("INSERT INTO provisoria_descarte (empresa_id, candidata_id, actor) VALUES (%s,%s,%s)"
                          " ON CONFLICT DO NOTHING", (emp["id"], cid, actor)).rowcount
    conn.execute("UPDATE provisoria_rut_propuesto SET estado = 'descartado' WHERE empresa_id = %s AND estado = 'pendiente'"
                 " AND rut IN (SELECT rut FROM empresa WHERE id = ANY(%s))", (emp["id"], candidata_ids))
    auditoria.registrar(conn, actor, "empresa.descartar_candidatas", "empresa", emp["codigo"], {"candidatas": candidata_ids})
    return n


def proponer_rut(conn, emp: dict, rut: str, fuente_tipo: str, fuente_id) -> bool:
    """El .sav trajo un EC_RUT válido para una provisoria: queda como propuesta, no se aplica sola."""
    r, _ = rutmod.validar(rut)
    if r is None or emp["base"] != "provisoria" or emp["rut"]:
        return False
    return bool(conn.execute("INSERT INTO provisoria_rut_propuesto (empresa_id, rut, fuente_tipo, fuente_id)"
                             " VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", (emp["id"], r, fuente_tipo, fuente_id)).rowcount)


# ─────────────────────────────────────────────────────────────
# Pantalla «Base provisoria»
# ─────────────────────────────────────────────────────────────

REGLAS_CANDIDATAS = [{"criterio": "telefono", "tipo": "exacta"}, {"criterio": "razon_social", "tipo": "flexible"},
                     {"criterio": "direccion", "tipo": "flexible"}, {"criterio": "dominio_web", "tipo": "exacta"}]


def candidatas_definitiva(conn, emp: dict, umbral: float) -> list[dict]:
    """Empresas de la definitiva que se parecen a la provisoria (sin las descartadas), con la regla y la similitud."""
    e164s = [r["e164"] for r in conn.execute(
        "SELECT t.e164 FROM telefono_vinculo v JOIN telefono t ON t.id = v.telefono_id WHERE v.empresa_id = %s"
        " AND t.e164 IS NOT NULL", (emp["id"],))]
    descartadas = {r["candidata_id"] for r in conn.execute(
        "SELECT candidata_id FROM provisoria_descarte WHERE empresa_id = %s", (emp["id"],))}
    vistas: dict[int, dict] = {}
    for regla in REGLAS_CANDIDATAS:
        regla = {**regla, "umbral": umbral} if regla["tipo"] == "flexible" else regla
        for e, s in candidatos(conn, regla, emp, e164s, excluir=descartadas | {emp["id"]}):
            if e["base"] != "definitiva" or e["id"] in vistas:
                continue
            vistas[e["id"]] = _resumen(e) | {"similitud": s, "criterio": regla["criterio"]}
    for p in conn.execute("SELECT p.rut, e.* FROM provisoria_rut_propuesto p JOIN empresa e ON e.rut = p.rut"
                          " WHERE p.empresa_id = %s AND p.estado = 'pendiente' AND e.baja IS NULL", (emp["id"],)):
        if p["id"] not in descartadas and p["id"] not in vistas:
            vistas[p["id"]] = _resumen(p) | {"similitud": 1.0, "criterio": "rut del .sav"}
    return sorted(vistas.values(), key=lambda x: -x["similitud"])[:5]


def listar(conn, q: str | None = None, pagina: int = 1, solo_con_candidatas: bool = False) -> dict:
    umbral = float(config.vigente(conn)[1].get("umbral_fusion_flexible", 0.85))
    where, args = ["e.base = 'provisoria'", "e.baja IS NULL"], []
    if q:
        where.append("(e.razon_social ILIKE %s OR e.codigo ILIKE %s)")
        args += [f"%{q}%", f"%{q.strip()}%"]
    filas = conn.execute(
        "SELECT e.*, c.fuente AS carga_fuente,"
        " (SELECT count(*) FROM telefono_vinculo v WHERE v.empresa_id = e.id) AS n_telefonos,"
        " (SELECT count(*) FROM v_vinculo_discable d WHERE d.empresa_id = e.id) AS n_discables,"
        " (SELECT count(DISTINCT mi.muestra_id) FROM muestra_item mi WHERE mi.empresa_id = e.id) AS n_muestras,"
        " (SELECT json_agg(json_build_object('rut', p.rut, 'fuente_id', p.fuente_id)) FROM provisoria_rut_propuesto p"
        "   WHERE p.empresa_id = e.id AND p.estado = 'pendiente') AS ruts_propuestos,"
        " (SELECT ea.valor_texto FROM empresa_atributo ea JOIN atributo a ON a.id = ea.atributo_id"
        "   WHERE ea.empresa_id = e.id AND a.clave = 'id_informado') AS id_informado,"
        " count(*) OVER () AS total"
        f" FROM empresa e LEFT JOIN carga c ON c.id = e.carga_alta_id WHERE {' AND '.join(where)}"
        " ORDER BY e.razon_social NULLS LAST, e.id LIMIT 50 OFFSET %s", (*args, (max(1, pagina) - 1) * 50)).fetchall()
    for f in filas:
        f["candidatas"] = candidatas_definitiva(conn, f, umbral)
    if solo_con_candidatas:
        filas = [f for f in filas if f["candidatas"]]
    return {"total": filas[0]["total"] if filas else 0, "pagina": max(1, pagina), "empresas": filas, "umbral": umbral}


def contar_con_candidatas(conn) -> int:
    """Para Inicio: provisorias con alguna candidata en la definitiva (por teléfono o razón social parecida)."""
    umbral = float(config.vigente(conn)[1].get("umbral_fusion_flexible", 0.85))
    return conn.execute(
        """
        SELECT count(*) AS n FROM empresa p WHERE p.base = 'provisoria' AND p.baja IS NULL AND (
          EXISTS (SELECT 1 FROM telefono_vinculo vp JOIN telefono t ON t.id = vp.telefono_id
                  JOIN telefono_vinculo vd ON vd.telefono_id = t.id JOIN empresa d ON d.id = vd.empresa_id
                  WHERE vp.empresa_id = p.id AND d.base = 'definitiva' AND d.baja IS NULL AND t.e164 IS NOT NULL
                    AND NOT EXISTS (SELECT 1 FROM provisoria_descarte x WHERE x.empresa_id = p.id AND x.candidata_id = d.id))
          OR EXISTS (SELECT 1 FROM empresa d WHERE d.base = 'definitiva' AND d.baja IS NULL
                     AND lower(d.razon_social) %% lower(p.razon_social)
                     AND similarity(lower(d.razon_social), lower(p.razon_social)) >= %s
                     AND NOT EXISTS (SELECT 1 FROM provisoria_descarte x WHERE x.empresa_id = p.id AND x.candidata_id = d.id))
          OR EXISTS (SELECT 1 FROM provisoria_rut_propuesto r WHERE r.empresa_id = p.id AND r.estado = 'pendiente'))
        """, (umbral,)).fetchone()["n"]


# ─────────────────────────────────────────────────────────────
# Completar RUT por archivo (codigo_provisorio;rut), con preview
# ─────────────────────────────────────────────────────────────

def ruts_preview(conn, archivo: dict) -> dict:
    columnas, filas, _ = lectores.leer_tabla(storage.leer(archivo), archivo["tipo"])
    norm = {c: catalogos.normalizar(c) for c in columnas}
    col_cod = next((c for c in columnas if norm[c] in ("codigo provisorio", "codigo", "id empresa", "ec id empresa")), None)
    col_rut = next((c for c in columnas if norm[c] in ("rut", "nro rut", "ec rut")), None)
    if not col_cod or not col_rut:
        raise HTTPException(422, "El archivo tiene que traer las columnas codigo_provisorio y rut")
    salida = []
    for i, f in enumerate(filas, start=2):
        cod, rut = texto(f.get(col_cod)), texto(f.get(col_rut))
        fila = {"fila": i, "codigo": cod, "rut_crudo": rut}
        emp = empresas.por_rut(conn, cod or "", seguir_fusion=False) if cod and empresas.CODIGO_PROVISORIO.match(cod) else None
        r, motivo = rutmod.validar(rut)
        if emp is None or emp["base"] != "provisoria" or emp["baja"]:
            fila.update(accion="error", motivo="no es una empresa de la base provisoria")
        elif r is None:
            fila.update(accion="error", motivo=f"RUT inválido: {motivo}")
        else:
            otra = conn.execute("SELECT codigo, razon_social FROM empresa WHERE rut = %s AND id <> %s", (r, emp["id"])).fetchone()
            fila.update(rut=r, razon_social=emp["razon_social"],
                        accion="fusionar" if otra else "promover",
                        existente=otra["codigo"] if otra else None, existente_razon_social=otra["razon_social"] if otra else None)
        salida.append(fila)
    return {"columnas": [col_cod, col_rut], "filas": salida,
            "conteos": {a: sum(1 for x in salida if x["accion"] == a) for a in ("promover", "fusionar", "error")}}


def ruts_aplicar(conn, archivo: dict, fusionar: bool, actor: str) -> dict:
    """Aplica el archivo: promueve las que tienen un RUT nuevo; con fusionar=True, fusiona las demás con la empresa
    que ya tiene ese RUT (la fusión es reversible)."""
    prev = ruts_preview(conn, archivo)
    n = {"promovidas": 0, "fusionadas": 0, "errores": 0, "pendientes": 0}
    for f in prev["filas"]:
        if f["accion"] == "error":
            n["errores"] += 1
            continue
        emp = empresas.por_rut(conn, f["codigo"], seguir_fusion=False)
        if f["accion"] == "promover":
            promover(conn, emp, f["rut"], actor, "archivo", archivo["id"])
            n["promovidas"] += 1
        elif fusionar:
            destino = empresas.por_rut(conn, f["existente"])
            empresas.fusionar(conn, destino, emp, actor, f"RUT {f['rut']} por archivo")
            n["fusionadas"] += 1
        else:
            n["pendientes"] += 1
    auditoria.registrar(conn, actor, "provisoria.ruts_archivo", "archivo", archivo["id"], n)
    return n
