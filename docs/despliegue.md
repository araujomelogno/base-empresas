# Guía de despliegue

Esta guía explica cómo poner en producción la Base de Empresas en un proyecto propio de Google Cloud, cómo actualizarla después, cómo operarla y cómo trabajar en local. Está escrita para hacerse de arriba hacia abajo, en orden, desde una **Mac**.

Describe el sistema **tal como está hoy en el repositorio**. Hay dos cambios especificados que todavía no están implementados y que van a modificar los pasos 3 y 4:

- `specs/SPEC_alta_usuarios_enlace_acceso.md`: los usuarios se dan de alta solo desde la aplicación y reciben un enlace por correo.
- `specs/SPEC_job_cdr_en_cloud.md`: el job del CDR pasa a ser parte del sistema y la conexión se configura desde la aplicación.

Cuando se implementen, esta guía se actualiza junto con ellos.

---

## Índice

- [Qué vas a tener al terminar](#qué-vas-a-tener-al-terminar)
- [Antes de empezar](#antes-de-empezar)
- [Cómo está armado el sistema](#cómo-está-armado-el-sistema)
- [Cuánto cuesta](#cuánto-cuesta)
- [Preparar la Mac](#preparar-la-mac)
- [Primer despliegue](#primer-despliegue)
  - [Paso 1. Activar el ingreso con email y clave en Firebase y conectar la web](#paso-1-activar-el-ingreso-con-email-y-clave-en-firebase-y-conectar-la-web)
  - [Paso 2. Crear la infraestructura y publicar la API y la web](#paso-2-crear-la-infraestructura-y-publicar-la-api-y-la-web)
  - [Paso 3. Dar de alta a los usuarios](#paso-3-dar-de-alta-a-los-usuarios)
  - [Paso 4. Programar el job del CDR](#paso-4-programar-el-job-del-cdr)
  - [Paso 5. Configuración inicial del negocio](#paso-5-configuración-inicial-del-negocio)
  - [Paso 6. Verificar que todo funciona](#paso-6-verificar-que-todo-funciona)
- [Actualizaciones](#actualizaciones)
- [Operación](#operación)
- [Desarrollo local en la Mac](#desarrollo-local-en-la-mac)
- [Variables de entorno de la API](#variables-de-entorno-de-la-api)
- [Problemas frecuentes](#problemas-frecuentes)

---

## Qué vas a tener al terminar

- La aplicación web publicada en `https://<proyecto>.web.app`, con ingreso por email y clave.
- La API corriendo en Cloud Run, con su base de datos Postgres en Cloud SQL, backups diarios y migraciones aplicadas.
- El export diario de la auditoría a BigQuery.
- El job que lee el CDR de uContact todas las noches y carga los intentos de llamada.
- Al menos un usuario administrador que puede entrar y dar de alta al resto.

**Tiempo estimado:** entre 1,5 y 2 horas la primera vez, contando la preparación de la Mac. La mayor parte es espera: crear la instancia de Cloud SQL tarda unos 10 minutos y cada construcción de la imagen de la API, unos 5.

**Quién:** una persona con rol **Owner** en el proyecto de Google Cloud (solo hace falta para el primer despliegue) y con los datos de acceso a la base MySQL del CDR.

---

## Antes de empezar

Tené a mano o resuelto lo siguiente. Si algo falta, los pasos se frenan a mitad de camino.

| Qué | Para qué | Cómo se consigue |
| --- | --- | --- |
| Proyecto de Google Cloud con facturación habilitada (en esta guía, `equipos-base-empresas`) | Todo el sistema vive ahí | Consola de Google Cloud → *Nuevo proyecto* → vincular una cuenta de facturación |
| Rol **Owner** en ese proyecto | El script crea cuentas de servicio, permisos y recursos | Que un administrador de la organización te lo asigne |
| El mismo proyecto agregado a Firebase | Hosting de la web y autenticación | Consola de Firebase → *Agregar proyecto* → elegir el proyecto de Google Cloud que ya existe |
| Datos de la base MySQL del CDR: host, puerto, base, usuario de solo lectura y contraseña | El job del CDR (paso 4) | Quien administra uContact o la base `uc` |
| La lista de emails de los administradores iniciales | El paso 2 los deja como administradores | — |
| Una Mac con macOS 13 o posterior | Desde ahí se corre todo | Se prepara en la sección siguiente |

---

## Cómo está armado el sistema

| Pieza | Servicio de Google | Qué hace |
| --- | --- | --- |
| Web | Firebase Hosting (carpeta `web/public`) | Las pantallas, en JavaScript sin framework. Todo pedido a `/api/**` se reenvía a la API en Cloud Run |
| Autenticación | Firebase Authentication | Ingreso con email y clave. La web obtiene un token y la API lo valida en cada pedido |
| API | Cloud Run, servicio `empresas-api` (imagen del `Dockerfile`) | FastAPI. Reglas de negocio, permisos por rol y auditoría |
| Base de datos | Cloud SQL Postgres 16, instancia `empresas-pg`, tamaño `db-f1-micro` | Esquema `empresas`. Las migraciones están en `db/empresas/` |
| Migraciones | Cloud Run job `empresas-migrar` | Corre `db/migrate.py` con la misma imagen de la API |
| Tareas en segundo plano | Cloud Tasks, cola `empresas-tareas` | Análisis y confirmación de cargas, ingestas y remapeos de .sav, para que no corten por tiempo |
| Archivos subidos | Cloud Storage, bucket privado `<proyecto>-empresas-archivos` | Las bases y los .sav que sube la gente |
| Secretos | Secret Manager | `empresas-database-url` (conexión a Postgres), `empresas-job-token` y `empresas-tarea-token` (autentican los procesos automáticos ante la API) |
| Auditoría histórica | BigQuery, tabla `empresas_auditoria.auditoria` | Copia diaria de la auditoría a las 5:10, para consultas largas |
| Job del CDR | Script `jobs/cdr/cdr_job.py` (ver paso 4) | A las 4:00 lee las llamadas nuevas de la base MySQL del CDR y las manda a la API |

Todo está en la región **Iowa (`us-central1`)**, salvo el dataset de BigQuery, que queda en la multirregión `US` (decisión D27 en `docs/decisiones.md`).

**Sobre el CDR:** la base MySQL del CDR es accesible desde fuera de la red de Equipos, así que el job puede correr en Google Cloud. Hoy el job es un script independiente que lee la conexión de variables de entorno; el paso 4 explica cómo programarlo en Cloud Run.

### Tamaño inicial de la base de datos

La base arranca con el tamaño más chico de Cloud SQL, **`db-f1-micro`**: núcleo compartido, 0,6 GB de memoria, hasta 25 conexiones y sin SLA de Google. Se eligió para que el costo inicial sea mínimo (decisión D31).

Para no superar esas 25 conexiones, el script despliega la API con **5 conexiones por instancia (`DB_POOL_MAX=5`) y un máximo de 3 instancias** de Cloud Run.

Cuando el uso crezca, se pasa a `db-g1-small` con un solo comando y unos minutos sin servicio. Las señales para hacerlo y el paso a paso están en [`docs/cambio_a_small.md`](cambio_a_small.md).

---

## Cuánto cuesta

Aproximadamente **US$10–25 por mes** con el tamaño inicial. Casi todo es Cloud SQL, que se paga por hora mientras la instancia exista, aunque nadie la use (unos US$10–14). Cloud Run, Cloud Tasks, Cloud Scheduler, Storage, Secret Manager, BigQuery y Firebase quedan dentro de sus tramos gratuitos con el volumen previsto. El job del CDR en Cloud Run (paso 4) también entra en el tramo gratuito.

El detalle, los supuestos y qué puede hacer subir la factura están en [`docs/costos.md`](costos.md). Conviene configurar una **alerta de presupuesto** en la cuenta de facturación (por ejemplo, en US$40 por mes) antes de empezar.

---

## Preparar la Mac

Esto se hace una sola vez por Mac. Todo se instala con [Homebrew](https://brew.sh). Abrí la Terminal (la que viene con macOS, usa zsh) y corré los comandos de a uno.

**1. Herramientas de línea de comandos de Apple** (incluyen `git`):

```bash
xcode-select --install
```

Se abre una ventana: aceptá e instalá. Si dice que ya están instaladas, seguí.

**2. Homebrew:**

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Al terminar, Homebrew muestra dos líneas para agregarlo al `PATH`. En una Mac con Apple Silicon, la línea clave es `eval "$(/opt/homebrew/bin/brew shellenv)"`. Corré las dos líneas que te muestra y **abrí una Terminal nueva** antes de seguir.

**3. Google Cloud SDK** (trae `gcloud` y `bq`):

```bash
brew install --cask google-cloud-sdk
```

**4. Node, Python y Postgres:**

```bash
brew install node python@3.12 postgresql@16
```

Node hace falta para la herramienta de Firebase. Python y Postgres solo hacen falta para el paso 3, para desarrollo local y para la fase 0.

**5. Herramienta de Firebase:**

```bash
npm install -g firebase-tools
```

`openssl` y `bash` ya vienen con macOS y alcanzan para el script de despliegue.

**6. El repositorio:**

```bash
git clone https://github.com/araujomelogno/base-empresas.git ~/base-empresas
```

**7. Iniciar sesión en Google Cloud y en Firebase** (cada comando abre el navegador):

```bash
gcloud auth login
```

```bash
gcloud config set project equipos-base-empresas
```

```bash
firebase login
```

**Comprobación:** estos tres comandos tienen que responder sin error.

```bash
gcloud --version && bq version && firebase --version
```

A partir de acá, **todos los comandos de la guía se corren desde la carpeta del repositorio**:

```bash
cd ~/base-empresas
```

---

## Primer despliegue

### Paso 1. Activar el ingreso con email y clave en Firebase y conectar la web

**Para qué:** la web necesita saber a qué proyecto de Firebase pedirle el token de ingreso, y Firebase tiene que tener habilitado el ingreso con email y clave.

1. **Habilitar el ingreso.** En la [consola de Firebase](https://console.firebase.google.com), abrí el proyecto → **Authentication** → *Comenzar* → pestaña **Método de acceso** → **Correo electrónico/contraseña** → activar la primera opción → *Guardar*.

2. **Registrar la web.** En **Configuración del proyecto** (el engranaje arriba a la izquierda) → pestaña **General** → sección **Tus apps** → botón **Web** (`</>`). Poné un nombre (por ejemplo, "Base de Empresas"), **no** marques Firebase Hosting en este paso y tocá *Registrar app*. Firebase muestra un bloque de código con un objeto `firebaseConfig`, parecido a este:

   ```js
   const firebaseConfig = {
     apiKey: "AIza...",
     authDomain: "equipos-base-empresas.firebaseapp.com",
     projectId: "equipos-base-empresas",
     appId: "1:1234567890:web:abc123",
   };
   ```

3. **Pegarlo en la web.** Abrí `web/public/js/config.js` y reemplazá los valores de ejemplo (`TU_API_KEY`, `TU_PROYECTO`, `TU_APP_ID`) por los de tu `firebaseConfig`. Dejá `authMode: "firebase"`. Estas claves son públicas por diseño: quien controla el acceso es la API, no la web.

4. **Indicar el proyecto a la herramienta de Firebase.** Copiá el archivo de ejemplo:

   ```bash
   cp web/.firebaserc.example web/.firebaserc
   ```

   Abrilo y verificá que diga el id de tu proyecto (`equipos-base-empresas`).

5. **Dominios autorizados.** En **Authentication** → **Configuración** → **Dominios autorizados**, verificá que estén `equipos-base-empresas.web.app` y `equipos-base-empresas.firebaseapp.com`. Si vas a usar un dominio propio, agregalo acá también.

**Comprobación:** `web/public/js/config.js` ya no tiene ningún `TU_...`.

---

### Paso 2. Crear la infraestructura y publicar la API y la web

**Para qué:** un solo script crea todos los recursos de Google Cloud, construye y publica la API, aplica las migraciones de la base, programa el export de auditoría y publica la web.

Desde la carpeta del repositorio:

```bash
PROYECTO=equipos-base-empresas ADMIN_EMAILS=garaujo@equipos.com.uy ./infra/desplegar.sh todo
```

- `PROYECTO` es el id del proyecto de Google Cloud.
- `ADMIN_EMAILS` es la lista de emails, separados por coma, que quedan como **administradores** la primera vez que entran. No hace falta darlos de alta en la pantalla Usuarios (ver paso 3).

Tarda aproximadamente 20–30 minutos. El script es **idempotente**: si se corta por cualquier motivo, se puede volver a correr y saltea lo que ya existe.

**Qué hace, en orden:**

| Etapa | Qué crea o hace |
| --- | --- |
| `base` | Habilita las APIs de Google necesarias. Crea la cuenta de servicio `empresas-api` con los permisos mínimos (cliente de Cloud SQL, lectura de secretos, encolar en Cloud Tasks, escribir y consultar en BigQuery). Crea la instancia de Cloud SQL (Enterprise, `db-f1-micro`, 10 GB SSD con autoincremento, backups diarios a las 6:00, recuperación a un punto en el tiempo, 14 copias), la base `empresas` y el usuario `empresas_app` con una clave aleatoria. Guarda en Secret Manager la cadena de conexión y dos tokens aleatorios. Crea el bucket privado, la cola de Cloud Tasks, el dataset y la tabla de BigQuery y el repositorio de imágenes en Artifact Registry. |
| `api` | Construye la imagen con Cloud Build y despliega Cloud Run con `AUTH_MODE=firebase`, `TASKS_MODE=cloudtasks`, el bucket, la cola, la tabla de BigQuery y los secretos. Ajusta el pool de conexiones y el máximo de instancias al tamaño de Cloud SQL. La primera vez, completa `API_URL` con la URL que asigna Cloud Run. |
| `migrar` | Crea y ejecuta el Cloud Run job `empresas-migrar`, que aplica las migraciones pendientes. |
| `programar` | Crea el Cloud Scheduler que exporta la auditoría a BigQuery todos los días a las 5:10. |
| `web` | Publica la web con `firebase deploy --only hosting`. |

**Variables opcionales del script:**

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `REGION` | `us-central1` | Región de todos los recursos |
| `TIER` | `db-f1-micro` | Tamaño de Cloud SQL al crearla |
| `DISCO_GB` | `10` | Disco inicial de Cloud SQL. Se puede agrandar pero no achicar; el autoincremento lo agranda solo si hace falta, así que no conviene subirlo de entrada |

**Comprobación:** al final, el script imprime `API en https://empresas-api-...run.app`. Probá:

```bash
URL=$(gcloud run services describe empresas-api --region us-central1 --format 'value(status.url)')
curl -s $URL/api/salud
```

Tiene que responder `{"ok":true}`. Abrí también `https://equipos-base-empresas.web.app`: tiene que aparecer la pantalla de ingreso. Todavía no vas a poder entrar: falta el paso 3.

---

### Paso 3. Dar de alta a los usuarios

**Cómo funciona hoy:** para entrar, cada persona necesita **dos cosas con el mismo email**:

1. Una **cuenta en Firebase Authentication**, que es la que tiene la clave.
2. Un **registro en la pantalla Usuarios** de la aplicación, que dice qué rol tiene. Sin ese registro, la API responde "no tiene acceso a la Base de Empresas".

Además, la API exige que el email de la cuenta esté **verificado**. Las cuentas creadas a mano en la consola de Firebase quedan sin verificar, así que hay que marcarlas (ver 3.3).

> Esto cambia con `specs/SPEC_alta_usuarios_enlace_acceso.md`: el alta pasa a ser un solo paso desde la pantalla Usuarios, sin tocar la consola.

#### 3.1 El primer administrador

Los emails que pusiste en `ADMIN_EMAILS` no necesitan el registro en Usuarios: la primera vez que entran, la API los da de alta sola como administradores. Solo necesitan la cuenta en Firebase.

1. En la consola de Firebase → **Authentication** → pestaña **Usuarios** → **Agregar usuario**. Escribí el email (exactamente el mismo que en `ADMIN_EMAILS`) y una clave provisoria.
2. Marcá el email como verificado (3.3).
3. Entrá a `https://equipos-base-empresas.web.app` con ese email y esa clave.
4. Ya adentro, conviene cambiar la clave: cerrá sesión, tocá "¿Olvidaste tu contraseña?" y seguí el correo que llega.

#### 3.2 El resto de las personas

Para cada persona:

1. **Cuenta en Firebase:** igual que en 3.1, paso 1, y marcar el email como verificado (3.3). Pasale la clave provisoria por un canal seguro, o pedile que use "¿Olvidaste tu contraseña?" para elegir la suya.
2. **Registro en la aplicación:** entrá como administrador → **Usuarios** → *Nuevo* → mismo email, nombre, rol y, si corresponde, el permiso para exportar contactos.

Los roles son: **Administrador/a**, **Data steward**, **Jefe/a de proyecto**, **Coordinador/a de campo** y **Lectura**. Quién ve qué pantalla está en el manual de usuario.

#### 3.3 Marcar el email como verificado

La consola de Firebase no tiene un botón para esto, así que se hace con un comando. Una sola vez, prepará un entorno de Python en la carpeta del repositorio:

```bash
python3.12 -m venv .venv && source .venv/bin/activate && pip install firebase-admin
```

```bash
gcloud auth application-default login
```

```bash
gcloud auth application-default set-quota-project equipos-base-empresas
```

Después, por cada email (con el entorno activado: `source .venv/bin/activate`):

```bash
python -c "import firebase_admin as f; from firebase_admin import auth; f.initialize_app(options={'projectId':'equipos-base-empresas'}); u=auth.get_user_by_email('nombre@equipos.com.uy'); auth.update_user(u.uid, email_verified=True); print('verificado', u.email)"
```

**Comprobación:** la persona entra a la web y ve la pantalla de inicio con su nombre y su rol abajo a la izquierda.

> **Si al tocar "Ingresar" no pasa nada:** hay un error que la web muestra y borra enseguida (está corregido en `specs/SPEC_alta_usuarios_enlace_acceso.md`, R1). Para verlo, abrí las herramientas de desarrollador del navegador (Cmd+Opción+I) → pestaña **Network** → tocá Ingresar → mirá la respuesta de `/api/me`. Los mensajes más comunes están en [Problemas frecuentes](#problemas-frecuentes).

---

### Paso 4. Programar el job del CDR

**Para qué:** todas las noches, el job lee las llamadas nuevas de la base MySQL del CDR de uContact (de campañas y del marcador manual) y las manda a la API, que las cruza por número destino con los teléfonos de la base y las registra como intentos.

**Dónde corre:** la base del CDR es accesible desde fuera de la red de Equipos, así que el job corre en **Google Cloud, como un Cloud Run job programado con Cloud Scheduler**. No hace falta ninguna máquina de Equipos prendida.

> Hoy el job es el script `jobs/cdr/cdr_job.py`, que lee la conexión de variables de entorno y no está integrado al script de despliegue; por eso este paso tiene varios comandos. `specs/SPEC_job_cdr_en_cloud.md` lo integra al sistema y pasa la conexión a la pantalla Configuración.

**Cómo corre sin guardar estado:** un Cloud Run job no tiene disco propio, así que no puede guardar por dónde iba (`estado.json`). En lugar de eso, cada noche relee **los últimos 2 días** (`--dias 2 --no-estado`). Como la API ignora las llamadas que ya recibió (por `uniqueid`), releer no duplica nada; solo agrega las nuevas.

#### 4.1 Guardar la contraseña de MySQL como secreto

```bash
printf '%s' 'LA_CONTRASEÑA' | gcloud secrets create empresas-cdr-mysql-password --replication-policy=automatic --data-file=-
```

Después borrá el comando del historial de la Terminal (`history -c`), porque la contraseña quedó escrita ahí.

#### 4.2 Crear el Cloud Run job

Completá los valores de MySQL (host, puerto, base y usuario) y corré:

```bash
API_URL=$(gcloud run services describe empresas-api --region us-central1 --format 'value(status.url)')
```

```bash
gcloud run jobs deploy empresas-cdr --source jobs/cdr --region us-central1 \
  --service-account empresas-api@equipos-base-empresas.iam.gserviceaccount.com \
  --command python --args cdr_job.py,--dias,2,--no-estado \
  --set-env-vars "MYSQL_HOST=HOST,MYSQL_PORT=3306,MYSQL_DB=uc,MYSQL_USER=USUARIO,API_URL=${API_URL},CDR_TZ=America/Montevideo" \
  --set-secrets "MYSQL_PASSWORD=empresas-cdr-mysql-password:latest,JOB_TOKEN=empresas-job-token:latest" \
  --memory 1Gi --task-timeout 3600 --max-retries 1
```

- `--source jobs/cdr` construye la imagen a partir de esa carpeta con Cloud Build (detecta Python por `requirements.txt`).
- Si la tabla del CDR no se llama `cdr`, o hay que unir con otra tabla, agregá la consulta en `CDR_SQL` (ver `jobs/cdr/README.md`, "Consulta").

#### 4.3 Probarlo y cargar el histórico

Primera corrida, con el período que interese (por ejemplo, desde el 1 de octubre):

```bash
gcloud run jobs execute empresas-cdr --region us-central1 --wait --args cdr_job.py,--desde,2026-10-01,--no-estado
```

Si termina bien, en la consola de Google Cloud → **Cloud Run** → **Jobs** → `empresas-cdr` → la ejecución → **Registros** vas a ver los conteos que devolvió la API (recibidas, internas, no cruzan, intentos nuevos, asociados a ítem, duplicados). En la aplicación, el lote aparece en **Actividad** y la fecha del último lote en la pantalla de inicio.

Si falla con un error de conexión a MySQL que dice que no responde el puerto, lo más probable es que el servidor solo acepte conexiones de IPs autorizadas. Cloud Run sale con IPs que cambian; en ese caso hay que darle una IP fija de salida (Cloud NAT con IP estática, aprox. US$4–6 por mes) y autorizarla en el servidor. Está descripto en `specs/SPEC_job_cdr_en_cloud.md`, sección 6.

#### 4.4 Programarlo a las 4:00

Darle a la cuenta de servicio permiso para ejecutar el job:

```bash
gcloud run jobs add-iam-policy-binding empresas-cdr --region us-central1 \
  --member serviceAccount:empresas-api@equipos-base-empresas.iam.gserviceaccount.com --role roles/run.invoker
```

Crear la programación:

```bash
gcloud scheduler jobs create http empresas-cdr --location us-central1 \
  --schedule "0 4 * * *" --time-zone "America/Montevideo" \
  --uri "https://run.googleapis.com/v2/projects/equipos-base-empresas/locations/us-central1/jobs/empresas-cdr:run" \
  --http-method POST \
  --oauth-service-account-email empresas-api@equipos-base-empresas.iam.gserviceaccount.com
```

**Comprobación:** forzá una corrida programada y mirá que aparezca una ejecución nueva en Cloud Run → Jobs → `empresas-cdr`:

```bash
gcloud scheduler jobs run empresas-cdr --location us-central1
```

**Costo:** una corrida diaria de pocos minutos entra en el tramo gratuito de Cloud Run, y con este son 2 trabajos de Cloud Scheduler (3 gratis por cuenta de facturación). El secreto nuevo también entra en el tramo gratuito de Secret Manager.

> **Alternativa sin Cloud Run:** el mismo script puede correr en cualquier máquina con Python y acceso a la base MySQL, con un timer de systemd o con `launchd`; los pasos están en `jobs/cdr/README.md`. No se recomienda: depende de que esa máquina esté prendida y deja el job fuera del monitoreo de Google Cloud.

---

### Paso 5. Configuración inicial del negocio

Con un usuario administrador, en la aplicación:

1. **Naturalezas jurídicas.** Cargá la hoja "excluidos" del Excel de referencia. Se puede hacer a mano en **Naturalezas jurídicas** o con el script:

   ```bash
   python fase0/cargar_excluidos.py <ruta-del-excel> --api <URL-de-la-API> --token <id-token>
   ```

   El id token es el de tu sesión: en el navegador, con la aplicación abierta, herramientas de desarrollador → **Network** → cualquier pedido a `/api/` → encabezado `Authorization`, el texto después de `Bearer`.

2. **Configuración.** En **Configuración**, revisá y completá:
   - **Meses de enfriamiento** (desde el último contacto efectivo).
   - **Destinos internos del CDR** (extensiones, conferencias, pruebas). La lista sale del experimento A de la fase 0.
   - **Prefijos de salida de la central**, si se marcan con prefijo.
   - **Franjas horarias.**
   - **Formato del CSV de uContact.** Verificalo exportando una muestra chica e importándola en uContact antes del primer estudio real.

3. **Alchemer.** Agregá el bloque estándar de variables a cada cuestionario que se vaya a usar con el sistema: `fase0/alchemer_bloque_estandar.md`.

---

### Paso 6. Verificar que todo funciona

- [ ] `curl -s $URL/api/salud` responde `{"ok":true}`.
- [ ] Un administrador entra a la web y ve la pantalla de inicio.
- [ ] Un segundo usuario, dado de alta según el paso 3.2, entra y ve solo las pantallas de su rol.
- [ ] Una carga chica de prueba (un Excel con 5 empresas) se analiza, se confirma y después se deshace.
- [ ] El job del CDR corrió a mano y su lote aparece en **Actividad**.
- [ ] Al día siguiente, la pantalla de inicio muestra la fecha del lote de las 4:00.

---

## Actualizaciones

Siempre desde la carpeta del repositorio, con el código actualizado (`git pull`).

| Qué cambió | Qué correr |
| --- | --- |
| Código de la API | `PROYECTO=equipos-base-empresas ./infra/desplegar.sh api` |
| Hay una migración nueva (`db/empresas/NNNN_*.sql`) | Primero `./infra/desplegar.sh api` y después `./infra/desplegar.sh migrar` (las dos con `PROYECTO=...`) |
| Web | `PROYECTO=equipos-base-empresas ./infra/desplegar.sh web` |
| Job del CDR (`jobs/cdr/`) | Volver a correr el comando de 4.2 (`gcloud run jobs deploy empresas-cdr ...`) |
| Tamaño de Cloud SQL | `PROYECTO=equipos-base-empresas TIER=db-g1-small ./infra/desplegar.sh redimensionar` (ver [`docs/cambio_a_small.md`](cambio_a_small.md)) |

**Las migraciones se escriben compatibles hacia atrás:** agregan columnas o tablas, no las borran. Así la versión anterior de la API sigue funcionando mientras corren. Una migración ya aplicada nunca se edita: se agrega otra.

**Volver atrás la API.** Cloud Run guarda las revisiones anteriores. Listalas y mandá todo el tráfico a la que funcionaba:

```bash
gcloud run revisions list --service empresas-api --region us-central1
```

```bash
gcloud run services update-traffic empresas-api --region us-central1 --to-revisions <revision>=100
```

**Volver atrás la web.** Consola de Firebase → **Hosting** → historial de versiones → *Revertir* en la versión anterior.

---

## Operación

### Backups y restauración

Cloud SQL hace un backup diario a las 6:00 y guarda los registros para recuperar la base a cualquier momento de los últimos 7 días. Para probar una restauración **sin tocar producción**, se clona la instancia a un momento dado:

```bash
gcloud sql instances clone empresas-pg empresas-pg-prueba --point-in-time '2026-11-02T10:00:00Z'
```

Conviene hacerlo una vez por trimestre (coincide con la auditoría por muestreo del PRD) y **borrar el clon después**, porque cuesta lo mismo que la instancia original mientras exista:

```bash
gcloud sql instances delete empresas-pg-prueba
```

Los archivos subidos quedan en el bucket; la auditoría, además, en BigQuery.

### Monitoreo

| Qué mirar | Dónde |
| --- | --- |
| Errores de la API | Consola de Google Cloud → **Cloud Run** → `empresas-api` → **Registros**, filtrando por severidad ERROR. Cada error no manejado queda con su traza |
| Tareas en segundo plano | Si una carga o ingesta queda en error, la pantalla lo muestra con el mensaje. La cola está en **Cloud Tasks** → `empresas-tareas` |
| Job del CDR | La pantalla de inicio muestra la fecha del último lote. Las ejecuciones y sus registros, en **Cloud Run** → **Jobs** → `empresas-cdr` |
| Export de auditoría | **Cloud Scheduler** → `empresas-auditoria-bq` → resultado de la última ejecución |

**Alertas recomendadas** (Cloud Monitoring → *Alertas* → *Crear política*):

- Errores 5xx de Cloud Run en `empresas-api`.
- Ejecución fallida del job `empresas-cdr`.
- CPU, memoria o almacenamiento de Cloud SQL por encima del 80%. Con `db-f1-micro`, estas alertas son las que avisan que llegó el momento de pasar a `db-g1-small`.

### Rotar los tokens

El token del job (`empresas-job-token`) lo usan el job del CDR y el export de auditoría. Para cambiarlo:

```bash
openssl rand -hex 32 | gcloud secrets versions add empresas-job-token --data-file=-
```

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh api         # la API toma la versión nueva
PROYECTO=equipos-base-empresas ./infra/desplegar.sh programar   # actualiza el Cloud Scheduler de auditoría
```

El job del CDR lee siempre la última versión del secreto, así que no hay que cambiar nada en él.

El token de tareas (`empresas-tarea-token`) se rota igual y solo requiere redesplegar la API.

### Seguridad y Ley 18.331

- La API rechaza todo pedido sin un token válido de Firebase o de un email que no esté registrado y activo en Usuarios. Los permisos por rol se validan en la API, no en la web.
- El bucket es privado (acceso uniforme y prevención de acceso público).
- La base de datos no tiene IP pública para usuarios: Cloud Run entra por el conector de Cloud SQL.
- Exportar contactos personales requiere un permiso específico por usuario y queda auditado.
- **Pendiente legal antes de operar con datos reales:** inscripción de la base ante la URCDP y plazo de conservación de los contactos que no se usan. Como los datos quedan en Estados Unidos (Iowa), también conviene que legal confirme el encuadre de la transferencia internacional de datos personales (Google ofrece cláusulas contractuales en su acuerdo de procesamiento de datos).

---

## Desarrollo local en la Mac

Para trabajar en el código sin tocar producción. Requiere lo instalado en [Preparar la Mac](#preparar-la-mac).

### Postgres

Arrancar Postgres como servicio:

```bash
brew services start postgresql@16
```

`postgresql@16` no se agrega solo al `PATH`. Para tener `psql` y `createdb` en la Terminal (en Apple Silicon; en Intel, la ruta es `/usr/local/opt/postgresql@16/bin`):

```bash
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

Homebrew crea el superusuario de Postgres con tu usuario de macOS, no con `postgres`. Para que los comandos de esta guía y los tests funcionen tal cual, creá una vez el rol `postgres`:

```bash
createuser -s postgres
```

### Entorno de Python

Homebrew no deja instalar paquetes en el Python del sistema (error "externally-managed-environment"), así que se usa un entorno virtual en la carpeta del repositorio:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
```

```bash
pip install -r api/requirements-dev.txt
```

En cada Terminal nueva hay que activarlo otra vez con `source .venv/bin/activate`, desde la carpeta del repositorio.

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

El script de la demo aplica las migraciones y carga datos ficticios en una base vacía. Abrí http://localhost:8080. Si `config.js` no tiene Firebase configurado, la web entra en **modo dev**: se ingresa con el email de un usuario registrado (por ejemplo `admin@equipos.com.uy`, de la demo) sin clave.

**Nunca despliegues con `AUTH_MODE=dev`:** cualquiera podría entrar con cualquier email.

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

Los tests de la API usan un Postgres real: cada test migra un esquema limpio. Cubren los criterios de aceptación de R1.1 a R1.13, incluido el control de que ninguna empresa excluida, en no llamar o en enfriamiento entra a una muestra ni a un CSV, y que toda muestra se reproduce con su semilla.

### Manual de usuario en PDF

Necesita Playwright con su Chromium, instalados una vez dentro de `docs/build`:

```bash
(cd docs/build && npm install && npx playwright install chromium)
```

```bash
pip install markdown pypdf
```

Con la aplicación levantada con la demo, en otra Terminal:

```bash
node docs/build/capturas.js http://localhost:8080 docs/manual/img <rut> api/demo/clima_parte_a_ola1.sav <base.csv>
```

```bash
python docs/build/generar_pdfs.py
```

---

## Variables de entorno de la API

Las fija `infra/desplegar.sh`; esta tabla es de referencia.

| Variable | Valor en producción | Qué es |
| --- | --- | --- |
| `DATABASE_URL` | Secreto `empresas-database-url` | `postgresql://usuario:clave@/empresas?host=/cloudsql/PROYECTO:REGION:INSTANCIA` |
| `DB_POOL_MAX` | 5 con `db-f1-micro`, 8 con `db-g1-small` | Conexiones a Postgres por instancia de la API |
| `AUTH_MODE` | `firebase` | `dev` solo en local y en tests |
| `FIREBASE_PROJECT_ID` | Id del proyecto | Para validar los tokens de ingreso |
| `ADMIN_EMAILS` | Emails separados por coma | Quedan como administradores en su primer ingreso |
| `JOB_TOKEN` | Secreto `empresas-job-token` | Autentica al job del CDR y al export de auditoría |
| `TAREA_TOKEN` | Secreto `empresas-tarea-token` | Autentica a Cloud Tasks |
| `TASKS_MODE` | `cloudtasks` | `background` en local, `inline` en tests |
| `TASKS_QUEUE` | `projects/…/queues/empresas-tareas` | Cola de Cloud Tasks |
| `API_URL` | URL de Cloud Run | A dónde llama Cloud Tasks |
| `STORAGE_BUCKET` | Nombre del bucket | Sin bucket, los archivos van a `STORAGE_DIR` (solo en local) |
| `BQ_TABLA_AUDITORIA` | `proyecto.empresas_auditoria.auditoria` | Destino del export diario |
| `CORS_ORIGINS` | Vacío | Solo si la web se sirve desde otro dominio |
| `APP_TZ` | `America/Montevideo` | Zona horaria de franjas y fechas |

Variables del job del CDR (Cloud Run job `empresas-cdr`): `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DB`, `MYSQL_USER`, `MYSQL_PASSWORD` (secreto), `API_URL`, `JOB_TOKEN` (secreto), `CDR_TZ` y, si hace falta, `CDR_SQL` y `LOTE_TAMANO`. El detalle está en `jobs/cdr/README.md`.

---

## Problemas frecuentes

| Qué pasa | Causa probable | Qué hacer |
| --- | --- | --- |
| Al tocar "Ingresar" no pasa nada | La API rechazó el ingreso y la web borra el mensaje enseguida | Mirar la respuesta de `/api/me` en las herramientas de desarrollador → **Network** (ver paso 3) |
| "El usuario no tiene email verificado" | La cuenta se creó a mano en la consola de Firebase | Marcar el email como verificado (paso 3.3) |
| "no tiene acceso a la Base de Empresas" | El email no está en **Usuarios** o está inactivo | Agregarlo o reactivarlo con su rol |
| "Token inválido" | Reloj del equipo desfasado o sesión vencida | Cerrar sesión y volver a entrar; verificar la hora del equipo |
| Pantalla "Falta configurar Firebase" | `config.js` tiene los valores de ejemplo | Completar `firebaseConfig` (paso 1) y correr `./infra/desplegar.sh web` |
| Una carga queda "analizando" mucho tiempo | La tarea falló o la cola está pausada | Ver **Cloud Tasks** y los registros de Cloud Run; la pantalla muestra el error |
| El CSV sale con menos renglones de lo esperado | Ítems sin teléfono discable o ya completos en la parte | El resumen de la exportación lo detalla |
| El job del CDR falla con un error de MySQL que dice que no responde el puerto | El servidor solo acepta IPs autorizadas | IP fija de salida (paso 4.3) |
| El job del CDR falla con "Access denied" | Usuario o contraseña de MySQL incorrectos | Revisar `MYSQL_USER` y agregar una versión nueva del secreto `empresas-cdr-mysql-password` |
| El job del CDR termina con código 1 | La API no respondió | La próxima corrida relee los últimos 2 días y lo recupera |
| "Archivo demasiado grande" | El archivo pasa los 30 MB | Pasar el Excel a CSV o partirlo |
| `error: externally-managed-environment` al hacer `pip install` | Se usó el Python de Homebrew sin entorno virtual | Activar `.venv` (ver [Entorno de Python](#entorno-de-python)) |
| `zsh: command not found: createdb` o `psql` | `postgresql@16` no está en el `PATH` | Agregarlo a `~/.zshrc` (ver [Postgres](#postgres)) |
| `role "postgres" does not exist` | El Postgres de Homebrew usa tu usuario de macOS | `createuser -s postgres` |
| `zsh: command not found: gcloud` | La Terminal se abrió antes de instalar el SDK | Abrir una Terminal nueva |
| El puerto 5432 está ocupado | Hay otro Postgres corriendo (por ejemplo, Postgres.app) | Cerrar el otro, o `brew services stop postgresql@16` y apuntar `DATABASE_URL` al que ya está |
| `remaining connection slots are reserved` o `too many clients` | La API pidió más conexiones de las que admite `db-f1-micro` | Pasar a `db-g1-small` ([`docs/cambio_a_small.md`](cambio_a_small.md)) |
| Cargas grandes o sorteos muy lentos | `db-f1-micro` tiene poca CPU y memoria | Ídem |
