"""Alta de usuarios con enlace de acceso (SPEC_alta_usuarios_enlace_acceso, R2–R6).

El administrador escribe email, nombre y rol. La API crea la cuenta de Firebase con una clave
aleatoria que nadie conoce (no se guarda, no se devuelve, no se loguea), la marca como
verificada y manda un enlace para que la persona fije su contraseña. Si el correo falla, la
cuenta queda creada y el enlace vuelve en la respuesta para pasarlo por otro canal. El enlace
nunca se guarda en la base, en la auditoría ni en los logs.

Las cuentas se manejan a través de un proveedor: Firebase Admin SDK en producción y uno en
memoria en modo dev y en los tests.
"""
import logging
import secrets
import time
from dataclasses import dataclass, field

from fastapi import HTTPException

from . import auditoria, correo, plantillas, settings

log = logging.getLogger(__name__)
DIAS_CORREO_ENVIO = 90


@dataclass
class Cuenta:
    uid: str
    email: str
    verificada: bool
    deshabilitada: bool
    ultimo_ingreso_ms: int | None  # epoch en milisegundos, como lo da Firebase

    @property
    def nunca_ingreso(self) -> bool:
        return not self.ultimo_ingreso_ms


# ─────────────────────────────────────────────────────────────
# Proveedores de cuentas
# ─────────────────────────────────────────────────────────────

class CuentasFirebase:
    """Firebase Authentication vía Admin SDK. La cuenta de servicio necesita
    roles/firebaseauth.admin para crear cuentas, deshabilitarlas y generar enlaces."""

    def __init__(self):
        from . import auth as auth_api

        from firebase_admin import auth as fb_auth

        self.fb = fb_auth
        self.app = auth_api.firebase_app()

    def _cuenta(self, u) -> Cuenta:
        return Cuenta(u.uid, u.email, bool(u.email_verified), bool(u.disabled),
                      u.user_metadata.last_sign_in_timestamp if u.user_metadata else None)

    def buscar(self, email: str) -> Cuenta | None:
        try:
            return self._cuenta(self.fb.get_user_by_email(email, app=self.app))
        except self.fb.UserNotFoundError:
            return None

    def crear(self, email: str, nombre: str | None, deshabilitada: bool) -> Cuenta:
        u = self.fb.create_user(email=email, password=secrets.token_urlsafe(32), email_verified=True,
                                display_name=nombre or None, disabled=deshabilitada, app=self.app)
        return self._cuenta(u)

    def actualizar(self, uid: str, **cambios) -> None:
        mapa = {"verificada": "email_verified", "deshabilitada": "disabled", "nombre": "display_name"}
        self.fb.update_user(uid, app=self.app, **{mapa[k]: v for k, v in cambios.items()})

    def enlace(self, email: str) -> str:
        ajustes = self.fb.ActionCodeSettings(url=settings.APP_URL)
        return self.fb.generate_password_reset_link(email, ajustes, app=self.app)

    def varias(self, emails: list[str]) -> dict[str, Cuenta]:
        salida = {}
        for i in range(0, len(emails), 100):  # get_users acepta hasta 100 identificadores
            r = self.fb.get_users([self.fb.EmailIdentifier(e) for e in emails[i:i + 100]], app=self.app)
            for u in r.users:
                salida[u.email.lower()] = self._cuenta(u)
        return salida


@dataclass
class CuentasMemoria:
    """Cuentas simuladas para desarrollo local (AUTH_MODE=dev) y tests."""
    cuentas: dict = field(default_factory=dict)

    def buscar(self, email):
        return self.cuentas.get(email)

    def crear(self, email, nombre, deshabilitada):
        c = Cuenta(f"uid-{len(self.cuentas) + 1}", email, True, deshabilitada, None)
        self.cuentas[email] = c
        return c

    def actualizar(self, uid, **cambios):
        for c in self.cuentas.values():
            if c.uid == uid:
                if "verificada" in cambios:
                    c.verificada = cambios["verificada"]
                if "deshabilitada" in cambios:
                    c.deshabilitada = cambios["deshabilitada"]

    def enlace(self, email):
        # Misma forma que el enlace de Firebase, para que la pantalla se vea como en producción
        return (f"{settings.APP_URL}/__/auth/action?mode=resetPassword&oobCode={secrets.token_urlsafe(24)}"
                f"&continueUrl={settings.APP_URL}&lang=es")

    def varias(self, emails):
        return {e: self.cuentas[e] for e in emails if e in self.cuentas}


_proveedor = None


def proveedor():
    global _proveedor
    if _proveedor is None:
        _proveedor = CuentasMemoria() if settings.AUTH_MODE == "dev" else CuentasFirebase()
    return _proveedor


