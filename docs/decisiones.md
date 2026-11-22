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
| D21 | El job del CDR pasa datos crudos; la API normaliza con la configuración | Vigente (dónde corre: D33) |
| D22 | Asociación de llamadas a ítems por teléfono y ventana de campo | Vigente |
| D23 | Mapeo del .sav: estructura, prioridad de EC_RESULTADO y respaldo por RUT | Vigente |
| D24 | El estado por parte no retrocede, salvo al corregir el mapeo | Vigente |
| D25 | Límite de 30 MB por archivo | Vigente |
| D26 | Autenticación de jobs y tareas con token compartido | Vigente |
| D27 | Región Iowa (`us-central1`) para todo el sistema | Vigente (29/10/2026) |
| D28 | La fase 0 reusa los módulos del backend | Vigente |
| D29 | Catálogo de naturalezas sin exclusiones hasta cargar la hoja "excluidos" | Pendiente |
| D30 | Meses de enfriamiento por defecto: 6 | Pendiente |
| D31 | Cloud SQL arranca en `db-f1-micro`; el paso siguiente es `db-g1-small` | Vigente (29/10/2026) |
| D32 | Alta de usuarios con enlace de acceso: un solo paso, clave aleatoria y correo desde `notificaciones@` | Vigente (02/11/2026) |
| D33 | El job del CDR corre en Google Cloud, con la API; conexión en Configuración y contraseña en Secret Manager | Vigente (02/11/2026) |
| D34 | Carga v2: atributos administrables, origen del teléfono como evidencia, traducción de valores y estado «descartada» | Vigente (11/11/2026) |
| D35 | Llamada atendida: disposición ANSWERED del CDR o, si la disposición no lo dice, duración facturada > 0 | Provisoria (11/11/2026) |
| D36 | Borrado definitivo de empresas y cargas, solo administrador | Vigente (11/11/2026; ajustada por D37) |
| D37 | Borrar estudios y muestras, cancelar tareas al borrar y verificar la reproducibilidad con borrados (marco inmutable) | Vigente (11/11/2026) |
| D38 | Qué es una llamada y cómo se cuentan las llamadas a empresas (criterios del dashboard, sin filtro de campaña, filtro por empresa) | Vigente (11/11/2026) |
| D39 | Toda fila del .sav es una encuesta completa; el número usado y el adicional quedan verificados | Vigente (12/11/2026) |
| D40 | Los contactos como entidad: cargas, alta y edición manual, atributos de contacto y borrado definitivo | Vigente (12/11/2026; cambia lo dicho sobre contactos en D34) |
| D41 | Normalización y fusión de atributos (clave automática, similitud con pg_trgm, «Fusionar con…») | Vigente (12/11/2026) |
| D42 | Base provisoria: empresas sin RUT, sorteables, que pasan a la definitiva al tener RUT o al fusionarse | Vigente (12/11/2026) |
| D43 | Reglas de fusión en cascada, exactas o flexibles, con las coincidencias decididas en el preview | Vigente (12/11/2026) |
| D44 | Templates de sorteo como copias de criterios, empresas sin teléfono opcionales por muestra y todo dato de la empresa como filtro y estrato | Vigente (17/11/2026; reemplaza la habilitación por casillas de D34) |
| D45 | Proveedores del enriquecimiento (Google Places, Brave Search, Claude) y riesgo aceptado de guardar el teléfono de Places | Vigente (17/11/2026) |
| D46 | Enriquecimiento bajo demanda con estimación aprobada, tope por corrida y tope mensual duro; cascada de lo más barato a lo más caro | Vigente (17/11/2026) |
| D47 | Duplicados difusos entre empresas con RUT y grupo económico (relacionadas sin fusionar, una por grupo en el sorteo) | Vigente (17/11/2026) |
| D48 | Tablero de calidad por dimensión DMBOK con histórico diario | Vigente (17/11/2026) |
| D49 | Naturalezas jurídicas: se edita el nombre y la exclusión; el código y el borrado, solo si ninguna empresa la usa ni la usó; rutas por id | Vigente (20/11/2026) |
| D50 | Cargas por lotes: preview, confirmación, deshacer y borrado por lotes de 5.000 filas, cada uno una transacción; estado «interrumpida», reanudar, una carga pesada a la vez | Vigente (22/11/2026) |
| D51 | Crear la carga sin esperas: el archivo se parsea una vez al analizarlo (archivo_fila), los archivos grandes se leen en segundo plano, «Siguiente» responde enseguida y una clave evita cargas duplicadas | Vigente (22/11/2026) |

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

**Arranque.** Los emails de la variable `ADMIN_EMAILS` quedan como administradores la primera vez que entran, para no depender de un INSERT manual. Desde D32, además, el despliegue les crea la cuenta y les manda su enlace de acceso.

**Cuentas.** Desde D32, las cuentas de Firebase las crea la API al dar de alta en la pantalla Usuarios; nadie las crea a mano en la consola. Desactivar a alguien en Usuarios también deshabilita su cuenta de Firebase.

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

## D21 — El job del CDR pasa datos crudos

**Decisión.** El job nocturno (4:00) lee la tabla `cdr` de MySQL en forma incremental y pasa las llamadas crudas a `cdr.procesar_lote`, la misma función que atiende `POST /api/intentos/lote` (que queda para cargas a mano). Dónde corre y cómo se configura está en D33; originalmente corría en un servidor Ubuntu y llamaba al endpoint por HTTP. Normalizar, descartar destinos internos, calcular la franja y cruzar con la base se hace en la API, con la configuración vigente.

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

**Decisión.** El export de auditoría y el alta de los administradores iniciales (`desplegar.sh invitar`) se autentican con el header `X-Job-Token`; Cloud Tasks con `X-Tarea-Token`. Los dos tokens se generan al desplegar, se guardan en Secret Manager y se comparan en tiempo constante. El job del CDR ya no usa el token: corre con la identidad de la cuenta de servicio y escribe directo en la base (D33).

**Descartado (por ahora).** Tokens OIDC de cuentas de servicio para el export de auditoría. El motivo original (un servidor Ubuntu sin identidad de Google) dejó de valer con D33; hoy todo corre en Google Cloud y se podría pasar a OIDC, pero el token rotable funciona y el cambio no aporta lo suficiente todavía.

## D27 — Región

**Contexto.** El PRD proponía `southamerica-east1` (São Paulo) por cercanía. Al revisar los costos se decidió (29/10/2026) que el sistema va **siempre en Iowa**.

**Decisión.** `us-central1` (Iowa) para Cloud SQL, Cloud Run, Cloud Tasks, Cloud Scheduler, Artifact Registry y el bucket; `firebase.json` reescribe `/api/**` al servicio de esa región. El dataset de BigQuery para auditoría queda en la multirregión `US`.

**Por qué.** Iowa es la región de precio de referencia de Google: los servicios cuestan del orden de un tercio menos que en São Paulo.

**Consecuencias.**

- Más latencia desde Montevideo (del orden de 150 ms por pedido en lugar de 40 ms). La API y la base están en la misma región, así que solo lo nota el navegador y no afecta las consultas internas. Para pantallas administrativas es imperceptible.
- Los datos personales (contactos) quedan alojados en Estados Unidos. Legal tiene que confirmar el encuadre de la transferencia internacional bajo la Ley 18.331, además de la inscripción ante la URCDP que ya estaba pendiente.
- El script de despliegue usa `REGION=us-central1` por defecto.

## D28 — La fase 0 reusa los módulos del backend

**Decisión.** Los scripts de `fase0/` importan `app.telefonos`, `app.rut`, `app.lectores` y `app.sav`. Lo que se valida con datos reales es exactamente lo que después corre en el sistema.

**Nota.** El spec toma el patrón de ingesta del repositorio de paneles (`sav.py`, ingesta diferida). Ese repositorio no estaba disponible en esta sesión de desarrollo, así que el patrón se implementó a partir de su descripción en el PRD y el spec. Conviene compararlos antes del piloto.

## D29 — Catálogo de naturalezas (pendiente)

El catálogo inicial (`db/empresas/0003_seed.sql`) trae las naturalezas jurídicas habituales en Uruguay **sin ninguna marcada como excluida**, porque la hoja "excluidos" del Excel de referencia todavía no se adjuntó. Para cargarla: `python fase0/cargar_excluidos.py <excel>` (ver `fase0/README.md`). **Decide:** dirección.

## D30 — Enfriamiento por defecto (pendiente)

La configuración inicial usa 6 meses de enfriamiento desde el último contacto efectivo; el PRD lo deja abierto. Es un parámetro: se cambia desde la pantalla de configuración sin despliegue. **Decide:** dirección.

## D31 — Cloud SQL arranca en `db-f1-micro`

**Contexto.** La propuesta original era `db-custom-1-3840` (1 vCPU dedicada, 3,75 GB), unos US$50 por mes solo en la instancia. Al revisar los costos se decidió (29/10/2026) empezar con el tamaño mínimo.

