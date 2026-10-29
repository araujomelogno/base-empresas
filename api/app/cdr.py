"""Análisis del CDR por número destino (R1.8).

El job nocturno (servidor Ubuntu) lee las llamadas nuevas de la base MySQL de uContact y
las empuja a POST /intentos/lote. Acá se normaliza el destino, se descartan los destinos
internos y se cruza contra los teléfonos de la base. Lo que no cruza se cuenta pero no se
guarda. Re-procesar un día no duplica intentos (idempotente por ID de llamada).
"""
import datetime as dt
from collections import Counter, defaultdict

from psycopg.types.json import Jsonb

from . import auditoria, config, telefonos as telmod
from .util import TZ


def franja(inicio: dt.datetime, franjas: list[dict]) -> str:
    local = inicio.astimezone(TZ)
    dia = local.isoweekday()
    hhmm = local.strftime("%H:%M")
    for f in franjas:
        # "23:59" como fin de franja incluye el último minuto del día
        if dia in f["dias"] and f["desde"] <= hhmm and (hhmm < f["hasta"] or f["hasta"] == "23:59"):
            return f["nombre"]
    return "fuera de franja"


def _fecha(v) -> dt.datetime:
    if isinstance(v, dt.datetime):
        d = v
    else:
        s = str(v).strip().replace("Z", "+00:00")
        d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def procesar_lote(conn, llamadas: list[dict], origen: str, actor: str) -> dict:
    _, cfg = config.vigente(conn)
    internos, prefijos, franjas = cfg["destinos_internos"], cfg.get("prefijos_salida") or [], cfg["franjas"]
    c = Counter()
    no_cruzan_tipo = Counter()
    candidatas = []
    for ll in llamadas:
        c["recibidas"] += 1
        destino = str(ll.get("destino") or "").strip()
        if not destino or telmod.es_interno(destino, internos):
            c["internas"] += 1
            continue
        n = telmod.normalizar(destino, prefijos)
        if not n.e164:
            c["no_normalizables"] += 1
            no_cruzan_tipo[n.tipo] += 1
            continue
        candidatas.append((ll, n))

    e164s = sorted({n.e164 for _, n in candidatas})
    tels = {r["e164"]: r for r in conn.execute(
        "SELECT t.id, t.e164, coalesce(array_agg(v.empresa_id) FILTER (WHERE v.empresa_id IS NOT NULL), '{}') AS empresas"
        " FROM telefono t LEFT JOIN telefono_vinculo v ON v.telefono_id = t.id"
        " LEFT JOIN empresa e ON e.id = v.empresa_id AND e.baja IS NULL"
        " WHERE t.e164 = ANY(%s) GROUP BY t.id", (e164s,))}
    empresa_ids = sorted({e for t in tels.values() for e in t["empresas"]})
    # Ítems de muestras activas para esas empresas, con la ventana de campo del estudio
    items = defaultdict(list)
    for r in conn.execute(
            "SELECT i.id, i.empresa_id, s.campo_desde, s.campo_hasta, m.id AS muestra_id FROM muestra_item i"
            " JOIN muestra m ON m.id = i.muestra_id AND m.estado = 'activa' JOIN estudio s ON s.id = m.estudio_id"
            " WHERE i.empresa_id = ANY(%s)", (empresa_ids,)):
        items[r["empresa_id"]].append(r)

    lote_id = conn.execute("INSERT INTO cdr_lote (origen, conteos) VALUES (%s, '{}'::jsonb) RETURNING id",
                           (origen,)).fetchone()["id"]
    para_conciliar = []
    filas = []
    for ll, n in candidatas:
        t = tels.get(n.e164)
        if t is None:
            c["no_cruzan"] += 1
            no_cruzan_tipo[n.tipo] += 1
            continue
        inicio = _fecha(ll["inicio"])
        fecha_local = inicio.astimezone(TZ).date()
        posibles = {it["id"] for eid in t["empresas"] for it in items.get(eid, [])
                    if it["campo_desde"] <= fecha_local <= it["campo_hasta"]}
        item_id = next(iter(posibles)) if len(posibles) == 1 else None
        uf = str(ll.get("userfield") or "")
        disp, disp_enc = (uf.split("|", 1) + [""])[:2] if uf else (ll.get("disposicion"), None)
        filas.append((str(ll["cdr_id"]), lote_id, t["id"], list(t["empresas"]), item_id, ll.get("encuestador") or None,
                      inicio, franja(inicio, franjas), ll.get("duracion"), disp or ll.get("disposicion") or None,
                      disp_enc or None, ll.get("campania") or None, ll.get("destino")))
        if len(posibles) > 1:
            para_conciliar.append((str(ll["cdr_id"]), sorted(posibles)))

    nuevos = 0
    with conn.cursor() as cur:
        for f in filas:
            cur.execute(
                "INSERT INTO intento (cdr_id, lote_id, telefono_id, empresas, item_id, encuestador, inicio, franja, duracion,"
                " disposicion, disposicion_encuesta, campania, destino_crudo)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (cdr_id) DO NOTHING RETURNING id",
                f)
            if cur.fetchone():
                nuevos += 1
                c["asociados_a_item"] += 1 if f[4] else 0
            else:
                c["duplicados"] += 1
    for cdr_id, posibles in para_conciliar:
        intento = conn.execute("SELECT id FROM intento WHERE cdr_id = %s AND item_id IS NULL", (cdr_id,)).fetchone()
        if intento:
            conn.execute(
                "INSERT INTO conciliacion (tipo, objeto_id, motivo, candidatos) VALUES ('intento', %s, %s, %s)"
                " ON CONFLICT (tipo, objeto_id) DO NOTHING",
                (intento["id"], "El teléfono está en más de una muestra activa", Jsonb({"items": posibles})))
            c["a_conciliacion"] += 1
    c["intentos_nuevos"] = nuevos
    conteos = dict(c)
    conteos["no_cruzan_por_tipo"] = dict(no_cruzan_tipo)
    conn.execute("UPDATE cdr_lote SET conteos = %s WHERE id = %s", (Jsonb(conteos), lote_id))
    auditoria.registrar(conn, actor, "cdr.lote", "cdr_lote", lote_id, conteos)
    return {"lote_id": lote_id, **conteos}
