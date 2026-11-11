"""Log de auditoría append-only (R1.13)."""


def registrar(conn, actor: str, accion: str, objeto: str, objeto_id=None, detalle: dict | None = None) -> int:
    return conn.execute(
        "INSERT INTO auditoria (actor, accion, objeto, objeto_id, detalle) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (actor, accion, objeto, None if objeto_id is None else str(objeto_id), _json(detalle)),
    ).fetchone()["id"]


def _json(d):
    from psycopg.types.json import Jsonb

    return Jsonb(d) if d is not None else None
