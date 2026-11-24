"""Enriquecimiento bajo demanda con topes (SPEC_fase2_enriquecimiento, B1 a B3; D46).

Flujo: estimar (crea la corrida «estimada», sin gastar) → aprobar (con un tope por corrida y el tope mensual
duro) → tarea en Cloud Tasks que recorre las empresas con la cascada de lo más barato a lo más caro:
fuentes propias (US$0) → Google Places → Brave (si falta sitio) → lectura del sitio + Claude (si falta teléfono).
Según la configuración (Q1), la cascada se corta apenas hay un teléfono o sigue hasta tener teléfono y sitio.

Topes: antes de cada llamada paga se RESERVA su costo máximo en enriquecimiento_paso, con un lock, verificando
el gasto de la corrida y el del mes. Si no entra, la corrida se detiene («detenida por tope») sin hacer la llamada.
Lo conseguido se guarda empresa por empresa: cancelar o llegar al tope no pierde lo hecho.

Datos: teléfonos «sin verificar» con origen Google Places o Sitio web; sitio, dirección y email institucional
como historia con fuente «enriquecimiento» y confianza baja (no pisan datos de mejor fuente). Una corrida se
puede deshacer: se quitan sus vínculos y valores, salvo los teléfonos que la sala ya verificó.
"""
import datetime as dt
import random

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, catalogos, config, empresas, intermediarios, mantenimiento, proveedores, provisorias, secretos, settings, tareas
from .db import conexion
from .util import razon_normalizada

PROVEEDORES = config.PROVEEDORES
NOMBRES = {"google_places": "Google Places", "brave": "Brave Search", "claude": "Claude", "sitio": "Lectura del sitio",
           "propias": "Fuentes propias"}
ORIGEN_DE = {"google_places": "google_places", "claude": "web"}   # origen del teléfono según el paso que lo trajo
MOTIVO_ESTUDIO = "sitio de estudio contable/jurídico (enriquecimiento)"
TERMINADAS = ("terminada", "detenida_tope", "cancelada", "error")
_LOCK = "SELECT pg_advisory_xact_lock(hashtext('enriquecimiento_gasto'))"


def cfg_vigente(conn) -> tuple[dict, dict]:
    _, params = config.vigente(conn)
    return config.enriquecimiento(params), params


# ─────────────────────────────────────────────────────────────
# Proveedores: claves (Secret Manager) y estado
# ─────────────────────────────────────────────────────────────

def estado_proveedores(conn, cfg: dict | None = None) -> dict:
    cfg = cfg or cfg_vigente(conn)[0]
    out = {}
    for p in PROVEEDORES:
        ultimo = conn.execute("SELECT actor, fecha FROM auditoria WHERE accion = 'config.clave_proveedor' AND objeto_id = %s"
                              " ORDER BY id DESC LIMIT 1", (p,)).fetchone()
        configurado = bool(proveedores.clave(p))
        out[p] = {"nombre": NOMBRES[p], "activo": bool(cfg[f"{p}_activo"]), "configurado": configurado,
                  "estado": "no configurado" if not configurado else "activo" if cfg[f"{p}_activo"] else "desactivado",
                  "fecha": ultimo["fecha"] if ultimo and configurado else None,
                  "por": ultimo["actor"] if ultimo and configurado else None}
    return out


def guardar_clave(conn, proveedor: str, valor: str, actor: str) -> dict:
    if proveedor not in PROVEEDORES:
        raise HTTPException(404, "Proveedor desconocido")
    if not valor or not valor.strip():
        raise HTTPException(422, "La clave está vacía")
    secretos.guardar(settings.SECRETOS_PROVEEDORES[proveedor], valor.strip())
    # Nunca el valor: solo qué secreto se actualizó
    auditoria.registrar(conn, actor, "config.clave_proveedor", "config", proveedor,
                        {"secreto": settings.SECRETOS_PROVEEDORES[proveedor]})
    return estado_proveedores(conn)[proveedor]


def _usable(estado: dict, p: str) -> bool:
    return estado[p]["activo"] and estado[p]["configurado"]


# ─────────────────────────────────────────────────────────────
# Gasto
# ─────────────────────────────────────────────────────────────

def gasto_mes(conn) -> float:
    r = conn.execute("SELECT coalesce(sum(costo), 0) AS g FROM enriquecimiento_paso"
                     " WHERE fecha >= date_trunc('month', now())").fetchone()
    return float(r["g"])


def places_mes(conn) -> int:
    """Llamadas a Places en el mes (cuentan contra las gratuitas)."""
    return conn.execute("SELECT count(*) AS n FROM enriquecimiento_paso WHERE proveedor = 'google_places'"
                        " AND resultado IN ('ok', 'sin_resultado', 'en_curso') AND fecha >= date_trunc('month', now())"
                        ).fetchone()["n"]


def costo_claude(cfg: dict, entrada: int, salida: int) -> float:
    return (entrada * cfg["precio_claude_entrada"] + salida * cfg["precio_claude_salida"]) / 1_000_000


