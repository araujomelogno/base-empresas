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

from . import auditoria, catalogos, config, empresas, intermediarios, lectores, rut as rutmod, storage, tareas
from . import telefonos as telmod
from .util import dominio, razon_normalizada, sin_tildes, texto

CAMPOS_NUCLEO = (
    "rut", "razon_social", "fantasia", "naturaleza", "ciiu", "tamano", "departamento", "localidad",
    "direccion", "web", "email", "estado",
)
CAMPOS_SUCURSAL = ("sucursal_direccion", "sucursal_departamento", "sucursal_localidad")
CAMPOS_MAPEO = CAMPOS_NUCLEO + CAMPOS_SUCURSAL
# Los contactos no vienen en las bases: se generan en el campo (EC_RESP_* del .sav). Una
# plantilla vieja que los tenga se sigue abriendo y estos campos se ignoran con un aviso.
CAMPOS_CONTACTO = ("contacto_nombre", "contacto_cargo", "contacto_area", "contacto_email", "contacto_telefono")
CLAVES_MAPEO = set(CAMPOS_MAPEO) | {"telefonos", "origenes_telefono", "origen_defecto", "atributos", "traducciones"}

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
    "sucursal_direccion": ["direccion sucursal", "sucursal direccion", "domicilio sucursal", "direccion local"],
    "sucursal_departamento": ["departamento sucursal", "sucursal departamento"],
    "sucursal_localidad": ["localidad sucursal", "sucursal localidad", "ciudad sucursal"],
}
_TEL = re.compile(r"^(tel|telefono|telefonos|celular|cel|movil|fono|phone|tel fijo|telefono fijo)( ?(\d+))?$")
_ORIGEN = re.compile(r"^(origen|fuente)( (del )?(tel|telefono|telefonos|numero|nro))?( ?(\d+))?$")


def _norm_col(c: str) -> str:
    c = sin_tildes(str(c).lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]", " ", c)).strip()


def sugerir_mapeo(columnas: list[str], atributos: list[dict] | None = None) -> dict:
    """Mapeo sugerido por nombre de columna: solo los campos que se reconocen en el archivo."""
    mapeo: dict = {"telefonos": []}
    norm = {c: _norm_col(c) for c in columnas}
    usadas = set()
    origenes = {c: _ORIGEN.match(norm[c]) for c in columnas}
    origenes = {c: m for c, m in origenes.items() if m}
    usadas |= set(origenes)
    for campo, sinos in SINONIMOS.items():
        for s in sinos:  # el orden de sinónimos marca la preferencia
            col = next((c for c in columnas if norm[c] == s and c not in usadas), None)
            if col:
                mapeo[campo] = col
                usadas.add(col)
                break
    for a in atributos or []:
        nombres = [a["clave"].replace("_", " "), catalogos.normalizar(a["nombre"]), *a["sinonimos"]]
        col = next((c for n in nombres for c in columnas if norm[c] == n and c not in usadas), None)
        if col:
            mapeo.setdefault("atributos", {})[a["clave"]] = col
            usadas.add(col)
    numeros_tel = {}
    for c in columnas:
        m = _TEL.match(norm[c])
        if c not in usadas and m:
            mapeo["telefonos"].append(c)
            numeros_tel[c] = m.group(3)
    # Emparejamiento sugerido del origen: «Origen 1» ↔ «Tel 1»; una sola columna sin número, para todos
    if origenes and mapeo["telefonos"]:
        por_numero = {m.group(6): c for c, m in origenes.items() if m.group(6)}
        sin_numero = [c for c, m in origenes.items() if not m.group(6)]
        ot = {}
        for t in mapeo["telefonos"]:
            col = por_numero.get(numeros_tel.get(t)) or (sin_numero[0] if len(sin_numero) == 1 else None)
            if col is None and len(origenes) == 1:
                col = next(iter(origenes))
            if col:
                ot[t] = {"columna": col}
        if ot:
            mapeo["origenes_telefono"] = ot
    return mapeo


