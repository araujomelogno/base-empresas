# Guía de despliegue

Esta guía lleva la Base de Empresas desde el repositorio hasta producción en un proyecto de Google Cloud propio, y explica cómo actualizarla, operarla y desarrollar en local. Los comandos están escritos para una **Mac**. La fase 0 no se despliega: sus scripts corren en la Mac o en el servidor Ubuntu (ver `fase0/README.md`).

## Arquitectura

| Pieza | Servicio | Qué hace |
| --- | --- | --- |
| Web | Firebase Hosting (`web/public`) | Pantallas en JS sin framework. Reescribe `/api/**` a Cloud Run |
| Autenticación | Firebase Authentication | Email y clave. La API valida el ID token |
| API | Cloud Run `empresas-api` (`Dockerfile`) | FastAPI. Reglas de negocio, permisos por rol, auditoría |
| Base de datos | Cloud SQL Postgres 16 `empresas-pg`, tamaño `db-f1-micro` | Esquema `empresas`, migraciones en `db/empresas/` |
| Migraciones | Cloud Run job `empresas-migrar` | Corre `db/migrate.py` con la misma imagen de la API |
| Tareas diferidas | Cloud Tasks `empresas-tareas` | Preview y confirmación de cargas, ingestas y remapeos del .sav |
| Archivos | Cloud Storage `<proyecto>-empresas-archivos` | Bases y .sav subidos (privado) |
| Secretos | Secret Manager | `empresas-database-url`, `empresas-job-token`, `empresas-tarea-token` |
| Auditoría larga | BigQuery `empresas_auditoria.auditoria` | Export diario a las 5:10 (Cloud Scheduler) |
| CDR | Servidor Ubuntu de Equipos o una Mac de la oficina (`jobs/cdr`) | Job a las 4:00: lee MySQL de uContact y empuja a la API |

Todo vive en **Iowa (`us-central1`)**, salvo el dataset de BigQuery, que queda en la multirregión `US` (ver decisiones, D27).

### Capacidad inicial

La base de datos arranca con el tamaño más chico de Cloud SQL, **`db-f1-micro`** (núcleo compartido, 0,6 GB de memoria, 25 conexiones, sin SLA de Google), para que el costo inicial sea mínimo (ver `docs/costos.md` y la decisión D31). Para que la API no supere esas 25 conexiones, el script la despliega con **5 conexiones por instancia (`DB_POOL_MAX=5`) y hasta 3 instancias de Cloud Run**.

Cuando el uso crezca, se pasa a `db-g1-small` con un solo comando y unos minutos sin servicio. Las señales para hacerlo y el paso a paso están en **[`docs/cambio_a_small.md`](cambio_a_small.md)**.

## Requisitos

- Un proyecto de Google Cloud con facturación habilitada y permisos de **Owner** para quien despliega (solo la primera vez).
- El mismo proyecto agregado a Firebase (consola de Firebase → *Agregar proyecto* → elegir el proyecto existente).
- Una **Mac** (Apple Silicon o Intel, macOS 13 o posterior) desde la que se despliega, preparada como se explica abajo.
- Acceso a la base MySQL del CDR (`uc`) con un usuario de solo lectura, desde la máquina que va a correr el job del CDR (paso 4).

### Preparar la Mac

