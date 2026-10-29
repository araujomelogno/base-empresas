# PRD — Base de Empresas Equipos

Oct 23, 2026 · @Equipos

## Resumen y problema

**Equipos va a construir una base maestra de empresas, con el RUT como clave, de donde salgan muestras aleatorias y auditables para las encuestas a empresas.** Además debe guardar cada contacto, cada llamada y cada resultado. Es un sistema independiente sobre Firebase + Google Cloud. Alchemer sigue siendo el sistema de encuestas y uContact el discador.

Hoy cada estudio a empresas arma su propia lista. Las bases están dispersas entre estudios anteriores, padrones y búsquedas ad hoc. Eso genera cinco problemas:

- **Duplicados y datos viejos:** la misma empresa aparece con razones sociales y teléfonos distintos según la fuente, y nadie sabe cuál es el vigente.
- **Teléfonos que no son de la empresa:** muchas empresas declaran el número de su estudio contable o jurídico, así que se llama a un intermediario compartido por decenas de RUTs.
- **Sobrecontacto o subutilización:** no hay registro único de cuándo se contactó a cada empresa, así que se vuelve a llamar a empresas recién encuestadas y se dejan sin usar otras disponibles.
- **Muestras que no se pueden reconstruir:** no queda registro de con qué criterios ni con qué sorteo salió cada empresa.
- **Resultados desconectados:** la respuesta de Alchemer, la llamada del CDR de uContact y el teléfono marcado viven en tres sistemas, y el cruce se hace a mano.

No resolverlo cuesta horas-agente en números inválidos, peor tasa de respuesta por sobrecontacto, riesgo regulatorio con datos personales (Ley 18.331) y re-trabajo en cada estudio para rearmar la base.

## Objetivos y no-objetivos

**Objetivos (resultados, no entregables):**

1. **Una sola fuente de verdad por RUT:** al menos 95% de las empresas activas con un registro maestro único, sin duplicados, con linaje de cada dato (fuente, fecha, confianza).
2. **Menos llamadas perdidas:** bajar al menos 30% la proporción de llamadas a números inválidos o que no corresponden a la empresa, comparada con los estudios a empresas de 2026.
3. **Muestras auditables:** el 100% de las muestras reproducibles a partir de criterios + semilla + snapshot, y cada empresa sorteada con motivo de inclusión trazable.
4. **Resultado vinculado sin trabajo manual:** al menos 95% de las respuestas de Alchemer asociadas al ingerir el .sav, sin cruces manuales, a ítem de muestra, empresa, teléfono y encuestador.
5. **Cumplimiento de reglas de contacto:** cero llamadas a empresas excluidas por naturaleza jurídica, en lista de no llamar o en período de enfriamiento.

**No-objetivos (v1):**

- **Reemplazar Alchemer o uContact:** siguen siendo el instrumento y el discador; el sistema interopera por CSV, URL variables, ingesta de .sav y lectura del CDR.
- **Integrarse con la plataforma de campo de ANDE (Paneles + COLOQUIO):** se decidió que sea un sistema independiente; la integración futura sería por API.
- **Analizar el contenido de las respuestas:** se guarda el estado y el resultado de cada parte, no se procesan las preguntas (eso queda en Alchemer o en el sistema de paneles).
- **CRM comercial:** no gestiona clientes de Equipos ni oportunidades; las empresas son unidades de investigación.
- **Crawling masivo de toda la web uruguaya:** el enriquecimiento con IA es dirigido (por empresa o por segmento), no un rastreo general.

## Usuarios y user stories

Hay cinco roles. Las historias están ordenadas por prioridad dentro de cada rol.

**Jefe de proyecto (diseña el estudio y la muestra)**

