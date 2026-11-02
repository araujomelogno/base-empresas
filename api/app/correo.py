"""Envío de correos por el SMTP de Google Workspace (R7 de SPEC_alta_usuarios_enlace_acceso).

Sale desde notificaciones@equipos.com.uy con STARTTLS en smtp.gmail.com:587. Reintenta solo
los errores transitorios (conexión, 4xx) y nunca incluye la contraseña en mensajes ni logs.
El correo es una comodidad: quien llama decide qué hacer si no salió (mostrar el enlace).
"""
import logging
import smtplib
import socket
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from . import settings

log = logging.getLogger(__name__)

INTENTOS = 3
ESPERA_S = 2


@dataclass
class Resultado:
    enviado: bool
    detalle: str
    intentos: int


class _Permanente(Exception):
    """Error que no se arregla reintentando (credencial, destinatario)."""


def _limpiar(texto: str) -> str:
    """Saca la contraseña de cualquier texto que vaya a mostrarse o guardarse."""
    if settings.SMTP_PASSWORD:
        texto = texto.replace(settings.SMTP_PASSWORD, "***")
    return texto


def _motivo(e: Exception) -> tuple[str, bool]:
    """Traduce el error a un motivo legible. Devuelve (motivo, es_permanente)."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "Workspace rechazó la credencial: revisar la contraseña de aplicación (empresas-smtp-password)", True
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "El servidor de correo rechazó la dirección del destinatario", True
    if isinstance(e, smtplib.SMTPSenderRefused):
        return "El servidor de correo rechazó el remitente", True
    if isinstance(e, smtplib.SMTPResponseException):
        codigo = e.smtp_code
        texto = e.smtp_error.decode("utf-8", "replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        return f"El servidor de correo respondió {codigo}: {_limpiar(texto)[:200]}", 500 <= codigo < 600
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "El servidor de correo no respondió a tiempo", False
    if isinstance(e, (ConnectionError, OSError, smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)):
        return "No se pudo conectar con el servidor de correo", False
    return f"Error al enviar el correo: {_limpiar(str(e))[:200]}", True


def _mandar(destinatario: str, asunto: str, cuerpo: str):
    msg = EmailMessage()
    msg["From"] = formataddr((settings.SMTP_NOMBRE, settings.SMTP_USUARIO))
    msg["To"] = destinatario
    msg["Subject"] = asunto
    msg["Message-ID"] = make_msgid(domain=settings.SMTP_USUARIO.split("@")[-1])
    msg.set_content(cuerpo)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as s:
        s.starttls()
        s.login(settings.SMTP_USUARIO, settings.SMTP_PASSWORD)
        s.send_message(msg)


def enviar(destinatario: str, asunto: str, cuerpo: str) -> Resultado:
    if not settings.SMTP_PASSWORD:
        return Resultado(False, "El envío de correos no está configurado (falta SMTP_PASSWORD)", 0)
    ultimo = ""
    for intento in range(1, INTENTOS + 1):
        try:
            _mandar(destinatario, asunto, cuerpo)
            return Resultado(True, "Enviado", intento)
        except Exception as e:  # se clasifica y se reintenta solo si es transitorio
            ultimo, permanente = _motivo(e)
            log.warning("Correo a %s falló (intento %s): %s", destinatario, intento, ultimo)
            if permanente:
                return Resultado(False, ultimo, intento)
            if intento < INTENTOS:
                time.sleep(ESPERA_S * intento)
    return Resultado(False, ultimo, INTENTOS)
