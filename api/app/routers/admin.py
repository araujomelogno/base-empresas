"""Configuración, naturalezas, no llamar, usuarios, auditoría y tareas (R1.4, R1.12, R1.13)."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import accesos, auditoria, cdr_corridas, config, empresas, intermediarios, provisorias, settings, tareas, telefonos as telmod
from ..auth import ROLES, Usuario, requiere, requiere_job, requiere_tarea, usuario_actual
from ..db import conexion, get_conn

router = APIRouter()


@router.get("/inicio")
def inicio(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    """Resumen para la pantalla de inicio: estado de la base y bandejas pendientes."""
    r = conn.execute(
        """
        SELECT (SELECT count(*) FROM empresa WHERE baja IS NULL AND base = 'definitiva') AS empresas,
               (SELECT count(*) FROM empresa WHERE baja IS NULL AND base = 'provisoria') AS provisorias,
               (SELECT count(*) FROM v_empresa_disponible d JOIN empresa e ON e.id = d.empresa_id
                 WHERE d.disponible AND e.baja IS NULL) AS disponibles,
               (SELECT count(*) FROM telefono WHERE e164 IS NOT NULL) AS telefonos,
               (SELECT count(DISTINCT empresa_id) FROM v_vinculo_discable) AS con_telefono_discable,
               (""" + intermediarios.SQL_CONTADOR + """) AS sospechosos,
               (SELECT count(*) FROM telefono WHERE intermediario = 'confirmado') AS intermediarios,
               (SELECT count(*) FROM revision_fusion WHERE estado = 'pendiente') AS revision,
               (SELECT count(*) FROM conciliacion WHERE estado = 'pendiente') AS conciliacion,
               (SELECT count(*) FROM muestra WHERE estado = 'activa') AS muestras_activas,
               (SELECT count(*) FROM no_llamar WHERE activo) AS no_llamar,
               (SELECT count(*) FROM intento WHERE inicio > now() - interval '7 days') AS intentos_7d
        """).fetchone()
    r["provisorias_con_candidatas"] = provisorias.contar_con_candidatas(conn) if r["provisorias"] else 0
    r["ultimas_cargas"] = conn.execute(
        "SELECT id, fuente, estado, fecha, conteos->>'altas' AS altas FROM carga ORDER BY id DESC LIMIT 5").fetchall()
    version, _ = config.vigente(conn)
    r["config_version"] = version
    r["cdr"] = cdr_corridas.resumen(conn)
    return r


# ── Configuración ──

@router.get("/config")
def ver_config(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    version, params = config.vigente(conn)
    params = {**params, "cdr": config.cdr(params), "enriquecimiento": config.enriquecimiento(params),
              "dominios_genericos": params.get("dominios_genericos") or list(config.DOMINIOS_GENERICOS)}
    r = {"version": version, "parametros": params, "historial": config.historial(conn)}
    if u.rol == "admin":  # nunca el valor: solo si está configurada, cuándo y por quién
        r["cdr_password"] = cdr_corridas.estado_password(conn)
    return r


# ── CDR: contraseña, prueba de conexión y corridas (SPEC_job_cdr_en_cloud) ──

class PasswordCdr(BaseModel):
    password: str


@router.put("/config/cdr/password")
def guardar_password_cdr(body: PasswordCdr, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return cdr_corridas.guardar_password(conn, body.password, u.email)


class PruebaCdr(BaseModel):
    parametros: dict | None = None
    password: str | None = None


@router.post("/config/cdr/probar")
def probar_cdr(body: PruebaCdr, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return cdr_corridas.probar(conn, body.parametros, body.password or None)


class CorridaCdr(BaseModel):
    desde: dt.date | None = None
    hasta: dt.date | None = None
    dry_run: bool = False


@router.post("/config/cdr/correr")
def correr_cdr(body: CorridaCdr, u: Usuario = Depends(requiere("admin"))):
    with conexion() as conn:
        corrida_id = cdr_corridas.lanzar(conn, u.email, body.desde, body.hasta, body.dry_run)
    cdr_corridas.despachar(corrida_id, cdr_corridas.argumentos(corrida_id, body.desde, body.hasta, body.dry_run))
    return {"corrida_id": corrida_id}


@router.get("/cdr/corridas")
def corridas_cdr(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return cdr_corridas.corridas(conn)


@router.get("/cdr/corridas/{corrida_id}")
def corrida_cdr(corrida_id: int, conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    return cdr_corridas.corrida(conn, corrida_id)


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
# El código es el identificador: lo guardan la historia de cada empresa, la configuración (naturalezas excluidas) y los
# criterios de las muestras. Por eso se edita el nombre y la exclusión, pero no el código, y solo se borra una
# naturaleza que ninguna empresa usa ni usó.

_USO_NATURALEZA = """
SELECT (SELECT count(*) FROM empresa e WHERE e.naturaleza_id = n.id AND e.baja IS NULL) AS empresas,
       (SELECT count(*) FROM empresa e WHERE e.naturaleza_id = n.id) AS empresas_todas,
       (SELECT count(*) FROM empresa_campo_historia h WHERE h.campo = 'naturaleza' AND h.valor = n.codigo) AS historia