def columnas_de_mapeo(mapeo: dict) -> set[str]:
    cols = set()
    for k in CAMPOS_MAPEO:
        if mapeo.get(k):
            cols.add(mapeo[k])
    cols |= set(mapeo.get("telefonos") or [])
    for o in (mapeo.get("origenes_telefono") or {}).values():
        if o.get("columna"):
            cols.add(o["columna"])
    cols |= {c for c in (mapeo.get("atributos") or {}).values() if c}
    return cols


def limpiar_mapeo(mapeo: dict) -> tuple[dict, list[str]]:
    """Quita los campos vacíos y los de contacto (con aviso). Acepta telefonos como lista de columnas
    o de objetos {columna, origen_columna | origen_fijo}."""
    avisos = []
    m = {}
    contacto = [k for k in CAMPOS_CONTACTO if (mapeo or {}).get(k)]
    if contacto:
        avisos.append("La plantilla tenía campos de contacto (" + ", ".join(contacto) + "): se ignoran. "
                      "Los contactos se cargan con las respuestas del campo (.sav).")
    for k, v in (mapeo or {}).items():
        if k in CAMPOS_CONTACTO or not v:
            continue
        m[k] = v
    tels, ot = [], dict(m.get("origenes_telefono") or {})
    for t in m.get("telefonos") or []:
        if isinstance(t, dict):
            col = t.get("columna")
            if not col:
                continue
            tels.append(col)
            if t.get("origen_columna"):
                ot[col] = {"columna": t["origen_columna"]}
            elif t.get("origen_fijo"):
                ot[col] = {"fijo": t["origen_fijo"]}
        else:
            tels.append(t)
    m["telefonos"] = tels
    ot = {k: v for k, v in ot.items() if k in tels and v and (v.get("columna") or v.get("fijo"))}
    if ot:
        m["origenes_telefono"] = ot
    else:
        m.pop("origenes_telefono", None)
    if m.get("atributos"):
        m["atributos"] = {k: v for k, v in m["atributos"].items() if v}
    return m, avisos


def _validar_mapeo(conn, mapeo: dict, columnas: list[str]):
    if not mapeo.get("rut"):
        raise HTTPException(422, "El mapeo tiene que indicar la columna del RUT")
    for campo in mapeo:
        if campo not in CLAVES_MAPEO:
            raise HTTPException(422, f"Campo de destino desconocido: {campo}")
    for c in columnas_de_mapeo(mapeo):
        if c not in columnas:
            raise HTTPException(422, f"La columna '{c}' no está en el archivo")
    activos = {o["codigo"] for o in catalogos.origenes(conn, activos=True)}
    if mapeo.get("telefonos"):
        if not mapeo.get("origen_defecto"):
            raise HTTPException(422, "Elegí el origen por defecto de los teléfonos de esta carga")
        if mapeo["origen_defecto"] not in activos:
            raise HTTPException(422, f"Origen de teléfono desconocido o inactivo: {mapeo['origen_defecto']}")
        for col, o in (mapeo.get("origenes_telefono") or {}).items():
            if o.get("fijo") and o["fijo"] not in activos:
                raise HTTPException(422, f"Origen de teléfono desconocido o inactivo: {o['fijo']}")
    defs = {a["clave"]: a for a in catalogos.atributos(conn)}
    for clave in mapeo.get("atributos") or {}:
        if clave not in defs:
            raise HTTPException(422, f"Atributo desconocido: {clave}")
        if not defs[clave]["activo"]:
            raise HTTPException(422, f"El atributo {defs[clave]['nombre']} está desactivado")
    tr = mapeo.get("traducciones") or {}
    for valor, cod in (tr.get("origen") or {}).items():
        if cod is not None and cod not in activos:
            raise HTTPException(422, f"La traducción de «{valor}» apunta a un origen desconocido o inactivo: {cod}")
    for clave, col in (mapeo.get("atributos") or {}).items():
        for valor, op in (tr.get(catalogos.PREFIJO + clave) or {}).items():
            if op is not None and op not in (defs[clave]["opciones"] or []):
                raise HTTPException(422, f"La traducción de «{valor}» no es una opción de {defs[clave]['nombre']}")


