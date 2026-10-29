---
titulo: Registro de decisiones
subtitulo: Base de Empresas — Fase 0 y Fase 1
---

# Registro de decisiones

Este registro explica **por qué** el sistema quedó como quedó. Cada decisión tiene contexto, la opción elegida, las alternativas que se descartaron y sus consecuencias. Las decisiones que vienen del PRD o del spec (28/10/2026) se citan como tales; el resto se tomó durante la construcción y se puede revisar.

Estado de cada decisión: **Vigente** (aplicada en el código), **Provisoria** (aplicada, pero conviene validarla en el piloto) o **Pendiente** (la decide otra persona).

## Resumen

| # | Decisión | Estado |
| --- | --- | --- |
| D01 | Cloud SQL Postgres como núcleo; Firebase solo para Auth y Hosting | Vigente (PRD) |
| D02 | API en Python (FastAPI) en Cloud Run; web en JS sin framework | Vigente (spec) |
| D03 | La web y la API comparten dominio: Hosting reescribe `/api/**` a Cloud Run | Vigente |
| D04 | Roles en Postgres, validados en el backend con el token de Firebase | Vigente |
| D05 | Historia y auditoría append-only, protegidas por triggers | Vigente |
| D06 | Deshacer = anular, no borrar | Vigente |
| D07 | Regla de supervivencia: confianza, después fecha; la sala le gana a las cargas | Vigente |
| D08 | Validación del RUT con módulo 11 y control del "001" | Provisoria |
| D09 | Normalización de teléfonos a E.164 con reglas uruguayas propias | Vigente |
| D10 | Intermediario = teléfono con ≥ N RUTs activos; el liberado guarda cuántos tenía | Vigente |
| D11 | Solo el RUT fusiona solo; los demás criterios van a revisión | Vigente (spec) |
| D12 | El preview de una carga corre el mismo código en un savepoint descartado | Vigente |
| D13 | Las cargas y las ingestas corren como tareas diferidas (Cloud Tasks) | Vigente (spec) |
| D14 | Exclusión por naturaleza y no llamar son reglas que no se pueden apagar | Vigente |
| D15 | La exclusión por naturaleza se versiona en la configuración | Vigente |
| D16 | Disponibilidad calculada por una función SQL sobre una versión de configuración | Vigente |
| D17 | Regla extra: "sin teléfono discable" (configurable) | Provisoria |
| D18 | Sorteo con orden sha256(semilla:empresa) sobre un snapshot congelado | Vigente |
| D19 | El CSV vuelve a aplicar las exclusiones al exportar | Vigente |
| D20 | Contactos en el CSV solo con permiso específico | Vigente |
| D21 | El job del CDR empuja datos crudos; la API normaliza con la configuración | Vigente |
| D22 | Asociación de llamadas a ítems por teléfono y ventana de campo | Vigente |
| D23 | Mapeo del .sav: estructura, prioridad de EC_RESULTADO y respaldo por RUT | Vigente |
| D24 | El estado por parte no retrocede, salvo al corregir el mapeo | Vigente |
| D25 | Límite de 30 MB por archivo | Vigente |
| D26 | Autenticación de jobs y tareas con token compartido | Vigente |
| D27 | Región southamerica-east1 | Vigente (PRD) |
| D28 | La fase 0 reusa los módulos del backend | Vigente |
| D29 | Catálogo de naturalezas sin exclusiones hasta cargar la hoja "excluidos" | Pendiente |
| D30 | Meses de enfriamiento por defecto: 6 | Pendiente |

## D01 — Cloud SQL Postgres como núcleo

**Contexto.** El dominio es relacional: el teléfono se vincula muchos a muchos con empresas, los sorteos son estratificados y la disponibilidad depende de varias tablas.

**Decisión (PRD).** Un solo esquema `empresas` en Cloud SQL for PostgreSQL 16, con migraciones numeradas (`db/empresas/0001_init.sql`…) que aplica `db/migrate.py`, igual que en paneles. Firebase se usa para autenticación y para servir la web.

