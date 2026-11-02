# Despliegue: job del CDR en Google Cloud

Este documento lleva a producción el cambio de [`specs/SPEC_job_cdr_en_cloud.md`](../specs/SPEC_job_cdr_en_cloud.md) sobre una instalación que ya existe (proyecto `equipos-base-empresas`). Para una instalación desde cero alcanza con la [guía de despliegue](despliegue.md), que ya incluye estos pasos (paso 4, "Conectar el CDR").

**Qué cambia:**

- El job del CDR deja de ser un script aparte (`jobs/cdr/`) para instalar en un servidor Ubuntu o en una Mac. Pasa a ser parte de la API y corre en Google Cloud como el **Cloud Run job `empresas-cdr`**, todos los días a las 4:00 (hora de Montevideo), programado con Cloud Scheduler. No depende de ninguna máquina de Equipos.
- La conexión a la base MySQL del CDR se carga desde la aplicación, en **Configuración → CDR**. Ya no hay un archivo `cdr_job.env`.
- La contraseña de MySQL va a Secret Manager (`empresas-cdr-mysql-password`). Nunca se muestra, no se guarda en la base y no aparece en la auditoría ni en los registros.
- «Probar conexión» dice por qué falla, si falla. «Correr ahora» y «Reprocesar desde…» lanzan el job a mano.
- El job guarda en Postgres por dónde va y cada corrida que hace. La pantalla de inicio avisa si la corrida de la noche falló o si no corrió, y **Actividad** muestra el historial.

**Tiempo estimado:** 30 a 45 minutos, más la carga del histórico. La web y la API quedan sin servicio solo los segundos del despliegue de Cloud Run.

## Antes de empezar

| Qué | Dónde | Quién |
| --- | --- | --- |
| Permisos de Owner en el proyecto `equipos-base-empresas` | Google Cloud | Quien despliega |
| La Mac preparada (`gcloud`, `firebase`, repositorio al día) | Ver [despliegue.md](despliegue.md), "Preparar la Mac" | Quien despliega |
| Datos de la base MySQL del CDR: host, puerto, base, tabla, usuario de solo lectura y contraseña | Se cargan en la aplicación (paso 3) | Quien administra uContact o la base `uc` |
| Saber si el servidor MySQL solo acepta conexiones de IPs autorizadas | Si no se sabe, lo detecta «Probar conexión» (paso 4) | Quien administra el servidor |
| Un usuario **administrador** de la aplicación | La pantalla Configuración es solo para administradores | — |
| Dónde corría el job anterior, si estaba instalado (servidor, Mac o Cloud Run job creado a mano) | Para apagarlo en el paso 6 | Quien lo instaló |

Traé el repositorio al día:

```bash
cd ~/base-empresas && git pull
```

## Paso 1 — API y migración

La API nueva trae el job, la pantalla y los endpoints. Primero se publica la API, porque el job usa su misma imagen:

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh api
```

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh migrar
```

- `api` agrega las variables nuevas de la API: `GCP_PROYECTO`, `GCP_REGION`, `CDR_JOB=empresas-cdr` y `CDR_SECRETO=empresas-cdr-mysql-password`. Si ya existe un Cloud Run job `empresas-cdr`, también le actualiza la imagen; si no existe, se crea en el paso 2.
- `migrar` aplica `db/empresas/0005_cdr_en_cloud.sql`: crea `cdr_estado` (por dónde va el job) y `cdr_corrida` (historial de corridas) y agrega `corrida_id` a `cdr_lote`. Es compatible hacia atrás.

**Hacé los pasos 1 y 2 seguidos y lejos de las 4:00.** Si había un Cloud Run job `empresas-cdr` creado a mano, después del paso 1 queda con la imagen nueva pero con los argumentos viejos, y fallaría si el Cloud Scheduler lo ejecuta antes del paso 2.

## Paso 2 — Job, programación y secreto

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh cdr
```

Qué hace:

1. Crea el secreto **vacío** `empresas-cdr-mysql-password`, si no existía, y le da a la cuenta de servicio `empresas-api` permiso para leerlo y agregarle versiones **solo sobre ese secreto**.
2. Crea o actualiza el Cloud Run job `empresas-cdr` con la imagen de la API (`python -m app.jobs.cdr_job`), conectado a Cloud SQL, con hasta una hora por corrida.
3. Le da a la cuenta de servicio permiso para ejecutar el job con argumentos propios: lo usan «Correr ahora» y «Reprocesar desde…».
4. Crea o actualiza el Cloud Scheduler `empresas-cdr`: todos los días a las 4:00, hora de Montevideo.

Salida esperada al final:

```
  Listo. Cargá la conexión en la aplicación: Configuración → CDR (docs/despliegue.md, paso 4).
