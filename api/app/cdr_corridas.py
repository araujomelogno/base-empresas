"""Corridas del job del CDR: "Correr ahora", "Reprocesar desde…", estado para la pantalla de
inicio y la contraseña de MySQL (SPEC_job_cdr_en_cloud, R2, R5 y R6).

En producción, "Correr ahora" ejecuta el Cloud Run job `empresas-cdr` con argumentos
(run_job con overrides). Sin CDR_JOB (desarrollo local, tests) corre el job en el mismo proceso.
"""
import datetime as dt
import logging
import threading

from fastapi import HTTPException

from . import auditoria, cdr_mysql, config, secretos, settings
from .db import conexion

log = logging.getLogger(__name__)
HORAS_INTERRUMPIDA = 2   # una corrida "en curso" más vieja que esto se considera interrumpida
HORAS_SIN_CORRIDA = 26   # aviso en la pantalla de inicio


def cerrar_interrumpidas(conn):
    conn.execute(
        "UPDATE cdr_corrida SET estado = 'error', fin = now(), mensaje = 'La corrida no terminó (se interrumpió)'"
        " WHERE estado = 'en_curso' AND inicio < now() - make_interval(hours => %s)", (HORAS_INTERRUMPIDA,))


def lanzar(conn, actor: str, desde: dt.date | None, hasta: dt.date | None, dry_run: bool) -> int:
    """Crea la corrida "manual". Hay que llamar a despachar() después del commit."""
    if hasta and not desde:
        raise HTTPException(422, "Para reprocesar indicá la fecha desde")
    if desde and hasta and hasta <= desde:
        raise HTTPException(422, "La fecha hasta tiene que ser posterior a la fecha desde")
    conn.execute("SELECT pg_advisory_xact_lock(727002)")  # dos clics simultáneos no lanzan dos corridas
    cerrar_interrumpidas(conn)
    en_curso = conn.execute("SELECT id FROM cdr_corrida WHERE estado = 'en_curso' LIMIT 1").fetchone()
    if en_curso:
        raise HTTPException(409, f"Ya hay una corrida del CDR en curso (#{en_curso['id']}): esperá a que termine")
    from .jobs import cdr_job

    corrida_id = cdr_job.crear_corrida(conn, "manual", actor, desde, hasta, dry_run)
    auditoria.registrar(conn, actor, "cdr.correr", "cdr_corrida", corrida_id,
                        {"desde": desde, "hasta": hasta, "dry_run": dry_run})
    return corrida_id


def argumentos(corrida_id: int, desde, hasta, dry_run) -> list[str]:
    args = ["--corrida", str(corrida_id)]
    if desde:
        args += ["--desde", str(desde)]
    if hasta:
        args += ["--hasta", str(hasta)]
    if dry_run:
        args.append("--dry-run")
    return args


def despachar(corrida_id: int, args: list[str]) -> None:
    if settings.CDR_JOB:
        try:
            _ejecutar_cloud_run(args)
        except Exception as e:
            log.error("No se pudo ejecutar el Cloud Run job del CDR: %s", e)
            with conexion() as c:
                c.execute("UPDATE cdr_corrida SET estado = 'error', fin = now(), mensaje = %s WHERE id = %s",
                          (f"No se pudo lanzar el Cloud Run job {settings.CDR_JOB}: {type(e).__name__}", corrida_id))
            raise HTTPException(502, "No se pudo lanzar el job del CDR en Cloud Run. Revisá los permisos de la"
                                     " cuenta de servicio sobre el job (ver docs/despliegue.md).") from e
        return
    from .jobs import cdr_job

    if settings.TASKS_MODE == "inline":
        cdr_job.main(args)
    else:
        threading.Thread(target=cdr_job.main, args=(args,), daemon=True).start()