**Descartado.** Firestore: no resuelve bien las consultas M:N ni los conteos por estrato, y obliga a duplicar datos.

**Consecuencias.** Hay un costo fijo mensual por la instancia (ver el documento de costos). Las migraciones en producción corren como Cloud Run job con la misma imagen de la API.

## D02 — FastAPI en Cloud Run y web sin framework

**Contexto.** El spec pide el mismo estilo que paneles: JS sin framework en Firebase Hosting y API Python en Cloud Run.

**Decisión.** API con FastAPI (validación con Pydantic, documentación automática en `/api/docs`) y `psycopg` 3 con pool de conexiones. Web en módulos ES nativos, sin paso de build: `index.html`, `css/app.css` y `js/`. La estética (tokens de color, Montserrat, sidebar oscuro, tarjetas, tablas) se tomó de la app de fichaje de Equipos.

**Consecuencias.** No hay dependencias de npm en producción. Cualquier persona que sepa HTML y JS puede mantener la web.

## D03 — Mismo dominio para la web y la API

**Decisión.** `firebase.json` reescribe `/api/**` al servicio `empresas-api` de Cloud Run. La web llama a rutas relativas (`/api/...`).

**Por qué.** Evita CORS y la configuración de dominios, y la API no queda expuesta con otro nombre a los usuarios.

**Consecuencias.** Las reescrituras de Hosting tienen un límite de tamaño de pedido (32 MB) y de tiempo (60 s): por eso los archivos se limitan a 30 MB (D25) y lo pesado corre en tareas diferidas (D13). El job del CDR y Cloud Tasks llaman directo a la URL de Cloud Run.

## D04 — Roles en Postgres, validados en el backend

**Decisión.** Firebase Auth autentica (email y clave). La API verifica el ID token con `firebase-admin` y busca el email en la tabla `usuario`, que tiene el rol (`admin`, `steward`, `jefe`, `coordinador`, `lectura`) y el permiso `exportar_contactos`. Cada endpoint de escritura declara los roles que acepta; el administrador puede todo. La web oculta lo que el rol no puede hacer, pero quien decide es la API.

**Arranque.** Los emails de la variable `ADMIN_EMAILS` quedan como administradores la primera vez que entran, para no depender de un INSERT manual.

**Modo dev.** Con `AUTH_MODE=dev` la API confía en el header `X-Dev-User`. Solo para desarrollo local y tests; el script de despliegue fija `AUTH_MODE=firebase`.

**Descartado.** Custom claims de Firebase: obligan a usar el Admin SDK para cada cambio de rol y el cambio tarda en propagarse al token.

## D05 — Historia y auditoría append-only

**Decisión.** `empresa_campo_historia`, `telefono_vinculo_historia` y `auditoria` tienen un trigger que rechaza cualquier UPDATE o DELETE. Lo exige el spec y es la base del linaje.

**Consecuencias.** Ninguna operación de la aplicación puede reescribir el pasado, ni siquiera por error. Corregir un dato es agregar una fila nueva.

## D06 — Deshacer es anular, no borrar

**Contexto.** El spec pide que una carga se pueda deshacer entera, y que una fusión se pueda revertir, pero la historia es append-only (D05).

**Decisión.**

- **Carga:** pasa a estado `deshecha`. El cálculo del valor vigente ignora las filas de historia de cargas deshechas. Se borran los vínculos de teléfono, contactos y sucursales que creó esa carga (no son tablas de historia). Las empresas que solo existían por esa carga quedan con `baja = 'anulada'`: no se borran, porque tienen historia asociada. Si una carga posterior trae ese RUT, la empresa se reactiva.
- **Fusión:** la empresa absorbida queda con `baja = 'fusionada'` y apunta a la absorbente. Lo que se movió (vínculos, contactos, sucursales, pedidos de no llamar heredados) queda listado en `empresa_fusion.movidos`, y deshacer lo devuelve. Los valores que aportó la absorbida entran como filas de historia con fuente `fusion`, que se ignoran si la fusión se deshace.

