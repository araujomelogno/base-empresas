"""Catálogos administrables de la carga v2: atributos de empresa y orígenes de teléfono
(SPEC_carga_v2_atributos_y_origen_telefono, C1, C2 y C4).

Los campos del núcleo (RUT, razón social, naturaleza, CIIU, tamaño…) siguen fijos en el
código porque de ellos dependen la disponibilidad, los estratos, la fusión y las exclusiones.
Todo lo demás que traiga una base se guarda como atributo.
"""
import datetime as dt
import re
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria
from .util import sin_tildes

TIPOS = ("texto", "numero", "fecha", "lista")
CLAVE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
PREFIJO = "atributo."          # campo de empresa_campo_historia
ORIGENES_SISTEMA = ("sala", "manual", "sin_dato")
SIN_DATO = "sin_dato"


def normalizar(s) -> str:
    """Para sugerir traducciones: sin mayúsculas, tildes, puntuación ni espacios repetidos."""
    s = sin_tildes(str(s or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


# Palabras que no distinguen un atributo de otro al compararlos (F4.1)
VACIAS = {"de", "del", "la", "las", "el", "los", "y", "e", "en", "por", "para", "a", "al", "con",
          "cant", "cantidad", "nro", "n", "num", "numero", "no", "total", "tot"}
NORMALIZACIONES = ("ninguna", "capital", "mayusculas")


def norm_comparar(s) -> str:
    """Para comparar nombres de atributos: sin mayúsculas, tildes, puntuación ni palabras vacías."""
    palabras = [w for w in normalizar(s).split(" ") if w and w not in VACIAS]
    return " ".join(palabras) or normalizar(s)


def similitudes(conn, a: list[str], b: list[str]) -> dict[tuple[str, str], float]:
    """Similitud de trigramas (pg_trgm) entre cada texto de a y cada texto de b, en una sola consulta."""
    a, b = sorted({x for x in a if x}), sorted({x for x in b if x})
    if not a or not b:
        return {}
    return {(r["x"], r["y"]): float(r["s"]) for r in conn.execute(
        "SELECT x, y, similarity(x, y) AS s FROM unnest(%s::text[]) x, unnest(%s::text[]) y", (a, b))}


def parecidos(conn, textos: list[str], ambito: str | None = "empresa", umbral: float | None = None,
              excluir: set | None = None) -> dict[str, list[dict]]:
    """Atributos activos cuyo nombre, clave o sinónimos se parecen a cada texto (F4.1).
    Devuelve {texto: [{id, clave, nombre, tipo, ambito, similitud, por}]} ordenado de mayor a menor."""
    if umbral is None:
        from . import config
        umbral = float(config.vigente(conn)[1].get("umbral_similitud_atributos", 0.6))
    defs = [a for a in atributos(conn, True, ambito) if not excluir or a["clave"] not in excluir]
    nombres = {}
    for a in defs:
        for n in (a["nombre"], a["clave"].replace("_", " "), *(a["sinonimos"] or [])):
            nombres.setdefault(norm_comparar(n), []).append((a, n))
    norm = {t: norm_comparar(t) for t in textos}
    sim = similitudes(conn, list(norm.values()), list(nombres))
    out = {}
    for t, nt in norm.items():
        mejores = {}
        for nn, lista in nombres.items():
            s_ = 1.0 if nt == nn else sim.get((nt, nn), 0.0)
            if s_ < umbral:
                continue
            for a, original in lista:
                if s_ > mejores.get(a["id"], {}).get("similitud", -1):
                    mejores[a["id"]] = {"id": a["id"], "clave": a["clave"], "nombre": a["nombre"], "tipo": a["tipo"],
                                        "ambito": a["ambito"], "similitud": round(s_, 2), "por": original}
        if mejores:
            out[t] = sorted(mejores.values(), key=lambda x: -x["similitud"])
    return out


def opcion_equivalente(opciones, valor) -> str | None:
    """La opción del catálogo igual al valor sin distinguir mayúsculas, tildes ni espacios (F4.1)."""
    n = normalizar(valor)
    if not n:
        return None
    for o in opciones or []:
        if normalizar(o) == n:
            return o
    return None


def agregar_sinonimo(conn, atributo_id: int, texto: str, actor: str) -> dict:
    """Al aceptar una sugerencia de la carga, el nombre de la columna queda como sinónimo del atributo."""
    a = conn.execute("SELECT * FROM atributo WHERE id = %s FOR UPDATE", (atributo_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "Atributo inexistente")
    n = normalizar(texto)
    if n and n not in (a["sinonimos"] or []):
        sin = sorted({*(a["sinonimos"] or []), n})
        a = conn.execute("UPDATE atributo SET sinonimos = %s, actualizado = now() WHERE id = %s RETURNING *",
                         (sin, atributo_id)).fetchone()
        auditoria.registrar(conn, actor, "atributo.sinonimo", "atributo", a["clave"], {"sinonimo": n})
    return a


def slug(s) -> str:
    c = normalizar(s).replace(" ", "_")
    c = re.sub(r"^[^a-z]+", "", c)[:40]
    return c or "origen"


# ─────────────────────────────────────────────────────────────
# Atributos
# ─────────────────────────────────────────────────────────────

AMBITOS = ("empresa", "contacto")


def atributos(conn, activos: bool | None = None, ambito: str | None = None) -> list[dict]:
    """Catálogo de atributos; ambito: 'empresa', 'contacto' o None (todos)."""
    filas = conn.execute(
        "SELECT a.*, CASE WHEN a.ambito = 'contacto'"
        "  THEN (SELECT count(*) FROM contacto_atributo ca WHERE ca.atributo_id = a.id)"
        "  ELSE (SELECT count(*) FROM empresa_atributo ea WHERE ea.atributo_id = a.id) END AS n_valores"
        " FROM atributo a WHERE (%s::boolean IS NULL OR a.activo = %s) AND (%s::text IS NULL OR a.ambito = %s)"
        " ORDER BY a.nombre", (activos, activos, ambito, ambito)).fetchall()
    return filas


def atributo_por_clave(conn, clave: str) -> dict | None:
    return conn.execute("SELECT * FROM atributo WHERE clave = %s", (clave,)).fetchone()


def _limpiar_atributo(datos: dict, actual: dict | None = None) -> dict:
    d = {**(actual or {}), **{k: v for k, v in datos.items() if v is not None}}
    nombre = str(d.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(422, "Indicá el nombre visible del atributo")
    tipo = d.get("tipo")
    if tipo not in TIPOS:
        raise HTTPException(422, f"Tipo de atributo inválido; opciones: {', '.join(TIPOS)}")
    opciones = [str(o).strip() for o in (d.get("opciones") or []) if str(o).strip()]
    if len(set(opciones)) != len(opciones):
        raise HTTPException(422, "Las opciones de la lista no pueden repetirse")
    # F1.5: una lista puede quedar sin opciones; se completan en la carga, con la traducción de valores
    if tipo != "lista":
        opciones = []
    sinonimos = sorted({normalizar(s) for s in (d.get("sinonimos") or []) if normalizar(s)})
    estratificable = bool(d.get("estratificable"))
    if estratificable and tipo != "lista":
        raise HTTPException(422, "Solo un atributo de tipo lista puede usarse como estrato")
    ambito = d.get("ambito") or "empresa"
    if ambito not in AMBITOS:
        raise HTTPException(422, "El ámbito de un atributo es «empresa» o «contacto»")
    filtrable = bool(d.get("filtrable"))
    if ambito == "contacto":  # los atributos de contacto no filtran ni estratifican el sorteo (P2)
        filtrable = estratificable = False
    normalizar_texto = d.get("normalizar_texto") or "ninguna"
    if normalizar_texto not in NORMALIZACIONES:
        raise HTTPException(422, "Normalización de texto: ninguna, capital o mayusculas")
    if len({normalizar(o) for o in opciones}) != len(opciones):
        raise HTTPException(422, "Las opciones de la lista no pueden repetirse (sin distinguir mayúsculas ni tildes)")
    return {"nombre": nombre, "tipo": tipo, "opciones": opciones, "sinonimos": sinonimos,
            "filtrable": filtrable, "estratificable": estratificable, "ambito": ambito,
            "normalizar_texto": normalizar_texto if tipo == "texto" else "ninguna",
            "activo": bool(d.get("activo", True))}


def clave_libre(conn, nombre: str) -> str:
    """Clave automática a partir del nombre (F1.5): minúsculas, sin tildes, guiones bajos, hasta 40 caracteres;
    si ya existe se agrega _2, _3…"""
    base = slug(nombre)
    if base == "origen" and not normalizar(nombre):
        base = "atributo"
    clave, n = base, 1
    while atributo_por_clave(conn, clave):
        n += 1
        sufijo = f"_{n}"
        clave = base[:40 - len(sufijo)] + sufijo
    return clave


def crear_atributo(conn, datos: dict, actor: str) -> dict:
    d = _limpiar_atributo(datos)
    clave = str(datos.get("clave") or "").strip()
    if clave:  # la API sigue aceptando una clave explícita (scripts); la web nunca la pide
        if not CLAVE.match(clave):
            raise HTTPException(422, "La clave va en minúsculas, sin espacios ni tildes, empieza con una letra"
                                     " (p. ej. cantidad_empleados) y tiene hasta 40 caracteres")
        if atributo_por_clave(conn, clave):
            raise HTTPException(409, f"Ya existe un atributo con la clave {clave}")
    else:
        clave = clave_libre(conn, d["nombre"])
    a = conn.execute(
        "INSERT INTO atributo (clave, nombre, tipo, opciones, sinonimos, filtrable, estratificable, activo, creado_por,"
        " ambito, normalizar_texto) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (clave, d["nombre"], d["tipo"], Jsonb(d["opciones"]), d["sinonimos"], d["filtrable"], d["estratificable"],
         d["activo"], actor, d["ambito"], d["normalizar_texto"])).fetchone()
    auditoria.registrar(conn, actor, "atributo.crear", "atributo", clave, d)
    return a


def actualizar_atributo(conn, atributo_id: int, datos: dict, actor: str) -> dict:
    a = conn.execute("SELECT * FROM atributo WHERE id = %s FOR UPDATE", (atributo_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "Atributo inexistente")
    if a["sistema"]:
        raise HTTPException(409, f"{a['nombre']} es un atributo del sistema: no se edita")
    if datos.get("clave") not in (None, a["clave"]):
        raise HTTPException(422, "La clave de un atributo no se puede cambiar")
    if datos.get("ambito") not in (None, a["ambito"]):
        raise HTTPException(422, "El ámbito de un atributo no se puede cambiar")
    if datos.get("tipo") not in (None, a["tipo"]):
        if tiene_valores(conn, a):
            raise HTTPException(409, "No se puede cambiar el tipo de un atributo que ya tiene valores cargados")
    d = _limpiar_atributo(datos, a)
    quitadas = set(a["opciones"] or []) - set(d["opciones"])
    if quitadas:
        tabla = "contacto_atributo" if a["ambito"] == "contacto" else "empresa_atributo"
        en_uso = conn.execute(f"SELECT count(*) AS n FROM {tabla} WHERE atributo_id = %s AND valor_texto = ANY(%s)",
                              (atributo_id, sorted(quitadas))).fetchone()["n"]
        if en_uso:
            quien = "contactos" if a["ambito"] == "contacto" else "empresas"
            raise HTTPException(409, f"No se puede quitar {', '.join(sorted(quitadas))}: {en_uso} {quien} tienen ese valor")
    a = conn.execute(
        "UPDATE atributo SET nombre = %s, tipo = %s, opciones = %s, sinonimos = %s, filtrable = %s, estratificable = %s,"
        " activo = %s, normalizar_texto = %s, actualizado = now() WHERE id = %s RETURNING *",
        (d["nombre"], d["tipo"], Jsonb(d["opciones"]), d["sinonimos"], d["filtrable"], d["estratificable"], d["activo"],
         d["normalizar_texto"], atributo_id)).fetchone()
    auditoria.registrar(conn, actor, "atributo.editar", "atributo", a["clave"], d)
    return a


def tiene_valores(conn, a: dict) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM empresa_campo_historia WHERE campo = %(c)s"
        " UNION ALL SELECT 1 FROM contacto_historia WHERE campo = %(c)s LIMIT 1", {"c": PREFIJO + a["clave"]}).fetchone())


def _usado_en_muestra_activa(conn, clave: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM muestra WHERE estado = 'activa' AND (criterios->'atributos' ? %s"
        " OR criterios->'estratificar_por' ? %s) LIMIT 1", (clave, PREFIJO + clave)).fetchone())


def borrar_atributo(conn, atributo_id: int, actor: str) -> dict:
    a = conn.execute("SELECT * FROM atributo WHERE id = %s FOR UPDATE", (atributo_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "Atributo inexistente")
    if a["sistema"]:
        raise HTTPException(409, f"{a['nombre']} es un atributo del sistema: no se borra")
    if tiene_valores(conn, a):
        raise HTTPException(409, "El atributo tiene valores cargados: desactivalo en lugar de borrarlo")
    if _usado_en_muestra_activa(conn, a["clave"]):
        raise HTTPException(409, "El atributo se usa en una muestra activa")
    conn.execute("DELETE FROM atributo WHERE id = %s", (atributo_id,))
    auditoria.registrar(conn, actor, "atributo.borrar", "atributo", a["clave"])
    return {"borrado": a["clave"]}


def _muestras_activas_con(conn, clave: str) -> list[str]:
    return [f"{r['estudio']} — {r['nombre']}" for r in conn.execute(
        "SELECT m.nombre, e.nombre AS estudio FROM muestra m JOIN estudio e ON e.id = m.estudio_id"
        " WHERE m.estado = 'activa' AND (m.criterios->'atributos' ? %s OR m.criterios->'estratificar_por' ? %s)"
        " ORDER BY m.id", (clave, PREFIJO + clave))]


def fusionar_atributo(conn, atributo_id: int, destino_id: int, actor: str) -> dict:
    """F4.2: fusiona el atributo A dentro de B. Los valores de A pasan a B como historia nueva (fuente «fusion»,
    detalle.fusionado_de = A) y se recalcula el valor vigente de B; los nombres y sinónimos de A pasan a los
    sinónimos de B y las opciones de lista se unifican; A queda inactivo con la nota «fusionado en B»."""
    from . import contactos, empresas

    if atributo_id == destino_id:
        raise HTTPException(422, "Elegí otro atributo para fusionar")
    a = conn.execute("SELECT * FROM atributo WHERE id = %s FOR UPDATE", (atributo_id,)).fetchone()
    b = conn.execute("SELECT * FROM atributo WHERE id = %s FOR UPDATE", (destino_id,)).fetchone()
    if a is None or b is None:
        raise HTTPException(404, "Atributo inexistente")
    if a["sistema"] or b["sistema"]:
        raise HTTPException(409, "Los atributos del sistema no se fusionan")
    if a["fusionado_en"]:
        raise HTTPException(409, f"{a['nombre']} ya fue fusionado en otro atributo")
    if b["fusionado_en"] or not b["activo"]:
        raise HTTPException(409, f"{b['nombre']} no está activo")
    if a["ambito"] != b["ambito"]:
        raise HTTPException(422, "Solo se fusionan atributos del mismo ámbito (de empresa o de contacto)")
    if a["tipo"] != b["tipo"] and b["tipo"] != "texto":
        raise HTTPException(422, f"Tipos incompatibles: {a['tipo']} no entra en {b['tipo']} (sí en un atributo de texto)")
    usan = _muestras_activas_con(conn, a["clave"])
    if usan:
        raise HTTPException(409, f"{a['nombre']} se usa como filtro o estrato de una muestra activa: {', '.join(usan)}")
    # Catálogo: sinónimos y opciones
    sinonimos = sorted({*(b["sinonimos"] or []), *(a["sinonimos"] or []), normalizar(a["nombre"]),
                        a["clave"].replace("_", " ")} - {normalizar(b["nombre"])})
    opciones = list(b["opciones"] or [])
    if b["tipo"] == "lista":
        for o in a["opciones"] or []:
            if not opcion_equivalente(opciones, o):
                opciones.append(o)
    conn.execute("UPDATE atributo SET sinonimos = %s, opciones = %s, actualizado = now() WHERE id = %s",
                 (sinonimos, Jsonb(opciones), b["id"]))
    b = {**b, "opciones": opciones}
    conn.execute("UPDATE atributo SET activo = false, filtrable = false, estratificable = false, fusionado_en = %s,"
                 " nota = %s, actualizado = now() WHERE id = %s", (b["id"], f"fusionado en {b['nombre']}", a["id"]))
    detalle = {"fusionado_de": a["clave"]}
    n_empresas = n_contactos = 0
    if a["ambito"] == "empresa":
        filas = conn.execute("SELECT * FROM empresa_campo_historia WHERE campo = %s ORDER BY id", (PREFIJO + a["clave"],)).fetchall()
        tocadas = set()
        for h in filas:
            conn.execute(
                "INSERT INTO empresa_campo_historia (empresa_id, campo, valor, fuente_tipo, fuente_id, confianza, actor, detalle, fecha)"
                " VALUES (%s,%s,%s,'fusion',NULL,%s,%s,%s,%s)",
                (h["empresa_id"], PREFIJO + b["clave"], h["valor"], h["confianza"], actor,
                 Jsonb({**detalle, "fuente_original": h["fuente_tipo"], "fuente_id_original": h["fuente_id"]}), h["fecha"]))
            tocadas.add(h["empresa_id"])
        for eid in sorted(tocadas):
            empresas.recalcular_atributos(conn, eid, [a["clave"], b["clave"]])
        n_empresas = len(tocadas)
    else:
        for v in conn.execute("SELECT ca.*, c.empresa_id FROM contacto_atributo ca JOIN contacto c ON c.id = ca.contacto_id"
                              " WHERE ca.atributo_id = %s", (a["id"],)).fetchall():
            contacto = {"id": v["contacto_id"], "empresa_id": v["empresa_id"]}
            ya = conn.execute("SELECT 1 FROM contacto_atributo WHERE contacto_id = %s AND atributo_id = %s",
                              (v["contacto_id"], b["id"])).fetchone()
            if not ya:
                aplicar_atributo_contacto(conn, contacto, b["clave"], v["valor_texto"] or v["crudo"], "fusion", None, actor,
                                          detalle)
                n_contactos += 1
            conn.execute("DELETE FROM contacto_atributo WHERE contacto_id = %s AND atributo_id = %s", (v["contacto_id"], a["id"]))
            contactos.historia(conn, contacto, PREFIJO + a["clave"], None, "fusion", None, actor, {"fusionado_en": b["clave"]})
    resumen = {"de": a["clave"], "en": b["clave"], "empresas": n_empresas, "contactos": n_contactos,
               "sinonimos_agregados": sorted(set(sinonimos) - set(b.get("sinonimos") or []))}
    auditoria.registrar(conn, actor, "atributo.fusionar", "atributo", a["clave"], resumen)
    return resumen


def _numero(s: str) -> Decimal | None:
    t = s.strip().replace(" ", "").replace("$", "")
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".") if t.count(",") == 1 else t.replace(",", "")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        n = Decimal(t)
    except InvalidOperation:
        return None
    return n if n.is_finite() else None


def _fecha(s: str) -> dt.date | None:
    t = s.strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?", t)
    if m:
        a, mes, d = int(m[1]), int(m[2]), int(m[3])
    else:
        m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?: .*)?", t)
        if not m:
            return None
        d, mes, a = int(m[1]), int(m[2]), int(m[3])
    try:
        return dt.date(a, mes, d)
    except ValueError:
        return None


def interpretar(atributo: dict, crudo) -> dict:
    """Valor tipado de un atributo. valido=False: no se pudo interpretar (queda como crudo)."""
    s = "" if crudo is None else str(crudo).strip()
    r = {"crudo": s, "texto": None, "numero": None, "fecha": None, "valido": True}
    tipo = atributo["tipo"]
    if tipo == "numero":
        n = _numero(s)
        if n is None:
            r["valido"] = False
        else:
            r["numero"] = n
            r["texto"] = format(n.normalize(), "f")
    elif tipo == "fecha":
        f = _fecha(s)
        if f is None:
            r["valido"] = False
        else:
            r["fecha"] = f
            r["texto"] = f.isoformat()
    elif tipo == "lista":
        if s in (atributo["opciones"] or []):
            r["texto"] = s
        elif opcion_equivalente(atributo["opciones"], s):  # «SI», «si» y «Sí » son la opción «Sí»
            r["texto"] = opcion_equivalente(atributo["opciones"], s)
        else:
            r["valido"] = False
    else:
        s = re.sub(r"\s+", " ", s)
        modo = atributo.get("normalizar_texto") or "ninguna"
        if modo == "mayusculas":
            s = s.upper()
        elif modo == "capital" and s:
            s = s[0].upper() + s[1:].lower()
        r["texto"] = s
    return r


def recalcular_atributos(conn, empresa_id: int, ganadores: dict) -> None:
    """Guarda en empresa_atributo el ganador de cada atributo (ganadores: {'atributo.x': fila|None})."""
    claves = [c[len(PREFIJO):] for c in ganadores]
    if not claves:
        return
    defs = {a["clave"]: a for a in conn.execute("SELECT * FROM atributo WHERE clave = ANY(%s)", (claves,))}
    for campo, g in ganadores.items():
        a = defs.get(campo[len(PREFIJO):])
        if a is None:
            continue
        if a["fusionado_en"]:  # F4.2: sus valores viven en el atributo que lo absorbió
            conn.execute("DELETE FROM empresa_atributo WHERE empresa_id = %s AND atributo_id = %s", (empresa_id, a["id"]))
            continue
        if g is None:
            conn.execute("DELETE FROM empresa_atributo WHERE empresa_id = %s AND atributo_id = %s", (empresa_id, a["id"]))
            continue
        v = interpretar(a, g["valor"])
        conn.execute(
            "INSERT INTO empresa_atributo (empresa_id, atributo_id, valor_texto, valor_numero, valor_fecha, valor_crudo,"
            " fuente_tipo, fuente_id, confianza, fecha) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (empresa_id, atributo_id) DO UPDATE SET valor_texto = EXCLUDED.valor_texto,"
            " valor_numero = EXCLUDED.valor_numero, valor_fecha = EXCLUDED.valor_fecha, valor_crudo = EXCLUDED.valor_crudo,"
            " fuente_tipo = EXCLUDED.fuente_tipo, fuente_id = EXCLUDED.fuente_id, confianza = EXCLUDED.confianza,"
            " fecha = EXCLUDED.fecha",
            (empresa_id, a["id"], v["texto"], v["numero"], v["fecha"], v["crudo"], g["fuente_tipo"], g["fuente_id"],
             g["confianza"], g["fecha"]))


def atributos_de_empresa(conn, empresa_id: int) -> list[dict]:
    return conn.execute(
        "SELECT a.clave, a.nombre, a.tipo, a.activo, ea.valor_texto, ea.valor_numero, ea.valor_fecha, ea.valor_crudo,"
        " (ea.valor_texto IS NULL) AS invalido, ea.fuente_tipo, ea.fuente_id, ea.confianza, ea.fecha"
        " FROM empresa_atributo ea JOIN atributo a ON a.id = ea.atributo_id WHERE ea.empresa_id = %s ORDER BY a.nombre",
        (empresa_id,)).fetchall()


# ─────────────────────────────────────────────────────────────
# Orígenes de teléfono
# ─────────────────────────────────────────────────────────────

def origenes(conn, activos: bool | None = None) -> list[dict]:
    return conn.execute(
        "SELECT o.*, (SELECT count(*) FROM telefono_vinculo_origen x WHERE x.origen_id = o.id) AS n_vinculos"
        " FROM origen_telefono o WHERE (%s::boolean IS NULL OR o.activo = %s) ORDER BY o.prioridad, o.nombre",
        (activos, activos)).fetchall()


def origen_por_codigo(conn, codigo: str) -> dict | None:
    return conn.execute("SELECT * FROM origen_telefono WHERE codigo = %s", (codigo,)).fetchone()


def crear_origen(conn, datos: dict, actor: str) -> dict:
    nombre = str(datos.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(422, "Indicá el nombre del origen")
    codigo = str(datos.get("codigo") or "").strip() or slug(nombre)
    if not CLAVE.match(codigo):
        raise HTTPException(422, "El código va en minúsculas, sin espacios ni tildes y empieza con una letra (p. ej. guia_tel)")
    if origen_por_codigo(conn, codigo):
        raise HTTPException(409, f"Ya existe un origen con el código {codigo}")
    if datos.get("prioridad") is not None:
        prioridad = int(datos["prioridad"])
    else:  # al final de la lista, antes de "Sin dato"
        prioridad = conn.execute("SELECT coalesce(max(prioridad), 20) + 10 AS p FROM origen_telefono"
                                 " WHERE codigo <> 'sin_dato'").fetchone()["p"]
    o = conn.execute("INSERT INTO origen_telefono (codigo, nombre, prioridad, activo) VALUES (%s,%s,%s,%s) RETURNING *",
                     (codigo, nombre, prioridad, datos.get("activo") is not False)).fetchone()
    auditoria.registrar(conn, actor, "origen_telefono.crear", "origen_telefono", codigo,
                        {"nombre": nombre, "prioridad": prioridad})
    return o


def actualizar_origen(conn, origen_id: int, datos: dict, actor: str) -> dict:
    o = conn.execute("SELECT * FROM origen_telefono WHERE id = %s FOR UPDATE", (origen_id,)).fetchone()
    if o is None:
        raise HTTPException(404, "Origen inexistente")
    if datos.get("codigo") not in (None, o["codigo"]):
        raise HTTPException(422, "El código de un origen no se puede cambiar")
    nombre = str(datos.get("nombre") or o["nombre"]).strip()
    activo = o["activo"] if datos.get("activo") is None else bool(datos["activo"])
    if o["sistema"] and not activo:
        raise HTTPException(409, "Los orígenes de sistema no se pueden desactivar")
    prioridad = int(datos["prioridad"]) if datos.get("prioridad") is not None else o["prioridad"]
    o = conn.execute("UPDATE origen_telefono SET nombre = %s, prioridad = %s, activo = %s WHERE id = %s RETURNING *",
                     (nombre, prioridad, activo, origen_id)).fetchone()
    auditoria.registrar(conn, actor, "origen_telefono.editar", "origen_telefono", o["codigo"],
                        {"nombre": nombre, "prioridad": prioridad, "activo": activo})
    return o


def ordenar_origenes(conn, codigos: list[str], actor: str) -> list[dict]:
    """Reasigna las prioridades según el orden dado (10, 20, 30…). 'Sin dato' queda siempre al final."""
    existentes = {o["codigo"] for o in conn.execute("SELECT codigo FROM origen_telefono")}
    desconocidos = set(codigos) - existentes
    if desconocidos:
        raise HTTPException(422, f"Orígenes desconocidos: {', '.join(sorted(desconocidos))}")
    orden = [c for c in codigos if c != SIN_DATO]
    for i, c in enumerate(orden):
        conn.execute("UPDATE origen_telefono SET prioridad = %s WHERE codigo = %s", ((i + 1) * 10, c))
    conn.execute("UPDATE origen_telefono SET prioridad = 1000 WHERE codigo = %s", (SIN_DATO,))
    auditoria.registrar(conn, actor, "origen_telefono.ordenar", "origen_telefono", None, {"orden": orden})
    return origenes(conn)


def borrar_origen(conn, origen_id: int, actor: str) -> dict:
    o = conn.execute("SELECT * FROM origen_telefono WHERE id = %s FOR UPDATE", (origen_id,)).fetchone()
    if o is None:
        raise HTTPException(404, "Origen inexistente")
    if o["sistema"]:
        raise HTTPException(409, "Los orígenes de sistema no se pueden borrar")
    if conn.execute("SELECT 1 FROM telefono_vinculo_origen WHERE origen_id = %s LIMIT 1", (origen_id,)).fetchone():
        raise HTTPException(409, "El origen tiene teléfonos cargados: desactivalo en lugar de borrarlo")
    conn.execute("DELETE FROM origen_telefono WHERE id = %s", (origen_id,))
    auditoria.registrar(conn, actor, "origen_telefono.borrar", "origen_telefono", o["codigo"])
    return {"borrado": o["codigo"]}


def registrar_origen(conn, vinculo_id: int, codigo: str, fuente_tipo: str, fuente_id) -> bool:
    """Evidencia del origen de un vínculo. Devuelve True si es nueva (único por vínculo y origen)."""
    r = conn.execute(
        "INSERT INTO telefono_vinculo_origen (vinculo_id, origen_id, fuente_tipo, fuente_id)"
        " SELECT %s, id, %s, %s FROM origen_telefono WHERE codigo = %s ON CONFLICT DO NOTHING RETURNING vinculo_id",
        (vinculo_id, fuente_tipo, fuente_id, codigo)).fetchone()
    return r is not None


# ─────────────────────────────────────────────────────────────
# Atributos de contacto (F3.3)
# ─────────────────────────────────────────────────────────────

def atributos_de_contactos(conn, contacto_ids: list[int]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    if not contacto_ids:
        return out
    for r in conn.execute(
            "SELECT ca.contacto_id, a.id AS atributo_id, a.clave, a.nombre, a.tipo, ca.valor_texto, ca.valor_numero,"
            " ca.valor_fecha, ca.crudo, ca.fuente_tipo, ca.fuente_id, ca.actualizado"
            " FROM contacto_atributo ca JOIN atributo a ON a.id = ca.atributo_id"
            " WHERE ca.contacto_id = ANY(%s) ORDER BY a.nombre", (contacto_ids,)):
        out.setdefault(r["contacto_id"], []).append(r)
    return out


def aplicar_atributo_contacto(conn, contacto: dict, clave: str, crudo, fuente_tipo: str, fuente_id, actor: str | None,
                              detalle=None) -> bool:
    """Guarda el valor de un atributo de contacto (el más reciente gana) con su historia. True si cambió."""
    from . import contactos

    a = conn.execute("SELECT * FROM atributo WHERE clave = %s AND ambito = 'contacto'", (clave,)).fetchone()
    if a is None or crudo is None or str(crudo).strip() == "":
        return False
    v = interpretar(a, crudo)
    actual = conn.execute("SELECT * FROM contacto_atributo WHERE contacto_id = %s AND atributo_id = %s",
                          (contacto["id"], a["id"])).fetchone()
    if actual and actual["valor_texto"] == v["texto"] and actual["crudo"] == v["crudo"]:
        return False
    conn.execute(
        "INSERT INTO contacto_atributo (contacto_id, atributo_id, valor_texto, valor_numero, valor_fecha, crudo,"
        " fuente_tipo, fuente_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (contacto_id, atributo_id) DO UPDATE SET"
        " valor_texto = EXCLUDED.valor_texto, valor_numero = EXCLUDED.valor_numero, valor_fecha = EXCLUDED.valor_fecha,"
        " crudo = EXCLUDED.crudo, fuente_tipo = EXCLUDED.fuente_tipo, fuente_id = EXCLUDED.fuente_id, actualizado = now()",
        (contacto["id"], a["id"], v["texto"], v["numero"], v["fecha"], v["crudo"], fuente_tipo, fuente_id))
    contactos.historia(conn, contacto, PREFIJO + clave, v["texto"] if v["valido"] else v["crudo"], fuente_tipo, fuente_id,
                       actor, {**(detalle or {}), **({} if v["valido"] else {"invalido": True})})
    return True


def quitar_atributo_contacto(conn, contacto: dict, clave: str, fuente_tipo: str, fuente_id, actor: str) -> bool:
    from . import contactos

    a = conn.execute("SELECT * FROM atributo WHERE clave = %s AND ambito = 'contacto'", (clave,)).fetchone()
    if a is None:
        return False
    r = conn.execute("DELETE FROM contacto_atributo WHERE contacto_id = %s AND atributo_id = %s RETURNING 1",
                     (contacto["id"], a["id"])).fetchone()
    if r:
        contactos.historia(conn, contacto, PREFIJO + clave, None, fuente_tipo, fuente_id, actor)
    return bool(r)
