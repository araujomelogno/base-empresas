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

from . import auditoria, catalogos, config, contactos, empresas, intermediarios, lectores, provisorias, rut as rutmod, storage, tareas
from . import telefonos as telmod
from .util import dominio, razon_normalizada, sin_tildes, texto

CAMPOS_NUCLEO = (
    "rut", "razon_social", "fantasia", "naturaleza", "ciiu", "tamano", "departamento", "localidad",
    "direccion", "web", "email", "estado",
)
CAMPOS_SUCURSAL = ("sucursal_direccion", "sucursal_departamento", "sucursal_localidad")
CAMPOS_MAPEO = CAMPOS_NUCLEO + CAMPOS_SUCURSAL
# D-d (cambia lo decidido antes): los contactos pueden venir en una carga, uno por fila (F3.2)
CAMPOS_CONTACTO = ("contacto_nombre", "contacto_cargo", "contacto_area", "contacto_email", "contacto_telefono")
CLAVES_MAPEO = set(CAMPOS_MAPEO) | set(CAMPOS_CONTACTO) | {
    "telefonos", "origenes_telefono", "origen_defecto", "atributos", "traducciones", "contacto_atributos"}

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
    "contacto_nombre": ["contacto", "nombre contacto", "nombre del contacto", "persona de contacto", "responsable",
                        "contacto nombre"],
    "contacto_cargo": ["cargo", "cargo contacto", "cargo del contacto", "puesto"],
    "contacto_area": ["area", "area contacto", "area del contacto", "sector"],
    "contacto_email": ["email contacto", "mail contacto", "correo contacto", "e mail contacto", "email del contacto"],
    "contacto_telefono": ["tel contacto", "telefono contacto", "celular contacto", "telefono del contacto", "cel contacto"],
}
_EMAIL_GENERICO = ("email", "mail", "correo", "e mail", "correo electronico")
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
    # Con un contacto en el archivo, un «Email» genérico es el del contacto si no hay otro
    if mapeo.get("contacto_nombre") and mapeo.get("email") and not mapeo.get("contacto_email") \
            and norm[mapeo["email"]] in _EMAIL_GENERICO:
        mapeo["contacto_email"] = mapeo.pop("email")
    if not mapeo.get("contacto_nombre"):  # cargo, área… sueltos no son de un contacto
        for k in ("contacto_cargo", "contacto_area", "contacto_email", "contacto_telefono"):
            if mapeo.get(k):
                usadas.discard(mapeo.pop(k))
    for a in atributos or []:
        if a.get("ambito", "empresa") == "contacto" and not mapeo.get("contacto_nombre"):
            continue
        nombres = [a["clave"].replace("_", " "), catalogos.normalizar(a["nombre"]), *a["sinonimos"]]
        col = next((c for n in nombres for c in columnas if norm[c] == n and c not in usadas), None)
        if col:
            destino = "contacto_atributos" if a.get("ambito") == "contacto" else "atributos"
            mapeo.setdefault(destino, {})[a["clave"]] = col
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
    for k in CAMPOS_MAPEO + CAMPOS_CONTACTO:
        if mapeo.get(k):
            cols.add(mapeo[k])
    cols |= set(mapeo.get("telefonos") or [])
    cols |= {c for c in (mapeo.get("contacto_atributos") or {}).values() if c}
    for o in (mapeo.get("origenes_telefono") or {}).values():
        if o.get("columna"):
            cols.add(o["columna"])
    cols |= {c for c in (mapeo.get("atributos") or {}).values() if c}
    return cols


def limpiar_mapeo(mapeo: dict) -> tuple[dict, list[str]]:
    """Quita los campos vacíos. Acepta telefonos como lista de columnas o de objetos
    {columna, origen_columna | origen_fijo}. Los campos de contacto se usan (D-d, F3.2)."""
    avisos = []
    m = {}
    for k, v in (mapeo or {}).items():
        if not v:
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
    ot = {k: v for k, v in ot.items() if (k in tels or k == m.get("contacto_telefono"))
          and v and (v.get("columna") or v.get("fijo"))}
    if ot:
        m["origenes_telefono"] = ot
    else:
        m.pop("origenes_telefono", None)
    for k in ("atributos", "contacto_atributos"):
        if m.get(k):
            m[k] = {a: v for a, v in m[k].items() if v}
    return m, avisos