**Restricción.** Una carga solo se deshace si ninguna de sus empresas (altas o actualizadas) entró a una muestra, como pide el spec.

## D07 — Regla de supervivencia

**Decisión (spec).** Para cada campo, gana el valor de mayor confianza; a igual confianza, el más reciente. Si existe un valor confirmado por la sala (fuente `sala` o `sav`), los valores de cargas quedan fuera de la competencia aunque tengan más confianza. Un valor manual (data steward) sí puede ganarle a la sala, porque es una corrección explícita.

**Confianza.** Por defecto: manual 90, sala 80, sav 80, fusión 60, carga 50, sistema 40. Se cambian en la configuración. Cada carga puede declarar su propia confianza (por ejemplo, un padrón oficial a 70 y un directorio a 40).

**Conflictos.** Una carga cuenta como conflicto cada empresa donde llegó un valor distinto del vigente que no ganó. El preview muestra ejemplos para revisar.

## D08 — Validación del RUT

**Decisión.** 12 dígitos; registro (dígitos 1–2) entre 01 y 22; número (3–8) distinto de cero; posiciones 9–11 igual a `001`; dígito verificador con módulo 11 y pesos 4,3,2,9,8,7,6,5,4,3,2 (si da 10, es inválido). Se toleran puntos, guiones, espacios, el prefijo "UY" y el cero inicial que Excel suele comer.

**Estado: provisoria.** El control de `001` es el que aplican las librerías de validación más usadas (python-stdnum), pero conviene confirmarlo con el experimento D de la fase 0. Si aparecen RUTs legítimos que no lo cumplen, se quita esa línea de `api/app/rut.py`.

## D09 — Normalización de teléfonos

**Decisión.** Todo teléfono se guarda una sola vez, en E.164 (`+598…`). Reglas: fijos de 8 dígitos que empiezan con 2 o 4; celulares 09X (se guardan sin el 0); se aceptan los prefijos `+598`, `00598` y `598`, y el formato viejo con 0 de larga distancia (`042…`, `02…`); se quita el texto de internos ("int. 25"). Lo que tiene 5 dígitos o menos es interno; los 7 dígitos son del formato anterior a 2010 y quedan inválidos (no se adivina el prefijo). Los números que no se pueden normalizar se guardan crudos con estado inválido y nunca se exportan. El detalle con ejemplos está en `fase0/datos/reglas_normalizacion.md`.

**Por qué propio.** Las librerías genéricas (libphonenumber) no conocen los formatos viejos que traen las bases propias ni los internos del CDR, y agregan una dependencia pesada. Las reglas están cubiertas por tests.

## D10 — Intermediarios

**Decisión.** Un teléfono vinculado a «umbral» RUTs activos o más (5 por defecto) se marca `sospechoso` al terminar cada carga o ingesta, y deja de ser discable. El data steward lo **confirma** (todos sus vínculos pasan a `intermediario`) o lo **libera**. Al liberar se guarda cuántos RUTs tenía; vuelve a marcarse solo si suma RUTs nuevos, como pide el spec. La sala también puede confirmarlo con `EC_CALIDAD_TEL = 3` (estudio contable o jurídico).

**Señal adicional.** La bandeja muestra cuántos rubros distintos tienen las empresas que comparten el número: muchas empresas de rubros distintos es la firma típica de un estudio contable.

## D11 — Reglas de fusión en las cargas

**Decisión (spec).** La regla por defecto es RUT: si el RUT existe, se actualiza; si no, es alta. Las otras reglas (teléfono, razón social normalizada, dominio web) solo **detectan** coincidencias para filas cuyo RUT no existe en la base: esas filas no se dan de alta, van a la bandeja de revisión. Ahí el steward elige: alta como empresa nueva, aplicar los datos a la empresa existente o descartar.

**Por qué.** En la fase 1 toda empresa entra con RUT válido; las coincidencias por otros criterios suelen ser grupos económicos o errores de carga, y no deben fusionarse sin una persona.

