"""Disponibilidad guardada (SPEC_rendimiento_base_grande, P-2, D55).

empresa_disponibilidad guarda, para cada empresa, el resultado de bloqueos(cfg) con la configuración vigente: si está
disponible, qué reglas la bloquean, hasta cuándo, y cuántos teléfonos discables tiene. El buscador, Inicio y el armado
de muestras la leen en lugar de calcular la disponibilidad de toda la base en cada pedido.

Cómo se mantiene:
- Triggers por sentencia (migración 0020) anotan en disponibilidad_pendiente las empresas que una operación tocó:
  empresas, vínculos, teléfonos, «no llamar», muestras y naturalezas. Así ninguna operación puede olvidarse de avisar.
- procesar() recalcula las anotadas con disponibilidad_calcular(cfg, ids), que aplica las mismas reglas que
  bloqueos(cfg) solo a esas empresas. Lo hace el mantenimiento al terminar cada operación grande, el job cada 10
  minutos y, si son pocas (hasta INLINE), el mismo pedido que va a leer.
- Un cambio de configuración que afecta pocas empresas (una naturaleza excluida, los meses de enfriamiento, la regla
  de muestra activa) las anota; uno que afecta a toda la base (la regla «sin teléfono discable») pide el recálculo
  completo, que corre en segundo plano con progreso. Mientras tanto la tabla «no está lista» y se usa el cálculo
  anterior (la vista v_empresa_disponible).
- El enfriamiento vence con el tiempo, sin que nada cambie: marcar_vencidos() anota las empresas cuyo «hasta» pasó.
"""
import logging

from psycopg.types.json import Jsonb

from . import config

log = logging.getLogger(__name__)

INLINE = 2000          # pendientes que un pedido recalcula en el momento (más, se encolan)
TANDA = 5000           # empresas por paso del recálculo en segundo plano
BASE_CHICA = 20000     # hasta esta cantidad de empresas, el recálculo completo se hace en el momento

_REGLAS_POR_DEFECTO = ("enfriamiento", "muestra_activa", "sin_telefono_discable")

_UPSERT = """
INSERT INTO empresa_disponibilidad AS d (empresa_id, disponible, reglas, hasta, telefonos_discables, actualizado)
SELECT empresa_id, disponible, reglas, hasta, telefonos_discables, now()
FROM disponibilidad_calcular(%s, %s) ORDER BY empresa_id
ON CONFLICT (empresa_id) DO UPDATE SET disponible = EXCLUDED.disponible, reglas = EXCLUDED.reglas,
  hasta = EXCLUDED.hasta, telefonos_discables = EXCLUDED.telefonos_discables, actualizado = EXCLUDED.actualizado
WHERE (d.disponible, d.reglas, d.hasta, d.telefonos_discables)
      IS DISTINCT FROM (EXCLUDED.disponible, EXCLUDED.reglas, EXCLUDED.hasta, EXCLUDED.telefonos_discables)
"""


def reglas(params: dict) -> dict:
    """La parte de la configuración que usa bloqueos(cfg): si cambia, cambia la disponibilidad."""
    rd = params.get("reglas_disponibilidad") or {}
    return {"meses_enfriamiento": params.get("meses_enfriamiento"),
            "reglas_disponibilidad": {k: bool(rd.get(k, True)) for k in _REGLAS_POR_DEFECTO},
            "naturalezas_excluidas": sorted(params.get("naturalezas_excluidas") or [])}


def calcular(conn, ids: list[int], params: dict | None = None) -> list[dict]:
    """La disponibilidad de esas empresas, calculada ahora (la ficha)."""
    params = params if params is not None else config.vigente(conn)[1]
    return conn.execute("SELECT * FROM disponibilidad_calcular(%s, %s) ORDER BY empresa_id", (Jsonb(params), ids)).fetchall()


def recalcular(conn, ids: list[int], params: dict) -> int:
    if not ids:
        return 0
    return conn.execute(_UPSERT, (Jsonb(params), sorted(set(ids)))).rowcount


def control(conn) -> dict:
    return conn.execute("SELECT * FROM disponibilidad_control WHERE id = 1").fetchone() or {}


