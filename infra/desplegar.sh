#!/usr/bin/env bash
# Despliegue de la Base de Empresas en un proyecto de GCP propio (ver docs/despliegue.md).
#
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh todo        # primera vez
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh api         # nueva versión: migra, servicio de tareas y API
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh migrar      # solo aplicar migraciones (casos especiales)
#   PROYECTO=equipos-base-empresas ./infra/desplegar.sh tareas      # solo el servicio de tareas, con la imagen de la API
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
# D52: las tareas pesadas (lectura de archivos, lotes de carga, deshacer, borrar) corren en un servicio aparte, con
# un solo proceso, una tarea a la vez y 2 GiB, para que una carga grande no deje sin memoria a la web.
SERVICIO_TAREAS="${SERVICIO_TAREAS:-empresas-tareas}"
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
    # API + servicio de tareas (D52) + 1 del job de migraciones, sin pasar de las disponibles
    db-f1-micro) POOL=5; INSTANCIAS=3; POOL_TAREAS=3; INSTANCIAS_TAREAS=2 ;;   # 25 (22 usables): 15 + 6 + 1
    db-g1-small) POOL=8; INSTANCIAS=4; POOL_TAREAS=4; INSTANCIAS_TAREAS=2 ;;   # 50: 32 + 8 + 1
    *) POOL=10; INSTANCIAS=4; POOL_TAREAS=5; INSTANCIAS_TAREAS=3 ;;            # 100 o más
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

  cola

  echo "▶ BigQuery (export diario de auditoría)"
  existe bq --project_id "$PROYECTO" show empresas_auditoria || bq --project_id "$PROYECTO" --location=US mk -d empresas_auditoria
  existe bq --project_id "$PROYECTO" show empresas_auditoria.auditoria || bq --project_id "$PROYECTO" mk -t \
    --time_partitioning_field fecha empresas_auditoria.auditoria \
    id:INTEGER,actor:STRING,accion:STRING,objeto:STRING,objeto_id:STRING,detalle:STRING,fecha:TIMESTAMP

  echo "▶ Artifact Registry"
  existe g artifacts repositories describe "$REPO" --location "$REGION" || g artifacts repositories create "$REPO" \
    --repository-format=docker --location "$REGION"
}

# Fase 2: un secreto por proveedor del enriquecimiento. Se crean vacíos; las claves se cargan desde la
# aplicación (Configuración → Enriquecimiento), que agrega versiones y nunca las muestra.
secretos_proveedores() {
  echo "▶ Secretos de los proveedores del enriquecimiento (Google Places, Brave Search, Claude)"
  g services enable places.googleapis.com >/dev/null
  local s rol
  for s in empresas-places-key empresas-brave-key empresas-anthropic-key; do
    existe g secrets describe "$s" || g secrets create "$s" --replication-policy=automatic >/dev/null
    for rol in roles/secretmanager.secretVersionManager roles/secretmanager.secretAccessor; do
      g secrets add-iam-policy-binding "$s" --member "serviceAccount:$SA" --role "$rol" >/dev/null
    done
  done
}

cola() {
  # D52: si el pedido de una tarea muere (proceso sin memoria, instancia que se apaga) o la tarea está ocupada en otro
  # proceso (503), Cloud Tasks reintenta hasta 5 veces, de 30 s a 5 min: a los 3 minutos sin latido se retoma sola.
  echo "▶ Cola de Cloud Tasks ${COLA} (5 intentos, de 30 s a 5 min)"
  local accion=create
  existe g tasks queues describe "$COLA" --location "$REGION" && accion=update
  g tasks queues "$accion" "$COLA" --location "$REGION" --max-concurrent-dispatches=2 --max-attempts=5 \
    --min-backoff=30s --max-backoff=300s --max-doublings=4
}

