"""Configuración de despliegue leída de variables de entorno.

Los parámetros de negocio (umbral de intermediario, enfriamiento, etc.) NO van acá:
viven en la tabla config_version y se editan desde la pantalla de configuración.
"""
import os


def _lista(nombre: str) -> list[str]:
    return [x.strip() for x in os.environ.get(nombre, "").split(",") if x.strip()]


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres@localhost/empresas_dev")
# firebase: valida el ID token de Firebase Auth. dev: confía en el header X-Dev-User (solo local).
AUTH_MODE = os.environ.get("AUTH_MODE", "firebase")
FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID")
# Emails que quedan como administradores la primera vez que entran (arranque del sistema).
ADMIN_EMAILS = [e.lower() for e in _lista("ADMIN_EMAILS")]
# Token compartido con el job del CDR (servidor Ubuntu) y con Cloud Tasks.
JOB_TOKEN = os.environ.get("JOB_TOKEN", "")
TAREA_TOKEN = os.environ.get("TAREA_TOKEN", "")
# Archivos subidos: bucket de Cloud Storage o carpeta local.
STORAGE_BUCKET = os.environ.get("STORAGE_BUCKET")
STORAGE_DIR = os.environ.get("STORAGE_DIR", "/tmp/base-empresas-archivos")
# Tareas diferidas: inline (tests), background (local) o cloudtasks (producción).
TASKS_MODE = os.environ.get("TASKS_MODE", "background")
TASKS_QUEUE = os.environ.get("TASKS_QUEUE")  # projects/P/locations/L/queues/Q
API_URL = os.environ.get("API_URL", "")
CORS_ORIGINS = _lista("CORS_ORIGINS")
BQ_TABLA_AUDITORIA = os.environ.get("BQ_TABLA_AUDITORIA")  # proyecto.dataset.tabla
TZ = os.environ.get("APP_TZ", "America/Montevideo")