def resumen_gasto(conn) -> dict:
    """Tarjeta de enriquecimiento del tablero de calidad: gasto del mes contra el tope y costo por teléfono verificado."""
    cfg, _ = cfg_vigente(conn)
    mes = gasto_mes(conn)
    por = {r["proveedor"]: float(r["g"]) for r in conn.execute(
        "SELECT proveedor, sum(costo) AS g FROM enriquecimiento_paso WHERE fecha >= date_trunc('month', now())"
        " GROUP BY proveedor")}
    total = float(conn.execute("SELECT coalesce(sum(costo), 0) AS g FROM enriquecimiento_paso").fetchone()["g"])
    enr = ("FROM telefono_vinculo v WHERE EXISTS (SELECT 1 FROM telefono_vinculo_origen x JOIN origen_telefono o"
           " ON o.id = x.origen_id WHERE x.vinculo_id = v.id AND o.codigo IN ('google_places', 'web'))")
    verif_total = conn.execute(f"SELECT count(*) AS n {enr} AND v.estado = 'verificado'").fetchone()["n"]
    verif_mes = conn.execute(
        f"SELECT count(*) AS n {enr} AND v.estado = 'verificado' AND EXISTS (SELECT 1 FROM telefono_vinculo_historia h"
        " WHERE h.vinculo_id = v.id AND h.estado = 'verificado' AND h.fecha >= date_trunc('month', now()))").fetchone()["n"]
    return {"gasto_mes": round(mes, 4), "tope_mensual": cfg["tope_mensual"],
            "restante_mes": round(max(0.0, cfg["tope_mensual"] - mes), 4),
            "por_proveedor": {NOMBRES.get(k, k): round(v, 4) for k, v in por.items() if v},
            "gasto_total": round(total, 4), "verificados_mes": verif_mes, "verificados_total": verif_total,
            "costo_por_verificado_mes": round(mes / verif_mes, 4) if verif_mes else None,
            "costo_por_verificado_total": round(total / verif_total, 4) if verif_total else None,
            "meta_costo_por_verificado": 0.10, "places_gratis_restantes": max(0, cfg["places_gratis_mes"] - places_mes(conn))}


def tasa_exito_places(conn, cfg: dict) -> float:
    r = conn.execute("SELECT count(*) AS n, count(*) FILTER (WHERE (p.detalle->>'telefono')::boolean) AS ok"
                     " FROM enriquecimiento_paso p JOIN enriquecimiento_corrida c ON c.id = p.corrida_id"
                     " WHERE p.proveedor = 'google_places' AND c.tipo = 'enriquecimiento'"
                     " AND p.resultado IN ('ok', 'sin_resultado')").fetchone()
    return round(r["ok"] / r["n"], 3) if r["n"] >= 20 else cfg["tasa_exito_places"]


# ─────────────────────────────────────────────────────────────
# Estimación (antes de gastar)
# ─────────────────────────────────────────────────────────────

_EMPRESAS_SQL = """
SELECT e.id, e.codigo, e.base, e.baja, e.estado, e.razon_social, e.fantasia, e.departamento, e.localidad, e.web,
       EXISTS (SELECT 1 FROM v_vinculo_discable d WHERE d.empresa_id = e.id) AS tiene_telefono,
       EXISTS (SELECT 1 FROM v_vinculo_discable d WHERE d.empresa_id = e.id AND d.estado = 'verificado') AS verificado,
       EXISTS (SELECT 1 FROM no_llamar n WHERE n.activo AND n.alcance = 'empresa' AND n.objeto_id = e.id) AS no_llamar,
       EXISTS (SELECT 1 FROM enriquecimiento_paso p JOIN enriquecimiento_corrida c ON c.id = p.corrida_id
               WHERE p.empresa_id = e.id AND c.tipo = 'enriquecimiento' AND c.deshecha IS NULL
                 AND p.proveedor <> 'propias' AND p.fecha > now() - make_interval(days => %(dias)s)) AS reciente,
       (SELECT ea.valor_texto FROM empresa_atributo ea JOIN atributo a ON a.id = ea.atributo_id
         WHERE a.clave = 'google_place_id' AND ea.empresa_id = e.id) AS place_id
FROM empresa e WHERE e.id = ANY(%(ids)s)
"""

MOTIVOS = {
    "no_llamar": "están en «no llamar»",
    "verificado": "ya tienen un teléfono verificado",
    "reciente": "se enriquecieron en los últimos {dias} días",
    "tiene_telefono": "ya tienen un teléfono discable (no se gasta en ellas)",
    "completa": "ya tienen teléfono y sitio web",
    "candidata": "son provisorias con candidata en la definitiva: conviene fusionarlas",
    "cerrada": "están cerradas o dadas de baja",
}


def _candidatos(conn, origen: str, muestra_id=None, filtros=None, rut=None, alcance="sin_telefono") -> list[int]:
    if origen == "muestra":
        if conn.execute("SELECT 1 FROM muestra WHERE id = %s", (muestra_id,)).fetchone() is None:
            raise HTTPException(404, "Muestra inexistente")
        cond = (" AND NOT EXISTS (SELECT 1 FROM v_vinculo_discable d WHERE d.empresa_id = i.empresa_id)"
                if alcance == "sin_telefono" else "")
        return [r["empresa_id"] for r in conn.execute(
            "SELECT i.empresa_id, min(i.estrato) AS est, min(i.orden) AS ord FROM muestra_item i WHERE i.muestra_id = %s"
            + cond + " GROUP BY i.empresa_id ORDER BY 2, 3, 1", (muestra_id,))]
    if origen == "lista":
        from .routers.empresas import filtros_busqueda

        f = dict(filtros or {})
        from . import disponibilidad
        from .routers.empresas import join_disponibilidad

        guardada = disponibilidad.asegurar(conn)
        where, args, _ = filtros_busqueda(conn, f.get("q"), f.get("departamento"), f.get("tamano"), f.get("naturaleza"),
                                          f.get("disponible"), f.get("base") or "definitiva", f.get("sin_telefono"),
                                          f.get("sin_web"), f.get("rut_verificado"), guardada=guardada)
        return [r["id"] for r in conn.execute(
            "SELECT e.id FROM empresa e LEFT JOIN naturaleza_juridica n ON n.id = e.naturaleza_id"
            + join_disponibilidad(guardada) +
            f" WHERE {' AND '.join(where)} ORDER BY e.razon_social NULLS LAST, e.codigo LIMIT 100001", args)]
    emp = empresas.obtener_o_404(conn, rut)
    return [emp["id"]]


