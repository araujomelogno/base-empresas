"""Autenticación (Firebase Auth) y permisos por rol en el backend (R1.13).

Roles: admin, steward (data steward), jefe (jefe de proyecto), coordinador (coordinador
de campo) y lectura. El administrador puede todo. Los GET están abiertos a todo usuario
activo; las escrituras piden roles explícitos.
"""
import hmac
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request

from . import settings
from .db import get_conn

ROLES = ("admin", "steward", "jefe", "coordinador", "lectura")


@dataclass
class Usuario:
    id: int
    email: str
    nombre: str | None
    rol: str
    exportar_contactos: bool

    def puede(self, *roles: str) -> bool:
        return self.rol == "admin" or self.rol in roles


_firebase_app = None


def _verificar_token_firebase(token: str) -> str:
    global _firebase_app
    import firebase_admin
    from firebase_admin import auth as fb_auth

    if _firebase_app is None:
        opciones = {"projectId": settings.FIREBASE_PROJECT_ID} if settings.FIREBASE_PROJECT_ID else None
        _firebase_app = firebase_admin.initialize_app(options=opciones)
    try:
        datos = fb_auth.verify_id_token(token, app=_firebase_app)
    except Exception as e:  # token vencido, firma inválida, etc.
        raise HTTPException(401, f"Token inválido: {e}") from e
    email = (datos.get("email") or "").lower()
    if not email or not datos.get("email_verified", True):
        raise HTTPException(401, "El usuario no tiene email verificado")
    return email


def _email_de_request(request: Request) -> str:
    if settings.AUTH_MODE == "dev":
        email = request.headers.get("X-Dev-User", "").lower()
        if not email:
            raise HTTPException(401, "Falta X-Dev-User (modo dev)")
        return email
    authz = request.headers.get("Authorization", "")
    if not authz.startswith("Bearer "):
        raise HTTPException(401, "Falta el token de Firebase")
    return _verificar_token_firebase(authz[7:])


def usuario_actual(request: Request, conn=Depends(get_conn)) -> Usuario:
    email = _email_de_request(request)
    row = conn.execute("SELECT * FROM usuario WHERE email = %s", (email,)).fetchone()
    if row is None and email in settings.ADMIN_EMAILS:
        row = conn.execute(
            "INSERT INTO usuario (email, rol, exportar_contactos) VALUES (%s, 'admin', true) RETURNING *",
            (email,),
        ).fetchone()
    if row is None or not row["activo"]:
        raise HTTPException(403, f"{email} no tiene acceso a la Base de Empresas")
    return Usuario(row["id"], row["email"], row["nombre"], row["rol"], row["exportar_contactos"])


def requiere(*roles: str):
    """Dependencia: el usuario debe tener alguno de los roles (admin siempre pasa)."""

    def dep(u: Usuario = Depends(usuario_actual)) -> Usuario:
        if not u.puede(*roles):
            raise HTTPException(403, f"Esta acción requiere rol: {', '.join(roles)}")
        return u

    return dep


def _comparar(dado: str | None, esperado: str) -> bool:
    return bool(esperado) and bool(dado) and hmac.compare_digest(dado, esperado)


def requiere_job(x_job_token: str | None = Header(default=None)) -> str:
    """El job nocturno del CDR se autentica con un token compartido (Secret Manager)."""
    if not _comparar(x_job_token, settings.JOB_TOKEN):
        raise HTTPException(401, "Token de job inválido")
    return "job:cdr"


def requiere_tarea(x_tarea_token: str | None = Header(default=None)) -> str:
    if not _comparar(x_tarea_token, settings.TAREA_TOKEN):
        raise HTTPException(401, "Token de tarea inválido")
    return "cloud-tasks"
