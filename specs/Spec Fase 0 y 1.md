# Spec — Fase 0 y Fase 1

Oct 28, 2026 · @Equipos

**La fase 0 (1–2 semanas, costo de infraestructura casi nulo) valida con datos reales los dos cruces de los que depende todo: llamadas por número destino y respuestas por .sav.** La fase 1 construye el mínimo para correr un estudio a empresas de punta a punta: base maestra, muestra reproducible, CSV para uContact, análisis del CDR, ingesta del .sav y actualización de la base.

El spec parte del PRD de la otra pestaña, ya ajustado con los comentarios del 28/10: análisis del CDR por destino sin depender de la campaña, ingesta manual del .sav con mapeo (sin webhook), feedback de la sala como variables del cuestionario, reglas parametrizables y fusión por RUT u otros criterios. El patrón de ingesta se toma del [sistema de paneles](https://github.com/araujomelogno/paneles) (`sav.py`, ingesta diferida con Cloud Tasks).

## Fase 0 — Validar los cruces

**Objetivo:** antes de escribir el sistema, probar con un estudio a empresas ya terminado que las llamadas y las respuestas se pueden asociar a la empresa y al teléfono sin trabajo manual. Se trabaja con scripts en Python sobre copias de los datos; no se despliega nada.

**Insumos:** la lista de teléfonos de un estudio a empresas reciente, el CDR de su período de campo (todas las llamadas, de campañas y manuales), los .sav de cada parte, la hoja "excluidos" del Excel de referencia y 2 o 3 bases propias de estudios anteriores.

### Experimentos

| # | Pregunta | Cómo se prueba | Criterio de éxito (go) |
| --- | --- | --- | --- |
| A | ¿Se puede asociar cada llamada a un teléfono de la lista por su número destino? | Normalizar a E.164 el destino de todas las llamadas salientes del período y cruzarlo con los teléfonos de la lista; clasificar lo que no cruza (interno, prefijo, número fuera de lista) | ≥ 95% de las llamadas salientes externas del período cruzan con la lista o quedan explicadas por una regla |
| B | ¿El .sav trae lo necesario para asociar cada respuesta? | Leer cada .sav con `pyreadstat`, reusando `analizar()` de paneles; identificar la variable de identificador (`id_item`, RUT o teléfono) y mapearla | ≥ 95% de las filas se asocian a una empresa de la lista; las que no, con motivo |
| C | ¿Qué variables tiene que tener todo cuestionario a empresas? | Revisar los cuestionarios del estudio y proponer un bloque estándar | Bloque estándar acordado con coordinación de campo |
| D | ¿Cuánto se duplica y cuántos intermediarios hay en las bases propias? | Unir las bases por RUT, contar duplicados, RUTs inválidos, empresas sin RUT y teléfonos compartidos por 5 o más RUTs | Conteos documentados; umbral de intermediario confirmado o ajustado |

**Bloque estándar de variables (propuesta para el experimento C):** nombres fijos para que el mapeo del .sav se pueda reusar como plantilla.

| Variable | Tipo | Contenido |
| --- | --- | --- |
| `EC_ID_ITEM` | URL variable oculta | Identificador del ítem de muestra |
| `EC_RUT` | URL variable oculta | RUT de la empresa |
| `EC_TEL_USADO` | Pregunta o URL variable | Teléfono con el que se hizo la encuesta |
| `EC_CALIDAD_TEL` | Pregunta cerrada | 1 corresponde · 2 no es de la empresa · 3 estudio contable o jurídico · 4 empresa cerró · 5 inexistente |
| `EC_TEL_ALT` | Pregunta abierta | Número alternativo que dieron |
| `EC_RESP_NOMBRE`, `EC_RESP_CARGO`, `EC_RESP_AREA` | Preguntas abiertas | Quién contestó |
| `EC_RESULTADO` | Pregunta cerrada o estado de Alchemer | Completa, rechazo, no corresponde, agendada |

### Entregables

- [ ] Informe de validación con los resultados de A–D y la decisión go/no-go.
- [ ] Reglas de normalización de teléfonos uruguayos (fijos, celulares, prefijos 0 y 598, internos).
- [ ] Lista inicial de destinos internos a ignorar en el CDR.
- [ ] Bloque estándar de variables cargado como plantilla en Alchemer.
- [ ] Catálogo inicial de naturalezas jurídicas con la marca de exclusión (desde la hoja "excluidos").

**Si algo falla:** si A no llega al 95%, se agrega una pregunta `EC_TEL_USADO` obligatoria y el cruce de llamadas queda como informativo. Si B falla porque faltan las URL variables, el identificador pasa a ser RUT + teléfono y se exige el bloque estándar desde el primer estudio de la fase 1.

**Costo:** sin infraestructura nueva (los scripts corren en el servidor Ubuntu o en una laptop); solo horas de análisis.

## Fase 1 — Alcance

**Problema:** cada estudio a empresas arma su lista a mano, llama a números de intermediarios o inválidos, no sabe cuándo se contactó a cada empresa y no puede reconstruir cómo salió la muestra. Los resultados quedan en el .sav y las llamadas en el CDR, sin volver a la base.

**Objetivos de la fase 1:**

1. Un estudio real a empresas corre entero en el sistema: carga, sorteo, CSV, campo, CDR, .sav y actualización de la base.
2. Cero empresas excluidas, en no llamar o en enfriamiento dentro de las muestras.
3. Al menos 95% de las filas del .sav y de las llamadas a teléfonos de la muestra quedan asociadas sin trabajo manual.
4. Cualquier muestra se puede volver a sortear con su semilla, snapshot y versión de configuración, y da la misma lista.

**No-objetivos de la fase 1:**

- **Enriquecimiento con APIs o IA** (Places, Brave, Tavily, Claude): queda para la fase 2. La fase 1 se alimenta de bases propias, padrón y la sala.
- **Candidatos sin RUT:** en la fase 1 toda empresa entra con RUT válido; las filas sin RUT quedan rechazadas con motivo.
- **Duplicados difusos y resolución asistida:** la fusión por otros criterios existe como regla configurable, pero sin sugerencias por similitud.
- **Webhooks o API de Alchemer:** la única entrada de respuestas es el .sav.
- **Tablero de calidad por dimensión DMBOK:** se guardan los datos (linaje, auditoría), el tablero llega en la fase 2.

## Flujo de un estudio

**El circuito se cierra en la base:** lo que la sala aprende en cada estudio (números que no corresponden, intermediarios, contactos, último contacto efectivo) cambia qué empresas salen en la próxima muestra.

&#91;embedded content: flujo de un estudio · 6 pasos\]

Las dos entradas del campo son independientes: el CDR entra solo cada noche y cubre también las llamadas manuales; el .sav lo sube el coordinador cuando cierra una parte o una ola.

## User stories (fase 1)

Entre corchetes, el requerimiento que la cubre.

**Data steward**

- Como data steward, quiero subir un Excel o CSV de empresas, mapear sus columnas y ver un preview de altas, actualizaciones, conflictos y rechazos antes de confirmar, para no ensuciar la base. \[R1.3\]
- Como data steward, quiero elegir la regla de fusión de la carga (RUT por defecto, u otro criterio), para cargar fuentes que no traen RUT limpio. \[R1.3\]
- Como data steward, quiero ver la lista de teléfonos sospechosos de intermediario y confirmarlos o liberarlos, para sacarlos del discado. \[R1.2\]
- Como data steward, quiero ver la historia de cada campo de una empresa, para saber de dónde salió cada dato. \[R1.1, R1.10\]

**Jefe de proyecto**

- Como jefe de proyecto, quiero crear un estudio con sus partes y el survey de Alchemer de cada una, para seguir el avance por parte. \[R1.5\]
- Como jefe de proyecto, quiero sortear una muestra por estratos con cuotas y reemplazos, y ver cuántas empresas quedaron fuera por cada regla, para saber si el marco alcanza. \[R1.6\]
- Como jefe de proyecto, quiero liberar reemplazos de un estrato, para cubrir bajas sin volver a sortear. \[R1.6\]

**Coordinador de campo**

- Como coordinador, quiero descargar el CSV de la muestra listo para cargar en uContact, para lanzar la campaña sin editar planillas. \[R1.7\]
- Como coordinador, quiero subir el .sav de una parte, revisar el mapeo que propone el sistema y confirmarlo, para que los resultados y las marcas de la sala actualicen la base. \[R1.9\]
- Como coordinador, quiero reusar el mapeo de la ola anterior del mismo cuestionario, para no volver a mapear. \[R1.9\]
- Como coordinador, quiero ver por empresa y por teléfono cuántas veces se llamó, cuándo y quién, incluidas las llamadas manuales, para controlar el protocolo de intentos. \[R1.8, R1.11\]

**Administrador**

- Como administrador, quiero cambiar el umbral de intermediario, los meses de enfriamiento y las naturalezas excluidas desde la configuración, para ajustar las reglas sin un desarrollador. \[R1.4, R1.12\]
- Como administrador, quiero registrar un pedido de no llamar, para que se respete en todas las muestras desde ese momento. \[R1.4\]

## Requerimientos (fase 1)

Todos son P0 de la fase 1. Los parámetros entre comillas angulares se leen de la configuración (R1.12), nunca del código.

### R1.1 — Registro maestro por RUT

- [ ] El RUT se valida con el dígito verificador. Dado un RUT inválido, la fila se rechaza con motivo y no crea empresa.
- [ ] Hay una sola empresa por RUT (restricción única en la base).
- [ ] Cada campo de la empresa guarda su valor vigente y la historia: valor, fuente (carga, .sav, manual), fecha, actor y confianza.
- [ ] Regla de supervivencia: gana la fuente de mayor confianza; a igual confianza, la más reciente. Un dato confirmado por la sala nunca lo pisa una carga.
- [ ] Una fusión de dos empresas guarda el registro absorbido y se puede deshacer.

### R1.2 — Teléfonos como entidad y detección de intermediarios

- [ ] Todo teléfono se normaliza a E.164 con las reglas de la fase 0; si no se puede normalizar, se guarda crudo con estado inválido.
- [ ] Un teléfono existe una vez y se vincula a una o más empresas, sucursales o contactos. Cada vínculo teléfono–empresa tiene estado: sin verificar, verificado, no corresponde, intermediario, inexistente.
- [ ] **Dado** un teléfono vinculado a ≥ «umbral\_intermediario» RUTs (5 por defecto), **cuando** se termina una carga o una ingesta, **entonces** queda como sospechoso de intermediario y sale de toda exportación hasta que el steward lo confirme o lo libere.
- [ ] Un teléfono liberado no vuelve a marcarse salvo que sume RUTs nuevos.

### R1.3 — Carga de bases y reglas de fusión

- [ ] Acepta .xlsx, .csv y .sav. El mapeo de columnas se guarda como plantilla por tipo de fuente.
- [ ] La carga elige una regla de fusión: RUT (por defecto), teléfono, razón social normalizada o dominio web. Las coincidencias que no son por RUT van a una bandeja de revisión; no se fusionan solas.
- [ ] Antes de confirmar se muestra un preview con conteos: altas, actualizaciones, conflictos, rechazos y nuevos sospechosos de intermediario.
- [ ] Cada carga es un lote con fuente, fecha, responsable y licencia de uso; se puede deshacer entera mientras ninguna de sus empresas haya entrado a una muestra.
- [ ] Las cargas grandes corren en diferido (Cloud Tasks) con progreso visible, como en paneles.

### R1.4 — Exclusiones y no llamar

- [ ] Catálogo de naturalezas jurídicas editable, con marca "excluida de contacto"; la carga inicial sale de la hoja "excluidos".
- [ ] Lista de no llamar por empresa, teléfono o contacto, con motivo, fecha y quién la pidió.
- [ ] Las empresas excluidas se guardan y se actualizan, pero **nunca** entran a un marco muestral ni a un CSV. Hay un test automático que lo verifica.

### R1.5 — Estudios y partes

- [ ] Un estudio tiene nombre, cliente, fechas de campo y una o más partes.
- [ ] Cada parte tiene `survey_id` de Alchemer, link base, respondente objetivo (área o cargo) y su plantilla de mapeo del .sav.
- [ ] Cada ítem de muestra tiene estado por parte: pendiente, en curso, completa, rechazo, no contactable, fuera de marco.

### R1.6 — Sorteo de muestra y reemplazos

- [ ] La muestra se define con filtros (rubro, tamaño, departamento, naturaleza), estratos, tamaño por estrato y cantidad de reemplazos por estrato.
- [ ] Al sortear se congela un snapshot del marco, se aplica la versión vigente de las reglas de disponibilidad y se guardan semilla y versión de configuración.
- [ ] **Dado** una muestra ya sorteada, **cuando** se re-ejecuta con su semilla, snapshot y configuración, **entonces** devuelve exactamente los mismos ítems en el mismo orden.
- [ ] El resultado muestra cuántas empresas excluyó cada regla y avisa si algún estrato no alcanza el tamaño pedido.
- [ ] Las empresas sorteadas quedan bloqueadas para otras muestras mientras la muestra esté activa.
- [ ] Los reemplazos se liberan por estrato y en el orden sorteado; queda registrado quién los liberó y por qué.

### R1.7 — CSV para uContact

- [ ] Un renglón por teléfono discable de cada ítem liberado, con `id_item`, `tel_e164`, RUT, razón social, contacto sugerido y el link de Alchemer con URL variables (`EC_ID_ITEM`, `EC_RUT`, `EC_TEL_USADO`).
- [ ] Nunca incluye teléfonos intermediarios, inexistentes, en no llamar o que no corresponden.
- [ ] El formato de columnas se configura una vez para que coincida con la importación de uContact.

### R1.8 — Análisis del CDR por número destino

- [ ] Un job nocturno lee las llamadas nuevas desde la base del CDR (incremental por fecha/ID) y toma **todas**, de campañas y del marcador manual.
- [ ] Normaliza el destino, descarta los «destinos\_internos» y cruza contra los teléfonos de la base. Lo que no cruza se cuenta pero no se guarda como intento.
- [ ] Cada intento guarda teléfono, empresas vinculadas, encuestador (`peeraccount`), fecha y hora, franja, duración, disposición (`userfield`) y campaña si existe.
- [ ] **Dado** un destino que es un teléfono de una muestra activa, **cuando** la llamada cae entre las fechas de campo, **entonces** el intento queda asociado al ítem; si el teléfono está en dos muestras activas, va a conciliación.
- [ ] Re-procesar un día no duplica intentos (idempotente por ID de llamada).

### R1.9 — Ingesta del .sav con mapeo

- [ ] El coordinador sube el .sav de una parte. El backend lo lee y devuelve una propuesta editable: variable identificador sugerida, variables del bloque estándar reconocidas por nombre, y para cada variable con códigos, el mapeo de valores sugerido.
- [ ] Nada se aplica hasta que el coordinador confirma. El mapeo declarado gana sobre las etiquetas del archivo.
- [ ] Se muestran conteos antes de confirmar: filas asociadas, sin asociar, valores sin mapear ("el 99 quedó sin mapear: 412 filas").
- [ ] El valor crudo se guarda aunque quede sin mapear, para corregir el mapeo después sin volver a subir el archivo.
- [ ] El mapeo confirmado se guarda como plantilla de la parte y se precarga en el próximo .sav.
- [ ] Subir dos veces el mismo .sav no duplica resultados (idempotente por `response_id`).

### R1.10 — Actualización de la base desde resultados

- [ ] `EC_CALIDAD_TEL` actualiza el estado del vínculo teléfono–empresa; "estudio contable o jurídico" lo marca como intermediario confirmado.
- [ ] `EC_TEL_ALT` crea un teléfono nuevo vinculado a la empresa, con estado sin verificar y fuente "sala".
- [ ] `EC_RESP_*` crea o actualiza un contacto de la empresa con su área y cargo.
- [ ] Un contacto efectivo (encuesta completa, parcial o rechazo explícito de la empresa) actualiza la fecha de último contacto efectivo, de la que se cuenta el enfriamiento.
- [ ] Cada cambio queda con linaje: estudio, parte, encuestador, fecha.

### R1.11 — Indicadores de actividad

- [ ] Tablero filtrable por estudio, muestra, encuestador y período: empresas llamadas, teléfonos marcados, intentos por franja, contactos efectivos y completas.
- [ ] La ficha de la empresa muestra una línea de tiempo con cargas, intentos, resultados y cambios de datos.

### R1.12 — Configuración parametrizable

- [ ] Parámetros mínimos: umbral de intermediario, meses de enfriamiento, reglas de disponibilidad activas, catálogo de naturalezas excluidas, reglas de fusión disponibles, destinos internos y franjas horarias.
- [ ] Cada cambio genera una versión nueva con autor y fecha. Las muestras guardan la versión con la que se sortearon.

### R1.13 — Roles y auditoría

- [ ] Roles: administrador, data steward, jefe de proyecto, coordinador de campo, lectura. Auth con Firebase, permisos en el backend.
- [ ] Log de auditoría append-only para cargas, fusiones, exclusiones, sorteos, exportaciones, ingestas y cambios de configuración.
- [ ] Exportar contactos personales requiere un permiso específico y queda auditado (Ley 18.331).

## Modelo de datos (Cloud SQL Postgres)

Un solo esquema `empresas`. Las tablas de historia y auditoría son append-only. Migraciones numeradas como en paneles (`db/empresas/0001_init.sql`…).

| Tabla | Columnas clave | Notas |
| --- | --- | --- |
| `empresa` | `rut` (único), razón social, fantasía, `naturaleza_id`, CIIU, tamaño, estado, `ultimo_contacto_efectivo` | Valor vigente de cada campo |
| `empresa_campo_historia` | `empresa_id`, campo, valor, `fuente_tipo`, `fuente_id`, confianza, actor, fecha | Linaje por campo |
| `sucursal` | `empresa_id`, dirección, departamento, localidad |  |
| `contacto` | `empresa_id`, `sucursal_id`?, nombre, cargo, área, email | Dato personal (Ley 18.331) |
| `telefono` | `e164` (único), crudo, tipo (fijo / celular), estado global |  |
| `telefono_vinculo` | `telefono_id`, `empresa_id`, `contacto_id`?, estado, fuente, fecha | M:N; aquí vive "intermediario" |
| `naturaleza_juridica` | código, nombre, `excluida` | Catálogo |
| `no_llamar` | alcance (empresa / teléfono / contacto), `objeto_id`, motivo, solicitante, fecha |  |
| `carga` | fuente, archivo, responsable, licencia, regla de fusión, estado, conteos | Lote de ingesta |
| `estudio` / `parte` | nombre, cliente, fechas / `survey_id`, link, respondente objetivo, `plantilla_mapeo` (jsonb) |  |
| `muestra` | `estudio_id`, criterios (jsonb), semilla, `config_version`, `snapshot_id`, estado |  |
| `muestra_item` | `muestra_id`, `empresa_id`, estrato, rol (titular / reemplazo), orden, liberado |  |
| `item_parte_estado` | `item_id`, `parte_id`, estado, teléfono usado, respondente, fecha |  |
| `intento` | `cdr_id` (único), `telefono_id`, `item_id`?, encuestador, inicio, franja, duración, disposición, campaña | Desde el CDR |
| `sav_ingesta` / `sav_fila` | parte, archivo, mapeo confirmado, conteos / `response_id`, `item_id`?, valores crudos (jsonb) | Crudo para remapear |
| `config_version` | versión, parámetros (jsonb), autor, fecha |  |
| `auditoria` | actor, acción, objeto, detalle (jsonb), fecha | Append-only; export diario a BigQuery |

Disponibilidad: la vista `v_empresa_disponible` evalúa las reglas de la configuración vigente (exclusión por naturaleza, no llamar, enfriamiento desde `ultimo_contacto_efectivo`, bloqueo por muestra activa) y devuelve, para cada empresa no disponible, la regla que la bloquea y hasta cuándo.

## Pantallas y endpoints

Web app en Firebase Hosting (mismo estilo que paneles: JS sin framework), API en Cloud Run (Python), ingestas en diferido con Cloud Tasks.

| Pantalla | Rol principal | Endpoints | Req. |
| --- | --- | --- | --- |
| Empresas: buscador y ficha (datos, historia, teléfonos, contactos, línea de tiempo) | Todos | `GET /empresas`, `GET /empresas/{rut}` | R1.1, R1.11 |
| Cargas: subir, mapear, preview, confirmar, deshacer | Data steward | `POST /cargas/analizar`, `POST /cargas`, `GET /cargas/{id}`, `DELETE /cargas/{id}` | R1.3 |
| Intermediarios: bandeja de sospechosos | Data steward | `GET /telefonos/sospechosos`, `POST /telefonos/{id}/resolver` | R1.2 |
| Estudios y partes | Jefe de proyecto | `POST /estudios`, `POST /estudios/{id}/partes` | R1.5 |
| Muestras: definir, sortear, ver exclusiones, liberar reemplazos | Jefe de proyecto | `POST /muestras`, `POST /muestras/{id}/sortear`, `POST /muestras/{id}/liberar` | R1.6 |
| Exportar CSV | Coordinador | `GET /muestras/{id}/csv` | R1.7 |
| Ingesta .sav: subir, mapeo propuesto, conteos, confirmar | Coordinador | `POST /partes/{id}/sav/analizar`, `POST /partes/{id}/sav`, `GET /sav/{id}` | R1.9, R1.10 |
| Conciliación (filas del .sav y llamadas sin asociar) | Coordinador | `GET /conciliacion`, `POST /conciliacion/{id}` | R1.8, R1.9 |
| Actividad (tablero) | Coordinador, jefe | `GET /actividad` | R1.11 |
| Configuración, naturalezas, no llamar, usuarios | Administrador | `GET/PUT /config`, `/naturalezas`, `/no-llamar`, `/usuarios` | R1.4, R1.12, R1.13 |

El job del CDR no es una pantalla: corre a las 4:00 en el servidor Ubuntu (como el dashboard de productividad) y llama a `POST /intentos/lote`.

## Métricas, terminado, riesgos y plan

**Métricas de la fase 1** (se miden en el estudio piloto):

| Métrica | Meta | Cómo se mide |
| --- | --- | --- |
| Filas del .sav asociadas sin conciliación manual | ≥ 95% | `sav_fila` con `item_id` / total |
| Llamadas a teléfonos de la muestra asociadas a un ítem | ≥ 95% | `intento` con `item_id` / intentos a teléfonos de la muestra |
| Empresas excluidas, en no llamar o en enfriamiento dentro de muestras | 0 | Test automático + consulta de control por muestra |
| Muestras reproducibles | 100% | Re-sorteo con semilla en el test de integración |
| Tiempo del coordinador para ingerir un .sav con plantilla | ≤ 10 minutos | Medido en el piloto |

**Definición de terminado:**

- [ ] Los criterios de R1.1 a R1.13 pasan con tests automáticos (pytest + Postgres de prueba, como en paneles).
- [ ] Un estudio real a empresas corrió entero en el sistema y su informe de cierre salió de los indicadores.
- [ ] Manual de usuario con capturas para steward, jefe de proyecto y coordinador.
- [ ] Registro de decisiones (`docs/decisiones.md`) y guía de despliegue.

**Riesgos:**

| Riesgo | Mitigación |
| --- | --- |
| Los cuestionarios no incluyen el bloque estándar y el .sav no trae `EC_ID_ITEM` | Plantilla de Alchemer obligatoria desde el piloto; fallback por RUT + teléfono |
| Un mismo teléfono está en dos muestras activas y la llamada no se puede atribuir | El bloqueo por muestra activa lo evita; si pasa, va a conciliación |
| Las bases propias traen muchos RUTs inválidos o sin RUT | Se mide en el experimento D; la fase 1 los rechaza con motivo y la fase 2 los recupera |
| El acceso al CDR desde fuera de la red | El job corre en el servidor Ubuntu y empuja a la API |

**Plan de iteraciones** (estimación de 7–8 semanas después de la fase 0):

1. **Iteración 1 — Base (2 semanas):** esquema, auth y roles, configuración versionada, cargas con fusión, teléfonos e intermediarios, exclusiones. R1.1–R1.4, R1.12, R1.13.
2. **Iteración 2 — Muestra (2 semanas):** estudios y partes, sorteo reproducible, reemplazos, CSV para uContact. R1.5–R1.7.
3. **Iteración 3 — Campo (2 semanas):** job del CDR por destino, ingesta del .sav con mapeo y plantillas, actualización de la base. R1.8–R1.10.
4. **Iteración 4 — Piloto (1–2 semanas):** tablero de actividad, conciliación y un estudio real de punta a punta. R1.11.

**Costo de la fase 1:** la infraestructura empieza a costar al crear Cloud SQL, aprox. US$65–100 por mes (ver Arquitectura en el PRD). No hay gasto en APIs de enriquecimiento hasta la fase 2.
