#!/usr/bin/env bash
# Despliegue de la Base de Empresas en un proyecto de GCP propio (ver docs/despliegue.md).
#
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh todo        # primera vez
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh api         # nueva versión de la API
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh migrar      # aplicar migraciones
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh web         # nueva versión de la web
#   PROYECTO=equipos-base-empresas TIER=db-g1-small ./infra/desplegar.sh redimensionar
#                                                                  # cambiar el tamaño de Cloud SQL (docs/cambio_a_small.md)
#
# Se puede correr de nuevo sin romper nada: los "create" que ya existen se saltean.
set -euo pipefail

: "${PROYECTO:?Definí PROYECTO (id del proyecto de GCP)}"
REGION="${REGION:-us-central1}"          # Iowa: región decidida para todo el sistema
# Tamaño de Cloud SQL. Se arranca con db-f1-micro (núcleo compartido, 0,6 GB, 25 conexiones);
# el paso siguiente es db-g1-small (docs/cambio_a_small.md). Si no se indica, se usa el de la
# instancia existente, o db-f1-micro al crearla.
TIER="${TIER:-}"
DISCO_GB="${DISCO_GB:-10}"
INSTANCIA="${INSTANCIA:-empresas-pg}"
DB="${DB:-empresas}"
DB_USUARIO="${DB_USUARIO:-empresas_app}"
SERVICIO="${SERVICIO:-empresas-api}"
COLA="${COLA:-empresas-tareas}"
BUCKET="${BUCKET:-${PROYECTO}-empresas-archivos}"
REPO="${REPO:-empresas}"
SA="empresas-api@${PROYECTO}.iam.gserviceaccount.com"
IMAGEN="${REGION}-docker.pkg.dev/${PROYECTO}/${REPO}/api:$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)"
CONEXION="${PROYECTO}:${REGION}:${INSTANCIA}"
ADMIN_EMAILS="${ADMIN_EMAILS:-}"

g() { gcloud --project "$PROYECTO" "$@"; }

# Conexiones por instancia de la API y máximo de instancias de Cloud Run según el tamaño de
# Cloud SQL, dejando margen para las 3 conexiones reservadas y el job de migraciones.
limites() {
  if [ -z "$TIER" ]; then
    TIER="$(g sql instances describe "$INSTANCIA" --format 'value(settings.tier)' 2>/dev/null || true)"
    TIER="${TIER:-db-f1-micro}"
  fi
  case "$TIER" in
    db-f1-micro) POOL=5; INSTANCIAS=3 ;;     # 25 conexiones: 3 × 5 = 15
    db-g1-small) POOL=8; INSTANCIAS=4 ;;     # 50 conexiones: 4 × 8 = 32
    *) POOL=10; INSTANCIAS=4 ;;              # 100 o más
  esac
}
existe() { "$@" >/dev/null 2>&1; }
secreto() {  # secreto NOMBRE VALOR — crea el secreto o agrega una versión
  if existe g secrets describe "$1"; then printf '%s' "$2" | g secrets versions add "$1" --data-file=-;
  else printf '%s' "$2" | g secrets create "$1" --replication-policy=automatic --data-file=-; fi
}

base() {
  echo "▶ APIs"
  g services enable run.googleapis.com sqladmin.googleapis.com cloudtasks.googleapis.com secretmanager.googleapis.com \
    cloudbuild.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com bigquery.googleapis.com \
    storage.googleapis.com firebase.googleapis.com identitytoolkit.googleapis.com

  echo "▶ Cuenta de servicio de la API"
  existe g iam service-accounts describe "$SA" || g iam service-accounts create empresas-api --display-name "Base de Empresas API"
  for rol in roles/cloudsql.client roles/secretmanager.secretAccessor roles/cloudtasks.enqueuer roles/bigquery.dataEditor \
             roles/bigquery.jobUser; do
    g projects add-iam-policy-binding "$PROYECTO" --member "serviceAccount:$SA" --role "$rol" --condition=None >/dev/null
  done

  limites
  echo "▶ Cloud SQL (Postgres 16, ${TIER}, ${DISCO_GB} GB SSD, backups diarios)"
  existe g sql instances describe "$INSTANCIA" || g sql instances create "$INSTANCIA" --database-version=POSTGRES_16 \
    --edition=ENTERPRISE --tier="$TIER" --region="$REGION" --storage-size="$DISCO_GB" --storage-type=SSD \
    --storage-auto-increase --backup-start-time=06:00 --enable-point-in-time-recovery --retained-backups-count=14
  existe g sql databases describe "$DB" --instance "$INSTANCIA" || g sql databases create "$DB" --instance "$INSTANCIA"
  if ! existe g secrets describe empresas-database-url; then
    CLAVE="$(openssl rand -base64 24 | tr -d '/+=')"
    g sql users create "$DB_USUARIO" --instance "$INSTANCIA" --password "$CLAVE"
    secreto empresas-database-url "postgresql://${DB_USUARIO}:${CLAVE}@/${DB}?host=/cloudsql/${CONEXION}"
  fi
  existe g secrets describe empresas-job-token || secreto empresas-job-token "$(openssl rand -hex 32)"
  existe g secrets describe empresas-tarea-token || secreto empresas-tarea-token "$(openssl rand -hex 32)"

  echo "▶ Bucket de archivos subidos (privado)"
  existe gcloud storage buckets describe "gs://$BUCKET" || gcloud storage buckets create "gs://$BUCKET" --project "$PROYECTO" \
    --location "$REGION" --uniform-bucket-level-access --public-access-prevention
  gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$SA" --role roles/storage.objectAdmin >/dev/null

  echo "▶ Cola de Cloud Tasks"
  existe g tasks queues describe "$COLA" --location "$REGION" || g tasks queues create "$COLA" --location "$REGION" \
    --max-concurrent-dispatches=2 --max-attempts=3 --min-backoff=30s

  echo "▶ BigQuery (export diario de auditoría)"
  existe bq --project_id "$PROYECTO" show empresas_auditoria || bq --project_id "$PROYECTO" --location=US mk -d empresas_auditoria
  existe bq --project_id "$PROYECTO" show empresas_auditoria.auditoria || bq --project_id "$PROYECTO" mk -t \
    --time_partitioning_field fecha empresas_auditoria.auditoria \
    id:INTEGER,actor:STRING,accion:STRING,objeto:STRING,objeto_id:STRING,detalle:STRING,fecha:TIMESTAMP

  echo "▶ Artifact Registry"
  existe g artifacts repositories describe "$REPO" --location "$REGION" || g artifacts repositories create "$REPO" \
    --repository-format=docker --location "$REGION"
}

