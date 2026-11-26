"""Estudios, partes, sorteo de muestras y reemplazos (R1.5, R1.6).

El sorteo es reproducible: al sortear se congela un snapshot del marco (empresas
disponibles con su estrato y su CIIU) y se guarda la semilla y la versión de configuración. El
orden dentro de cada estrato es el de sha256("semilla:empresa_id"), que no depende del
orden en que la base devuelve las filas ni de la versión de Postgres o de Python.

Dos métodos (D56): aleatorio simple (el de siempre) y sistemático por CIIU (sortear_sistematico).
"""
import hashlib
import secrets
from collections import Counter, defaultdict

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, catalogos, config, criterios as crit, disponibilidad, mantenimiento
from .db import sin_limite

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


METODOS = ("aleatorio", "sistematico_ciiu")


def sortear_snapshot(marco: list[tuple[int, str]], semilla: int, definicion: dict[str, tuple[int, int]],
                     grupos: dict[int, int] | None = None, metodo: str = "aleatorio", ciiu: dict | None = None,
                     vecinos: dict | None = None):
    """Despacha según el método (D56). Sistemático: ciiu {empresa_id: ciiu} y, si se pasa, vecinos se llena con
    {reemplazo_id: titular_id}. Aleatorio: el sorteo de siempre."""
    if metodo == "sistematico_ciiu":
        return sortear_sistematico(marco, semilla, definicion, ciiu or {}, grupos, vecinos)
    return sortear_aleatorio(marco, semilla, definicion, grupos)


def arranque(semilla: int, estrato: str, n_marco: int) -> int:
    """Arranque del sistemático, en [0, N): con p_i = (a + i·N) // n equivale a un arranque al azar en [0, N/n)."""
    return int(hashlib.sha256(f"{semilla}:{estrato}:arranque".encode()).hexdigest(), 16) % n_marco