**Decisión.** La instancia se crea con `db-f1-micro` (núcleo compartido, 0,6 GB, 25 conexiones) y 10 GB de disco con autoincremento. Para respetar las 25 conexiones, la API se despliega con `DB_POOL_MAX=5` y hasta 3 instancias de Cloud Run. El script elige esos límites según el tamaño real de la instancia, así que un cambio de tamaño no requiere tocar código.

**Por qué alcanza para empezar.** El sistema tiene pocos usuarios simultáneos y lo pesado (cargas e ingestas) corre en segundo plano, con a lo sumo 2 tareas a la vez.

**Contras aceptados.** No tiene SLA de Google ni admite descuento por compromiso, y las cargas grandes y los sorteos son más lentos.

**Paso siguiente.** `db-g1-small` (1,7 GB, 50 conexiones), con `TIER=db-g1-small ./infra/desplegar.sh redimensionar`: unos minutos sin servicio y sin migrar datos. Las señales para hacerlo y el procedimiento están en `docs/cambio_a_small.md`. Cuando se haga, anotar acá la fecha.

## D32 — Alta de usuarios con enlace de acceso

**Contexto.** Para que una persona entrara había que darla de alta dos veces con el mismo email: una cuenta en la consola de Firebase y un registro con su rol en la pantalla Usuarios. Si faltaba uno, o había un error de tipeo, quedaba afuera. Las cuentas creadas a mano quedaban con el email sin verificar y la API las rechazaba. Encima, el login no mostraba el error: al fallar `/me`, la web cerraba la sesión de Firebase y el login se volvía a dibujar sin el mensaje. En el primer despliegue, el administrador inicial no pudo entrar y no vio ningún mensaje. (Spec: `specs/SPEC_alta_usuarios_enlace_acceso.md`.)

**Decisión.** Se adopta el modelo de `plataforma-informes-ec`:

- El administrador escribe email, nombre y rol en la pantalla Usuarios. La API crea la cuenta de Firebase con una clave aleatoria (`secrets.token_urlsafe`) que no se guarda, no se devuelve ni se loguea.
- La persona recibe un correo desde `notificaciones@equipos.com.uy` (SMTP de Google Workspace) con un enlace de Firebase para fijar su contraseña, que vence en una hora. «Reenviar acceso» manda uno nuevo: de bienvenida si nunca entró, de restablecimiento si ya entró.
- El correo es una comodidad, no un punto de falla. Si el SMTP falla, la cuenta queda creada y la pantalla muestra el motivo y el enlace una sola vez, para pasarlo por otro canal. El enlace no se guarda en la base, en la auditoría ni en los logs. Cada envío queda en `correo_envio` (sin el enlace), que se purga a los 90 días.
- Si el email ya tenía cuenta (creada a mano), no se crea otra ni se toca su clave: se registra en Usuarios, se marca verificada y se avisa que use «Reenviar acceso».
- Desactivar en Usuarios deshabilita la cuenta de Firebase; reactivar la habilita.
- El despliegue (`./infra/desplegar.sh todo` o `invitar`) les crea la cuenta y les manda el enlace a los administradores iniciales, con la misma lógica, a través de un endpoint protegido con el token del job que solo actúa sobre `ADMIN_EMAILS`.
- El login guarda el último error antes del `signOut` y lo vuelve a mostrar en el segundo dibujo. Los rechazos de Firebase (clave incorrecta, cuenta deshabilitada, demasiados intentos) también tienen su mensaje.

**Diferencia con `plataforma-informes-ec`.** Las cuentas se crean con `email_verified=True`. Nadie conoce la clave aleatoria, así que la única forma de entrar es el enlace que llega a ese buzón: eso prueba que la persona es dueña del email. Hace falta porque la API de la Base de Empresas exige email verificado.

**Seguridad.**

- La cuenta de servicio de la API suma el rol `roles/firebaseauth.admin` (crear, deshabilitar y generar enlaces).
- La contraseña SMTP es una contraseña de aplicación **exclusiva de este proyecto** (`empresas-smtp-password`), revocable sin afectar a `paneles` ni a `plataforma-informes-ec`, y nunca aparece en mensajes de error.

**Descartado.**

- **Ingreso con Google u otros proveedores:** fuera del alcance del spec; se mantiene email y contraseña, como en `paneles` y `plataforma-informes-ec`.
- **Seguir creando las cuentas en la consola de Firebase:** es justamente el doble paso que fallaba, y deja cuentas sin verificar.
- **Invitaciones propias que duren días:** exigen tokens propios y su gestión. El enlace de Firebase (una hora) más «Reenviar acceso» alcanza para pocos usuarios internos.
- **Un proveedor transaccional** (SendGrid, Mailgun): el volumen no lo justifica y la cuenta de Workspace ya se paga.

**Desarrollo local.** Con `AUTH_MODE=dev` las cuentas se simulan en memoria y, si no hay `SMTP_PASSWORD`, el correo "falla" con un motivo claro y la pantalla muestra el enlace de prueba. Los tests simulan Firebase y el SMTP.

**Pendiente (P1 del spec).**

- «¿Olvidaste tu contraseña?» con el correo de `notificaciones@` (hoy sale del remitente de Firebase).
- Plantillas editables desde Configuración.
- Último ingreso guardado en `usuario`.

## D33 — El job del CDR corre en Google Cloud

**Contexto.** El diseño original (D21) suponía que la base MySQL del CDR de uContact solo era accesible desde la red de Equipos. Por eso el job era un script aparte (`jobs/cdr/`) para correr en el servidor Ubuntu del dashboard o en una Mac de la oficina, con systemd o launchd, la conexión en un archivo `cdr_job.env` y el estado en un `estado.json` local. **El supuesto era incorrecto:** la base es accesible desde internet. Con eso, el job dependía de una máquina prendida, la conexión solo se podía cambiar entrando a esa máquina y nadie veía desde la aplicación si había corrido. (Spec: `specs/SPEC_job_cdr_en_cloud.md`.)

**Decisión.**

- **El job vive con la API:** `api/app/jobs/cdr_job.py`, desplegado como Cloud Run job `empresas-cdr` con la misma imagen (como `empresas-migrar`) y ejecutado por Cloud Scheduler a las 4:00 de Montevideo. Llama a `cdr.procesar_lote` en el mismo proceso, sin HTTP: una sola copia de la lógica, se actualiza con `desplegar.sh api` y usa la misma configuración y los mismos tests.
- **Estado y corridas en Postgres** (`cdr_estado`, `cdr_corrida`): Cloud Run no tiene disco. Cada lote y el avance del estado van en la misma transacción, así que el estado solo avanza si el lote se guardó y nunca retrocede; un reproceso no lo toca. Un lock de Postgres impide dos corridas a la vez.
- **Conexión en Configuración → CDR:** host, puerto, base, usuario, tabla o consulta, TLS y zona horaria son un bloque más de la configuración, versionado y auditado como el resto. «Probar conexión» clasifica el error (host, puerto, credenciales, base, tabla, permisos, TLS, columnas) para que se pueda resolver sin mirar logs.
- **La contraseña va a Secret Manager (`empresas-cdr-mysql-password`), no a `Parametros`:** la configuración se guarda en la base, se versiona, se muestra en pantalla y se audita, así que una contraseña ahí quedaría copiada en cada versión, en la auditoría y en el export a BigQuery. En Secret Manager solo la leen la API y el job, y el permiso de la cuenta de servicio es sobre ese secreto, no sobre todos. La pantalla nunca la devuelve; solo dice si está configurada, cuándo y por quién. Al cambiarla se deshabilitan las versiones anteriores. Tampoco aparece en errores ni logs (se reemplaza por `***`).
- **«Correr ahora» y «Reprocesar desde…»** ejecutan el Cloud Run job con argumentos propios (`run_job` con overrides), y la pantalla sigue la corrida.
- **IP fija opcional** (`IP_FIJA=1`: VPC, Cloud NAT e IP estática) solo si el servidor MySQL filtra por IP de origen.

**Descartado.**

- **Mantener el job en un servidor o una Mac:** depende de que la máquina esté prendida, queda fuera del monitoreo de Google Cloud y la conexión no se puede cambiar desde la aplicación.
- **Un servicio aparte para el job:** duplicaría la lógica de cruce y la configuración, y habría que desplegarlo por separado.
- **Contraseña en `Parametros` o en una variable de entorno fija:** la primera la expone (ver arriba); la segunda obliga a redesplegar para cambiarla.
- **Validar el certificado TLS del MySQL:** el servidor usa un certificado propio; se cifra sin validar la CA. Con «requerido», el job se niega a seguir si la conexión no quedó cifrada.

**Consecuencias.** El job escribe directo en la base, así que deja de usar `JOB_TOKEN` (D26). La migración 0005 agrega `cdr_estado`, `cdr_corrida` y la columna `cdr_lote.corrida_id`. La carpeta `jobs/cdr/` se elimina; sus tests pasan a `api/tests/test_cdr_job.py`. La fase 0 puede seguir corriendo en una laptop.

## D34 — Carga v2: atributos administrables y origen del teléfono

