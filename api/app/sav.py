"""Ingesta del .sav de Alchemer con mapeo (R1.9).

Mismo patrón que la ingesta de panelistas del sistema de paneles: el backend lee el
archivo con pyreadstat y devuelve una propuesta editable; la propuesta no aplica nada; el
mapeo declarado gana sobre las etiquetas del archivo; el valor crudo se guarda aunque quede
sin mapear; se avisa con conteos ("el 99 quedó sin mapear: 412 filas"); la ingesta corre en
diferido. El mapeo confirmado queda como plantilla de la parte.
"""
import datetime as dt
import re
from collections import Counter, defaultdict

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, config, lectores, resultados, rut as rutmod, storage, tareas
from . import telefonos as telmod
from .util import TZ, sin_tildes, texto

# Destinos del sistema y nombres con los que se reconocen en el .sav (bloque estándar EC_*)
DESTINOS = {
    "tel_usado": ["EC_TEL_USADO", "tel_usado", "telefono_usado"],
    "calidad_tel": ["EC_CALIDAD_TEL", "calidad_tel"],
    "tel_alt": ["EC_TEL_ALT", "tel_alt", "telefono_alternativo"],
    "resp_nombre": ["EC_RESP_NOMBRE", "resp_nombre"],
    "resp_cargo": ["EC_RESP_CARGO", "resp_cargo"],
    "resp_area": ["EC_RESP_AREA", "resp_area"],
    "resultado": ["EC_RESULTADO", "resultado"],
    "rut": ["EC_RUT", "rut"],
    "encuestador": ["EC_ENCUESTADOR", "encuestador", "agente", "interviewer"],
    "fecha": ["datesubmitted", "date_submitted", "EC_FECHA", "fecha", "datestarted"],
    "estado_alchemer": ["status", "estado", "responsestatus"],
}
RESPONSE_ID = ["responseid", "response_id", "respondentid", "id", "EC_RESPONSE_ID"]
ID_ITEM = ["EC_ID_ITEM", "id_item", "iditem"]
CODIFICADOS = {
    "calidad_tel": ("corresponde", "no_corresponde", "intermediario", "cerro", "inexistente", "ignorar"),
    "resultado": ("completa", "parcial", "rechazo", "no_corresponde", "agendada", "descalificada", "ignorar"),
    "estado_alchemer": ("completa", "parcial", "rechazo", "no_corresponde", "agendada", "descalificada", "ignorar"),
}
# Códigos del bloque estándar acordado en la fase 0
ESTANDAR_CALIDAD = {"1": "corresponde", "2": "no_corresponde", "3": "intermediario", "4": "cerro", "5": "inexistente"}
PALABRAS = {
    "calidad_tel": [("contable", "intermediario"), ("juridic", "intermediario"), ("estudio", "intermediario"),
                    ("no es de", "no_corresponde"), ("no corresponde", "no_corresponde"), ("cerr", "cerro"),
                    ("inexist", "inexistente"), ("no existe", "inexistente"), ("corresponde", "corresponde")],
    "resultado": [("complet", "completa"), ("parcial", "parcial"), ("rechaz", "rechazo"),
                  ("no corresponde", "no_corresponde"), ("agend", "agendada"), ("descalif", "descalificada"),
                  ("disqualif", "descalificada"), ("partial", "parcial"), ("complete", "completa")],
}
PALABRAS["estado_alchemer"] = PALABRAS["resultado"]


def _buscar(columnas: list[str], nombres: list[str]) -> str | None:
    idx = {c.lower(): c for c in columnas}
    for n in nombres:
        if n.lower() in idx:
            return idx[n.lower()]
    return None


def _sugerir_valor(destino: str, codigo: str, etiqueta: str | None) -> str | None:
    if destino == "calidad_tel" and etiqueta is None and codigo in ESTANDAR_CALIDAD:
        return ESTANDAR_CALIDAD[codigo]
    texto_ = sin_tildes(str(etiqueta if etiqueta is not None else codigo).lower())
    for palabra, valor in PALABRAS[destino]:
        if palabra in texto_:
            return valor
    if destino == "calidad_tel" and codigo in ESTANDAR_CALIDAD:
        return ESTANDAR_CALIDAD[codigo]
    return None


