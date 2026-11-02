"""Configuración de despliegue leída de variables de entorno.

Los parámetros de negocio (umbral de intermediario, enfriamiento, etc.) NO van acá:
viven en la tabla config_version y se editan desde la pantalla de configuración.
"""
import os


def _lista(nombre: str) -> list[str]:
    return [x.strip() for x in os.environ.get(nombre, "").split(",") if x.strip()]


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres@localhost/empresas_dev")
# Conexiones por instancia de Cloud Run. Con db-f1-micro (25 conexiones en total) va 5 y
# Cloud Run con máximo 3 instancias; ver docs/cambio_a_small.md.
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "10"))
# firebase: valida el ID token de Firebase Auth. dev: confía en el header X-Dev-User (solo local).
AUTH_MODE = os.environ.get("AUTH_MODE", "firebase")
FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID")
# Emails que quedan como administradores la primera vez que entran (arranque del sistema).
ADMIN_EMAILS = [e.lower() for e in _lista("ADMIN_EMAILS")]
# Correo de acceso por SMTP de Google Workspace (SPEC alta de usuarios). La clave es una
# contraseña de aplicación exclusiva de este proyecto (Secret Manager: empresas-smtp-password).
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USUARIO = os.environ.get("SMTP_USUARIO", "notificaciones@equipos.com.uy")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_NOMBRE = os.environ.get("SMTP_NOMBRE", "Equipos Consultores")
# URL de la web (Firebase Hosting): destino del enlace de acceso y {{url_app}} en los correos.
APP_URL = os.environ.get("APP_URL", "http://localhost:8080")
# Token compartido para los jobs que llaman a la API (export de auditoría, invitación de
# administradores) y token de Cloud Tasks.
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
# Proyecto y región de Google Cloud (Secret Manager y el Cloud Run job del CDR).
GCP_PROYECTO = os.environ.get("GCP_PROYECTO") or FIREBASE_PROJECT_ID
GCP_REGION = os.environ.get("GCP_REGION", "us-central1")
# Secretos: Secret Manager en producción; en memoria en desarrollo local y tests.
SECRETOS = os.environ.get("SECRETOS", "secretmanager" if AUTH_MODE == "firebase" else "memoria")
# Contraseña de MySQL del CDR (la conexión se configura en la pantalla Configuración).
CDR_SECRETO = os.environ.get("CDR_SECRETO", "empresas-cdr-mysql-password")
# Cloud Run job que lee el CDR. Vacío: "Correr ahora" ejecuta el job en el mismo proceso (desarrollo, tests).
CDR_JOB = os.environ.get("CDR_JOB", "")