# Variables de entorno comunes a la API y al servicio de tareas (el mismo código)
entorno() {  # entorno URL_API ADMINS URL_TAREAS
  echo "^;^AUTH_MODE=firebase;FIREBASE_PROJECT_ID=${PROYECTO};TASKS_MODE=cloudtasks;TASKS_QUEUE=projects/${PROYECTO}/locations/${REGION}/queues/${COLA};STORAGE_BUCKET=${BUCKET};BQ_TABLA_AUDITORIA=${PROYECTO}.empresas_auditoria.auditoria;ADMIN_EMAILS=${2};API_URL=${1};TAREAS_URL=${3};APP_URL=${APP_URL};SMTP_USUARIO=${SMTP_USUARIO};SMTP_HOST=${SMTP_HOST};SMTP_PORT=${SMTP_PORT};GCP_PROYECTO=${PROYECTO};GCP_REGION=${REGION};CDR_JOB=${CDR_JOB_NOMBRE};CDR_SECRETO=${CDR_SECRETO}"
}
SECRETOS="DATABASE_URL=empresas-database-url:latest,JOB_TOKEN=empresas-job-token:latest,TAREA_TOKEN=empresas-tarea-token:latest,SMTP_PASSWORD=empresas-smtp-password:latest"

url_de() { g run services describe "$1" --region "$REGION" --format 'value(status.url)' 2>/dev/null || true; }

admins_actuales() {  # si no se pasa ADMIN_EMAILS, se conserva el valor que ya tiene el servicio
  local admins="$ADMIN_EMAILS"
  if [ -z "$admins" ] && [ -n "$(url_de "$SERVICIO")" ]; then
    admins="$(g run services describe "$SERVICIO" --region "$REGION" --format json | python3 -c \
      'import json,sys; e=json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0].get("env",[]); print(next((x.get("value","") for x in e if x["name"]=="ADMIN_EMAILS"),""))')"
  fi
  echo "$admins"
}

imagen_actual() { g run services describe "$SERVICIO" --region "$REGION" --format 'value(spec.template.spec.containers[0].image)'; }

api() {
  limites
  secretos_proveedores
  echo "▶ Imagen $IMAGEN"
  g builds submit --tag "$IMAGEN" .
  # R3 (D52): nunca código sin su migración. Se migra con la imagen nueva ANTES de pasarle el tráfico; si falla, no
  # se despliega nada (las migraciones son compatibles hacia atrás: la versión anterior sigue andando).
  if ! migrar "$IMAGEN"; then
    echo "✖ La migración falló: NO se desplegó la versión nueva (sigue la anterior). Revisá el error del job"
    echo "  empresas-migrar en la consola de Cloud Run (Jobs → empresas-migrar → Ejecuciones) y pasámelo."
    exit 1
  fi
  cola
  red_de_salida
  local url admins
  url="$(url_de "$SERVICIO")"
  admins="$(admins_actuales)"
  # El servicio de tareas primero: la API nueva encola tareas que tiene que entender
  tareas "$IMAGEN"
  echo "▶ Cloud Run $SERVICIO (la web: 2 procesos, 1 GiB)"
  g run deploy "$SERVICIO" --image "$IMAGEN" --region "$REGION" --service-account "$SA" \
    --add-cloudsql-instances "$CONEXION" --allow-unauthenticated --memory 1Gi --cpu 1 --timeout 1800 \
    --min-instances 0 --max-instances "$INSTANCIAS" --concurrency 20 \
    --set-env-vars "$(entorno "$url" "$admins" "$URL_TAREAS");DB_POOL_MAX=${POOL};WORKERS=2;MEMORIA_LIMITE_MB=1024" \
    ${RED[@]+"${RED[@]}"} --set-secrets "$SECRETOS"
  if [ -z "$url" ]; then  # primera vez: la URL recién existe después del deploy
    url="$(url_de "$SERVICIO")"
    g run services update "$SERVICIO" --region "$REGION" --update-env-vars "API_URL=${url}"
    g run services update "$SERVICIO_TAREAS" --region "$REGION" --update-env-vars "API_URL=${url}"
  fi
  echo "API en $url · tareas en $URL_TAREAS"
  # El job del CDR usa la misma imagen: se actualiza junto con la API
  if existe g run jobs describe "$CDR_JOB_NOMBRE" --region "$REGION"; then
    g run jobs update "$CDR_JOB_NOMBRE" --region "$REGION" --image "$IMAGEN"
  fi
}

