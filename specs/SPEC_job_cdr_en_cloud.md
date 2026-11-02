# SPEC — Job del CDR en Google Cloud, con la conexión en Configuración

**Sistema:** Base de Empresas · Equipos Consultores (`araujomelogno/base-empresas`)
**Corrige:** el supuesto de que la base MySQL del CDR solo es accesible desde la red de Equipos, y el diseño que sale de ahí (job en un servidor Ubuntu o en una Mac de la oficina, con la conexión en un archivo `cdr_job.env`)
**Alcance:** job del CDR, pantalla Configuración, script y guía de despliegue, documentación que repite el supuesto
**Estado:** Para desarrollo
**Última actualización:** 2026-11-02

---

## 1. Problem Statement

`docs/despliegue.md` (paso 4) dice que la base MySQL del CDR de uContact "solo es accesible desde la red de Equipos" y por eso manda a correr el job en el servidor Ubuntu o en una Mac de la oficina. **No es así:** la base es accesible desde afuera de la red.

Las dos opciones que da la guía son malas por motivos propios:

- **Dependen de una máquina física.** Si la Mac está apagada o el servidor se cae, no hay CDR, y nadie se entera hasta que falta un día en Actividad.
- **Sacan una pieza del sistema de Google Cloud.** Logs, reintentos, despliegue y monitoreo quedan en otro lado, y la actualización del job es un `git pull` manual en otra máquina.
- **Ponen la conexión en un archivo.** Host, usuario y contraseña de MySQL viven en `cdr_job.env` en esa máquina. Cambiar la conexión exige entrar por SSH a esa máquina, no queda auditado, y nadie más sabe dónde se configura.
- **Guardan el estado incremental en un archivo local** (`estado.json`). Si se pierde la máquina, se pierde por dónde iba la ingesta.

El supuesto se repite en otros archivos del repo (ver R7), así que hay que corregirlo en todos.

## 2. Goals

1. **El job corre en Google Cloud** todos los días a la hora configurada, sin ninguna máquina de Equipos involucrada.
2. **La conexión al CDR se configura desde la aplicación:** un administrador la carga o la cambia en la pantalla Configuración, con historial de cambios y sin tocar código ni servidores.
3. **La contraseña de MySQL nunca queda en la base, en un archivo, en la auditoría ni en los logs:** vive en Secret Manager.
4. **Un problema de conexión se ve en el día:** la pantalla de inicio y Actividad muestran si la última corrida falló y por qué.
5. **Sin costo recurrente relevante:** el job entra en los tramos gratuitos de Cloud Run y Cloud Scheduler (ver §7).

## 3. Non-Goals

- **Cambiar qué hace la ingesta.** El cruce por número destino, los destinos internos, la deduplicación por `uniqueid` y la idempotencia por `cdr_id` siguen igual (`api/app/cdr.py`).
- **Leer el CDR en tiempo real.** Sigue siendo una corrida diaria más un botón "Correr ahora".
- **Soportar otros motores además de MySQL.**
- **Mantener el job en el servidor Ubuntu o en una Mac como alternativa.** Dos caminos para lo mismo duplican el mantenimiento; se elimina.

## 4. User Stories

**Administrador**

- Como administrador, quiero cargar host, puerto, base, usuario y contraseña del CDR en la pantalla Configuración, para conectar el sistema sin pedirle nada a un desarrollador.
- Como administrador, quiero un botón "Probar conexión" que me diga si conecta y, si no, por qué (no resuelve el host, no responde el puerto, usuario o clave incorrectos, no existe la tabla, faltan columnas), para corregirlo en el momento.
- Como administrador, quiero que la contraseña no se vuelva a mostrar una vez guardada, y ver solo cuándo y quién la cambió, para que no circule.
- Como administrador, quiero correr el job a mano y reprocesar desde una fecha, para cargar el histórico la primera vez o recuperar un período.

**Coordinador de campo**

- Como coordinador, quiero ver en la pantalla de inicio la fecha de la última corrida del CDR y si terminó bien, para saber si los intentos de ayer ya están.

**Responsable técnico**

- Como responsable técnico, quiero que el job use la misma imagen, los mismos logs y el mismo despliegue que la API, para no mantener una pieza aparte.

## 5. Requirements

### P0 — Must-Have

#### R1 — Parámetros de conexión en Configuración

- [ ] Nuevo bloque `cdr` en `Parametros` (`api/app/config.py`), versionado como el resto:

| Campo | Tipo | Por defecto | Notas |
| --- | --- | --- | --- |
| `host` | texto | — | Obligatorio para correr el job |
| `puerto` | entero | 3306 | |
| `base` | texto | — | Por ejemplo `uc` |
| `usuario` | texto | — | Usuario de solo lectura |
| `tabla` | texto | `cdr` | Se usa en la consulta por defecto |
| `consulta` | texto, opcional | — | Reemplaza la consulta por defecto; mismo contrato que hoy `CDR_SQL` (columnas con `AS`, orden por `calldate`, uno o dos `%s`) |
| `tls` | `requerido` / `preferido` / `desactivado` | `preferido` | |
| `zona_horaria` | texto | `America/Montevideo` | Zona de `calldate` en MySQL (hoy `CDR_TZ`) |
| `lote_tamano` | entero | 2000 | |
| `activo` | booleano | `false` | El job no corre hasta que se active |

- [ ] La consulta se valida al guardar: solo `SELECT`, sin `;` múltiples, con uno o dos `%s`.
- [ ] La contraseña **no** es parte de `Parametros` (que se guarda en la base y se ve en el historial).

#### R2 — Contraseña en Secret Manager

- [ ] La pantalla Configuración tiene un campo "Contraseña" de solo escritura. Al guardar, la API agrega una versión nueva del secreto `empresas-cdr-mysql-password` en Secret Manager y deshabilita la anterior.
- [ ] La API nunca devuelve la contraseña. La pantalla muestra "Configurada el {fecha} por {usuario}" o "Sin configurar".
- [ ] El cambio queda en auditoría como `config.cdr_password` con autor y fecha, **sin** el valor.
- [ ] La cuenta de servicio `empresas-api` recibe permiso para agregar versiones solo sobre ese secreto (`roles/secretmanager.secretVersionManager` a nivel del secreto, no del proyecto) y para leerlo.

#### R3 — Probar conexión

- [ ] Botón "Probar conexión" en Configuración (`POST /config/cdr/probar`, solo admin). Usa los parámetros del formulario aunque todavía no estén guardados y la contraseña guardada (o la que se acaba de escribir, sin guardarla).
- [ ] Conecta con un tiempo máximo de 10 segundos, corre la consulta para las últimas 24 horas con `LIMIT 5` y devuelve: si conectó, la versión de MySQL, si la conexión usa TLS, cuántas filas trajo, las columnas encontradas y las que faltan.
- [ ] Clasifica el error con un mensaje claro: no resuelve el host · no responde el puerto (posible firewall, ver R6) · usuario o contraseña incorrectos · la base no existe · la tabla no existe · faltan columnas · el servidor exige TLS.
- [ ] Nunca incluye la contraseña en el mensaje.

#### R4 — El job corre en Cloud Run

- [ ] La lógica de `jobs/cdr/cdr_job.py` pasa a la API como `api/app/jobs/cdr_job.py`, que lee MySQL directamente y llama a `cdr.procesar_lote` en el mismo proceso, sin pasar por HTTP. Se conservan la lectura incremental, la deduplicación por `uniqueid` (tramo con más `billsec`), el mapeo de columnas y los conteos.
- [ ] Se despliega como **Cloud Run job `empresas-cdr`** con la misma imagen de la API (como `empresas-migrar`), con acceso a Cloud SQL y al secreto de la contraseña.
- [ ] **Cloud Scheduler** `empresas-cdr` lo ejecuta todos los días a las 4:00, hora de Montevideo (`CRON_TZ=America/Montevideo`).
- [ ] Si `cdr.activo` es falso o falta algún parámetro, el job termina sin error y deja la corrida como "omitida" con el motivo.
- [ ] Argumentos: `--desde AAAA-MM-DD`, `--hasta AAAA-MM-DD` (reproceso) y `--dry-run` (no escribe intentos; deja el payload en el bucket de archivos y los conteos en la corrida).

#### R5 — Estado incremental y corridas en la base

- [ ] El estado (`última calldate enviada` + `uniqueid` de ese segundo) pasa de `estado.json` a una tabla `cdr_estado` en Postgres. Avanza solo después de procesar cada lote y nunca retrocede, como hoy.
- [ ] Cada ejecución deja una fila en `cdr_corrida`: inicio, fin, estado (ok / error / omitida), origen (programada / manual), rango leído, conteos (recibidas, internas, no cruzan, intentos nuevos, asociados a ítem, duplicados) y mensaje de error.
- [ ] La pantalla de inicio muestra la última corrida y su estado. Si la última corrida programada falló o no hubo corrida en 26 horas, se muestra un aviso visible para administradores y coordinadores.
- [ ] Actividad muestra el historial de corridas.
- [ ] Migración nueva `db/empresas/NNNN_cdr_en_cloud.sql`, compatible hacia atrás.

