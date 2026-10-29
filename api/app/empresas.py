"""Registro maestro de empresas: linaje por campo, supervivencia, teléfonos y fusiones (R1.1, R1.2).

Regla de supervivencia: gana el valor de mayor confianza y, a igual confianza, el más
reciente. Un dato confirmado por la sala (fuente 'sala' o 'sav') nunca lo pisa una carga.
La historia es append-only: deshacer una carga o una fusión no borra filas, las anula
(el cálculo del valor vigente ignora las filas de cargas deshechas y fusiones deshechas).
"""
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import auditoria, rut as rutmod, telefonos as telmod
from .util import razon_normalizada

CAMPOS = ("razon_social", "fantasia", "naturaleza", "ciiu", "tamano", "departamento",
          "localidad", "direccion", "web", "estado")
ESTADOS_EMPRESA = ("activa", "cerrada", "desconocida")
FUENTES_SALA = ("sala", "sav")

_CANDIDATOS_SQL = """
SELECT h.id, h.campo, h.valor, h.fuente_tipo, h.fuente_id, h.confianza, h.actor, h.fecha, h.detalle
FROM empresa_campo_historia h
LEFT JOIN carga c ON h.fuente_tipo = 'carga' AND c.id = h.fuente_id
LEFT JOIN empresa_fusion f ON h.fuente_tipo = 'fusion' AND f.id = h.fuente_id
WHERE h.empresa_id = %s
  AND (c.id IS NULL OR c.estado <> 'deshecha')
  AND (f.id IS NULL OR f.deshecha IS NULL)
"""


def ganador(filas: list[dict]) -> dict | None:
    """Aplica la regla de supervivencia a las filas de historia de un campo."""
    if not filas:
        return None
    if any(f["fuente_tipo"] in FUENTES_SALA for f in filas):
        filas = [f for f in filas if f["fuente_tipo"] != "carga"]
    return max(filas, key=lambda f: (f["confianza"], f["fecha"], f["id"]))


def _naturaleza_id(conn, codigo):
    if codigo is None:
        return None
    r = conn.execute("SELECT id FROM naturaleza_juridica WHERE codigo = %s", (codigo,)).fetchone()
    return r["id"] if r else None


def resolver_naturaleza(conn, valor) -> str | None:
    """Acepta código ('SA') o nombre ('Sociedad anónima') y devuelve el código."""
    if valor is None:
        return None
    v = str(valor).strip()
    r = conn.execute(
        "SELECT codigo FROM naturaleza_juridica WHERE upper(codigo) = upper(%s) OR lower(nombre) = lower(%s)",
        (v, v),
    ).fetchone()
    return r["codigo"] if r else None


def vigentes(conn, empresa_id: int, campos=None) -> dict:
    """Valor ganador (fila completa de historia) por campo."""
    filas = conn.execute(_CANDIDATOS_SQL, (empresa_id,)).fetchall()
    por_campo: dict[str, list] = {}
    for f in filas:
        if campos is None or f["campo"] in campos:
            por_campo.setdefault(f["campo"], []).append(f)
    return {c: ganador(fs) for c, fs in por_campo.items()}


def recalcular(conn, empresa_id: int, campos=None) -> dict:
    """Recalcula y guarda los valores vigentes; devuelve {campo: (antes, después)} de lo que cambió."""
    campos = tuple(campos or CAMPOS)
    emp = conn.execute("SELECT e.*, n.codigo AS naturaleza FROM empresa e "
                       "LEFT JOIN naturaleza_juridica n ON n.id = e.naturaleza_id WHERE e.id = %s",
                       (empresa_id,)).fetchone()
    ganadores = vigentes(conn, empresa_id, campos)
    cambios = {}
    sets, args = [], []
    for c in campos:
        g = ganadores.get(c)
        nuevo = g["valor"] if g else (None if c != "estado" else "desconocida")
        actual = emp[c]
        if nuevo != actual:
            cambios[c] = (actual, nuevo)
            if c == "naturaleza":
                sets.append("naturaleza_id = %s")
                args.append(_naturaleza_id(conn, nuevo))
            else:
                sets.append(f"{c} = %s")
                args.append(nuevo)
    if sets:
        conn.execute(f"UPDATE empresa SET {', '.join(sets)}, actualizado = now() WHERE id = %s",
                     (*args, empresa_id))
    return cambios


