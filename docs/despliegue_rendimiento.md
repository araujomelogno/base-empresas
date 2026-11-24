# Despliegue: rendimiento con una base grande

Este documento lleva a producción las mejoras de rendimiento para una base con cientos de miles de empresas, en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**, desde tu MacBook. La decisión está en [`docs/decisiones.md`](decisiones.md) (D55), el pedido en [`specs/SPEC_rendimiento_base_grande.md`](../specs/SPEC_rendimiento_base_grande.md) y el uso, en el manual («Empresas → Buscar» y «Configuración → Rendimiento de la base»).

**Qué pasaba.** Después de la carga de 193.553 empresas, la pantalla Empresas daba «Error»: los valores de los filtros tardaban entre 11 y 22 s, la lista 9 s, y después Inicio, Naturalezas y el resto fallaban con `PoolTimeout` a los 30 s.

**Qué cambia:**

| Cambio | Detalle |
| --- | --- |
| Estadísticas al día solas | Al terminar cada carga, deshacer, borrado, .sav, enriquecimiento o sorteo corre un mantenimiento: `ANALYZE` de a una tabla, con la duración en el log. El job diario analiza las tablas que cambiaron más del 10 %. Autovacuum más frecuente en las tablas grandes |
| Disponibilidad guardada | La disponibilidad de cada empresa se guarda en `empresa_disponibilidad` y se recalcula solo para las empresas que cambian. El buscador, Inicio y el armado de muestras ya no la calculan para toda la base. El sorteo la sigue calculando en el momento |
| Lista de Empresas rápida | Total estimado («≈ 193.500», con **Contar exacto**), página siguiente por clave (la página 50 tarda lo mismo que la 1) e índices nuevos |
| Valores y contadores precalculados | Los valores de los filtros, los contadores de Inicio y el uso de las naturalezas se guardan en `resumen_base`, con su fecha visible |
| Nada de PoolTimeout | Cada consulta de la web tiene 15 s como máximo (después, un mensaje claro); el pool espera 10 s y responde «La base está ocupada», y la web reintenta una vez. Pool de la API de 5 a 4 conexiones por instancia, para que entre el job del CDR. Franja «Hay una carga grande en curso (lote N de M)» |
| Medición | Log de los pedidos de más de 2 s y, en Configuración → Rendimiento de la base, las 10 consultas más lentas |
| Migraciones | `0020_rendimiento_base_grande.sql` (tablas, triggers, autovacuum) y `0021_indices_base_grande.sql` (índices con `CREATE INDEX CONCURRENTLY`, que no bloquea la aplicación) |
| Cargas | Cada lote tarda un poco más (medido en local: de 1,2 a 1,5 s por lote de 5.000 filas), por las marcas de disponibilidad y el ANALYZE de cada lote del preview. A cambio, el preview ya no se vuelve 5 veces más lento cuando el autovacuum deja las estadísticas en «tabla vacía» |
| Scheduler | Job nuevo **`empresas-mantenimiento`** cada 10 minutos; el diario `empresas-calidad` también hace el mantenimiento diario |

**Tiempo estimado:** 30 minutos, más el llenado inicial (unos minutos con 200.000 empresas). **Costo:** ninguno adicional. Los índices y las tablas nuevas ocupan del orden de cientos de MB (el disco tiene autoincremento; a US$0,17 por GB al mes son centavos).

## Antes de empezar

**No despliegues con una carga en curso.** Mirá en **Cargas** que ninguna esté en «en proceso», «deshaciendo» o «borrando» con la barra moviéndose. La migración agrega triggers a la tabla de empresas y arma índices sobre 2 millones de filas: con una carga corriendo, espera a que termine.

## Paso a paso

`api` aplica las migraciones antes de publicar la versión nueva (D52). Los índices se arman con `CREATE INDEX CONCURRENTLY`, sentencia por sentencia y fuera de una transacción, así que la aplicación sigue funcionando mientras tanto. El job de migraciones ahora tiene hasta 60 minutos.

```bash
cd ~/base-empresas && git checkout main && git pull
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
```

