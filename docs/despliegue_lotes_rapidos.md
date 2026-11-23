# Despliegue: lotes de carga rápidos

Este documento lleva a producción los lotes de carga rápidos en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**, desde tu MacBook. La decisión está en [`docs/decisiones.md`](decisiones.md) (D53) y el pedido, en [`specs/SPEC_lotes_rapidos.md`](../specs/SPEC_lotes_rapidos.md).

**Qué pasaba.** La carga #9 (193.556 filas) procesaba **1 fila por segundo**: el lote 1 no terminaba en los 30 minutos del pedido. Había dos causas:

- **Unas 30 consultas por fila,** cada una con su ida y vuelta entre Cloud Run y Cloud SQL.
- **Planes de consulta armados con estadísticas de tablas vacías,** que recorrían la tabla entera en lugar de usar el índice.

**Qué cambia:**

| Cambio | Para qué |
| --- | --- |
| Cada lote se procesa por **tandas de 500 filas**: unas pocas consultas traen todo lo necesario, la decisión (supervivencia, altas, actualizaciones, conflictos, teléfonos, orígenes) se toma en memoria con la misma regla, y se escribe en bloque | De unas 30 consultas por fila a menos de 0,1 |
| `ANALYZE` antes del primer lote y cada 5 lotes, y dentro del lote, planes con las estadísticas actuales y siempre por índice | Que ninguna búsqueda recorra la tabla entera |
| Deshacer y borrar recalculan las empresas por tandas | Lo mismo, al deshacer o borrar una carga grande |
| El log muestra el ritmo de cada lote: `filas_s`, consultas y tiempo en la base | Ver enseguida si se cumple la meta de 100 filas por segundo |
| Migración `0018_lotes_rapidos.sql` | Guarda las consultas de cada lote |

**Los resultados no cambian.** Un test procesa el mismo escenario con el algoritmo anterior y con el nuevo, y compara la base entera: empresas, historia, atributos, teléfonos, vínculos, orígenes, sucursales, contactos, rechazos y conteos.

Algunas filas siguen yendo de a una, con el algoritmo anterior: filas sin RUT válido, empresas fusionadas o anuladas, reglas de fusión además del RUT para empresas nuevas, y contactos con teléfono. Son pocas y, con los planes correctos, cada consulta tarda poco.

**Tiempo estimado:** 15 minutos, más la carga. **Costo:** ninguno. Se hacen muchas menos consultas, así que la base y Cloud Run trabajan menos tiempo.

## Antes de empezar

Borrá las cargas **#8** y **#9** con **Borrar carga**. Fijate que no quede ninguna otra carga en «analizando» o «en proceso» con la barra moviéndose.

## Paso a paso

`api` ya aplica la migración (0018) y despliega el servicio de tareas (D52):

```bash
cd ~/base-empresas && git checkout main && git pull
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Si ya está mergeado el fix de región del script, la variable es `EMPRESAS_REGION=us-central1`. Si se usa IP fija para el CDR, `api` va con `IP_FIJA=1`, como siempre. Después, recargá la aplicación con **Cmd+Shift+R**.

## Verificación

1. **Creá la carga** con `acumulaGermanV7.xlsx` y la misma plantilla. La barra avanza de a 500 filas.

2. **El ritmo de cada lote.** La meta es `filas_s` de 100 o más, y que el preview completo termine en menos de 40 minutos:

   ```bash
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="empresas-tareas" AND textPayload:"filas_s="' --project equipos-base-empresas --freshness=2h --limit 50 --format='table(timestamp,textPayload)'
   ```

   Cada línea dice `filas=… segundos=… filas_s=… consultas=… base_s=…`. Un lote de 5.000 filas tendría que hacer unas pocas centenas de consultas. Una línea con **ALARMA** significa que el lote bajó de 20 filas por segundo: pasame esas líneas.

3. **(Opcional) Las consultas en la base.** Mientras corre un lote, en `psql` (o en Cloud SQL Studio):

   ```sql
   SELECT relname, seq_scan, idx_scan, n_live_tup, last_analyze, last_autoanalyze
   FROM pg_stat_user_tables
   WHERE relname IN ('empresa', 'empresa_campo_historia', 'empresa_atributo', 'telefono', 'telefono_vinculo')
   ORDER BY relname;
   ```

   Corrila dos veces, con un minuto de diferencia: `seq_scan` de `empresa` y de `empresa_campo_historia` no tiene que crecer.

   Si `pg_stat_statements` está activo (como en la medición del 23/11), podés reiniciar las estadísticas con `SELECT pg_stat_statements_reset();` y, al rato, mirar las consultas más pesadas:

   ```sql
   SELECT calls, round(mean_exec_time::numeric, 2) AS ms_promedio, left(query, 80) AS consulta
   FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 15;
   ```

   Tienen que ser pocas llamadas, una por tanda y no una por fila, y en promedio de pocos milisegundos.

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| `filas_s` por debajo de 100 en todos los lotes | La CPU compartida de la `db-f1-micro` | Pasame las líneas `filas_s=` del log. El paso siguiente es una instancia más grande de Cloud SQL (ver D53), con su costo |
| Algunos lotes lentos y otros rápidos | Lotes con muchas filas poco comunes (contactos con teléfono, empresas sin RUT, reglas de fusión por teléfono o nombre) | Es esperable. Si molesta, pasame el log |
| Un error en la carga que antes no pasaba | Una diferencia del motor nuevo con el anterior | Como resguardo, se puede volver al algoritmo anterior sin desplegar código: `gcloud run services update empresas-tareas --region us-central1 --project equipos-base-empresas --update-env-vars CARGAS_POR_FILA=1`. Pasame el error |

**Volver atrás:** redirigir el tráfico de `empresas-api` y de `empresas-tareas` a la revisión anterior (ver [despliegue.md](despliegue.md), «Actualizaciones»). La migración 0018 puede quedar.
