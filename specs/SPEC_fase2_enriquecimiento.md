# SPEC — Fase 2: enriquecimiento bajo demanda, descubrimiento de empresas, duplicados difusos y tablero de calidad

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, proyecto GCP `equipos-base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_fase2_enriquecimiento.md`, para que Claude Code lo implemente y lo despliegue **por etapas** (sección 9).
**Base:** `main` en `7d74414`. Fase 2 del PRD (`docs/PRD.md`, «Fases» y «Cascada de enriquecimiento»), revisada en un brainstorming del 17/11/2026.
**Fecha:** 17/11/2026

---

## 1. Problema

- **Empresas sin teléfono.** Muchas empresas de la base no tienen ningún teléfono discable. Hoy no se pueden sortear (o salen sin número, si la muestra las incluye), y conseguir el número es trabajo manual de la sala.
- **Empresas que faltan.** La base no tiene empresas de rubros o zonas que nunca se cargaron.
- **Duplicados con RUT distinto.** Las reglas de fusión resuelven filas sin RUT, pero no detectan pares de empresas con RUT distinto que son la misma empresa o el mismo grupo económico.
- **Calidad sin medir.** No hay un tablero que diga, con las reglas del PRD, cómo está la calidad de la base y qué trabajo tiene el data steward cada semana.

Sin esto la base no mejora sola: cada estudio vuelve a buscar los mismos números a mano.

## 2. Lo que ya existe y se reutiliza

La fase 2 del PRD incluía piezas que ya se construyeron en el spec anterior:

| Pieza del PRD | Dónde está hoy |
|---|---|
| Bandeja de candidatos sin RUT | **Base provisoria** (F6.1 de `SPEC_mejoras_sav_contactos_atributos_identidad`) |
| Resolución de entidades asistida (sugerir el RUT por similitud) | Candidatas en la pantalla «Base provisoria» y reglas de fusión flexibles con `pg_trgm` (F6.2) |
| Medir la calidad de cada fuente de teléfonos | Catálogo de **orígenes de teléfono** y tarjeta **Rendimiento por origen** |

Este spec **no las reconstruye**: las usa.

- Las empresas descubiertas entran a la base provisoria.
- Los teléfonos enriquecidos entran con un origen propio, así que Rendimiento por origen mide sola cuánto rinde cada fuente paga.

## 3. Decisiones (Germán Araújo, 17/11/2026)

| # | Tema | Decisión |
|---|---|---|
| D-1 | Google Places | **Se usa y se guarda el teléfono que devuelve Places**, con origen «Google Places». Se acepta el riesgo respecto de los términos de Google Maps Platform: el `place_id` se puede guardar sin límite, pero los términos no habilitan expresamente guardar el resto del contenido (ver sección 8). |
| D-2 | Cuándo se enriquece | **Bajo demanda y con tope.** Se lanza desde una muestra, una lista filtrada o una ficha, con un costo estimado que hay que aprobar, un tope por corrida y un **tope mensual duro**. No hay enriquecimiento masivo automático. |
| D-3 | Duplicados difusos | La bandeja ofrece **fusionar**, marcar como **grupo económico** (quedan relacionadas sin fusionarse) o **sin relación**. |
| D-4 | Exclusividad por cliente o tema | **Queda fuera** de esta fase. |
| D-5 | Proveedores | Para empezar, **Google Places, Brave Search y un modelo chico de Claude**. Tavily y SerpAPI no se integran salvo que se mida que hacen falta. |

## 4. Objetivos

1. **Conseguir teléfono.** Al menos el **60 %** de las empresas sin teléfono discable a las que se lanza una corrida terminan con al menos un teléfono nuevo.
2. **Costo por teléfono verificado.** El costo de enriquecimiento por teléfono que después la sala verifica es **≤ US$0,10**, que es el guardrail del PRD. La meta stretch es ≤ US$0,05.
3. **Gasto bajo control.** Ninguna corrida supera el tope aprobado y el gasto del mes nunca supera el tope mensual.
4. **Duplicados revisados.** El data steward resuelve los duplicados difusos detectados en menos de 2 semanas.
5. **Calidad visible.** Cada dimensión de calidad del PRD tiene un valor actual, una meta, su evolución mes a mes y la lista de empresas que la incumplen.