def _ejecutar_cloud_run(args: list[str]) -> None:
    from google.cloud import run_v2

    nombre = settings.CDR_JOB
    if "/" not in nombre:
        nombre = f"projects/{settings.GCP_PROYECTO}/locations/{settings.GCP_REGION}/jobs/{nombre}"
    pedido = run_v2.RunJobRequest(
        name=nombre,
        overrides=run_v2.RunJobRequest.Overrides(container_overrides=[
            run_v2.RunJobRequest.Overrides.ContainerOverride(args=["-m", "app.jobs.cdr_job", *args])]))
    run_v2.JobsClient().run_job(request=pedido)  # no se espera a que termine: la corrida se sigue en la base


def corridas(conn, limite: int = 30) -> list[dict]:
    cerrar_interrumpidas(conn)
    return conn.execute("SELECT * FROM cdr_corrida ORDER BY id DESC LIMIT %s", (limite,)).fetchall()


def corrida(conn, corrida_id: int) -> dict:
    r = conn.execute("SELECT * FROM cdr_corrida WHERE id = %s", (corrida_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "Corrida inexistente")
    return r


def resumen(conn) -> dict:
    """Para la pantalla de inicio: última corrida y si hay que avisar (R5)."""
    _, params = config.vigente(conn)
    activo = config.cdr(params)["activo"]
    cerrar_interrumpidas(conn)
    ultima = conn.execute("SELECT * FROM cdr_corrida ORDER BY id DESC LIMIT 1").fetchone()
    programada = conn.execute("SELECT * FROM cdr_corrida WHERE origen = 'programada' ORDER BY id DESC LIMIT 1").fetchone()
    reciente = conn.execute(
        "SELECT 1 FROM cdr_corrida WHERE estado <> 'omitida' AND inicio > now() - make_interval(hours => %s) LIMIT 1",
        (HORAS_SIN_CORRIDA,)).fetchone()
    aviso = None
    if activo:
        if programada and programada["estado"] == "error":
            aviso = f"La última corrida programada del CDR falló: {programada['mensaje'] or 'sin detalle'}"
        elif not reciente:
            aviso = f"No hubo ninguna corrida del CDR en las últimas {HORAS_SIN_CORRIDA} horas"
    return {"activo": activo, "ultima": ultima, "aviso": aviso}


# ─── Contraseña de MySQL ───

def estado_password(conn) -> dict:
    ultimo = conn.execute("SELECT actor, fecha FROM auditoria WHERE accion = 'config.cdr_password'"
                          " ORDER BY id DESC LIMIT 1").fetchone()
    configurada = bool(secretos.leer_cdr())
    return {"configurada": configurada, "fecha": ultimo["fecha"] if ultimo and configurada else None,
            "por": ultimo["actor"] if ultimo and configurada else None}


def guardar_password(conn, valor: str, actor: str) -> dict:
    if not valor or not valor.strip():
        raise HTTPException(422, "La contraseña está vacía")
    secretos.guardar_cdr(valor)
    auditoria.registrar(conn, actor, "config.cdr_password", "config", "cdr", {"secreto": settings.CDR_SECRETO})
    return estado_password(conn)


def probar(conn, parametros: dict | None, password: str | None) -> dict:
    """Prueba con los parámetros del formulario (aunque no estén guardados) y la contraseña
    escrita o, si no se escribió, la guardada."""
    if parametros is None:
        _, params = config.vigente(conn)
        parametros = params.get("cdr") or {}
    try:
        p = config.ConfigCdr.model_validate({**parametros, "activo": False}).model_dump()
    except Exception as e:
        raise HTTPException(422, f"Parámetros del CDR inválidos: {e}") from e
    faltan = [c for c in ("host", "base", "usuario") if not p[c]]
    if faltan:
        raise HTTPException(422, f"Completá: {', '.join(faltan)}")
    clave = password or secretos.leer_cdr()
    if not clave:
        raise HTTPException(422, "Escribí la contraseña: todavía no hay una guardada")
    return cdr_mysql.probar(p, clave)
