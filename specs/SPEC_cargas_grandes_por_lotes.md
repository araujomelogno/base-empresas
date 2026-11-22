# SPEC — Cargas grandes por lotes: preview, confirmación, deshacer y borrado

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, proyecto GCP `equipos-base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_cargas_grandes_por_lotes.md`, para que Claude Code lo implemente y lo despliegue.
**Base:** `main` en `6ae1f83` (PR #19).
**Fecha:** 22/11/2026
**Origen:** falla de la carga #7 (190.000 filas) del 22/11/2026, analizada con los logs de Cloud Run y Cloud SQL (opción A elegida por Germán Araújo).

---

## 1. Problema

El 22/11/2026, la confirmación de una carga de **190.000 empresas** (carga #7, tarea 21) falló al final y no aplicó nada. Esto muestran los logs:

- **Se escribió toda la carga y después se descartó.** Entre las 05:31 y las 05:43 UTC, el autovacuum de Postgres limpió las filas de una transacción abortada, y todas las tablas quedaron con **«0 remain»**:

  | Tabla | Filas descartadas |
  |---|---|
  | `empresa` | 387.112 |
  | `empresa_campo_historia` | 2.132.278 |
  | `empresa_atributo` | 795.379 |
  | `telefono_vinculo` | 170.565 |
  | `telefono_vinculo_origen` | 187.848 |
  | `telefono` | 121.884 |

- **Se cortó a los 30 minutos.**
  - La instancia que procesaba la tarea arrancó a las 04:49.
  - La tarea dejó de avanzar a las 05:29:34, y justo después empezó el descarte.
  - La API corre con `--timeout 1800` y Cloud Tasks con `dispatch_deadline` de 1800 s. Al vencer el plazo se cortó la conexión y Postgres hizo rollback.
  - No quedó un error de Python porque el proceso no falló: lo cortaron.
- **No hubo falta de memoria ni caídas de Cloud SQL.**
- **La base quedó saturada durante la carga.** `GET /api/atributos` tardaba entre 100 y 232 s, y dos llamadas fallaron con `psycopg_pool.PoolTimeout: couldn't get a connection after 30.00 sec`.

**Causa:** `cargas._tarea_confirmar` procesa **todas las filas en una sola transacción y una sola tarea**: lee el archivo, ejecuta `procesar(...)` fila por fila con varias consultas por fila, y después detecta intermediarios sobre todo el conjunto. Con 190.000 filas tarda más de 30 minutos en una `db-f1-micro`.

Otras operaciones tienen el mismo diseño y también fallarían con cargas de este tamaño:

- **El preview** (`_tarea_preview`) procesa todo en un savepoint dentro de una sola tarea.
- **«Deshacer carga»** (`cargas.deshacer`) es **sincrónico**, dentro del pedido HTTP. Firebase Hosting corta a los 60 s, y recalcula empresa por empresa.
- **«Borrar carga»** corre en una sola tarea con una sola transacción.

**Consecuencia:** hoy no se puede cargar una base de más de unas decenas de miles de filas. Si una carga grande llegara a confirmarse, tampoco se podría deshacer ni borrar.

## 2. Decisión

**Opción A: todo el procesamiento de cargas se hace por lotes.**

- Cada lote (por defecto, 5.000 filas) es **una transacción y una tarea**.
- Una carga deja de ser «todo o nada»: si se interrumpe, los lotes ya aplicados quedan y se puede **reanudar**, **deshacer** o **borrar**.
- Deshacer y borrar siguen siendo exactos porque cada dato guarda de qué carga vino.

Descartadas:
- **B.** Correr la carga como Cloud Run job en una sola transacción: satura la base durante horas.
- **C.** Agrandar la base a `db-g1-small` como única solución: cuesta US$25–30 más por mes y no garantiza bajar de 30 minutos.

## 3. Objetivos

1. **Una base de 190.000 filas se procesa entera.** El preview y la confirmación terminan sin cortarse y en menos de 60 minutos cada uno, en la instancia actual (`db-f1-micro`).
2. **Ningún lote se acerca al límite de 30 minutos.** Meta: menos de 3 minutos por lote de 5.000 filas.
3. **La aplicación sigue usable durante una carga grande.** Ninguna llamada de la web falla por `PoolTimeout`, y las pantallas responden en menos de 5 s.
4. **Toda carga interrumpida se puede reanudar, deshacer o borrar** desde la pantalla, sin intervenir la base.
5. **Deshacer y borrar una carga de 190.000 filas terminan sin cortarse.**

## 4. Fuera de alcance

- **Subir archivos de más de 30 MB.** Es un límite de Firebase Hosting. Si hiciera falta, se resuelve aparte con subida directa al bucket (P2).
- **Agrandar Cloud SQL.** Queda como recurso si las métricas no se cumplen (ver sección 9).
- **Paralelizar lotes de una misma carga.** Se procesan en orden, uno a la vez, por consistencia y para no saturar la base.
- **Cambiar las reglas de negocio de la carga.** Mapeo, fusión, supervivencia, orígenes y atributos siguen igual; solo cambia cómo se ejecutan.

## 5. Historias de usuario

- Como **data steward**, quiero cargar una base de 190.000 empresas y que termine, viendo el avance lote por lote.
- Como **data steward**, si una carga se interrumpe (por un corte, un despliegue o un error en un lote), quiero ver cuántos lotes se aplicaron y **reanudarla** desde donde quedó, sin duplicar nada.
- Como **data steward**, quiero **deshacer** o **borrar** una carga grande, completa o interrumpida, sin que se corte.
- Como **cualquier usuario**, quiero seguir usando la aplicación mientras corre una carga grande.

## 6. Requisitos

### P0 — Imprescindibles

#### L1. El archivo se lee una sola vez

- Hoy cada tarea vuelve a leer y parsear el archivo original desde el bucket (`_leer`). Con lotes, eso sería parsear un .xlsx de 190.000 filas decenas de veces.
- **Cambio:** al crear la carga (`cargas.crear`), el archivo se convierte **una vez** a un formato intermedio que se pueda leer por rango de filas. Opciones:
  - una tabla `carga_fila` (`carga_id`, `fila`, `datos jsonb`), recomendada porque permite leer un rango con una consulta;
  - o un CSV normalizado en el bucket.
- Cada lote lee solo sus filas.
- La tabla intermedia se borra cuando la carga queda **confirmada, descartada, deshecha o borrada**, para no ocupar disco. Mientras la carga está en preview o interrumpida se conserva, porque hace falta para reanudar.

**Criterios de aceptación:**
- [ ] El archivo original se parsea una sola vez por carga (se verifica con un contador o con los logs).
- [ ] Al confirmar una carga se libera su almacenamiento intermedio.

#### L2. Preview por lotes

- El preview se ejecuta como una **cadena de tareas**, una por lote:
  - cada lote corre en su propia transacción, con un savepoint que se descarta, igual que hoy;
  - cada lote suma sus conteos a los de la carga.
- **Coherencia entre lotes:** como cada lote descarta lo que haría, un lote no «ve» las empresas que crearía un lote anterior. Para que los conteos sean exactos:
  - **Antes del primer lote**, una pasada liviana sobre la tabla intermedia agrupa las filas por clave de identidad (RUT válido normalizado). Así, todas las filas con el mismo RUT caen **en el mismo lote**. Los lotes se arman por grupos de RUT, de aproximadamente el tamaño configurado.
  - Las filas sin RUT (que se resuelven con reglas flexibles o van a la base provisoria) se procesan al final. Para ellas, el preview informa que sus conteos son **aproximados** si dos filas del mismo archivo podrían coincidir entre sí.
- Las **coincidencias a decidir** (reglas flexibles) se acumulan de todos los lotes en la misma pantalla de hoy. Las decisiones se guardan por número de fila, como hoy.
- **Progreso:** «Lote 12 de 38 · 60.000 de 190.000 filas», con la barra de avance actual.

**Criterios de aceptación:**
- [ ] El preview de una base de 190.000 filas termina, y sus conteos (altas, actualizaciones, rechazos, teléfonos, atributos) coinciden con los de la confirmación, salvo la aclaración de las filas sin RUT.
- [ ] Un archivo con el mismo RUT repetido en filas lejanas (fila 10 y fila 150.000) cuenta **1 alta**, no 2.

#### L3. Confirmación por lotes

- La confirmación es una **cadena de tareas, una por lote**, en el mismo orden y con los mismos lotes que el preview.
- **Cada lote:**
  1. corre en **su propia transacción**: aplica sus filas con las reglas actuales y la misma `carga_id` como fuente;
  2. registra su resultado en una tabla nueva `carga_lote` (`carga_id`, `numero`, `fila_desde`, `fila_hasta`, `estado` pendiente/en_proceso/aplicado/error, `conteos`, `intentos`, `inicio`, `fin`, `error`);
  3. **al hacer commit**, encola el lote siguiente.
- **Idempotencia:** si Cloud Tasks reintenta un lote que ya está «aplicado», no hace nada. Si un lote falló a mitad de camino, su transacción se revirtió y se puede reintentar entero.
- **Paso final**, cuando el último lote se aplicó (en su propia tarea, también por partes si hace falta):
  - detección de intermediarios sobre los teléfonos tocados (`intermediarios.detectar`), en tandas de, por ejemplo, 10.000 teléfonos;
  - rechazos consolidados;
  - conteos totales;
  - Auditoría `carga.confirmar`;
  - estado **«confirmada»**.
- **Tiempo por lote:** cada lote tiene que terminar con holgura dentro del límite. Meta < 3 min; alarma en el log si supera 10 min.
- **Velocidad:** se reemplazan las consultas fila por fila por operaciones **por lote**:
  - precargar en una consulta las empresas existentes de los RUT del lote, sus teléfonos y sus atributos;
  - insertar la historia, los vínculos, los orígenes y los atributos con `executemany` o `COPY`;
  - recalcular los valores vigentes solo de las empresas tocadas.

  El resultado tiene que ser **idéntico** al procesamiento actual (los tests existentes de cargas siguen pasando).
- **Una carga a la vez:** solo una carga puede estar confirmando, deshaciendo o borrando por lotes al mismo tiempo (lock por advisory lock o por estado). Si se intenta otra, queda **en cola** con el aviso «Esperando a que termine la carga #N». Así la base no se satura con dos procesos pesados.
- **Respiro para la base:** entre lote y lote hay una pausa configurable (por defecto 1 s). La tarea usa **una sola conexión** del pool, para no dejar a la web sin conexiones.

**Criterios de aceptación:**
- [ ] La confirmación de 190.000 filas termina sin superar los 30 minutos en ningún lote, y la carga queda «confirmada» con los mismos conteos que el preview.
- [ ] Mientras corre, la ficha de una empresa, la lista de atributos y Actividad responden en menos de 5 s, sin `PoolTimeout`.
- [ ] Reintentar manualmente la tarea de un lote ya aplicado no duplica datos.
- [ ] Los tests actuales de cargas (altas, actualizaciones, supervivencia, orígenes, atributos, contactos, reglas de fusión y base provisoria) siguen pasando con un tamaño de lote chico (por ejemplo, 2), para forzar varios lotes.

#### L4. Cargas interrumpidas: reanudar, deshacer o borrar

- **Estado nuevo «interrumpida»**, para cuando la cadena se corta:
  - un lote falla después de sus reintentos;
  - una tarea queda «corriendo» sin avanzar por más de 35 minutos (más que el plazo de Cloud Tasks): un chequeo periódico, que puede ser el Scheduler diario o la misma pantalla, la marca como interrumpida;
  - o se cancela.
- **Detalle de la carga interrumpida:**
  - **«N de M lotes aplicados (X filas)»** y el error del lote que falló;
  - lo que ya se aplicó está en la base y se ve como cualquier dato de esa carga.
- **Acciones** (data steward y admin):
  - **«Reanudar»:** encola el primer lote no aplicado y sigue la cadena.
  - **«Deshacer»:** quita lo que aplicaron los lotes hechos (L5). Hoy solo se permite en cargas «confirmadas»; se amplía a «interrumpida».
  - **«Borrar carga»:** como hoy, pero por lotes (L5).
- **Cancelar** una confirmación en curso (mecanismo `cancelada` ya existente) deja la carga **interrumpida**: el lote en curso se revierte y los anteriores quedan.

**Criterios de aceptación:**
- [ ] Si se fuerza un error en el lote 5 de 10, la carga queda «interrumpida, 4 de 10 lotes aplicados». «Reanudar» aplica del 5 al 10 y la deja «confirmada», con los mismos resultados que una carga sin interrupción.
- [ ] Deshacer una carga interrumpida deja la base como estaba antes de la carga.
- [ ] Una tarea «corriendo» trabada más de 35 minutos se marca como interrumpida y ofrece Reanudar.

#### L5. Deshacer y borrar por lotes

- **«Deshacer carga»** pasa de sincrónico (dentro del pedido HTTP) a **tarea por lotes**, con progreso:
  - **Lote 1:** quita los vínculos, orígenes, contactos y sucursales de la carga, en tandas por id.
  - **Lotes siguientes:** recalculan las empresas tocadas, de a 2.000.
  - **Lote final:** marca como anuladas las empresas que quedaron sin respaldo, reevalúa intermediarios y deja la carga «deshecha».
- **«Borrar carga»** (`borrado._tarea_borrar_carga`) sigue la misma idea. Cada paso (aportes, empresas sin respaldo, recálculos, archivo) se hace en tandas, cada una en su transacción, con un estado intermedio **«borrando»**. Si se interrumpe, «Borrar» se puede volver a lanzar y retoma.
- La regla de que no se deshace una carga cuyas empresas están en una muestra sigue igual.

**Criterios de aceptación:**
- [ ] Deshacer una carga de 190.000 filas termina sin cortarse y la base vuelve al estado anterior.
- [ ] Borrar una carga de 190.000 filas termina sin cortarse. Si se interrumpe, volver a lanzarlo completa el borrado.

#### L6. Configuración, observabilidad y tests

- **Configuración** (Configuración → Cargas, versionada):
  - tamaño de lote (por defecto 5.000; mínimo 500; máximo 20.000);
  - pausa entre lotes (por defecto 1 s);
  - tiempo para considerar una tarea trabada (por defecto 35 min).
- **Log por lote:** carga, número de lote, filas, duración y conteos. Así un problema futuro se diagnostica con un filtro simple, sin que el seguimiento de progreso de la web llene los logs.
- **Menos logs del seguimiento de progreso:** el seguimiento de la web pasa de cada 2 s a cada 5 s mientras dure una carga larga.
- **Test de volumen:** genera 50.000 filas sintéticas, mide el tiempo por lote y falla si un lote supera 3 min en el entorno de test. Corre aparte (marcado como lento).
- `docs/decisiones.md`: **D49 — Cargas por lotes**: deja de ser todo o nada, estado «interrumpida», reanudar, una carga pesada a la vez.
- Manual: «Cargas grandes», que explica el progreso por lotes, qué hacer si queda interrumpida y que se puede seguir usando la aplicación mientras corre.

### P1 — Deseables

- **P1.1** `GET /api/atributos` hoy tarda mucho con la base cargada: cuenta los valores (`n_valores`) en el momento. Conviene guardar ese conteo o calcularlo con un índice, para que la pantalla no dependa del tamaño de `empresa_atributo`.
- **P1.2** Estimar la duración antes de confirmar («unos 25 minutos») con el tiempo medido por lote en el preview.
- **P1.3** Aviso por correo al data steward cuando una carga grande termina o queda interrumpida.

### P2 — A futuro

- Subida directa al bucket con URL firmada, para archivos de más de 30 MB.
- Lotes en paralelo para cargas sin dependencias entre filas.

## 7. Qué hacer con la carga #7

- Hoy está «en proceso» o «error», sin datos aplicados, porque se revirtió todo.
- **Antes de desplegar este cambio:** borrarla con «Borrar carga» (sirve para cargas trabadas), o dejarla.
- **Después de desplegar:** volver a crear la carga con el mismo archivo y la misma plantilla, revisar el preview por lotes y confirmar.

## 8. Despliegue

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh migrar
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

- La migración nueva (`0013_cargas_por_lotes.sql`) agrega `carga_fila` (o el campo con la ruta del CSV intermedio), `carga_lote` y los estados «interrumpida» y «borrando».
- Si ya está mergeado el fix de región, se usa `EMPRESAS_REGION=us-central1`.
- **No desplegar mientras corre una carga:** el despliegue reinicia Cloud Run y la interrumpe. Con este cambio se puede reanudar; sin él, se pierde.

**Prueba en producción:**
1. Una carga de unas 20.000 filas: preview, confirmar y deshacer.
2. Después, la base de 190.000.

## 9. Costo

**Ninguno adicional.** Las tareas por lotes son más pedidos cortos a Cloud Run y a Cloud Tasks: decenas por carga, dentro de los niveles gratuitos. La tabla intermedia ocupa espacio en la misma Cloud SQL mientras dura la carga (del orden de cientos de MB para 190.000 filas) y se libera al terminar. El disco actual de 10 GB, con autoincremento, alcanza.

**Si después de implementarlo los lotes siguen siendo lentos** (más de 3 min por cada 5.000 filas), el siguiente paso sería subir Cloud SQL a `db-g1-small`, por unos **US$25–30 más por mes**. No se recomienda antes de medir.

## 10. Métricas de éxito

| Métrica | Meta |
|---|---|
| Duración del preview y de la confirmación de 190.000 filas | < 60 min cada uno |
| Duración por lote de 5.000 filas | < 3 min (alarma > 10 min) |
| Errores `PoolTimeout` durante una carga | 0 |
| Cargas interrumpidas que se resuelven con Reanudar, Deshacer o Borrar sin tocar la base | 100 % |

## 11. Preguntas abiertas

| # | Pregunta | Quién | ¿Bloquea? |
|---|---|---|---|
| Q1 | ¿El tamaño de lote por defecto (5.000) está bien, o preferís empezar más chico (2.000) para ver el avance más seguido? | Germán | No: es configurable |
| Q2 | ¿Hace falta el aviso por correo al terminar una carga grande (P1.3)? | Germán | No |