"""


@router.get("/naturalezas")
def naturalezas(conn=Depends(get_conn), u: Usuario = Depends(usuario_actual)):
    filas = conn.execute(
        "SELECT n.*, u.* FROM naturaleza_juridica n CROSS JOIN LATERAL (" + _USO_NATURALEZA + ") u ORDER BY n.nombre").fetchall()
    for f in filas:
        f["borrable"] = not f["empresas_todas"] and not f["historia"]
    return filas


class Naturaleza(BaseModel):
    codigo: str
    nombre: str
    excluida: bool = False


class EdicionNaturaleza(BaseModel):
    nombre: str | None = None
    excluida: bool | None = None
    codigo: str | None = None


def _nombre_naturaleza(conn, nombre: str | None, nid: int | None) -> str:
    n = (nombre or "").strip()
    if not n:
        raise HTTPException(422, "El nombre está vacío")
    otra = conn.execute("SELECT codigo FROM naturaleza_juridica WHERE lower(nombre) = lower(%s) AND id IS DISTINCT FROM %s",
                        (n, nid)).fetchone()
    if otra:
        raise HTTPException(409, f"Ya hay una naturaleza con ese nombre ({otra['codigo'] or 'sin código'})")
    return n


def _excluir(conn, codigo: str, excluida: bool, actor: str, quitar: str | None = None) -> int | None:
    """Excluir o habilitar crea una versión nueva de la configuración (la fuente de verdad versionada).
    quitar: un código viejo que sale de las excluidas (al corregir el código de una naturaleza sin uso)."""
    _, params = config.vigente(conn)
    excl = set(params["naturalezas_excluidas"])
    nuevo = ((excl - {quitar}) | {codigo}) if excluida else (excl - {codigo, quitar})
    if nuevo == excl:
        return None
    return config.guardar(conn, {**params, "naturalezas_excluidas": sorted(nuevo)}, actor,
                          f"{'Excluye' if excluida else 'Habilita'} naturaleza {codigo or '(sin código)'}")


def _naturaleza_o_404(conn, nid: int) -> dict:
    """Por id y no por código: una naturaleza vieja puede tener el código vacío (antes no se validaba), y con el
    código en la URL («/naturalezas/») la API respondía una redirección que el navegador cortaba."""
    n = conn.execute("SELECT n.*, u.* FROM naturaleza_juridica n CROSS JOIN LATERAL (" + _USO_NATURALEZA + ") u"
                     " WHERE n.id = %s FOR UPDATE OF n", (nid,)).fetchone()
    if n is None:
        raise HTTPException(404, "No existe esa naturaleza")
    return n


@router.post("/naturalezas")
def guardar_naturaleza(body: Naturaleza, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    """Crea la naturaleza o, si el código ya existe, actualiza su nombre y su exclusión (lo usan la demo y la carga
    inicial de fase0/cargar_excluidos.py). La pantalla edita con PUT y no deja crear un código que ya existe."""
    codigo = (body.codigo or "").strip().upper()
    nombre = (body.nombre or "").strip()
    if not codigo or not nombre:
        raise HTTPException(422, "Completá el código y el nombre")
    nueva = conn.execute("INSERT INTO naturaleza_juridica (codigo, nombre) VALUES (%s, %s)"
                         " ON CONFLICT (codigo) DO UPDATE SET nombre = EXCLUDED.nombre RETURNING (xmax = 0) AS nueva",
                         (codigo, nombre)).fetchone()["nueva"]
    version = _excluir(conn, codigo, body.excluida, u.email)
    auditoria.registrar(conn, u.email, "naturaleza.crear" if nueva else "naturaleza.guardar", "naturaleza_juridica", codigo,
                        {"nombre": nombre, "excluida": body.excluida})
    return {"codigo": codigo, "config_version": version}


@router.put("/naturalezas/{nid}")
def editar_naturaleza(nid: int, body: EdicionNaturaleza, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    n = _naturaleza_o_404(conn, nid)
    cambios = {}
    codigo, viejo = n["codigo"], None
    if body.codigo is not None and body.codigo.strip().upper() != n["codigo"]:
        # El código se corrige solo si nadie lo usa (ninguna empresa ni dato de la historia lo tiene)
        if n["empresas_todas"] or n["historia"]:
            raise HTTPException(409, f"El código de {n['codigo']} no se cambia: lo usan empresas o su historia")
        codigo = body.codigo.strip().upper()
        if not codigo:
            raise HTTPException(422, "El código está vacío")
        if conn.execute("SELECT 1 FROM naturaleza_juridica WHERE codigo = %s AND id <> %s", (codigo, nid)).fetchone():
            raise HTTPException(409, f"Ya existe la naturaleza {codigo}")
        conn.execute("UPDATE naturaleza_juridica SET codigo = %s WHERE id = %s", (codigo, nid))
        cambios["codigo"] = {"antes": n["codigo"], "despues": codigo}
        viejo = n["codigo"]
    if body.nombre is not None:
        nombre = _nombre_naturaleza(conn, body.nombre, nid)
        if nombre != n["nombre"]:
            conn.execute("UPDATE naturaleza_juridica SET nombre = %s WHERE id = %s", (nombre, nid))
            cambios["nombre"] = {"antes": n["nombre"], "despues": nombre}
    excluida = n["excluida"] if body.excluida is None else body.excluida
    version = _excluir(conn, codigo, excluida, u.email, quitar=viejo) if (body.excluida is not None or viejo is not None) else None
    if version and excluida != n["excluida"]:
        cambios["excluida"] = {"antes": n["excluida"], "despues": excluida}
    if cambios:
        auditoria.registrar(conn, u.email, "naturaleza.editar", "naturaleza_juridica", codigo or f"id:{nid}", cambios)
    return {"id": nid, "codigo": codigo, "config_version": version, "cambios": list(cambios)}


@router.delete("/naturalezas/{nid}")
def borrar_naturaleza(nid: int, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    n = _naturaleza_o_404(conn, nid)
    nombre = n["codigo"] or n["nombre"]
    if n["empresas_todas"]:
        raise HTTPException(409, f"{nombre} la tienen {n['empresas_todas']} empresas: no se puede borrar."
                                 " Si no se usa más, cambiale el nombre o dejala como está")
    if n["historia"]:
        raise HTTPException(409, f"{nombre} figura en la historia de {n['historia']} datos de empresas: no se puede borrar")
    version = _excluir(conn, n["codigo"], False, u.email) if n["excluida"] else None
    conn.execute("DELETE FROM naturaleza_juridica WHERE id = %s", (nid,))
    auditoria.registrar(conn, u.email, "naturaleza.borrar", "naturaleza_juridica", n["codigo"] or f"id:{nid}",
                        {"nombre": n["nombre"], "excluida": n["excluida"]})
    return {"borrada": n["codigo"], "id": nid, "config_version": version}


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
                                   ELSE (SELECT c.nombre || ' (' || e.codigo || ')' FROM contacto c JOIN empresa e ON e.id = c.empresa_id
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
        objeto_id, etiqueta = e["id"], e["codigo"]
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
    return accesos.listar(conn)


@router.post("/usuarios")
def guardar_usuario(body: UsuarioIn, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    """Alta con enlace de acceso o edición. Ver accesos.guardar."""
    if body.rol not in ROLES:
        raise HTTPException(422, f"rol: {', '.join(ROLES)}")
    email = body.email.strip().lower()
    if "@" not in email or " " in email:
        raise HTTPException(422, "Email inválido")
    if email == u.email and (body.rol != "admin" or not body.activo):
        raise HTTPException(422, "No podés quitarte el rol de administrador ni desactivarte a vos mismo")
    return accesos.guardar(conn, {**body.model_dump(), "email": email,
                                  "nombre": (body.nombre or "").strip() or None}, u.email)


@router.post("/usuarios/{email}/reenviar-acceso")
def reenviar_acceso(email: str, conn=Depends(get_conn), u: Usuario = Depends(requiere("admin"))):
    return accesos.reenviar(conn, email.strip().lower(), u.email)


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


# ── Administradores iniciales (infra/desplegar.sh invitar) ──

class Invitacion(BaseModel):
    forzar: bool = False


@router.post("/jobs/invitar-admins")
def invitar_admins(body: Invitacion, conn=Depends(get_conn), _: str = Depends(requiere_job)):
    """Crea la cuenta de cada email de ADMIN_EMAILS y le manda su enlace (R6). Solo actúa sobre
    ADMIN_EMAILS, así que el token del job no sirve para dar de alta a otras personas."""
    if not settings.ADMIN_EMAILS:
        raise HTTPException(422, "ADMIN_EMAILS está vacía en la configuración de la API")
    return {"resultados": accesos.invitar_admins(conn, body.forzar)}


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