- Como jefe de proyecto, quiero definir un estudio con varias partes (cada una con su encuesta de Alchemer y su respondente objetivo), para seguir el avance por empresa y por parte.
- Como jefe de proyecto, quiero sortear una muestra aleatoria con criterios (rubro, tamaño, departamento, naturaleza jurídica, estratos y cuotas), para obtener la lista que va a campo.
- Como jefe de proyecto, quiero que el sorteo excluya automáticamente a las empresas que bloquee alguna regla de disponibilidad parametrizable (enfriamiento, otra muestra activa, naturaleza jurídica, no llamar u otras que se configuren), para no tener que depurarla a mano.
- Como jefe de proyecto, quiero una reserva de reemplazos por estrato, para cubrir bajas sin volver a sortear toda la muestra.
- Como jefe de proyecto, quiero ver la tasa de respuesta, el rechazo y la contactabilidad de la muestra por estrato, para decidir si libero reemplazos.

**Coordinador de campo (opera uContact)**

- Como coordinador, quiero exportar la muestra en el formato CSV que carga uContact, con el link de Alchemer y sus URL variables ya armados, para lanzar la campaña sin editar planillas.
- Como coordinador, quiero ver qué empresas, qué números, cuándo y qué encuestador se llamaron, para controlar el protocolo de intentos.
- Como coordinador, quiero que una empresa con todos sus teléfonos agotados pase a "requiere enriquecimiento", para no perderla de la muestra.

**Encuestador**

- Como encuestador, quiero registrar en una pregunta del cuestionario de Alchemer "el número no es de esta empresa", "es un estudio contable/jurídico", "la empresa cerró" o "me pasaron otro número: \_\_\_", para que la base se corrija cuando el coordinador ingiera el .sav de la encuesta.
- Como encuestador, quiero registrar en el cuestionario de Alchemer el contacto que atendió (nombre, cargo, área), para que la siguiente parte de la encuesta vaya a la persona correcta (el sistema lo toma al ingerir el .sav).

**Analista de datos / data steward**

- Como data steward, quiero cargar bases de estudios anteriores, padrones y directorios, y que el sistema las una por RUT o por otros criterios de fusión configurables (teléfono, razón social normalizada, dominio web) y marque los conflictos, para mantener un registro maestro único.
- Como data steward, quiero una bandeja de candidatos sin RUT (por ejemplo, de Google Maps) para vincularlos a una empresa o descartarlos.
- Como data steward, quiero ver los teléfonos compartidos por muchos RUTs y confirmar si son intermediarios, para sacarlos del discado.
- Como data steward, quiero lanzar un enriquecimiento dirigido (por segmento o por empresa) con una estimación de costo antes de ejecutarlo, para controlar el gasto en APIs.
- Como data steward, quiero ver el historial de cada campo (valor, fuente, fecha, quién lo cambió), para auditar la base.

**Dirección / responsable de protección de datos**

- Como responsable, quiero registrar una solicitud de baja o de no llamar y que se respete en todas las muestras, para cumplir la Ley 18.331.
- Como dirección, quiero indicadores de calidad de la base (completitud, frescura, teléfonos válidos) y de uso (empresas contactadas por mes), para decidir dónde invertir en enriquecimiento.

## Modelo de dominio

**La empresa (RUT) es la unidad de muestreo, y el teléfono es una entidad propia vinculada muchos a muchos.** Esa decisión permite detectar los números de estudios contables compartidos y guardar la calidad de cada número por separado.

&#91;embedded content: modelo de dominio · 11 entidades\]

El ítem de muestra es la pieza central: lleva el RUT y el teléfono que se marcó, recibe los intentos del CDR y los resultados de Alchemer por parte, y cuando cierra actualiza la historia de contacto de la empresa. Las sucursales son datos de la empresa y no se sortean por separado. Los contactos pueden asociarse a una sucursal y a un área.

## Requerimientos

El P0 es el mínimo para correr un estudio a empresas completo de punta a punta: base, muestra, campo y resultado. El enriquecimiento con IA es P1 porque la sala y las bases existentes alcanzan para empezar.

### P0 — Imprescindibles

**P0.1 Registro maestro de empresas por RUT**