def _clasificar(conn, ids: list[int], cfg: dict) -> tuple[list[dict], dict]:
    filas = {r["id"]: r for r in conn.execute(_EMPRESAS_SQL, {"ids": ids, "dias": cfg["dias_sin_reenriquecer"]})}
    umbral = float(config.vigente(conn)[1].get("umbral_fusion_flexible", 0.85))
    a_enriquecer, salteadas = [], {}
    for eid in ids:
        e = filas.get(eid)
        motivo = None
        if e is None or e["baja"] or e["estado"] == "cerrada":
            motivo = "cerrada"
        elif e["no_llamar"]:
            motivo = "no_llamar"
        elif e["verificado"]:
            motivo = "verificado"
        elif e["reciente"]:
            motivo = "reciente"
        elif e["tiene_telefono"] and (cfg["corte"] == "telefono" or e["web"]):
            motivo = "tiene_telefono" if cfg["corte"] == "telefono" else "completa"
        elif e["base"] == "provisoria" and provisorias.candidatas_definitiva(conn, e, umbral):
            motivo = "candidata"
        if motivo:
            salteadas[motivo] = salteadas.get(motivo, 0) + 1
        else:
            a_enriquecer.append(e)
    return a_enriquecer, salteadas


def _costos(cfg: dict, filas: list[dict], gratis: int, estado: dict, tasa: float) -> dict:
    """Costo máximo (todos los pasos para todas) y esperado (con la tasa de éxito de Places)."""
    n = len(filas)
    con_places = sum(1 for f in filas if not f.get("place_id")) if _usable(estado, "google_places") else 0
    pagas = max(0, con_places - gratis)
    places = pagas * cfg["precio_places"]
    brave = n * cfg["precio_brave"] if _usable(estado, "brave") else 0.0
    claude = (n * costo_claude(cfg, cfg["tokens_entrada_estimados"], cfg["tokens_salida_estimados"])
              if _usable(estado, "claude") else 0.0)
    resto = (1 - tasa) if con_places else 1.0
    return {"empresas": n, "llamadas_places": con_places, "places_gratis": min(con_places, gratis),
            "maximo": round(places + brave + claude, 4),
            "esperado": round(places + resto * (brave + claude), 4),
            "por_proveedor_maximo": {"Google Places": round(places, 4), "Brave Search": round(brave, 4),
                                     "Claude": round(claude, 4)}}


def _estimacion(conn, cfg: dict, filas: list[dict], salteadas: dict) -> dict:
    estado = estado_proveedores(conn, cfg)
    mes = gasto_mes(conn)
    gratis = max(0, cfg["places_gratis_mes"] - places_mes(conn))
    tasa = tasa_exito_places(conn, cfg)
    c = _costos(cfg, filas, gratis, estado, tasa)
    restante = max(0.0, cfg["tope_mensual"] - mes)
    permitido = round(min(cfg["tope_corrida"], restante), 4)
    # Cuántas empresas entran en lo permitido (y en el máximo por corrida)
    lo, hi = 0, min(len(filas), cfg["max_empresas_corrida"])
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _costos(cfg, filas[:mid], gratis, estado, tasa)["maximo"] <= permitido + 1e-9:
            lo = mid
        else:
            hi = mid - 1
    return {**c, "salteadas": {k: {"cantidad": v, "motivo": MOTIVOS[k].format(dias=cfg["dias_sin_reenriquecer"])}
                               for k, v in salteadas.items()},
            "gasto_mes": round(mes, 4), "tope_mensual": cfg["tope_mensual"], "restante_mes": round(restante, 4),
            "tope_corrida": cfg["tope_corrida"], "permitido": permitido, "max_empresas_permitidas": lo,
            "max_empresas_corrida": cfg["max_empresas_corrida"], "tasa_exito_places": tasa, "corte": cfg["corte"],
            "excede": c["maximo"] > permitido + 1e-9 or len(filas) > cfg["max_empresas_corrida"],
            "proveedores": {k: v["estado"] for k, v in estado.items()}, "precios": {
                "places": cfg["precio_places"], "brave": cfg["precio_brave"], "modelo_claude": cfg["modelo_claude"],
                "claude_entrada": cfg["precio_claude_entrada"], "claude_salida": cfg["precio_claude_salida"]}}


ORIGENES = ("muestra", "lista", "ficha")


def estimar(conn, origen: str, actor: str, muestra_id: int | None = None, filtros: dict | None = None,
            rut: str | None = None, alcance: str = "sin_telefono") -> dict:
    """Crea la corrida «estimada» con la lista de empresas, las salteadas y el costo. No gasta nada."""
    if origen not in ORIGENES:
        raise HTTPException(422, f"Origen desconocido: {origen}")
    if alcance not in ("sin_telefono", "todas"):
        raise HTTPException(422, "Alcance: sin_telefono o todas")
    cfg, _ = cfg_vigente(conn)
    ids = _candidatos(conn, origen, muestra_id, filtros, rut, alcance)
    if len(ids) > 100000:
        raise HTTPException(422, "Son más de 100.000 empresas: filtrá más la lista")
    filas, salteadas = _clasificar(conn, ids, cfg)
    est = _estimacion(conn, cfg, filas, salteadas)
    c = conn.execute(
        "INSERT INTO enriquecimiento_corrida (origen, muestra_id, filtros, empresa_ids, salteadas, estimacion, opciones,"
        " creado_por) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (origen, muestra_id, Jsonb({**(filtros or {}), **({"rut": rut} if rut else {})}) if (filtros or rut) else None,
         [f["id"] for f in filas], Jsonb(salteadas), Jsonb(est), Jsonb({"alcance": alcance, "candidatas": len(ids)}),
         actor)).fetchone()
    return detalle(conn, c["id"])