def lista(conn, params: dict | None = None) -> bool:
    """La tabla está calculada entera con las reglas vigentes (puede tener pendientes: se recalculan enseguida)."""
    params = params if params is not None else config.vigente(conn)[1]
    c = control(conn)
    return bool(c.get("completo") and c.get("cfg") == reglas(params))


def pendientes(conn, hasta: int | None = None) -> int:
    """Cuántas empresas esperan recalcularse (con «hasta», cuenta como mucho hasta+1: es barato)."""
    if hasta is None:
        return conn.execute("SELECT count(DISTINCT empresa_id) AS n FROM disponibilidad_pendiente").fetchone()["n"]
    return conn.execute("SELECT count(*) AS n FROM (SELECT 1 FROM disponibilidad_pendiente LIMIT %s) x",
                        (hasta + 1,)).fetchone()["n"]


def procesar(conn, params: dict, limite: int = TANDA) -> int:
    """Toma hasta «limite» marcas (las que otro proceso tiene tomadas las saltea) y recalcula esas empresas."""
    # ARRAY(…) se calcula una vez y el borrado va por la clave: con «id IN (subconsulta)» o un join, y las estadísticas
    # diciendo «tabla vacía» (se llenó durante la carga), Postgres recorría la tabla por cada fila tomada (medido: más
    # de 8 minutos con 100.000 marcas)
    ids = sorted({r["empresa_id"] for r in conn.execute(
        "DELETE FROM disponibilidad_pendiente WHERE id = ANY(ARRAY(SELECT id FROM disponibilidad_pendiente ORDER BY id"
        " LIMIT %s FOR UPDATE SKIP LOCKED)) RETURNING empresa_id", (limite,))})
    recalcular(conn, ids, params)
    return len(ids)


def marcar_vencidos(conn) -> int:
    """El enfriamiento que venció (su «hasta» ya pasó): esas empresas vuelven a calcularse."""
    return conn.execute(
        "INSERT INTO disponibilidad_pendiente (empresa_id) SELECT d.empresa_id FROM empresa_disponibilidad d"
        " WHERE d.hasta IS NOT NULL AND d.hasta <= now()"
        " AND NOT EXISTS (SELECT 1 FROM disponibilidad_pendiente p WHERE p.empresa_id = d.empresa_id)").rowcount


def base_chica(conn) -> bool:
    return conn.execute("SELECT count(*) AS n FROM (SELECT 1 FROM empresa LIMIT %s) x",
                        (BASE_CHICA,)).fetchone()["n"] < BASE_CHICA


def paso_completo(conn, params: dict, tanda: int = TANDA) -> tuple[bool, int, int] | None:
    """Un paso del recálculo completo, por id. Devuelve (terminado, hechas, total), o None si otro proceso lo está
    haciendo. Si la configuración cambió a mitad de camino, vuelve a empezar con la nueva."""
    if not conn.execute("SELECT pg_try_advisory_xact_lock(hashtext('disponibilidad_completa')) AS ok").fetchone()["ok"]:
        return None
    objetivo = reglas(params)
    c = conn.execute("SELECT * FROM disponibilidad_control WHERE id = 1 FOR UPDATE").fetchone()
    if c["cfg_en_curso"] != objetivo or c["ultimo_id"] is None:
        total = conn.execute("SELECT count(*) AS n FROM empresa").fetchone()["n"]
        c = conn.execute("UPDATE disponibilidad_control SET cfg_en_curso = %s, ultimo_id = 0, hechas = 0, total = %s,"
                         " iniciado = now(), terminado = NULL WHERE id = 1 RETURNING *", (Jsonb(objetivo), total)).fetchone()
        log.info("Disponibilidad: recálculo completo de %s empresas", total)
    ids = [r["id"] for r in conn.execute("SELECT id FROM empresa WHERE id > %s ORDER BY id LIMIT %s",
                                         (c["ultimo_id"], tanda))]
    if ids:
        recalcular(conn, ids, params)
        c = conn.execute("UPDATE disponibilidad_control SET ultimo_id = %s, hechas = hechas + %s,"
                         " total = greatest(total, hechas + %s) WHERE id = 1 RETURNING *",
                         (ids[-1], len(ids), len(ids))).fetchone()
        return False, c["hechas"], c["total"]
    c = conn.execute("UPDATE disponibilidad_control SET cfg = cfg_en_curso, completo = true, cfg_en_curso = NULL,"
                     " ultimo_id = NULL, terminado = now() WHERE id = 1 RETURNING *").fetchone()
    log.info("Disponibilidad: recálculo completo terminado (%s empresas)", c["hechas"])
    return True, c["hechas"], c["total"]