def aplicar_valores(conn, empresa_id: int, valores: dict, fuente_tipo: str, fuente_id, confianza: int,
                    actor: str, detalle: dict | None = None) -> tuple[dict, dict]:
    """Registra en la historia los valores no vacíos y recalcula los vigentes.

    Devuelve (cambios, conflictos): conflictos son los campos donde el valor que llegó es
    distinto del vigente y no ganó (p. ej. una carga contra un dato confirmado por la sala).
    """
    limpios = {c: v for c, v in valores.items() if c in CAMPOS and v is not None and str(v).strip() != ""}
    if not limpios:
        return {}, {}
    antes = vigentes(conn, empresa_id, tuple(limpios))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO empresa_campo_historia (empresa_id, campo, valor, fuente_tipo, fuente_id, confianza, actor, detalle)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            [(empresa_id, c, str(v), fuente_tipo, fuente_id, confianza, actor, Jsonb(detalle) if detalle else None)
             for c, v in limpios.items()],
        )
    cambios = recalcular(conn, empresa_id, tuple(limpios))
    conflictos = {}
    for c, v in limpios.items():
        previo = antes.get(c)
        if previo is not None and previo["valor"] != str(v) and c not in cambios:
            conflictos[c] = {"vigente": previo["valor"], "fuente_vigente": previo["fuente_tipo"], "llego": str(v)}
    return cambios, conflictos


def por_rut(conn, rut: str, seguir_fusion: bool = True) -> dict | None:
    r, _ = rutmod.validar(rut)
    if r is None:
        return None
    emp = conn.execute("SELECT * FROM empresa WHERE rut = %s", (r,)).fetchone()
    vistos = set()
    while seguir_fusion and emp and emp["baja"] == "fusionada" and emp["fusionada_en"] and emp["id"] not in vistos:
        vistos.add(emp["id"])
        emp = conn.execute("SELECT * FROM empresa WHERE id = %s", (emp["fusionada_en"],)).fetchone()
    return emp


def obtener_o_404(conn, rut: str) -> dict:
    emp = por_rut(conn, rut, seguir_fusion=False)
    if emp is None:
        raise HTTPException(404, f"No existe la empresa con RUT {rut}")
    return emp


# ─────────────────────────────────────────────────────────────
# Teléfonos y vínculos
# ─────────────────────────────────────────────────────────────

def telefono(conn, valor, prefijos=()) -> tuple[dict | None, telmod.Telefono, bool]:
    """Obtiene o crea el teléfono. Devuelve (fila, normalizado, creado)."""
    n = telmod.normalizar(valor, prefijos)
    if not n.crudo:
        return None, n, False
    if n.e164:
        fila = conn.execute(
            "INSERT INTO telefono (e164, crudo, tipo) VALUES (%s, %s, %s) ON CONFLICT (e164) DO NOTHING RETURNING *",
            (n.e164, n.crudo, n.tipo),
        ).fetchone()
        if fila:
            return fila, n, True
        return conn.execute("SELECT * FROM telefono WHERE e164 = %s", (n.e164,)).fetchone(), n, False
    fila = conn.execute(
        "INSERT INTO telefono (e164, crudo, tipo, estado) VALUES (NULL, %s, 'invalido', 'invalido')"
        " ON CONFLICT (crudo) WHERE e164 IS NULL DO NOTHING RETURNING *",
        (n.crudo,),
    ).fetchone()
    if fila:
        return fila, n, True
    return conn.execute("SELECT * FROM telefono WHERE crudo = %s AND e164 IS NULL", (n.crudo,)).fetchone(), n, False


def vincular(conn, telefono_id: int, empresa_id: int, fuente_tipo: str, fuente_id, actor: str,
             contacto_id=None, sucursal_id=None, estado="sin_verificar", detalle=None) -> tuple[dict, bool]:
    v = conn.execute(
        "INSERT INTO telefono_vinculo (telefono_id, empresa_id, contacto_id, sucursal_id, estado, fuente_tipo, fuente_id)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (telefono_id, empresa_id) DO NOTHING RETURNING *",
        (telefono_id, empresa_id, contacto_id, sucursal_id, estado, fuente_tipo, fuente_id),
    ).fetchone()
    if v:
        _historia_vinculo(conn, v, estado, fuente_tipo, fuente_id, actor, detalle)
        return v, True
    v = conn.execute("SELECT * FROM telefono_vinculo WHERE telefono_id = %s AND empresa_id = %s",
                     (telefono_id, empresa_id)).fetchone()
    if contacto_id and v["contacto_id"] is None:
        conn.execute("UPDATE telefono_vinculo SET contacto_id = %s WHERE id = %s", (contacto_id, v["id"]))
    return v, False