`programar` crea el job `empresas-mantenimiento` (cada 10 minutos) y vuelve a crear los demás:

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh programar
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Si ya está mergeado el fix de región del script, la variable es `EMPRESAS_REGION=us-central1`. Si se usa IP fija para el CDR, `api` va con `IP_FIJA=1`, como siempre. Para que el job del CDR tome el pool y el límite nuevos, volvé a desplegarlo:

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh cdr
```

Después, recargá la aplicación con **Cmd+Shift+R**.

### El tamaño de los índices

El job de migraciones informa el tamaño de cada índice nuevo. Para verlo:

```bash
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="empresas-migrar"' --project equipos-base-empresas --limit 30 --format 'value(textPayload)'
```

## El llenado inicial

Después de migrar, `empresa_disponibilidad` y `resumen_base` están vacías. Una tarea en segundo plano las llena **de a 5.000 empresas**. Arranca sola con la primera visita a Empresas o Inicio, o con el job de cada 10 minutos. Para arrancarla ya:

```bash
gcloud scheduler jobs run empresas-mantenimiento --location us-central1 --project equipos-base-empresas
```

Mientras se llena:

- arriba de la aplicación aparece la franja **«Preparando la base para búsquedas rápidas: N de M empresas»**;
- Empresas usa el cálculo anterior (lento, pero correcto) y en Inicio «Disponibles» dice **calculando…**;
- **Configuración → Rendimiento de la base** muestra «Disponibilidad guardada: preparándose: N de M».

Con 193.553 empresas en la `db-f1-micro` debería tardar unos minutos. Al terminar, la franja desaparece y la tarjeta dice «lista».

## Verificación

1. **Configuración → Rendimiento de la base:** «Disponibilidad guardada: lista»; los tres resúmenes con fecha; «Estadísticas de la base actualizadas: hace N minutos».
2. **Empresas** abre en menos de 1,5 s y dice «≈ 193.5xx empresas». **Siguiente** varias veces responde igual de rápido. **Contar exacto** da el número justo.
3. Filtrá por departamento y buscá «SRL» o «pérez»: menos de 1,5 s.
4. **Inicio** y **Naturalezas** abren en menos de 1 s y muestran cuándo se actualizaron los números.
5. Durante la próxima carga grande, la franja amarilla dice el lote, y Inicio, Empresas, Cargas y Naturalezas abren (o muestran «La base está ocupada», nunca «Error»). Al terminar, el log del servicio `empresas-tareas` muestra los `ANALYZE` y la tarjeta, las estadísticas recién actualizadas:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="empresas-tareas" AND textPayload:"ANALYZE"' --project equipos-base-empresas --limit 20 --format 'value(timestamp,textPayload)'
```

6. Los pedidos lentos quedan en el log de `empresas-api` con el texto «pedido lento»:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="empresas-api" AND textPayload:"pedido lento"' --project equipos-base-empresas --limit 20 --format 'value(timestamp,textPayload)'
```

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| `api` termina con «La migración falló» | Una carga en curso tenía tomada la tabla, o el job se cortó a mitad de un índice | No se publicó nada. Esperá a que termine la carga y volvé a correr `api`: un índice que quedó a medio armar se borra y se vuelve a crear solo. Si sigue, pasame el error del job `empresas-migrar` |
| La franja «Preparando la base…» no avanza | El job `empresas-mantenimiento` no se creó o la tarea no se despachó | Corré `programar` y después `gcloud scheduler jobs run empresas-mantenimiento …` (arriba). En Configuración → Rendimiento de la base, **Recalcular ahora** también la encola |
| «Las 10 consultas más lentas: no disponible» | La extensión `pg_stat_statements` no está creada en la base | En Cloud SQL Studio, como `postgres`: `CREATE EXTENSION IF NOT EXISTS pg_stat_statements;` |
| Una pantalla dice «La consulta tardó demasiado» sin cargas en curso | Una consulta que todavía no se optimizó | Mirá en la tarjeta cuál es y pasámela. Mientras tanto se puede subir el límite: `gcloud run services update empresas-api --region us-central1 --update-env-vars DB_STATEMENT_TIMEOUT_MS=30000` |
| «La base está ocupada» seguido | Demasiados pedidos a la vez para la `db-f1-micro` | Es el punto en que conviene agrandar la base (`TIER=db-g1-small ./infra/desplegar.sh redimensionar`, unos US$25–30 al mes; ver la sección 9 del spec) |

**Volver atrás:** redirigí el tráfico de `empresas-api` y `empresas-tareas` a la revisión anterior (ver [despliegue.md](despliegue.md), «Actualizaciones»). Las tablas, triggers e índices nuevos pueden quedar: la versión anterior no los usa. Los triggers solo anotan empresas a recalcular en una tabla, así que la versión anterior funciona igual. Si querés sacarlos del todo, avisame y preparo la migración inversa.