def posiciones_sistematicas(a: int, n_marco: int, n: int) -> list[int]:
    """Posiciones de los n titulares en una lista de N, con aritmética entera: p_i = floor((a + i·N) / n)."""
    return [(a + i * n_marco) // n for i in range(n)]


def sortear_sistematico(marco: list[tuple[int, str]], semilla: int, definicion: dict[str, tuple[int, int]],
                        ciiu: dict[int, str | None], grupos: dict[int, int] | None = None,
                        vecinos: dict | None = None):
    """Sorteo sistemático por CIIU (D56), independiente en cada estrato. Función pura.

    1. La lista del estrato se ordena por CIIU completo (texto); las sin CIIU al final; los empates, por
       sha256(semilla:empresa_id) como el aleatorio.
    2. Con N empresas y n titulares (n < N), arranque a = sha256(semilla:estrato:arranque) mod N y titulares en las
       posiciones floor((a + i·N) / n). Si n ≥ N, todas son titulares.
    3. El reemplazo de un titular es su vecino: la siguiente empresa de la lista (circular) que no esté elegida. Los
       titulares toman reemplazo en el orden sha256(semilla:titular_id) (así liberar «los próximos M» no favorece los
       CIIU bajos); con más reemplazos que titulares, se da otra vuelta.
    4. Con grupos (una por grupo económico): si en una posición hay una empresa de un grupo ya usado, se toma la
       siguiente de la lista que no esté elegida y cuyo grupo esté libre. Primero los titulares de todos los
       estratos y después los reemplazos, como en el aleatorio.
    Devuelve [(empresa_id, estrato, rol, orden)]: titulares 1…n en el orden de la lista, reemplazos n+1…"""
    por_estrato = defaultdict(list)
    for empresa_id, estrato in marco:
        por_estrato[estrato].append(empresa_id)
    listas = {est: sorted(por_estrato.get(est, []), key=lambda eid: (ciiu.get(eid) is None, ciiu.get(eid) or "",
                                                                     clave_orden(semilla, eid), eid))
              for est in definicion}
    usados: set = set()
    elegidas: dict[str, set[int]] = {est: set() for est in definicion}   # posiciones tomadas en cada lista
    titulares: dict[str, list[int]] = {est: [] for est in definicion}    # posiciones de los titulares
    reemplazos: dict[str, list[tuple[int, int]]] = {est: [] for est in definicion}   # (posición, posición del titular)

    def libre(est, j):
        if j in elegidas[est]:
            return False
        g = (grupos or {}).get(listas[est][j])
        return g is None or g not in usados

    def tomar(est, j):
        elegidas[est].add(j)
        g = (grupos or {}).get(listas[est][j])
        if g is not None:
            usados.add(g)

    def siguiente_libre(est, desde):
        """Desde la posición «desde» (incluida), la primera libre, en círculo. None si no queda ninguna."""
        n_marco = len(listas[est])
        for d in range(n_marco):
            j = (desde + d) % n_marco
            if libre(est, j):
                return j
        return None

    for est in sorted(definicion):
        n, _ = definicion[est]
        n_marco = len(listas[est])
        if not n_marco or n <= 0:
            continue
        objetivo = range(n_marco) if n >= n_marco else posiciones_sistematicas(arranque(semilla, est, n_marco), n_marco, n)
        for p in objetivo:
            j = siguiente_libre(est, p)
            if j is None:
                break
            tomar(est, j)
            titulares[est].append(j)
    for est in sorted(definicion):
        _, r = definicion[est]
        if r <= 0 or not titulares[est]:
            continue
        orden_t = sorted(titulares[est], key=lambda j: (clave_orden(semilla, listas[est][j]), listas[est][j]))
        while len(reemplazos[est]) < r:
            antes = len(reemplazos[est])
            for t in orden_t:
                if len(reemplazos[est]) >= r:
                    break
                j = siguiente_libre(est, (t + 1) % len(listas[est]))
                if j is None:
                    break
                tomar(est, j)
                reemplazos[est].append((j, t))
            if len(reemplazos[est]) == antes:   # ya no queda ninguna libre
                break
    salida = []
    for est in sorted(definicion):
        lista = listas[est]
        tits = sorted(titulares[est])
        for k, j in enumerate(tits):
            salida.append((lista[j], est, "titular", k + 1))
        for k, (j, t) in enumerate(reemplazos[est]):
            salida.append((lista[j], est, "reemplazo", len(tits) + k + 1))
            if vecinos is not None:
                vecinos[lista[j]] = lista[t]
    return salida


def sortear_aleatorio(marco: list[tuple[int, str]], semilla: int, definicion: dict[str, tuple[int, int]],
                      grupos: dict[int, int] | None = None):
    """Función pura del sorteo aleatorio simple. marco: [(empresa_id, estrato)].
    definicion: {estrato: (n_titulares, n_reemplazos)}. Devuelve [(empresa_id, estrato, rol, orden)].
    grupos ({empresa_id: grupo_id}, B4): como máximo una empresa por grupo económico en toda la muestra. Si sale
    una empresa de un grupo que ya tiene otra, se saltea y sigue la siguiente del orden. Primero se completan los
    titulares de todos los estratos y después los reemplazos, así un reemplazo no le quita el lugar a un titular."""
    por_estrato = defaultdict(list)
    for empresa_id, estrato in marco:
        por_estrato[estrato].append(empresa_id)
    if grupos:
        orden = {e: sorted(por_estrato.get(e, []), key=lambda eid: (clave_orden(semilla, eid), eid)) for e in definicion}
        elegidos, pos, usados = {e: [] for e in definicion}, dict.fromkeys(definicion, 0), set()

        def tomar(est, hasta):
            lista = orden[est]
            while len(elegidos[est]) < hasta and pos[est] < len(lista):
                eid = lista[pos[est]]
                pos[est] += 1
                g = grupos.get(eid)
                if g is not None:
                    if g in usados:
                        continue
                    usados.add(g)
                elegidos[est].append(eid)

        for est in sorted(definicion):
            tomar(est, definicion[est][0])
        for est in sorted(definicion):
            tomar(est, sum(definicion[est]))
        return [(eid, est, "titular" if k < definicion[est][0] else "reemplazo", k + 1)
                for est in sorted(definicion) for k, eid in enumerate(elegidos[est])]
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


def _con_telefono(conn, ids: list[int] | None = None) -> set[int]:
    if ids is not None:
        return {r["empresa_id"] for r in conn.execute(
            "SELECT DISTINCT empresa_id FROM v_vinculo_discable WHERE empresa_id = ANY(%s)", (ids,))}
    return {r["empresa_id"] for r in conn.execute("SELECT DISTINCT empresa_id FROM v_vinculo_discable")}


AVISO_SIN_TELEFONO = crit.AVISO_SIN_TELEFONO
# Por qué una empresa del marco no se puede sortear (las reglas de bloqueos y el filtro de origen)
MOTIVOS = {"sin_telefono_discable": "sin teléfono discable", "enfriamiento": "enfriamiento",
           "muestra_activa": "en muestra activa", "no_llamar": "no llamar", "naturaleza_excluida": "naturaleza excluida",
           "cerrada": "empresa cerrada", "baja": "dada de baja", "filtro_origen": "sin teléfono del origen elegido"}


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


def calcular_marco(conn, criterios: dict, cfg: dict, defs: dict, muestra_id: int | None = None,
                   guardada: bool = False):
    """R3 (D56): el universo (empresas que cumplen los filtros) con el estrato de cada una, calculado sobre TODO el
    universo, y las reglas que bloquean a cada una (las no sorteables). Devuelve (universo, etiquetas, bloqueos,
    con_tel). guardada=True (el armado): la disponibilidad guardada (D55) si está lista; el sorteo la calcula al
    momento con bloqueos_ids. con_tel es None si no se calculó."""
    universo = _universo(conn, criterios, defs)
    ids = [f["id"] for f in universo]
    con_tel = None
    if guardada and disponibilidad.asegurar(conn, cfg):
        bloqueos, con_tel = defaultdict(set), set()
        for r in conn.execute("SELECT empresa_id, reglas, telefonos_discables FROM empresa_disponibilidad"
                              " WHERE empresa_id = ANY(%s) AND (NOT disponible OR telefonos_discables > 0)", (ids,)):
            if r["reglas"]:
                bloqueos[r["empresa_id"]].update(r["reglas"])
            if r["telefonos_discables"]:
                con_tel.add(r["empresa_id"])
    else:
        bloqueos = _bloqueos(conn, cfg, muestra_id, ids)
    _filtro_origen(conn, universo, criterios.get("origenes") or [], bloqueos)
    etiq = crit.etiquetas(universo, criterios, defs)
    return universo, etiq, bloqueos, con_tel


def resumen_estratos(universo: list[dict], etiq: list[str], bloqueos: dict) -> dict[str, dict]:
    """Por estrato: total, sorteables, no sorteables y motivos ({regla: empresas}; una empresa con dos motivos
    cuenta en los dos, pero una sola vez en no_sorteables)."""
    salida: dict[str, dict] = {}
    for f, e in zip(universo, etiq):
        x = salida.setdefault(e, {"estrato": e, "total": 0, "sorteables": 0, "no_sorteables": 0, "motivos": Counter()})
        x["total"] += 1
        reglas = bloqueos.get(f["id"])
        if reglas:
            x["no_sorteables"] += 1
            x["motivos"].update(reglas)
        else:
            x["sorteables"] += 1
    for x in salida.values():
        x["motivos"] = dict(sorted(x["motivos"].items(), key=lambda kv: (-kv[1], kv[0])))
        x["disponibles"] = x["sorteables"]   # nombre anterior, mientras la pantalla se migra
    return salida


def previsualizar_marco(conn, criterios: dict, avisos: list | None = None) -> dict:
    """Cuántas empresas tiene cada estrato, cuántas se pueden sortear y por qué no las demás, sin sortear (R3, D56).
    avisos (aplicar un template): lo que ya no existe se saca con aviso en lugar de rechazar."""
    pedia_sin_tel = bool((criterios or {}).get("incluir_sin_telefono"))
    criterios = _validar_criterios(conn, criterios, avisos, tamanos=False)
    sin_limite(conn, 120)
    _, cfg = config.vigente(conn)
    defs = crit.definiciones(conn)
    universo, etiq, bloqueos, con_tel = calcular_marco(conn, criterios, cfg, defs, guardada=True)
    if con_tel is None:
        con_tel = _con_telefono(conn, [f["id"] for f in universo])
    excl, marco = _aplicar_bloqueos(universo, bloqueos)
    por = resumen_estratos(universo, etiq, bloqueos)
    sin_tel = Counter(e for f, e in zip(universo, etiq) if not bloqueos.get(f["id"]) and f["id"] not in con_tel)
    for k, x in por.items():
        x["sin_telefono"] = sin_tel.get(k, 0)   # sorteables sin teléfono: solo con la regla apagada en Configuración
    estratos = [por[k] for k in sorted(por, key=crit.orden_natural)]
    av = crit.avisos_estratos(universo, criterios, defs, len(por))
    if pedia_sin_tel and avisos is None:
        av.insert(0, AVISO_SIN_TELEFONO)
    return {"universo": len(universo), "marco": len(marco), "sorteables": len(marco),
            "no_sorteables": len(universo) - len(marco), "exclusiones": excl, "estratos": estratos,
            "sin_telefono": sum(sin_tel.values()), "avisos": av,
            "regla_sin_telefono": bool((cfg.get("reglas_disponibilidad") or {}).get("sin_telefono_discable", True)),
            "criterios": criterios}


def no_sorteables(conn, criterios: dict) -> list[dict]:
    """«Descargar no sorteables» (R3): las empresas del marco que no se pueden sortear, con su estrato y su motivo."""
    criterios = _validar_criterios(conn, criterios, [], tamanos=False)
    sin_limite(conn, 120)
    _, cfg = config.vigente(conn)
    defs = crit.definiciones(conn)
    universo, etiq, bloqueos, _ = calcular_marco(conn, criterios, cfg, defs, guardada=True)
    filas = [(f, e, sorted(bloqueos[f["id"]])) for f, e in zip(universo, etiq) if bloqueos.get(f["id"])]
    if not filas:
        return []
    datos = {r["id"]: r for r in conn.execute(
        "SELECT id, codigo, razon_social, departamento, ciiu FROM empresa WHERE id = ANY(%s)", ([f["id"] for f, _, _ in filas],))}
    return [{"rut": datos[f["id"]]["codigo"], "razon_social": datos[f["id"]]["razon_social"] or "",
             "departamento": datos[f["id"]]["departamento"] or "", "ciiu": datos[f["id"]]["ciiu"] or "", "estrato": e,
             "motivos": reglas} for f, e, reglas in sorted(filas, key=lambda x: (crit.orden_natural(x[1]), x[0]["id"]))]


def _bloqueos(conn, cfg, muestra_id, ids: list[int]):
    """Las reglas de bloqueos(cfg) para las empresas del universo, calculadas al momento (D55: bloqueos_ids, las mismas
    reglas solo para esas empresas, en lugar de toda la base)."""
    b = defaultdict(set)
    for r in conn.execute("SELECT empresa_id, regla FROM bloqueos_ids(%s, %s, %s)", (Jsonb(cfg), ids, muestra_id)):
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
    metodo = criterios.get("metodo") or "aleatorio"
    sin_limite(conn, 120)
    version, cfg = config.vigente(conn)
    defs = crit.definiciones(conn)
    # R3 (D56): los estratos se calculan sobre todo el universo; al sorteo entran solo las sorteables. La opción
    # «Incluir empresas sin teléfono» ya no existe: si una muestra en borrador la tiene, se ignora.
    universo, etiq, bloqueos, _ = calcular_marco(conn, criterios, cfg, defs, muestra_id)
    excl, _ = _aplicar_bloqueos(universo, bloqueos)
    por = resumen_estratos(universo, etiq, bloqueos)
    sorteables = [(f, e) for f, e in zip(universo, etiq) if not bloqueos.get(f["id"])]
    marco = [(f["id"], e) for f, e in sorteables]
    ciiu = {f["id"]: f["ciiu"] for f, _ in sorteables}   # congelado en el snapshot, con los dos métodos
    # B4: la pertenencia a grupos económicos se congela en el snapshot (Verificar reproducibilidad)
    grupos = {r["id"]: r["grupo_economico_id"] for r in conn.execute(
        "SELECT id, grupo_economico_id FROM empresa WHERE grupo_economico_id IS NOT NULL AND id = ANY(%s)",
        ([eid for eid, _ in marco],))}

    snapshot_id = conn.execute(
        "INSERT INTO marco_snapshot (config_version, criterios, n, ciiu_congelado) VALUES (%s,%s,%s,true) RETURNING id",
        (version, Jsonb(criterios), len(marco))).fetchone()["id"]
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO marco_snapshot_item (snapshot_id, empresa_id, estrato, grupo_id, ciiu)"
                        " VALUES (%s,%s,%s,%s,%s)",
                        [(snapshot_id, eid, est, grupos.get(eid), ciiu.get(eid)) for eid, est in marco])

    definicion = definicion_estratos(criterios, {e for _, e in marco})
    semilla = semilla if semilla is not None else secrets.randbits(62)
    vecinos: dict[int, int] = {}
    sorteados = sortear_snapshot(marco, semilla, definicion, grupos if criterios.get("una_por_grupo") else None,
                                 metodo, ciiu, vecinos)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO muestra_item (muestra_id, empresa_id, estrato, rol, orden, liberado, liberado_por, liberado_motivo,"
            " liberado_fecha, reemplaza_a) VALUES (%s,%s,%s,%s,%s,%s,%s,%s, CASE WHEN %s THEN now() END, %s)",
            [(muestra_id, eid, est, rol, orden, rol == "titular", actor if rol == "titular" else None,
              "titular" if rol == "titular" else None, rol == "titular", vecinos.get(eid))
             for eid, est, rol, orden in sorteados])
    _pendientes_partes(conn, muestra_id)

    disponibles = Counter(e for _, e in marco)
    con_tel = _con_telefono(conn, [eid for eid, _, _, _ in sorteados])
    sin_tel = Counter(est for eid, est, _, _ in sorteados if eid not in con_tel)
    avisos, por_estrato = [], []
    for est in sorted(definicion, key=crit.orden_natural):
        n, r = definicion[est]
        d = disponibles.get(est, 0)
        x = por.get(est, {})
        por_estrato.append({"estrato": est, "pedido": n, "reemplazos": r, "disponibles": d,
                            "titulares": min(n, d), "reemplazos_sorteados": max(0, min(r, d - n)),
                            "sin_telefono": sin_tel.get(est, 0), "total": x.get("total", 0),
                            "no_sorteables": x.get("no_sorteables", 0), "motivos": x.get("motivos", {})})
        if d < n:
            avisos.append(f"El estrato {est} no alcanza: pidió {n} y hay {d} sorteables")
        elif d < n + r:
            avisos.append(f"El estrato {est} tiene solo {d - n} reemplazos de {r} pedidos")
    sin_pedir = sorted(set(disponibles) - set(definicion))
    if criterios.get("incluir_sin_telefono"):  # borrador anterior a D56: la opción se ignora, con aviso
        avisos.insert(0, AVISO_SIN_TELEFONO)
    resultado = {"universo": len(universo), "marco": len(marco), "no_sorteables": len(universo) - len(marco),
                 "exclusiones": excl, "estratos": por_estrato, "metodo": metodo,
                 "avisos": avisos, "estratos_no_pedidos": sin_pedir, "sin_telefono": sum(sin_tel.values()),
                 "una_por_grupo": bool(criterios.get("una_por_grupo")), "en_grupos": len(grupos)}
    conn.execute(
        "UPDATE muestra SET estado = 'activa', semilla = %s, config_version = %s, snapshot_id = %s, resultado = %s,"
        " sorteada_por = %s, sorteada = now() WHERE id = %s",
        (semilla, version, snapshot_id, Jsonb(resultado), actor, muestra_id))
    auditoria.registrar(conn, actor, "muestra.sortear", "muestra", muestra_id,
                        {"semilla": semilla, "config_version": version, "snapshot_id": snapshot_id,
                         "n_items": len(sorteados), "exclusiones": excl})
    mantenimiento.al_terminar(f"muestra #{muestra_id} sorteada", ("muestra_item",))
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
    m = conn.execute("SELECT m.*, s.n AS snapshot_n, s.ciiu_congelado FROM muestra m"
                     " LEFT JOIN marco_snapshot s ON s.id = m.snapshot_id WHERE m.id = %s", (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Muestra inexistente")
    if m["snapshot_id"] is None:
        raise HTTPException(409, "La muestra no está sorteada")
    filas = conn.execute("SELECT empresa_id, estrato, grupo_id, ciiu FROM marco_snapshot_item WHERE snapshot_id = %s",
                         (m["snapshot_id"],)).fetchall()
    marco = [(r["empresa_id"], r["estrato"]) for r in filas]
    grupos = {r["empresa_id"]: r["grupo_id"] for r in filas if r["grupo_id"] is not None}
    borrados = items_borrados(conn, muestra_id)
    base = {"semilla": m["semilla"], "snapshot_id": m["snapshot_id"], "config_version": m["config_version"],
            "items_borrados": borrados, "snapshot_incompleto": len(marco) < m["snapshot_n"]}
    guardado = [(r["empresa_id"], r["estrato"], r["rol"], r["orden"]) for r in conn.execute(
        "SELECT empresa_id, estrato, rol, orden FROM muestra_item WHERE muestra_id = %s", (muestra_id,))]
    base["items"] = len(guardado)
    metodo = m["criterios"].get("metodo") or "aleatorio"
    base["metodo"] = metodo
    if base["snapshot_incompleto"] or (metodo == "sistematico_ciiu" and not m["ciiu_congelado"]):
        return {**base, "reproducible": False, "resultado": "no_verificable"}
    definicion = definicion_estratos(m["criterios"], {e for _, e in marco})
    ciiu = {r["empresa_id"]: r["ciiu"] for r in filas}
    nuevo = sorted(sortear_snapshot(marco, m["semilla"], definicion, grupos if m["criterios"].get("una_por_grupo") else None,
                                    metodo, ciiu), key=lambda x: (x[1], x[3]))
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


def liberar_vecino(conn, muestra_id: int, item_id: int, motivo: str, actor: str) -> dict:
    """P1 (D56): sobre un titular del sorteo sistemático, libera su reemplazo (el vecino que tiene asignado)."""
    if not motivo or not motivo.strip():
        raise HTTPException(422, "Indicá el motivo de la liberación")
    m = conn.execute("SELECT * FROM muestra WHERE id = %s FOR UPDATE", (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Muestra inexistente")
    if m["estado"] != "activa":
        raise HTTPException(409, "Solo se liberan reemplazos de una muestra activa")
    t = conn.execute("SELECT * FROM muestra_item WHERE id = %s AND muestra_id = %s", (item_id, muestra_id)).fetchone()
    if t is None or t["rol"] != "titular":
        raise HTTPException(404, "El ítem no es un titular de esta muestra")
    r = conn.execute("SELECT id FROM muestra_item WHERE muestra_id = %s AND reemplaza_a = %s AND NOT liberado"
                     " ORDER BY orden LIMIT 1", (muestra_id, t["empresa_id"])).fetchone()
    if r is None:
        raise HTTPException(409, "Ese titular no tiene un reemplazo sin liberar")
    conn.execute("UPDATE muestra_item SET liberado = true, liberado_por = %s, liberado_motivo = %s, liberado_fecha = now()"
                 " WHERE id = %s", (actor, motivo, r["id"]))
    _pendientes_partes(conn, muestra_id)
    auditoria.registrar(conn, actor, "muestra.liberar_vecino", "muestra", muestra_id,
                        {"titular": item_id, "item": r["id"], "motivo": motivo})
    return {"liberados": 1, "items": [r["id"]]}


def cerrar(conn, muestra_id: int, actor: str) -> dict:
    m = conn.execute("UPDATE muestra SET estado = 'cerrada' WHERE id = %s AND estado = 'activa' RETURNING id",
                     (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(409, "Solo se cierra una muestra activa")
    auditoria.registrar(conn, actor, "muestra.cerrar", "muestra", muestra_id)
    mantenimiento.al_terminar(f"muestra #{muestra_id} cerrada", ())   # D55: la regla «muestra activa» de sus empresas
    return {"id": muestra_id, "estado": "cerrada"}


def detalle(conn, muestra_id: int) -> dict:
    m = conn.execute("SELECT m.*, e.nombre AS estudio_nombre FROM muestra m JOIN estudio e ON e.id = m.estudio_id"
                     " WHERE m.id = %s", (muestra_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "Muestra inexistente")
    m["exportacion"] = opciones_exportacion(m)
    m["avisos"] = [AVISO_SIN_TELEFONO] if m["estado"] == "borrador" and (m["criterios"] or {}).get("incluir_sin_telefono") else []
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
               e.codigo AS rut, e.base, e.razon_social, e.departamento, e.tamano, e.ciiu, i.reemplaza_a,
               (SELECT coalesce(t.razon_social, t.codigo) FROM empresa t WHERE t.id = i.reemplaza_a) AS vecino_de,
               (SELECT r.id FROM muestra_item r WHERE r.muestra_id = i.muestra_id AND r.reemplaza_a = i.empresa_id
                  AND NOT r.liberado ORDER BY r.orden LIMIT 1) AS reemplazo_libre,
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
