# SPEC — Carga de bases v2: atributos administrables y origen del teléfono

**Sistema:** Base de Empresas · Equipos Consultores (`araujomelogno/base-empresas`)
**Origen:** primera prueba del sistema en producción (noviembre de 2026)
**Alcance:** mapeo y preview de cargas, catálogo de atributos, catálogo y evidencia de origen de teléfonos, filtros del sorteo, exportación a uContact, tablero de actividad, estados de la carga
**Estado:** Para desarrollo
**Última actualización:** 2026-11-10

---

## 1. Problem Statement

En la primera prueba, la carga de una base resultó difícil de usar y, además, deja afuera información que importa para el negocio:

- **Los campos que se pueden cargar están fijos en el código** (`CAMPOS_MAPEO` en `api/app/cargas.py`). Un dato útil que no está en esa lista, como cantidad de empleados, exporta sí/no o cámara a la que pertenece, no tiene dónde guardarse ni sirve para sortear.
- **La pantalla de mapeo muestra los 21 campos juntos.** Todos menos el RUT ya son opcionales, pero no se nota. Parece que hay que completarlos y no se entiende qué son los campos de contacto y de sucursal.
- **Los contactos no vienen en los archivos.** Se generan en el campo, cuando el encuestador registra quién atendió y llega en el .sav. Que la carga ofrezca campos de contacto confunde.
- **No se guarda el origen de cada teléfono.** Hoy un vínculo teléfono–empresa solo dice "vino de la carga #12". No se puede saber qué orígenes (guía, DGI, web, estudio anterior…) dan teléfonos que contestan, ni sortear o exportar según el origen. Es la información que define dónde conviene conseguir teléfonos.
- **La cantidad de teléfonos por fila no se ve en el preview.** El sistema ya admite filas con distinta cantidad de teléfonos, pero el preview no lo muestra.
- **El estado de la carga es una palabra suelta** (analizando, preview, en proceso, confirmada, deshecha, error). No dice qué significa ni qué hacer. Además, descartar una carga en preview la deja como "deshecha", igual que deshacer una confirmada, y son cosas distintas.

## 2. Goals

1. **Cualquier dato de una base se puede guardar y usar sin tocar código:** un administrador crea un atributo nuevo y la próxima carga ya lo puede mapear, filtrar y estratificar.
2. **Cada teléfono cargado tiene su origen:** el 100% de los vínculos creados por una carga queda con al menos un origen.
3. **Se puede medir el rendimiento de cada origen:** contactabilidad, contactos efectivos y % de números que no corresponden, por origen y por estudio.
4. **El sorteo y la exportación pueden usar el origen:** filtrar empresas por origen de sus teléfonos, filtrar los teléfonos del CSV y ordenarlos por prioridad de origen.
5. **Un data steward hace su primera carga sin ayuda:** el mapeo muestra solo lo relevante y cada estado de la carga explica qué significa y qué sigue.

## 3. Non-Goals

- **Volver administrables los campos del núcleo** (RUT, razón social, fantasía, naturaleza, CIIU, tamaño, departamento, localidad, dirección, web, estado). Las reglas de disponibilidad, estratos, fusión y exclusiones dependen de ellos: si se pudieran borrar o renombrar, se rompería el sorteo.
- **Cargar contactos desde un archivo.** Los contactos se generan con las respuestas del campo (`EC_RESP_*` en el .sav). Si algún día una base trae contactos, se especifica aparte.
- **Empresas sin RUT.** El RUT sigue siendo obligatorio; los candidatos sin RUT siguen previstos para la fase 2.
- **Recalcular el origen de teléfonos cargados antes de este cambio.** Quedan con origen "Sin dato" (P1 permite asignárselo por carga).
- **Atributos en el CSV de uContact.** El CSV sigue con sus columnas configurables actuales (P2).

## 4. User Stories

**Administrador**

- Como administrador, quiero crear un atributo (por ejemplo, «Cantidad de empleados», número) con sus sinónimos, para que las cargas lo reconozcan y se pueda usar en el sorteo.
- Como administrador, quiero definir el catálogo de orígenes de teléfono y su orden de prioridad, para que las cargas y las exportaciones hablen el mismo idioma.
- Como administrador, quiero desactivar un atributo que ya no se usa sin perder los valores cargados, para no ensuciar el mapeo.

**Data steward**