def _validar_mapeo(conn, mapeo: dict, columnas: list[str], destino: str = "definitiva"):
    if not mapeo.get("rut") and destino != "provisoria":
        raise HTTPException(422, "El mapeo tiene que indicar la columna del RUT (o elegí el destino «Base provisoria»)")
    for campo in mapeo:
        if campo not in CLAVES_MAPEO:
            raise HTTPException(422, f"Campo de destino desconocido: {campo}")
    for c in columnas_de_mapeo(mapeo):
        if c not in columnas:
            raise HTTPException(422, f"La columna '{c}' no está en el archivo")
    contacto = [k for k in CAMPOS_CONTACTO if mapeo.get(k)] + list(mapeo.get("contacto_atributos") or {})
    if contacto and not mapeo.get("contacto_nombre"):
        raise HTTPException(422, "Para cargar contactos, indicá la columna con el nombre del contacto")
    activos = {o["codigo"] for o in catalogos.origenes(conn, activos=True)}
    if mapeo.get("telefonos") or mapeo.get("contacto_telefono"):
        if not mapeo.get("origen_defecto"):
            raise HTTPException(422, "Elegí el origen por defecto de los teléfonos de esta carga")
        if mapeo["origen_defecto"] not in activos:
            raise HTTPException(422, f"Origen de teléfono desconocido o inactivo: {mapeo['origen_defecto']}")
        for col, o in (mapeo.get("origenes_telefono") or {}).items():
            if o.get("fijo") and o["fijo"] not in activos:
                raise HTTPException(422, f"Origen de teléfono desconocido o inactivo: {o['fijo']}")
    defs = {a["clave"]: a for a in catalogos.atributos(conn)}
    for bloque, ambito in (("atributos", "empresa"), ("contacto_atributos", "contacto")):
        for clave in mapeo.get(bloque) or {}:
            if clave not in defs or defs[clave]["ambito"] != ambito:
                raise HTTPException(422, f"Atributo de {ambito} desconocido: {clave}")
            if not defs[clave]["activo"]:
                raise HTTPException(422, f"El atributo {defs[clave]['nombre']} está desactivado")
    tr = mapeo.get("traducciones") or {}
    for valor, cod in (tr.get("origen") or {}).items():
        if cod is not None and cod not in activos:
            raise HTTPException(422, f"La traducción de «{valor}» apunta a un origen desconocido o inactivo: {cod}")
    for clave, col in {**(mapeo.get("atributos") or {}), **(mapeo.get("contacto_atributos") or {})}.items():
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
        plantilla = conn.execute("SELECT mapeo, destino, reglas FROM carga_plantilla WHERE tipo_fuente = %s",
                                 (tipo_fuente,)).fetchone()
    avisos = []
    if plantilla:
        mapeo_p, avisos = limpiar_mapeo(plantilla["mapeo"])
    if plantilla:  # F4.2: un atributo fusionado se reemplaza por el que lo absorbió
        fusionados = {r["clave"]: r["destino"] for r in conn.execute(
            "SELECT a.clave, b.clave AS destino FROM atributo a JOIN atributo b ON b.id = a.fusionado_en")}
        for bloque in ("atributos", "contacto_atributos"):
            if mapeo_p.get(bloque):
                mapeo_p[bloque] = {fusionados.get(k, k): v for k, v in mapeo_p[bloque].items()}
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
        "sugerencias_atributos": sugerir_atributos(conn, columnas, mapeo),
        "destino": (plantilla or {}).get("destino") or "definitiva",
        "reglas": (plantilla or {}).get("reglas") or provisorias.REGLAS_DEFECTO,
        "criterios_fusion": list(provisorias.CRITERIOS),
        "umbral_fusion_flexible": float(config.vigente(conn)[1].get("umbral_fusion_flexible", 0.85)),
        "campos": {"empresa": CAMPOS_NUCLEO, "sucursal": CAMPOS_SUCURSAL, "contacto": CAMPOS_CONTACTO},
        "atributos": atributos, "origenes": catalogos.origenes(conn, activos=True),
        "plantillas": [r["tipo_fuente"] for r in conn.execute("SELECT tipo_fuente FROM carga_plantilla ORDER BY 1")],
    }


