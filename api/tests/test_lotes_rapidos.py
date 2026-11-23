"""SPEC_lotes_rapidos (D53): el motor por tandas da exactamente la misma base que el algoritmo fila por fila, con
menos de 0,1 consultas por fila en el caso común, y deshacer y borrar recalculan por tandas."""
import os

import pytest

from conftest import cargar, reiniciar_base
from app import rut as rutmod


def _ruts(n: int) -> list[str]:
    out, i = [], 100000
    while len(out) < n:
        base = f"21{i:06d}001"
        dv = rutmod.digito_verificador(base)
        if dv is not None:
            out.append(base + str(dv))
        i += 1
    return out


RUTS = _ruts(26000)
NAT = ["SA", "Sociedad anónima", "SRL", "XYZ", ""]
ESTADO = ["Activa", "cerrada", "", "baja definitiva", "Activa"]
ORIGEN = ["GUIA", "Web propia", "", "Guía"]
EMPLEADOS = ["12", "muchos", "", "1.200", "7"]
EXPORTA = ["SI", "si", "No", "Talvez", "Capaz", ""]
DEPTO = ["Salto", "Montevideo", "", "Paysandú"]


def _fila(i: int, rut: str, base: bool = False) -> dict:
    tel = ["29%06d" % (i % 400), "099 123 456 / 2901 1234", "123", "abc", "", "4%07d" % (i % 900)][i % 6]
    return {
        "RUT": rut, "Razón social": f"Empresa {i % 700}" + (" SA" if i % 3 == 0 else ""),
        "Naturaleza": NAT[i % 5], "Estado": ESTADO[i % 5], "Web": "https://www.ejemplo%d.com.uy/" % (i % 50) if i % 2 else "",
        "Departamento": DEPTO[i % 4], "Teléfono": tel, "Celular": "09%07d" % (i % 300) if i % 4 == 0 else "",
        "Origen": ORIGEN[i % 4], "Empleados": EMPLEADOS[i % 5], "Exporta": EXPORTA[i % 6],
        "Dir sucursal": f"Calle {i % 7}" if i % 5 == 0 and not base else "",
        "Loc sucursal": "Centro" if i % 5 == 0 and not base else "",
        "Contacto": ["Ana Pérez", "", "Juan Gómez", ""][i % 4],
        "Cargo": ["Gerente", "", "", "Dueño"][i % 4],
        "Email contacto": ["ana@ejemplo.uy", "", "juan@x", ""][i % 4],
        "Tel contacto": "098%06d" % (i % 50) if i % 8 == 2 else "",
        "Antigüedad": str(i % 30) if i % 3 == 1 else "",
    }


MAPEO = {
    "rut": "RUT", "razon_social": "Razón social", "naturaleza": "Naturaleza", "estado": "Estado", "web": "Web",
    "departamento": "Departamento", "telefonos": ["Teléfono", "Celular"],
    "origenes_telefono": {"Teléfono": {"columna": "Origen"}, "Celular": {"fijo": "guia"}}, "origen_defecto": "sin_dato",
    "atributos": {"empleados": "Empleados", "exporta": "Exporta"},
    "sucursal_direccion": "Dir sucursal", "sucursal_localidad": "Loc sucursal",
    "contacto_nombre": "Contacto", "contacto_cargo": "Cargo", "contacto_email": "Email contacto",
    "contacto_telefono": "Tel contacto", "contacto_atributos": {"antiguedad": "Antigüedad"},
    "traducciones": {"origen": {"GUIA": "guia", "Web propia": "sin_dato"},
                     "atributo.exporta": {"Talvez": None, "Capaz": "No"}},
}


