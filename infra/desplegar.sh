#!/usr/bin/env bash
# Despliegue de la Base de Empresas en un proyecto de GCP propio (ver docs/despliegue.md).
#
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh todo        # primera vez
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh api         # nueva versión de la API
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh migrar      # aplicar migraciones
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh web         # nueva versión de la web
#   PROYECTO=equipos-base-empresas TIER=db-g1-small ./infra/desplegar.sh redimensionar
#                                                                  # cambiar el tamaño de Cloud SQL (docs/cambio_a_small.md)
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh invitar     # enlace de acceso nuevo para ADMIN_EMAILS
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh cdr         # job del CDR (Cloud Run job + Scheduler)
#   PROYECTO=equipos-base-empresas IP_FIJA=1 ./infra/desplegar.sh cdr  # ídem, con IP de salida fija
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
# Correo de acceso (alta de usuarios con enlace): SMTP de Google Workspace y URL de la web
APP_URL="${APP_URL:-https://${PROYECTO}.web.app}"
SMTP_USUARIO="${SMTP_USUARIO:-notificaciones@equipos.com.uy}"
SMTP_HOST="${SMTP_HOST:-smtp.gmail.com}"
SMTP_PORT="${SMTP_PORT:-587}"
# Job del CDR: Cloud Run job con la misma imagen de la API, todos los días a las 4:00 de Montevideo.
# La conexión se carga en la pantalla Configuración; la contraseña va a este secreto.
CDR_JOB_NOMBRE="${CDR_JOB_NOMBRE:-empresas-cdr}"
CDR_SECRETO="${CDR_SECRETO:-empresas-cdr-mysql-password}"
# IP_FIJA=1: salida a internet por Cloud NAT con una IP estática (solo si el MySQL filtra por IP)
IP_FIJA="${IP_FIJA:-}"

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
             roles/bigquery.jobUser roles/firebaseauth.admin; do
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
  if ! existe g secrets describe empresas-smtp-password; then
    echo "▶ Contraseña de aplicación de ${SMTP_USUARIO} para este proyecto (docs/despliegue.md, paso 1)"
    if [ ! -t 0 ]; then
      echo "  Falta el secreto empresas-smtp-password y la terminal no es interactiva. Crealo con:"
      echo "  printf '%s' 'CLAVE' | gcloud secrets create empresas-smtp-password --project $PROYECTO --data-file=-"
      exit 1
    fi
    local clave
    read -rs -p "  Pegá la contraseña de aplicación (no se muestra): " clave; echo
    clave="${clave// /}"   # Google la muestra en grupos de 4 con espacios
    [ -n "$clave" ] || { echo "  La contraseña está vacía"; exit 1; }
    secreto empresas-smtp-password "$clave"
  fi

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
  # Si no se pasa ADMIN_EMAILS, se conserva el valor que ya tiene el servicio
  local admins="$ADMIN_EMAILS"
  if [ -z "$admins" ] && [ -n "$url" ]; then
    admins="$(g run services describe "$SERVICIO" --region "$REGION" --format json | python3 -c \
      'import json,sys; e=json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0].get("env",[]); print(next((x.get("value","") for x in e if x["name"]=="ADMIN_EMAILS"),""))')"
  fi
  red_de_salida
  echo "▶ Cloud Run $SERVICIO"
  g run deploy "$SERVICIO" --image "$IMAGEN" --region "$REGION" --service-account "$SA" \
    --add-cloudsql-instances "$CONEXION" --allow-unauthenticated --memory 1Gi --cpu 1 --timeout 1800 \
    --min-instances 0 --max-instances "$INSTANCIAS" --concurrency 20 \
    --set-env-vars "^;^DB_POOL_MAX=${POOL};AUTH_MODE=firebase;FIREBASE_PROJECT_ID=${PROYECTO};TASKS_MODE=cloudtasks;TASKS_QUEUE=projects/${PROYECTO}/locations/${REGION}/queues/${COLA};STORAGE_BUCKET=${BUCKET};BQ_TABLA_AUDITORIA=${PROYECTO}.empresas_auditoria.auditoria;ADMIN_EMAILS=${admins};API_URL=${url};APP_URL=${APP_URL};SMTP_USUARIO=${SMTP_USUARIO};SMTP_HOST=${SMTP_HOST};SMTP_PORT=${SMTP_PORT};GCP_PROYECTO=${PROYECTO};GCP_REGION=${REGION};CDR_JOB=${CDR_JOB_NOMBRE};CDR_SECRETO=${CDR_SECRETO}" \
    ${RED[@]+"${RED[@]}"} \
    --set-secrets "DATABASE_URL=empresas-database-url:latest,JOB_TOKEN=empresas-job-token:latest,TAREA_TOKEN=empresas-tarea-token:latest,SMTP_PASSWORD=empresas-smtp-password:latest"
  if [ -z "$url" ]; then  # primera vez: la URL recién existe después del deploy
    url="$(g run services describe "$SERVICIO" --region "$REGION" --format 'value(status.url)')"
    g run services update "$SERVICIO" --region "$REGION" --update-env-vars "API_URL=${url}"
  fi
  echo "API en $url"
  # El job del CDR usa la misma imagen: se actualiza junto con la API
  if existe g run jobs describe "$CDR_JOB_NOMBRE" --region "$REGION"; then
    g run jobs update "$CDR_JOB_NOMBRE" --region "$REGION" --image "$IMAGEN"
  fi
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