def _historia_vinculo(conn, v, estado, fuente_tipo, fuente_id, actor, detalle=None):
    conn.execute(
        "INSERT INTO telefono_vinculo_historia (vinculo_id, telefono_id, empresa_id, estado, fuente_tipo, fuente_id, actor, detalle)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (v["id"], v["telefono_id"], v["empresa_id"], estado, fuente_tipo, fuente_id, actor,
         Jsonb(detalle) if detalle else None),
    )


def cambiar_estado_vinculo(conn, vinculo: dict, estado: str, fuente_tipo: str, fuente_id, actor: str,
                           detalle=None) -> bool:
    if vinculo["estado"] == estado:
        return False
    conn.execute("UPDATE telefono_vinculo SET estado = %s, fecha = now() WHERE id = %s", (estado, vinculo["id"]))
    _historia_vinculo(conn, vinculo, estado, fuente_tipo, fuente_id, actor, detalle)
    return True


def contacto(conn, empresa_id: int, nombre: str, cargo, area, email, fuente_tipo, fuente_id,
             detalle=None, sucursal_id=None) -> tuple[dict, bool]:
    """Crea o actualiza un contacto de la empresa (se identifica por nombre normalizado)."""
    clave = razon_normalizada(nombre)
    for c in conn.execute("SELECT * FROM contacto WHERE empresa_id = %s", (empresa_id,)).fetchall():
        if razon_normalizada(c["nombre"]) == clave:
            conn.execute(
                "UPDATE contacto SET cargo = coalesce(%s, cargo), area = coalesce(%s, area),"
                " email = coalesce(%s, email), actualizado = now() WHERE id = %s",
                (cargo, area, email, c["id"]),
            )
            return c, False
    c = conn.execute(
        "INSERT INTO contacto (empresa_id, sucursal_id, nombre, cargo, area, email, fuente_tipo, fuente_id, detalle)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (empresa_id, sucursal_id, nombre.strip(), cargo, area, email, fuente_tipo, fuente_id,
         Jsonb(detalle) if detalle else None),
    ).fetchone()
    return c, True


# ─────────────────────────────────────────────────────────────
# Fusión de empresas (reversible)
# ─────────────────────────────────────────────────────────────