def _leer(conn, archivo_id: int):
    archivo = conn.execute("SELECT * FROM archivo WHERE id = %s", (archivo_id,)).fetchone()
    if archivo is None:
        raise HTTPException(404, "Archivo inexistente")
    columnas, filas, meta = lectores.leer_tabla(storage.leer(archivo), archivo["tipo"])
    return archivo, columnas, filas


def analizar(conn, archivo: dict, tipo_fuente: str | None) -> dict:
    columnas, filas, _ = lectores.leer_tabla(storage.leer(archivo), archivo["tipo"])
    atributos = catalogos.atributos(conn, activos=True)
    plantilla = None
    if tipo_fuente:
        plantilla = conn.execute("SELECT mapeo FROM carga_plantilla WHERE tipo_fuente = %s", (tipo_fuente,)).fetchone()
    avisos = []
    if plantilla:
        mapeo_p, avisos = limpiar_mapeo(plantilla["mapeo"])
    if plantilla and columnas_de_mapeo(mapeo_p) <= set(columnas):
        mapeo, origen = mapeo_p, "plantilla"
        activos = {a["clave"] for a in atributos}
        quitados = [k for k in (mapeo.get("atributos") or {}) if k not in activos]
        if quitados:
            mapeo["atributos"] = {k: v for k, v in mapeo["atributos"].items() if k in activos}
            avisos.append(f"Atributos de la plantilla que ya no están activos: {', '.join(quitados)}")
    else:
        mapeo, origen = sugerir_mapeo(columnas, atributos), "sugerido"
        if plantilla:  # la plantilla no encaja con estas columnas, pero sus traducciones sirven
            for k in ("traducciones", "origen_defecto"):
                if mapeo_p.get(k):
                    mapeo[k] = mapeo_p[k]
    return {
        "archivo_id": archivo["id"], "nombre": archivo["nombre"], "tipo": archivo["tipo"],
        "columnas": columnas, "n_filas": len(filas), "ejemplos": filas[:8],
        "mapeo": mapeo, "origen_mapeo": origen, "avisos": avisos,
        "campos": {"empresa": CAMPOS_NUCLEO, "sucursal": CAMPOS_SUCURSAL},
        "atributos": atributos, "origenes": catalogos.origenes(conn, activos=True),
        "plantillas": [r["tipo_fuente"] for r in conn.execute("SELECT tipo_fuente FROM carga_plantilla ORDER BY 1")],
    }


def _valor(fila: dict, mapeo: dict, campo: str):
    col = mapeo.get(campo)
    return texto(fila.get(col)) if col else None


# ─────────────────────────────────────────────────────────────
# Traducción de valores (C5): origen del teléfono y atributos de lista
# ─────────────────────────────────────────────────────────────