## 5. Fuera de alcance

- **Enriquecer la base entera de una vez.** Sería del orden de US$2.400 por cada 50.000 empresas (ver D-2).
- **Monitoreo continuo con IA** (cambios de sitio, cierres): es P2 del PRD.
- **Exclusividad por cliente o tema** (D-4).
- **Datos personales desde la web.** No se extraen nombres de personas, celulares personales ni emails personales; solo datos institucionales (Ley 18.331).
- **Obtener el RUT automáticamente** (DGI u otras fuentes): sigue siendo P2.
- **Tavily y SerpAPI** (D-5).

## 6. Historias de usuario

**Jefe de estudio y coordinador de campo**
- Después de sortear, quiero enriquecer las empresas de la muestra que no tienen teléfono, viendo antes cuánto va a costar, para que salgan a campo con número.
- Quiero ver, en la ficha de una empresa, de dónde salió cada teléfono enriquecido y cuándo, para decidir si confiar en él.

**Data steward**
- Quiero enriquecer una lista filtrada (por ejemplo, pymes de Canelones sin web), con un tope de gasto.
- Quiero buscar empresas nuevas por rubro y zona («imprentas en Salto») y que entren a la base provisoria, sin duplicar las que ya tengo.
- Quiero una bandeja de posibles duplicados entre empresas con RUT, para fusionarlas, marcarlas como grupo económico o descartar la relación.
- Quiero un tablero de calidad con lo que tengo que corregir esta semana.

**Administrador**
- Quiero configurar las claves de los proveedores, los precios, el tope mensual y el tope por corrida, sin desplegar.
- Quiero ver cuánto se gastó en el mes, por proveedor, y que el sistema frene solo al llegar al tope.

## 7. Requisitos

### Etapa A — Tablero de calidad

Va primero porque da la línea de base para medir el efecto del enriquecimiento.

#### A1. Tablero de calidad por dimensión (DMBOK)

**Dónde está:** pantalla nueva **«Calidad de la base»** (menú Administración), para admin, data steward y jefes.

**Qué muestra:** una tarjeta por regla del PRD, cada una con valor actual, meta, estado (cumple, cerca o no cumple) y evolución de los últimos 6 meses.

| Dimensión | Regla (se calcula sobre la base definitiva, salvo que se indique otra cosa) | Meta |
|---|---|---|
| Validez | RUT con dígito verificador correcto; teléfonos en E.164 válidos para Uruguay | 100 % |
| Unicidad | Una empresa por RUT; un teléfono por número; pares de duplicados difusos sin resolver (B4) | 100 %; 0 pendientes |
| Completitud | Empresas disponibles con al menos 1 teléfono discable, CIIU y departamento | ≥ 90 % |
| Exactitud | Teléfonos verificados por la sala sobre el total de discables | Sube cada trimestre |
| Actualidad | Teléfonos discables verificados en los últimos 24 meses | ≥ 70 % |
| Consistencia | Naturaleza jurídica coherente con la razón social (SA, SRL, SAS…); se informan las alertas sin revisar | Alertas revisadas |
| Base provisoria | Empresas provisorias y % con candidata en la definitiva | Sin meta (informativo) |

**Cada tarjeta lleva a la lista** de empresas, teléfonos o pares que incumplen la regla, con un enlace a cada ficha. Así el tablero funciona como lista de trabajo del data steward.

**Tarjeta de enriquecimiento:** gasto del mes contra el tope mensual, gasto por proveedor y **costo por teléfono verificado**. Este último se calcula como gasto de enriquecimiento dividido por la cantidad de teléfonos de origen enriquecido que pasaron a verificado, en el mes y acumulado.