def describir(columnas, filas, meta) -> list[dict]:
    salida = []
    for c in columnas:
        vals = [f.get(c) for f in filas if f.get(c) is not None]
        distintos = Counter(lectores.clave_valor(v) for v in vals)
        salida.append({
            "nombre": c, "etiqueta": (meta.get("etiquetas") or {}).get(c),
            "valores": (meta.get("valores") or {}).get(c) or {},
            "n_distintos": len(distintos), "n_no_vacios": len(vals),
            "frecuentes": distintos.most_common(12),
        })
    return salida


def proponer(columnas, filas, meta, plantilla: dict | None) -> dict:
    """Propuesta editable. Si hay plantilla de la parte, se precarga y solo se completan huecos."""
    base = plantilla or {}
    variables = dict(base.get("variables") or {})
    for destino, nombres in DESTINOS.items():
        if not variables.get(destino) or variables[destino] not in columnas:
            col = _buscar(columnas, nombres)
            if col:
                variables[destino] = col
            else:
                variables.pop(destino, None)
    ident = base.get("identificador") or {}
    if not ident.get("variable") or ident["variable"] not in columnas:
        col = _buscar(columnas, ID_ITEM)
        if col:
            ident = {"variable": col, "tipo": "id_item"}
        elif variables.get("rut"):
            ident = {"variable": variables["rut"], "tipo": "rut"}
        else:
            ident = {}
    resp = base.get("response_id") if base.get("response_id") in columnas else _buscar(columnas, RESPONSE_ID)
    valores = {k: dict(v) for k, v in (base.get("valores") or {}).items()}
    etiquetas = meta.get("valores") or {}
    for destino in CODIFICADOS:
        var = variables.get(destino)
        if not var:
            continue
        mapa = valores.setdefault(destino, {})
        codigos = set(etiquetas.get(var, {}).keys())
        codigos |= {lectores.clave_valor(f.get(var)) for f in filas if f.get(var) is not None}
        for cod in sorted(codigos, key=str):
            if cod not in mapa:
                sug = _sugerir_valor(destino, cod, etiquetas.get(var, {}).get(cod))
                if sug:
                    mapa[cod] = sug
    return {"response_id": resp, "identificador": ident, "variables": variables, "valores": valores}


def validar_mapeo(mapeo: dict, columnas: list[str]):
    if not mapeo.get("response_id") or mapeo["response_id"] not in columnas:
        raise HTTPException(422, "Indicá la variable de response_id (identificador de la respuesta en Alchemer)")
    ident = mapeo.get("identificador") or {}
    if ident.get("tipo") not in ("id_item", "rut") or ident.get("variable") not in columnas:
        raise HTTPException(422, "Indicá la variable identificador (id_item o RUT)")
    for destino, var in (mapeo.get("variables") or {}).items():
        if destino not in DESTINOS:
            raise HTTPException(422, f"Destino desconocido: {destino}")
        if var and var not in columnas:
            raise HTTPException(422, f"La variable {var} no está en el archivo")
    for destino, mapa in (mapeo.get("valores") or {}).items():
        if destino not in CODIFICADOS:
            raise HTTPException(422, f"{destino} no es una variable codificada")
        malos = {v for v in mapa.values() if v not in CODIFICADOS[destino]}
        if malos:
            raise HTTPException(422, f"Valores no válidos para {destino}: {', '.join(sorted(malos))}")


# ─────────────────────────────────────────────────────────────
# Asociación de filas a ítems de muestra
# ─────────────────────────────────────────────────────────────

