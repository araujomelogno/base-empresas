"""Descubrimiento de empresas nuevas por rubro y zona en Google Places (SPEC_fase2_enriquecimiento, B5 / etapa C).

Una búsqueda («imprentas en Salto») es un lote «Descubrimiento #N»: se estima el costo (una llamada Text Search por
página, con los mismos topes que el enriquecimiento), se aprueba, se busca y cada resultado se compara con la base:
  - mismo place_id ya guardado → se informa, no se hace nada;
  - coincide con una empresa (teléfono, sitio o nombre y dirección, con las reglas de fusión) → se ofrece completarla
    (con decisión humana si la regla es flexible);
  - no coincide con nada → alta en la base provisoria con origen Google Places.
Nada se guarda hasta confirmar. El lote tiene linaje (fuente «descubrimiento»), se puede deshacer y queda en Auditoría.

Qué aporta (D58): para cada coincidencia, el preview dice dato por dato (teléfono, sitio, dirección, place ID) si es
nuevo, igual o distinto y, si es distinto, si reemplazaría al vigente o quedaría solo en la historia (simulando la
regla de supervivencia). Las que no aportan nada quedan en «No guardar». Al confirmar se guarda lo que pasó de verdad.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, empresas, enriquecimiento as enr, intermediarios, config, mantenimiento, proveedores, provisorias
from . import telefonos as telmod

REGLAS = [{"criterio": "telefono", "tipo": "exacta"}, {"criterio": "dominio_web", "tipo": "exacta"},
          {"criterio": "razon_social", "tipo": "flexible", "umbral": 0.85},
          {"criterio": "direccion", "tipo": "flexible", "umbral": 0.85}]
UMBRAL_DIRECCION = next(r["umbral"] for r in REGLAS if r["criterio"] == "direccion")
CAMPOS_COMPLETAR = ("web", "direccion")   # los campos que aplica «Completar la empresa» (además del teléfono)
FUENTES = {"carga": "una carga", "sala": "la sala", "sav": "la sala (.sav)", "manual": "una edición manual",
           "enriquecimiento": "un enriquecimiento", "descubrimiento": "otro descubrimiento", "fusion": "una fusión"}


def consulta_texto(consulta: str | None, rubro: str | None, departamento: str | None, localidad: str | None) -> tuple[str, str]:
    """(texto de la búsqueda, rubro). «imprentas en Salto» o rubro + localidad + departamento."""
    if consulta and consulta.strip():
        texto = consulta.strip()
        r = texto.split(" en ")[0].strip() if " en " in texto else (rubro or texto)
        return (texto if "uruguay" in texto.lower() else f"{texto}, Uruguay"), (rubro or r).strip()
    if not rubro or not rubro.strip():
        raise HTTPException(422, "Escribí la búsqueda («imprentas en Salto») o el rubro")
    lugar = ", ".join(x for x in (localidad, departamento) if x)
    return f"{rubro.strip()} en {lugar or 'Uruguay'}{', Uruguay' if lugar else ''}", rubro.strip()


def estimar(conn, actor: str, consulta: str | None = None, rubro: str | None = None, departamento: str | None = None,
            localidad: str | None = None, paginas: int = 1) -> dict:
    cfg, _ = enr.cfg_vigente(conn)
    texto, rub = consulta_texto(consulta, rubro, departamento, localidad)
    paginas = max(1, min(int(paginas or 1), cfg["max_paginas_descubrimiento"]))
    estado = enr.estado_proveedores(conn, cfg)
    if not estado["google_places"]["configurado"]:
        raise HTTPException(409, "Google Places no está configurado (Configuración → Enriquecimiento)")
    if not estado["google_places"]["activo"]:
        raise HTTPException(409, "Google Places está desactivado en la configuración")
    mes = enr.gasto_mes(conn)
    gratis = max(0, cfg["places_gratis_mes"] - enr.places_mes(conn))
    maximo = round(max(0, paginas - gratis) * cfg["precio_places"], 4)
    restante = max(0.0, cfg["tope_mensual"] - mes)
    permitido = round(min(cfg["tope_corrida"], restante), 4)
    est = {"consulta": texto, "rubro": rub, "paginas": paginas, "maximo": maximo, "places_gratis": min(paginas, gratis),
           "precio_pagina": cfg["precio_places"], "gasto_mes": round(mes, 4), "tope_mensual": cfg["tope_mensual"],
           "restante_mes": round(restante, 4), "tope_corrida": cfg["tope_corrida"], "permitido": permitido,
           "excede": maximo > permitido + 1e-9, "max_resultados": paginas * 20}
    c = conn.execute(
        "INSERT INTO enriquecimiento_corrida (tipo, origen, filtros, estimacion, creado_por)"
        " VALUES ('descubrimiento', 'descubrimiento', %s, %s, %s) RETURNING id",
        (Jsonb({"consulta": texto, "rubro": rub, "departamento": departamento, "localidad": localidad, "paginas": paginas}),
         Jsonb(est), actor)).fetchone()
    return enr.detalle(conn, c["id"])


def _corrida(conn, cid: int, estados: tuple) -> dict:
    c = conn.execute("SELECT * FROM enriquecimiento_corrida WHERE id = %s AND tipo = 'descubrimiento' FOR NO KEY UPDATE",
                     (cid,)).fetchone()
    if c is None:
        raise HTTPException(404, "Búsqueda inexistente")
    if c["estado"] not in estados:
        raise HTTPException(409, f"La búsqueda está {c['estado']}")
    return c


def buscar(conn, cid: int, actor: str) -> dict:
    """Aprueba la estimación y hace las llamadas (una por página). Deja el preview clasificado; no guarda empresas."""
    c = _corrida(conn, cid, ("estimada",))
    est, f = c["estimacion"], c["filtros"]
    if est.get("excede"):
        raise HTTPException(409, f"El costo máximo (US${est['maximo']:.2f}) supera lo permitido (US${est['permitido']:.2f})")
    cfg, _ = enr.cfg_vigente(conn)
    conn.execute("UPDATE enriquecimiento_corrida SET aprobada = now(), aprobada_por = %s WHERE id = %s", (actor, cid))
    lugares, token, avisos = [], None, []
    for pagina in range(est["paginas"]):
        r = enr.reservar(cid, None, "google_places", cfg["precio_places"], est["permitido"], cfg, f["consulta"])
        if r is None:
            avisos.append("La búsqueda se detuvo al llegar al tope de gasto")
            break
        pid, costo = r
        try:
            nuevos, token = proveedores.places_buscar(f["consulta"], token)
        except proveedores.ProveedorError as e:
            enr.cerrar_paso(pid, costo if e.cobrada else 0, "error", {"error": str(e), "pagina": pagina + 1})
            avisos.append(str(e))
            break
        enr.cerrar_paso(pid, costo, "ok" if nuevos else "sin_resultado", {"pagina": pagina + 1, "resultados": len(nuevos)})
        lugares += nuevos
        if not token:
            break
    filas = [clasificar(conn, i, l) for i, l in enumerate(lugares)]
    agregar_aportes(conn, filas, cfg)
    resumen = {k: sum(1 for x in filas if x["caso"] == k) for k in ("ya_guardado", "coincide", "nueva")}
    resumen["aportan"] = sum(1 for x in filas if x["caso"] == "coincide" and x.get("aporta_algo"))
    gasto = conn.execute("SELECT coalesce(sum(costo), 0) AS g FROM enriquecimiento_paso WHERE corrida_id = %s",
                         (cid,)).fetchone()["g"]
    conn.execute("UPDATE enriquecimiento_corrida SET estado = 'preview', gasto = %s, resultado = %s WHERE id = %s",
                 (gasto, Jsonb({"resultados": filas, "resumen": resumen, "avisos": avisos}), cid))
    auditoria.registrar(conn, actor, "descubrimiento.buscar", "enriquecimiento_corrida", cid,
                        {"consulta": f["consulta"], "resultados": len(filas), "gasto": float(gasto), **resumen})
    return enr.detalle(conn, cid)


def clasificar(conn, i: int, l) -> dict:
    n = telmod.normalizar(l.telefono) if l.telefono else None
    e164 = n.e164 if n and n.discable else None
    fila = {"i": i, "place_id": l.place_id, "nombre": l.nombre, "direccion": l.direccion, "telefono": e164,
            "web": l.web, "departamento": l.departamento, "localidad": l.localidad, "cerrado": l.cerrado}
    ya = conn.execute("SELECT e.id, e.codigo, e.razon_social FROM empresa_atributo ea JOIN atributo a ON a.id = ea.atributo_id"
                      " JOIN empresa e ON e.id = ea.empresa_id WHERE a.clave = 'google_place_id' AND ea.valor_texto = %s"
                      " AND e.baja IS NULL LIMIT 1", (l.place_id,)).fetchone()
    if ya:
        return {**fila, "caso": "ya_guardado", "empresa": ya, "accion": "omitir", "marcada": False}
    datos = {"razon_social": l.nombre, "direccion": l.direccion, "departamento": l.departamento, "web": l.web}
    m = provisorias.cascada(conn, REGLAS, None, datos, [e164] if e164 else [])
    if m:
        cand = m["candidata"]
        return {**fila, "caso": "coincide", "accion": "completar", "marcada": m["accion"] == "fusionar",
                "regla": m["regla"]["criterio"], "tipo": m["regla"]["tipo"], "similitud": m["similitud"],
                "empresa": {"id": cand["id"], "codigo": cand["codigo"], "razon_social": cand["razon_social"],
                            "base": cand["base"]}, "candidatas": m["candidatas"]}
    return {**fila, "caso": "nueva", "accion": "alta", "marcada": not l.cerrado}


def _web_igual(a, b) -> bool:
    da, db = proveedores.dominio(a), proveedores.dominio(b)
    return da == db if da and db else str(a or "").strip().lower().rstrip("/") == str(b or "").strip().lower().rstrip("/")


def similitudes_direccion(conn, pares: list[tuple[str, str]]) -> dict[tuple[str, str], float]:
    """Similitud de trigramas de cada par de direcciones normalizadas (las mismas que usa la regla «direccion»),
    en una sola consulta."""
    pares = sorted({(provisorias.direccion_normalizada(a), provisorias.direccion_normalizada(b)) for a, b in pares
                    if a and b})
    if not pares:
        return {}
    return {(r["x"], r["y"]): float(r["s"]) for r in conn.execute(
        "SELECT x, y, similarity(x, y) AS s FROM unnest(%s::text[], %s::text[]) AS t(x, y)",
        ([a for a, _ in pares], [b for _, b in pares]))}


def _direccion_igual(a, b, sim: dict) -> bool:
    na, nb = provisorias.direccion_normalizada(a), provisorias.direccion_normalizada(b)
    return bool(na) and (na == nb or sim.get((na, nb), 0.0) >= UMBRAL_DIRECCION)


def _motivo_historia(vigente: dict, confianza: int) -> str:
    fuente = FUENTES.get(vigente["fuente_tipo"], vigente["fuente_tipo"])
    if vigente["fuente_tipo"] in empresas.FUENTES_SALA:
        return f"el vigente viene de {fuente}"
    if vigente["confianza"] > confianza:
        return f"el vigente tiene más confianza ({vigente['confianza']} contra {confianza}; viene de {fuente})"
    return f"el vigente es igual de confiable y más reciente (viene de {fuente})"


def agregar_aportes(conn, filas: list[dict], cfg: dict) -> None:
    """A1 (D58): agrega «aporta» y «aporta_algo» a cada fila «coincide» y ajusta su acción por defecto. Los datos de
    las empresas coincidentes se precargan para todo el lote: 4 consultas como máximo, sin importar las filas."""
    coinciden = [f for f in filas if f["caso"] == "coincide" and f.get("empresa")]
    if not coinciden:
        return
    ids = sorted({f["empresa"]["id"] for f in coinciden})
    emps = {r["id"]: r for r in conn.execute(
        "SELECT e.id, e.web, e.direccion, (SELECT ea.valor_texto FROM empresa_atributo ea JOIN atributo a"
        "  ON a.id = ea.atributo_id WHERE a.clave = 'google_place_id' AND ea.empresa_id = e.id LIMIT 1) AS place_id"
        " FROM empresa e WHERE e.id = ANY(%s)", (ids,))}
    historia: dict[tuple[int, str], list] = {}
    for h in conn.execute(empresas._CANDIDATOS_VARIAS + " AND h.campo = ANY(%s)", (ids, list(CAMPOS_COMPLETAR))):
        historia.setdefault((h["empresa_id"], h["campo"]), []).append(h)
    e164s = sorted({f["telefono"] for f in coinciden if f["telefono"]})
    tiene = {(r["empresa_id"], r["e164"]) for r in conn.execute(
        "SELECT v.empresa_id, t.e164 FROM telefono_vinculo v JOIN telefono t ON t.id = v.telefono_id"
        " WHERE v.empresa_id = ANY(%s) AND t.e164 = ANY(%s)", (ids, e164s))} if e164s else set()
    sim = similitudes_direccion(conn, [(f["direccion"], emps.get(f["empresa"]["id"], {}).get("direccion"))
                                       for f in coinciden])
    ahora = datetime.now(timezone.utc)
    for f in coinciden:
        eid = f["empresa"]["id"]
        e = emps.get(eid) or {"web": None, "direccion": None, "place_id": None}
        aporta = [{"dato": "telefono", "valor": f["telefono"],
                   "estado": "sin_dato" if not f["telefono"] else "igual" if (eid, f["telefono"]) in tiene else "nuevo"}]
        for campo, igual in (("web", _web_igual), ("direccion", lambda a, b: _direccion_igual(a, b, sim))):
            valor, actual = f.get(campo), e[campo]
            item = {"dato": campo, "valor": valor, "actual": actual}
            if not valor or not str(valor).strip():
                item["estado"] = "sin_dato"
            elif not actual:
                item["estado"] = "nuevo"
            elif igual(valor, actual):
                item["estado"] = "igual"
            else:
                # Distinto: la misma regla de supervivencia, con la fila que agregaría el descubrimiento
                filas_h = historia.get((eid, campo), [])
                candidata = {"id": float("inf"), "valor": str(valor), "fuente_tipo": "descubrimiento",
                             "confianza": cfg["confianza"], "fecha": ahora}
                g = empresas.ganador(filas_h + [candidata])
                if g is candidata:
                    item["estado"] = "reemplaza"
                else:
                    item["estado"] = "solo_historia"
                    item["motivo"] = _motivo_historia(empresas.ganador(filas_h), cfg["confianza"])
            aporta.append(item)
        # El place ID se informa, pero no cuenta como aporte: toda coincidencia que no estaba guardada lo trae
        aporta.append({"dato": "place_id", "valor": f["place_id"], "actual": e["place_id"], "estado":
                       "nuevo" if not e["place_id"] else "igual" if e["place_id"] == f["place_id"] else "distinto"})
        f["aporta"] = aporta
        f["aporta_algo"] = any(a["estado"] in ("nuevo", "reemplaza") for a in aporta if a["dato"] != "place_id")
        # Por defecto: «Completar» solo si la regla es exacta Y aporta algo; si no, «No guardar»
        f["marcada"] = bool(f["marcada"] and f["aporta_algo"])


def _resultado_real(antes, valor, cambio: bool, igual) -> str | None:
    """A3: lo que pasó con un campo al completar ("nuevo" | "igual" | "reemplazo" | "historia"), o None sin dato."""
    if not valor or not str(valor).strip():
        return None
    if not antes:
        return "nuevo"
    if igual(valor, antes):
        return "igual"
    return "reemplazo" if cambio else "historia"


def confirmar(conn, cid: int, seleccion: dict[str, str], actor: str) -> dict:
    """seleccion: {índice: "alta" | "completar" | "omitir"}. Lo que no figura se toma con su acción marcada por defecto."""
    c = _corrida(conn, cid, ("preview",))
    cfg, params = enr.cfg_vigente(conn)
    filas = c["resultado"]["resultados"]
    rubro = (c["filtros"] or {}).get("rubro")
    conteo = {"altas": 0, "completadas": 0, "omitidas": 0, "telefonos": 0, "sin_cambios": 0}
    detalle, tel_ids = [], []
    for f in filas:
        accion = seleccion.get(str(f["i"]), f["accion"] if f["marcada"] else "omitir")
        if accion == "omitir" or f["caso"] == "ya_guardado":
            conteo["omitidas"] += 1
            continue
        if accion == "alta":
            emp = conn.execute("INSERT INTO empresa (rut, base, alta_corrida_id) VALUES (NULL, 'provisoria', %s) RETURNING *",
                               (cid,)).fetchone()
            valores = {"razon_social": f["nombre"], "direccion": f["direccion"], "departamento": f["departamento"],
                       "localidad": f["localidad"], "web": f["web"]}
            conteo["altas"] += 1
        elif accion == "completar" and f.get("empresa"):
            emp = conn.execute("SELECT * FROM empresa WHERE id = %s", (f["empresa"]["id"],)).fetchone()
            if emp is None or emp["baja"]:
                conteo["omitidas"] += 1
                continue
            valores = {"direccion": f["direccion"], "web": f["web"]}
            conteo["completadas"] += 1
        else:
            raise HTTPException(422, f"Acción inválida para el resultado {f['i']}: {accion}")
        cambios, _ = empresas.aplicar_valores(conn, emp["id"], valores, "descubrimiento", cid, cfg["confianza"], actor,
                                              {"lote": cid, "place_id": f["place_id"]})
        attrs = {"google_place_id": {"valor": f["place_id"]}}
        if rubro:
            attrs["rubro_descubrimiento"] = {"valor": rubro}
        empresas.aplicar_atributos(conn, emp["id"], attrs, "descubrimiento", cid, cfg["confianza"], actor)
        tel = None
        if f["telefono"]:
            t, _, _ = empresas.telefono(conn, f["telefono"])
            _, nuevo = empresas.vincular(conn, t["id"], emp["id"], "descubrimiento", cid, actor, origen="google_places",
                                         detalle={"lote": cid, "place_id": f["place_id"]})
            conteo["telefonos"] += int(nuevo)
            tel_ids.append(t["id"])
            tel = "nuevo" if nuevo else "ya_tenia"
        if accion == "completar":
            # A3 (D58): lo que pasó de verdad, con las mismas comparaciones que el preview
            sim = similitudes_direccion(conn, [(f["direccion"], emp["direccion"])])
            d = {"i": f["i"], "empresa_id": emp["id"], "telefono": tel,
                 "web": _resultado_real(emp["web"], f["web"], "web" in cambios, _web_igual),
                 "direccion": _resultado_real(emp["direccion"], f["direccion"], "direccion" in cambios,
                                              lambda a, b: _direccion_igual(a, b, sim))}
            detalle.append(d)
            if tel != "nuevo" and d["web"] not in ("nuevo", "reemplazo") and d["direccion"] not in ("nuevo", "reemplazo"):
                conteo["sin_cambios"] += 1
    if tel_ids:
        intermediarios.detectar(conn, int(params["umbral_intermediario"]), tel_ids, actor)
    res = {**c["resultado"], "confirmado": {**conteo, "detalle": detalle}}
    conn.execute("UPDATE enriquecimiento_corrida SET estado = 'confirmada', resultado = %s, terminada = now() WHERE id = %s",
                 (Jsonb(res), cid))
    auditoria.registrar(conn, actor, "descubrimiento.confirmar", "enriquecimiento_corrida", cid, conteo)  # sin el detalle
    mantenimiento.al_terminar(f"descubrimiento #{cid}", mantenimiento.ENRIQUECIMIENTO)
    return enr.detalle(conn, cid)


def deshacer(conn, cid: int, actor: str) -> dict:
    _corrida(conn, cid, ("confirmada",))
    altas = [r["id"] for r in conn.execute("SELECT id FROM empresa WHERE alta_corrida_id = %s AND baja IS NULL", (cid,))]
    en_muestra = conn.execute("SELECT count(DISTINCT empresa_id) AS n FROM muestra_item WHERE empresa_id = ANY(%s)",
                              (altas,)).fetchone()["n"]
    if en_muestra:
        raise HTTPException(409, f"No se puede deshacer: {en_muestra} empresas de este lote ya entraron a una muestra")
    conn.execute("UPDATE enriquecimiento_corrida SET estado = 'deshecha', deshecha = now(), deshecha_por = %s WHERE id = %s",
                 (actor, cid))
    r = enr.quitar_datos(conn, cid, "descubrimiento", actor)
    anuladas = 0
    for eid in altas:
        quedan = conn.execute(
            "SELECT (SELECT count(*) FROM empresa_campo_historia h LEFT JOIN enriquecimiento_corrida c"
            "        ON h.fuente_tipo IN ('enriquecimiento', 'descubrimiento') AND c.id = h.fuente_id"
            "        LEFT JOIN carga g ON h.fuente_tipo = 'carga' AND g.id = h.fuente_id"
            "        WHERE h.empresa_id = %s AND (c.id IS NULL OR c.deshecha IS NULL) AND (g.id IS NULL OR NOT " + empresas.CARGA_SIN_EFECTO.replace("c.", "g.") + "))"
            " + (SELECT count(*) FROM telefono_vinculo WHERE empresa_id = %s)"
            " + (SELECT count(*) FROM contacto WHERE empresa_id = %s) AS n", (eid, eid, eid)).fetchone()["n"]
        if quedan == 0:
            conn.execute("UPDATE empresa SET baja = 'anulada', actualizado = now() WHERE id = %s", (eid,))
            anuladas += 1
    r["provisorias_anuladas"] = anuladas
    auditoria.registrar(conn, actor, "descubrimiento.deshacer", "enriquecimiento_corrida", cid, r)
    mantenimiento.al_terminar(f"descubrimiento #{cid} deshecho", mantenimiento.ENRIQUECIMIENTO)
    return r


# ─── P1 (D58): el preview en CSV, con «Qué aporta» y, si está confirmado, «Qué se agregó» ───

NOMBRE_DATO = {"telefono": ("Teléfono", "nuevo"), "web": ("Sitio", "nuevo"), "direccion": ("Dirección", "nueva")}
ESTADO_REAL = {"nuevo": "nuevo", "ya_tenia": "ya lo tenía", "igual": "igual", "reemplazo": "reemplazó al vigente",
               "historia": "solo en la historia"}


def texto_aporta(fila: dict) -> str:
    """«Teléfono nuevo · Sitio distinto: reemplaza» o «No aporta nada» (las mismas etiquetas que la pantalla)."""
    if "aporta" not in fila:
        return ""
    partes = []
    for a in fila["aporta"]:
        if a["dato"] not in NOMBRE_DATO:
            continue
        nombre, nuevo = NOMBRE_DATO[a["dato"]]
        if a["estado"] == "nuevo":
            partes.append(f"{nombre} {nuevo}")
        elif a["estado"] == "reemplaza":
            partes.append(f"{nombre} distint{'a' if nuevo == 'nueva' else 'o'}: reemplaza")
        elif a["estado"] == "solo_historia":
            partes.append(f"{nombre} distint{'a' if nuevo == 'nueva' else 'o'}: solo historia")
    if not fila.get("aporta_algo"):
        return "No aporta nada" + (f" ({' · '.join(partes)})" if partes else "")
    return " · ".join(partes)


def texto_agregado(d: dict | None) -> str:
    if not d:
        return ""
    return " · ".join(f"{NOMBRE_DATO[k][0]}: {ESTADO_REAL[d[k]]}" for k in ("telefono", "web", "direccion") if d.get(k))


def preview_csv(conn, cid: int) -> tuple[list[str], list[list]]:
    c = conn.execute("SELECT * FROM enriquecimiento_corrida WHERE id = %s AND tipo = 'descubrimiento'", (cid,)).fetchone()
    if c is None:
        raise HTTPException(404, "Búsqueda inexistente")
    r = c["resultado"] or {}
    detalle = {d["i"]: d for d in ((r.get("confirmado") or {}).get("detalle") or [])}
    cab = ["caso", "nombre_places", "direccion_places", "telefono_places", "web_places", "place_id", "rut_base",
           "razon_social_base", "regla", "similitud", "que_aporta", "accion_sugerida", "que_se_agrego"]
    filas = []
    for f in r.get("resultados") or []:
        e = f.get("empresa") or {}
        sugerida = "omitir" if f["caso"] == "ya_guardado" or not f.get("marcada") else f.get("accion")
        filas.append([f["caso"], f["nombre"], f.get("direccion"), f.get("telefono"), f.get("web"), f.get("place_id"),
                      e.get("codigo"), e.get("razon_social"), f.get("regla"), f.get("similitud"), texto_aporta(f),
                      sugerida, texto_agregado(detalle.get(f["i"]))])
    return cab, filas