**Histórico:** un Cloud Scheduler diario guarda una foto de los indicadores en la tabla `calidad_medicion` (fecha, dimensión, valor, numerador, denominador). El gráfico de evolución se arma con esa tabla.

**Criterios de aceptación:**
- [ ] El tablero muestra las 7 dimensiones con su valor, meta y estado, y cada una abre la lista de lo que la incumple.
- [ ] Al día siguiente de desplegar ya hay una medición guardada, y a los 7 días la evolución muestra 7 puntos.
- [ ] La consistencia detecta, por ejemplo, una empresa con naturaleza «SRL» y razón social «… S.A.».

### Etapa B — Enriquecimiento bajo demanda

#### B1. Configuración de proveedores, precios y topes

**Dónde está:** Configuración, sección **«Enriquecimiento»** (solo admin), versionada como el resto de la configuración y con historial.

**Qué se configura:**
- **Proveedores:** Google Places, Brave Search y Claude, cada uno activable y desactivable. Las **claves de API** se guardan en **Secret Manager**, con el mismo patrón que la contraseña del CDR: se cargan desde la aplicación y nunca se muestran.
- **Precio unitario de cada paso** (lo usa el estimador, y se actualiza a mano si el proveedor cambia precios). Valores iniciales verificados el 17/11/2026:

  | Paso | Precio inicial |
  |---|---|
  | Places Text Search Enterprise | US$0,035 por llamada (US$35 cada 1.000), con 1.000 llamadas gratis por mes |
  | Brave Search | US$0,005 por búsqueda (valor del PRD, a confirmar) |
  | Claude, modelo chico vigente (hoy Haiku 5.5) | US$0,10 por millón de tokens de entrada y US$0,50 por millón de salida; el modelo es un parámetro |

- **Topes:**
  - **mensual duro** (valor inicial US$100);
  - **por corrida** (valor inicial US$20);
  - **máximo de empresas por corrida** (valor inicial 2.000).
- **Confianza** con la que entran los datos enriquecidos: 30 por defecto, por debajo de cargas (50) y sala (80). Así nunca pisan datos de mejor fuente.
- **Orígenes de teléfono de sistema nuevos:** `google_places` («Google Places») y `web` («Sitio web»). Se agregan al catálogo con prioridad baja, editable.

**Criterios de aceptación:**
- [ ] Sin clave cargada, un proveedor aparece como «no configurado» y la cascada lo saltea.
- [ ] Cambiar un precio o un tope queda en el historial de configuración y en Auditoría.

#### B2. Corrida de enriquecimiento

**Desde dónde se lanza:**
- el detalle de una **muestra**: «Enriquecer empresas sin teléfono discable», o «todas las de la muestra»;
- el buscador de **Empresas**, con los filtros actuales: «Enriquecer estas N empresas»;
- la **ficha** de una empresa: «Enriquecer esta empresa».

**Quién la lanza:** admin y data steward. El jefe de estudio puede lanzarla solo desde una muestra.

**Qué busca:** teléfono, sitio web, dirección y email institucional (genérico, como info@ o contacto@). También una **señal de intermediario**: si el sitio pertenece a un estudio contable o jurídico.

**Paso 1, estimación y aprobación (antes de gastar):**
- El sistema calcula el **costo máximo**: N empresas por el costo de todos los pasos. También calcula el **costo esperado**, con la tasa de éxito medida de cada paso; mientras no haya historia, usa 60 % para Places.
- Muestra cuántas empresas se saltean y por qué:
  - ya tienen un teléfono verificado;
  - se enriquecieron en los últimos 90 días;
  - están en «no llamar».
- Muestra el gasto del mes y lo que queda del tope.
- Para lanzar hay que **aprobar**. Si el costo máximo supera el tope por corrida o lo que queda del tope mensual, se ofrece reducir la cantidad de empresas (por orden de la muestra, o al azar).