class Contexto:
    """Ítems de las muestras del estudio, precargados para asociar sin una consulta por fila."""

    def __init__(self, conn, parte: dict):
        self.parte = parte
        self.items = {}
        self.por_rut = defaultdict(list)
        self.tels = defaultdict(set)
        for r in conn.execute(
                "SELECT i.*, e.rut FROM muestra_item i JOIN muestra m ON m.id = i.muestra_id JOIN empresa e ON e.id = i.empresa_id"
                " WHERE m.estudio_id = %s", (parte["estudio_id"],)):
            self.items[r["id"]] = r
            self.por_rut[r["rut"]].append(r["id"])
        if self.items:
            for r in conn.execute(
                    "SELECT v.empresa_id, t.e164 FROM telefono_vinculo v JOIN telefono t ON t.id = v.telefono_id"
                    " WHERE v.empresa_id = ANY(%s) AND t.e164 IS NOT NULL",
                    (list({i["empresa_id"] for i in self.items.values()}),)):
                self.tels[r["empresa_id"]].add(r["e164"])

    def asociar(self, fila: dict, mapeo: dict) -> tuple[dict | None, str | None, list[int]]:
        """Devuelve (item, motivo_si_no, candidatos)."""
        ident = mapeo["identificador"]
        valor = texto(fila.get(ident["variable"]))
        var_rut = mapeo.get("variables", {}).get("rut")
        if ident["tipo"] == "id_item" and valor:
            try:
                item_id = int(float(valor))
            except ValueError:
                return None, f"id_item no numérico: {valor}", []
            item = self.items.get(item_id)
            if item is not None:
                return item, None, []
            if not var_rut:
                return None, f"id_item {item_id} no pertenece a una muestra del estudio", []
            valor_rut = texto(fila.get(var_rut))
        elif ident["tipo"] == "rut":
            valor_rut = valor
        else:
            # Sin id_item: respaldo por RUT + teléfono (riesgo previsto en el spec)
            valor_rut = texto(fila.get(var_rut)) if var_rut else None
        if not valor_rut:
            return None, "sin identificador", []
        r, motivo = rutmod.validar(valor_rut)
        if r is None:
            return None, f"RUT inválido: {motivo}", []
        cands = self.por_rut.get(r, [])
        if len(cands) == 1:
            return self.items[cands[0]], None, []
        if not cands:
            return None, f"el RUT {r} no está en las muestras del estudio", []
        tel_var = mapeo.get("variables", {}).get("tel_usado")
        if tel_var:
            n = telmod.normalizar(fila.get(tel_var))
            por_tel = [c for c in cands if n.e164 and n.e164 in self.tels[self.items[c]["empresa_id"]]]
            if len(por_tel) == 1:
                return self.items[por_tel[0]], None, []
        return None, "el RUT aparece en más de un ítem del estudio", cands


def valores_mapeados(fila: dict, mapeo: dict) -> tuple[dict, dict]:
    """Traduce la fila cruda a valores del sistema. Devuelve (valores, sin_mapear {destino: código})."""
    v, sin_mapear = {}, {}
    for destino, var in (mapeo.get("variables") or {}).items():
        if not var:
            continue
        crudo = fila.get(var)
        if crudo is None or (isinstance(crudo, str) and not crudo.strip()):
            continue
        if destino in CODIFICADOS:
            cod = lectores.clave_valor(crudo)
            valor = (mapeo.get("valores") or {}).get(destino, {}).get(cod)
            if valor is None:
                sin_mapear[destino] = cod
            else:
                v[destino] = valor
        else:
            v[destino] = texto(crudo)
    # EC_RESULTADO gana sobre el estado de Alchemer
    if "resultado" not in v and v.get("estado_alchemer") and v["estado_alchemer"] != "ignorar":
        v["resultado"] = v["estado_alchemer"]
    if v.get("resultado") == "ignorar":
        v.pop("resultado")
    return v, sin_mapear


def _fecha(valor, defecto: dt.datetime) -> dt.datetime:
    if not valor:
        return defecto
    s = str(valor).strip()
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = dt.datetime.fromisoformat(s) if fmt is None else dt.datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=TZ)
        except ValueError:
            continue
    m = re.match(r"^\d+(\.\d+)?$", s)
    if m:  # fecha SPSS: segundos desde 1582-10-14
        return (dt.datetime(1582, 10, 14) + dt.timedelta(seconds=float(s))).replace(tzinfo=TZ)
    return defecto


def contar(conn, parte: dict, filas: list[dict], mapeo: dict) -> dict:
    ctx = Contexto(conn, parte)
    c = Counter()
    motivos = Counter()
    sin_mapear = defaultdict(Counter)
    ids = [texto(f.get(mapeo["response_id"])) for f in filas]
    existentes = {r["response_id"] for r in conn.execute(
        "SELECT response_id FROM sav_fila WHERE parte_id = %s AND response_id = ANY(%s)",
        (parte["id"], [i for i in ids if i]))}
    for f, rid in zip(filas, ids):
        c["filas"] += 1
        if not rid:
            c["sin_response_id"] += 1
            continue
        if rid in existentes:
            c["ya_ingeridas"] += 1
        item, motivo, _ = ctx.asociar(f, mapeo)
        if item is None:
            c["sin_asociar"] += 1
            motivos[motivo.split(":")[0]] += 1
        else:
            c["asociadas"] += 1
        _, sm = valores_mapeados(f, mapeo)
        for destino, cod in sm.items():
            sin_mapear[destino][cod] += 1
    avisos = [f"{destino}: el {cod} quedó sin mapear: {n} filas"
              for destino, cs in sin_mapear.items() for cod, n in cs.most_common()]
    total = c["filas"] - c["sin_response_id"]
    return {**c, "porcentaje_asociadas": round(100 * c["asociadas"] / total, 1) if total else 0.0,
            "motivos_sin_asociar": dict(motivos), "sin_mapear": {k: dict(v) for k, v in sin_mapear.items()},
            "avisos": avisos}