def _cuentas():
    try:
        return proveedor()
    except Exception as e:
        raise HTTPException(502, f"No se pudo conectar con Firebase Authentication: {e}") from e


# ─────────────────────────────────────────────────────────────
# Correo de acceso
# ─────────────────────────────────────────────────────────────

def _registrar_envio(conn, tipo, destinatario, r: correo.Resultado, actor):
    conn.execute(
        "INSERT INTO correo_envio (tipo, destinatario, estado, motivo, intentos, disparado_por)"
        " VALUES (%s,%s,%s,%s,%s,%s)",
        (tipo, destinatario, "enviado" if r.enviado else "fallido", None if r.enviado else r.detalle,
         max(r.intentos, 1), actor))
    conn.execute("DELETE FROM correo_envio WHERE fecha < now() - make_interval(days => %s)", (DIAS_CORREO_ENVIO,))


def enviar_acceso(conn, tipo: str, usuario: dict, actor: str) -> tuple[dict, str | None]:
    """Genera el enlace y manda la plantilla. Devuelve (correo, enlace_si_fallo)."""
    cuentas = _cuentas()
    try:
        enlace = cuentas.enlace(usuario["email"])
    except Exception as e:
        raise HTTPException(502, f"Firebase no generó el enlace de acceso: {e}") from e
    admin = conn.execute("SELECT coalesce(nombre, email) AS n FROM usuario WHERE email = %s", (actor,)).fetchone()
    asunto, cuerpo = plantillas.render(tipo, {
        "nombre": usuario.get("nombre") or usuario["email"].split("@")[0], "email": usuario["email"],
        "rol": plantillas.ROLES_LEGIBLES.get(usuario["rol"], usuario["rol"]), "enlace": enlace,
        "url_app": settings.APP_URL, "admin": admin["n"] if admin else "Un administrador"})
    r = correo.enviar(usuario["email"], asunto, cuerpo)
    _registrar_envio(conn, tipo, usuario["email"], r, actor)
    return {"enviado": r.enviado, "detalle": r.detalle, "tipo": tipo}, (None if r.enviado else enlace)


# ─────────────────────────────────────────────────────────────
# Alta, edición, reenvío
# ─────────────────────────────────────────────────────────────

def guardar(conn, datos: dict, actor: str) -> dict:
    """Alta o edición desde la pantalla Usuarios (R2, R5)."""
    email = datos["email"]
    previo = conn.execute("SELECT * FROM usuario WHERE email = %s", (email,)).fetchone()
    fila = conn.execute(
        "INSERT INTO usuario (email, nombre, rol, exportar_contactos, activo) VALUES (%s,%s,%s,%s,%s)"
        " ON CONFLICT (email) DO UPDATE SET nombre = EXCLUDED.nombre, rol = EXCLUDED.rol,"
        " exportar_contactos = EXCLUDED.exportar_contactos, activo = EXCLUDED.activo RETURNING *",
        (email, datos.get("nombre"), datos["rol"], datos["exportar_contactos"], datos["activo"])).fetchone()
    resp = {"email": email, "correo": {"enviado": False, "detalle": "No se envió correo"}}
    cuentas = _cuentas()
    cuenta = cuentas.buscar(email)
    if previo is not None:
        # Edición: no manda correo. Solo sincroniza activo ↔ cuenta habilitada.
        resp["estado"] = "actualizado"
        if cuenta and cuenta.deshabilitada == fila["activo"]:
            cuentas.actualizar(cuenta.uid, deshabilitada=not fila["activo"])
    elif cuenta is not None:
        # La cuenta ya existía (p. ej. creada a mano en la consola): no se toca la clave.
        resp["estado"] = "ya_existia"
        cambios = {}
        if not cuenta.verificada:
            cambios["verificada"] = True
        if cuenta.deshabilitada == fila["activo"]:
            cambios["deshabilitada"] = not fila["activo"]
        if cambios:
            cuentas.actualizar(cuenta.uid, **cambios)
        resp["mensaje"] = "La cuenta ya existía; usá «Reenviar acceso» si necesita entrar"
    else:
        resp["estado"] = "creado"
        cuentas.crear(email, fila["nombre"], deshabilitada=not fila["activo"])
        if fila["activo"]:
            resp["correo"], enlace = enviar_acceso(conn, "bienvenida", fila, actor)
            if enlace:
                resp["enlace"] = enlace
    auditoria.registrar(conn, actor, "usuario.guardar", "usuario", email,
                        {"rol": fila["rol"], "exportar_contactos": fila["exportar_contactos"], "activo": fila["activo"],
                         "estado": resp["estado"], "correo_enviado": resp["correo"]["enviado"]})
    return resp