- [ ] El RUT se valida con el dígito verificador; un RUT inválido no crea empresa y va a la bandeja de revisión.
- [ ] Hay una sola empresa por RUT; cargar un RUT existente actualiza campos según las reglas de supervivencia (fuente más confiable, luego más reciente) y nunca duplica.
- [ ] Cada empresa tiene razón social, nombre de fantasía, naturaleza jurídica, rubro (CIIU), tamaño, estado (activa / cerrada / desconocida) y sucursales (dirección, departamento, localidad).
- [ ] Cada empresa tiene contactos con nombre, cargo, área y canales; un contacto puede estar asociado a una sucursal y a un área.

**P0.2 Teléfono como entidad propia (muchos a muchos)**

- [ ] Los teléfonos se normalizan a E.164 (+598…) y se guardan una sola vez, vinculados a una o más empresas, sucursales o contactos.
- [ ] Cada vínculo teléfono–empresa tiene estado: sin verificar, verificado, no corresponde, intermediario, inexistente.
- [ ] Dado un teléfono vinculado a 5 o más RUTs (5 por defecto, parametrizable por configuración), el sistema lo marca como **sospechoso de intermediario** y lo excluye de las exportaciones a uContact hasta que un data steward lo confirme o lo libere.
- [ ] La señal se refuerza si las empresas que comparten el número tienen rubros distintos, o si el número aparece en el sitio web de un estudio contable o jurídico.

**P0.3 Ingesta de bases (estudios previos, padrones, directorios)**

- [ ] Se carga Excel o CSV con mapeo de columnas guardable por tipo de fuente.
- [ ] Cada carga es un lote con fuente, fecha, responsable y licencia de uso; cada valor queda asociado a su lote (linaje).
- [ ] Hay un preview antes de confirmar: altas, actualizaciones, conflictos y rechazos. Las reglas de fusión son configurables: por RUT (por defecto) o por otros criterios (teléfono, razón social normalizada, dominio web, con umbral de similitud); los cruces que no son por RUT van a revisión.

**P0.4 Naturaleza jurídica y exclusiones**

- [ ] Hay un catálogo de naturalezas jurídicas con un flag "excluida de contacto" (catálogo parametrizable; la carga inicial sale de la hoja "excluidos" del Excel de referencia).
- [ ] Las empresas excluidas se guardan y se enriquecen, pero nunca entran al marco muestral ni a una exportación.
- [ ] Existe una lista de "no llamar" por empresa, teléfono o contacto, con motivo y fecha, que se aplica a todo el sistema.

**P0.5 Políticas de disponibilidad**

- [ ] La disponibilidad se calcula al sortear, no se mantiene a mano: una empresa está **disponible** si no viola ninguna regla activa y **usada** si alguna regla la bloquea.
- [ ] Reglas mínimas: enfriamiento global (no sortear si tuvo un contacto efectivo en los últimos N meses, contados desde el último contacto efectivo, con N configurable), bloqueo por muestra activa y exclusión por naturaleza o no llamar. Todas se parametrizan desde la configuración (activar o desactivar, plazos, alcance) sin tocar código, y se pueden agregar reglas nuevas.
- [ ] La ficha de la empresa muestra su estado y qué regla la bloquea y hasta cuándo.

**P0.6 Estudios, partes y muestras**

- [ ] Un estudio tiene una o más partes; cada parte tiene su survey ID de Alchemer y su respondente objetivo (área o cargo).
- [ ] Una muestra guarda criterios, estratos y cuotas, la semilla aleatoria, la fecha y un snapshot congelado del marco; con eso, volver a ejecutar el sorteo da exactamente la misma lista.
- [ ] Cada ítem de muestra tiene rol (titular o reemplazo), estrato, orden de liberación y estado por parte (pendiente, en curso, completa, rechazo, no contactable, fuera de marco).
- [ ] Los reemplazos se liberan por estrato, de forma manual o por regla, y queda registrado quién los liberó y por qué.