#### R6 — Correr ahora y reprocesar

- [ ] En Configuración, junto a la conexión: "Correr ahora" y "Reprocesar desde…" (fecha desde, fecha hasta opcional), solo admin.
- [ ] La API dispara una ejecución del Cloud Run job con esos argumentos (`run.jobs.run` con overrides) y devuelve el id de la corrida para seguirla en pantalla.
- [ ] No se permite lanzar una corrida si hay otra en curso.
- [ ] La cuenta de servicio `empresas-api` recibe permiso para ejecutar ese job (`roles/run.invoker` sobre `empresas-cdr`).

#### R7 — Despliegue y documentación

- [ ] `infra/desplegar.sh`: nuevo paso `cdr` (incluido en `todo`) que crea el secreto vacío si no existe, crea o actualiza el Cloud Run job `empresas-cdr` y el Cloud Scheduler a las 4:00 de Montevideo, y asigna los permisos de R2 y R6.
- [ ] `docs/despliegue.md`:
  - Tabla de arquitectura: la fila del CDR pasa a "Cloud Run job `empresas-cdr` + Cloud Scheduler".
  - **Paso 4 reescrito:** "Conectar el CDR". En la aplicación, Configuración → CDR: cargar los parámetros y la contraseña, "Probar conexión", activar y "Reprocesar desde…" la fecha inicial. Se quita todo lo de la red de Equipos, el servidor Ubuntu, la Mac, systemd y launchd.
  - Verificación (paso 6) y Operación: "Correr ahora" desde la aplicación o `gcloud run jobs execute empresas-cdr --region us-central1`; logs en Cloud Run → Jobs → `empresas-cdr`.
  - Rotar tokens: `JOB_TOKEN` ya no lo usa el job del CDR; aclarar para qué queda (export de auditoría).
  - Tabla de actualizaciones: el job se actualiza con `./infra/desplegar.sh api` (misma imagen); se quita el `git pull` en `/opt/base-empresas`.
  - Problemas frecuentes: los mensajes de R3.
- [ ] Corregir el supuesto en todos los lugares donde aparece: `README.md` (tabla de carpetas), `api/app/cdr.py` y `api/app/settings.py` (comentarios), `docs/PRD.md`, `docs/decisiones.md` (la decisión del job nocturno y el descarte de OIDC), `docs/costos.md` (fila del servidor Ubuntu y plan de iteraciones) y `specs/Spec Fase 0 y 1.md` (pantallas y riesgos). La fase 0 puede seguir corriendo en una laptop: eso no cambia.
- [ ] `docs/decisiones.md`: nueva decisión **D33 — El job del CDR corre en Google Cloud**, que reemplaza a la anterior: el supuesto era incorrecto, por qué el job vive con la API, por qué la contraseña va a Secret Manager y no a `Parametros`.
- [ ] `jobs/cdr/`: se eliminan `cdr-job.service`, `cdr-job.timer`, `uy.equipos.cdr-job.plist`, `cdr_job.env.example` y el README de instalación. Los tests se portan a `api/tests`.

#### R8 — Tests

- [ ] Se portan los tests de `jobs/cdr/test_cdr_job.py` (lotes, deduplicación, estado que solo avanza con éxito, mismo segundo entre lotes, reproceso que no retrocede, dry-run) adaptados al estado en Postgres.
- [ ] Nuevos: validación de la consulta; "Probar conexión" con cada clase de error (MySQL mockeado); la contraseña nunca aparece en respuestas, auditoría ni logs capturados; job con `activo=false` queda "omitido"; no se puede lanzar una corrida con otra en curso; los endpoints de configuración del CDR rechazan a quien no es administrador.
- [ ] Siguen pasando todos los tests de `api` y `fase0`.

### P1 — Nice-to-Have

- **Horario configurable:** la hora de la corrida se edita en Configuración y la API actualiza el Cloud Scheduler.
- **Aviso por correo** a los administradores cuando una corrida programada falla (reusando el envío de `SPEC_alta_usuarios_enlace_acceso.md`).
- **IP de salida fija** (ver §6), solo si el servidor MySQL filtra por IP.

### P2 — Future Considerations

- Corridas más frecuentes (por ejemplo cada hora durante el campo), si la operación lo pide.
- Leer otras fuentes de llamadas con el mismo contrato de `procesar_lote`.