def sugerir_atributos(conn, columnas: list[str], mapeo: dict) -> list[dict]:
    """F4.1: cada columna sin mapear que se parece a un atributo existente (nombre o sinónimos, con pg_trgm).
    Al aceptar la sugerencia, el nombre de la columna queda como sinónimo del atributo."""
    usadas = columnas_de_mapeo(mapeo)
    libres = [c for c in columnas if c not in usadas and not _TEL.match(_norm_col(c)) and not _ORIGEN.match(_norm_col(c))]
    if not libres:
        return []
    ya = set(mapeo.get("atributos") or {}) | set(mapeo.get("contacto_atributos") or {})
    ambito = None if mapeo.get("contacto_nombre") else "empresa"
    out = []
    for col, lista in catalogos.parecidos(conn, libres, ambito, excluir=ya).items():
        mejor = lista[0]
        out.append({"columna": col, "atributo_id": mejor["id"], "clave": mejor["clave"], "nombre": mejor["nombre"],
                    "ambito": mejor["ambito"], "similitud": mejor["similitud"], "por": mejor["por"],
                    "otros": [{"clave": x["clave"], "nombre": x["nombre"], "similitud": x["similitud"]} for x in lista[1:3]]})
    return sorted(out, key=lambda x: -x["similitud"])


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
    for clave, col in {**(mapeo.get("atributos") or {}), **(mapeo.get("contacto_atributos") or {})}.items():
        a = t.defs.get(clave)
        if not a or a["tipo"] != "lista":
            continue
        cuenta = Counter(texto(f.get(col)) for f in filas)
        cuenta.pop(None, None)
        cuenta.pop("", None)
        ya = tr.get(catalogos.PREFIJO + clave) or {}
        # F4.1: «SI», «si» y «Sí » son la opción «Sí»: no piden traducción
        faltan = [(v, n) for v, n in cuenta.most_common() if not catalogos.opcion_equivalente(a["opciones"], v)]
        sim = catalogos.similitudes(conn, [catalogos.normalizar(v) for v, _ in faltan],
                                    [catalogos.normalizar(o) for o in a["opciones"]])
        umbral = float(config.vigente(conn)[1].get("umbral_similitud_atributos", 0.6))

        def parecida(v):
            nv = catalogos.normalizar(v)
            mejor = max(((sim.get((nv, catalogos.normalizar(o)), 0.0), o) for o in a["opciones"]), default=(0.0, None))
            return (mejor[1], round(mejor[0], 2)) if mejor[0] >= umbral else (None, None)
        pendientes = []
        for v, n in faltan:
            sug = _sugerencia(v, [(o, o) for o in a["opciones"]])
            pct = None
            if sug is None:  # «Exportadora» se parece a «Exportador»: se sugiere, nunca se aplica sola
                sug, pct = parecida(v)
            pendientes.append({"valor": v, "filas": n, "sugerido": sug, "similitud": pct,
                               "traduccion": ya.get(v), "traducido": v in ya})
        if pendientes:
            salida["atributos"].append({"clave": clave, "nombre": a["nombre"], "opciones": a["opciones"],
                                        "valores": pendientes})
    salida["pendientes"] = sum(1 for x in salida["origen"] if not x["traducido"]) + sum(
        1 for a in salida["atributos"] for x in a["valores"] if not x["traducido"])
    return salida


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
    por_atributo.update({k: Counter() for k in (mapeo.get("contacto_atributos") or {})})
    rechazos, conflictos_muestra, ruts_vistos = [], [], set()
    telefonos_tocados: set[int] = set()
    # F6.1 / F6.2: destino, opciones, reglas en cascada y decisiones tomadas en el preview
    destino = carga.get("destino") or "definitiva"
    opciones = carga.get("opciones") or {}
    sin_rut_a_provisoria = destino == "provisoria" or bool(opciones.get("sin_rut_a_provisoria"))
    con_rut_a_definitiva = destino == "definitiva" or opciones.get("con_rut_a_definitiva", True) is not False
    reglas = carga.get("reglas") or provisorias.REGLAS_DEFECTO
    decisiones = carga.get("decisiones") or {}
    coincidencias = []
    total = len(filas)
    for i, fila in enumerate(filas):
        nfila = i + 2
        if tarea_id and i % 200 == 0:
            tareas.progreso(tarea_id, i, total)
        crudo_rut = texto(fila.get(mapeo["rut"])) if mapeo.get("rut") else None
        r, motivo = rutmod.validar(crudo_rut) if crudo_rut else (None, "sin RUT")
        if r is None and not sin_rut_a_provisoria:
            rechazos.append((nfila, motivo, fila))
            c["rechazos"] += 1
            continue
        if r and r in ruts_vistos:
            c["conflictos"] += 1
            c["rut_repetido_en_archivo"] += 1
        if r:
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

        if r is None and crudo_rut:  # un identificador que no es RUT válido no se pierde (atributo de sistema)
            attrs["id_informado"] = {"valor": crudo_rut, "invalido": False}
        emp = conn.execute("SELECT * FROM empresa WHERE rut = %s", (r,)).fetchone() if r else None
        while emp and emp["baja"] == "fusionada" and emp["fusionada_en"]:
            emp = conn.execute("SELECT * FROM empresa WHERE id = %s", (emp["fusionada_en"],)).fetchone()
        es_alta = False
        if emp is None:
            email_c = _valor(fila, mapeo, "contacto_email") or datos.get("email")
            m = provisorias.cascada(conn, reglas, r, datos, [t.e164 for t, _ in tels if t.e164], email_c)
            if m and m["accion"] == "consultar":
                decision = decisiones.get(str(nfila))
                cand = m["candidata"]
                if len(coincidencias) < 500:
                    coincidencias.append({
                        "fila": nfila, "rut": r, "datos": {k: v for k, v in datos.items() if v},
                        "telefonos": [t.e164 or t.crudo for t, _ in tels], "candidata": provisorias._resumen(cand),
                        "candidatas": m["candidatas"], "criterio": m["regla"]["criterio"], "tipo": m["regla"]["tipo"],
                        "similitud": m["similitud"], "decision": decision})
                c["coincidencias"] += 1
                if decision == "fusionar":
                    emp = cand
                    c["fusiones_decididas"] += 1
                elif decision == "otra":
                    c["otra_empresa"] += 1
                else:  # «Decidir después» o sin decisión: a la bandeja de Revisión de fusiones
                    c["revision"] += 1
                    if real:
                        conn.execute(
                            "INSERT INTO revision_fusion (carga_id, fila, datos, criterio, candidata_id, similitud)"
                            " VALUES (%s,%s,%s,%s,%s,%s)",
                            (cid, nfila, Jsonb({"rut": r, "id_informado": None if r else crudo_rut,
                                                **{k: v for k, v in datos.items() if v},
                                                "telefonos": [{"crudo": t.crudo, "origen": o} for t, o in tels],
                                                "atributos": attrs}),
                             m["regla"]["criterio"] + ("" if m["regla"]["tipo"] == "exacta" else " (flexible)"),
                             cand["id"], m["similitud"]),
                        )
                    continue
            elif m and m["accion"] == "fusionar":
                emp = m["candidata"]
                c[f"fusion_por_{m['regla']['criterio']}"] += 1
        if emp is None:
            base = "definitiva" if r and con_rut_a_definitiva else "provisoria"
            emp = conn.execute("INSERT INTO empresa (rut, base, carga_alta_id) VALUES (%s, %s, %s) RETURNING *",
                               (r, base, cid)).fetchone()
            es_alta = True
            c[f"altas_{base}"] += 1
        elif emp["baja"] == "anulada":
            conn.execute("UPDATE empresa SET baja = NULL, carga_alta_id = %s WHERE id = %s", (cid, emp["id"]))
            es_alta = True
            c[f"altas_{emp['base']}"] += 1
        elif r and emp["base"] == "provisoria" and not emp["rut"] and con_rut_a_definitiva:
            # La fila trae el RUT de una provisoria que coincidió por otra regla: pasa a la definitiva
            emp = provisorias.promover(conn, emp, r, actor, "carga", cid, carga_id=cid if real else None)
            c["promovidas"] += 1
        hubo_cambio = aplicar_fila(conn, emp, datos, tels, cid, confianza, actor, c, conflictos_muestra,
                                   telefonos_tocados, attrs, por_origen)
        if mapeo.get("contacto_nombre"):
            hubo_cambio = aplicar_contacto(conn, emp, fila, mapeo, traductor, prefijos, cid, actor, c, por_atributo,
                                           telefonos_tocados) or hubo_cambio
        if es_alta:
            c["altas"] += 1
        elif hubo_cambio:
            c["actualizaciones"] += 1
            c[f"actualizaciones_{emp['base']}"] += 1
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
    conteos["coincidencias_a_decidir"] = coincidencias
    conteos["destino"] = destino
    return conteos, rechazos