def reenviar(conn, email: str, actor: str) -> dict:
    """Reenviar acceso (R4): Bienvenida si nunca ingresó, Restablecer si ya ingresó."""
    fila = conn.execute("SELECT * FROM usuario WHERE email = %s", (email,)).fetchone()
    if fila is None:
        raise HTTPException(404, f"{email} no está dado de alta en Usuarios")
    if not fila["activo"]:
        raise HTTPException(409, "El usuario está desactivado: reactivalo antes de reenviar el acceso")
    cuentas = _cuentas()
    cuenta = cuentas.buscar(email)
    creada = False
    if cuenta is None:
        cuenta = cuentas.crear(email, fila["nombre"], deshabilitada=False)
        creada = True
    else:
        cambios = {"verificada": True} if not cuenta.verificada else {}
        if cuenta.deshabilitada:
            cambios["deshabilitada"] = False
        if cambios:
            cuentas.actualizar(cuenta.uid, **cambios)
    tipo = "bienvenida" if cuenta.nunca_ingreso else "restablecer"
    resp_correo, enlace = enviar_acceso(conn, tipo, fila, actor)
    conn.execute("UPDATE usuario SET reenvios = reenvios + 1, ultimo_reenvio_por = %s, ultimo_reenvio_en = now()"
                 " WHERE email = %s", (actor, email))
    auditoria.registrar(conn, actor, "usuario.reenviar_acceso", "usuario", email,
                        {"tipo": tipo, "cuenta_creada": creada, "correo_enviado": resp_correo["enviado"]})
    resp = {"email": email, "estado": "cuenta_creada" if creada else "reenviado", "correo": resp_correo}
    if enlace:
        resp["enlace"] = enlace
    return resp


def listar(conn) -> list[dict]:
    """Usuarios con su cuenta de Firebase (último ingreso) y el último correo de acceso (R8)."""
    filas = conn.execute(
        """
        SELECT u.*, c.estado AS correo_estado, c.motivo AS correo_motivo, c.fecha AS correo_fecha, c.tipo AS correo_tipo
        FROM usuario u
        LEFT JOIN LATERAL (SELECT * FROM correo_envio e WHERE e.destinatario = u.email ORDER BY e.fecha DESC LIMIT 1) c ON true
        ORDER BY u.activo DESC, u.email
        """).fetchall()
    try:
        cuentas = _cuentas().varias([f["email"] for f in filas])
        error = None
    except Exception as e:  # la lista se muestra igual, sin los datos de Firebase
        log.warning("No se pudieron leer las cuentas de Firebase: %s", e)
        cuentas, error = {}, "No se pudieron leer las cuentas de Firebase"
    for f in filas:
        c = cuentas.get(f["email"])
        f["cuenta"] = None if c is None else {
            "verificada": c.verificada, "deshabilitada": c.deshabilitada,
            "ultimo_ingreso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(c.ultimo_ingreso_ms / 1000))
            if c.ultimo_ingreso_ms else None}
        f["error_cuentas"] = error
    return filas


def invitar_admins(conn, forzar: bool, actor: str = "despliegue") -> list[dict]:
    """Administradores iniciales (R6): crea la cuenta de cada email de ADMIN_EMAILS y le manda
    su enlace. Con forzar=False, una cuenta que ya existe no se toca; con forzar=True se le
    manda un enlace nuevo (Reenviar acceso)."""
    salida = []
    for email in settings.ADMIN_EMAILS:
        fila = conn.execute("SELECT * FROM usuario WHERE email = %s", (email,)).fetchone()
        if fila is None:
            fila = conn.execute("INSERT INTO usuario (email, rol, exportar_contactos) VALUES (%s, 'admin', true)"
                                " RETURNING *", (email,)).fetchone()
            auditoria.registrar(conn, actor, "usuario.guardar", "usuario", email, {"rol": "admin", "estado": "creado"})
        cuenta = _cuentas().buscar(email)
        if cuenta is not None and not forzar:
            if not cuenta.verificada:
                _cuentas().actualizar(cuenta.uid, verificada=True)
            salida.append({"email": email, "estado": "ya_existia",
                           "mensaje": "La cuenta ya existía. Para un enlace nuevo: ./infra/desplegar.sh invitar,"
                                      " o «¿Olvidaste tu contraseña?» en el login"})
            continue
        if not fila["activo"]:
            salida.append({"email": email, "estado": "desactivado",
                           "mensaje": "Está desactivado en Usuarios: reactivalo desde la pantalla Usuarios"})
            continue
        salida.append(reenviar(conn, email, actor))
    return salida