**Contexto.** En la primera prueba en producción la carga resultó difícil de usar y dejaba afuera información de negocio: los campos cargables estaban fijos en el código, el mapeo mostraba 21 campos juntos (incluidos contactos, que las bases no traen), no se guardaba de dónde salió cada teléfono y el estado de la carga no explicaba nada. (Spec: `specs/SPEC_carga_v2_atributos_y_origen_telefono.md`.)

**Decisión.**

- **Núcleo fijo, atributos administrables.** RUT, razón social, fantasía, naturaleza, CIIU, tamaño, departamento, localidad, dirección, web y estado siguen en el código: de ellos dependen la disponibilidad, los estratos, la fusión y las exclusiones. Todo lo demás es un **atributo** (`atributo`: clave inmutable, tipo texto/número/fecha/lista, sinónimos, filtro, estrato, activo) que crea un administrador. **Cambiado por D44 (17/11/2026):** «filtro» y «estrato» ya no restringen; todo atributo de empresa activo sirve como filtro y estrato del sorteo.
- **Mismo linaje para los atributos.** La historia va a `empresa_campo_historia` con `campo = 'atributo.<clave>'` y la misma regla de supervivencia (D07). `empresa_atributo` guarda el ganador **tipado** (texto, número o fecha) para filtrar y estratificar en SQL. Un número o una fecha que no se puede interpretar no rechaza la fila: queda como crudo, se cuenta como inválido y no entra a los filtros.
- **El origen del teléfono es evidencia del vínculo**, no un atributo del teléfono: `telefono_vinculo_origen` (vínculo, origen, carga, fecha), único por vínculo y origen. Un número que llega de dos orígenes queda con los dos; un teléfono cuenta en cada origen y los totales lo cuentan una vez. El catálogo `origen_telefono` tiene prioridad (el orden del CSV) y tres orígenes de sistema: **Sala** (`EC_TEL_ALT`), **Manual** (ficha) y **Sin dato** (vínculos anteriores al cambio, que la migración deja así).
- **Origen por columna o fijo, con origen por defecto obligatorio.** El mapeo guarda `origenes_telefono` ({columna de teléfono: {columna} | {fijo}}) y `origen_defecto`; `telefonos` sigue siendo la lista de columnas, así las plantillas viejas siguen abriendo.
- **Traducción de valores confirmada, nunca automática.** Los valores de origen y de atributos de lista que no coinciden exactamente con el catálogo se listan con su cantidad de filas; se sugiere sin mayúsculas, tildes ni espacios, pero la API rechaza la carga mientras quede alguno sin traducir. Es el criterio de la ingesta del .sav (D23). La traducción queda en la plantilla del tipo de fuente.
- ~~**Sin contactos en las cargas.** Se generan en el campo (`EC_RESP_*` del .sav). Una plantilla vieja con campos de contacto se abre y esos campos se ignoran con un aviso.~~ **Cambiado por D40 (D-d, 12/11/2026):** los contactos pueden venir en una carga (bloque «Contacto», uno por fila) y las plantillas viejas con campos de contacto pasan a usarlos.
- **«Descartada» ≠ «deshecha».** Descartar una carga en preview o en error la deja `descartada`; `deshecha` queda solo para una carga confirmada que se anuló. La migración 0006 pasa a `descartada` las deshechas que nunca se confirmaron. Deshacer también borra el origen que la carga sumó a vínculos que ya existían.
- **Sorteo y CSV.** Los filtros por atributo y por origen quedan en `muestra.criterios` y entran al snapshot (D18), así la muestra se reproduce con su semilla. El filtro de origen es una regla más del cuadro de exclusiones (`filtro_origen`). La exportación guarda en `muestra.exportacion` los orígenes elegidos y el orden (por prioridad de origen y después verificados, por defecto), y suma la columna `origen_telefono`.
- **Fusiones.** El vínculo que sobrevive hereda los orígenes del que se borra; deshacer la fusión los devuelve.

**Descartado.**

- **Volver administrables los campos del núcleo:** se podría romper el sorteo y las reglas de disponibilidad.
- **Columnas dinámicas en `empresa`** (una por atributo): exigen DDL desde la aplicación y migraciones por cada atributo.
- **Aplicar las traducciones sugeridas solas:** «GUIA TEL.» puede no ser la guía; un error de traducción contamina el análisis por origen sin que nadie lo note.
- **Recalcular el origen de los teléfonos viejos:** no hay de dónde sacarlo; quedan con «Sin dato».

**Consecuencias.** Migración `0006_carga_v2.sql` (compatible hacia atrás). Sin costo de infraestructura: son tablas y pantallas sobre la misma base y la misma API.

## D35 — Llamada atendida (contactabilidad por origen)

**Contexto.** La tarjeta de rendimiento por origen (C9) necesita saber si una llamada fue atendida. El spec lo dejó como pregunta abierta para coordinación de campo: disposición del CDR (`ANSWERED`) o `userfield`.

**Decisión provisoria.** Una llamada está atendida si la disposición del CDR empieza con `ANSWER` o, cuando la disposición no es una de las de Asterisk (por ejemplo, porque vino del `userfield` del marcador), si la duración facturada (`billsec`) es mayor a 0. BUSY, NO ANSWER, FAILED, CONGESTION y CANCEL nunca cuentan como atendidas aunque tengan duración. Está en un solo lugar (`ATENDIDA` en `api/app/actividad.py`) y la pantalla la explica.

**Pendiente.** Que coordinación de campo la confirme con un estudio real.

## D36 — Borrado definitivo de empresas y cargas

**Contexto.** Deshacer una carga anula y conserva la historia, y no se puede si alguna empresa ya entró a una muestra. Hacía falta poder limpiar pruebas y atender pedidos de supresión (Ley 18.331).

**Decisión.** Solo el administrador puede **Borrar empresa** (ficha) y **Borrar carga** (detalle de la carga), en cualquier estado (desde D37 también mientras se procesa: la tarea se cancela). Es definitivo y arrastra todo: historia, teléfonos vinculados (el teléfono se borra si no le queda otra empresa ni rastro), contactos, sucursales, atributos, empresas fusionadas dentro de la que se borra, su lugar en las muestras, e intentos del CDR y filas del .sav de esos ítems. **El marco congelado de los sorteos no se toca** (ajuste de D37): los ítems que se van se copian a `muestra_item_borrado`. Borrar una carga borra las empresas que solo venían de ella y recalcula las demás sin lo que aportó; elimina también su archivo. Se confirma escribiendo el RUT o «BORRAR». Queda un registro en Auditoría (`empresa.borrar`, `carga.borrar`) con los conteos.

**Cómo convive con el append-only.** La migración `0007_borrado_definitivo.sql` deja borrar filas de las historias solo dentro de una transacción marcada con `SET LOCAL empresas.purga = 'on'`, que usa únicamente `api/app/borrado.py`. La auditoría no tiene excepción.

**Consecuencias.** Las muestras que tenían esas empresas pierden esos ítems y sus conteos bajan. La verificación de reproducibilidad los sigue contando (D37); solo las muestras dañadas con la primera versión de este borrado, que sí borraba filas del marco congelado, quedan «no verificables». Los «no llamar» por número se conservan (y con ellos el teléfono). Sin costo de infraestructura.

## D37 — Borrado de estudios y muestras, cancelación de tareas y verificación con borrados

**Contexto.** No se podían borrar estudios ni muestras: las pruebas de sorteo quedaban para siempre y una muestra activa seguía bloqueando a sus empresas. Las cargas trabadas («analizando» o «en proceso» porque Cloud Tasks no ejecutó la tarea o porque se reinició la instancia) no se podían borrar. Y después de borrar empresas, «Verificar reproducibilidad» daba una falsa alarma porque el borrado quitaba filas del marco congelado. (Spec: `specs/SPEC_borrado_estudios_muestras_y_cargas_en_curso.md`; decisiones de Germán Araújo del 11/11/2026.)

**Decisión.**