def aplicar_contacto(conn, emp, fila, mapeo, traductor, prefijos, cid, actor, c, por_atributo, telefonos_tocados) -> bool:
    """Un contacto por fila (F3.2): se identifica por nombre normalizado o email dentro de la empresa;
    si ya existe se completan los campos vacíos. Su teléfono se vincula a la empresa con el origen de la
    fila y queda como «número del contacto»."""
    v = {k: _valor(fila, mapeo, k) for k in CAMPOS_CONTACTO}
    attrs = {}
    for clave, col in (mapeo.get("contacto_atributos") or {}).items():
        crudo = texto(fila.get(col))
        if crudo:
            attrs[clave] = crudo
    if not v["contacto_nombre"]:
        if any(v[k] for k in CAMPOS_CONTACTO[1:]) or attrs:
            c["contactos_sin_nombre"] += 1
        return False
    email = contactos.normalizar_email(v["contacto_email"])
    if email and not contactos.EMAIL.match(email):
        c["contactos_email_invalido"] += 1
        email = None
    contacto, nuevo = empresas.contacto(conn, emp["id"], v["contacto_nombre"], v["contacto_cargo"], v["contacto_area"],
                                        email, "carga", cid, actor=actor, solo_vacios=True)
    hubo = nuevo or bool(contacto.get("_cambios"))
    if v["contacto_telefono"]:
        origen, _ = traductor.origen(fila, mapeo["contacto_telefono"])
        for crudo in telmod.separar(v["contacto_telefono"]) or [v["contacto_telefono"]]:
            n = telmod.normalizar(crudo, prefijos)
            if n.tipo == "interno":
                c["telefonos_invalidos"] += 1
                continue
            fila_tel, n, creado = empresas.telefono(conn, crudo, prefijos)
            if fila_tel is None:
                continue
            if creado:
                c["telefonos_nuevos"] += 1
            _, vnuevo = empresas.vincular(conn, fila_tel["id"], emp["id"], "carga", cid, actor, origen=origen)
            if vnuevo and n.e164:
                telefonos_tocados.add(fila_tel["id"])
            if contactos.relacionar_telefono(conn, contacto["id"], fila_tel["id"], "del_contacto", "carga", cid):
                c["contactos_telefonos"] += 1
                contactos.historia(conn, contacto, "telefono", n.e164 or n.crudo, "carga", cid, actor)
                hubo = True
    for clave, crudo in attrs.items():
        a = traductor.atributo(clave, crudo)
        if a is None:
            por_atributo[clave]["sin_dato"] += 1
            continue
        por_atributo[clave]["invalidos" if a["invalido"] else "cargados"] += 1
        if catalogos.aplicar_atributo_contacto(conn, contacto, clave, a["valor"], "carga", cid, actor):
            hubo = True
    c["contactos_nuevos" if nuevo else "contactos_actualizados" if hubo else "contactos_sin_cambios"] += 1
    return hubo


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
            conflictos_muestra.append({"rut": emp["codigo"], "campos": conflictos})
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