red_de_salida() {
  # Con IP_FIJA=1, la API (por "Probar conexión") y el job salen a internet por Cloud NAT con una
  # IP estática, para que un MySQL que filtra por IP de origen la pueda autorizar.
  RED=()
  [ "$IP_FIJA" = "1" ] || return 0
  echo "▶ IP de salida fija (VPC, Cloud Router, Cloud NAT e IP estática)"
  g services enable compute.googleapis.com
  existe g compute networks describe empresas-vpc || g compute networks create empresas-vpc --subnet-mode=custom
  existe g compute networks subnets describe empresas-subnet --region "$REGION" || g compute networks subnets create \
    empresas-subnet --network empresas-vpc --region "$REGION" --range 10.8.0.0/26
  existe g compute addresses describe empresas-salida-ip --region "$REGION" || g compute addresses create \
    empresas-salida-ip --region "$REGION"
  existe g compute routers describe empresas-router --region "$REGION" || g compute routers create empresas-router \
    --network empresas-vpc --region "$REGION"
  existe g compute routers nats describe empresas-nat --router empresas-router --region "$REGION" || g compute routers \
    nats create empresas-nat --router empresas-router --region "$REGION" --nat-all-subnet-ip-ranges \
    --nat-external-ip-pool empresas-salida-ip
  echo "  IP de salida fija: $(g compute addresses describe empresas-salida-ip --region "$REGION" --format 'value(address)')"
  echo "  Pedí que el servidor MySQL del CDR acepte conexiones desde esa IP."
  RED=(--network empresas-vpc --subnet empresas-subnet --vpc-egress all-traffic)
}

cdr() {
  echo "▶ Job del CDR: secreto, Cloud Run job ${CDR_JOB_NOMBRE} y Cloud Scheduler (4:00, Montevideo)"
  existe g secrets describe "$CDR_SECRETO" || g secrets create "$CDR_SECRETO" --replication-policy=automatic
  # La API agrega versiones (pantalla Configuración) y las lee, solo sobre este secreto
  for rol in roles/secretmanager.secretVersionManager roles/secretmanager.secretAccessor; do
    g secrets add-iam-policy-binding "$CDR_SECRETO" --member "serviceAccount:$SA" --role "$rol" >/dev/null
  done
  red_de_salida
  local imagen
  imagen="$(g run services describe "$SERVICIO" --region "$REGION" --format 'value(spec.template.spec.containers[0].image)')"
  g run jobs deploy "$CDR_JOB_NOMBRE" --image "$imagen" --region "$REGION" --service-account "$SA" \
    --set-cloudsql-instances "$CONEXION" --set-secrets "DATABASE_URL=empresas-database-url:latest" \
    --set-env-vars "^;^AUTH_MODE=firebase;GCP_PROYECTO=${PROYECTO};GCP_REGION=${REGION};CDR_SECRETO=${CDR_SECRETO};STORAGE_BUCKET=${BUCKET};DB_POOL_MAX=3" \
    --command python --args=-m,app.jobs.cdr_job --task-timeout 3600 --max-retries 0 \
    ${RED[@]+"${RED[@]}"}
  # "Correr ahora" y "Reprocesar desde…": la API ejecuta el job con argumentos propios
  for rol in roles/run.invoker roles/run.jobsExecutorWithOverrides; do
    g run jobs add-iam-policy-binding "$CDR_JOB_NOMBRE" --region "$REGION" --member "serviceAccount:$SA" \
      --role "$rol" >/dev/null
  done
  local uri="https://run.googleapis.com/v2/projects/${PROYECTO}/locations/${REGION}/jobs/${CDR_JOB_NOMBRE}:run"
  local accion=create
  existe g scheduler jobs describe "$CDR_JOB_NOMBRE" --location "$REGION" && accion=update
  g scheduler jobs "$accion" http "$CDR_JOB_NOMBRE" --location "$REGION" --schedule "0 4 * * *" \
    --time-zone "America/Montevideo" --uri "$uri" --http-method POST --oauth-service-account-email "$SA"
  echo "  Listo. Cargá la conexión en la aplicación: Configuración → CDR (docs/despliegue.md, paso 4)."
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

invitar() {
  # Crea la cuenta de cada email de ADMIN_EMAILS y le manda su enlace de acceso, con la misma
  # lógica que el alta desde la pantalla Usuarios. forzar=false (al final de "todo"): una cuenta
  # que ya existe no se toca. forzar=true ("invitar"): le llega un enlace nuevo.
  local forzar="${1:-true}" url token
  url="$(g run services describe "$SERVICIO" --region "$REGION" --format 'value(status.url)')"
  token="$(g secrets versions access latest --secret empresas-job-token)"
  echo "▶ Administradores iniciales: enlace de acceso"
  curl -sS --fail-with-body -X POST "${url}/api/jobs/invitar-admins" -H "X-Job-Token: ${token}" \
    -H "Content-Type: application/json" -d "{\"forzar\": ${forzar}}" | python3 -c '
import json, sys
for r in json.load(sys.stdin)["resultados"]:
    c = r.get("correo") or {}
    linea = "  " + r["email"] + ": " + r["estado"]
    if c:
        linea += " · correo " + ("enviado" if c.get("enviado") else "NO enviado: " + c.get("detalle", ""))
    print(linea)
    if r.get("mensaje"):
        print("    " + r["mensaje"])
    if r.get("enlace"):
        print("    Enlace de acceso (se muestra una sola vez y vence en una hora):")
        print("    " + r["enlace"])
'
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
  invitar) invitar true ;;
  cdr) cdr ;;
  todo) base; api; migrar; cdr; programar; web; invitar false ;;
  *) echo "uso: PROYECTO=... $0 {todo|base|api|migrar|cdr|web|programar|redimensionar|invitar}"; exit 1 ;;
esac