- **Borrar muestra y borrar estudio, solo administrador**, con confirmación escrita (BORRAR para la muestra, el nombre para el estudio), como tareas (`muestra.borrar`, `estudio.borrar`) y con registro en Auditoría (`muestra.borrar`, `estudio.borrar`) con los conteos. Antes de confirmar, el modal muestra lo que se va a borrar (`GET …/borrado`).
- **Qué se borra:** la muestra, sus ítems y estados por parte, sus intentos del CDR, sus filas del .sav, la conciliación que apunta a ellos y su marco congelado (si ninguna otra muestra lo usa). Un estudio borra además sus partes, sus ingestas .sav (con las filas que no se asociaron) y los archivos .sav que nadie más usa. Los intentos del CDR sin ítem no se tocan.
- **Lo que el campo dejó en la base se conserva:** empresas, historia (incluida la de la sala), vínculos y su estado, contactos, teléfonos y último contacto efectivo. Una empresa que tuvo un contacto efectivo sigue en enfriamiento. La ficha marca «ingesta borrada» cuando el linaje apunta a una ingesta que ya no existe; el estudio y la parte siguen en el detalle de la historia.
- **Cancelación de tareas.** La tarea admite el estado `cancelada`. Borrar una carga cancela su preview o su confirmación; borrar un estudio, sus ingestas .sav en curso. La marca se hace con autocommit; una tarea cancelada no arranca, y una que está corriendo lo detecta al informar progreso y **revierte toda su transacción**: no aplica nada y no deja la carga ni la ingesta en «error». El borrado espera a que la tarea suelte los locks, con `lock_timeout` de 2 minutos; si se agota, falla con un mensaje claro y se reintenta. Una tarea huérfana (figura corriendo pero su proceso murió) no tiene locks: el borrado sigue de inmediato. Las tareas canceladas quedan como registro.
- **El marco congelado es inmutable.** Borrar una empresa ya no toca `marco_snapshot_item` (la migración quita su FK a `empresa`: el `empresa_id` queda como número, que sin la fila borrada no identifica a nadie). Los ítems que se van se copian a `muestra_item_borrado` con la acción y el registro de Auditoría. «Verificar reproducibilidad» re-sortea sobre el marco completo y compara contra los ítems que quedan más los borrados: **reproducible**, **reproducible con N empresas borradas después del sorteo**, **no coincide** (una alteración real) o **no verificable** (el marco perdió filas con la versión anterior del borrado).
- **Detalle de carga e ingesta:** una tarea que figura corriendo hace más de 30 minutos (más que el plazo de Cloud Tasks) se muestra como «trabada».

**Descartado.**

- **Revertir lo aprendido por el campo** al borrar una muestra: borraría información verdadera sobre las empresas (un número que no corresponde sigue sin corresponder).
- **Esperar a que termine la tarea antes de borrar** (lo que hacía D36): una tarea trabada no termina nunca.
- **Volver a sortear para «arreglar» la verificación:** ocultaría una alteración real; el marco inmutable más los ítems borrados permiten distinguirlas.
- **Borrar una parte suelta:** queda para más adelante (P2).

**Consecuencias.** Migración `0008_borrado_estudios_muestras.sql`. Sin costo de infraestructura.

## D38 — Qué es una llamada y cómo se cuentan las llamadas a empresas

**Contexto.** En Actividad, la columna «Llamadas» de las corridas del job del CDR mostraba las filas leídas del CDR (con tramos repetidos, internos y filas releídas), y «Nuevos» no decía qué eran. «Rendimiento por origen» no mostraba llamadas a empresas que no estaban en una muestra cuando se filtraba por estudio o muestra, porque el filtro era por ítem. Y no había forma de ver a qué empresas se llamó. (Spec: `specs/SPEC_conteo_llamadas_cdr_y_rendimiento_por_origen.md`, versión 2; decisiones de Germán Araújo del 11/11/2026.)

**Decisión.**

- **Una llamada** es lo que cuenta el dashboard de productividad CATI: **una por `uniqueid`** (los tramos cuentan una vez), con **destino externo** (no interno según `destinos_internos`), sin volver a contar las filas del segundo ya procesado en la corrida anterior. **No se filtra por campaña.**
- **Conteos de cada corrida** (`cdr_corrida.conteos`, `conteo_version = 2`): `llamadas`; `llamadas_a_empresas` (las que cruzan con un teléfono de la base, **nuevas más ya registradas**, así un reproceso repite el número en lugar de mostrar 0); `telefonos_marcados` y `empresas_llamadas` distintos; y el embudo `asociadas_a_muestra` + `en_conciliacion` + `sin_muestra` = `llamadas_a_empresas`. Las corridas anteriores muestran «—»: un reproceso con «Correr ahora» y fechas las recalcula.
- **`cdr_corrida_intento`** (migración 0009) guarda las llamadas a empresas de cada corrida, nuevas o ya registradas. Con eso salen los distintos y el embudo, y «Exportar empresas» de una corrida da exactamente sus empresas aunque los intentos se hayan guardado antes (su `lote_id` es el de la primera vez). Para las corridas anteriores se usa el `lote_id` de sus lotes, como pedía el spec.
- **Rendimiento por origen no depende de las muestras.** Sin filtros cuenta todas las llamadas a empresas del período. Con un estudio o una muestra, Actividad filtra **por empresa** (las llamadas a empresas que pertenecen a alguna de sus muestras), no por ítem: cuenta también la llamada hecha antes del campo o la que quedó en Conciliación. Aplica al tablero y a la tarjeta, así coinciden. La fila **Total** sale de todas las llamadas filtradas (cada teléfono y empresa una vez), y si alguna llamada a una empresa ya no tiene vínculo vigente aparece la fila «Sin vínculo vigente».
- **Lista de empresas llamadas** (`GET /api/actividad/empresas-llamadas`, también en CSV): una fila por empresa, con sus teléfonos llamados y su origen, llamadas, atendidas (D35), primera y última llamada, encuestadores, y estudio, muestra y estado del ítem. Se abre desde una corrida, desde cada número de la tarjeta y desde Actividad con los filtros vigentes. La ven y exportan administrador, coordinador y jefe; cada exportación queda en Auditoría (`actividad.exportar_empresas`). No incluye contactos (nombres de personas). Una llamada a un número compartido por varias empresas aparece en la fila de cada una; el total de llamadas arriba de la lista la cuenta una vez.

**Descartado.**

- **Filtrar por campaña:** las llamadas del marcador manual no tienen campaña y son parte del trabajo de campo.
- **Seguir filtrando por ítem:** escondía llamadas reales a empresas de la muestra (antes del campo, en Conciliación).
- **Guardar todas las llamadas del CDR, también las que no cruzan:** no se guardan (no son de empresas de la base); por eso las llamadas por encuestador del tablero siguen contando solo las llamadas a empresas (P1.1 queda para cuando se decida guardarlas).

**Consecuencias.** Migración `0009_conteo_llamadas.sql` (tabla e índices). El conteo nuevo vive en el job: hay que desplegar `api` y `cdr`. Sin costo de infraestructura.

## D39 — Toda fila del .sav es una encuesta completa

**Contexto.** En la primera ingesta real el .sav no traía `EC_RESULTADO` ni el `status` de Alchemer mapeados: las filas quedaron sin resultado, no contaron como encuestas, no marcaron el ítem ni actualizaron el último contacto efectivo. Además el número con el que se habló (`EC_TEL_USADO`) y el adicional (`EC_TEL_ALT`) entraban «sin verificar», y una fila sin aplicar no decía por qué. (Spec: `specs/SPEC_mejoras_sav_contactos_atributos_identidad.md`, decisiones D-a y D-b de Germán Araújo, 12/11/2026.)

**Decisión.**

