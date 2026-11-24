"""Valores de los filtros y contadores precalculados (SPEC_rendimiento_base_grande, P-4, D55).

resumen_base guarda tres resúmenes que antes se calculaban en cada visita recorriendo la base entera:
- «valores»: departamento, tamaño, CIIU a 2 dígitos y localidad distintos, con su cantidad de empresas;
- «inicio»: los contadores de Inicio que cuestan (empresas, disponibles, teléfonos, intermediarios, provisorias);
- «naturalezas»: el uso de cada naturaleza jurídica (empresas activas, todas, y filas de historia).

Cada sentencia que cambia algo que estos resúmenes cuentan avanza resumen_cambios_seq (triggers de 0020). Un resumen
calculado con un valor anterior quedó viejo: en una base chica se recalcula en el momento; en una grande se muestra
el que hay, con su fecha, y se encola el recálculo (también corre al terminar cada operación grande, en el job cada
10 minutos si hubo cambios, en el job diario y con el botón «Recalcular»).
"""
import logging
import time

from psycopg.types.json import Jsonb

from . import disponibilidad, intermediarios, provisorias

log = logging.getLogger(__name__)

CLAVES = ("valores", "inicio", "naturalezas")


def version_actual(conn, clave: str = "valores") -> int:
    """Contador de cambios que importa a ese resumen. Inicio suma los de la disponibilidad guardada (los dos crecen)."""
    v = _seq(conn, "resumen_cambios_seq")
    return v + _seq(conn, "disponibilidad_cambios_seq") if clave == "inicio" else v


def _seq(conn, nombre: str) -> int:
    r = conn.execute(f"SELECT last_value, is_called FROM {nombre}").fetchone()
    return r["last_value"] if r["is_called"] else 0


def calcular_valores(conn) -> dict:
    """Una sola recorrida de la tabla para los cuatro campos (GROUPING SETS), ordenados como antes."""
    filas = conn.execute(
        """
        SELECT campo, valor, n FROM (
          SELECT CASE WHEN GROUPING(departamento) = 0 THEN 'departamento' WHEN GROUPING(tamano) = 0 THEN 'tamano'
                      WHEN GROUPING(left(ciiu, 2)) = 0 THEN 'ciiu2' ELSE 'localidad' END AS campo,
                 coalesce(departamento, tamano, left(ciiu, 2), localidad) AS valor, count(*) AS n
          FROM empresa WHERE baja IS NULL
          GROUP BY GROUPING SETS ((departamento), (tamano), (left(ciiu, 2)), (localidad))
        ) x WHERE valor IS NOT NULL ORDER BY campo, valor
        """).fetchall()
    r = {"departamento": [], "tamano": [], "ciiu2": [], "localidad": []}
    for f in filas:
        r[f["campo"]].append({"valor": f["valor"], "n": f["n"]})
    return r


def calcular_inicio(conn) -> dict:
    r = conn.execute(
        """
        SELECT (SELECT count(*) FROM empresa WHERE baja IS NULL AND base = 'definitiva') AS empresas,
               (SELECT count(*) FROM empresa WHERE baja IS NULL AND base = 'provisoria') AS provisorias,
               (SELECT count(*) FROM telefono WHERE e164 IS NOT NULL) AS telefonos,
               (""" + intermediarios.SQL_CONTADOR + """) AS sospechosos,
               (SELECT count(*) FROM telefono WHERE intermediario = 'confirmado') AS intermediarios
        """).fetchone()
    if disponibilidad.lista(conn):
        r.update(conn.execute(
            "SELECT count(*) FILTER (WHERE disponible) AS disponibles,"
            " count(*) FILTER (WHERE telefonos_discables > 0) AS con_telefono_discable FROM empresa_disponibilidad"
        ).fetchone())
    else:  # la disponibilidad se está calculando: no se recorre la base entera para contar
        r.update({"disponibles": None, "con_telefono_discable": None})
    r["provisorias_con_candidatas"] = provisorias.contar_con_candidatas(conn) if r["provisorias"] else 0
    return r


def calcular_naturalezas(conn) -> dict:
    por_id = {str(f["naturaleza_id"]): {"empresas": f["activas"], "empresas_todas": f["todas"]} for f in conn.execute(
        "SELECT naturaleza_id, count(*) FILTER (WHERE baja IS NULL) AS activas, count(*) AS todas FROM empresa"
        " WHERE naturaleza_id IS NOT NULL GROUP BY naturaleza_id")}
    historia = {f["valor"]: f["n"] for f in conn.execute(
        "SELECT valor, count(*) AS n FROM empresa_campo_historia WHERE campo = 'naturaleza' AND valor IS NOT NULL"
        " GROUP BY valor")}
    return {"por_id": por_id, "historia": historia}


_CALCULOS = {"valores": calcular_valores, "inicio": calcular_inicio, "naturalezas": calcular_naturalezas}


def recalcular(conn, claves=CLAVES) -> dict:
    """Recalcula y guarda. La versión se toma antes de calcular: un cambio que llega mientras tanto lo deja viejo."""
    versiones = {c: version_actual(conn, c) for c in claves}
    hechos = {}
    for clave in claves:
        version = versiones[clave]
        t0 = time.monotonic()
        valor = _CALCULOS[clave](conn)
        seg = round(time.monotonic() - t0, 2)
        hechos[clave] = conn.execute(
            "INSERT INTO resumen_base (clave, valor, version, actualizado, segundos) VALUES (%s, %s, %s, now(), %s)"
            " ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, version = EXCLUDED.version,"
            " actualizado = EXCLUDED.actualizado, segundos = EXCLUDED.segundos RETURNING *",
            (clave, Jsonb(valor), version, seg)).fetchone()
        if seg > 1:
            log.info("Resumen %s recalculado en %s s", clave, seg)
    return hechos


def viejos(conn) -> list[str]:
    """Los resúmenes que faltan o quedaron viejos."""
    hay = {r["clave"]: r["version"] for r in conn.execute("SELECT clave, version FROM resumen_base")}
    return [c for c in CLAVES if hay.get(c) is None or hay[c] < version_actual(conn, c)]


def leer(conn, clave: str) -> dict:
    """{valor, actualizado, al_dia}. Viejo: en una base chica se recalcula ya; en una grande se devuelve el guardado y se
    encola el recálculo (si no hay ninguno guardado, se calcula ahora, una sola vez)."""
    from . import mantenimiento

    r = conn.execute("SELECT * FROM resumen_base WHERE clave = %s", (clave,)).fetchone()
    if r is not None and r["version"] >= version_actual(conn, clave):
        return {"valor": r["valor"], "actualizado": r["actualizado"], "al_dia": True}
    if r is None or disponibilidad.base_chica(conn):
        if clave == "inicio":
            disponibilidad.asegurar(conn)
        r = recalcular(conn, (clave,))[clave]
        return {"valor": r["valor"], "actualizado": r["actualizado"], "al_dia": True}
    mantenimiento.encolar("resumen viejo")
    return {"valor": r["valor"], "actualizado": r["actualizado"], "al_dia": False}


def actualizado(conn) -> dict:
    """Fecha de cada resumen (la web la usa para saber si los valores que tiene guardados siguen sirviendo)."""
    return {r["clave"]: r["actualizado"] for r in conn.execute("SELECT clave, actualizado FROM resumen_base")}
