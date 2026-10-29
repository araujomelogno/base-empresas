"""Detección y resolución de teléfonos intermediarios (R1.2).

Un teléfono vinculado a «umbral_intermediario» RUTs o más queda como sospechoso y sale
de toda exportación hasta que el data steward lo confirme o lo libere. Un teléfono
liberado no vuelve a marcarse salvo que sume RUTs nuevos.
"""
from fastapi import HTTPException

from . import auditoria, empresas

_CONTEO = """
SELECT t.id, t.intermediario, t.intermediario_n, count(DISTINCT v.empresa_id) AS n
FROM telefono t
JOIN telefono_vinculo v ON v.telefono_id = t.id
JOIN empresa e ON e.id = v.empresa_id AND e.baja IS NULL
WHERE (%(ids)s::int[] IS NULL OR t.id = ANY(%(ids)s::int[]))
GROUP BY t.id
HAVING count(DISTINCT v.empresa_id) >= %(umbral)s
"""


def detectar(conn, umbral: int, telefono_ids: list[int] | None = None, actor: str = "sistema") -> list[int]:
    """Marca los nuevos sospechosos y devuelve sus ids."""
    nuevos = []
    for t in conn.execute(_CONTEO, {"ids": telefono_ids, "umbral": umbral}).fetchall():
        if t["intermediario"] is None or (t["intermediario"] == "liberado" and t["n"] > (t["intermediario_n"] or 0)):
            nuevos.append(t["id"])
    if nuevos:
        conn.execute(
            "UPDATE telefono SET intermediario = 'sospechoso', intermediario_fecha = now(), intermediario_por = %s"
            " WHERE id = ANY(%s)",
            (actor, nuevos),
        )
        auditoria.registrar(conn, actor, "telefono.sospechoso", "telefono", None, {"ids": nuevos, "umbral": umbral})
    return nuevos


def contar_nuevos(conn, umbral: int, telefono_ids: list[int] | None = None) -> int:
    n = 0
    for t in conn.execute(_CONTEO, {"ids": telefono_ids, "umbral": umbral}).fetchall():
        if t["intermediario"] is None or (t["intermediario"] == "liberado" and t["n"] > (t["intermediario_n"] or 0)):
            n += 1
    return n


def sospechosos(conn, estado: str = "sospechoso") -> list[dict]:
    return conn.execute(
        """
        SELECT t.id, t.e164, t.crudo, t.tipo, t.intermediario, t.intermediario_fecha, t.intermediario_por,
               count(DISTINCT v.empresa_id) AS n_empresas,
               count(DISTINCT e.ciiu) AS n_rubros,
               json_agg(json_build_object('rut', e.rut, 'razon_social', e.razon_social, 'ciiu', e.ciiu,
                                          'estado_vinculo', v.estado) ORDER BY e.razon_social) AS empresas
        FROM telefono t
        JOIN telefono_vinculo v ON v.telefono_id = t.id
        JOIN empresa e ON e.id = v.empresa_id AND e.baja IS NULL
        WHERE t.intermediario = %s
        GROUP BY t.id
        ORDER BY count(DISTINCT v.empresa_id) DESC, t.id
        """,
        (estado,),
    ).fetchall()


def resolver(conn, telefono_id: int, accion: str, actor: str, motivo: str | None = None) -> dict:
    t = conn.execute("SELECT * FROM telefono WHERE id = %s FOR UPDATE", (telefono_id,)).fetchone()
    if t is None:
        raise HTTPException(404, "Teléfono inexistente")
    n = conn.execute(
        "SELECT count(DISTINCT v.empresa_id) AS n FROM telefono_vinculo v JOIN empresa e ON e.id = v.empresa_id"
        " WHERE v.telefono_id = %s AND e.baja IS NULL",
        (telefono_id,),
    ).fetchone()["n"]
    if accion == "confirmar":
        conn.execute(
            "UPDATE telefono SET intermediario = 'confirmado', intermediario_n = %s, intermediario_fecha = now(),"
            " intermediario_por = %s WHERE id = %s",
            (n, actor, telefono_id),
        )
        for v in conn.execute("SELECT * FROM telefono_vinculo WHERE telefono_id = %s", (telefono_id,)).fetchall():
            empresas.cambiar_estado_vinculo(conn, v, "intermediario", "manual", None, actor, {"motivo": motivo})
    elif accion == "liberar":
        conn.execute(
            "UPDATE telefono SET intermediario = 'liberado', intermediario_n = %s, intermediario_fecha = now(),"
            " intermediario_por = %s WHERE id = %s",
            (n, actor, telefono_id),
        )
        for v in conn.execute("SELECT * FROM telefono_vinculo WHERE telefono_id = %s AND estado = 'intermediario'",
                              (telefono_id,)).fetchall():
            empresas.cambiar_estado_vinculo(conn, v, "sin_verificar", "manual", None, actor, {"motivo": motivo})
    else:
        raise HTTPException(422, "accion debe ser 'confirmar' o 'liberar'")
    auditoria.registrar(conn, actor, f"telefono.{accion}_intermediario", "telefono", t["e164"] or t["crudo"],
                        {"n_empresas": n, "motivo": motivo})
    return {"id": telefono_id, "intermediario": "confirmado" if accion == "confirmar" else "liberado", "n_empresas": n}