class Traductor:
    """Resuelve el origen de cada teléfono y el valor de los atributos de una fila."""

    def __init__(self, conn, mapeo: dict):
        self.mapeo = mapeo
        self.origenes = catalogos.origenes(conn, activos=True)
        self.exacto_origen = {}
        for o in self.origenes:
            self.exacto_origen[o["codigo"]] = o["codigo"]
            self.exacto_origen[o["nombre"]] = o["codigo"]
        self.defs = {a["clave"]: a for a in catalogos.atributos(conn)}
        self.tr = mapeo.get("traducciones") or {}

    def origen(self, fila: dict, col_tel: str) -> tuple[str, str | None]:
        """(código de origen, valor crudo sin traducir si lo hubo)."""
        spec = (self.mapeo.get("origenes_telefono") or {}).get(col_tel) or {}
        defecto = self.mapeo.get("origen_defecto") or catalogos.SIN_DATO
        if spec.get("fijo"):
            return spec["fijo"], None
        if not spec.get("columna"):
            return defecto, None
        crudo = texto(fila.get(spec["columna"]))
        if not crudo:
            return defecto, None
        if crudo in self.exacto_origen:
            return self.exacto_origen[crudo], None
        trad = self.tr.get("origen") or {}
        if crudo in trad:
            return trad[crudo] or catalogos.SIN_DATO, None
        return defecto, crudo

    def atributo(self, clave: str, crudo: str) -> dict | None:
        """{"valor", "invalido"} o None si se tradujo como "sin dato"."""
        a = self.defs[clave]
        if a["tipo"] == "lista" and crudo not in (a["opciones"] or []):
            trad = self.tr.get(catalogos.PREFIJO + clave) or {}
            if crudo in trad:
                if trad[crudo] is None:
                    return None
                crudo = trad[crudo]
        v = catalogos.interpretar(a, crudo)
        return {"valor": v["texto"], "invalido": False} if v["valido"] else {"valor": v["crudo"], "invalido": True}


def _sugerencia(valor: str, opciones: list[tuple[str, str]]) -> str | None:
    """opciones: [(valor_destino, texto_comparable)]. Sin mayúsculas, tildes ni espacios; nunca se aplica sola."""
    n = catalogos.normalizar(valor)
    if not n:
        return None
    for destino, t in opciones:
        if catalogos.normalizar(t) == n:
            return destino
    for destino, t in opciones:
        nt = catalogos.normalizar(t)
        if len(nt) >= 4 and len(n) >= 4 and (nt in n or n in nt):
            return destino
    return None