- Como data steward, quiero que el mapeo me muestre solo los campos que el sistema reconoció en el archivo y me deje agregar los demás, para no tener que revisar 21 campos que la base no trae.
- Como data steward, quiero indicar qué columna del archivo dice el origen de cada teléfono, para que cada número quede con su origen.
- Como data steward, quiero traducir los valores de origen que trae el archivo («guia», «Guía Tel.», «PAGINAS BLANCAS») a un origen del catálogo, para que el análisis no se fragmente.
- Como data steward, quiero ver en el preview cuántas filas no traen teléfono y cuántos teléfonos llegan por origen, para decidir si la base vale la pena antes de confirmarla.
- Como data steward, quiero entender en qué estado está la carga y qué tengo que hacer, para no dejar cargas a medio camino.

**Jefe de proyecto**

- Como jefe de proyecto, quiero filtrar el marco por atributos (por ejemplo, empresas con más de 50 empleados) y estratificar por un atributo de lista, para diseñar muestras que hoy no puedo armar.
- Como jefe de proyecto, quiero que solo entren al sorteo empresas con algún teléfono discable de los orígenes que elijo, para no sortear empresas que solo tienen números poco confiables.
- Como jefe de proyecto, quiero ver el rendimiento de cada origen, para decidir qué orígenes usar en el próximo estudio.

**Coordinador de campo**

- Como coordinador, quiero exportar el CSV solo con teléfonos de ciertos orígenes, o con todos pero ordenados por prioridad de origen, para que los encuestadores llamen primero a los números más confiables.

## 5. Requirements

### P0 — Must-Have

#### C1 — Catálogo de atributos administrable

- [ ] Nueva pantalla **Configuración → Atributos** (rol administrador). Cada atributo tiene: clave (única, sin espacios, inmutable una vez creada), nombre visible, tipo (`texto`, `numero`, `fecha`, `lista`), opciones (solo para `lista`), sinónimos para el mapeo automático, si sirve como **filtro** del sorteo, si sirve como **estrato** (solo `lista`) y activo/inactivo.
- [ ] Desactivar un atributo lo saca del mapeo y de los filtros, pero conserva sus valores. No se puede borrar un atributo con valores ni uno usado en una muestra activa.
- [ ] Cada cambio del catálogo queda en auditoría.
- [ ] El núcleo sigue fijo y se muestra en la pantalla como "Campos del sistema (no editables)", para que se entienda la diferencia.

#### C2 — Valores de atributos con linaje

- [ ] Una tabla nueva guarda el valor vigente por empresa y atributo, tipado (`valor_texto`, `valor_numero`, `valor_fecha`).
- [ ] La historia usa la misma `empresa_campo_historia` que hoy, con `campo = 'atributo.<clave>'`, y aplica la misma regla de supervivencia: gana la fuente de mayor confianza y, a igual confianza, la más reciente.
- [ ] **Validación por tipo al cargar:**
  - Un número o una fecha que no se puede interpretar no rechaza la fila: el valor queda como crudo y cuenta como "valor inválido" en el preview.
  - En un atributo `lista`, un valor fuera de las opciones va a la traducción de valores (C5).
- [ ] La ficha de la empresa muestra los atributos en la pestaña **Datos**, debajo del núcleo, con su fuente, confianza y fecha.
- [ ] Deshacer una carga anula también los valores de atributos que trajo.

#### C3 — Mapeo agrupado y con campos opcionales

- [ ] El paso de mapeo se divide en bloques con una línea de ayuda cada uno:
  1. **Empresa:** el núcleo. El RUT es obligatorio y está marcado.
  2. **Atributos:** los del catálogo, activos.
  3. **Teléfonos:** columnas de teléfono y su origen (C4).
  4. **Sucursal:** «un local de la empresa con dirección distinta de la fiscal». Va plegado por defecto.
- [ ] Al abrir el mapeo se muestran solo los campos y atributos que el sistema reconoció en el archivo (por nombre, sinónimo o plantilla). El resto se agrega con **+ Agregar campo**, que lista los disponibles.
- [ ] Un campo agregado y dejado sin columna no se guarda en el mapeo.
- [ ] **Se quitan los campos de contacto** (`contacto_nombre`, `contacto_cargo`, `contacto_area`, `contacto_email`, `contacto_telefono`) de `CAMPOS_MAPEO`, del mapeo y de las plantillas nuevas. Una plantilla vieja que los tenga se sigue abriendo: esos campos se ignoran con un aviso.
- [ ] Las columnas del archivo que no se usan se listan al pie («Columnas que no se van a cargar: …»), para que nada se pierda sin darse cuenta.