**Ejecución:** corre como **tarea** en Cloud Tasks, con progreso y opción de cancelar (mecanismo `cancelada` ya existente). La cascada por empresa va **de lo más barato a lo más caro** y **se corta apenas consigue al menos un teléfono** (ver Q1):

1. **Fuentes propias (US$0):** teléfonos de la empresa en estado «sin verificar» o con otros orígenes. Si ya tiene un teléfono discable, no se gasta en ella. Si es provisoria con candidata en la definitiva, se sugiere la fusión en vez de enriquecer.
2. **Google Places Text Search:**
   - **consulta:** razón social (o nombre de fantasía) más localidad o departamento y «Uruguay»;
   - **aceptación de un resultado:** si el nombre tiene una similitud de trigramas ≥ 0,6 con el de la empresa y el departamento coincide cuando hay dato;
   - **datos que se toman:** teléfono nacional, sitio web, dirección y `place_id`;
   - **varios resultados aceptables:** se toma el de mayor similitud y los demás se informan.
3. **Búsqueda web (Brave):** solo si no hay teléfono o no hay sitio. Se busca razón social más «Uruguay», con ciudad si hay dato, y se elige el **sitio oficial**: el dominio que mejor coincide con el nombre, descartando directorios, redes sociales y guías.
4. **Extracción con Claude:**
   - **qué lee:** la portada y la página de contacto del sitio (como máximo 2 páginas y unos 6.000 tokens);
   - **qué devuelve:** un JSON con teléfonos, emails institucionales, dirección, si es estudio contable o jurídico, y una confianza;
   - **qué no extrae:** el prompt prohíbe datos personales (nombres, celulares o emails de personas).

**Tope duro:** antes de cada llamada paga, se verifica que el gasto acumulado de la corrida y del mes no supere los topes. Si se superaría, la corrida **se detiene** en ese punto con el estado «detenida por tope» y lo hecho queda guardado.

**Registro de cada corrida:**
- **corrida** (`enriquecimiento_corrida`): quién, desde dónde, cantidad de empresas, estimación aprobada, gasto real, estado y resultado;
- **cada paso** (`enriquecimiento_paso`): empresa, proveedor, consulta, costo, resultado, y el `place_id` o la URL usada.

**Criterios de aceptación:**
- [ ] Una corrida sobre 50 empresas sin teléfono muestra la estimación, no gasta nada hasta aprobarla, y al terminar informa empresas con teléfono nuevo, gasto real por proveedor y empresas sin resultado.
- [ ] Una empresa que ya tiene un teléfono discable no genera llamadas pagas.
- [ ] Con el tope mensual casi agotado, la corrida se detiene al llegar al tope y no hace la llamada siguiente.
- [ ] Cancelar una corrida en curso la detiene sin perder lo ya conseguido.
- [ ] Ningún dato personal queda guardado a partir de la extracción. Hay un test con un sitio de ejemplo que lista a una persona con su celular.

#### B3. Qué pasa con los datos encontrados

**Teléfonos:**
- Cada teléfono encontrado se vincula a la empresa **«sin verificar»**, con origen `google_places` o `web`.
- La evidencia de cada origen guarda la corrida y la URL o el `place_id`.
- Entran a la exportación como cualquier teléfono discable, en el orden de prioridad de su origen.
- Los verifica la sala con el .sav, como al resto.

**Sitio web, dirección y email institucional:**
- Entran como historia de la empresa con fuente `enriquecimiento`, la corrida y la confianza configurada.
- La regla de supervivencia hace que **no pisen** datos de mejor fuente.
- El email institucional se guarda en un atributo de sistema `email_institucional`.

**Señal de estudio contable o jurídico:** el teléfono queda como **intermediario sospechoso**, con el motivo «sitio de estudio contable/jurídico (enriquecimiento)», y va a la bandeja de Intermediarios.

**`place_id`:** se guarda en la empresa (atributo de sistema `google_place_id`). Sirve para no volver a pagar la búsqueda y para el descubrimiento (B5).

**Latitud y longitud de Places:** no se guardan. Los términos permiten guardarlas solo 30 días y no hacen falta.