## D12 — Preview exacto

**Decisión.** El preview de una carga ejecuta exactamente el mismo código que la confirmación, dentro de un savepoint que después se descarta. Los conteos (altas, actualizaciones, conflictos, rechazos, a revisión, nuevos sospechosos) son los reales.

**Descartado.** Un "simulador" separado: con el tiempo diverge de la carga real.

**Consecuencia.** Una carga grande se procesa dos veces (preview y confirmación). Es aceptable porque ambas corren en diferido.

## D13 — Tareas diferidas con Cloud Tasks

**Decisión (spec).** El preview y la confirmación de cargas, y la confirmación y el remapeo de ingestas de .sav, se crean como `tarea` en la base y se encolan en Cloud Tasks, que llama a `POST /api/tareas/{id}/ejecutar`. La web muestra el progreso con una barra (la tarea actualiza su avance en una conexión aparte). Una tarea que ya corrió no se vuelve a ejecutar aunque Cloud Tasks reintente.

**Modos.** `TASKS_MODE=cloudtasks` en producción, `background` (un hilo) en desarrollo e `inline` en los tests: siempre el mismo código.

## D14 — Reglas que no se pueden apagar

**Decisión.** La configuración permite activar o desactivar el enfriamiento, el bloqueo por muestra activa y la exclusión de empresas sin teléfono discable. La exclusión por naturaleza jurídica, la lista de no llamar, las empresas cerradas y las dadas de baja están **siempre** activas; la validación de la configuración rechaza cualquier intento de desactivarlas.

**Por qué.** El spec exige que las excluidas nunca entren a un marco ni a un CSV, con un test automático que lo verifique (`test_excluidas_nunca_en_marco_ni_csv`). Un interruptor en la configuración sería una forma de romper esa garantía.

## D15 — La exclusión por naturaleza se versiona

**Contexto.** El modelo de datos del spec pone `excluida` en el catálogo, pero R1.12 pide que el catálogo de naturalezas excluidas sea un parámetro versionado (las muestras guardan la versión con la que se sortearon).

**Decisión.** La lista de códigos excluidos vive en la configuración (`naturalezas_excluidas`). La columna `naturaleza_juridica.excluida` es un espejo que la API mantiene al guardar cada versión. Marcar o desmarcar una naturaleza desde la pantalla crea una versión nueva de la configuración.

## D16 — Disponibilidad en SQL

**Decisión.** La función `empresas.bloqueos(config)` devuelve, para cada empresa bloqueada, la regla y hasta cuándo, evaluada contra una configuración dada. La vista `v_empresa_disponible` la aplica con la configuración vigente (la usan el buscador y la ficha). El sorteo la aplica con la versión vigente al momento de sortear y guarda esa versión.

**Reglas nuevas.** Agregar una regla es agregar un `UNION ALL` en la función (migración nueva) y su clave en la validación de la configuración.

## D17 — Regla "sin teléfono discable"

**Decisión.** Además de las reglas del PRD, se agregó una que deja fuera del marco a las empresas sin ningún teléfono discable (válido, no intermediario, vínculo sin verificar o verificado, sin no llamar). Está activa por defecto y se puede apagar.

**Por qué.** Una empresa sin teléfono discable ocupa un lugar de la muestra y no genera renglones en el CSV. En la fase 2 esas empresas pasan a "requiere enriquecimiento".

**Estado: provisoria.** Si dirección prefiere sortearlas igual (por ejemplo, para medir cobertura), se apaga desde la configuración.

## D18 — Sorteo reproducible

**Contexto.** El PRD sugiere `setseed` + `ORDER BY random()` en SQL.

**Decisión.** Al sortear se congela un snapshot del marco (`marco_snapshot` y `marco_snapshot_item`: cada empresa disponible con su estrato). Dentro de cada estrato las empresas se ordenan por `sha256("semilla:empresa_id")` y se toman los primeros *n* como titulares y los siguientes *r* como reemplazos, en ese orden. La semilla se puede indicar o se genera al azar (62 bits) y se guarda con la versión de configuración.

