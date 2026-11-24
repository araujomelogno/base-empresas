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
# D55 (P-5): tiempo máximo de cada consulta de la web (statement_timeout, en ms); 0 sin límite. El servicio de tareas y
# el job del CDR van con 0 (infra/desplegar.sh); las tareas, los jobs y las descargas lo levantan igual (db.sin_limite).
DB_STATEMENT_TIMEOUT_MS = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "15000"))
# Cuánto espera un pedido por una conexión libre del pool antes de responder «La base está ocupada» (503)
DB_POOL_TIMEOUT = float(os.environ.get("DB_POOL_TIMEOUT", "10"))
# P-6: los pedidos que tardan más que esto quedan en el log (endpoint, duración y usuario)
PEDIDO_LENTO_SEGUNDOS = float(os.environ.get("PEDIDO_LENTO_SEGUNDOS", "2"))
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
# Claves de API del enriquecimiento (SPEC_fase2_enriquecimiento, B1): se cargan desde Configuración → Enriquecimiento
# y nunca se muestran. Un secreto por proveedor.
SECRETOS_PROVEEDORES = {
    "google_places": os.environ.get("PLACES_SECRETO", "empresas-places-key"),
    "brave": os.environ.get("BRAVE_SECRETO", "empresas-brave-key"),
    "claude": os.environ.get("ANTHROPIC_SECRETO", "empresas-anthropic-key"),
}
# simulado: los proveedores responden con datos de ejemplo, sin llamadas pagas (demo local). real: APIs de verdad.
PROVEEDORES_MODO = os.environ.get("PROVEEDORES_MODO", "real")
# Cargas por lotes (D50): solo para tests y pruebas locales; en producción manda la configuración (Configuración → Cargas)
CARGAS_TAMANO_LOTE = int(os.environ["CARGAS_TAMANO_LOTE"]) if os.environ.get("CARGAS_TAMANO_LOTE") else None
CARGAS_PAUSA = float(os.environ["CARGAS_PAUSA"]) if os.environ.get("CARGAS_PAUSA") else None
# D51: un archivo de más de 10 MB o de más de 20.000 filas (estimadas sin parsearlo) se lee en segundo plano
ARCHIVO_BYTES_SINCRONICO = int(os.environ.get("ARCHIVO_BYTES_SINCRONICO", 10 * 1024 * 1024))
ARCHIVO_FILAS_SINCRONICO = int(os.environ.get("ARCHIVO_FILAS_SINCRONICO", 20000))
# D52: latido de una tarea que corre, y cuánto sin latido para darla por muerta y retomarla
TAREA_LATIDO_SEGUNDOS = float(os.environ.get("TAREA_LATIDO_SEGUNDOS", 30))
TAREA_RETOMAR_SEGUNDOS = int(os.environ.get("TAREA_RETOMAR_SEGUNDOS", 180))
# Límite de memoria de la instancia (para avisar en el log si un lote pasa del 75 %); si no, el del cgroup
MEMORIA_LIMITE_MB = int(os.environ["MEMORIA_LIMITE_MB"]) if os.environ.get("MEMORIA_LIMITE_MB") else None
# URL del servicio de Cloud Run que ejecuta las tareas (empresas-tareas); si no, la de la API
TAREAS_URL = os.environ.get("TAREAS_URL", "")
# D53: filas por tanda dentro de un lote (pocas consultas por tanda); CARGAS_POR_FILA=1 vuelve al algoritmo anterior
CARGAS_TANDA = int(os.environ.get("CARGAS_TANDA", 500))
CARGAS_POR_FILA = os.environ.get("CARGAS_POR_FILA") == "1"