def fusionar(conn, absorbente: dict, absorbida: dict, actor: str, motivo: str | None) -> int:
    if absorbente["id"] == absorbida["id"]:
        raise HTTPException(422, "No se puede fusionar una empresa consigo misma")
    if absorbida["baja"] or absorbente["baja"]:
        raise HTTPException(409, "Alguna de las empresas ya está dada de baja o fusionada")
    fusion_id = conn.execute(
        "INSERT INTO empresa_fusion (absorbente_id, absorbida_id, movidos, actor, motivo)"
        " VALUES (%s,%s,'{}'::jsonb,%s,%s) RETURNING id",
        (absorbente["id"], absorbida["id"], actor, motivo),
    ).fetchone()["id"]
    a, b = absorbente["id"], absorbida["id"]
    movidos = {"vinculos": [], "vinculos_borrados": [], "contactos": [], "sucursales": [], "no_llamar": [],
               "ultimo_contacto_efectivo": absorbente["ultimo_contacto_efectivo"]}
    for v in conn.execute("SELECT * FROM telefono_vinculo WHERE empresa_id = %s", (b,)).fetchall():
        ya = conn.execute("SELECT 1 FROM telefono_vinculo WHERE empresa_id = %s AND telefono_id = %s",
                          (a, v["telefono_id"])).fetchone()
        if ya:
            movidos["vinculos_borrados"].append(dict(v))
            conn.execute("DELETE FROM telefono_vinculo WHERE id = %s", (v["id"],))
        else:
            movidos["vinculos"].append(v["id"])
            conn.execute("UPDATE telefono_vinculo SET empresa_id = %s WHERE id = %s", (a, v["id"]))
            _historia_vinculo(conn, {**v, "empresa_id": a}, v["estado"], "fusion", fusion_id, actor,
                              {"desde_empresa": b})
    movidos["contactos"] = [r["id"] for r in conn.execute(
        "UPDATE contacto SET empresa_id = %s WHERE empresa_id = %s RETURNING id", (a, b))]
    movidos["sucursales"] = [r["id"] for r in conn.execute(
        "UPDATE sucursal SET empresa_id = %s WHERE empresa_id = %s RETURNING id", (a, b))]
    for n in conn.execute("SELECT * FROM no_llamar WHERE activo AND alcance = 'empresa' AND objeto_id = %s",
                          (b,)).fetchall():
        nid = conn.execute(
            "INSERT INTO no_llamar (alcance, objeto_id, motivo, solicitante, registrado_por)"
            " VALUES ('empresa', %s, %s, %s, %s) RETURNING id",
            (a, f"{n['motivo']} (heredado por fusión)", n["solicitante"], actor),
        ).fetchone()["id"]
        movidos["no_llamar"].append(nid)
    # Valores de la absorbida entran como candidatos con su misma confianza
    for campo, fila in vigentes(conn, b).items():
        if fila:
            conn.execute(
                "INSERT INTO empresa_campo_historia (empresa_id, campo, valor, fuente_tipo, fuente_id, confianza, actor, detalle)"
                " VALUES (%s,%s,%s,'fusion',%s,%s,%s,%s)",
                (a, campo, fila["valor"], fusion_id, fila["confianza"], actor,
                 Jsonb({"desde_empresa": b, "fuente_original": fila["fuente_tipo"]})),
            )
    recalcular(conn, a)
    conn.execute(
        "UPDATE empresa SET ultimo_contacto_efectivo = GREATEST(ultimo_contacto_efectivo, %s) WHERE id = %s",
        (absorbida["ultimo_contacto_efectivo"], a),
    )
    conn.execute("UPDATE empresa SET baja = 'fusionada', fusionada_en = %s, actualizado = now() WHERE id = %s", (a, b))
    conn.execute("UPDATE empresa_fusion SET movidos = %s WHERE id = %s", (Jsonb(movidos), fusion_id))
    auditoria.registrar(conn, actor, "empresa.fusionar", "empresa", absorbente["rut"],
                        {"fusion_id": fusion_id, "absorbida": absorbida["rut"], "motivo": motivo})
    return fusion_id


def deshacer_fusion(conn, fusion_id: int, actor: str):
    f = conn.execute("SELECT * FROM empresa_fusion WHERE id = %s FOR UPDATE", (fusion_id,)).fetchone()
    if f is None:
        raise HTTPException(404, "Fusión inexistente")
    if f["deshecha"]:
        raise HTTPException(409, "La fusión ya fue deshecha")
    a, b, m = f["absorbente_id"], f["absorbida_id"], f["movidos"]
    for vid in m["vinculos"]:
        conn.execute("UPDATE telefono_vinculo SET empresa_id = %s WHERE id = %s", (b, vid))
    for v in m["vinculos_borrados"]:
        conn.execute(
            "INSERT INTO telefono_vinculo (id, telefono_id, empresa_id, contacto_id, sucursal_id, estado, fuente_tipo, fuente_id, fecha)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (v["id"], v["telefono_id"], b, v["contacto_id"], v["sucursal_id"], v["estado"], v["fuente_tipo"],
             v["fuente_id"], v["fecha"]),
        )
    if m["contactos"]:
        conn.execute("UPDATE contacto SET empresa_id = %s WHERE id = ANY(%s)", (b, m["contactos"]))
    if m["sucursales"]:
        conn.execute("UPDATE sucursal SET empresa_id = %s WHERE id = ANY(%s)", (b, m["sucursales"]))
    if m["no_llamar"]:
        conn.execute("UPDATE no_llamar SET activo = false WHERE id = ANY(%s)", (m["no_llamar"],))
    conn.execute("UPDATE empresa_fusion SET deshecha = now(), deshecha_por = %s WHERE id = %s", (actor, fusion_id))
    conn.execute("UPDATE empresa SET ultimo_contacto_efectivo = %s WHERE id = %s",
                 (m.get("ultimo_contacto_efectivo"), a))
    conn.execute("UPDATE empresa SET baja = NULL, fusionada_en = NULL, actualizado = now() WHERE id = %s", (b,))
    recalcular(conn, a)
    rut_a = conn.execute("SELECT rut FROM empresa WHERE id = %s", (a,)).fetchone()["rut"]
    auditoria.registrar(conn, actor, "empresa.deshacer_fusion", "empresa", rut_a, {"fusion_id": fusion_id})