tareas() {  # tareas [IMAGEN] — sin imagen, la que tiene la API ahora
  limites
  local imagen="${1:-$(imagen_actual)}" url admins
  url="$(url_de "$SERVICIO")"
  admins="$(admins_actuales)"
  red_de_salida
  URL_TAREAS="$(url_de "$SERVICIO_TAREAS")"
  echo "▶ Cloud Run $SERVICIO_TAREAS (tareas pesadas: 1 proceso, 1 tarea a la vez, 2 GiB)"
  g run deploy "$SERVICIO_TAREAS" --image "$imagen" --region "$REGION" --service-account "$SA" \
    --add-cloudsql-instances "$CONEXION" --allow-unauthenticated --memory 2Gi --cpu 1 --timeout 1800 \
    --min-instances 0 --max-instances "$INSTANCIAS_TAREAS" --concurrency 1 \
    --set-env-vars "$(entorno "$url" "$admins" "$URL_TAREAS");DB_POOL_MAX=${POOL_TAREAS};WORKERS=1;MEMORIA_LIMITE_MB=2048" \
    ${RED[@]+"${RED[@]}"} --set-secrets "$SECRETOS"
  if [ -z "$URL_TAREAS" ]; then  # primera vez: el servicio se encola a sí mismo los pasos siguientes
    URL_TAREAS="$(url_de "$SERVICIO_TAREAS")"
    g run services update "$SERVICIO_TAREAS" --region "$REGION" --update-env-vars "TAREAS_URL=${URL_TAREAS}"
  fi
  # La API manda las tareas al servicio de tareas (si ya existe y todavía no lo sabe)
  if [ -n "$url" ] && [ -z "${1:-}" ]; then
    g run services update "$SERVICIO" --region "$REGION" --update-env-vars "TAREAS_URL=${URL_TAREAS}"
  fi
}

migrar() {  # migrar [IMAGEN] — sin imagen, la que tiene la API ahora
  echo "▶ Migraciones (Cloud Run job empresas-migrar)"
  local imagen="${1:-$(imagen_actual)}"
  g run jobs deploy empresas-migrar --image "$imagen" --region "$REGION" --service-account "$SA" \
    --set-cloudsql-instances "$CONEXION" --set-secrets "DATABASE_URL=empresas-database-url:latest" \
    --command python --args /srv/db/migrate.py --max-retries 0 || return 1
  g run jobs execute empresas-migrar --region "$REGION" --wait || return 1
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
  echo "▶ Cloud Scheduler: auditoría a BigQuery (5:10), foto de calidad (5:20) y duplicados difusos (5:30), Montevideo"
  local url token nombre hora ruta
  url="$(g run services describe "$SERVICIO" --region "$REGION" --format 'value(status.url)')"
  token="$(g secrets versions access latest --secret empresas-job-token)"
  for job in "empresas-auditoria-bq|10 5 * * *|auditoria-bq" "empresas-calidad|20 5 * * *|calidad" \
             "empresas-duplicados|30 5 * * *|duplicados"; do
    IFS='|' read -r nombre hora ruta <<< "$job"
    existe g scheduler jobs describe "$nombre" --location "$REGION" && \
      g scheduler jobs delete "$nombre" --location "$REGION" --quiet
    g scheduler jobs create http "$nombre" --location "$REGION" --schedule "$hora" \
      --time-zone "America/Montevideo" --uri "${url}/api/jobs/${ruta}" --http-method POST \
      --headers "X-Job-Token=${token}" --attempt-deadline 600s
  done
}

case "${1:-}" in
  base) base ;;
  api) api ;;
  tareas) tareas ;;
  migrar) migrar || { echo "✖ La migración falló"; exit 1; } ;;
  web) web ;;
  programar) programar ;;
  redimensionar) redimensionar ;;
  invitar) invitar true ;;
  cdr) cdr ;;
  todo) base; api; cdr; programar; web; invitar false ;;   # api ya migra y despliega el servicio de tareas
  *) echo "uso: PROYECTO=... $0 {todo|base|api|tareas|migrar|cdr|web|programar|redimensionar|invitar}"; exit 1 ;;
esac