def completar_en_el_momento(conn, params: dict) -> bool:
    """Base chica: el recálculo completo entero, en la transacción del pedido."""
    while True:
        r = paso_completo(conn, params, BASE_CHICA)
        if r is None:
            return False
        if r[0]:
            return True


def asegurar(conn, params: dict | None = None) -> bool:
    """Antes de leer la tabla: la deja al día si es poco trabajo, y si no lo encola. Devuelve si se puede usar
    (False: hay que usar el cálculo anterior, porque la tabla todavía no está calculada con las reglas vigentes)."""
    from . import mantenimiento

    params = params if params is not None else config.vigente(conn)[1]
    if not lista(conn, params):
        if base_chica(conn):
            if not completar_en_el_momento(conn, params):
                return False
        else:
            mantenimiento.encolar("disponibilidad: recálculo completo")
            return False
    marcar_vencidos(conn)
    n = pendientes(conn, INLINE)
    if n and n <= INLINE:
        procesar(conn, params, INLINE)
    elif n:
        mantenimiento.encolar("disponibilidad: empresas a recalcular")
    return True


def config_cambiada(conn, antes: dict, despues: dict):
    """Al guardar la configuración. Si cambió una regla que afecta a pocas empresas, se anotan esas; si cambió la de
    «sin teléfono discable» (puede afectar a cualquiera), la tabla queda «no lista» hasta el recálculo completo."""
    a, d = reglas(antes), reglas(despues)
    if a == d:
        return
    c = conn.execute("SELECT * FROM disponibilidad_control WHERE id = 1 FOR UPDATE").fetchone()
    if not (c and c["completo"] and c["cfg"] == a):
        return  # no estaba lista: el recálculo completo ya va a usar la configuración nueva
    ra, rd = a["reglas_disponibilidad"], d["reglas_disponibilidad"]
    if ra["sin_telefono_discable"] != rd["sin_telefono_discable"]:
        log.info("Disponibilidad: cambió la regla «sin teléfono discable»; hace falta el recálculo completo")
        return
    x = conn.execute
    cambio = set(a["naturalezas_excluidas"]) ^ set(d["naturalezas_excluidas"])
    if cambio:
        x("INSERT INTO disponibilidad_pendiente (empresa_id) SELECT e.id FROM empresa e JOIN naturaleza_juridica n"
          " ON n.id = e.naturaleza_id WHERE n.codigo = ANY(%s)", (sorted(cambio),))
    if a["meses_enfriamiento"] != d["meses_enfriamiento"] or ra["enfriamiento"] != rd["enfriamiento"]:
        x("INSERT INTO disponibilidad_pendiente (empresa_id) SELECT id FROM empresa WHERE ultimo_contacto_efectivo IS NOT NULL")
    if ra["muestra_activa"] != rd["muestra_activa"]:
        x("INSERT INTO disponibilidad_pendiente (empresa_id) SELECT DISTINCT i.empresa_id FROM muestra_item i"
          " JOIN muestra m ON m.id = i.muestra_id WHERE m.estado = 'activa'")
    x("UPDATE disponibilidad_control SET cfg = %s WHERE id = 1", (Jsonb(d),))


def estado(conn) -> dict:
    """Para la web: si está lista, el recálculo completo en curso y las pendientes."""
    c = control(conn)
    params = config.vigente(conn)[1]
    return {"lista": bool(c.get("completo") and c.get("cfg") == reglas(params)),
            "recalculo": ({"hechas": c["hechas"], "total": c["total"], "iniciado": c["iniciado"]}
                          if c.get("cfg_en_curso") is not None else None),
            "pendientes": pendientes(conn, 10000), "terminado": c.get("terminado")}