# ─────────────────────────────────────────────────────────────
# Flujo: analizar → contar (con mapeo editado) → confirmar → remapear
# ─────────────────────────────────────────────────────────────

def _parte(conn, parte_id: int) -> dict:
    p = conn.execute("SELECT * FROM parte WHERE id = %s", (parte_id,)).fetchone()
    if p is None:
        raise HTTPException(404, "Parte inexistente")
    return p


def _leer(conn, ingesta: dict):
    archivo = conn.execute("SELECT * FROM archivo WHERE id = %s", (ingesta["archivo_id"],)).fetchone()
    if archivo["tipo"] != "sav":
        raise HTTPException(415, "La ingesta de resultados acepta solo .sav")
    return lectores.leer_sav(storage.leer(archivo))


def analizar(conn, parte_id: int, archivo: dict, actor: str, plantilla_de_parte: int | None = None) -> dict:
    parte = _parte(conn, parte_id)
    if archivo["tipo"] != "sav":
        raise HTTPException(415, "La ingesta de resultados acepta solo .sav")
    columnas, filas, meta = lectores.leer_sav(storage.leer(archivo))
    plantilla = parte["plantilla_mapeo"]
    origen = "plantilla de la parte" if plantilla else None
    if plantilla_de_parte:
        otra = _parte(conn, plantilla_de_parte)
        plantilla, origen = otra["plantilla_mapeo"], f"plantilla de la parte {otra['nombre']}"
    mapeo = proponer(columnas, filas, meta, plantilla)
    ingesta = conn.execute(
        "INSERT INTO sav_ingesta (parte_id, archivo_id, mapeo, actor) VALUES (%s,%s,%s,%s) RETURNING *",
        (parte_id, archivo["id"], Jsonb(mapeo), actor)).fetchone()
    conteos = contar(conn, parte, filas, mapeo) if mapeo.get("response_id") and mapeo.get("identificador") else {}
    conn.execute("UPDATE sav_ingesta SET conteos = %s WHERE id = %s", (Jsonb(conteos), ingesta["id"]))
    auditoria.registrar(conn, actor, "sav.analizar", "sav_ingesta", ingesta["id"],
                        {"parte_id": parte_id, "archivo": archivo["nombre"], "filas": len(filas)})
    return {"ingesta_id": ingesta["id"], "archivo": archivo["nombre"], "n_filas": len(filas),
            "variables": describir(columnas, filas, meta), "mapeo": mapeo, "origen_mapeo": origen or "sugerido",
            "conteos": conteos, "destinos": list(DESTINOS), "codificados": {k: list(v) for k, v in CODIFICADOS.items()}}


def recontar(conn, ingesta_id: int, mapeo: dict) -> dict:
    ing = obtener(conn, ingesta_id)
    columnas, filas, _ = _leer(conn, ing)
    validar_mapeo(mapeo, columnas)
    return contar(conn, _parte(conn, ing["parte_id"]), filas, mapeo)


def confirmar(conn, parte_id: int, ingesta_id: int, mapeo: dict, actor: str) -> int:
    ing = conn.execute("SELECT * FROM sav_ingesta WHERE id = %s FOR UPDATE", (ingesta_id,)).fetchone()
    if ing is None or ing["parte_id"] != parte_id:
        raise HTTPException(404, "Ingesta inexistente para esta parte")
    if ing["estado"] not in ("analizada", "error"):
        raise HTTPException(409, f"La ingesta está {ing['estado']}")
    columnas, _, _ = _leer(conn, ing)
    validar_mapeo(mapeo, columnas)
    conn.execute("UPDATE sav_ingesta SET estado = 'en_proceso', mapeo = %s WHERE id = %s", (Jsonb(mapeo), ingesta_id))
    return tareas.crear(conn, "sav.confirmar", {"ingesta_id": ingesta_id}, actor)