def aprobar(conn, corrida_id: int, actor: str, limite: int | None = None, reducir: str = "orden") -> dict:
    """Aprueba la estimación (si hace falta, reduciendo la cantidad de empresas) y crea la tarea. Devuelve la tarea."""
    c = conn.execute("SELECT * FROM enriquecimiento_corrida WHERE id = %s AND tipo = 'enriquecimiento' FOR NO KEY UPDATE",
                     (corrida_id,)).fetchone()
    if c is None:
        raise HTTPException(404, "Corrida inexistente")
    if c["estado"] != "estimada":
        raise HTTPException(409, "La corrida ya fue aprobada o descartada")
    if (dt.datetime.now(dt.timezone.utc) - c["creado"]).total_seconds() > 3600:
        raise HTTPException(409, "La estimación tiene más de una hora: volvé a estimar")
    cfg, _ = cfg_vigente(conn)
    ids = list(c["empresa_ids"])
    if not ids:
        raise HTTPException(422, "No hay empresas para enriquecer")
    if limite is not None:
        if limite < 1:
            raise HTTPException(422, "Indicá cuántas empresas enriquecer")
        if reducir == "azar":
            ids = sorted(random.Random(corrida_id).sample(ids, min(limite, len(ids))), key=ids.index)
        else:
            ids = ids[:limite]
    filas, _ = _clasificar(conn, ids, cfg)
    est = _estimacion(conn, cfg, filas, c["salteadas"])
    if est["excede"]:
        raise HTTPException(409, f"El costo máximo (US${est['maximo']:.2f}) supera lo permitido (US${est['permitido']:.2f})"
                                 f" o el máximo de {cfg['max_empresas_corrida']} empresas: enriquecé como máximo"
                                 f" {est['max_empresas_permitidas']} empresas")
    if not filas:
        raise HTTPException(422, "No hay empresas para enriquecer")
    est["aprobada"] = {"empresas": len(filas), "reducida": limite is not None, "reducir": reducir if limite else None}
    tarea_id = tareas.crear(conn, "enriquecimiento", {"corrida_id": corrida_id}, actor)
    conn.execute("UPDATE enriquecimiento_corrida SET estado = 'en_curso', empresa_ids = %s, estimacion = %s,"
                 " aprobada_por = %s, aprobada = now(), tarea_id = %s WHERE id = %s",
                 ([f["id"] for f in filas], Jsonb(est), actor, tarea_id, corrida_id))
    auditoria.registrar(conn, actor, "enriquecimiento.aprobar", "enriquecimiento_corrida", corrida_id,
                        {"empresas": len(filas), "costo_maximo": est["maximo"], "costo_esperado": est["esperado"],
                         "permitido": est["permitido"], "origen": c["origen"], "muestra_id": c["muestra_id"]})
    return {"corrida_id": corrida_id, "tarea_id": tarea_id}


def descartar(conn, corrida_id: int, actor: str) -> dict:
    r = conn.execute("UPDATE enriquecimiento_corrida SET estado = 'descartada' WHERE id = %s AND estado IN ('estimada', 'preview')"
                     " RETURNING id", (corrida_id,)).fetchone()
    if r is None:
        raise HTTPException(409, "Solo se descarta una estimación que no se aprobó")
    return {"descartada": corrida_id}


def cancelar(conn, corrida_id: int, actor: str) -> dict:
    c = conn.execute("SELECT * FROM enriquecimiento_corrida WHERE id = %s", (corrida_id,)).fetchone()
    if c is None:
        raise HTTPException(404, "Corrida inexistente")
    if c["estado"] != "en_curso":
        raise HTTPException(409, "Solo se cancela una corrida en curso")
    tareas.cancelar("id = %s", (c["tarea_id"],), f"Cancelada por {actor}")
    with conexion() as c2:  # visible enseguida: la tarea lo ve al pasar a la empresa siguiente
        c2.execute("UPDATE enriquecimiento_corrida SET estado = 'cancelada', terminada = now() WHERE id = %s"
                   " AND estado = 'en_curso'", (corrida_id,))
    auditoria.registrar(conn, actor, "enriquecimiento.cancelar", "enriquecimiento_corrida", corrida_id)
    return {"cancelada": corrida_id}


# ─────────────────────────────────────────────────────────────
# Reserva del gasto (tope duro antes de cada llamada paga)
# ─────────────────────────────────────────────────────────────

def reservar(corrida_id: int, empresa_id: int | None, proveedor: str, costo_max: float, tope_corrida: float,
             cfg: dict, consulta: str | None = None) -> tuple[int, float] | None:
    """Reserva el costo máximo de la llamada en su propia transacción (con lock). None si no entra en los topes."""
    with conexion() as r:
        r.execute(_LOCK)
        if proveedor == "google_places":
            costo_max = 0.0 if places_mes(r) < cfg["places_gratis_mes"] else cfg["precio_places"]
        mes = gasto_mes(r)
        corrida = float(r.execute("SELECT coalesce(sum(costo), 0) AS g FROM enriquecimiento_paso WHERE corrida_id = %s",
                                  (corrida_id,)).fetchone()["g"])
        if corrida + costo_max > tope_corrida + 1e-9 or mes + costo_max > cfg["tope_mensual"] + 1e-9:
            r.execute("INSERT INTO enriquecimiento_paso (corrida_id, empresa_id, proveedor, consulta, costo, resultado, detalle)"
                      " VALUES (%s,%s,%s,%s,0,'tope',%s)",
                      (corrida_id, empresa_id, proveedor, consulta, Jsonb({"gasto_corrida": round(corrida, 4),
                                                                           "gasto_mes": round(mes, 4),
                                                                           "costo_llamada": round(costo_max, 4)})))
            return None
        pid = r.execute("INSERT INTO enriquecimiento_paso (corrida_id, empresa_id, proveedor, consulta, costo, resultado)"
                        " VALUES (%s,%s,%s,%s,%s,'en_curso') RETURNING id",
                        (corrida_id, empresa_id, proveedor, consulta, costo_max)).fetchone()["id"]
        return pid, costo_max