def valores(conn, archivo_id: int, mapeo: dict) -> dict:
    """Valores distintos de las columnas de origen y de atributos de lista que no coinciden
    exactamente con el catálogo, con cuántas filas tiene cada uno y una traducción sugerida."""
    mapeo, _ = limpiar_mapeo(mapeo)
    _, columnas, filas = _leer(conn, archivo_id)
    for c in columnas_de_mapeo(mapeo):
        if c not in columnas:
            raise HTTPException(422, f"La columna '{c}' no está en el archivo")
    t = Traductor(conn, mapeo)
    tr = mapeo.get("traducciones") or {}
    salida = {"origen": [], "atributos": []}
    cols_origen = sorted({o["columna"] for o in (mapeo.get("origenes_telefono") or {}).values() if o.get("columna")})
    if cols_origen:
        cuenta = Counter(texto(f.get(c)) for f in filas for c in cols_origen)
        cuenta.pop(None, None)
        cuenta.pop("", None)
        opciones = [(o["codigo"], o["codigo"]) for o in t.origenes] + [(o["codigo"], o["nombre"]) for o in t.origenes]
        for v, n in cuenta.most_common():
            if v in t.exacto_origen:
                continue
            ya = (tr.get("origen") or {})
            salida["origen"].append({"valor": v, "filas": n, "sugerido": _sugerencia(v, opciones),
                                     "traduccion": ya.get(v), "traducido": v in ya})
    for clave, col in (mapeo.get("atributos") or {}).items():
        a = t.defs.get(clave)
        if not a or a["tipo"] != "lista":
            continue
        cuenta = Counter(texto(f.get(col)) for f in filas)
        cuenta.pop(None, None)
        cuenta.pop("", None)
        ya = tr.get(catalogos.PREFIJO + clave) or {}
        pendientes = [{"valor": v, "filas": n, "sugerido": _sugerencia(v, [(o, o) for o in a["opciones"]]),
                       "traduccion": ya.get(v), "traducido": v in ya}
                      for v, n in cuenta.most_common() if v not in a["opciones"]]
        if pendientes:
            salida["atributos"].append({"clave": clave, "nombre": a["nombre"], "opciones": a["opciones"],
                                        "valores": pendientes})
    salida["pendientes"] = sum(1 for x in salida["origen"] if not x["traducido"]) + sum(
        1 for a in salida["atributos"] for x in a["valores"] if not x["traducido"])
    return salida


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
    traductor = Traductor(conn, mapeo)
    c = Counter()
    por_telefonos = Counter()
    por_origen: dict[str, Counter] = {}
    por_atributo: dict[str, Counter] = {k: Counter() for k in (mapeo.get("atributos") or {})}
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
        datos = {k: _valor(fila, mapeo, k) for k in CAMPOS_MAPEO}
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
            crudos = telmod.separar(fila.get(col))
            if not crudos:
                continue
            origen, sin_traducir = traductor.origen(fila, col)
            if sin_traducir:
                c["origen_sin_traducir"] += len(crudos)
            for crudo in crudos:  # varios números en una celda toman el origen de esa fila y columna
                tels.append((telmod.normalizar(crudo, prefijos), origen))
        n_tels = len(tels)
        por_telefonos["0" if n_tels == 0 else "1" if n_tels == 1 else "2" if n_tels == 2 else "3+"] += 1
        attrs = {}
        for clave, col in (mapeo.get("atributos") or {}).items():
            crudo = texto(fila.get(col))
            if not crudo:
                continue
            v = traductor.atributo(clave, crudo)
            if v is None:
                por_atributo[clave]["sin_dato"] += 1
                continue
            attrs[clave] = v
            por_atributo[clave]["invalidos" if v["invalido"] else "cargados"] += 1

        emp = conn.execute("SELECT * FROM empresa WHERE rut = %s", (r,)).fetchone()
        while emp and emp["baja"] == "fusionada" and emp["fusionada_en"]:
            emp = conn.execute("SELECT * FROM empresa WHERE id = %s", (emp["fusionada_en"],)).fetchone()
        es_alta = False
        if emp is None:
            if carga["regla_fusion"] != "rut":
                cand = _buscar_candidata(conn, carga["regla_fusion"], datos, [t for t, _ in tels])
                if cand is not None:
                    c["revision"] += 1
                    if real:
                        conn.execute(
                            "INSERT INTO revision_fusion (carga_id, fila, datos, criterio, candidata_id)"
                            " VALUES (%s,%s,%s,%s,%s)",
                            (cid, nfila, Jsonb({"rut": r, **{k: v for k, v in datos.items() if v},
                                                "telefonos": [{"crudo": t.crudo, "origen": o} for t, o in tels],
                                                "atributos": attrs}),
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
                                   telefonos_tocados, attrs, por_origen)
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
    conteos["filas_por_telefonos"] = {k: por_telefonos.get(k, 0) for k in ("0", "1", "2", "3+")}
    conteos["telefonos_por_origen"] = {o: {"nuevos": n.get("nuevos", 0), "existentes": n.get("existentes", 0)}
                                       for o, n in sorted(por_origen.items())}
    conteos["atributos"] = {k: {"cargados": n.get("cargados", 0), "invalidos": n.get("invalidos", 0),
                                "sin_dato": n.get("sin_dato", 0)} for k, n in por_atributo.items()}
    return conteos, rechazos


def aplicar_fila(conn, emp, datos, tels, cid, confianza, actor, c, conflictos_muestra, telefonos_tocados,
                 atributos=None, por_origen=None) -> bool:
    """tels: [(Telefono normalizado, código de origen)]; atributos: {clave: {"valor", "invalido"}}."""
    cambios, conflictos = empresas.aplicar_valores(conn, emp["id"], datos, "carga", cid, confianza, actor)
    hubo = bool(cambios)
    if atributos:
        cambios_a, conflictos_a = empresas.aplicar_atributos(conn, emp["id"], atributos, "carga", cid, confianza, actor)
        hubo = hubo or bool(cambios_a)
        conflictos = {**conflictos, **conflictos_a}
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
    for t, origen in tels:
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
        _, nuevo = empresas.vincular(conn, fila_tel["id"], emp["id"], "carga", cid, actor, sucursal_id=sucursal_id,
                                     origen=origen)
        if por_origen is not None:
            por_origen.setdefault(origen, Counter())["nuevos" if nuevo else "existentes"] += 1
        if nuevo:
            c["vinculos_nuevos"] += 1
            hubo = True
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
    mapeo, _ = limpiar_mapeo(mapeo)
    _validar_mapeo(conn, mapeo, columnas)
    pend = valores(conn, archivo_id, mapeo)
    if pend["pendientes"]:
        ejemplos = [x["valor"] for x in pend["origen"] if not x["traducido"]] + [
            x["valor"] for a in pend["atributos"] for x in a["valores"] if not x["traducido"]]
        raise HTTPException(422, f"Hay {pend['pendientes']} valores sin traducir al catálogo (por ejemplo: "
                                 f"{', '.join(ejemplos[:5])}). Elegí para cada uno un valor del catálogo o «sin dato».")
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
    if carga["estado"] == "descartada":
        raise HTTPException(409, "La carga ya fue descartada")
    if carga["estado"] in ("analizando", "preview", "error"):
        # Nunca se aplicó: se descarta (distinto de deshacer una carga confirmada)
        conn.execute("UPDATE carga SET estado = 'descartada', descartada = now() WHERE id = %s", (carga_id,))
        auditoria.registrar(conn, actor, "carga.descartar", "carga", carga_id)
        return {"estado": "descartada", "empresas_anuladas": 0, "empresas_recalculadas": 0}
    if carga["estado"] != "confirmada":
        raise HTTPException(409, f"No se puede deshacer una carga en estado {carga['estado']}")
    ids = empresas_de_carga(conn, carga_id)
    en_muestra = conn.execute(
        "SELECT count(DISTINCT empresa_id) AS n FROM muestra_item WHERE empresa_id = ANY(%s)", (ids,)).fetchone()["n"]
    if en_muestra:
        raise HTTPException(409, f"No se puede deshacer: {en_muestra} empresas de esta carga ya entraron a una muestra")
    conn.execute("UPDATE carga SET estado = 'deshecha', deshecha = now() WHERE id = %s", (carga_id,))
    # El origen que esta carga sumó a vínculos que ya existían
    conn.execute("DELETE FROM telefono_vinculo_origen WHERE fuente_tipo = 'carga' AND fuente_id = %s", (carga_id,))
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
    resumen = {"estado": "deshecha", "empresas_anuladas": anuladas, "empresas_recalculadas": len(ids), "vinculos_borrados": len(vincs)}
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
        " c.confirmada, c.deshecha, c.descartada, a.nombre AS archivo_nombre FROM carga c JOIN archivo a ON a.id = c.archivo_id"
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
    tels = [(telmod.normalizar(t), catalogos.SIN_DATO) if isinstance(t, str)
            else (telmod.normalizar(t["crudo"]), t.get("origen") or catalogos.SIN_DATO) for t in datos.pop("telefonos", [])]
    atributos = datos.pop("atributos", None) or {}
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
        aplicar_fila(conn, emp, datos, tels, carga["id"], carga["confianza"], actor, c, [], tocados, atributos)
        _, cfg = config.vigente(conn)
        if tocados:
            intermediarios.detectar(conn, cfg["umbral_intermediario"], sorted(tocados), actor)
    conn.execute("UPDATE revision_fusion SET estado = %s, resuelto_por = %s, resuelto = now() WHERE id = %s",
                 (accion, actor, revision_id))
    auditoria.registrar(conn, actor, f"revision.{accion}", "revision_fusion", revision_id,
                        {"rut": datos.get("rut"), "candidata_id": r["candidata_id"]})
    return {"id": revision_id, "estado": accion}