**P0.7 Exportación a uContact y vínculo con Alchemer**

- [ ] Se genera un CSV en el formato de lista de uContact, con un renglón por teléfono discable e `id_item` como identificador.
- [ ] El link de Alchemer de cada parte se genera con URL variables: `id_item`, `rut`, `tel_id` y `parte`; el encuestador lo agrega del lado de uContact.
- [ ] Solo se exportan teléfonos en estado sin verificar o verificado, nunca intermediarios, inexistentes o en no llamar.

**P0.8 Ingesta de CDR y de resultados**

- [ ] Cada noche se lee el CDR de uContact (base MySQL) y se registra como intento cada llamada cuyo número destino coincide con un teléfono de la base, venga de una campaña o del marcador manual: teléfono, empresa, ítem de muestra (si el número está en una muestra activa), encuestador (peeraccount), fecha y hora, disposición de llamada y de encuesta (userfield).
- [ ] No se filtra por campaña: muchas llamadas salen del marcador manual y no quedan asociadas a ninguna. El análisis se hace por número destino contra los teléfonos de la base, y solo se descartan los destinos internos (extensiones, conferencias, pruebas).
- [ ] El coordinador de campo sube el .sav que exporta Alchemer para cada parte. El sistema lo analiza y propone a qué campo va cada variable (ítem, RUT, teléfono usado, respondente, calidad del número, contacto, resultado); el coordinador confirma el mapeo y recién ahí se ingiere. Es el mismo patrón que la ingesta de panelistas del sistema de paneles. Las filas que no se pueden asociar van a una bandeja de conciliación.
- [ ] Una encuesta completa registra a qué teléfono se hizo, quién la hizo y quién la contestó, en la muestra y en la historia general de la empresa. El mapeo admite otras variables de interés de la base de respuestas, como quién contestó y cuál de los teléfonos disponibles se usó.

**P0.9 Feedback de calidad desde la sala**

- [ ] Con una pregunta del cuestionario de Alchemer, el encuestador marca: número no corresponde, intermediario, empresa cerró o número alternativo. La variable llega en el .sav y se mapea en la ingesta.
- [ ] Cada marca actualiza el estado del vínculo teléfono–empresa, con el linaje "sala, encuestador X, fecha".

**P0.10 Indicadores de actividad**

- [ ] Hay un tablero con empresas contactadas, números marcados, intentos por franja, encuestador y fecha, filtrable por estudio, muestra y período.
- [ ] Desde la ficha de la empresa se ve la línea de tiempo de todos sus contactos y resultados.

**P0.11 Configuración parametrizable**

- [ ] Una pantalla de configuración con historial de cambios reúne todos los parámetros: umbral de intermediario (5 por defecto), meses de enfriamiento, catálogo de naturalezas excluidas, reglas de fusión, reglas de disponibilidad, destinos internos a ignorar en el CDR y franjas horarias.
- [ ] Cambiar un parámetro no requiere despliegue. Cada muestra guarda la versión de la configuración con la que se sorteó, para que siga siendo reproducible.

### P1 — Muy deseables

- **Cascada de enriquecimiento dirigido** (ver Integraciones), con presupuesto por ejecución, estimación de costo previa y tope duro.
- **Búsqueda de empresas nuevas** por rubro y zona en Google Places, con resultados como candidatos sin RUT.
- **Resolución de entidades asistida:** sugerir el RUT de un candidato por similitud de nombre, dirección y teléfono (`pg_trgm`), con confirmación humana.
- **Detección de duplicados difusos** entre empresas con RUT distinto pero el mismo teléfono, sitio web o dirección (por ejemplo, grupos económicos).
- **Exclusividad por cliente o tema** como regla de disponibilidad adicional.
- **Tablero de calidad de datos** por dimensión DMBOK.

### P2 — A futuro (diseñar para no impedirlo)

- Monitoreo continuo con IA (cambios en sitios web, cierres, cambios de teléfono).
- Muestreo PPS (probabilidad proporcional al tamaño) y ponderadores calculados.