## 6. Red: ¿el servidor filtra por IP?

Cloud Run sale a internet con IPs que cambian. Si el servidor MySQL acepta conexiones de cualquier IP (con usuario, clave y TLS), no hace falta nada más. Si filtra por IP, hay que darle al job una IP de salida fija: Direct VPC egress + Cloud NAT con una IP estática reservada, y pedir que se autorice esa IP en el servidor.

- Lo resuelve "Probar conexión": si el error es "no responde el puerto", es casi seguro un filtro por IP.
- `infra/desplegar.sh` agrega la variable opcional `IP_FIJA=1` que crea la red, el NAT y la IP, e imprime la IP para autorizarla.
- **Costo de la IP fija (solo si hace falta):** aprox. US$4–6 por mes (IP estática en uso más la puerta de enlace de Cloud NAT; el tráfico procesado del CDR es mínimo). A confirmar en la calculadora de GCP.

## 7. Costos

| Ítem | Uso estimado | Costo mensual |
| --- | --- | --- |
| Cloud Run job `empresas-cdr` | 1 corrida diaria de 1–3 minutos | US$0 (tramo gratuito) |
| Cloud Scheduler | 2 jobs en total (auditoría + CDR) | US$0 (3 jobs gratis por cuenta de facturación) |
| Secret Manager (`empresas-cdr-mysql-password`) | 1 secreto, ~30 accesos | US$0 a 0,06 (US$0,06 por versión activa si se pasa el tramo de 6 versiones) |
| Cloud SQL (`cdr_estado`, `cdr_corrida`) | Pocas filas | Despreciable |
| IP de salida fija (solo si el servidor filtra por IP) | — | aprox. US$4–6 |
| Servidor Ubuntu / Mac | Deja de usarse para esto | — |

Total adicional: **US$0**, o aprox. **US$4–6 por mes** si hace falta la IP fija.

## 8. Success Metrics

| Métrica | Meta | Cómo se mide | Cuándo |
| --- | --- | --- | --- |
| Días con corrida programada exitosa | ≥ 99% | `cdr_corrida` | Primer mes |
| Días sin CDR que nadie notó | 0 | Aviso de R5 visible el mismo día | Primer mes |
| Cambios de conexión que requieren entrar a un servidor | 0 | Todo por Configuración | Al cerrar el PR |
| Tiempo para conectar el CDR en un despliegue nuevo | ≤ 10 minutos | Prueba en el despliegue de `equipos-base-empresas` | Al desplegar |

## 9. Open Questions

| Pregunta | Quién | ¿Bloquea? |
| --- | --- | --- |
| ¿Qué base y tabla se usan: la base `uc` (donde ya lee el dashboard de productividad) o la de uContact cloud? ¿Cómo se llama la tabla del CDR en esa base? | Operaciones | No: son parámetros de Configuración |
| ¿El servidor MySQL filtra por IP de origen? Si sí, hace falta la IP fija (§6). | Operaciones | No: lo detecta "Probar conexión" |
| ¿El servidor acepta TLS? Si sí, conviene dejar `tls = requerido`. | Operaciones | No |
| ¿Hay un usuario de solo lectura con acceso solo a la tabla del CDR? | Operaciones | No, pero se recomienda |

## 10. Timeline Considerations

- Un PR, estimado en 1 a 2 días: la lógica del job ya existe y se mueve; lo nuevo es la configuración, el secreto, "Probar conexión" y las corridas.
- **Reemplaza el paso 4 del despliegue en curso:** no conviene instalar el job en el servidor Ubuntu ni en una Mac mientras tanto.
- No depende del spec de alta de usuarios, salvo el aviso por correo (P1).

## 11. Definition of Done

- [ ] R1 a R8 implementados con sus criterios verificados.
- [ ] Desplegado con `./infra/desplegar.sh todo` en `equipos-base-empresas`.
- [ ] Desde Configuración se cargó la conexión real, "Probar conexión" dio OK y "Reprocesar desde…" cargó el histórico.
- [ ] Al día siguiente, la corrida de las 4:00 quedó OK en `cdr_corrida` y se ve en la pantalla de inicio.
- [ ] Con una contraseña incorrecta, "Probar conexión" mostró "usuario o contraseña incorrectos" sin exponer la clave.
- [ ] No queda ninguna mención a la red de Equipos, al servidor Ubuntu ni a la Mac como lugar del job en el repo (salvo la fase 0).