#### C4 — Origen del teléfono desde una columna del archivo

- [ ] Nuevo catálogo **Configuración → Orígenes de teléfono**: código, nombre, prioridad (orden), activo y si es de sistema. Viene con dos orígenes de sistema que no se pueden borrar: **Sala** (números que llegan por `EC_TEL_ALT` en el .sav) y **Manual** (agregados desde la ficha). También trae **Sin dato**, para los teléfonos anteriores a este cambio.
- [ ] En el bloque **Teléfonos** del mapeo, por cada columna de teléfono marcada se elige de dónde sale su origen:
  - **una columna del archivo** (puede ser la misma para todos los teléfonos de la fila o una por columna de teléfono, por ejemplo «Tel 1» con «Origen 1»), o
  - **un origen fijo** del catálogo para esa columna.
- [ ] **Origen por defecto de la carga:** obligatorio. Se usa cuando la columna de origen viene vacía en una fila.
- [ ] El sistema sugiere el emparejamiento por nombre de columna (`Origen 1` ↔ `Tel 1`, `Fuente tel` ↔ `Teléfono`). El data steward lo confirma.
- [ ] Si una celda de teléfono trae varios números (separados por / ; o ,), todos toman el origen de esa fila y columna.
- [ ] El origen queda como **evidencia** del vínculo, en una tabla nueva: vínculo, origen, carga y fecha, con un único registro por vínculo y origen. Un mismo número que llega de dos orígenes queda con los dos.
- [ ] La ficha de la empresa, pestaña **Teléfonos**, muestra los orígenes de cada número.

#### C5 — Traducción de valores (origen y atributos de lista)

- [ ] Después del mapeo y antes del preview, si la columna de origen o una de atributo `lista` trae valores que no coinciden exactamente con el catálogo, se muestra una tabla con los **valores distintos del archivo y cuántas filas tiene cada uno**. Para cada valor se elige:
  - un valor del catálogo,
  - **crear uno nuevo** (solo administrador), o
  - **sin dato**.
- [ ] Se sugiere la traducción sin distinguir mayúsculas, tildes ni espacios, pero **nunca se aplica sola**: hay que confirmarla. Es el mismo criterio que la ingesta del .sav y los atributos de paneles.
- [ ] La traducción queda guardada en la plantilla del tipo de fuente y se precarga en la próxima carga.

#### C6 — Preview con teléfonos y atributos

- [ ] El preview agrega:
  - filas **sin ningún teléfono**, con **1**, **2** y **3 o más**;
  - **teléfonos por origen** (nuevos y ya existentes);
  - **valores de atributos** cargados e inválidos por atributo.
- [ ] Las filas sin teléfono **no se rechazan**: la empresa se carga igual y queda no disponible por la regla «sin teléfono discable», si está activa.

#### C7 — Filtros del sorteo por atributos y por origen

- [ ] **Atributos en el marco.** En **Nueva muestra**, bloque Filtros, aparecen los atributos marcados como filtro:
  - `lista`: selección múltiple;
  - `numero` y `fecha`: desde / hasta;
  - `texto`: contiene.
- [ ] Los atributos `lista` marcados como estrato se pueden elegir en «Estratificar por».
- [ ] **Origen en el marco.** Filtro nuevo: «Solo empresas con al menos un teléfono discable de estos orígenes». Sin selección, no filtra.
- [ ] Los filtros de atributos y de origen quedan en los **criterios de la muestra**, entran al snapshot y respetan la reproducibilidad: re-sortear con la semilla da la misma lista.
- [ ] **El cuadro de exclusiones** muestra cuántas empresas dejó afuera el filtro de origen.

#### C8 — Origen en la exportación a uContact

- [ ] En **Exportar a uContact**, dos opciones nuevas que quedan guardadas en la muestra (con auditoría cuando cambian):
  - **Orígenes a exportar:** todos (por defecto) o solo los elegidos.
  - **Orden de los teléfonos:** por prioridad de origen (según el catálogo) y, dentro de cada origen, primero los verificados. Es el orden por defecto.
- [ ] Un teléfono con varios orígenes toma el de mayor prioridad para ordenar, y pasa el filtro si alguno de sus orígenes está elegido.
- [ ] El resumen previo a la descarga dice cuántos ítems quedan **sin teléfono exportable por el filtro de origen**, aparte de los que no tienen ningún teléfono discable.
- [ ] Nueva columna disponible en el formato del CSV: `origen_telefono` (el de mayor prioridad).