**Ficha:**
- La pestaña Teléfonos muestra el origen y un enlace a la corrida.
- La línea de tiempo muestra «Enriquecimiento #N: 1 teléfono (Google Places), web, dirección».

**Rendimiento por origen:** muestra Google Places y Sitio web como cualquier origen. Es la medición de calidad de cada fuente.

**Deshacer:** una corrida se puede **deshacer** desde su detalle. Se quitan los vínculos y los valores que trajo, salvo los teléfonos que la sala ya verificó, que quedan.

**Criterios de aceptación:**
- [ ] Un teléfono de Places queda «sin verificar», con origen Google Places, y sale en el CSV de la muestra.
- [ ] Un sitio web enriquecido no reemplaza a uno cargado con confianza 50.
- [ ] Deshacer una corrida quita sus teléfonos no verificados y conserva los verificados.

#### B4. Duplicados difusos y grupo económico

**Detección:** un proceso diario, que también se puede lanzar a mano, busca **pares de empresas de la base definitiva con RUT distinto** que comparten algo de esto:
- **un teléfono discable**: se excluyen los intermediarios confirmados y los teléfonos con 5 o más RUT, que ya maneja la detección de intermediarios;
- **el dominio del sitio web**: se excluyen dominios genéricos como gmail.com o facebook.com, con una lista editable;
- **la dirección normalizada y el departamento**;
- **una razón social muy similar**: similitud ≥ 0,9 sin sufijo societario.

**Bandeja «Posibles duplicados»** (menú Base de datos, para data steward):
- Cada par aparece lado a lado, con los criterios que coinciden y la evidencia.
- **Acciones:**
  - **«Fusionar»**: usa la fusión existente, que es reversible;
  - **«Son grupo económico»**: las relaciona sin fusionarlas. Tabla `grupo_economico` con nombre editable, y `empresa.grupo_economico_id`. Si una de las dos ya está en un grupo, la otra se suma a ese grupo;
  - **«Sin relación»**: se guarda para no volver a proponer el par.
- Las tres acciones quedan en Auditoría.

**Grupo económico en la ficha y en el sorteo:**
- **Ficha:** muestra el grupo y las otras empresas que lo forman.
- **Sorteo:** opción nueva en el paso 1 de «Nueva muestra», **«Como máximo una empresa por grupo económico»**, marcada por defecto (ver Q3). Si sale sorteada una empresa de un grupo que ya tiene otra en la muestra, se saltea y sigue la siguiente del orden.
  - La pertenencia a grupos se congela en el snapshot, así **Verificar reproducibilidad** sigue funcionando.
  - La opción se guarda en los criterios y en los templates de sorteo.

**Criterios de aceptación:**
- [ ] Dos empresas con RUT distinto y el mismo teléfono aparecen como par, con «teléfono» como criterio.
- [ ] «Son grupo económico» las relaciona sin fusionarlas, y una muestra con la opción marcada no saca las dos.
- [ ] «Sin relación» hace que el par no vuelva a aparecer.
- [ ] Verificar reproducibilidad de una muestra con la opción marcada da OK.

### Etapa C — Descubrimiento de empresas nuevas

#### B5. Búsqueda por rubro y zona en Google Places

**Pantalla «Buscar empresas nuevas»** (menú Base de datos, para admin y data steward):
- Se escriben consultas como «imprentas en Salto» o «estudios de arquitectura en Montevideo». También se puede armar la consulta con rubro, departamento y localidad.
- **Estimación de costo:**
  - cada página de resultados es una llamada Text Search (US$0,035);
  - se fija cuántas páginas pedir, como máximo las que permita la API;
  - aplican los mismos topes que en B2.

**Preview antes de guardar.** Cada resultado se compara con la base y se clasifica:

| Caso | Qué pasa |
|---|---|
| Mismo `place_id` ya guardado | Se informa; no se hace nada |
| Coincide con una empresa por teléfono, sitio o nombre y dirección, usando las reglas de fusión | Se ofrece **completarla** con los datos de Places (y guardar el `place_id`), con decisión humana si la regla es flexible |
| No coincide con nada | **Alta en la base provisoria**, con origen Google Places |

Se puede desmarcar cualquier resultado antes de confirmar.

**Al confirmar:** se crea un lote **«Descubrimiento #N»**, que funciona como una carga: tiene linaje, se puede deshacer y queda en Auditoría. Las provisorias nuevas pasan después por el flujo existente (agregar el RUT o fusionar). El rubro que se buscó queda guardado como atributo de la empresa (`rubro_descubrimiento`).

**Criterios de aceptación:**
- [ ] «Imprentas en Salto» muestra los resultados con su clasificación, no guarda nada hasta confirmar, y al confirmar crea provisorias con código `P-`, teléfono «sin verificar» y origen Google Places.
- [ ] Un resultado que coincide con una empresa existente no se duplica.
- [ ] Deshacer el lote quita las provisorias que creó y los datos que agregó.

### P1 — Deseables

- **Reporte mensual por correo** a dirección y al data steward, con la calidad por dimensión, el gasto de enriquecimiento y el costo por teléfono verificado. Cubre el proceso mensual del PRD.
- **Enriquecimiento sugerido:** al sortear, avisar «N empresas de esta muestra no tienen teléfono: enriquecerlas costaría hasta US$X».
- **Tasa de éxito real por paso**, en el estimador y en el tablero.

### P2 — A futuro

- Tavily o SerpAPI como pasos adicionales, si Brave no alcanza.
- Monitoreo continuo con IA (P2 del PRD).
- Exclusividad por cliente o tema (D-4).

## 8. Riesgos

| Riesgo | Mitigación |
|---|---|
| **Términos de Google Maps Platform.** Los Service Specific Terms permiten guardar el `place_id` y, por 30 días, la latitud y la longitud. No habilitan expresamente guardar el teléfono ni el resto del contenido, y los términos generales restringen guardar contenido de Google Maps. | Decisión D-1: riesgo aceptado y documentado en D45. Mitigaciones: (1) el origen `google_places` queda en cada vínculo, así que se puede borrar o desactivar en bloque si hiciera falta; (2) un interruptor en la configuración apaga Places sin desplegar; (3) se recomienda una consulta legal antes de usar Places en volumen. |
| Datos personales extraídos de la web | El prompt prohíbe datos personales, se valida la salida (descartar celulares cuando el texto los asocia a una persona) y hay un test. Solo se guardan datos institucionales. |
| Gasto descontrolado | Estimación con aprobación, tope por corrida, tope mensual duro que se verifica antes de cada llamada paga, y registro de cada paso con su costo. |
| Teléfonos de mala calidad (directorios, centrales) | Entran «sin verificar» y con confianza baja. Rendimiento por origen los mide, y la señal de intermediario los marca. |
| Fusionar por error un grupo económico | La bandeja separa «fusionar» de «grupo económico», y la fusión es reversible. |

## 9. Etapas de implementación

| Etapa | Contenido | Despliegue |
|---|---|---|
| **A** | A1, tablero de calidad e histórico diario | api, migrar, web, programar (Scheduler) |
| **B** | B1 a B4: configuración, corrida, datos encontrados, duplicados y grupo económico | api, migrar, web, programar |
| **C** | B5, descubrimiento en Places | api, web |

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh migrar
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh programar
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Si ya está mergeado el fix de región, se usa `EMPRESAS_REGION=us-central1`.

**Antes de la etapa B:**
- crear las claves de Google Places (en el mismo proyecto GCP, restringida a Places API), de Brave Search y de Anthropic;
- cargarlas en Configuración → Enriquecimiento;
- habilitar la facturación de Places en el proyecto.

**Documentación:**
- decisiones **D45**: proveedores y riesgo de Places;
- **D46**: enriquecimiento bajo demanda con topes;
- **D47**: grupo económico y su regla de sorteo;
- **D48**: tablero de calidad;
- guía de despliegue; secciones del manual; regenerar el Word y el PDF.