def aplicar_filas(conn, ingesta: dict, parte: dict, filas: list[dict], mapeo: dict, actor: str,
                  tarea_id: int | None, forzar: bool) -> dict:
    """Guarda cada fila cruda y aplica sus resultados. forzar=True reaplica aunque no haya cambiado."""
    _, cfg = config.vigente(conn)
    ctx = Contexto(conn, parte)
    estudio_id = parte["estudio_id"]
    c = Counter()
    sin_mapear = defaultdict(Counter)
    total = len(filas)
    for i, fila in enumerate(filas):
        if tarea_id and i % 100 == 0:
            tareas.progreso(tarea_id, i, total)
        rid = texto(fila.get(mapeo["response_id"]))
        if not rid:
            c["sin_response_id"] += 1
            continue
        previa = conn.execute("SELECT * FROM sav_fila WHERE parte_id = %s AND response_id = %s",
                              (parte["id"], rid)).fetchone()
        if previa and previa["valores"] == fila and previa["aplicado"] is not None and not forzar:
            c["ya_ingeridas"] += 1
            if previa["item_id"]:
                c["asociadas"] += 1
            else:
                c["sin_asociar"] += 1
            continue
        item, motivo, cands = ctx.asociar(fila, mapeo)
        v, sm = valores_mapeados(fila, mapeo)
        for destino, cod in sm.items():
            sin_mapear[destino][cod] += 1
        fecha = _fecha(v.get("fecha"), ingesta["fecha"])
        linaje = {"estudio_id": estudio_id, "parte_id": parte["id"], "ingesta_id": ingesta["id"], "response_id": rid,
                  "encuestador": v.get("encuestador"), "fecha": fecha}
        aplicado = resultados.aplicar(conn, item, parte, v, linaje, cfg, actor, forzar) if item else {}
        sf = conn.execute(
            "INSERT INTO sav_fila (ingesta_id, parte_id, response_id, item_id, valores, aplicado, motivo)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (parte_id, response_id) DO UPDATE SET ingesta_id = EXCLUDED.ingesta_id,"
            " item_id = EXCLUDED.item_id, valores = EXCLUDED.valores, aplicado = EXCLUDED.aplicado, motivo = EXCLUDED.motivo,"
            " actualizado = now() RETURNING id",
            (ingesta["id"], parte["id"], rid, item["id"] if item else None, Jsonb(fila), Jsonb(aplicado),
             motivo)).fetchone()
        if item:
            c["asociadas"] += 1
            conn.execute("UPDATE conciliacion SET estado = 'resuelta', resuelto = now(), resuelto_por = %s,"
                         " resolucion = %s WHERE tipo = 'sav_fila' AND objeto_id = %s AND estado = 'pendiente'",
                         (actor, Jsonb({"item_id": item["id"], "automatica": True}), sf["id"]))
            for k in aplicado:
                c[f"aplicado_{k}"] += 1
        else:
            c["sin_asociar"] += 1
            conn.execute(
                "INSERT INTO conciliacion (tipo, objeto_id, motivo, candidatos) VALUES ('sav_fila', %s, %s, %s)"
                " ON CONFLICT (tipo, objeto_id) DO UPDATE SET motivo = EXCLUDED.motivo, candidatos = EXCLUDED.candidatos,"
                " estado = 'pendiente'",
                (sf["id"], motivo, Jsonb({"items": cands})))
        c["procesadas"] += 1
    tareas.progreso(tarea_id, total, total)
    conteos = dict(c)
    conteos["filas"] = total
    conteos["sin_mapear"] = {k: dict(v) for k, v in sin_mapear.items()}
    conteos["avisos"] = [f"{d}: el {cod} quedó sin mapear: {n} filas" for d, cs in sin_mapear.items()
                         for cod, n in cs.most_common()]
    base = total - c["sin_response_id"]
    conteos["porcentaje_asociadas"] = round(100 * c["asociadas"] / base, 1) if base else 0.0
    return conteos


@tareas.handler("sav.confirmar")
def _tarea_confirmar(conn, payload, tarea_id):
    ing = conn.execute("SELECT * FROM sav_ingesta WHERE id = %s", (payload["ingesta_id"],)).fetchone()
    parte = _parte(conn, ing["parte_id"])
    _, filas, _ = _leer(conn, ing)
    conteos = aplicar_filas(conn, ing, parte, filas, ing["mapeo"], ing["actor"], tarea_id, forzar=False)
    conn.execute("UPDATE sav_ingesta SET estado = 'confirmada', conteos = %s, confirmada = now() WHERE id = %s",
                 (Jsonb(conteos), ing["id"]))
    conn.execute("UPDATE parte SET plantilla_mapeo = %s WHERE id = %s", (Jsonb(ing["mapeo"]), parte["id"]))
    auditoria.registrar(conn, ing["actor"], "sav.confirmar", "sav_ingesta", ing["id"], conteos)
    return {"ingesta_id": ing["id"], "conteos": conteos}