#### C9 — Rendimiento por origen

- [ ] Nueva tarjeta **Rendimiento por origen** en **Actividad**, con los mismos filtros de estudio, muestra y período. Por origen:

| Columna | Definición |
| --- | --- |
| Teléfonos discables | Vínculos discables con ese origen |
| Teléfonos llamados | Con al menos un intento en el período |
| Intentos | Intentos a esos teléfonos |
| Contactabilidad | Teléfonos con al menos una llamada atendida / teléfonos llamados |
| Contactos efectivos | Ítems con contacto efectivo cuyo teléfono usado tiene ese origen |
| % no corresponde | Vínculos pasados a «no corresponde» por la sala / teléfonos llamados |
| % inexistente | Ídem «inexistente» |
| % intermediario | Ídem «intermediario» |
| Intentos por contacto efectivo | Intentos / contactos efectivos |

- [ ] Un teléfono con varios orígenes cuenta en cada uno. La tarjeta lo aclara, y la fila **Total** cuenta cada teléfono una sola vez.
- [ ] La tarjeta se puede descargar como CSV.

#### C10 — Estados de la carga explicados

- [ ] Se agrega el estado **descartada** (una carga en preview o en error que no se confirmó) y se deja **deshecha** solo para una carga confirmada que se anuló. Una migración pasa a **descartada** las cargas deshechas que nunca se confirmaron.
- [ ] El detalle de la carga muestra una barra de pasos (**Archivo → Mapeo → Preview → Confirmación**) y, debajo del estado, qué significa y qué sigue:

| Estado | Qué significa | Qué sigue |
| --- | --- | --- |
| Analizando | El sistema está leyendo el archivo y calculando el preview | Esperar; la barra muestra el avance |
| Preview | Conteos listos; **todavía no se escribió nada** | Revisar y **Confirmar** o **Descartar** |
| En proceso | Se está aplicando a la base | Esperar |
| Confirmada | Aplicada a la base | Se puede **Deshacer** mientras ninguna de sus empresas haya entrado a una muestra |
| Descartada | Se revisó y no se aplicó | Nada; queda como registro |
| Deshecha | Se aplicó y después se anuló; la historia queda tachada | Nada |
| Error | Falló el análisis o la aplicación; se muestra el motivo | Corregir el archivo o el mapeo y hacer una carga nueva |

- [ ] La lista de cargas muestra el estado con su color y la misma explicación en un tooltip.

#### C11 — Tests

- [ ] **Atributos:** crear, desactivar, impedir el borrado con valores; carga con atributos de cada tipo; valor inválido como crudo; supervivencia; deshacer anula los valores.
- [ ] **Origen:** columna de origen compartida y emparejada; origen fijo; origen por defecto cuando falta; varios números en una celda; mismo número con dos orígenes; traducción de valores sugerida pero no aplicada sin confirmar.
- [ ] **Sorteo:** filtros por atributo y por origen; estratificar por atributo; reproducibilidad con los filtros nuevos; conteo de exclusiones.
- [ ] **CSV:** filtro por origen, orden por prioridad, columna `origen_telefono`, conteo de ítems sin teléfono exportable.
- [ ] **Rendimiento:** atribución a varios orígenes y total sin duplicar.
- [ ] **Estados:** descartar deja «descartada»; deshacer una confirmada deja «deshecha»; la migración de estados.
- [ ] Siguen pasando todos los tests existentes.

### P1 — Nice-to-Have

- **Asignar origen a una carga vieja:** desde el detalle de una carga anterior a este cambio, elegir un origen para todos sus teléfonos «Sin dato».
- **Origen al agregar un teléfono a mano:** en la ficha, elegir el origen (por defecto «Manual»).
- **Gráfico de rendimiento por origen:** contactabilidad y % no corresponde, en barras, junto a la tabla de C9.
- **Atributos en la revisión de fusiones:** mostrar los atributos de la fila y de la empresa existente para comparar.

### P2 — Future Considerations

- Atributos como columnas del CSV de uContact.
- Atributos calculados (por ejemplo, tramo de empleados a partir del número).
- Orígenes automáticos del enriquecimiento de la fase 2 (Google Places, búsqueda web, Claude), con el costo por teléfono verificado de cada uno.

## 6. Modelo de datos (resumen)