def _principal(n: int) -> list[dict]:
    filas = []
    for i in range(n):
        if i % 20 == 14:
            filas.append(dict(filas[i - 10]))            # la misma fila otra vez en la tanda: «sin cambios»
            continue
        if i % 50 == 7:
            rut = "123"                                  # RUT inválido: rechazo
        elif i % 40 == 3:
            rut = RUTS[i % 60]                           # empresa que ya existía (actualización, conflictos con la sala)
        elif i % 33 == 5:
            rut = RUTS[1000 + (i // 2) % 30]             # el mismo RUT varias veces, cerca y lejos
        elif i % 10 == 4:
            rut = RUTS[3000 + i // 20]                   # el mismo RUT dos veces en la misma tanda, con otros valores
        elif i % 71 == 9:
            rut = RUTS[200 + i % 3]                      # empresa anulada (se reactiva)
        elif i % 89 == 11:
            rut = RUTS[61]                               # empresa fusionada en otra
        else:
            rut = RUTS[5000 + i]                         # alta
        filas.append(_fila(i, rut))
    return filas


def _escenario(api, sql, n: int) -> dict:
    from app import empresas
    from app.db import conexion

    for datos in ({"clave": "empleados", "nombre": "Empleados", "tipo": "numero"},
                  {"clave": "exporta", "nombre": "Exporta", "tipo": "lista", "opciones": ["Sí", "No"]},
                  {"clave": "antiguedad", "nombre": "Antigüedad", "tipo": "numero", "ambito": "contacto"}):
        assert api.post("/atributos", json=datos).status_code == 200
    assert api.post("/origenes-telefono", json={"codigo": "guia", "nombre": "Guía"}).status_code == 200
    # Base: 62 empresas, con datos de la sala en algunas, una anulada (por una carga deshecha) y una fusionada
    cargar(api, [_fila(i, RUTS[i], base=True) for i in range(62)], tipo_fuente="t", mapeo=MAPEO)
    for i in range(10):
        eid = sql.execute("SELECT id FROM empresa WHERE rut = %s", (RUTS[i],)).fetchone()["id"]
        sql.execute("INSERT INTO empresa_campo_historia (empresa_id, campo, valor, fuente_tipo, confianza, actor)"
                    " VALUES (%s, 'estado', 'cerrada', 'sala', 10, 'encuestador'),"
                    " (%s, 'razon_social', 'Nombre de la sala', 'sav', 10, 'encuestador')", (eid, eid))
        with conexion() as conn:
            empresas.recalcular(conn, eid)
    b = cargar(api, [_fila(i, RUTS[200 + i], base=True) for i in range(3)], tipo_fuente="t", mapeo=MAPEO)
    assert api.delete(f"/cargas/{b['id']}", rol="steward").status_code == 200
    assert api.post(f"/empresas/{RUTS[60]}/fusionar", rol="steward",
                    json={"rut_absorbida": RUTS[61], "motivo": "misma"}).status_code == 200
    # La carga grande: preview y confirmación
    c = cargar(api, _principal(n), tipo_fuente="t", mapeo=MAPEO, confirmar=False, confianza=60)
    preview = c["conteos"]
    assert api.post(f"/cargas/{c['id']}/confirmar", rol="steward").status_code == 200
    # Una carga con regla de fusión por teléfono (la cascada va fila por fila)
    d = [_fila(i, RUTS[-40 + i]) for i in range(40)]      # RUTs que la carga grande no usa
    cargar(api, d, tipo_fuente="t2", mapeo=MAPEO, regla="telefono")
    return {"preview": _sin_variables(preview), **foto(sql)}


def _sin_variables(conteos: dict) -> dict:
    return {k: v for k, v in conteos.items() if k not in ("lotes",)}


def foto(sql) -> dict:
    """La base entera por claves naturales (sin ids ni fechas, que dependen del momento)."""
    def q(s):
        return [tuple(r.values()) for r in sql.execute(s).fetchall()]
    tel = "coalesce(t.e164, 'crudo:' || t.crudo)"
    return {
        "empresa": q("SELECT e.codigo, e.base, e.baja, f.codigo, e.razon_social, e.fantasia, n.codigo, e.ciiu, e.tamano,"
                     " e.departamento, e.localidad, e.direccion, e.web, e.estado, e.carga_alta_id FROM empresa e"
                     " LEFT JOIN empresa f ON f.id = e.fusionada_en LEFT JOIN naturaleza_juridica n ON n.id = e.naturaleza_id"
                     " ORDER BY 1"),
        "historia": q("SELECT e.codigo, h.campo, h.valor, h.fuente_tipo, h.fuente_id, h.confianza, h.actor, h.detalle::text"
                      " FROM empresa_campo_historia h JOIN empresa e ON e.id = h.empresa_id ORDER BY e.codigo, h.campo, h.id"),
        "atributo": q("SELECT e.codigo, a.clave, ea.valor_texto, ea.valor_numero, ea.valor_fecha, ea.valor_crudo,"
                      " ea.fuente_tipo, ea.fuente_id, ea.confianza FROM empresa_atributo ea JOIN empresa e ON e.id = ea.empresa_id"
                      " JOIN atributo a ON a.id = ea.atributo_id ORDER BY 1, 2"),
        "telefono": q("SELECT e164, crudo, tipo, estado, intermediario FROM telefono ORDER BY 1, 2"),
        "vinculo": q(f"SELECT {tel}, e.codigo, k.nombre, s.direccion, v.estado, v.fuente_tipo, v.fuente_id"
                     " FROM telefono_vinculo v JOIN telefono t ON t.id = v.telefono_id JOIN empresa e ON e.id = v.empresa_id"
                     " LEFT JOIN contacto k ON k.id = v.contacto_id LEFT JOIN sucursal s ON s.id = v.sucursal_id ORDER BY 1, 2"),
        "vinculo_historia": q(f"SELECT {tel}, e.codigo, h.estado, h.fuente_tipo, h.fuente_id, h.actor"
                              " FROM telefono_vinculo_historia h JOIN telefono t ON t.id = h.telefono_id"
                              " JOIN empresa e ON e.id = h.empresa_id ORDER BY 1, 2, 3, 4, 5"),
        "origen": q(f"SELECT {tel}, e.codigo, o.codigo, x.fuente_tipo, x.fuente_id FROM telefono_vinculo_origen x"
                    " JOIN telefono_vinculo v ON v.id = x.vinculo_id JOIN telefono t ON t.id = v.telefono_id"
                    " JOIN empresa e ON e.id = v.empresa_id JOIN origen_telefono o ON o.id = x.origen_id ORDER BY 1, 2, 3, 4, 5"),
        "sucursal": q("SELECT e.codigo, s.direccion, s.departamento, s.localidad, s.fuente_tipo, s.fuente_id FROM sucursal s"
                      " JOIN empresa e ON e.id = s.empresa_id ORDER BY 1, 2, 3, 4"),
        "contacto": q("SELECT e.codigo, k.nombre, k.cargo, k.area, k.email, k.fuente_tipo, k.fuente_id FROM contacto k"
                      " JOIN empresa e ON e.id = k.empresa_id ORDER BY 1, 2"),
        "contacto_historia": q("SELECT e.codigo, k.nombre, h.campo, h.valor, h.fuente_tipo, h.fuente_id FROM contacto_historia h"
                               " JOIN contacto k ON k.id = h.contacto_id JOIN empresa e ON e.id = k.empresa_id ORDER BY h.id"),
        "contacto_telefono": q(f"SELECT e.codigo, k.nombre, {tel}, ct.relacion, ct.fuente_tipo, ct.fuente_id"
                               " FROM contacto_telefono ct JOIN contacto k ON k.id = ct.contacto_id"
                               " JOIN empresa e ON e.id = k.empresa_id JOIN telefono t ON t.id = ct.telefono_id ORDER BY 1, 2, 3"),
        "contacto_atributo": q("SELECT e.codigo, k.nombre, a.clave, ca.valor_texto, ca.valor_numero, ca.crudo, ca.fuente_tipo"
                               " FROM contacto_atributo ca JOIN contacto k ON k.id = ca.contacto_id"
                               " JOIN empresa e ON e.id = k.empresa_id JOIN atributo a ON a.id = ca.atributo_id ORDER BY 1, 2, 3"),
        "rechazo": q("SELECT carga_id, fila, motivo FROM carga_rechazo ORDER BY 1, 2"),
        "revision": q("SELECT carga_id, fila, criterio, similitud FROM revision_fusion ORDER BY 1, 2"),
        "carga": q("SELECT id, estado, (conteos - 'lotes')::text FROM carga ORDER BY id"),
    }


def _comparar(a: dict, b: dict):
    for k in a:
        assert a[k] == b[k], f"«{k}» distinto: {len(a[k]) if isinstance(a[k], list) else ''} contra " \
                             f"{len(b[k]) if isinstance(b[k], list) else ''}; primera diferencia: " \
                             f"{next(((x, y) for x, y in zip(a[k], b[k]) if x != y), None) if isinstance(a[k], list) else ''}"


def _equivalencia(api, sql, monkeypatch, n: int):
    from app import settings

    monkeypatch.setattr(settings, "CARGAS_TAMANO_LOTE", 250)
    monkeypatch.setattr(settings, "CARGAS_TANDA", 100)
    monkeypatch.setattr(settings, "CARGAS_POR_FILA", True)
    por_fila = _escenario(api, sql, n)
    reiniciar_base()
    monkeypatch.setattr(settings, "CARGAS_POR_FILA", False)
    from app import cargas, cargas_tanda

    caminos = {"rapido": 0, "por_fila": 0}
    rapido, por_fila_fn = cargas_tanda._Tanda.aplicar, cargas.aplicar_una

    def contar_rapido(self, f):
        caminos["rapido"] += 1
        return rapido(self, f)

    def contar_por_fila(*a):
        caminos["por_fila"] += 1
        return por_fila_fn(*a)
    monkeypatch.setattr(cargas_tanda._Tanda, "aplicar", contar_rapido)
    monkeypatch.setattr(cargas, "aplicar_una", contar_por_fila)
    por_tandas = _escenario(api, sql, n)
    assert len(por_fila["empresa"]) > n // 2 and por_fila["contacto"] and por_fila["rechazo"]
    # con muchas filas, los teléfonos compartidos pasan a ser intermediarios y la regla por teléfono ya no los usa
    assert por_fila["revision"] or n > 5000
    # el escenario recorre los dos caminos: casi todo por tandas y los casos poco comunes fila por fila
    assert caminos["rapido"] > 4 * caminos["por_fila"] > 0, caminos
    _comparar(por_fila, por_tandas)


def test_mismo_resultado_que_fila_por_fila(api, sql, monkeypatch):
    _equivalencia(api, sql, monkeypatch, 1200)


@pytest.mark.skipif(not os.environ.get("RUN_LENTOS"), reason="test de volumen: correr con RUN_LENTOS=1")
def test_mismo_resultado_que_fila_por_fila_20000(api, sql, monkeypatch):
    _equivalencia(api, sql, monkeypatch, 20000)


# ─── Deshacer y borrar: recalcular por tandas ───

def test_recalcular_varias_igual_que_una_por_una(api, sql, monkeypatch):
    import psycopg

    from app import empresas, settings
    from app.db import pool

    monkeypatch.setattr(settings, "CARGAS_TAMANO_LOTE", 250)
    _escenario(api, sql, 300)
    # La carga grande deja de contar (como al deshacerla): los valores y atributos vigentes cambian
    sql.execute("UPDATE carga SET estado = 'deshaciendo' WHERE id = (SELECT max(id) FROM carga WHERE estado = 'confirmada'"
                " AND id < (SELECT max(id) FROM carga))")
    ids = [r["id"] for r in sql.execute("SELECT id FROM empresa ORDER BY id")]
    fotos = []
    with pool().connection() as c:
        for modo in ("una por una", "por tandas"):
            try:
                with c.transaction():
                    if modo == "una por una":
                        for eid in ids:
                            empresas.recalcular(c, eid)
                    else:
                        assert empresas.recalcular_varias(c, ids) > 0
                    f = foto(c)
                    fotos.append({k: f[k] for k in ("empresa", "atributo")})
                    raise psycopg.Rollback()
            except psycopg.Rollback:
                pass
    assert fotos[0]["empresa"] != foto(sql)["empresa"]            # recalcular cambió algo
    _comparar(*fotos)


# ─── V2 · Consultas por fila ───

def test_menos_de_01_consultas_por_fila(api, sql, monkeypatch):
    from app import settings

    monkeypatch.setattr(settings, "CARGAS_TAMANO_LOTE", 1000)
    filas = [{"RUT": RUTS[i], "Razón social": f"Empresa {i}", "Teléfono": "29%06d" % i, "Departamento": "Salto",
              "Empleados": str(i % 90)} for i in range(3000)]
    assert api.post("/atributos", json={"clave": "empleados", "nombre": "Empleados", "tipo": "numero"}).status_code == 200
    c = cargar(api, filas, mapeo={"atributos": {"empleados": "Empleados"}})
    assert c["estado"] == "confirmada" and c["conteos"]["altas"] == 3000
    l = sql.execute("SELECT sum(filas) AS filas, sum(consultas) AS c, sum(preview_consultas) AS p FROM carga_lote"
                    " WHERE carga_id = %s", (c["id"],)).fetchone()
    assert l["c"] / l["filas"] < 0.1 and l["p"] / l["filas"] < 0.1, l
    # Una segunda carga con las mismas empresas (actualizaciones): también por tandas
    c2 = cargar(api, [{**f, "Razón social": f["Razón social"] + " SRL"} for f in filas],
                mapeo={"atributos": {"empleados": "Empleados"}})
    assert c2["conteos"]["actualizaciones"] == 3000
    l = sql.execute("SELECT sum(filas) AS filas, sum(consultas) AS c FROM carga_lote WHERE carga_id = %s",
                    (c2["id"],)).fetchone()
    assert l["c"] / l["filas"] < 0.1, l