Todo se instala con [Homebrew](https://brew.sh). En la Terminal (zsh, la que viene con macOS):

```bash
xcode-select --install
```

Eso instala `git` y las herramientas de línea de comandos de Apple. Después, Homebrew:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Al terminar, Homebrew muestra dos líneas para agregarlo al `PATH` (en Apple Silicon, `eval "$(/opt/homebrew/bin/brew shellenv)"`); hay que correrlas y abrir una Terminal nueva. Luego las herramientas del despliegue:

```bash
brew install --cask google-cloud-sdk
```

```bash
brew install node python@3.12 postgresql@16
```

```bash
npm install -g firebase-tools
```

`google-cloud-sdk` trae `gcloud` y `bq`. `openssl` y `bash` ya vienen con macOS y alcanzan para el script de despliegue. Python y Postgres solo hacen falta para desarrollo local y para correr la fase 0 (ver más abajo).

Por último, el repositorio y las sesiones de Google y Firebase:

```bash
git clone https://github.com/araujomelogno/base-empresas.git ~/base-empresas
```

```bash
gcloud auth login
```

```bash
gcloud config set project equipos-base-empresas
```

```bash
firebase login
```

Los comandos de esta guía se corren desde la carpeta del repositorio (`cd ~/base-empresas`).

## Primer despliegue

### 1. Firebase Authentication y la web

1. En la consola de Firebase → **Authentication** → *Comenzar* → habilitar **Correo electrónico/contraseña**.
2. En **Configuración del proyecto** → *Tus apps* → agregar una app **Web** y copiar el objeto `firebaseConfig`.
3. Pegarlo en `web/public/js/config.js` (las claves de una app web de Firebase son públicas; el acceso lo controla la API) y dejar `authMode: "firebase"`.
4. Copiar `web/.firebaserc.example` a `web/.firebaserc` con el id del proyecto.
5. En **Authentication → Configuración → Dominios autorizados** verificar que estén el dominio `*.web.app` y, si se usa, el dominio propio.

### 2. Infraestructura, API, migraciones y web

Desde la raíz del repositorio:

```bash
PROYECTO=equipos-base-empresas ADMIN_EMAILS=garaujo@equipos.com.uy ./infra/desplegar.sh todo
```

El script es idempotente (se puede volver a correr) y hace, en orden:

1. **base:** habilita las APIs; crea la cuenta de servicio `empresas-api` con los roles mínimos (Cloud SQL client, Secret Manager accessor, Cloud Tasks enqueuer, BigQuery data editor y job user); crea la instancia de Cloud SQL (Enterprise, `db-f1-micro`, 10 GB SSD con autoincremento, backups diarios a las 6:00 con recuperación a un punto en el tiempo y 14 copias), la base `empresas` y el usuario `empresas_app` con clave aleatoria; guarda en Secret Manager la cadena de conexión y dos tokens aleatorios; crea el bucket privado, la cola de Cloud Tasks, el dataset y la tabla de BigQuery, y el repositorio de Artifact Registry.
2. **api:** construye la imagen con Cloud Build y despliega Cloud Run con `AUTH_MODE=firebase`, `TASKS_MODE=cloudtasks`, el bucket, la cola, la tabla de BigQuery y los secretos. El pool de conexiones (`DB_POOL_MAX`) y el máximo de instancias se ajustan solos al tamaño real de la instancia de Cloud SQL. La primera vez completa `API_URL` con la URL que asigna Cloud Run.
3. **migrar:** crea y ejecuta el Cloud Run job `empresas-migrar`, que aplica las migraciones pendientes.
4. **programar:** crea el Cloud Scheduler que exporta la auditoría a BigQuery todos los días a las 5:10.
5. **web:** `firebase deploy --only hosting`.

`ADMIN_EMAILS` lista (separados por coma) los emails que quedan como administradores la primera vez que entran. Después los usuarios se gestionan desde la pantalla **Usuarios**.

Variables opcionales del script: `REGION` (por defecto `us-central1`), `TIER` (tamaño de Cloud SQL al crearla, por defecto `db-f1-micro`) y `DISCO_GB` (por defecto 10). El disco de Cloud SQL se puede agrandar pero no achicar: conviene no subir `DISCO_GB` de entrada; el autoincremento lo agranda si hace falta.

### 3. Usuarios

Cada persona necesita dos cosas con el **mismo email**:

1. Una cuenta en Firebase Authentication (consola → Authentication → *Agregar usuario*, o que el administrador la cree y la persona use "¿Olvidaste tu contraseña?" para elegir su clave).
2. Un registro en la pantalla **Usuarios** de la aplicación con su rol. Sin ese registro, la API responde "no tiene acceso".

### 4. Job del CDR

El job lee la base MySQL de uContact, que solo es accesible desde la red de Equipos. Por eso corre en una máquina de esa red y no en Google Cloud. Hay dos opciones:

- **Servidor Ubuntu de Equipos** (recomendado, el mismo del dashboard de productividad): está siempre prendido. Usa un timer de systemd.
- **Una Mac de la oficina:** sirve si no se usa el servidor. Usa `launchd`; la Mac tiene que estar prendida a las 4:00 (si está dormida, el job corre al despertarse).

En cualquiera de las dos hacen falta la URL de la API y el token del job. Se obtienen desde tu Mac:

```bash
gcloud run services describe empresas-api --region us-central1 --format 'value(status.url)'
gcloud secrets versions access latest --secret empresas-job-token
```

Con esos dos valores, seguir `jobs/cdr/README.md`: clonar el repositorio, crear el entorno virtual, completar `jobs/cdr/cdr_job.env` (MySQL de solo lectura, `API_URL` = URL de Cloud Run, `JOB_TOKEN`), probar con `--dry-run` y programarlo a las 4:00, hora de Montevideo. El README tiene los pasos para el servidor Ubuntu (systemd) y para una Mac (launchd).

### 5. Configuración inicial de negocio

Con un usuario administrador, en la aplicación:

1. **Naturalezas jurídicas:** cargar la hoja "excluidos" del Excel de referencia con `python fase0/cargar_excluidos.py <excel> --api <url> --token <id token>` o marcarlas a mano.
2. **Configuración:** meses de enfriamiento, destinos internos del CDR (salen del experimento A de la fase 0), prefijos de salida de la central, franjas y el formato del CSV de uContact (verificarlo con una importación de prueba).
3. **Alchemer:** cargar el bloque estándar de variables en cada cuestionario (`fase0/alchemer_bloque_estandar.md`).

### 6. Verificación

```bash
URL=$(gcloud run services describe empresas-api --region us-central1 --format 'value(status.url)')
curl -s $URL/api/salud                     # {"ok":true}
```

- Entrar a la web con un administrador y ver la pantalla de inicio.
- Hacer una carga chica de prueba y deshacerla.
- Correr el job del CDR a mano (en el servidor Ubuntu: `sudo systemctl start cdr-job.service`; en una Mac: `launchctl kickstart gui/$(id -u)/uy.equipos.cdr-job`) y ver el lote en **Actividad**.

## Actualizaciones

| Cambio | Comando |
| --- | --- |
| Código de la API | `PROYECTO=… ./infra/desplegar.sh api` |
| Migración nueva (`db/empresas/NNNN_*.sql`) | `./infra/desplegar.sh api` y después `./infra/desplegar.sh migrar` |
| Web | `PROYECTO=… ./infra/desplegar.sh web` |
| Job del CDR | `git pull` en `/opt/base-empresas` (no requiere reiniciar el timer) |
| Tamaño de Cloud SQL | `PROYECTO=… TIER=db-g1-small ./infra/desplegar.sh redimensionar` (ver [`docs/cambio_a_small.md`](cambio_a_small.md)) |

Las migraciones se escriben para ser compatibles hacia atrás (agregar columnas o tablas, no borrar) para que la versión anterior de la API siga funcionando mientras corren. Una migración nunca se edita una vez aplicada: se agrega otra.

**Volver atrás la API:** Cloud Run guarda las revisiones anteriores.

```bash
gcloud run services update-traffic empresas-api --region us-central1 --to-revisions <revision>=100
```

**Volver atrás la web:** consola de Firebase → Hosting → historial de versiones → *Revertir*.

## Operación

### Backups y restauración

Cloud SQL hace un backup diario (6:00) y guarda los registros para recuperación a un punto en el tiempo (7 días). Para probar una restauración sin tocar producción:

```bash
gcloud sql instances clone empresas-pg empresas-pg-prueba --point-in-time '2026-11-02T10:00:00Z'
```

Se recomienda hacerlo una vez por trimestre (coincide con la auditoría por muestreo del PRD). Los archivos subidos quedan en el bucket; la auditoría, además, en BigQuery.

### Monitoreo

- **Errores de la API:** Cloud Run → `empresas-api` → *Registros* (filtrar por severidad ERROR). Cada error no manejado queda con su traza.
- **Tareas diferidas:** si una carga o ingesta queda en error, la pantalla lo muestra con el mensaje; la cola está en Cloud Tasks → `empresas-tareas`.
- **CDR:** la pantalla de inicio muestra la fecha del último lote. En el servidor Ubuntu: `journalctl -u cdr-job.service --since today`; en una Mac: `tail -n 100 ~/Library/Logs/cdr-job.log`.
- **Alertas sugeridas:** en Cloud Monitoring, una política sobre errores 5xx de Cloud Run y otra sobre CPU o almacenamiento de Cloud SQL por encima del 80%. Con `db-f1-micro`, esas alertas de CPU y memoria son las que avisan que llegó el momento de pasar a `db-g1-small`.

### Rotar los tokens

```bash
openssl rand -hex 32 | gcloud secrets versions add empresas-job-token --data-file=-
PROYECTO=… ./infra/desplegar.sh api         # toma la versión nueva
PROYECTO=… ./infra/desplegar.sh programar   # actualiza el Cloud Scheduler
```

Después actualizar `JOB_TOKEN` en `jobs/cdr/cdr_job.env` de la máquina que corre el job del CDR. El token de tareas se rota igual (`empresas-tarea-token`) y solo requiere redesplegar la API.

### Seguridad y Ley 18.331

- La API rechaza todo pedido sin token válido de Firebase o de un email no registrado. Los permisos se validan en el backend.
- El bucket es privado (acceso uniforme, prevención de acceso público).
- La base no tiene IP pública habilitada para usuarios: Cloud Run entra por el conector de Cloud SQL.
- Exportar contactos personales requiere el permiso específico del usuario y queda auditado.
- Pendiente legal antes de operar: inscripción de la base ante la URCDP y plazo de conservación de contactos sin uso. Como los datos quedan en Estados Unidos (Iowa), conviene que legal confirme también el encuadre de la transferencia internacional de datos personales (Google ofrece cláusulas contractuales en su acuerdo de procesamiento de datos).

## Desarrollo local en la Mac

Requisitos: Python 3.12, Postgres 16 y Node (Node solo para las capturas y el PDF del manual), instalados como en **Preparar la Mac**.

### Postgres

```bash
brew services start postgresql@16
```

`postgresql@16` no se agrega solo al `PATH`. Para tener `psql` y `createdb` en la Terminal (Apple Silicon; en Intel, la ruta es `/usr/local/opt/postgresql@16/bin`):

```bash
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

Homebrew crea el superusuario de Postgres con tu usuario de macOS, no con `postgres`. Para que los comandos de esta guía y los tests funcionen tal cual, se crea una vez el rol `postgres`:

```bash
createuser -s postgres
```

### Entorno de Python

Homebrew no deja instalar paquetes en el Python del sistema ("externally-managed-environment"), así que se usa un entorno virtual en la carpeta del repositorio:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
```

```bash
pip install -r api/requirements-dev.txt
```

En cada Terminal nueva, activarlo de nuevo con `source .venv/bin/activate` desde la carpeta del repositorio.

### Levantar la aplicación con datos de demostración

```bash
createdb empresas_dev
```

```bash
DATABASE_URL=postgresql://postgres@localhost/empresas_dev python api/demo/sembrar_demo.py
```

```bash
cd api && DATABASE_URL=postgresql://postgres@localhost/empresas_dev AUTH_MODE=dev SERVE_WEB=1 uvicorn app.main:app --port 8080 --reload
```

El script de la demo aplica las migraciones y carga datos ficticios en una base vacía. Abrí http://localhost:8080: si `config.js` no tiene Firebase configurado, la web entra en modo dev y se ingresa con un email registrado (por ejemplo `admin@equipos.com.uy` de la demo) sin clave. **Nunca** desplegar con `AUTH_MODE=dev`.

### Tests

```bash
createdb empresas_test
```

```bash
(cd api && TEST_DATABASE_URL=postgresql://postgres@localhost/empresas_test python -m pytest -q)
```

```bash
(cd fase0 && python -m pytest -q)
```

```bash
(cd jobs/cdr && python -m pytest -q)
```

Los tests de la API usan Postgres real: cada test migra un esquema limpio. Cubren los criterios de aceptación de R1.1 a R1.13, incluido el control de que ninguna empresa excluida, en no llamar o en enfriamiento entra a una muestra ni a un CSV, y que toda muestra se reproduce con su semilla.

### Manual de usuario en PDF

Necesita Playwright con su Chromium, instalados una vez dentro de `docs/build`:

```bash
(cd docs/build && npm install && npx playwright install chromium)
```

```bash
pip install markdown pypdf
```

Con la aplicación levantada con la demo (ver arriba), en otra Terminal:

```bash
node docs/build/capturas.js http://localhost:8080 docs/manual/img <rut> api/demo/clima_parte_a_ola1.sav <base.csv>
```

```bash
python docs/build/generar_pdfs.py
```

## Variables de entorno de la API

| Variable | Producción | Descripción |
| --- | --- | --- |
| `DATABASE_URL` | secreto | `postgresql://usuario:clave@/empresas?host=/cloudsql/PROYECTO:REGION:INSTANCIA` |
| `DB_POOL_MAX` | 5 con `db-f1-micro`, 8 con `db-g1-small` | Conexiones a Postgres por instancia de la API (lo fija el script) |
| `AUTH_MODE` | `firebase` | `dev` solo en local y tests |
| `FIREBASE_PROJECT_ID` | id del proyecto | Para validar los tokens |
| `ADMIN_EMAILS` | emails | Administradores iniciales |
| `JOB_TOKEN`, `TAREA_TOKEN` | secretos | Job del CDR y export de auditoría; Cloud Tasks |
| `TASKS_MODE` | `cloudtasks` | `background` en local, `inline` en tests |
| `TASKS_QUEUE` | `projects/…/queues/empresas-tareas` | Cola de Cloud Tasks |
| `API_URL` | URL de Cloud Run | A dónde llama Cloud Tasks |
| `STORAGE_BUCKET` | bucket | Sin bucket, los archivos van a `STORAGE_DIR` |
| `BQ_TABLA_AUDITORIA` | `proyecto.empresas_auditoria.auditoria` | Export diario |
| `CORS_ORIGINS` | vacío | Solo si la web se sirve desde otro dominio |
| `APP_TZ` | `America/Montevideo` | Zona horaria de franjas y fechas |

## Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| "no tiene acceso a la Base de Empresas" | El email no está en **Usuarios** o está inactivo | Agregarlo con su rol |
| "Token inválido" | Reloj del equipo desfasado o sesión vencida | Cerrar sesión y volver a entrar |
| Pantalla "Falta configurar Firebase" | `config.js` con valores de ejemplo | Completar `firebaseConfig` y redesplegar la web |
| Una carga queda "analizando" mucho tiempo | La tarea falló o la cola está pausada | Ver Cloud Tasks y los registros de Cloud Run; la pantalla muestra el error |
| El CSV sale con menos renglones de lo esperado | Ítems sin teléfono discable o ya completos en la parte | El resumen de la exportación lo detalla |
| El job del CDR termina con código 1 | La API no respondió | Se reintenta en la próxima corrida desde el último lote enviado |
| "Archivo demasiado grande" | Más de 30 MB | Pasar el Excel a CSV o partirlo |
| `error: externally-managed-environment` al hacer `pip install` | Se usó el Python de Homebrew sin entorno virtual | Activar `.venv` (ver **Entorno de Python**) |
| `zsh: command not found: createdb` o `psql` | `postgresql@16` no está en el `PATH` | Agregarlo a `~/.zshrc` (ver **Postgres**) |
| `role "postgres" does not exist` | Postgres de Homebrew usa tu usuario de macOS | `createuser -s postgres` |
| `zsh: command not found: gcloud` | La Terminal se abrió antes de instalar el SDK | Abrir una Terminal nueva |
| El puerto 5432 está ocupado | Otro Postgres (por ejemplo, Postgres.app) está corriendo | Cerrar el otro o usar `brew services stop postgresql@16` y apuntar `DATABASE_URL` al que ya está |
| Errores `remaining connection slots are reserved` o `too many clients` | La API pidió más conexiones de las que admite `db-f1-micro` | Pasar a `db-g1-small` ([`docs/cambio_a_small.md`](cambio_a_small.md)) |
| Cargas grandes o sorteos muy lentos | `db-f1-micro` tiene poca CPU y memoria | Ídem |