| Tabla | Columnas clave | Notas |
| --- | --- | --- |
| `atributo` | `clave` (única), `nombre`, `tipo`, `opciones` (jsonb), `sinonimos` (text[]), `filtrable`, `estratificable`, `activo` | Catálogo |
| `empresa_atributo` | `empresa_id`, `atributo_id`, `valor_texto`, `valor_numero`, `valor_fecha`, `valor_crudo`, `fuente_tipo`, `fuente_id`, `confianza`, `fecha` | Valor vigente; único por empresa y atributo |
| `empresa_campo_historia` | sin cambios | `campo = 'atributo.<clave>'` |
| `origen_telefono` | `codigo` (único), `nombre`, `prioridad`, `activo`, `sistema` | Catálogo; trae `sala`, `manual` y `sin_dato` |
| `telefono_vinculo_origen` | `vinculo_id`, `origen_id`, `fuente_tipo`, `fuente_id`, `fecha` | Evidencia; único por vínculo y origen |
| `carga` | `estado` agrega `descartada`; `mapeo` admite `atributos`, `telefonos[].origen` y `traducciones` | |
| `carga_plantilla` | `mapeo` incluye las traducciones de valores | |
| `muestra` | `criterios` admite `atributos` y `origenes`; nuevo `exportacion` (jsonb: orígenes y orden) | |

Las migraciones son compatibles hacia atrás. Los vínculos existentes reciben una evidencia con origen `sin_dato`.

## 7. Success Metrics

| Métrica | Meta | Cómo se mide | Cuándo |
| --- | --- | --- | --- |
| Vínculos creados por cargas con origen distinto de «Sin dato» | ≥ 95% | `telefono_vinculo_origen` de cargas posteriores al cambio | 1 mes |
| Cargas confirmadas o descartadas sin quedar en preview más de 7 días | ≥ 90% | `carga.estado` y fechas | 1 mes |
| Atributos creados y usados en al menos una muestra | ≥ 1 | Catálogo y criterios de muestras | 2 meses |
| Estudios que usan filtro u orden por origen en el CSV | ≥ 1 en el primer estudio real | `muestra.exportacion` | Primer estudio |
| Decisión de origen basada en la tarjeta de rendimiento | Al menos un origen priorizado o descartado con datos | Revisión con jefes de proyecto | 3 meses |

## 8. Open Questions

| Pregunta | Quién | ¿Bloquea? |
| --- | --- | --- |
| ¿Cuál es la lista inicial de orígenes? (por ejemplo: Guía telefónica, DGI, Web de la empresa, Estudio anterior, Directorio de cámara, Google Maps) | Dirección + data steward | No: se carga en Configuración |
| ¿Cuál es la prioridad por defecto entre esos orígenes? | Dirección + coordinación de campo | No |
| ¿Qué atributos se crean primero? | Data steward | No |
| ¿Contactabilidad se mide como «al menos una llamada atendida» según la disposición del CDR (`ANSWERED`) o según `userfield`? | Coordinación de campo | Sí, para C9 |

## 9. Timeline Considerations

Conviene entregarlo en tres PRs, en este orden:

1. **Carga clara (C3, C6 sin orígenes, C10):** sin cambios de modelo salvo el estado `descartada`. Destraba la prueba en curso. Estimación: 1–2 días.
2. **Origen del teléfono (C4, C5, C6 completo, C8, C9 y la parte de origen de C7).** Es lo de más valor para el negocio. Estimación: 3–4 días.
3. **Atributos (C1, C2, C5 para listas, la parte de atributos de C7).** Estimación: 3–4 días.

Las estimaciones son de desarrollo con tests y suponen el patrón ya existente de mapeo con plantillas y de traducción de valores del .sav.

**Costo:** no agrega infraestructura ni servicios. Son tablas y pantallas sobre la misma base de Cloud SQL y la misma API en Cloud Run: US$0 adicional por mes.

## 10. Definition of Done

- [ ] C1 a C11 implementados con sus criterios verificados y los tests pasando.
- [ ] Una base real con dos columnas de teléfono y una columna de origen se cargó con su traducción de valores, y el preview mostró teléfonos por origen y filas sin teléfono.
- [ ] Se creó un atributo de lista, se cargó en una base y se usó como estrato en una muestra que se reproduce con su semilla.
- [ ] Un CSV se exportó filtrado por origen y otro ordenado por prioridad.
- [ ] La tarjeta de rendimiento por origen muestra datos de un estudio con CDR y .sav ingeridos.
- [ ] Manual de usuario (guías 3 y 15) y `docs/decisiones.md` actualizados.