DESTINOS = ("definitiva", "provisoria")


def crear(conn, archivo_id: int, fuente: str, tipo_fuente: str, licencia: str, regla_fusion: str | None,
          confianza: int | None, mapeo: dict, guardar_plantilla: bool, actor: str, destino: str = "definitiva",
          reglas: list | None = None, opciones: dict | None = None) -> dict:
    version, cfg = config.vigente(conn)
    if destino not in DESTINOS:
        raise HTTPException(422, "Destino de la carga: definitiva o provisoria")
    if reglas is None:  # API anterior: una sola regla (D43: pasa a ser una lista)
        regla_fusion = regla_fusion or "rut"
        if regla_fusion not in cfg["reglas_fusion"]:
            raise HTTPException(422, f"La regla de fusión '{regla_fusion}' no está habilitada en la configuración")
        reglas = [{"criterio": "rut", "tipo": "exacta"}] + (
            [{"criterio": provisorias.LEGADO[regla_fusion], "tipo": "exacta"}] if regla_fusion != "rut" else [])
    reglas = provisorias.normalizar_reglas(reglas, float(cfg.get("umbral_fusion_flexible", 0.85)))
    regla_fusion = next((r for r in ("telefono", "razon_social", "dominio")
                         if any(x["criterio"] == provisorias.LEGADO[r] for x in reglas)), "rut")
    opciones = {"con_rut_a_definitiva": (opciones or {}).get("con_rut_a_definitiva", True) is not False,
                "sin_rut_a_provisoria": bool((opciones or {}).get("sin_rut_a_provisoria"))}
    if not licencia or not licencia.strip():
        raise HTTPException(422, "Indicá la licencia de uso de la fuente")
    archivo, columnas, filas = _leer(conn, archivo_id)
    mapeo, _ = limpiar_mapeo(mapeo)
    _validar_mapeo(conn, mapeo, columnas, destino)
    pend = valores(conn, archivo_id, mapeo)
    if pend["pendientes"]:
        ejemplos = [x["valor"] for x in pend["origen"] if not x["traducido"]] + [
            x["valor"] for a in pend["atributos"] for x in a["valores"] if not x["traducido"]]
        raise HTTPException(422, f"Hay {pend['pendientes']} valores sin traducir al catálogo (por ejemplo: "
                                 f"{', '.join(ejemplos[:5])}). Elegí para cada uno un valor del catálogo o «sin dato».")
    if confianza is None:
        confianza = cfg["confianza_fuentes"].get("carga", 50)
    carga = conn.execute(
        "INSERT INTO carga (archivo_id, fuente, tipo_fuente, licencia, responsable, regla_fusion, confianza, mapeo, config_version,"
        " destino, reglas, opciones) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (archivo_id, fuente, tipo_fuente, licencia, actor, regla_fusion, confianza, Jsonb(mapeo), version,
         destino, Jsonb(reglas), Jsonb(opciones)),
    ).fetchone()
    if guardar_plantilla:  # el destino y las reglas quedan en la plantilla (F6.1, F6.2)
        conn.execute(
            "INSERT INTO carga_plantilla (tipo_fuente, mapeo, autor, destino, reglas) VALUES (%s,%s,%s,%s,%s)"
            " ON CONFLICT (tipo_fuente) DO UPDATE SET mapeo = EXCLUDED.mapeo, autor = EXCLUDED.autor, destino = EXCLUDED.destino,"
            " reglas = EXCLUDED.reglas, actualizado = now()",
            (tipo_fuente, Jsonb(mapeo), actor, destino, Jsonb(reglas)),
        )
    auditoria.registrar(conn, actor, "carga.crear", "carga", carga["id"],
                        {"archivo": archivo["nombre"], "fuente": fuente, "destino": destino, "reglas": reglas,
                         "opciones": opciones})
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