- **Toda fila del .sav con response_id es una encuesta completa** (Alchemer exporta solo las completas). El mapeo ya no pide «resultado» ni «estado de Alchemer»: los mapeos y plantillas viejos que los tienen se limpian al usarlos. Si la fila está asociada a un ítem, el ítem queda «completa» en la parte (el estado más avanzado, no retrocede), y la empresa actualiza su último contacto efectivo con la fecha de la fila, haya o no `contacto_efectivo` en la configuración.
- **«Encuestas completas» cuenta las filas del .sav, asociadas o no** (tablero de Actividad, por encuestador con `EC_ENCUESTADOR` o «(sin encuestador)», detalle del estudio por parte y detalle de la ingesta). Los filtros de estudio toman las filas de las partes de ese estudio sin depender del ítem; con una muestra cuentan las filas asociadas a sus ítems; el período usa la fecha de la fila. La fila guarda fecha y encuestador (`sav_fila.fecha`, `sav_fila.encuestador`) para contarlas sin releer el archivo.
- **Teléfonos de la sala:** `EC_TEL_USADO` y `EC_TEL_ALT` se crean si no existen, se vinculan con origen «sala» y quedan **verificados**, con historia del vínculo y el linaje de la fila. Se normalizan con los prefijos de salida de la configuración. **Q1: una calidad negativa explícita gana** («no corresponde», «intermediario», «inexistente» para el número usado): ese número no se verifica. Un intermediario confirmado por el data steward no se verifica (decisión humana).
- **Motivo por fila** (`sav_fila.avisos`): «fila sin ítem asociado: en Conciliación», «EC_TEL_USADO no normalizable» (con el valor), «EC_TEL_USADO vacío», «EC_TEL_ALT vacío». El detalle de la ingesta los lista con conteos y filas de ejemplo. Al conciliar, la fila se aplica completa (teléfonos y contacto incluidos) y sale el aviso de «sin ítem».
- **Contacto–teléfono** (`contacto_telefono`): el contacto queda relacionado con el número por el que se habló («se habló el …», con estudio y parte) y con `EC_TEL_ALT` («número del contacto»). Reemplaza `telefono_vinculo.contacto_id`, que admitía un contacto por número (se migró). Volver a ingerir no suma «veces».
- **Línea de tiempo** con historia de contactos (`contacto_historia`, append-only con la misma excepción de purga que la historia de empresa) y lo que trajo cada ingesta agrupado en una línea desplegable («Ingesta .sav #12 (Estudio, Parte): 1 contacto nuevo, 1 teléfono verificado, ítem completo»).
- **Migración de lo ya ingerido:** «Corregir mapeo → Reaplicar» (`sav.remapear`) aplica la regla nueva a cada ingesta existente.

**Descartado.** Seguir buscando el resultado en una variable (Alchemer no exporta parciales); verificar igual un número que la sala marcó como que no corresponde (Q1).

**Consecuencias.** Migración `0010_sav_contactos.sql`. Hay que reaplicar las ingestas existentes después de desplegar (guía `docs/despliegue_mejoras_sav_contactos.md`).

## D40 — Los contactos como entidad

**Contexto.** Los contactos solo los creaba el .sav: no se podían cargar, agregar, editar ni borrar, ni tenían atributos. D34 había decidido que las bases no traen contactos; en la práctica sí los traen (D-d).

**Decisión.**

- **Alta, edición y borrado manual** en la pestaña Contactos de la ficha, para administrador y data steward (coordinador y lectura reciben 403). Campos: nombre (obligatorio), cargo, área, email (validado), sucursal, teléfonos (de la empresa o uno nuevo, que se vincula como manual) y atributos de contacto. Cada campo que cambia queda en `contacto_historia` con fuente manual y el usuario. Si el nombre normalizado coincide con otro contacto de la empresa, se avisa y se ofrece editar el existente.
- **Borrado definitivo** (dato personal, Ley 18.331): el contacto, su historia (purga), sus teléfonos de contacto, sus atributos y su «no llamar». En Auditoría queda `contacto.borrar` con el RUT de la empresa y el id del contacto, **sin el nombre**.
- **Contactos en la carga** (bloque «Contacto» del mapeo): un contacto por fila; se identifica dentro de la empresa por nombre normalizado o email; si existe, se completan solo los campos vacíos; su teléfono se vincula con el origen de la fila y queda como «número del contacto». Sin nombre, la fila se ignora con aviso. Deshacer o borrar la carga quita los contactos que trajo. Con un contacto en el archivo, una columna «Email» genérica se propone como email del contacto.
- **Atributos de contacto:** el catálogo tiene ámbito (`empresa` | `contacto`) y dos pestañas. Los valores van en `contacto_atributo` con historia. Se cargan desde la carga, desde el .sav (cualquier variable, con traducción de valores para las listas) y desde la ficha. No filtran ni estratifican el sorteo (P2). El ámbito no cambia después.
- El rol de lectura sigue viendo «(dato personal oculto)», también en la línea de tiempo.

**Descartado.** Deduplicar contactos entre empresas (fuera de alcance); varios contactos por fila de carga (P1).

**Consecuencias.** Tablas `contacto_historia`, `contacto_telefono`, `contacto_atributo` (migración 0010).

## D41 — Normalización y fusión de atributos

**Contexto.** La clave de un atributo se escribía a mano, nada detectaba que «Cant. empleados» y «Cantidad de empleados» eran el mismo atributo y los valores de lista distinguían mayúsculas.

**Decisión.**

- **Solo nombre y tipo son obligatorios.** Una lista puede quedar sin opciones (se completan en la carga). **La clave se genera sola** del nombre (minúsculas, sin tildes, guiones bajos, hasta 40 caracteres; `_2`, `_3` si existe) y no cambia si cambia el nombre. La API sigue aceptando una clave explícita; la web nunca la pide.
- **Atributos parecidos** con `pg_trgm` (extensión incluida en Cloud SQL): al mapear una carga, cada columna que no se reconoce se compara con nombres, claves y sinónimos (sin mayúsculas, tildes, puntuación ni palabras vacías como «de», «la», «cant.»), con umbral configurable (`umbral_similitud_atributos`, 0,6). Se ofrece «Usar ese atributo»: el nombre de la columna queda como sinónimo y la próxima base se mapea sola. Al crear un atributo parecido a otro se avisa.
- **Valores de lista** sin distinguir mayúsculas, tildes ni espacios («SI», «si» y «Sí » son «Sí», sin pedir traducción); los parecidos («Exportadora» / «Exportador») se sugieren en la traducción, nunca se aplican solos. **Texto:** se recortan espacios y se puede normalizar a mayúscula inicial o MAYÚSCULAS por atributo.
- **«Fusionar con…»** (solo administrador): A dentro de B, mismo ámbito, mismo tipo o B de texto. Los valores de A pasan a B como historia nueva (fuente `fusion`, `detalle.fusionado_de`) y se recalcula el vigente; nombres y sinónimos de A pasan a B; las opciones se unifican; A queda inactivo con la nota «fusionado en B» y nunca vuelve a tener valor vigente propio; las plantillas que usaban A se mapean a B. Bloqueado si A filtra o estratifica una muestra activa (se dice cuál). Auditoría `atributo.fusionar`.
- El atributo de sistema `id_informado` (D42) no se edita, borra ni fusiona.

**Consecuencias.** `CREATE EXTENSION pg_trgm` en la migración 0010 (lo crea el dueño de la base; ver la guía si Cloud SQL lo rechaza). Sin costo adicional.

## D42 — Base provisoria: empresas sin RUT

**Contexto.** Una base sin RUT (un directorio, un relevamiento web) se rechazaba entera aunque fueran empresas reales, y una fila con otro identificador se perdía (D-c).

**Decisión.**

- **Dos bases en la misma tabla** (`empresa.base`: `definitiva` | `provisoria`), para no duplicar teléfonos, contactos, muestras, CDR ni .sav. `rut` admite NULL **solo** en la provisoria (CHECK). Cada provisoria tiene un **código `P-` + id** (columna generada `codigo`, que en la definitiva es el RUT): sirve en la URL de la ficha, el buscador, la exportación y el .sav.
- **Cargas:** destino «Base definitiva» (como siempre) o «Base provisoria» (RUT opcional). En la provisoria, una fila con RUT válido va a la definitiva (opción activada por defecto). En la definitiva, la opción «Enviar las filas sin RUT válido a la provisoria» (desactivada por defecto) evita rechazarlas. Un identificador que no es RUT válido queda en el atributo de sistema `id_informado`. Las reglas comparan contra las dos bases. El destino queda en la carga y en la plantilla.
- **Pantalla «Base provisoria»** (data steward y administrador): código, razón social, teléfonos, carga, muestras, candidatas en la definitiva (teléfono, razón social y dirección parecidas, dominio, y el RUT que propuso el .sav), «Agregar RUT», «Fusionar con…», «Es otra empresa» y completar RUT por archivo `codigo_provisorio;rut` con preview. Inicio cuenta la provisoria aparte; «Empresas» sigue contando solo la definitiva.
- **Pasar a la definitiva:** «Agregar RUT» con un RUT válido nuevo (`empresa.promover`, con historia del campo `rut`); si el RUT existe, se ofrece fusionar la provisoria dentro de esa empresa (fusión existente, reversible). Los ítems de muestra y las llamadas de la absorbida se ven desde la absorbente.
- **Uso:** filtro «Base» en el buscador (definitiva por defecto); **Q2: «Incluir la base provisoria» viene desmarcado** en el sorteo (no cambia el marco de los estudios en curso; solo se guarda si se marca); las provisorias pasan por las mismas reglas de disponibilidad. La exportación agrega `EC_ID_EMPRESA` (código) y deja `EC_RUT` vacío; el .sav se asocia por `EC_ID_ITEM`. Un `EC_RUT` válido para una provisoria queda propuesto, no se aplica solo.

**Descartado.** Una tabla aparte para la provisoria (duplicaba todo el modelo); enriquecer el RUT automáticamente (P2).

**Consecuencias.** Migración `0011_base_provisoria.sql`. Las consultas que mostraban o enlazaban por RUT usan el código.

## D43 — Reglas de fusión en cascada

**Contexto.** La carga admitía una sola regla de fusión (`carga.regla_fusion`); hace falta una cascada (RUT, nombre, dirección…) y decidir los casos dudosos.

**Decisión.**

- **Lista ordenada de reglas por carga** (y en la plantilla): criterio (`rut`, `razon_social`, `telefono`, `dominio_web`, `direccion` con departamento, `email` de contacto) y tipo **exacta** (después de normalizar: tildes, mayúsculas, puntuación, sufijos societarios) o **flexible** (similitud `pg_trgm` ≥ umbral por regla, 0,85 por defecto). El RUT va siempre primero. Las cargas existentes se migran como lista de una regla.
- **Por fila:** gana la primera regla con resultado. Exacta con una candidata: se fusiona sola. Exacta con varias, flexible, o una coincidencia que uniría dos RUT válidos distintos: **se consulta**. Ninguna: alta (en la definitiva con RUT; en la provisoria sin RUT si el destino o la opción lo permiten; si no, rechazo).
- **«Coincidencias a decidir»** en el preview: la fila y su candidata lado a lado, regla y similitud; por fila «Fusionar», «Es otra empresa» o «Decidir después»; acciones masivas (≥ 95 %, ninguna). La confirmación usa esas decisiones, que quedan en la carga (`carga.decisiones`) y en Auditoría; lo que queda en «Decidir después» va a Revisión de fusiones con criterio y similitud.
- **Deshacer la carga** revierte lo que se fusionó en ella (sus datos) y las provisorias que pasó a la definitiva (`carga_promocion`).

**Descartado.** Fusionar sola una coincidencia flexible; unir dos RUT válidos distintos sin consultar.

**Consecuencias.** Columnas `carga.reglas`, `carga.opciones`, `carga.decisiones`, `revision_fusion.similitud`; índices de trigramas sobre razón social y dirección. La API anterior (`regla_fusion`) sigue funcionando.

## D44 — Templates de sorteo, empresas sin teléfono por muestra y filtros y estratos con todos los datos

**Contexto.** Cada muestra se armaba desde cero aunque se repitiera en cada ola; las empresas sin teléfono solo podían entrar al sorteo apagando la regla para todo el sistema; y solo los atributos marcados con las casillas «filtro» y «estrato» (y de lista, para estratos) servían en el sorteo. Además, los nombres de los formatos del CSV («uContact», «Planilla de la muestra») no decían qué generaban. (Spec: `specs/SPEC_templates_sorteo_sin_telefono_formatos_csv.md`, versión 3; decisiones de Germán Araújo del 17/11/2026.)

**Decisión.**

1. **Los templates son copias de criterios, no referencias vivas.** Un template (`muestra_template`) guarda los pasos 1 a 3 del asistente: filtros (de campo, por atributo, orígenes, base provisoria y empresas sin teléfono), estratos (con sus tramos y agrupamientos) y tamaños por estrato (con los descartados). No guarda la semilla, el estudio, el nombre ni las opciones de exportación. La muestra guarda su propia copia de los criterios y su `template_id`: **editar el template después no cambia las muestras ya creadas ni sorteadas**, y Verificar reproducibilidad no se ve afectado. Al aplicar un template los criterios se revalidan con las reglas actuales: lo que ya no existe (un atributo inactivo, un origen borrado) se saca con aviso, sin bloquear. El paso 3 marca los estratos del template sin empresas en el marco y los nuevos del marco. Un template se borra solo si nunca se usó; si no, se desactiva. Los ven y usan jefe y administrador. Auditoría: `muestra_template.crear`, `.editar`, `.borrar` y `muestra.crear` con `template_id`.
2. **Las empresas sin teléfono son opcionales por muestra.** «Incluir empresas sin teléfono discable» (`criterios.incluir_sin_telefono`) viene **desmarcado** (Q1): sin marcar, el comportamiento es el de siempre. Marcado, la regla `sin_telefono_discable` no se aplica a esa muestra; las demás sí (enfriamiento, muestra activa, no llamar, naturaleza excluida, baja, cerrada). Si la regla está apagada en la configuración general, la opción aparece marcada y deshabilitada. El filtro por origen sigue igual (una empresa sin teléfonos no tiene ninguno de ese origen). El sorteo y la vista previa cuentan las sin teléfono por estrato; el formato «Una fila por empresa» las trae con las columnas `tel_*` vacías y «Una fila por número» no las trae.
3. **Todo dato de la empresa sirve como filtro y como estrato**, sin habilitarlo antes: los campos fijos (razón social, fantasía, naturaleza, CIIU completo / a 2 / a 1 dígito, tamaño, departamento, localidad, dirección, web, estado) y todo atributo de empresa activo, de cualquier tipo. **Nunca los de contacto.** Filtros: lista (opciones), texto («contiene», «es uno de» sin mayúsculas ni tildes, «tiene dato» / «no tiene dato»), número y fecha (desde / hasta), cada uno con «incluir empresas sin dato»; se combinan con «y». Estratos: lista (uno por opción), texto (uno por valor normalizado, con «Otros» para los de menos de N empresas o fuera de los N más frecuentes), número (tramos que define el usuario, con cuartiles o tramos iguales sugeridos), fecha (año, semestre o tramos). Las reglas quedan en los criterios (`campos`, `estratos_def`) y el estrato de cada empresa se congela en el snapshot. **Se reemplaza la habilitación por casillas de la carga v2 (D34)**: «filtro» y «estrato» se quitan del formulario y de las validaciones; las columnas quedan sin uso.
4. **Formatos del CSV:** «Una fila por empresa» (primera y por defecto) y «Una fila por número»; los archivos se llaman `muestra{N}_parte{M}_por_empresa.csv` y `…_por_numero.csv`. El contenido no cambia. La API conserva los valores internos (`planilla`, `ucontact`).

**Descartado.** Templates que se apliquen «en vivo» (romperían la reproducibilidad); filtrar o estratificar por atributos de contacto; templates con opciones de exportación (P2); filtros combinados con «o» (P1).

**Consecuencias.** Migración `0012_templates_sorteo.sql`: tabla `muestra_template`, `muestra.template_id` (ON DELETE SET NULL), se quita el CHECK de `estratificable`, índices de `empresa_atributo` por atributo y valor, y la función `norm_txt`. La vista previa del marco responde en menos de 1 segundo con 100.000 empresas. Sin costo de infraestructura.

## D45 — Proveedores del enriquecimiento y riesgo de Google Places

**Contexto.** Muchas empresas no tienen un teléfono discable y conseguirlo es trabajo manual de la sala. La fase 2 del PRD preveía una cascada de fuentes externas. (Spec: `specs/SPEC_fase2_enriquecimiento.md`; decisiones de Germán Araújo del 17/11/2026, D-1 y D-5.)

**Decisión.**

1. **Proveedores:** Google Places (Text Search, SKU Enterprise: devuelve teléfono y sitio), Brave Search (para encontrar el sitio oficial) y un **modelo chico de Claude** (hoy `claude-haiku-5-5`, parámetro de la configuración) que lee la portada y la página de contacto del sitio y devuelve, con salida estructurada (JSON schema), teléfonos, emails institucionales, dirección y si el sitio es de un estudio contable o jurídico. Tavily y SerpAPI no se integran salvo que se mida que hacen falta.
2. **Se guarda el teléfono que devuelve Places**, con origen `google_places` en cada vínculo. Los términos de Google Maps Platform permiten guardar el `place_id` sin límite y la ubicación por 30 días, pero no habilitan expresamente guardar el teléfono ni el resto del contenido. **Riesgo aceptado** por dirección, con mitigaciones: el origen queda en cada vínculo (se puede borrar o desactivar en bloque), un interruptor de la configuración apaga Places sin desplegar, la latitud y la longitud no se piden ni se guardan, y se recomienda una consulta legal antes de usar Places en volumen (Q4).
3. **Claves en Secret Manager**, una por proveedor (`empresas-places-key`, `empresas-brave-key`, `empresas-anthropic-key`), con el patrón de la contraseña del CDR: se cargan desde Configuración → Enriquecimiento, nunca se devuelven y la Auditoría registra solo qué secreto cambió. Sin clave, el proveedor aparece «no configurado» y la cascada lo saltea.
4. **Datos personales (Ley 18.331):** solo datos institucionales. El prompt prohíbe nombres, celulares y emails de personas, y la salida **se valida** en el código: se descartan los teléfonos marcados como de una persona o que el texto presenta junto a un nombre o un título (Sr., Lic., Cr.…) y los emails cuya parte local no es genérica (info@, contacto@, ventas@…). El registro de cada paso guarda solo cuántos datos se descartaron, nunca cuáles.
5. **Orígenes y atributos de sistema nuevos:** orígenes `google_places` («Google Places») y `web` («Sitio web») con prioridad baja (900 y 910, editable); atributos `email_institucional`, `google_place_id` y `rubro_descubrimiento`. Rendimiento por origen mide sola cuánto rinde cada fuente paga.

**Descartado.** Enriquecimiento masivo automático (D46); scraping de directorios; Tavily y SerpAPI por ahora.

## D46 — Enriquecimiento bajo demanda con topes

**Contexto.** Enriquecer toda la base costaría del orden de US$2.400 cada 50.000 empresas; el gasto tiene que estar acotado y ser visible (D-2).

**Decisión.**

1. **Bajo demanda:** desde una muestra (empresas sin teléfono discable, o todas), desde Empresas con los filtros de la pantalla, o desde la ficha. Lanzan el administrador y el data steward; el jefe de estudio, solo desde una muestra.
2. **Estimación aprobada antes de gastar.** La corrida nace «estimada» con la lista de empresas, las salteadas y su motivo (teléfono verificado, enriquecida en los últimos 90 días, no llamar, cerrada, provisoria con candidata en la definitiva —se sugiere fusionar— y, según el corte, las que ya tienen teléfono discable), el **costo máximo** (todos los pasos para todas, con las llamadas gratuitas de Places que quedan en el mes) y el **esperado** (con la tasa de éxito medida de Places; 60 % mientras no haya 20 pasos de historia). Si el máximo supera lo permitido (el menor entre el tope por corrida y lo que queda del mes) o el máximo de empresas por corrida, hay que reducir la cantidad (primeras o al azar) para aprobar.
3. **Cascada de lo más barato a lo más caro:** fuentes propias (US$0) → Places → Brave (solo si falta el sitio) → lectura del sitio + Claude (solo si falta el teléfono). **El corte es configurable (Q1):** por defecto se corta apenas hay un teléfono; con «teléfono y sitio web» sigue hasta tener los dos. Un resultado de Places se acepta si el nombre tiene similitud de trigramas ≥ 0,6 y el departamento coincide cuando hay dato.
4. **Tope duro:** antes de cada llamada paga se **reserva** su costo máximo en `enriquecimiento_paso`, en una transacción propia con un lock, verificando el gasto de la corrida y el del mes. Si no entra, la corrida se detiene («detenida por tope») sin hacer esa llamada. Después se registra el costo real (Claude, por tokens de entrada y de salida). Así ni las corridas concurrentes superan el tope mensual.
5. **Se guarda empresa por empresa:** cancelar o llegar al tope no pierde lo conseguido. La corrida corre como tarea (Cloud Tasks) con progreso.
6. **Los datos entran con confianza 30** (cargas 50, sala 80): el sitio, la dirección y el email son historia con fuente `enriquecimiento` y nunca pisan datos de mejor fuente; los teléfonos entran «sin verificar» y los verifica la sala con el .sav. Un sitio de estudio contable o jurídico marca sus teléfonos como intermediario sospechoso, con el motivo, y van a la bandeja de Intermediarios.
7. **Deshacer** una corrida quita sus vínculos, su evidencia de origen y sus valores (la historia de una corrida deshecha deja de contar en la regla de supervivencia), salvo los teléfonos que la sala ya verificó.

**Descartado.** Enriquecimiento automático al cargar o al sortear (queda como aviso sugerido, P1); topes «blandos» que solo avisen.

**Consecuencias.** Tablas `enriquecimiento_corrida` (también los lotes de descubrimiento) y `enriquecimiento_paso`; `telefono.intermediario_motivo`; la historia acepta las fuentes `enriquecimiento` y `descubrimiento`. Bloque `enriquecimiento` en la configuración versionada (precios, topes, confianza, corte, modelo). Costo: solo el uso de las APIs, siempre bajo el tope mensual (valor inicial US$100).

## D47 — Duplicados difusos y grupo económico

**Contexto.** Las reglas de fusión resuelven filas sin RUT, pero no detectan dos empresas con RUT distinto que son la misma o del mismo grupo (D-3).

**Decisión.**

1. **Detección diaria** (Cloud Scheduler, y a mano desde la bandeja) de pares de la base definitiva con RUT distinto que comparten un teléfono discable (sin intermediarios y sin teléfonos con 5 o más RUT), el dominio del sitio (sin una lista editable de dominios genéricos), la dirección normalizada con el departamento, o una razón social con similitud ≥ 0,9 sin forma societaria.
2. **Bandeja «Posibles duplicados»** con el par lado a lado y la evidencia. Tres decisiones, todas auditadas: **fusionar** (la fusión reversible de siempre, eligiendo cuál queda), **son grupo económico** (`grupo_economico` y `empresa.grupo_economico_id`: quedan relacionadas sin fusionarse; si una ya está en un grupo, la otra se suma) y **sin relación** (el par no se vuelve a proponer). Un par con una empresa dada de baja queda obsoleto.
3. **Sorteo:** «Como máximo una empresa por grupo económico» (`criterios.una_por_grupo`), **marcada por defecto** en una muestra nueva (Q3). Si sale una empresa de un grupo que ya tiene otra en la muestra, se saltea y sigue la siguiente del orden; primero se completan los titulares de todos los estratos y después los reemplazos. La pertenencia a grupos se congela en el snapshot (`marco_snapshot_item.grupo_id`), así Verificar reproducibilidad sigue funcionando. La opción va en los criterios y en los templates; sin la clave (muestras viejas), el sorteo es el de siempre.

**Descartado.** Fusionar automáticamente por un criterio (siempre decide el data steward). La exclusividad por cliente o tema queda fuera de esta fase (D-4).

## D48 — Tablero de calidad

**Contexto.** No había una medida de la calidad de la base ni una lista de trabajo semanal para el data steward.

**Decisión.** Pantalla «Calidad de la base» (administrador, data steward y jefes) con una tarjeta por dimensión DMBOK del PRD —validez, unicidad, completitud, exactitud, actualidad, consistencia y base provisoria (informativa)—, cada indicador con su valor, meta, estado (cumple, cerca a 5 puntos, no cumple) y evolución. La exactitud se evalúa contra la medición de hace un trimestre («sube cada trimestre»). Cada indicador abre la lista de lo que lo incumple, con enlace a cada ficha; las alertas de consistencia (naturaleza que no coincide con la razón social, por ejemplo «SRL» con «… S.A.») se marcan como revisadas y vuelven si cambia la naturaleza o la razón social. Una tarjeta de enriquecimiento muestra el gasto del mes contra el tope, por proveedor, y el **costo por teléfono verificado** (gasto de enriquecimiento sobre los teléfonos de origen Google Places o Sitio web que pasaron a verificados), en el mes y acumulado, contra la meta de US$0,10. Un Cloud Scheduler diario guarda la foto de cada indicador en `calidad_medicion` (se puede correr dos veces: reemplaza la del día).

**Descartado.** Calcular la evolución sin histórico (no se puede reconstruir); un reporte por correo (P1).

## D49 — Editar y borrar naturalezas jurídicas

**Contexto.** La pantalla de Naturalezas jurídicas solo permitía crear naturalezas y marcarlas como excluidas: no había forma de corregir un nombre ni de sacar una naturaleza que sobraba.

**Decisión.**

1. **Se edita el nombre y la exclusión; el código, solo si la naturaleza no se usa.** El código es el identificador que guardan la historia de cada empresa (`empresa_campo_historia`, campo `naturaleza`), la configuración (`naturalezas_excluidas`, también en las versiones anteriores) y los criterios de las muestras y los templates. Cambiarlo rompería esas referencias. El nombre no puede quedar vacío ni repetir el de otra naturaleza.
2. **Se borra solo si ninguna empresa la tiene ni la tuvo**: ninguna empresa (activa o dada de baja) con esa naturaleza y ningún dato de la historia con ese código. Si estaba excluida, primero se saca de las excluidas con una versión nueva de la configuración.
3. **Auditoría:** `naturaleza.crear`, `naturaleza.editar` (con antes y después) y `naturaleza.borrar`. Solo el administrador.
4. **Compatibilidad:** `POST /api/naturalezas` sigue creando o actualizando (lo usan la demo y `fase0/cargar_excluidos.py`); la pantalla no deja crear un código que ya existe.
5. **Rutas por id, no por código (corrección del 20/11/2026).** Editar y borrar van a `PUT` / `DELETE /api/naturalezas/{id}`. El alta anterior no validaba el código y en producción quedó una naturaleza con el código vacío: con el código en la URL, el borrado iba a `/api/naturalezas/`, la API respondía una redirección 307 a la dirección directa de Cloud Run y el navegador la cortaba («Failed to fetch»). Una naturaleza **sin uso** puede corregir su código (si estaba excluida, el código nuevo reemplaza al viejo en la configuración), y la migración `0014_naturaleza_codigo.sql` agrega un CHECK `NOT VALID` que impide códigos vacíos de acá en adelante sin rechazar las filas viejas, que se corrigen o se borran desde la pantalla.

**Descartado.** Cambiar el código reescribiendo la historia (la historia es append-only); borrar una naturaleza en uso dejando a sus empresas sin naturaleza.

## D50 — Cargas por lotes

**Contexto.** El 22/11/2026 la confirmación de la carga #7 (190.000 filas) corrió 30 minutos, la cortó el plazo de Cloud Run y Cloud Tasks y Postgres revirtió todo: más de 3 millones de filas escritas y descartadas. La confirmación, el preview y el borrado procesaban toda la carga en una sola transacción y una sola tarea, y «Deshacer» corría dentro del pedido HTTP (Firebase Hosting corta a los 60 s). Además, la base quedó saturada y la web dio `PoolTimeout`. Ver `specs/SPEC_cargas_grandes_por_lotes.md`. (La spec la numera D49; ese número ya lo usaba la decisión de naturalezas jurídicas.)

**Decisión (opción A de la spec).**

1. **El archivo se lee una sola vez.** Al crear la carga, sus filas se copian a `carga_fila` (`COPY`, con el número de fila y el lote) y cada lote lee solo las suyas. `carga_fila` se borra cuando la carga queda confirmada, descartada, deshecha o borrada; mientras está en preview o interrumpida se conserva para poder reanudar. Las cargas creadas antes de este cambio arman sus filas la primera vez que se procesan.
2. **Lotes por RUT.** Los lotes (5.000 filas por defecto) se arman agrupando por RUT válido: todas las filas con el mismo RUT caen en el mismo lote, aunque estén lejos en el archivo, y un grupo nunca se parte. Las filas sin RUT van al final; si hay más de un lote de filas sin RUT, el preview marca sus conteos como **aproximados** (`aproximado_sin_rut`), porque dos filas sin RUT de lotes distintos podrían coincidir entre sí.
3. **Preview, confirmación, deshacer y borrado son tareas por pasos.** Cada paso es una transacción y una ejecución de la tarea (`tareas.Continuar`): al hacer commit, la misma tarea vuelve a la cola para el paso siguiente, con una pausa configurable (1 s) para que la web siga respondiendo. El estado de cada lote queda en `carga_lote` (preview hecho, pendiente / en proceso / aplicado / error, conteos, intentos, duración, error). Se loguea una línea por lote (`carga=… lote=… filas=… segundos=…`) y una ALARMA si un lote supera 10 minutos.
   - **Preview:** cada lote corre en un savepoint que se descarta y guarda sus conteos; el total es la suma. Las coincidencias a decidir se acumulan por número de fila, como antes.
   - **Confirmación:** cada lote aplica sus filas con la misma `carga_id` como fuente y detecta intermediarios sobre los teléfonos que tocó. El paso final suma los conteos, audita `carga.confirmar`, deja la carga «confirmada» y libera `carga_fila`.
   - **Idempotencia:** un lote «aplicado» no se vuelve a aplicar (Cloud Tasks puede reintentar). Un lote que falló se revirtió entero y se reintenta entero.
   - **Deshacer** deja de ser sincrónico: quitar los aportes en tandas de 20.000 filas, recalcular las empresas tocadas de a 2.000, anular las que quedaron sin respaldo y reevaluar intermediarios en tandas. Mientras dura, la carga está «deshaciendo» y ya no cuenta como respaldo de ninguna empresa.
   - **Borrar** va por los mismos pasos, con el estado «borrando». Si se corta, volver a tocar «Borrar carga» retoma desde el paso en que quedó.
4. **Estado «interrumpida».** Una carga queda interrumpida si un lote falla, si se cancela su tarea o si la tarea figura corriendo sin avanzar más de 35 minutos (más que el plazo de Cloud Tasks; lo revisan la pantalla de cargas y el job diario). Lo aplicado por los lotes terminados queda; el lote en curso se revirtió. Desde la pantalla: **Reanudar** (sigue desde el primer lote o paso no hecho), **Deshacer** (quita lo aplicado) o **Borrar**. Una carga interrumpida durante el preview, que no aplicó nada, se descarta.
5. **Una carga pesada a la vez.** Solo una carga puede estar en preview, confirmación, deshacer o borrado por lotes al mismo tiempo (advisory lock al encolar). Otra queda en cola con el aviso «Esperando a que termine la carga #N» y arranca sola cuando termina la anterior.
6. **Una operación vigente por carga.** `carga.tarea_id` identifica la operación en curso. Al final de cada paso la tarea bloquea la fila de la carga y verifica que sigue siendo la suya: si mientras tanto se pidió borrarla, el paso se revierte y no pisa el borrado.
7. **Configuración** (Configuración → Cargas grandes, versionada): filas por lote (5.000; entre 500 y 20.000), pausa entre lotes (1 s) y minutos sin avanzar para darla por cortada (35).
8. **La web** muestra «Lote N de M · X de Y filas», el avance «N de M lotes aplicados (X filas)», y consulta el progreso cada 5 s en las cargas de más de 20.000 filas.
9. **Estadísticas al día.** Al aplicar los lotes 1, 2, 4, 8… (cada vez que la carga duplica lo aplicado) se corre `ANALYZE` de las tablas que crecen. Sin eso, los planes que Postgres guarda para las consultas por fila y los chequeos de claves foráneas, armados con las tablas casi vacías, recorrían la tabla entera: en la primera carga grande, los primeros lotes tardaban de 2 a 4 veces más. Se probó forzar un plan por consulta (`plan_cache_mode`) y fue más lento.

**Medido** (test de volumen, 50.000 filas en lotes de 5.000, máquina de desarrollo): 10 a 26 s por lote de preview y unos 10 s por lote de confirmación (el primero, 39 s); 5 minutos en total. La meta es menos de 3 minutos por lote en producción.

**Compatibilidad.** Las reglas de negocio de la carga (mapeo, fusión, supervivencia, orígenes, atributos, contactos, base provisoria) no cambian: los tests de cargas corren con lotes de 2 filas para forzar varios lotes. Una carga chica es un solo lote.

**Descartado.** B, correr la carga como Cloud Run job en una sola transacción: satura la base durante horas. C, agrandar la base como única solución: cuesta más y no garantiza bajar de 30 minutos. Lotes en paralelo de una misma carga (P2). Reescribir `procesar` para precargar todo el lote en pocas consultas: se deja para cuando las mediciones en producción lo pidan, porque cambia el código que decide cada fila y el tiempo medido por lote ya está lejos del límite. Ajustar `CARGAS_TAMANO_LOTE` y `CARGAS_PAUSA` por variable de entorno queda para los tests.

## D51 — Crear la carga sin esperas mudas

**Contexto.** Con un archivo de 193.556 filas, «Siguiente» en el paso 2 de la carga no mostraba nada. El archivo se parseaba tres veces: al analizarlo, al revisar los valores a traducir (`POST /cargas/valores`) y al crear la carga (`POST /cargas`, que además copiaba todas las filas). Las dos últimas, dentro de pedidos sincrónicos, sin aviso en la pantalla, y Firebase Hosting corta a los 60 s: el navegador recibía un error mientras la API seguía y creaba la carga igual, y un segundo «Siguiente» creaba otra. Ver `specs/SPEC_crear_carga_asincrona.md`.

**Decisión.**

1. **El archivo se parsea una sola vez, al analizarlo.** Sus filas quedan en `archivo_fila` (`archivo_id`, `fila`, `datos`) y sus columnas y su cantidad de filas, en `archivo`. Todo lo que sigue sale de ahí. Si un archivo no tiene sus filas guardadas (uno subido antes de este cambio, o uno cuyas filas ya se liberaron), se leen y se guardan una vez, la primera vez que hacen falta. El log dice «archivo N parseado».
2. **Un archivo grande se lee en segundo plano.** Si pesa más de 10 MB o tiene más de 20.000 filas (estimadas sin parsearlo: los saltos de línea de un CSV, o la dimensión de la hoja de un Excel, o sus filas contadas en el XML), «Analizar» guarda el archivo, crea la tarea `archivo.leer` y responde enseguida. La pantalla muestra «Leyendo el archivo… N filas» y el resultado de la tarea es el mismo análisis de siempre. Los archivos chicos siguen igual que antes.
3. **Los valores a traducir se cuentan con una consulta** sobre `archivo_fila` (un `GROUP BY` del valor de cada columna), con la misma limpieza de siempre: con 200.000 filas tarda 0,1 s. Mientras tanto, «Siguiente» queda deshabilitado con «Revisando los valores…».
4. **Crear la carga responde enseguida.** Valida el mapeo con las columnas del análisis, verifica la traducción con la misma consulta, crea la carga y la plantilla y encola el preview: 0,1 s con 200.000 filas. El **primer paso del preview** reparte las filas en lotes por RUT (D50) con «Preparando los lotes…» (3 s con 200.000 filas); `carga_fila` guarda solo el lote de cada fila, y los datos se leen de `archivo_fila`. La pantalla muestra «Creando la carga…», «Preparando los lotes…» y «Calculando el preview… Lote N de M».
5. **Sin cargas duplicadas.** La web genera una clave al abrir el paso del mapeo y la manda al crear: la misma clave de la misma persona devuelve la carga ya creada (`carga.clave`, única por responsable). Además, si la misma persona está creando una carga de ese archivo (en «analizando», en los últimos 10 minutos), «Siguiente» ofrece **Ir a la carga #N** en lugar de crear otra.
6. **Las filas intermedias se liberan.** Al confirmar, descartar, deshacer o borrar la carga (si ninguna otra carga en curso usa el archivo), y en el job diario de calidad, que libera las de los archivos de hace más de 24 horas que ninguna carga en curso necesita. No hace falta otro Cloud Scheduler.

**Descartado.** Subir el archivo directo al bucket con una URL firmada (P2, para archivos de más de 30 MB). Guardar las filas en un CSV normalizado en el bucket: la tabla permite contar valores y leer lotes con una consulta.

## Preguntas abiertas que heredan del PRD

| Pregunta | Quién | Impacto en lo construido |
| --- | --- | --- |
| ¿Cuántos meses de enfriamiento? | Dirección | Solo un parámetro (D30) |
| ¿Qué padrón o directorio se usa como semilla y con qué licencia? | Dirección + legal | Cada carga registra su licencia |
| ¿Hay que inscribir la base ante la URCDP? | Legal | No bloquea construir; sí operar |
| ¿Qué destinos del CDR son internos? | Coordinación de campo | Lista inicial en `fase0/datos/destinos_internos.csv`; se edita en la configuración |
