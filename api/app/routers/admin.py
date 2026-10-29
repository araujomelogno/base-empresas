"""Configuración, naturalezas, no llamar, usuarios, auditoría y tareas (R1.4, R1.12, R1.13)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auditoria, config, empresas, settings, tareas, telefonos as telmod
from ..auth import ROLES, Usuario, requiere, requiere_job, requiere_tarea, usuario_actual
from ..db import get_conn

router = APIRouter()


@router.get("/inicio")
def inicio(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """Resumen para la pantalla de inicio: estado de la base y bandejas pendientes."""
    r = conn.execute(
        """
        SELECT (SELECT count(*) FROM empresa WHERE baja IS NULL) AS empresas,
               (SELECT count(*) FROM v_empresa_disponible d JOIN empresa e ON e.id = d.empresa_id
                 WHERE d.disponible AND e.baja IS NULL) AS disponibles,
               (SELECT count(*) FROM telefono WHERE e164 IS NOT NULL) AS telefonos,
               (SELECT count(DISTINCT empresa_id) FROM v_vinculo_discable) AS con_telefono_discable,
               (SELECT count(*) FROM telefono WHERE intermediario = 'sospechoso') AS sospechosos,
               (SELECT count(*) FROM telefono WHERE intermediario = 'confirmado') AS intermediarios,
               (SELECT count(*) FROM revision_fusion WHERE estado = 'pendiente') AS revision,
               (SELECT count(*) FROM conciliacion WHERE estado = 'pendiente') AS conciliacion,
               (SELECT count(*) FROM muestra WHERE estado = 'activa') AS muestras_activas,
               (SELECT count(*) FROM no_llamar WHERE activo) AS no_llamar,
               (SELECT max(recibido) FROM cdr_lote) AS ultimo_cdr,
               (SELECT count(*) FROM intento WHERE inicio > now() - interval '7 days') AS intentos_7d
        """).fetchone()
    r["ultimas_cargas"] = conn.execute(
        "SELECT id, fuente, estado, fecha, conteos->>'altas' AS altas FROM carga ORDER BY id DESC LIMIT 5").fetchall()
    version, _ = config.vigente(conn)
    r["config_version"] = version
    return r


# ── Configuración ──

@router.get("/config")
def ver_config(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    version, params = config.vigente(conn)
    return {"version": version, "parametros": params, "historial": config.historial(conn)}


@router.get("/config/{version}")
def ver_version(version: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return {"version": version, "parametros": config.obtener(conn, version)}


class CambioConfig(BaseModel):
    parametros: dict
    comentario: str | None = None


@router.put("/config")
def cambiar_config(body: CambioConfig, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return {"version": config.guardar(conn, body.parametros, u.email, body.comentario)}


# ── Naturalezas jurídicas ──

@router.get("/naturalezas")
def naturalezas(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return conn.execute(
        "SELECT n.*, (SELECT count(*) FROM empresa e WHERE e.naturaleza_id = n.id AND e.baja IS NULL) AS empresas"
        " FROM naturaleza_juridica n ORDER BY n.nombre").fetchall()


class Naturaleza(BaseModel):
    codigo: str
    nombre: str
    excluida: bool = False


@router.post("/naturalezas")
def guardar_naturaleza(body: Naturaleza, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    codigo = body.codigo.strip().upper()
    conn.execute("INSERT INTO naturaleza_juridica (codigo, nombre) VALUES (%s, %s)"
                 " ON CONFLICT (codigo) DO UPDATE SET nombre = EXCLUDED.nombre", (codigo, body.nombre.strip()))
    _, params = config.vigente(conn)
    excl = set(params["naturalezas_excluidas"])
    nuevo = (excl | {codigo}) if body.excluida else (excl - {codigo})
    version = None
    if nuevo != excl:
        version = config.guardar(conn, {**params, "naturalezas_excluidas": sorted(nuevo)}, u.email,
                                 f"{'Excluye' if body.excluida else 'Habilita'} naturaleza {codigo}")
    auditoria.registrar(conn, u.email, "naturaleza.guardar", "naturaleza_juridica", codigo,
                        {"nombre": body.nombre, "excluida": body.excluida})
    return {"codigo": codigo, "config_version": version}


# ── No llamar ──

class NoLlamar(BaseModel):
    alcance: str
    rut: str | None = None
    telefono: str | None = None
    contacto_id: int | None = None
    motivo: str
    solicitante: str


@router.get("/no-llamar")
def listar_no_llamar(activos: bool = True, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return conn.execute(
        """
        SELECT n.*, CASE n.alcance WHEN 'empresa' THEN (SELECT rut || ' · ' || coalesce(razon_social, '') FROM empresa WHERE id = n.objeto_id)
                                   WHEN 'telefono' THEN (SELECT coalesce(e164, crudo) FROM telefono WHERE id = n.objeto_id)
                                   ELSE (SELECT c.nombre || ' (' || e.rut || ')' FROM contacto c JOIN empresa e ON e.id = c.empresa_id
                                         WHERE c.id = n.objeto_id) END AS objeto
        FROM no_llamar n WHERE (%s = false OR n.activo) ORDER BY n.id DESC LIMIT 500
        """, (activos,)).fetchall()


@router.post("/no-llamar")
def registrar_no_llamar(body: NoLlamar, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin", "steward"))):
    if not body.motivo.strip() or not body.solicitante.strip():
        raise HTTPException(422, "Motivo y solicitante son obligatorios")
    if body.alcance == "empresa":
        e = empresas.por_rut(conn, body.rut or "")
        if e is None:
            raise HTTPException(404, "Empresa inexistente")
        objeto_id, etiqueta = e["id"], e["rut"]
    elif body.alcance == "telefono":
        n = telmod.normalizar(body.telefono)
        t = conn.execute("SELECT id FROM telefono WHERE e164 = %s", (n.e164,)).fetchone() if n.e164 else None
        if t is None:
            fila, n, _ = empresas.telefono(conn, body.telefono)
            if fila is None:
                raise HTTPException(422, "Teléfono vacío")
            t = fila
        objeto_id, etiqueta = t["id"], n.e164 or n.crudo
    elif body.alcance == "contacto":
        c = conn.execute("SELECT id FROM contacto WHERE id = %s", (body.contacto_id,)).fetchone()
        if c is None:
            raise HTTPException(404, "Contacto inexistente")
        objeto_id, etiqueta = c["id"], str(c["id"])
    else:
        raise HTTPException(422, "alcance: empresa | telefono | contacto")
    r = conn.execute(
        "INSERT INTO no_llamar (alcance, objeto_id, motivo, solicitante, registrado_por) VALUES (%s,%s,%s,%s,%s) RETURNING *",
        (body.alcance, objeto_id, body.motivo, body.solicitante, u.email)).fetchone()
    auditoria.registrar(conn, u.email, "no_llamar.registrar", body.alcance, etiqueta,
                        {"motivo": body.motivo, "solicitante": body.solicitante})
    return r


@router.delete("/no-llamar/{nid}")
def levantar_no_llamar(nid: int, motivo: str, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    r = conn.execute("UPDATE no_llamar SET activo = false WHERE id = %s AND activo RETURNING *", (nid,)).fetchone()
    if r is None:
        raise HTTPException(404, "Registro inexistente o ya levantado")
    auditoria.registrar(conn, u.email, "no_llamar.levantar", r["alcance"], r["objeto_id"], {"motivo": motivo})
    return {"ok": True}


# ── Usuarios ──

class UsuarioIn(BaseModel):
    email: str
    nombre: str | None = None
    rol: str
    exportar_contactos: bool = False
    activo: bool = True


@router.get("/usuarios")
def usuarios(conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return conn.execute("SELECT * FROM usuario ORDER BY activo DESC, email").fetchall()


@router.post("/usuarios")
def guardar_usuario(body: UsuarioIn, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    if body.rol not in ROLES:
        raise HTTPException(422, f"rol: {', '.join(ROLES)}")
    email = body.email.strip().lower()
    if email == u.email and (body.rol != "admin" or not body.activo):
        raise HTTPException(422, "No podés quitarte el rol de administrador a vos mismo")
    r = conn.execute(
        "INSERT INTO usuario (email, nombre, rol, exportar_contactos, activo) VALUES (%s,%s,%s,%s,%s)"
        " ON CONFLICT (email) DO UPDATE SET nombre = EXCLUDED.nombre, rol = EXCLUDED.rol,"
        " exportar_contactos = EXCLUDED.exportar_contactos, activo = EXCLUDED.activo RETURNING *",
        (email, body.nombre, body.rol, body.exportar_contactos, body.activo)).fetchone()
    auditoria.registrar(conn, u.email, "usuario.guardar", "usuario", email,
                        {"rol": body.rol, "exportar_contactos": body.exportar_contactos, "activo": body.activo})
    return r


# ── Auditoría ──

@router.get("/auditoria")
def ver_auditoria(objeto: str | None = None, actor: str | None = None, accion: str | None = None, limite: int = 200,
                  conn=Depends(get_conn), u: Usuario = Depends(requiere("admin", "steward"))):
    return conn.execute(
        "SELECT * FROM auditoria WHERE (%s::text IS NULL OR objeto = %s) AND (%s::text IS NULL OR actor = %s)"
        " AND (%s::text IS NULL OR accion LIKE %s || '%%') ORDER BY id DESC LIMIT %s",
        (objeto, objeto, actor, actor, accion, accion, min(limite, 2000))).fetchall()


# ── Tareas diferidas ──

@router.get("/tareas/{tarea_id}")
def ver_tarea(tarea_id: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    t = tareas.obtener(conn, tarea_id)
    if t is None:
        raise HTTPException(404, "Tarea inexistente")
    return t


@router.post("/tareas/{tarea_id}/ejecutar")
def ejecutar_tarea(tarea_id: int, _: str = Depends(requiere_tarea)):
    """Lo llama Cloud Tasks. Devuelve 200 aunque la tarea falle (el error queda en la tarea)."""
    return {"resultado": tareas.ejecutar(tarea_id)}


# ── Export diario de auditoría a BigQuery ──

@router.post("/jobs/auditoria-bq")
def exportar_auditoria(conn=Depends(get_conn), _: str = Depends(requiere_job)):
    if not settings.BQ_TABLA_AUDITORIA:
        raise HTTPException(503, "BQ_TABLA_AUDITORIA no está configurada")
    from google.cloud import bigquery

    estado = conn.execute("INSERT INTO export_estado (nombre) VALUES ('auditoria_bq') ON CONFLICT (nombre) DO UPDATE"
                          " SET nombre = EXCLUDED.nombre RETURNING *").fetchone()
    filas = conn.execute("SELECT * FROM auditoria WHERE id > %s ORDER BY id LIMIT 50000", (estado["ultimo_id"],)).fetchall()
    if not filas:
        return {"exportadas": 0}
    from ..util import json_dumps

    cliente = bigquery.Client()
    errores = cliente.insert_rows_json(settings.BQ_TABLA_AUDITORIA, [
        {"id": f["id"], "actor": f["actor"], "accion": f["accion"], "objeto": f["objeto"], "objeto_id": f["objeto_id"],
         "detalle": json_dumps(f["detalle"]) if f["detalle"] is not None else None, "fecha": f["fecha"].isoformat()}
        for f in filas])
    if errores:
        raise HTTPException(502, f"BigQuery rechazó filas: {errores[:3]}")
    conn.execute("UPDATE export_estado SET ultimo_id = %s, fecha = now() WHERE nombre = 'auditoria_bq'", (filas[-1]["id"],))
    return {"exportadas": len(filas), "ultimo_id": filas[-1]["id"]}