**Por qué no `random()`.** El generador de Postgres puede cambiar entre versiones y su resultado depende del orden físico de las filas. El hash es estable en cualquier lenguaje y versión, así que cualquiera puede verificar la muestra fuera del sistema. El botón "Verificar reproducibilidad" re-ejecuta el sorteo sobre el snapshot y compara ítem por ítem (y hay un test que lo hace).

**Bloqueo.** Los sorteos se serializan con un `pg_advisory_xact_lock` para que dos muestras no tomen la misma empresa al mismo tiempo. Mientras la muestra está activa, sus empresas (titulares y reemplazos) quedan bloqueadas para otras muestras.

## D19 — El CSV vuelve a evaluar las exclusiones

**Decisión.** Al exportar, además de exigir teléfonos discables, se vuelven a aplicar las reglas de naturaleza excluida, no llamar, cerrada y baja con la configuración vigente. Un pedido de no llamar que llega con el campo en curso se respeta en el siguiente CSV. Solo salen los ítems liberados cuyo estado en la parte es pendiente o en curso.

**Formato.** Las columnas (nombre y campo) y el separador se configuran una vez para que coincidan con la importación de uContact. El link de Alchemer lleva `EC_ID_ITEM`, `EC_RUT` y `EC_TEL_USADO` (E.164 sin el +).

## D20 — Contactos personales en el CSV

**Decisión (Ley 18.331, R1.13).** La columna de contacto sugerido solo se completa si el usuario tiene el permiso `exportar_contactos`; si no, sale vacía y la pantalla lo avisa. Toda exportación queda auditada con la cantidad de renglones y si incluyó contactos. El rol `lectura` ve los contactos ocultos en la ficha.

## D21 — El job del CDR empuja datos crudos

**Decisión.** El job nocturno (4:00, servidor Ubuntu, systemd) lee la tabla `cdr` de MySQL en forma incremental y manda las llamadas crudas a `POST /api/intentos/lote`. Normalizar, descartar destinos internos, calcular la franja y cruzar con la base se hace en la API, con la configuración vigente.

**Por qué.** Los destinos internos, los prefijos de salida y las franjas son parámetros de la configuración (R1.12): si el job los aplicara, habría que redistribuirlo con cada cambio. Re-procesar un día no duplica intentos (idempotente por `cdr_id`). Lo que no cruza se cuenta en el lote pero no se guarda como intento.

## D22 — Asociación de llamadas a ítems

**Decisión.** Una llamada se asocia a un ítem cuando su destino es un teléfono vinculado a una empresa que es ítem de una muestra **activa** y la fecha de la llamada cae dentro de las fechas de campo del estudio. Si hay exactamente un ítem posible, se asocia; si hay más de uno (un número compartido o una empresa en dos muestras), la llamada se guarda sin ítem y va a conciliación.

## D23 — Mapeo del .sav

**Decisión.** El mapeo tiene cuatro partes: la variable de `response_id`; el identificador (variable y tipo, `id_item` o RUT); qué variable del .sav corresponde a cada dato del sistema (teléfono usado, calidad, teléfono alternativo, respondente, resultado, estado de Alchemer, RUT, encuestador, fecha); y, para las variables codificadas, qué código va a qué valor del sistema. El backend propone y el coordinador confirma; nada se aplica antes.

- `EC_RESULTADO` gana sobre el estado de Alchemer (`status`); si no hay resultado, se usa el estado.
- El código `ignorar` permite marcar explícitamente un código como sin efecto (por ejemplo, 9 = no sabe).
- Si una fila no trae `id_item` (o trae uno que no es del estudio), se intenta por RUT y, si el RUT tiene más de un ítem, por el teléfono usado. Es el respaldo que prevé el spec si falla la URL variable.
- Los valores crudos se guardan en `sav_fila.valores`: el mapeo se puede corregir después y reaplicar sin volver a subir el archivo.
- Subir dos veces el mismo .sav no duplica nada (idempotente por parte y `response_id`); las filas que no cambiaron no se reaplican.
- El mapeo confirmado queda como plantilla de la parte y se precarga en el próximo .sav; también se puede copiar la plantilla de otra parte.