```

**Si ya existía un Cloud Run job `empresas-cdr` creado a mano** (con la guía anterior, `--source jobs/cdr`), este paso lo reemplaza: le cambia la imagen, los argumentos y las variables, y actualiza su Cloud Scheduler. Si el secreto `empresas-cdr-mysql-password` ya tenía la contraseña, se reutiliza. En ese caso la pantalla la muestra como «configurada», sin fecha ni autor.

Hasta que se active en la aplicación (paso 5), el job corre todas las noches pero no lee nada: cada corrida queda como «omitida», con el motivo.

## Paso 3 — Web

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh web
```

Publica la tarjeta del CDR en **Configuración**, el aviso en **Inicio** y las corridas en **Actividad**. Si alguien tenía la aplicación abierta, tiene que recargar la página.

## Paso 4 — Cargar la conexión y probarla

Con un usuario administrador, en **Configuración** → tarjeta **CDR — conexión a la base de uContact**:

1. Completá **Servidor (host)**, **Puerto** (normalmente 3306), **Base** (por ejemplo `uc`), **Usuario (solo lectura)** y **Tabla** (`cdr`, salvo que en el servidor se llame distinto).
2. **Cifrado (TLS):** dejá «Preferido». Si el servidor exige conexión cifrada, poné «Requerido»; si no la soporta, «Desactivado».
3. **Zona horaria de calldate:** la del servidor MySQL, normalmente `America/Montevideo`. **Llamadas por lote** puede quedar en 2000.
4. **Consulta propia (opcional):** solo si las columnas tienen otros nombres o hay que unir con otra tabla. Tiene que ser un único `SELECT` que devuelva `uniqueid`, `calldate`, `dst`, `duration`, `billsec`, `disposition`, `userfield` y `peeraccount` (con `AS` si se llaman distinto), ordenado por `calldate`, con un `%s` para la fecha desde y, opcionalmente, otro para la fecha hasta.
5. Escribí la **Contraseña de MySQL** y tocá **Guardar contraseña**. Abajo tiene que aparecer «configurada», con la fecha y tu usuario.
6. Tocá **Probar conexión**. Usa los datos del formulario, aunque todavía no estén guardados, y la contraseña guardada.

Resultado esperado: «Conectó. N llamadas de las últimas 24 horas en la muestra.», con la versión de MySQL, si la conexión va cifrada y las columnas que devolvió la consulta.

Si falla, el mensaje dice por qué:

| Mensaje | Qué hacer |
| --- | --- |
| No se resuelve el host | Corregir **Servidor (host)** |
| No responde el puerto | Revisar el puerto. Si está bien, el servidor casi seguro filtra por IP de origen: seguir con el [paso 4b](#paso-4b--ip-fija-de-salida-solo-si-el-servidor-filtra-por-ip) |
| Usuario o contraseña incorrectos | Corregir el usuario, o escribir la contraseña de nuevo y **Guardar contraseña** |
| La base … no existe / La tabla del CDR no existe | Corregir la base o la tabla, o usar una consulta propia |
| El usuario no tiene permiso para leer la base o la tabla del CDR | Pedir `SELECT` sobre la tabla para ese usuario |
| El servidor exige una conexión cifrada / Falló la conexión cifrada (TLS) | Cambiar **Cifrado (TLS)** a «Requerido» o «Desactivado», según el mensaje |
| La consulta del CDR tiene un error de sintaxis / usa una columna que no existe | Revisar la consulta propia |
| Faltan columnas en la consulta | Agregar las columnas que faltan a la consulta propia, con `AS` |

### Paso 4b — IP fija de salida (solo si el servidor filtra por IP)

Cloud Run sale a internet con IPs que cambian. Si el servidor MySQL solo acepta IPs autorizadas, la API (por «Probar conexión») y el job tienen que salir con una IP fija:

```bash
PROYECTO=equipos-base-empresas IP_FIJA=1 ./infra/desplegar.sh api
```

```bash
PROYECTO=equipos-base-empresas IP_FIJA=1 ./infra/desplegar.sh cdr
```

El script habilita la API de Compute Engine y crea la red `empresas-vpc` (subred `empresas-subnet`), la IP estática `empresas-salida-ip`, el Cloud Router `empresas-router` y el Cloud NAT `empresas-nat`. Al final imprime:

```
  IP de salida fija: 34.x.x.x
  Pedí que el servidor MySQL del CDR acepte conexiones desde esa IP.
```

Pedile a quien administra el servidor MySQL que autorice esa IP y volvé a tocar **Probar conexión**.

**Importante:** desde ese momento, **todo despliegue de la API o del job se hace con `IP_FIJA=1`**. Si no, la API y el job vuelven a salir sin IP fija y la conexión deja de funcionar. Cuesta unos US$4–6 por mes (ver [Costos](#costos)).

## Paso 5 — Activar y cargar el histórico

1. Marcá **Job del CDR activo**, escribí un comentario (por ejemplo, "Conexión del CDR en Cloud") y tocá **Guardar nueva versión**. Si falta el host, la base o el usuario, la pantalla no deja activarlo y dice qué falta.
2. Elegí la fecha inicial en **Reprocesar desde**:
   - **Si el job anterior nunca se instaló:** la fecha desde la que interesan las llamadas, por ejemplo el inicio del primer estudio.
   - **Si el job anterior ya cargaba llamadas:** la fecha del último lote que cargó (se ve en **Actividad**). Las llamadas que ya estaban se ignoran, así que no importa si la fecha se superpone.
3. **Opcional, para ver qué haría sin escribir nada:** marcá **Prueba sin guardar intentos (dry-run)** y tocá **Reprocesar**. La corrida cuenta las llamadas y deja el detalle en el bucket (`cdr/dry-run/corrida-N.json`), pero no carga intentos ni avanza el estado.
4. Desmarcá dry-run y tocá **Reprocesar**. La tarjeta sigue la corrida cada 2 segundos y, al terminar, muestra las filas leídas y los intentos nuevos.

El detalle de la corrida (recibidas, internas, no cruzan, intentos nuevos, asociados a ítem, duplicados) queda en **Actividad** → **Corridas del job del CDR**. Las ejecuciones y sus registros también están en la consola de Google Cloud → **Cloud Run** → **Jobs** → `empresas-cdr`.

Un reproceso no hace retroceder el job: la corrida programada de esa noche sigue desde la última llamada que ya había leído.

## Paso 6 — Apagar el job anterior

Si el script anterior estaba instalado en otra máquina, apagalo para que no queden dos procesos leyendo el CDR. El anterior manda a `POST /api/intentos/lote` con el token del job, que sigue funcionando para cargas a mano, así que no fallaría solo: hay que apagarlo.

- **Servidor Linux (systemd):**

  ```bash
  sudo systemctl disable --now cdr-job.timer
  ```

- **Mac (launchd):**

  ```bash
  launchctl unload ~/Library/LaunchAgents/uy.equipos.cdr-job.plist
  ```

- **Cloud Run job creado a mano:** no hay que hacer nada; el paso 2 ya lo reemplazó.

Después se pueden borrar de esa máquina el archivo `cdr_job.env`, que tiene la contraseña de MySQL, y el `estado.json`. El estado ahora vive en Postgres.

## Paso 7 — Verificación

Es la definición de terminado del spec. Marcá cada punto:

- [ ] «Probar conexión» respondió «Conectó» con los datos reales.
- [ ] «Reprocesar desde…» cargó el histórico: la corrida quedó «ok» en **Actividad**, con intentos nuevos.
- [ ] «Correr ahora» lanza una corrida que termina «ok». Mientras está en curso, otro «Correr ahora» responde "Ya hay una corrida del CDR en curso".
- [ ] La corrida programada funciona. Para no esperar a las 4:00, forzala:

  ```bash
  gcloud scheduler jobs run empresas-cdr --location us-central1
  ```

  A los pocos minutos aparece en **Actividad** con origen «programada» y estado «ok».
- [ ] Al día siguiente, la pantalla de inicio muestra la corrida de las 4:00 y **no** hay aviso del CDR.
- [ ] **Prueba de contraseña incorrecta:** escribí una contraseña cualquiera en el campo **sin guardarla** y tocá **Probar conexión**. Tiene que decir «Usuario o contraseña incorrectos», sin mostrar la clave. Después borrá el campo: la contraseña guardada no cambió.
- [ ] La contraseña no aparece en **Auditoría**: el cambio figura como `config.cdr_password`, sin el valor.

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| La corrida falla con `No module named app.jobs` | Se corrió `cdr` antes que `api`: el job quedó con la imagen anterior de la API | Correr el paso 1, que actualiza también la imagen del job |
| Una corrida falla con `can't open file 'cdr_job.py'` | El Cloud Run job creado a mano se ejecutó entre el paso 1 y el 2 | Correr el paso 2 |
| «Guardar contraseña» responde un error de Secret Manager | A la cuenta de servicio le falta el permiso sobre el secreto | Repetir el paso 2 (`./infra/desplegar.sh cdr`) |
| «Correr ahora» dice "No se pudo lanzar el job del CDR en Cloud Run" | Falta el permiso para ejecutar el job, o el job no existe | Repetir el paso 2 |
| La corrida programada queda «omitida» | El job no está activo, falta un parámetro o falta la contraseña; el motivo está en **Actividad** | Completar el paso 4 o el 5 |
| Aviso en inicio: "La última corrida programada del CDR falló" | Algún error de conexión o de consulta, ocurrido de noche | Ver el mensaje en **Actividad**, «Probar conexión», corregir y «Correr ahora». La corrida siguiente retoma desde donde quedó |
| Aviso en inicio: "No hubo ninguna corrida del CDR en las últimas 26 horas" | Cloud Scheduler pausado, borrado o sin permiso | Consola → **Cloud Scheduler** → `empresas-cdr` → último resultado. Repetir el paso 2 |
| «Probar conexión» funcionaba y después de un despliegue dice "No responde el puerto" | Se desplegó sin `IP_FIJA=1` y se perdió la IP fija | Redesplegar `api` y `cdr` con `IP_FIJA=1` (paso 4b). La IP no cambia: es la misma reservada |
| Una corrida queda «en curso» para siempre | La ejecución se cortó (por ejemplo, superó la hora) | Pasadas 2 horas se marca sola como error. Si la causa es el volumen, reprocesar por tramos más cortos con **Hasta** |
| Aparecen intentos duplicados | No pasa: la API ignora las llamadas que ya tiene por `uniqueid` | Si los conteos muestran «duplicados», es el comportamiento esperado |

**Volver atrás:**

1. Pausá la programación:

   ```bash
   gcloud scheduler jobs pause empresas-cdr --location us-central1
   ```

2. Redirigí el tráfico de Cloud Run a la revisión anterior de la API y revertí la web en Firebase Hosting (ver [despliegue.md](despliegue.md), "Actualizaciones").
3. Si hacía falta seguir cargando el CDR mientras tanto, volvé a prender el job anterior donde estaba (paso 6 al revés).

La migración 0005 puede quedar aplicada: solo agrega tablas y una columna, y la versión anterior las ignora. Para volver a avanzar, reanudá la programación con `gcloud scheduler jobs resume empresas-cdr --location us-central1` y redesplegá la versión nueva.

## Costos

| Ítem | Uso | Costo mensual |
| --- | --- | --- |
| Cloud Run job `empresas-cdr` | 1 corrida diaria de pocos minutos, más las manuales | US$0 (tramo gratuito) |
| Cloud Scheduler | 2 trabajos en total (auditoría y CDR) | US$0 (3 gratis por cuenta de facturación) |
| Secret Manager (`empresas-cdr-mysql-password`) | 1 versión activa; las anteriores se deshabilitan al cambiarla | US$0 (dentro de las 6 versiones activas gratis) |
| Cloud SQL (`cdr_estado`, `cdr_corrida`) | Pocas filas | Despreciable |
| IP fija de salida (solo con `IP_FIJA=1`) | IP estática en uso + puerta de enlace de Cloud NAT + pocos MB por noche | aprox. US$4–6 |

**Total adicional: US$0**, o unos **US$4–6 por mes** si hace falta la IP fija. A cambio, el servidor o la Mac dejan de ser necesarios para el CDR. El detalle está en [`docs/costos.md`](costos.md).