DECISIONES = ("fusionar", "otra", "despues")


def guardar_decisiones(conn, carga_id: int, decisiones: dict, actor: str) -> dict:
    """«Coincidencias a decidir» (F6.2): por fila, fusionar, es otra empresa o decidir después.
    La confirmación las usa y quedan en el linaje de la carga."""
    carga = conn.execute("SELECT * FROM carga WHERE id = %s FOR UPDATE", (carga_id,)).fetchone()
    if carga is None:
        raise HTTPException(404, "Carga inexistente")
    if carga["estado"] != "preview":
        raise HTTPException(409, "Las coincidencias se deciden en el preview")
    filas = {str(x["fila"]) for x in (carga["conteos"] or {}).get("coincidencias_a_decidir") or []}
    malas = [k for k, v in decisiones.items() if v not in DECISIONES or str(k) not in filas]
    if malas:
        raise HTTPException(422, f"Decisiones inválidas para las filas {', '.join(map(str, malas[:10]))}")
    nuevas = {**(carga["decisiones"] or {}), **{str(k): v for k, v in decisiones.items()}}
    conn.execute("UPDATE carga SET decisiones = %s WHERE id = %s", (Jsonb(nuevas), carga_id))
    auditoria.registrar(conn, actor, "carga.decidir", "carga", carga_id,
                        {"decisiones": {d: sum(1 for v in nuevas.values() if v == d) for d in DECISIONES}})
    return {"decisiones": nuevas}


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
        raise HTTPException(409, f"No se puede deshacer: {en_muestra} empresas de esta carga ya entraron a una muestra."
                                 " Un administrador puede usar «Borrar carga», que la elimina junto con su paso por las muestras.")
    conn.execute("UPDATE carga SET estado = 'deshecha', deshecha = now() WHERE id = %s", (carga_id,))
    # Las provisorias que esta carga pasó a la definitiva (agregó el RUT) vuelven a la provisoria
    for p in conn.execute("SELECT * FROM carga_promocion WHERE carga_id = %s ORDER BY id DESC", (carga_id,)).fetchall():
        conn.execute("UPDATE empresa SET rut = %s, base = %s WHERE id = %s", (p["rut_anterior"], p["base_anterior"], p["empresa_id"]))
    # El origen que esta carga sumó a vínculos que ya existían
    conn.execute("DELETE FROM telefono_vinculo_origen WHERE fuente_tipo = 'carga' AND fuente_id = %s", (carga_id,))
    vincs = conn.execute("DELETE FROM telefono_vinculo WHERE fuente_tipo = 'carga' AND fuente_id = %s"
                         " RETURNING id, telefono_id", (carga_id,)).fetchall()
    # Los contactos que trajo la carga se borran (con su historia); los que solo completó vuelven a recalcularse
    contactos.borrar(conn, [r["id"] for r in conn.execute(
        "SELECT id FROM contacto WHERE fuente_tipo = 'carga' AND fuente_id = %s", (carga_id,))])
    conn.execute("DELETE FROM contacto_telefono WHERE fuente_tipo = 'carga' AND fuente_id = %s", (carga_id,))
    conn.execute("DELETE FROM contacto_atributo WHERE fuente_tipo = 'carga' AND fuente_id = %s", (carga_id,))
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
    intermediarios.reevaluar(conn, [v["telefono_id"] for v in vincs]
                             + [r["telefono_id"] for r in conn.execute(
                                 "SELECT DISTINCT telefono_id FROM telefono_vinculo WHERE empresa_id = ANY(%s)", (ids,))],
                             actor)
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
    # La última tarea de la carga (preview o confirmación). «trabada»: figura corriendo hace más de
    # 30 minutos (más que el plazo de Cloud Tasks): la instancia que la corría probablemente murió.
    carga["tarea"] = conn.execute(
        "SELECT id, tipo, estado, progreso, total, error, creado,"
        " (estado = 'corriendo' AND creado < now() - make_interval(mins => %s)) AS trabada"
        " FROM tarea WHERE tipo IN ('carga.preview', 'carga.confirmar')"
        " AND (payload->>'carga_id')::int = %s ORDER BY id DESC LIMIT 1", (tareas.TRABADA_MINUTOS, carga_id)).fetchone()
    return carga