## Integraciones

Hay dos llaves de cruce. **Para las llamadas es el número destino:** el CDR se consulta directo en la base y cada destino se compara con los teléfonos de la base, haya o no campaña, porque muchas llamadas se hacen con marcador manual. **Para las respuestas es el .sav:** el coordinador sube la exportación de Alchemer y mapea sus variables, entre ellas `id_item`, que viaja como URL variable.

**uContact (salida y CDR)**

- **Hacia uContact (salida del sistema):** CSV para cargar la lista de la campaña, con `id_item`, `tel_e164`, `rut`, razón social, contacto sugerido y el link de Alchemer de la parte que corresponde. Lo genera este sistema; uContact no devuelve nada por este camino.
- **CDR (entrada):** job nocturno que consulta directamente la base MySQL del CDR (`uc`). Toma **todas** las llamadas, de campañas y del marcador manual, normaliza el número destino a E.164 y lo cruza con los teléfonos de la base. Usa las convenciones del dashboard de productividad: encuestador = `peeraccount`, `userfield` = disposición de llamada|disposición de encuesta, franjas de mañana (10:00–16:30), tarde y fin de semana. La campaña se guarda como dato cuando existe, pero no es la llave.
- El intento se asocia a un ítem de muestra cuando el destino es un teléfono de una muestra activa y la llamada cae dentro de la ventana de campo de esa muestra. Si el número está en más de una muestra activa (no debería pasar, por el bloqueo), va a conciliación.
- Como el CDR está en una base de la red de Equipos, la ingesta corre donde hoy corre el script del dashboard (servidor Ubuntu) y empuja a Cloud SQL, o usa un conector con IP autorizada.

**Alchemer (resultados)**