## D24 — El estado por parte no retrocede

**Decisión.** Si llegan varias respuestas para el mismo ítem y parte, el estado avanza según el orden pendiente → en curso → no contactable → fuera de marco → rechazo → completa, y no retrocede. La excepción es el remapeo: cuando el coordinador corrige un mapeo, el estado se recalcula con el valor corregido aunque sea "menor".

## D25 — Límite de 30 MB por archivo

**Decisión.** Por la reescritura de Firebase Hosting (D03), los archivos que se suben desde la web no pueden pasar de 30 MB. Una base de 50.000 empresas en CSV ocupa unos 5–10 MB, así que alcanza para el uso previsto. Los archivos se guardan en un bucket privado de Cloud Storage con su hash, para linaje.

**Si hace falta más.** Subida directa al bucket con URL firmada (fase 2).

## D26 — Autenticación de jobs y tareas

**Decisión.** El job del CDR y el export de auditoría se autentican con el header `X-Job-Token`; Cloud Tasks con `X-Tarea-Token`. Los dos tokens se generan al desplegar, se guardan en Secret Manager y se comparan en tiempo constante.

**Descartado (por ahora).** Tokens OIDC de cuentas de servicio: el servidor Ubuntu no tiene identidad de Google y habría que gestionar una clave de cuenta de servicio, que es más riesgosa que un token rotable.

## D27 — Región

**Decisión (PRD).** `southamerica-east1` (São Paulo) para Cloud SQL, Cloud Run, Cloud Tasks y el bucket: menor latencia desde Montevideo y datos en la región. El dataset de BigQuery para auditoría queda en `US` (multirregión) porque solo se usa para consultas largas; si legal pide que todo quede en la región, se crea en `southamerica-east1`.

## D28 — La fase 0 reusa los módulos del backend

**Decisión.** Los scripts de `fase0/` importan `app.telefonos`, `app.rut`, `app.lectores` y `app.sav`. Lo que se valida con datos reales es exactamente lo que después corre en el sistema.

**Nota.** El spec toma el patrón de ingesta del repositorio de paneles (`sav.py`, ingesta diferida). Ese repositorio no estaba disponible en esta sesión de desarrollo, así que el patrón se implementó a partir de su descripción en el PRD y el spec. Conviene compararlos antes del piloto.

## D29 — Catálogo de naturalezas (pendiente)

El catálogo inicial (`db/empresas/0003_seed.sql`) trae las naturalezas jurídicas habituales en Uruguay **sin ninguna marcada como excluida**, porque la hoja "excluidos" del Excel de referencia todavía no se adjuntó. Para cargarla: `python fase0/cargar_excluidos.py <excel>` (ver `fase0/README.md`). **Decide:** dirección.

## D30 — Enfriamiento por defecto (pendiente)

La configuración inicial usa 6 meses de enfriamiento desde el último contacto efectivo; el PRD lo deja abierto. Es un parámetro: se cambia desde la pantalla de configuración sin despliegue. **Decide:** dirección.

## Preguntas abiertas que heredan del PRD

| Pregunta | Quién | Impacto en lo construido |
| --- | --- | --- |
| ¿Cuántos meses de enfriamiento? | Dirección | Solo un parámetro (D30) |
| ¿Qué padrón o directorio se usa como semilla y con qué licencia? | Dirección + legal | Cada carga registra su licencia |
| ¿Hay que inscribir la base ante la URCDP? | Legal | No bloquea construir; sí operar |
| ¿Qué destinos del CDR son internos? | Coordinación de campo | Lista inicial en `fase0/datos/destinos_internos.csv`; se edita en la configuración |