def cerrar_paso(paso_id: int, costo: float, resultado: str, detalle: dict | None = None, place_id=None, url=None):
    with conexion() as r:
        r.execute("UPDATE enriquecimiento_paso SET costo = %s, resultado = %s, detalle = %s, place_id = %s, url = %s"
                  " WHERE id = %s", (round(costo, 6), resultado, Jsonb(detalle) if detalle else None, place_id, url, paso_id))


def paso_gratis(corrida_id, empresa_id, proveedor, resultado, detalle=None, url=None, consulta=None):
    with conexion() as r:
        r.execute("INSERT INTO enriquecimiento_paso (corrida_id, empresa_id, proveedor, consulta, costo, resultado, detalle, url)"
                  " VALUES (%s,%s,%s,%s,0,%s,%s,%s)", (corrida_id, empresa_id, proveedor, consulta, resultado,
                                                      Jsonb(detalle) if detalle else None, url))


class TopeAlcanzado(Exception):
    pass


# ─────────────────────────────────────────────────────────────
# Cascada por empresa
# ─────────────────────────────────────────────────────────────

def similitud(conn, a: str | None, b: str | None) -> float:
    na, nb = razon_normalizada(a), razon_normalizada(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return float(catalogos.similitudes(conn, [na], [nb]).get((na, nb), 0.0))


def _mismo_departamento(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return True
    return razon_normalizada(a) == razon_normalizada(b)


def elegir_lugar(conn, lugares, emp: dict, umbral: float) -> tuple[object | None, list[dict]]:
    """El lugar aceptable de mayor similitud (nombre ≥ umbral y mismo departamento) y los demás aceptables."""
    aceptables = []
    for l in lugares:
        s = max(similitud(conn, l.nombre, emp["razon_social"]), similitud(conn, l.nombre, emp.get("fantasia")))
        if s >= umbral and _mismo_departamento(l.departamento, emp.get("departamento")) and not l.cerrado:
            aceptables.append((s, l))
    aceptables.sort(key=lambda x: -x[0])
    if not aceptables:
        return None, []
    return aceptables[0][1], [{"nombre": l.nombre, "similitud": round(s, 3), "place_id": l.place_id} for s, l in aceptables[1:]]


class Corrida:
    """Estado de una corrida en ejecución."""

    def __init__(self, c: dict, cfg: dict, estado: dict, actor: str):
        self.id, self.cfg, self.actor = c["id"], cfg, actor
        self.tope = float((c["estimacion"] or {}).get("permitido", cfg["tope_corrida"]))
        self.usable = {p: _usable(estado, p) for p in PROVEEDORES}
        self.avisos: list[str] = []

    def apagar(self, p: str, motivo: str):
        if self.usable.get(p):
            self.usable[p] = False
            self.avisos.append(f"{NOMBRES[p]}: {motivo}. Se salteó en el resto de la corrida.")

    def pagar(self, empresa_id, proveedor, costo_max, consulta=None):
        r = reservar(self.id, empresa_id, proveedor, costo_max, self.tope, self.cfg, consulta)
        if r is None:
            raise TopeAlcanzado()
        return r


def procesar_empresa(run: Corrida, eid: int) -> dict:
    """Corre la cascada para una empresa y aplica lo encontrado. Lanza TopeAlcanzado si no entra la llamada siguiente
    (lo encontrado antes en esta empresa se aplica igual)."""
    cfg = run.cfg
    with conexion() as conn:
        emp = conn.execute(_EMPRESAS_SQL, {"ids": [eid], "dias": 0}).fetchone()
    salida = {"empresa_id": eid, "codigo": emp["codigo"] if emp else None,
              "razon_social": emp["razon_social"] if emp else None, "telefonos_nuevos": 0}
    if emp is None or emp["baja"]:
        return {**salida, "resultado": "baja"}
    tel = emp["tiene_telefono"]
    web = emp["web"]
    hallado = {"telefonos": [], "web": None, "direccion": None, "email": None, "place_id": None, "estudio": False,
               "url": None}
    nombre = emp["fantasia"] or emp["razon_social"] or ""
    tope = None

    def falta_tel():
        return not (tel or hallado["telefonos"])

    def falta_web():
        return cfg["corte"] == "telefono_y_web" and not (web or hallado["web"])

    try:
        # 1. Fuentes propias: si ya tiene un teléfono discable, no se gasta (salvo que falte el sitio con «teléfono y sitio»)
        if not falta_tel() and not falta_web():
            return {**salida, "resultado": "ya_tenia"}
        # 2. Google Places Text Search
        if run.usable["google_places"] and not emp["place_id"] and (falta_tel() or falta_web()):
            consulta = ", ".join(x for x in (nombre, emp["localidad"] or emp["departamento"], "Uruguay") if x)
            pid, costo = run.pagar(eid, "google_places", cfg["precio_places"], consulta)
            try:
                lugares, _ = proveedores.places_buscar(consulta)
            except proveedores.ProveedorError as e:
                cerrar_paso(pid, costo if e.cobrada else 0, "error", {"error": str(e)})
                if e.clave_invalida:
                    run.apagar("google_places", str(e))
            else:
                with conexion() as conn:
                    lugar, otros = elegir_lugar(conn, lugares, emp, cfg["similitud_places"])
                det = {"resultados": len(lugares), "telefono": bool(lugar and lugar.telefono), "otros": otros}
                if lugar:
                    det.update({"nombre": lugar.nombre, "web": bool(lugar.web)})
                    hallado["place_id"] = lugar.place_id
                    n = proveedores.telmod.normalizar(lugar.telefono) if lugar.telefono else None
                    if n and n.discable:
                        hallado["telefonos"].append((n.e164, "google_places", {"place_id": lugar.place_id}))
                    hallado["web"] = hallado["web"] or lugar.web
                    hallado["direccion"] = lugar.direccion
                cerrar_paso(pid, costo, "ok" if lugar else "sin_resultado", det, lugar.place_id if lugar else None)
        # 3. Búsqueda web (Brave): solo si falta teléfono o sitio, y no hay sitio
        sitio = hallado["web"] or web
        if run.usable["brave"] and not sitio and (falta_tel() or falta_web()):
            consulta = " ".join(x for x in (emp["razon_social"] or nombre, "Uruguay", emp["localidad"] or "") if x).strip()
            pid, costo = run.pagar(eid, "brave", cfg["precio_brave"], consulta)
            try:
                resultados = proveedores.brave_buscar(consulta)
            except proveedores.ProveedorError as e:
                cerrar_paso(pid, costo if e.cobrada else 0, "error", {"error": str(e)})
                if e.clave_invalida:
                    run.apagar("brave", str(e))
            else:
                sitio = proveedores.sitio_oficial(resultados, emp["razon_social"] or nombre, cfg["directorios"])
                cerrar_paso(pid, costo, "ok" if sitio else "sin_resultado",
                            {"resultados": len(resultados), "sitio": sitio}, url=sitio)
                if sitio:
                    hallado["web"] = sitio
        # 4. Sitio + Claude: solo si todavía falta teléfono
        if run.usable["claude"] and sitio and falta_tel():
            try:
                texto, leidas = proveedores.leer_sitio(sitio)
            except proveedores.ProveedorError as e:
                paso_gratis(run.id, eid, "sitio", "error", {"error": str(e)}, url=sitio)
                texto = None
            if texto:
                paso_gratis(run.id, eid, "sitio", "ok", {"paginas": len(leidas), "caracteres": len(texto)}, url=leidas[0])
                reserva = costo_claude(cfg, cfg["tokens_entrada_estimados"] + 1000, 2000)
                pid, _ = run.pagar(eid, "claude", reserva, sitio)
                try:
                    ext = proveedores.claude_extraer(texto, emp["razon_social"] or nombre, cfg["modelo_claude"])
                except proveedores.ProveedorError as e:
                    cerrar_paso(pid, 0, "error", {"error": str(e)})
                    if e.clave_invalida:
                        run.apagar("claude", str(e))
                else:
                    costo = costo_claude(cfg, ext.tokens_entrada, ext.tokens_salida)
                    confiable = ext.confianza >= 0.5
                    # Solo lo institucional y validado: nunca nombres ni datos personales en el registro
                    cerrar_paso(pid, costo, "ok" if confiable and (ext.telefonos or ext.emails) else "sin_resultado",
                                {"telefono": bool(ext.telefonos) and confiable, "telefonos": len(ext.telefonos),
                                 "emails": len(ext.emails), "estudio": ext.estudio, "confianza": ext.confianza,
                                 "tokens_entrada": ext.tokens_entrada, "tokens_salida": ext.tokens_salida,
                                 "datos_personales_descartados": ext.descartados}, url=sitio)
                    if confiable:
                        hallado["url"] = sitio
                        hallado["telefonos"] += [(t, "web", {"url": sitio}) for t in ext.telefonos]
                        hallado["email"] = ext.emails[0] if ext.emails else None
                        hallado["direccion"] = hallado["direccion"] or ext.direccion
                        hallado["estudio"] = ext.estudio
    except TopeAlcanzado:
        tope = True
    salida.update(aplicar(run, emp, hallado))
    salida["resultado"] = "con_telefono" if salida["telefonos_nuevos"] else "tope" if tope else "sin_resultado"
    if tope:
        salida["_tope"] = True
    return salida


def aplicar(run: Corrida, emp: dict, h: dict) -> dict:
    """Guarda lo encontrado: vínculos «sin verificar» con su origen, historia con fuente enriquecimiento y señales."""
    cfg, eid, cid, actor = run.cfg, emp["id"], run.id, run.actor
    out = {"telefonos_nuevos": 0, "web": False, "direccion": False, "email": False, "estudio": h["estudio"]}
    with conexion() as conn:
        tel_ids = []
        for e164, origen, evid in h["telefonos"]:
            t, n, _ = empresas.telefono(conn, e164)
            if t is None:
                continue
            _, nuevo = empresas.vincular(conn, t["id"], eid, "enriquecimiento", cid, actor, origen=origen,
                                         detalle={"corrida": cid, **evid})
            out["telefonos_nuevos"] += int(nuevo)
            tel_ids.append(t["id"])
            if h["estudio"] and origen == "web" and t["intermediario"] is None:
                conn.execute("UPDATE telefono SET intermediario = 'sospechoso', intermediario_motivo = %s,"
                             " intermediario_fecha = now(), intermediario_por = %s WHERE id = %s",
                             (MOTIVO_ESTUDIO, f"enriquecimiento:{cid}", t["id"]))
        valores = {}
        if h["web"] and h["web"] != emp["web"]:
            valores["web"] = h["web"]
        if h["direccion"]:
            valores["direccion"] = h["direccion"]
        if valores:
            cambios, _ = empresas.aplicar_valores(conn, eid, valores, "enriquecimiento", cid, cfg["confianza"], actor,
                                                  {"corrida": cid, "place_id": h["place_id"], "url": h["url"]})
            out["web"] = "web" in cambios
            out["direccion"] = "direccion" in cambios
        attrs = {}
        if h["place_id"]:
            attrs["google_place_id"] = {"valor": h["place_id"]}
        if h["email"]:
            attrs["email_institucional"] = {"valor": h["email"]}
        if attrs:
            cambios, _ = empresas.aplicar_atributos(conn, eid, attrs, "enriquecimiento", cid, cfg["confianza"], actor)
            out["email"] = "atributo.email_institucional" in cambios
        if tel_ids:
            umbral = int(config.vigente(conn)[1]["umbral_intermediario"])
            intermediarios.detectar(conn, umbral, tel_ids, actor)
    return out


@tareas.handler("enriquecimiento")
def _tarea_enriquecer(conn, payload, tarea_id):
    cid = payload["corrida_id"]
    c = conn.execute("SELECT * FROM enriquecimiento_corrida WHERE id = %s", (cid,)).fetchone()
    if c is None or c["estado"] != "en_curso":
        return {"omitida": True}
    cfg, _ = cfg_vigente(conn)
    run = Corrida(c, cfg, estado_proveedores(conn, cfg), c["aprobada_por"] or c["creado_por"])
    ids = list(c["empresa_ids"])
    resultados, estado = [], "terminada"
    try:
        for i, eid in enumerate(ids):
            tareas.progreso(tarea_id, i, len(ids))   # lanza Cancelada si se canceló
            r = procesar_empresa(run, eid)
            resultados.append(r)
            if r.pop("_tope", False):
                estado = "detenida_tope"
                break
        tareas.progreso(tarea_id, len(resultados), len(ids))
    except tareas.Cancelada:
        _cerrar(cid, "cancelada", resultados, run, len(ids))
        raise
    except Exception as e:
        _cerrar(cid, "error", resultados, run, len(ids), str(getattr(e, "detail", e)))
        raise
    return _cerrar(cid, estado, resultados, run, len(ids))


def _cerrar(cid, estado, resultados, run, total, error=None) -> dict:
    with conexion() as conn:
        gasto = conn.execute("SELECT coalesce(sum(costo), 0) AS g FROM enriquecimiento_paso WHERE corrida_id = %s",
                             (cid,)).fetchone()["g"]
        por = {NOMBRES[r["proveedor"]]: float(r["g"]) for r in conn.execute(
            "SELECT proveedor, sum(costo) AS g FROM enriquecimiento_paso WHERE corrida_id = %s GROUP BY proveedor", (cid,))}
        res = {"procesadas": len(resultados), "total": total,
               "con_telefono_nuevo": sum(1 for r in resultados if r.get("telefonos_nuevos")),
               "telefonos_nuevos": sum(r.get("telefonos_nuevos", 0) for r in resultados),
               "sin_resultado": sum(1 for r in resultados if r["resultado"] == "sin_resultado"),
               "con_web": sum(1 for r in resultados if r.get("web")),
               "con_email": sum(1 for r in resultados if r.get("email")),
               "estudios": sum(1 for r in resultados if r.get("estudio")),
               "gasto_por_proveedor": {k: round(v, 4) for k, v in por.items()}, "avisos": run.avisos,
               "empresas": resultados}
        base = sum(1 for r in resultados if r["resultado"] in ("con_telefono", "sin_resultado"))
        res["tasa_telefono"] = round(100.0 * res["con_telefono_nuevo"] / base, 1) if base else None
        # Una corrida ya marcada «cancelada» (botón Cancelar) no vuelve a «terminada»
        conn.execute("UPDATE enriquecimiento_corrida SET estado = CASE WHEN estado = 'cancelada' THEN 'cancelada' ELSE %s END,"
                     " gasto = %s, resultado = %s, terminada = now(), error = %s WHERE id = %s",
                     (estado, gasto, Jsonb(res), error, cid))
        auditoria.registrar(conn, "tarea:enriquecimiento", "enriquecimiento.terminar", "enriquecimiento_corrida", cid,
                            {"estado": estado, "gasto": float(gasto), "con_telefono_nuevo": res["con_telefono_nuevo"],
                             "procesadas": res["procesadas"]})
        mantenimiento.al_terminar(f"enriquecimiento #{cid}", mantenimiento.ENRIQUECIMIENTO)
    return {k: v for k, v in res.items() if k != "empresas"}


# ─────────────────────────────────────────────────────────────
# Deshacer, listar y detalle
# ─────────────────────────────────────────────────────────────

def deshacer(conn, corrida_id: int, actor: str) -> dict:
    c = conn.execute("SELECT * FROM enriquecimiento_corrida WHERE id = %s AND tipo = 'enriquecimiento' FOR NO KEY UPDATE",
                     (corrida_id,)).fetchone()
    if c is None:
        raise HTTPException(404, "Corrida inexistente")
    if c["estado"] not in TERMINADAS:
        raise HTTPException(409, "Solo se deshace una corrida terminada, detenida, cancelada o con error")
    # Primero se marca deshecha: así el recálculo ya no cuenta su historia (empresas._CANDIDATOS_SQL)
    conn.execute("UPDATE enriquecimiento_corrida SET estado = 'deshecha', deshecha = now(), deshecha_por = %s WHERE id = %s",
                 (actor, corrida_id))
    r = quitar_datos(conn, corrida_id, "enriquecimiento", actor)
    auditoria.registrar(conn, actor, "enriquecimiento.deshacer", "enriquecimiento_corrida", corrida_id, r)
    mantenimiento.al_terminar(f"enriquecimiento #{corrida_id} deshecho", mantenimiento.ENRIQUECIMIENTO)
    return r


def quitar_datos(conn, corrida_id: int, fuente: str, actor: str) -> dict:
    """Quita los vínculos y valores que trajo una corrida o un lote, salvo los teléfonos que la sala ya verificó."""
    ids = [r["empresa_id"] for r in conn.execute(
        "SELECT DISTINCT empresa_id FROM empresa_campo_historia WHERE fuente_tipo = %s AND fuente_id = %s"
        " UNION SELECT DISTINCT empresa_id FROM telefono_vinculo WHERE fuente_tipo = %s AND fuente_id = %s"
        " UNION SELECT DISTINCT v.empresa_id FROM telefono_vinculo_origen x JOIN telefono_vinculo v ON v.id = x.vinculo_id"
        "  WHERE x.fuente_tipo = %s AND x.fuente_id = %s", (fuente, corrida_id) * 3)]
    conservados = conn.execute("SELECT count(*) AS n FROM telefono_vinculo WHERE fuente_tipo = %s AND fuente_id = %s"
                               " AND estado = 'verificado'", (fuente, corrida_id)).fetchone()["n"]
    # El origen que sumó a vínculos que siguen (salvo los verificados, que conservan su evidencia)
    conn.execute("DELETE FROM telefono_vinculo_origen x USING telefono_vinculo v WHERE v.id = x.vinculo_id"
                 " AND x.fuente_tipo = %s AND x.fuente_id = %s AND v.estado <> 'verificado'", (fuente, corrida_id))
    vincs = conn.execute("DELETE FROM telefono_vinculo WHERE fuente_tipo = %s AND fuente_id = %s AND estado <> 'verificado'"
                         " RETURNING id, telefono_id", (fuente, corrida_id)).fetchall()
    # Señal de estudio contable/jurídico que marcó esta corrida (si nadie la resolvió)
    marcados = [r["id"] for r in conn.execute(
        "UPDATE telefono SET intermediario = NULL, intermediario_motivo = NULL, intermediario_fecha = NULL,"
        " intermediario_por = NULL WHERE intermediario = 'sospechoso' AND intermediario_por = %s RETURNING id",
        (f"enriquecimiento:{corrida_id}",))]
    for eid in ids:
        empresas.recalcular(conn, eid)   # la historia de la corrida deshecha deja de contar (empresas._CANDIDATOS_SQL)
    intermediarios.reevaluar(conn, [v["telefono_id"] for v in vincs] + marcados, actor)
    return {"empresas": len(ids), "vinculos_quitados": len(vincs), "verificados_conservados": conservados}


def listar(conn, tipo: str = "enriquecimiento", muestra_id: int | None = None, limite: int = 100) -> list[dict]:
    return conn.execute(
        "SELECT c.id, c.tipo, c.origen, c.muestra_id, m.nombre AS muestra, c.estado, c.creado_por, c.creado, c.aprobada,"
        " c.terminada, c.gasto, cardinality(c.empresa_ids) AS empresas, c.estimacion->>'maximo' AS costo_maximo,"
        " c.resultado->'con_telefono_nuevo' AS con_telefono_nuevo, c.resultado->'tasa_telefono' AS tasa_telefono,"
        " c.filtros, t.progreso, t.total"
        " FROM enriquecimiento_corrida c LEFT JOIN muestra m ON m.id = c.muestra_id LEFT JOIN tarea t ON t.id = c.tarea_id"
        " WHERE c.tipo = %s AND c.estado <> 'descartada' AND (%s::int IS NULL OR c.muestra_id = %s)"
        " ORDER BY c.id DESC LIMIT %s", (tipo, muestra_id, muestra_id, limite)).fetchall()


def detalle(conn, corrida_id: int) -> dict:
    c = conn.execute("SELECT c.*, m.nombre AS muestra, t.progreso, t.total, t.estado AS tarea_estado"
                     " FROM enriquecimiento_corrida c LEFT JOIN muestra m ON m.id = c.muestra_id"
                     " LEFT JOIN tarea t ON t.id = c.tarea_id WHERE c.id = %s", (corrida_id,)).fetchone()
    if c is None:
        raise HTTPException(404, "Corrida inexistente")
    c = dict(c)
    c["n_empresas"] = len(c.pop("empresa_ids") or [])
    c["pasos"] = conn.execute(
        "SELECT proveedor, resultado, count(*) AS n, sum(costo) AS costo FROM enriquecimiento_paso WHERE corrida_id = %s"
        " GROUP BY proveedor, resultado ORDER BY proveedor, resultado", (corrida_id,)).fetchall()
    return c


def pasos_empresa(conn, empresa_id: int) -> list[dict]:
    return conn.execute(
        "SELECT p.corrida_id, c.tipo, c.estado AS estado_corrida, p.proveedor, p.resultado, p.costo, p.fecha, p.url,"
        " p.place_id FROM enriquecimiento_paso p JOIN enriquecimiento_corrida c ON c.id = p.corrida_id"
        " WHERE p.empresa_id = %s ORDER BY p.id DESC LIMIT 50", (empresa_id,)).fetchall()
