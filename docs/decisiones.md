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

- **Núcleo fijo, atributos administrables.** RUT, razón social, fantasía, naturaleza, CIIU, tamaño, departamento, localidad, dirección, web y estado siguen en el código: de ellos dependen la disponibilidad, los estratos, la fusión y las exclusiones. Todo lo demás es un **atributo** (`atributo`: clave inmutable, tipo texto/número/fecha/lista, sinónimos, filtro, estrato, activo) que crea un administrador.
- **Mismo linaje para los atributos.** La historia va a `empresa_campo_historia` con `campo = 'atributo.<clave>'` y la misma regla de supervivencia (D07). `empresa_atributo` guarda el ganador **tipado** (texto, número o fecha) para filtrar y estratificar en SQL. Un número o una fecha que no se puede interpretar no rechaza la fila: queda como crudo, se cuenta como inválido y no entra a los filtros.
- **El origen del teléfono es evidencia del vínculo**, no un atributo del teléfono: `telefono_vinculo_origen` (vínculo, origen, carga, fecha), único por vínculo y origen. Un número que llega de dos orígenes queda con los dos; un teléfono cuenta en cada origen y los totales lo cuentan una vez. El catálogo `origen_telefono` tiene prioridad (el orden del CSV) y tres orígenes de sistema: **Sala** (`EC_TEL_ALT`), **Manual** (ficha) y **Sin dato** (vínculos anteriores al cambio, que la migración deja así).
- **Origen por columna o fijo, con origen por defecto obligatorio.** El mapeo guarda `origenes_telefono` ({columna de teléfono: {columna} | {fijo}}) y `origen_defecto`; `telefonos` sigue siendo la lista de columnas, así las plantillas viejas siguen abriendo.
- **Traducción de valores confirmada, nunca automática.** Los valores de origen y de atributos de lista que no coinciden exactamente con el catálogo se listan con su cantidad de filas; se sugiere sin mayúsculas, tildes ni espacios, pero la API rechaza la carga mientras quede alguno sin traducir. Es el criterio de la ingesta del .sav (D23). La traducción queda en la plantilla del tipo de fuente.
- **Sin contactos en las cargas.** Se generan en el campo (`EC_RESP_*` del .sav). Una plantilla vieja con campos de contacto se abre y esos campos se ignoran con un aviso.
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

## Preguntas abiertas que heredan del PRD

| Pregunta | Quién | Impacto en lo construido |
| --- | --- | --- |
| ¿Cuántos meses de enfriamiento? | Dirección | Solo un parámetro (D30) |
| ¿Qué padrón o directorio se usa como semilla y con qué licencia? | Dirección + legal | Cada carga registra su licencia |
| ¿Hay que inscribir la base ante la URCDP? | Legal | No bloquea construir; sí operar |
| ¿Qué destinos del CDR son internos? | Coordinación de campo | Lista inicial en `fase0/datos/destinos_internos.csv`; se edita en la configuración |
