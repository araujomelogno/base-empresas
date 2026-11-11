# Guía de despliegue

Esta guía explica cómo poner en producción la Base de Empresas en un proyecto propio de Google Cloud, cómo actualizarla después, cómo operarla y cómo trabajar en local. Está escrita para hacerse de arriba hacia abajo, en orden, desde una **Mac**.

Describe el sistema **tal como está hoy en el repositorio**, incluidos los dos cambios ya implementados:

- `specs/SPEC_alta_usuarios_enlace_acceso.md`: los usuarios se dan de alta solo desde la aplicación y reciben un enlace por correo (paso 3).
- `specs/SPEC_job_cdr_en_cloud.md`: el job del CDR es parte del sistema, corre en Google Cloud y su conexión se configura desde la aplicación (paso 4).

Si ya tenés una instalación anterior a esos cambios, no hace falta empezar de cero: [`docs/despliegue_alta_usuarios.md`](despliegue_alta_usuarios.md) lleva a producción el alta con enlace, [`docs/despliegue_job_cdr.md`](despliegue_job_cdr.md), el job del CDR en Google Cloud, y [`docs/despliegue_carga_v2.md`](despliegue_carga_v2.md), la carga v2 con atributos y origen del teléfono.

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
  - [Paso 4. Conectar el CDR](#paso-4-conectar-el-cdr)
  - [Paso 5. Configuración inicial del negocio](#paso-5-configuración-inicial-del-negocio)
  - [Paso 6. Verificar que todo funciona](#paso-6-verificar-que-todo-funciona)
- [Actualizaciones](#actualizaciones)
  - [Pasar el job del CDR a Google Cloud (instalación existente)](#pasar-el-job-del-cdr-a-google-cloud-instalación-existente)
- [Operación](#operación)
- [Desarrollo local en la Mac](#desarrollo-local-en-la-mac)
- [Variables de entorno de la API](#variables-de-entorno-de-la-api)
- [Problemas frecuentes](#problemas-frecuentes)

---

## Qué vas a tener al terminar

- La aplicación web publicada en `https://<proyecto>.web.app`, con ingreso por email y clave.
- La API corriendo en Cloud Run, con su base de datos Postgres en Cloud SQL, backups diarios y migraciones aplicadas.
- El export diario de la auditoría a BigQuery.
- El job que lee el CDR de uContact todas las noches y carga los intentos de llamada, con su conexión configurada desde la aplicación.
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
| Datos de la base MySQL del CDR: host, puerto, base, usuario de solo lectura y contraseña | Se cargan en la aplicación, Configuración → CDR (paso 4) | Quien administra uContact o la base `uc` |
| Acceso a la cuenta de Google de `notificaciones@equipos.com.uy`, con verificación en dos pasos | Contraseña de aplicación para mandar los enlaces de acceso (paso 1) | Operaciones |
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
| Secretos | Secret Manager | `empresas-database-url` (conexión a Postgres), `empresas-job-token` y `empresas-tarea-token` (autentican los procesos automáticos ante la API), `empresas-smtp-password` (correo de acceso) y `empresas-cdr-mysql-password` (contraseña de MySQL del CDR, que se carga desde la aplicación) |
| Correo de acceso | SMTP de Google Workspace (`notificaciones@equipos.com.uy`) | Enlace para que cada usuario nuevo cree su contraseña |
| Auditoría histórica | BigQuery, tabla `empresas_auditoria.auditoria` | Copia diaria de la auditoría a las 5:10, para consultas largas |
| Job del CDR | Cloud Run job `empresas-cdr` (misma imagen de la API, `python -m app.jobs.cdr_job`) + Cloud Scheduler a las 4:00 | Lee las llamadas nuevas de la base MySQL del CDR, las cruza con los teléfonos de la base y las registra como intentos. Guarda por dónde va y cada corrida en Postgres |

Todo está en la región **Iowa (`us-central1`)**, salvo el dataset de BigQuery, que queda en la multirregión `US` (decisión D27 en `docs/decisiones.md`).

**Sobre el CDR:** la base MySQL del CDR es accesible desde internet, así que el job corre en Google Cloud y no depende de ninguna máquina de Equipos. Los datos de conexión se cargan en la pantalla **Configuración → CDR**; la contraseña va a Secret Manager y nunca se muestra ni se guarda en la base (decisión D33).

### Tamaño inicial de la base de datos

La base arranca con el tamaño más chico de Cloud SQL, **`db-f1-micro`**: núcleo compartido, 0,6 GB de memoria, hasta 25 conexiones y sin SLA de Google. Se eligió para que el costo inicial sea mínimo (decisión D31).

Para no superar esas 25 conexiones, el script despliega la API con **5 conexiones por instancia (`DB_POOL_MAX=5`) y un máximo de 3 instancias** de Cloud Run.

Cuando el uso crezca, se pasa a `db-g1-small` con un solo comando y unos minutos sin servicio. Las señales para hacerlo y el paso a paso están en [`docs/cambio_a_small.md`](cambio_a_small.md).

---

## Cuánto cuesta

Aproximadamente **US$10–25 por mes** con el tamaño inicial. Casi todo es Cloud SQL, que se paga por hora mientras la instancia exista, aunque nadie la use (unos US$10–14). Cloud Run, Cloud Tasks, Cloud Scheduler, Storage, Secret Manager, BigQuery y Firebase quedan dentro de sus tramos gratuitos con el volumen previsto. El job del CDR en Cloud Run (paso 4) también entra en el tramo gratuito. Solo si el servidor MySQL filtra por IP hace falta una IP de salida fija, que suma unos US$4–6 por mes.

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

5. **Dominios autorizados.** En **Authentication** → **Configuración** → **Dominios autorizados**, verificá que estén `equipos-base-empresas.web.app` y `equipos-base-empresas.firebaseapp.com`. Si vas a usar un dominio propio, agregalo acá también. El enlace de acceso que llega por correo vuelve a esa dirección (`APP_URL`).

6. **Contraseña de aplicación para el correo de acceso.** La API manda el enlace para crear la contraseña desde `notificaciones@equipos.com.uy` por el SMTP de Google Workspace. Necesita una contraseña de aplicación **nueva y exclusiva de este proyecto**, para poder revocarla sin afectar a `paneles` ni a `plataforma-informes-ec`. En la cuenta de Google de `notificaciones@` → **Seguridad** → **Contraseñas de aplicaciones** → crear una con el nombre **Base de Empresas** y guardarla en Secret Manager:

   ```bash
   printf '%s' 'CONTRASEÑA-DE-APLICACION' | gcloud secrets create empresas-smtp-password --project equipos-base-empresas --data-file=-
   ```

   Si salteás este punto, el script del paso 2 la pide por la Terminal sin mostrarla.

**Comprobación:** `web/public/js/config.js` ya no tiene ningún `TU_...`.

---

### Paso 2. Crear la infraestructura y publicar la API y la web

**Para qué:** un solo script crea todos los recursos de Google Cloud, construye y publica la API, aplica las migraciones de la base, crea el job del CDR, programa el export de auditoría, publica la web y manda el enlace de acceso a los administradores iniciales.

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
| `base` | Habilita las APIs de Google necesarias. Crea la cuenta de servicio `empresas-api` con los permisos mínimos (cliente de Cloud SQL, lectura de secretos, encolar en Cloud Tasks, escribir y consultar en BigQuery y **Firebase Authentication Admin**, para crear cuentas y generar enlaces de acceso). Crea la instancia de Cloud SQL (Enterprise, `db-f1-micro`, 10 GB SSD con autoincremento, backups diarios a las 6:00, recuperación a un punto en el tiempo, 14 copias), la base `empresas` y el usuario `empresas_app` con una clave aleatoria. Guarda en Secret Manager la cadena de conexión, dos tokens aleatorios y la contraseña de aplicación del correo (la pide si no existe). Crea el bucket privado, la cola de Cloud Tasks, el dataset y la tabla de BigQuery y el repositorio de imágenes en Artifact Registry. |
| `api` | Construye la imagen con Cloud Build y despliega Cloud Run con `AUTH_MODE=firebase`, `TASKS_MODE=cloudtasks`, el bucket, la cola, la tabla de BigQuery y los secretos. Ajusta el pool de conexiones y el máximo de instancias al tamaño de Cloud SQL. La primera vez, completa `API_URL` con la URL que asigna Cloud Run. |
| `migrar` | Crea y ejecuta el Cloud Run job `empresas-migrar`, que aplica las migraciones pendientes. |
| `cdr` | Crea el secreto vacío `empresas-cdr-mysql-password` (con permiso de la cuenta de servicio solo sobre ese secreto), el Cloud Run job `empresas-cdr` con la misma imagen de la API y el Cloud Scheduler que lo ejecuta todos los días a las 4:00 (hora de Montevideo). El job queda **inactivo** hasta que se cargue la conexión en la aplicación (paso 4). |
| `programar` | Crea el Cloud Scheduler que exporta la auditoría a BigQuery todos los días a las 5:10. |
| `web` | Publica la web con `firebase deploy --only hosting`. |
| `invitar` | Crea la cuenta de Firebase de cada email de `ADMIN_EMAILS` y le manda su **enlace de acceso** por correo. Si el correo falla, imprime el enlace en la Terminal una sola vez (vence en una hora). |

**Variables opcionales del script:**

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `REGION` | `us-central1` | Región de todos los recursos |
| `TIER` | `db-f1-micro` | Tamaño de Cloud SQL al crearla |
| `DISCO_GB` | `10` | Disco inicial de Cloud SQL. Se puede agrandar pero no achicar; el autoincremento lo agranda solo si hace falta, así que no conviene subirlo de entrada |
| `APP_URL` | `https://<proyecto>.web.app` | Dirección de la web: destino del enlace de acceso. Si se usa un dominio propio, ponerlo acá y en los dominios autorizados de Firebase |
| `IP_FIJA` | vacío | `1` para que la API y el job del CDR salgan a internet con una IP fija (solo si el MySQL del CDR filtra por IP; ver paso 4) |

**Comprobación:** al final, el script imprime `API en https://empresas-api-...run.app`. Probá:

```bash
URL=$(gcloud run services describe empresas-api --region us-central1 --format 'value(status.url)')
curl -s $URL/api/salud
```

Tiene que responder `{"ok":true}`. Abrí también `https://equipos-base-empresas.web.app`: tiene que aparecer la pantalla de ingreso. Para entrar, seguí el paso 3.

---

### Paso 3. Dar de alta a los usuarios

**Cómo funciona:** el alta se hace **solo desde la pantalla Usuarios** de la aplicación. Ahí se crea la cuenta de Firebase y a la persona le llega un correo de `notificaciones@equipos.com.uy` con un enlace para crear su contraseña. No hace falta tocar la consola de Firebase.

#### 3.1 El primer administrador

Al terminar el paso 2, a cada email de `ADMIN_EMAILS` le llega el correo con el enlace. Lo abre, elige la contraseña y entra a `https://equipos-base-empresas.web.app` como administrador.

Si el enlace venció (dura una hora) o se perdió, pedí uno nuevo:

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh invitar
```

También sirve, desde el login, escribir el email y tocar «¿Olvidaste tu contraseña?».

#### 3.2 El resto de las personas

El administrador entra a **Usuarios** → *Nuevo* → email, nombre, rol y, si corresponde, el permiso para exportar contactos. A la persona le llega el mismo correo. Si el correo no sale, la pantalla muestra el motivo y el enlace **una sola vez**, para pasarlo por otro canal. «Reenviar acceso» manda un enlace nuevo cuando hace falta.

Los roles son: **Administrador/a**, **Data steward**, **Jefe/a de proyecto**, **Coordinador/a de campo** y **Lectura**. Quién ve qué pantalla está en el manual de usuario.

#### 3.3 Cerrar el registro público

Con el alta verificada, en la consola de Firebase → **Authentication** → **Configuración** → **Acciones del usuario**, desmarcá la creación de cuentas (*Enable create (sign-up)*), para que solo la API pueda crear cuentas. Esa opción aparece en los proyectos con Firebase Authentication with Identity Platform; si no aparece, no hace falta: la web no ofrece registrarse y la API rechaza a quien no está en **Usuarios**.

**Comprobación:** la persona entra a la web y ve la pantalla de inicio con su nombre y su rol abajo a la izquierda. Si no puede entrar, el login dice por qué (no está dado de alta, acceso desactivado, clave incorrecta o error de conexión); los mensajes están en [Problemas frecuentes](#problemas-frecuentes).

---

### Paso 4. Conectar el CDR

**Para qué:** todas las noches a las 4:00, el job lee las llamadas nuevas de la base MySQL del CDR de uContact (de campañas y del marcador manual), las cruza por número destino con los teléfonos de la base y las registra como intentos.

**Dónde corre:** en Google Cloud, como el Cloud Run job `empresas-cdr` que creó el paso 2, programado con Cloud Scheduler. No hace falta ninguna máquina de Equipos prendida. El job guarda en Postgres por dónde va (la fecha y los `uniqueid` de la última llamada leída), así que cada noche lee solo lo nuevo, y deja registro de cada corrida.

**Dónde se configura:** en la aplicación. Todo este paso lo hace un administrador desde el navegador.

#### 4.1 Cargar la conexión

En **Configuración** → tarjeta **CDR — conexión a la base de uContact**:

1. Completá **Servidor (host)**, **Puerto** (normalmente 3306), **Base** (por ejemplo `uc`), **Usuario (solo lectura)** y **Tabla** (`cdr`, salvo que en el servidor se llame distinto).
2. **Cifrado (TLS):** dejá «preferido». Si el servidor exige conexión cifrada, poné «requerido»; si no la soporta, «desactivado».
3. **Zona horaria de calldate:** la del servidor MySQL, normalmente `America/Montevideo`. **Llamadas por lote** puede quedar en 2000.
4. **Consulta propia (opcional):** solo si la tabla tiene otro nombre de columnas o hay que unir con otra tabla. Tiene que ser un `SELECT` con un `%s` para la fecha desde (y opcionalmente otro para la fecha hasta) y devolver las columnas `uniqueid`, `calldate`, `dst`, `duration`, `billsec`, `disposition`, `userfield` y `peeraccount` (con `AS` si se llaman distinto).
5. Escribí la **Contraseña de MySQL** y tocá **Guardar contraseña**. Va directo a Secret Manager (`empresas-cdr-mysql-password`): no se guarda en la base, no aparece en la auditoría ni en los registros, y la pantalla nunca la vuelve a mostrar. Solo dice «configurada», cuándo y por quién. Para cambiarla, se escribe otra y se guarda.

#### 4.2 Probar la conexión

Tocá **Probar conexión**. Conecta en 10 segundos como máximo, lee una muestra de las últimas 24 horas y muestra:

- si conectó, la versión de MySQL, si la conexión va cifrada y cuántas llamadas trajo la muestra;
- si falló, el motivo: no se resuelve el host, no responde el puerto, usuario o contraseña incorrectos, la base o la tabla no existe, falta permiso, error de TLS o faltan columnas en la consulta.

Si dice **«No responde el puerto»** y el servidor está prendido, casi seguro filtra por IP de origen: seguí con [4.5](#45-ip-fija-de-salida-solo-si-el-servidor-filtra-por-ip).

#### 4.3 Activar y cargar el histórico

1. Marcá **Job del CDR activo** y tocá **Guardar nueva versión** (la configuración queda versionada y auditada como el resto). Si falta el host, la base o el usuario, no deja activarlo.
2. En **Reprocesar desde**, elegí la fecha desde la que querés cargar llamadas (por ejemplo, el inicio del primer estudio) y tocá **Reprocesar**. Para ver qué haría sin escribir nada, marcá antes **Prueba sin guardar intentos (dry-run)**: deja el resumen en el bucket (`cdr/dry-run/`) y no avanza el estado.
3. La pantalla sigue la corrida y muestra los conteos al terminar: recibidas, internas, no cruzan, intentos nuevos, asociados a ítem, duplicados.

Reprocesar no duplica nada: la API ignora las llamadas que ya tiene (por `uniqueid`). Y nunca hace retroceder el estado del job: la corrida de esa noche sigue desde donde iba.

#### 4.4 Comprobar la corrida programada

Para no esperar a las 4:00, forzá una corrida programada:

```bash
gcloud scheduler jobs run empresas-cdr --location us-central1
```

A los pocos minutos, la corrida aparece en **Actividad** → **Corridas del job del CDR** con origen «programada». Las ejecuciones y sus registros también están en la consola de Google Cloud → **Cloud Run** → **Jobs** → `empresas-cdr`.

**Si algo falla**, la pantalla de inicio de administradores y coordinadores muestra un aviso: cuando la última corrida programada terminó en error, o cuando pasaron 26 horas sin ninguna corrida con el job activo.

#### 4.5 IP fija de salida (solo si el servidor filtra por IP)

Cloud Run sale a internet con IPs que cambian. Si el servidor MySQL solo acepta IPs autorizadas, la API (por «Probar conexión») y el job tienen que salir con una IP fija:

```bash
PROYECTO=equipos-base-empresas IP_FIJA=1 ./infra/desplegar.sh api
```

```bash
PROYECTO=equipos-base-empresas IP_FIJA=1 ./infra/desplegar.sh cdr
```

El script crea una red (`empresas-vpc`), un Cloud Router, Cloud NAT y una IP estática (`empresas-salida-ip`), e **imprime la IP**. Pedile a quien administra el servidor MySQL que la autorice y volvé a tocar **Probar conexión**. Cuesta unos US$4–6 por mes (ver `docs/costos.md`).

Desde ahí, **todo despliegue posterior de la API o del job se hace con `IP_FIJA=1`**; si no, vuelven a salir sin IP fija.

**Costo del paso:** una corrida diaria de pocos minutos entra en el tramo gratuito de Cloud Run; con este son 2 trabajos de Cloud Scheduler (3 gratis por cuenta de facturación), y el secreto entra en el tramo gratuito de Secret Manager.

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
- [ ] Un segundo usuario, dado de alta desde **Usuarios** (paso 3.2), recibe el correo, crea su contraseña, entra y ve solo las pantallas de su rol.
- [ ] Una carga chica de prueba (un Excel con 5 empresas) se analiza, se confirma y después se deshace.
- [ ] En **Configuración → CDR**, «Probar conexión» responde que conectó.
- [ ] La corrida de «Reprocesar desde…» terminó en «ok» y aparece en **Actividad** con sus conteos.
- [ ] «Correr ahora» (en **Configuración → CDR**) lanza una corrida que termina en «ok». Lo mismo desde la Terminal: `gcloud run jobs execute empresas-cdr --region us-central1`.
- [ ] Al día siguiente, la pantalla de inicio muestra la corrida programada de las 4:00 y no hay aviso del CDR.

---

## Actualizaciones

Siempre desde la carpeta del repositorio, con el código actualizado (`git pull`).

| Qué cambió | Qué correr |
| --- | --- |
| Código de la API | `PROYECTO=equipos-base-empresas ./infra/desplegar.sh api` |
| Hay una migración nueva (`db/empresas/NNNN_*.sql`) | Primero `./infra/desplegar.sh api` y después `./infra/desplegar.sh migrar` (las dos con `PROYECTO=...`) |
| Web | `PROYECTO=equipos-base-empresas ./infra/desplegar.sh web` |
| Job del CDR (`api/app/jobs/`) | Nada aparte: `./infra/desplegar.sh api` actualiza también la imagen del job `empresas-cdr`. Si se usa IP fija, siempre con `IP_FIJA=1` |
| Conexión al MySQL del CDR | Nada que desplegar: se cambia en **Configuración → CDR** |
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

### Pasar el job del CDR a Google Cloud (instalación existente)

Para una instalación que ya corría el script anterior (`jobs/cdr/cdr_job.py`, en un servidor, una Mac o un Cloud Run job creado a mano). Esto es el resumen; la guía completa, con la verificación, qué hacer si algo sale mal y cómo volver atrás, está en [`docs/despliegue_job_cdr.md`](despliegue_job_cdr.md).

1. Traé el repositorio al día y publicá la API nueva, la migración `0005_cdr_en_cloud.sql` (tablas `cdr_estado` y `cdr_corrida`), el job y la web:

   ```bash
   PROYECTO=equipos-base-empresas ./infra/desplegar.sh api
   ```

   ```bash
   PROYECTO=equipos-base-empresas ./infra/desplegar.sh migrar
   ```

   ```bash
   PROYECTO=equipos-base-empresas ./infra/desplegar.sh cdr
   ```

   ```bash
   PROYECTO=equipos-base-empresas ./infra/desplegar.sh web
   ```

   `cdr` reemplaza el Cloud Run job `empresas-cdr` y su Cloud Scheduler si se habían creado a mano, y reutiliza el secreto `empresas-cdr-mysql-password` si ya existía.

2. **Apagá el job anterior** donde corría, para que no haya dos cargando lo mismo. En Linux: `sudo systemctl disable --now cdr-job.timer`. En una Mac: `launchctl unload ~/Library/LaunchAgents/uy.equipos.cdr-job.plist`. Si tenía un `estado.json`, ya no se usa.
3. Seguí el [paso 4](#paso-4-conectar-el-cdr): cargá la conexión, probala, activá el job y reprocesá desde la fecha del último lote que había cargado el job anterior (se ve en **Actividad**). Las llamadas repetidas se ignoran, así que no pasa nada si la fecha se superpone.

**Volver atrás:** redirigir el tráfico de Cloud Run a la revisión anterior de la API y pausar el Cloud Scheduler `empresas-cdr` (`gcloud scheduler jobs pause empresas-cdr --location us-central1`). La migración 0005 solo agrega tablas y una columna, así que puede quedar aplicada.

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
| Job del CDR | La pantalla de inicio muestra la última corrida y un aviso si la última programada falló o si pasaron 26 horas sin corridas. El historial, en **Actividad** → **Corridas del job del CDR**. Las ejecuciones y sus registros, en **Cloud Run** → **Jobs** → `empresas-cdr` |
| Export de auditoría | **Cloud Scheduler** → `empresas-auditoria-bq` → resultado de la última ejecución |

**Correr el job del CDR fuera de hora:** desde la aplicación, **Configuración → CDR** → «Correr ahora» (o «Reprocesar desde…» para releer un período). Desde la Terminal:

```bash
gcloud run jobs execute empresas-cdr --region us-central1
```

Las dos formas dejan la corrida en **Actividad**. No se puede lanzar una mientras haya otra en curso.

**Alertas recomendadas** (Cloud Monitoring → *Alertas* → *Crear política*):

- Errores 5xx de Cloud Run en `empresas-api`.
- Ejecución fallida del job `empresas-cdr`.
- CPU, memoria o almacenamiento de Cloud SQL por encima del 80%. Con `db-f1-micro`, estas alertas son las que avisan que llegó el momento de pasar a `db-g1-small`.

### Rotar los tokens

El token del job (`empresas-job-token`) lo usan el export de auditoría y el subcomando `invitar`. El job del CDR no lo usa: escribe directo en la base. Para cambiarlo:

```bash
openssl rand -hex 32 | gcloud secrets versions add empresas-job-token --data-file=-
```

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh api         # la API toma la versión nueva
PROYECTO=equipos-base-empresas ./infra/desplegar.sh programar   # actualiza el Cloud Scheduler de auditoría
```

**Contraseña de MySQL del CDR:** se cambia desde **Configuración → CDR** → **Guardar contraseña**. La API agrega una versión nueva del secreto y deshabilita las anteriores; el job lee siempre la última.

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

Los tests de la API usan un Postgres real: cada test migra un esquema limpio. Los del job del CDR (`api/tests/test_cdr_job.py`) usan un MySQL simulado, así que no hace falta tener uno. Cubren los criterios de aceptación de R1.1 a R1.13, incluido el control de que ninguna empresa excluida, en no llamar o en enfriamiento entra a una muestra ni a un CSV, y que toda muestra se reproduce con su semilla.

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
| `JOB_TOKEN` | Secreto `empresas-job-token` | Autentica al export de auditoría y al subcomando `invitar` |
| `TAREA_TOKEN` | Secreto `empresas-tarea-token` | Autentica a Cloud Tasks |
| `TASKS_MODE` | `cloudtasks` | `background` en local, `inline` en tests |
| `TASKS_QUEUE` | `projects/…/queues/empresas-tareas` | Cola de Cloud Tasks |
| `API_URL` | URL de Cloud Run | A dónde llama Cloud Tasks |
| `STORAGE_BUCKET` | Nombre del bucket | Sin bucket, los archivos van a `STORAGE_DIR` (solo en local) |
| `BQ_TABLA_AUDITORIA` | `proyecto.empresas_auditoria.auditoria` | Destino del export diario |
| `CORS_ORIGINS` | Vacío | Solo si la web se sirve desde otro dominio |
| `APP_TZ` | `America/Montevideo` | Zona horaria de franjas y fechas |
| `APP_URL` | `https://<proyecto>.web.app` | Dirección de la web: destino del enlace de acceso |
| `SMTP_PASSWORD` | Secreto `empresas-smtp-password` | Contraseña de aplicación de `notificaciones@` (exclusiva de este proyecto) |
| `SMTP_USUARIO`, `SMTP_HOST`, `SMTP_PORT` | `notificaciones@equipos.com.uy`, `smtp.gmail.com`, `587` | Envío del correo de acceso |
| `GCP_PROYECTO`, `GCP_REGION` | Id del proyecto, `us-central1` | Para Secret Manager y para ejecutar el job del CDR |
| `CDR_JOB` | `empresas-cdr` | Cloud Run job que lanza «Correr ahora». Vacío en local: corre en el mismo proceso |
| `CDR_SECRETO` | `empresas-cdr-mysql-password` | Secreto con la contraseña de MySQL del CDR |
| `SECRETOS` | `secretmanager` (por defecto con `AUTH_MODE=firebase`) | `memoria` en local y en tests |

El job del CDR (Cloud Run job `empresas-cdr`) usa la misma imagen y las mismas variables de base (`DATABASE_URL`, `GCP_PROYECTO`, `GCP_REGION`, `CDR_SECRETO`, `STORAGE_BUCKET`, con `DB_POOL_MAX=3`). Los datos de conexión al MySQL no son variables de entorno: se leen de la configuración vigente (**Configuración → CDR**) y la contraseña, de Secret Manager.

---

## Problemas frecuentes

| Qué pasa | Causa probable | Qué hacer |
| --- | --- | --- |
| "no tiene acceso a la Base de Empresas" | El email no está en **Usuarios** | Darlo de alta en **Usuarios** |
| "Tu acceso está desactivado" | El usuario está inactivo en **Usuarios** | Editarlo y marcarlo como activo |
| "Tu email no está verificado" | Cuenta creada a mano en la consola de Firebase | «Reenviar acceso» en **Usuarios** (la marca verificada y manda un enlace) |
| El correo de acceso figura como **fallido** | Contraseña de aplicación inválida o revocada; el motivo se ve en **Usuarios** | Pasar el enlace que mostró la pantalla por otro canal; revisar `empresas-smtp-password` |
| "El enlace venció" o "ya se usó" al abrir el correo | Los enlaces vencen en una hora | En el login, «¿Olvidaste tu contraseña?», o «Reenviar acceso» en **Usuarios** |
| "Token inválido" | Reloj del equipo desfasado o sesión vencida | Cerrar sesión y volver a entrar; verificar la hora del equipo |
| Pantalla "Falta configurar Firebase" | `config.js` tiene los valores de ejemplo | Completar `firebaseConfig` (paso 1) y correr `./infra/desplegar.sh web` |
| Una carga, ingesta o preview queda "pendiente" y la pantalla avisa que la tarea no arrancó | Cloud Tasks no puede llamar a la API (dirección o token incorrectos, cola pausada) | Buscar en los registros de Cloud Run pedidos a `/api/tareas/` con error (`gcloud logging read 'httpRequest.requestUrl:"/tareas/"' --limit 10`). Corregido el problema, la tarea se ejecuta a mano: `curl -X POST "$URL/api/tareas/NUMERO/ejecutar" -H "X-Tarea-Token: $(gcloud secrets versions access latest --secret empresas-tarea-token)"` |
| Una carga queda "analizando" mucho tiempo | La tarea falló o la cola está pausada | Ver **Cloud Tasks** y los registros de Cloud Run; la pantalla muestra el error |
| El CSV sale con menos renglones de lo esperado | Ítems sin teléfono discable o ya completos en la parte | El resumen de la exportación lo detalla |
| CDR: "No se resuelve el host" | Nombre del servidor mal escrito | Corregir **Servidor (host)** en Configuración → CDR |
| CDR: "No responde el puerto" | Puerto equivocado o el servidor solo acepta IPs autorizadas | Revisar el puerto; si está bien, IP fija de salida ([4.5](#45-ip-fija-de-salida-solo-si-el-servidor-filtra-por-ip)) |
| CDR: "Usuario o contraseña incorrectos" | Usuario o contraseña de MySQL | Corregir el usuario o guardar la contraseña de nuevo |
| CDR: "La base … no existe" o "La tabla del CDR no existe" | Nombre de base o tabla | Corregirlos, o usar una consulta propia |
| CDR: "El usuario no tiene permiso…" | Al usuario de MySQL le falta `SELECT` sobre la tabla | Pedir el permiso a quien administra la base |
| CDR: error de TLS | El servidor exige cifrado, o no lo soporta | Cambiar **Cifrado (TLS)** a «requerido» o «desactivado» según el mensaje |
| CDR: "Faltan columnas en la consulta" | La tabla usa otros nombres de columna | Consulta propia con `AS` (paso 4.1) |
| Aviso en inicio: "La última corrida programada del CDR falló" | Cualquiera de los anteriores, ocurrido de noche | Ver el mensaje en **Actividad**, corregir y «Correr ahora». La corrida siguiente retoma desde donde quedó |
| Aviso en inicio: "No hubo ninguna corrida del CDR en las últimas 26 horas" | Cloud Scheduler pausado o sin permiso para ejecutar el job | **Cloud Scheduler** → `empresas-cdr` → último resultado; `./infra/desplegar.sh cdr` vuelve a dar los permisos |
| «Correr ahora» dice "No se pudo lanzar el job del CDR en Cloud Run" | A la cuenta de servicio le falta permiso sobre el job | `PROYECTO=equipos-base-empresas ./infra/desplegar.sh cdr` |
| "Ya hay una corrida del CDR en curso" | Otra corrida está trabajando | Esperar a que termine; una corrida que quedó colgada se marca en error sola a las 2 horas |
| "Archivo demasiado grande" | El archivo pasa los 30 MB | Pasar el Excel a CSV o partirlo |
| `error: externally-managed-environment` al hacer `pip install` | Se usó el Python de Homebrew sin entorno virtual | Activar `.venv` (ver [Entorno de Python](#entorno-de-python)) |
| `zsh: command not found: createdb` o `psql` | `postgresql@16` no está en el `PATH` | Agregarlo a `~/.zshrc` (ver [Postgres](#postgres)) |
| `role "postgres" does not exist` | El Postgres de Homebrew usa tu usuario de macOS | `createuser -s postgres` |
| `zsh: command not found: gcloud` | La Terminal se abrió antes de instalar el SDK | Abrir una Terminal nueva |
| El puerto 5432 está ocupado | Hay otro Postgres corriendo (por ejemplo, Postgres.app) | Cerrar el otro, o `brew services stop postgresql@16` y apuntar `DATABASE_URL` al que ya está |
| `remaining connection slots are reserved` o `too many clients` | La API pidió más conexiones de las que admite `db-f1-micro` | Pasar a `db-g1-small` ([`docs/cambio_a_small.md`](cambio_a_small.md)) |
| Cargas grandes o sorteos muy lentos | `db-f1-micro` tiene poca CPU y memoria | Ídem |