api() {
  limites
  echo "▶ Imagen $IMAGEN"
  g builds submit --tag "$IMAGEN" .
  local url
  url="$(g run services describe "$SERVICIO" --region "$REGION" --format 'value(status.url)' 2>/dev/null || true)"
  echo "▶ Cloud Run $SERVICIO"
  g run deploy "$SERVICIO" --image "$IMAGEN" --region "$REGION" --service-account "$SA" \
    --add-cloudsql-instances "$CONEXION" --allow-unauthenticated --memory 1Gi --cpu 1 --timeout 1800 \
    --min-instances 0 --max-instances "$INSTANCIAS" --concurrency 20 \
    --set-env-vars "DB_POOL_MAX=${POOL},AUTH_MODE=firebase,FIREBASE_PROJECT_ID=${PROYECTO},TASKS_MODE=cloudtasks,TASKS_QUEUE=projects/${PROYECTO}/locations/${REGION}/queues/${COLA},STORAGE_BUCKET=${BUCKET},BQ_TABLA_AUDITORIA=${PROYECTO}.empresas_auditoria.auditoria,ADMIN_EMAILS=${ADMIN_EMAILS},API_URL=${url}" \
    --set-secrets "DATABASE_URL=empresas-database-url:latest,JOB_TOKEN=empresas-job-token:latest,TAREA_TOKEN=empresas-tarea-token:latest"
  if [ -z "$url" ]; then  # primera vez: la URL recién existe después del deploy
    url="$(g run services describe "$SERVICIO" --region "$REGION" --format 'value(status.url)')"
    g run services update "$SERVICIO" --region "$REGION" --update-env-vars "API_URL=${url}"
  fi
  echo "API en $url"
}

migrar() {
  echo "▶ Migraciones (Cloud Run job con la misma imagen)"
  local imagen
  imagen="$(g run services describe "$SERVICIO" --region "$REGION" --format 'value(spec.template.spec.containers[0].image)')"
  g run jobs deploy empresas-migrar --image "$imagen" --region "$REGION" --service-account "$SA" \
    --set-cloudsql-instances "$CONEXION" --set-secrets "DATABASE_URL=empresas-database-url:latest" \
    --command python --args /srv/db/migrate.py --max-retries 0
  g run jobs execute empresas-migrar --region "$REGION" --wait
}

web() {
  echo "▶ Firebase Hosting"
  (cd web && firebase deploy --only hosting --project "$PROYECTO")
}

redimensionar() {
  : "${TIER:?Indicá el tamaño nuevo: TIER=db-g1-small}"
  # Cambia el tamaño de la instancia existente (reinicio de unos minutos, sin migrar datos)
  # y ajusta el pool de conexiones y las instancias de la API al nuevo tamaño.
  limites
  local actual
  actual="$(g sql instances describe "$INSTANCIA" --format 'value(settings.tier)')"
  echo "▶ Cloud SQL: ${actual} → ${TIER} (la base se reinicia y queda sin servicio unos minutos)"
  if [ "$actual" != "$TIER" ]; then
    g sql backups create --instance "$INSTANCIA" --description "antes de pasar a ${TIER}"
    g sql instances patch "$INSTANCIA" --tier "$TIER" --quiet
  fi
  echo "▶ API: DB_POOL_MAX=${POOL}, hasta ${INSTANCIAS} instancias"
  g run services update "$SERVICIO" --region "$REGION" --max-instances "$INSTANCIAS" --update-env-vars "DB_POOL_MAX=${POOL}"
  g sql instances describe "$INSTANCIA" --format 'value(settings.tier,state)'
}

programar() {
  echo "▶ Cloud Scheduler: export de auditoría a BigQuery todos los días a las 5:10"
  local url token
  url="$(g run services describe "$SERVICIO" --region "$REGION" --format 'value(status.url)')"
  token="$(g secrets versions access latest --secret empresas-job-token)"
  existe g scheduler jobs describe empresas-auditoria-bq --location "$REGION" && \
    g scheduler jobs delete empresas-auditoria-bq --location "$REGION" --quiet
  g scheduler jobs create http empresas-auditoria-bq --location "$REGION" --schedule "10 5 * * *" \
    --time-zone "America/Montevideo" --uri "${url}/api/jobs/auditoria-bq" --http-method POST \
    --headers "X-Job-Token=${token}"
}

case "${1:-}" in
  base) base ;;
  api) api ;;
  migrar) migrar ;;
  web) web ;;
  programar) programar ;;
  redimensionar) redimensionar ;;
  todo) base; api; migrar; programar; web ;;
  *) echo "uso: PROYECTO=... $0 {todo|base|api|migrar|web|programar|redimensionar}"; exit 1 ;;
esac