def listar(conn) -> list[dict]:
    return conn.execute(
        "SELECT c.id, c.fuente, c.tipo_fuente, c.licencia, c.responsable, c.regla_fusion, c.destino, c.reglas, c.estado, c.conteos, c.fecha,"
        " c.confirmada, c.deshecha, c.descartada, a.nombre AS archivo_nombre FROM carga c JOIN archivo a ON a.id = c.archivo_id"
        " ORDER BY c.id DESC LIMIT 200").fetchall()


# ─────────────────────────────────────────────────────────────
# Bandeja de revisión (coincidencias que no son por RUT)
# ─────────────────────────────────────────────────────────────

def revision_pendiente(conn) -> list[dict]:
    return conn.execute(
        "SELECT r.*, e.codigo AS candidata_rut, e.base AS candidata_base, e.razon_social AS candidata_razon, e.web AS candidata_web,"
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
    id_informado = datos.pop("id_informado", None)
    if id_informado:
        atributos = {**atributos, "id_informado": {"valor": id_informado, "invalido": False}}
    if accion == "alta":
        if datos.get("rut"):
            emp = conn.execute("INSERT INTO empresa (rut, carga_alta_id) VALUES (%s, %s) ON CONFLICT (rut) DO NOTHING"
                               " RETURNING *", (datos["rut"], carga["id"])).fetchone()
            emp = emp or conn.execute("SELECT * FROM empresa WHERE rut = %s", (datos["rut"],)).fetchone()
        else:  # fila sin RUT: alta en la base provisoria
            emp = conn.execute("INSERT INTO empresa (rut, base, carga_alta_id) VALUES (NULL, 'provisoria', %s) RETURNING *",
                               (carga["id"],)).fetchone()
    elif accion == "actualizar_candidata":
        emp = conn.execute("SELECT * FROM empresa WHERE id = %s", (r["candidata_id"],)).fetchone()
        if datos.get("rut") and emp["base"] == "provisoria" and not emp["rut"]:
            emp = provisorias.promover(conn, emp, datos["rut"], actor, "carga", carga["id"], carga_id=carga["id"])
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