- Cada parte del estudio guarda su `survey_id`. Las URL variables (`id_item`, `rut`, `tel_id`, `parte`) quedan como campos ocultos en la exportación.
- **Ingesta manual de .sav, sin webhook ni API:** el coordinador de campo exporta el .sav de Alchemer y lo sube. El backend lo lee (`pyreadstat`) y devuelve una **propuesta editable** de mapeo: qué variable es el identificador, cuál es el teléfono usado, el respondente, la calidad del número, el contacto que atendió y el estado de la encuesta. Para variables con códigos, el coordinador declara qué código va a qué valor del sistema.
- Se toma como referencia la ingesta de panelistas del [sistema de paneles](https://github.com/araujomelogno/paneles): parseo en el backend, la sugerencia propone pero no aplica, el mapeo declarado gana sobre las etiquetas del archivo, el valor crudo se guarda aunque quede sin mapear, se avisa con conteos ("el 99 quedó sin mapear: 412 filas") y la ingesta corre en diferido con Cloud Tasks.
- Los mapeos se guardan como plantilla por estudio y parte, así la segunda ola o el segundo .sav del mismo cuestionario se ingiere sin volver a mapear.
- Se guarda: estado (completa, parcial, descalificada), fechas, `id_item`, teléfono usado, encuestador, respondente y las variables de calidad del número. El resto de las respuestas no se copia; se referencia por `response_id`.

**Cascada de enriquecimiento (P1)**

Se aplica de la fuente más barata a la más cara, y se corta apenas el dato queda verificado:

1. **Fuentes propias:** historial de la sala, bases de estudios previos, padrones cargados. Costo: US$0.
2. **Google Places:** búsqueda por razón social + localidad para obtener teléfono, sitio web y `place_id`.
3. **Búsqueda web:** Brave como opción por defecto (la más barata); Tavily cuando conviene búsqueda + extracción en una llamada; SerpAPI solo para resultados de Google que las otras no traen.
4. **Extracción con Claude (modelo chico):** lee el sitio o los resultados y devuelve JSON con teléfonos, emails genéricos, dirección y si el sitio pertenece a un estudio contable o jurídico.

Cada resultado entra con confianza "no verificada" hasta que la sala lo confirme.

| Servicio | Precio de referencia | Costo por 1.000 empresas | Free tier |
| --- | --- | --- | --- |
| Google Places Text Search Enterprise (incluye teléfono y web) | US$35 / 1.000 | US$35 | 1.000 / mes |
| Google Places Place Details Enterprise | US$20 / 1.000 | US$20 (si ya se tiene `place_id`) | 1.000 / mes |
| Brave Search API | US$5 / 1.000 | US$5 | US$5 de crédito / mes |
| Tavily (búsqueda básica, pay-as-you-go) | US$0,008 / crédito | US$8 (+ US$1,6 si extrae 1 URL) | 1.000 créditos / mes |
| SerpAPI (plan Developer) | US$75 / mes por 5.000 | US$15 | 250 / mes |
| Claude, modelo chico, extracción (\~6k tokens in / 400 out) | aprox. US$1 / US$5 por millón de tokens | aprox. US$8 | — |

**Escenarios:** enriquecer 50.000 empresas por Places + web + LLM sin cascada cuesta aprox. **US$2.400 por única vez**. Con cascada, enriqueciendo solo lo que entra a muestra (por ejemplo, 3.000 empresas al mes, con 40% que llega a pasos pagos), cuesta aprox. **US$50–60 por mes**. Precios verificados en octubre de 2026 en las fuentes de abajo; el de Claude es aproximado y hay que confirmarlo.

## Gobierno de datos, calidad y cumplimiento

La base se trata como un dato maestro (MDM en DMBOK): tiene dueño, reglas de calidad medibles, linaje por campo y procesos periódicos. Sin esto, en un año vuelve a ser una planilla más.

**Roles (DMBOK: Data Governance)**

| Rol | Quién | Responsabilidad |
| --- | --- | --- |
| Data owner | Dirección de Equipos | Aprueba políticas: enfriamiento, exclusiones, fuentes autorizadas |
| Data steward | Analista de datos designado | Resuelve conflictos, intermediarios, candidatos sin RUT y auditorías |
| Productores | Encuestadores, coordinadores, cargas, enriquecimiento | Generan datos con linaje |
| Consumidores | Jefes de proyecto | Usan muestras e indicadores |

**Dimensiones de calidad y reglas medibles**

| Dimensión | Regla | Meta |
| --- | --- | --- |
| Validez | RUT con dígito verificador correcto; teléfono en E.164 válido para Uruguay | 100% |
| Unicidad | Una empresa por RUT; un teléfono por número | 100% |
| Completitud | Empresa disponible con al menos 1 teléfono discable, rubro y departamento | ≥ 90% |
| Exactitud | Teléfonos verificados por la sala sobre el total de teléfonos discables | Sube cada trimestre |
| Actualidad | Teléfono verificado en los últimos 24 meses | ≥ 70% de los discables |
| Consistencia | Naturaleza jurídica coherente con el tipo de RUT y la razón social (SA, SRL, SAS…) | Alertas revisadas |

**Linaje y auditoría**

- Cada valor de cada campo guarda fuente (lote, API, sala, manual), fecha, actor y confianza. La ficha muestra el valor vigente y su historia.
- Hay un log de auditoría inmutable (append-only) para altas, cambios, fusiones, exclusiones, sorteos y exportaciones, con un export a BigQuery para consultas largas.
- Las fusiones de empresas son reversibles: se guarda el registro absorbido.

**Procesos periódicos**

1. **Diario:** ingesta de CDR y resultados, recalcular estados de teléfonos y detectar nuevos sospechosos de intermediario.
2. **Semanal:** el data steward vacía las bandejas (conflictos, candidatos sin RUT, conciliación de Alchemer, intermediarios).
3. **Mensual:** reporte de calidad por dimensión y de costo de enriquecimiento.
4. **Trimestral:** auditoría por muestreo (por ejemplo, verificar 200 empresas al azar contra la fuente) y revisión de las políticas de enfriamiento y exclusión.
5. **Anual:** depuración de contactos personales sin uso y revisión del registro de la base ante la URCDP.

**Ley 18.331 (protección de datos personales)**

Los datos de la empresa (RUT, razón social, teléfono institucional) son de bajo riesgo. Los **contactos** (nombre, cargo, celular, email personal) son datos personales. Requisitos:

- [ ] Inscribir la base ante la URCDP (Unidad Reguladora y de Control de Datos Personales).
- [ ] Documentar la fuente y la finalidad de cada dato personal (el linaje lo cubre).
- [ ] Atender derechos de acceso, rectificación y supresión, con la lista de no llamar como mecanismo operativo.
- [ ] Control de acceso por rol: los encuestadores ven solo los datos de su campaña; la exportación masiva de contactos requiere un rol específico y queda auditada.
- [ ] Conservar los datos personales sin uso por un plazo máximo, a definir con asesoría legal.

Esto no es asesoramiento legal: conviene validar con un abogado el alcance de la inscripción y los plazos de conservación.

## Arquitectura y costos

**Cloud SQL for Postgres es el núcleo, y Firebase se usa para Auth y Hosting.** El dominio es relacional (muchos a muchos, sorteos estratificados en SQL, búsqueda difusa con `pg_trgm`), así que Firestore no encaja. Es el mismo patrón que el sistema de paneles, pero en un proyecto de GCP propio.

&#91;embedded content: arquitectura · Firebase + Google Cloud\]

La ingesta del CDR corre donde se alcanza la base MySQL de uContact (hoy, el servidor Ubuntu del dashboard) y escribe en Cloud SQL. Los sorteos se hacen en SQL con semilla fija (`setseed` + `ORDER BY random()` por estrato sobre el snapshot), así que son reproducibles.

**Costo mensual estimado (aproximado, a confirmar en la calculadora de GCP)**

| Componente | Supuesto | US$ / mes |
| --- | --- | --- |
| Cloud SQL Postgres (Enterprise) | 1 vCPU, 3,75 GB, 20 GB SSD, backups, southamerica-east1 | 60–80 |
| Cloud Run + Functions + Tasks + Scheduler | bajo volumen, mayormente dentro del free tier | 0–10 |
| Firebase Auth + Hosting | menos de 50 usuarios internos | 0 |
| BigQuery | menos de 10 GB, consultas ocasionales | 0–5 |
| Secret Manager, logging | — | 1–3 |
| **Infraestructura** |  | **aprox. 65–100** |
| Enriquecimiento con cascada | 3.000 empresas al mes, 40% llega a pasos pagos | 50–60 |
| **Total recurrente** |  | **aprox. 115–160** |
| Carga semilla (una vez) | 50.000 empresas por Places + web + LLM sin cascada | aprox. 2.400 una vez |

Para bajar costos: una instancia de Cloud SQL compartida con otro sistema ahorra los US$60–80 fijos, pero se pierde aislamiento (y se eligió un sistema independiente). La carga semilla conviene hacerla con cascada y solo sobre las empresas sin teléfono verificado, lo que la reduce a una fracción.

## Métricas de éxito

La línea base sale del CDR de los estudios a empresas de 2026, que ya se puede analizar. Se evalúa al primer estudio completo y a los 6 meses.

| Métrica | Tipo | Medición | Éxito | Stretch |
| --- | --- | --- | --- | --- |
| Respuestas de Alchemer vinculadas automáticamente | Leading | Respuestas con `id_item` válido / total | ≥ 95% | ≥ 99% |
| Muestras generadas en el sistema | Leading | Estudios a empresas con muestra sorteada en el sistema | 100% desde el 2.º estudio | — |
| Llamadas a números inválidos o que no corresponden | Lagging | Disposiciones de CDR "inexistente" + marcas de la sala / intentos | −30% vs. 2026 | −50% |
| Intentos por encuesta completa | Lagging | Intentos del CDR / completas | −15% vs. 2026 | −25% |
| Teléfonos intermediarios detectados y confirmados | Leading | Confirmados por el steward / sospechosos | ≥ 80% de precisión | — |
| Violaciones de reglas de contacto | Guardrail | Llamadas a excluidas, no llamar o en enfriamiento | 0 | 0 |
| Costo de enriquecimiento por empresa verificada | Guardrail | Gasto en APIs / teléfonos que pasan a verificado | ≤ US$0,10 | ≤ US$0,05 |

## Preguntas abiertas

**Decididas (28/10/2026):**

| Tema | Decisión |
| --- | --- |
| Asociación de llamadas | uContact acepta un campo de datos en la lista, pero muchas llamadas se hacen con marcador manual. El CDR se analiza por número destino, no por campaña ni por `id_item`. |
| Resultados de Alchemer | El plan incluye webhooks y API, pero se usa la ingesta manual del .sav con mapeo de variables, a cargo del coordinador. |
| Naturalezas excluidas | Catálogo parametrizable. La carga inicial sale de la hoja "excluidos" del Excel de referencia (pendiente de adjuntar). |
| Enfriamiento | Se cuenta desde el último contacto efectivo. Meses parametrizables. |
| Umbral de intermediario | 5 RUTs por teléfono por defecto, parametrizable por configuración. |
| Calidad del número | Pregunta del cuestionario de Alchemer que llega en el .sav. |

**Abiertas:**

| Pregunta | Quién | ¿Bloquea? |
| --- | --- | --- |
| ¿Cuántos meses de enfriamiento por defecto? | Dirección | No: es un parámetro, pero hace falta un valor inicial |
| ¿Qué padrón o directorio se va a usar como semilla y bajo qué licencia? | Dirección + legal | No (cambia la fase 1, no la bloquea) |
| ¿Hace falta inscribir la base ante la URCDP o ya está cubierta por una inscripción existente de Equipos? | Legal | No para construir, sí para operar |
| ¿Qué destinos del CDR son internos (extensiones, conferencias) y hay que ignorarlos? | Coordinación de campo | No: se arma la lista inicial en la fase 0 |

## Fases

No hay fecha límite declarada. Se propone entregar valor en cada fase y validar la integración primero, porque es el supuesto más riesgoso.

1. **Fase 0 — Validar los dos cruces (1–2 semanas):** con un estudio real ya terminado, comprobar que (a) los números destino del CDR, incluidas las llamadas manuales, se pueden cruzar con los teléfonos de la lista, y (b) el .sav de Alchemer trae `id_item`, teléfono usado y las variables de calidad, y se puede mapear. Si alguno falla, se rediseñan P0.8 y P0.9 antes de seguir. Detalle en la pestaña de spec.
2. **Fase 1 — Base + muestra + campo (P0):** registro maestro, teléfonos M:N con detección de intermediarios, ingesta de bases propias y padrón, exclusiones, políticas de disponibilidad, estudios multi-parte, muestras reproducibles con reemplazos, exportación a uContact, análisis del CDR por destino, ingesta del .sav de Alchemer con mapeo, feedback de sala, configuración parametrizable e indicadores de actividad. Se termina con un estudio real de punta a punta.
3. **Fase 2 — Enriquecimiento (P1):** cascada con presupuesto, búsqueda en Google Places, bandeja de candidatos sin RUT, resolución de entidades asistida, duplicados difusos y tablero de calidad.
4. **Fase 3 — Extensiones (P2):** monitoreo continuo con IA y muestreo PPS.

## Fuentes

- [Google Maps Platform — precios](https://developers.google.com/maps/billing-and-pricing/pricing?authuser=1)
- [SerpAPI — precios](https://serpapi.com/pricing)
- [Brave Search API — precios (CostBench, verificado 20/10/2026)](https://costbench.com/software/ai-search-apis/brave-search-api/)
- [Tavily — precios (ColdIQ)](https://coldiq.com/blog/tavily-pricing)