**Tests:** uno por cada criterio de aceptación. Los proveedores se simulan en los tests: ningún test hace llamadas pagas.

## 10. Costos

**Infraestructura: ninguno adicional.** Se agregan tablas, un Scheduler diario y tareas sobre la misma Cloud SQL y Cloud Run. Secret Manager suma tres secretos, que cuestan centavos por mes.

**APIs: gasto por uso, siempre bajo el tope mensual configurado (valor inicial US$100).**

| Escenario | Cálculo | Costo |
|---|---|---|
| 1 empresa, cascada completa | Places US$0,035 + Brave US$0,005 + Claude (unos 6.000 tokens de entrada y 400 de salida, ≈ US$0,0008) | **≈ US$0,04** como máximo |
| 1.000 empresas sin teléfono, Places encuentra el 60 % | Places 1.000 × 0,035 = US$35 (o US$0 si entran en las 1.000 gratis del mes) + Brave y Claude para 400 × 0,0058 ≈ US$2,3 | **≈ US$37** (≈ US$2 si se usan las llamadas gratis) |
| 3.000 empresas por mes (supuesto del PRD) | 2.000 llamadas pagas de Places = US$70 + Brave y Claude para 1.200 ≈ US$7 | **≈ US$77 por mes** |
| Descubrimiento: 20 búsquedas por mes de 3 páginas | 60 llamadas a US$0,035 | **≈ US$2 por mes** (o US$0 dentro de las gratis) |

**El costo lo pone Google Places.** Claude, con los precios actuales del modelo chico, es casi despreciable. Si el costo por teléfono verificado supera US$0,10, conviene probar con Brave + Claude primero y Places solo como respaldo. Es un cambio del orden de la cascada, que este spec deja **configurable** (P1).

Precios verificados el 17/11/2026: Places en la lista pública de Google Maps Platform (vía openplacesapi.com) y Claude en la página de Anthropic. El de Brave sale del PRD (octubre de 2026) y hay que confirmarlo.

## 11. Métricas de éxito

| Métrica | Tipo | Meta | Medición |
|---|---|---|---|
| Empresas enriquecidas con al menos 1 teléfono nuevo | Leading | ≥ 60 % | Por corrida |
| Costo por teléfono verificado de origen enriquecido | Guardrail | ≤ US$0,10 (stretch ≤ US$0,05) | Tablero, mensual |
| Contactabilidad de Google Places y Sitio web, contra los orígenes propios | Lagging | Que no sea más de 15 puntos peor | Rendimiento por origen |
| Corridas que superan el tope | Guardrail | 0 | Registro de corridas |
| Duplicados difusos pendientes con más de 14 días | Leading | 0 | Tablero, unicidad |
| Completitud (empresas disponibles con teléfono, CIIU y departamento) | Lagging | ≥ 90 % a 6 meses | Tablero |

## 12. Preguntas abiertas

| # | Pregunta | Quién | ¿Bloquea? |
|---|---|---|---|
| Q1 | ¿La cascada se corta con **1 teléfono** encontrado (propuesta, la más barata) o sigue hasta tener teléfono **y** sitio web? | Germán | Etapa B |
| Q2 | ¿Los topes iniciales (US$100 por mes, US$20 por corrida) están bien? | Dirección | No |
| Q3 | ¿«Como máximo una empresa por grupo económico» viene **marcado** por defecto (propuesta) o desmarcado? | Jefes de estudio | No |
| Q4 | ¿Se consulta con un abogado el uso del teléfono de Places antes de usarlo en volumen (riesgo D-1)? | Dirección / legal | No (riesgo aceptado) |
| Q5 | ¿Los términos de Brave Search permiten guardar lo que se obtiene a partir de sus resultados? El sitio y la extracción vienen de la propia empresa, pero conviene confirmarlo. | Legal | No |
