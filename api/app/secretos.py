"""Secretos que se cargan desde la aplicación (SPEC_job_cdr_en_cloud, R2).

Hoy, solo la contraseña de MySQL del CDR. Guardarla agrega una versión nueva del secreto en
Secret Manager y deshabilita las anteriores. La API nunca la devuelve: la pantalla solo ve
si está configurada, cuándo y quién la cambió (de la auditoría). En desarrollo local y en los
tests los secretos viven en memoria.
"""
import logging

from fastapi import HTTPException

from . import settings

log = logging.getLogger(__name__)


class SecretosMemoria:
    def __init__(self):
        self.valores: dict[str, str] = {}

    def leer(self, nombre: str) -> str | None:
        return self.valores.get(nombre)

    def guardar(self, nombre: str, valor: str) -> None:
        self.valores[nombre] = valor


class SecretManager:
    """La cuenta de servicio necesita secretAccessor y secretVersionManager sobre el secreto."""

    def __init__(self):
        from google.cloud import secretmanager

        self.cliente = secretmanager.SecretManagerServiceClient()
        self.proyecto = settings.GCP_PROYECTO

    def _ruta(self, nombre):
        return f"projects/{self.proyecto}/secrets/{nombre}"

    def leer(self, nombre):
        from google.api_core import exceptions

        try:
            r = self.cliente.access_secret_version(name=f"{self._ruta(nombre)}/versions/latest")
        except (exceptions.NotFound, exceptions.FailedPrecondition):
            return None  # el secreto no existe o no tiene ninguna versión habilitada
        return r.payload.data.decode("utf-8")

    def guardar(self, nombre, valor):
        from google.cloud import secretmanager

        nueva = self.cliente.add_secret_version(parent=self._ruta(nombre), payload={"data": valor.encode("utf-8")})
        habilitada = secretmanager.SecretVersion.State.ENABLED
        for v in self.cliente.list_secret_versions(parent=self._ruta(nombre)):
            if v.name != nueva.name and v.state == habilitada:
                self.cliente.disable_secret_version(name=v.name)


_proveedor = None


def proveedor():
    global _proveedor
    if _proveedor is None:
        _proveedor = SecretManager() if settings.SECRETOS == "secretmanager" else SecretosMemoria()
    return _proveedor


def leer_cdr() -> str | None:
    try:
        return proveedor().leer(settings.CDR_SECRETO)
    except Exception as e:
        raise HTTPException(502, f"No se pudo leer el secreto {settings.CDR_SECRETO}: {type(e).__name__}") from e


def guardar_cdr(valor: str) -> None:
    try:
        proveedor().guardar(settings.CDR_SECRETO, valor)
    except Exception as e:
        # el mensaje de la excepción no incluye el valor, pero por las dudas no se reenvía
        log.error("No se pudo guardar el secreto %s: %s", settings.CDR_SECRETO, type(e).__name__)
        raise HTTPException(502, f"No se pudo guardar la contraseña en Secret Manager ({type(e).__name__})."
                                 " Revisá los permisos de la cuenta de servicio sobre el secreto.") from e