def remapear(conn, ingesta_id: int, mapeo: dict, actor: str) -> int:
    ing = obtener(conn, ingesta_id)
    if ing["estado"] != "confirmada":
        raise HTTPException(409, "Solo se remapea una ingesta confirmada")
    columnas = list((conn.execute("SELECT valores FROM sav_fila WHERE ingesta_id = %s LIMIT 1",
                                  (ingesta_id,)).fetchone() or {"valores": {}})["valores"].keys())
    validar_mapeo(mapeo, columnas)
    conn.execute("UPDATE sav_ingesta SET mapeo = %s, estado = 'en_proceso' WHERE id = %s", (Jsonb(mapeo), ingesta_id))
    return tareas.crear(conn, "sav.remapear", {"ingesta_id": ingesta_id}, actor)


@tareas.handler("sav.remapear")
def _tarea_remapear(conn, payload, tarea_id):
    """Reaplica el mapeo corregido sobre los valores crudos guardados, sin volver a subir el archivo."""
    ing = conn.execute("SELECT * FROM sav_ingesta WHERE id = %s", (payload["ingesta_id"],)).fetchone()
    parte = _parte(conn, ing["parte_id"])
    filas = [r["valores"] for r in conn.execute("SELECT valores FROM sav_fila WHERE ingesta_id = %s ORDER BY id",
                                                (ing["id"],))]
    conteos = aplicar_filas(conn, ing, parte, filas, ing["mapeo"], ing["actor"], tarea_id, forzar=True)
    conn.execute("UPDATE sav_ingesta SET estado = 'confirmada', conteos = %s WHERE id = %s", (Jsonb(conteos), ing["id"]))
    conn.execute("UPDATE parte SET plantilla_mapeo = %s WHERE id = %s", (Jsonb(ing["mapeo"]), parte["id"]))
    auditoria.registrar(conn, ing["actor"], "sav.remapear", "sav_ingesta", ing["id"], conteos)
    return {"ingesta_id": ing["id"], "conteos": conteos}


def obtener(conn, ingesta_id: int) -> dict:
    ing = conn.execute(
        "SELECT s.*, a.nombre AS archivo_nombre, p.nombre AS parte_nombre, p.estudio_id FROM sav_ingesta s"
        " JOIN archivo a ON a.id = s.archivo_id JOIN parte p ON p.id = s.parte_id WHERE s.id = %s",
        (ingesta_id,)).fetchone()
    if ing is None:
        raise HTTPException(404, "Ingesta inexistente")
    # Variables y códigos presentes en el crudo guardado, para corregir el mapeo sin el archivo
    primera = conn.execute("SELECT valores FROM sav_fila WHERE ingesta_id = %s LIMIT 1", (ingesta_id,)).fetchone()
    ing["columnas"] = list(primera["valores"].keys()) if primera else []
    ing["frecuencias"] = {}
    for destino in CODIFICADOS:
        var = ((ing["mapeo"] or {}).get("variables") or {}).get(destino)
        if var:
            ing["frecuencias"][var] = [[r["v"], r["n"]] for r in conn.execute(
                "SELECT valores->>%s AS v, count(*) AS n FROM sav_fila WHERE ingesta_id = %s AND valores->>%s IS NOT NULL"
                " GROUP BY 1 ORDER BY 2 DESC", (var, ingesta_id, var))]
    ing["tarea"] = conn.execute(
        "SELECT id, estado, progreso, total, error FROM tarea WHERE tipo LIKE 'sav.%%'"
        " AND (payload->>'ingesta_id')::int = %s ORDER BY id DESC LIMIT 1", (ingesta_id,)).fetchone()
    return ing


def listar(conn, parte_id: int | None = None) -> list[dict]:
    return conn.execute(
        "SELECT s.id, s.parte_id, p.nombre AS parte_nombre, e.nombre AS estudio_nombre, a.nombre AS archivo_nombre,"
        " s.estado, s.conteos, s.actor, s.fecha, s.confirmada FROM sav_ingesta s JOIN parte p ON p.id = s.parte_id"
        " JOIN estudio e ON e.id = p.estudio_id JOIN archivo a ON a.id = s.archivo_id"
        " WHERE (%s::int IS NULL OR s.parte_id = %s) ORDER BY s.id DESC LIMIT 200", (parte_id, parte_id)).fetchall()
