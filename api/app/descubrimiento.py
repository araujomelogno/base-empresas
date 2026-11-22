"""Descubrimiento de empresas nuevas por rubro y zona en Google Places (SPEC_fase2_enriquecimiento, B5 / etapa C).

Una búsqueda («imprentas en Salto») es un lote «Descubrimiento #N»: se estima el costo (una llamada Text Search por
página, con los mismos topes que el enriquecimiento), se aprueba, se busca y cada resultado se compara con la base:
  - mismo place_id ya guardado → se informa, no se hace nada;
  - coincide con una empresa (teléfono, sitio o nombre y dirección, con las reglas de fusión) → se ofrece completarla
    (con decisión humana si la regla es flexible);
  - no coincide con nada → alta en la base provisoria con origen Google Places.
Nada se guarda hasta confirmar. El lote tiene linaje (fuente «descubrimiento»), se puede deshacer y queda en Auditoría.
"""
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, empresas, enriquecimiento as enr, intermediarios, config, proveedores, provisorias
from . import telefonos as telmod

REGLAS = [{"criterio": "telefono", "tipo": "exacta"}, {"criterio": "dominio_web", "tipo": "exacta"},
          {"criterio": "razon_social", "tipo": "flexible", "umbral": 0.85},
          {"criterio": "direccion", "tipo": "flexible", "umbral": 0.85}]


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
    resumen = {k: sum(1 for x in filas if x["caso"] == k) for k in ("ya_guardado", "coincide", "nueva")}
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


def confirmar(conn, cid: int, seleccion: dict[str, str], actor: str) -> dict:
    """seleccion: {índice: "alta" | "completar" | "omitir"}. Lo que no figura se toma con su acción marcada por defecto."""
    c = _corrida(conn, cid, ("preview",))
    cfg, params = enr.cfg_vigente(conn)
    filas = c["resultado"]["resultados"]
    rubro = (c["filtros"] or {}).get("rubro")
    conteo = {"altas": 0, "completadas": 0, "omitidas": 0, "telefonos": 0}
    tel_ids = []
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
        empresas.aplicar_valores(conn, emp["id"], valores, "descubrimiento", cid, cfg["confianza"], actor,
                                 {"lote": cid, "place_id": f["place_id"]})
        attrs = {"google_place_id": {"valor": f["place_id"]}}
        if rubro:
            attrs["rubro_descubrimiento"] = {"valor": rubro}
        empresas.aplicar_atributos(conn, emp["id"], attrs, "descubrimiento", cid, cfg["confianza"], actor)
        if f["telefono"]:
            t, _, _ = empresas.telefono(conn, f["telefono"])
            _, nuevo = empresas.vincular(conn, t["id"], emp["id"], "descubrimiento", cid, actor, origen="google_places",
                                         detalle={"lote": cid, "place_id": f["place_id"]})
            conteo["telefonos"] += int(nuevo)
            tel_ids.append(t["id"])
    if tel_ids:
        intermediarios.detectar(conn, int(params["umbral_intermediario"]), tel_ids, actor)
    res = {**c["resultado"], "confirmado": conteo}
    conn.execute("UPDATE enriquecimiento_corrida SET estado = 'confirmada', resultado = %s, terminada = now() WHERE id = %s",
                 (Jsonb(res), cid))
    auditoria.registrar(conn, actor, "descubrimiento.confirmar", "enriquecimiento_corrida", cid, conteo)
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
    return r
