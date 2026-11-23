# SPEC — Lotes de carga rápidos: menos consultas por fila y planes de consulta correctos

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_lotes_rapidos.md`, para que Claude Code lo implemente y lo despliegue.
**Base:** `main` en `666cb2a` (PR #22).
**Complementa:** `SPEC_cargas_grandes_por_lotes.md` (D50): el requisito L3 pedía operaciones por lote, y hoy se sigue procesando fila por fila.
**Fecha:** 23/11/2026

---

## 1. Problema

La carga #9 (`acumulaGermanV7.xlsx`, 193.556 filas, 40 lotes de unas 4.800 filas) no termina el lote 1 del preview dentro de los 30 minutos del pedido. Ya se descartaron otras causas:

- **No es memoria.** El archivo se leyó en 64 s con 161 MB y ningún proceso murió.
- **No son bloqueos.** `pg_stat_activity` mostró la sesión del lote en «idle in transaction / ClientRead», sin `pg_blocking_pids`. La base contesta y espera la consulta siguiente.

**Medición en producción** con `pg_stat_statements`, durante 2 minutos del lote 1 (23/11/2026, 07:45):

| Consulta | Llamadas | ms total | ms promedio |
|---|---|---|---|
| `SELECT … FROM empresa_campo_historia h LEFT JOIN carga … WHERE h.empresa_id = $1` (`_CANDIDATOS_SQL`, `empresas.vigentes`) | 495 | 13.870 | **28,0** |
| `INSERT INTO empresa_campo_historia …` | 1.374 | 4.955 | 3,6 |
| `INSERT INTO empresa_atributo …` | 531 | 3.747 | 7,1 |
| `INSERT INTO telefono_vinculo …` | 240 | 1.233 | 5,1 |
| `INSERT INTO telefono …` | 254 | 1.122 | 4,4 |
| `SELECT * FROM empresa WHERE rut = $1` | 124 | 904 | **7,3** |
| `INSERT INTO empresa …` | 124 | 857 | 6,9 |
| `UPDATE empresa SET …` | 30 | 827 | 27,6 |
| … (unas 15 consultas más por fila) | | | |

**Lectura de esos números:**

1. **El ritmo es de 124 empresas en 2 minutos, unas 1 fila por segundo.** Un lote de 4.800 filas tardaría unos 80 minutos, así que no puede terminar en 30. Las 193.556 filas tardarían más de 50 horas.
2. **Son unas 30 consultas por fila.** Cada una es una ida y vuelta a la base: unas 145.000 por lote.
3. **Consultas que deberían tardar menos de 0,5 ms tardan entre 4 y 28 ms.** El caso más claro es `SELECT * FROM empresa WHERE rut = $1`, que usa el índice único de RUT y aun así tarda 7 ms. Hay dos causas, que se suman:
   - **Planes de consulta con estadísticas viejas.** Antes de esta carga, las tablas de empresas estaban vacías: las cargas anteriores se borraron. Para el planificador de Postgres, `empresa` y `empresa_campo_historia` siguen teniendo «0 filas». Con esa estadística elige recorrer la tabla entera (seq scan) en lugar de usar el índice. Dentro de la transacción del lote, la tabla va creciendo con filas que el autoanalyze no ve todavía, así que **cada búsqueda recorre más filas que la anterior**: el lote se vuelve más lento a medida que avanza (crecimiento cuadrático). Además, psycopg prepara las consultas que se repiten, y el plan genérico queda fijo para el resto del lote.
   - **CPU de la base.** La `db-f1-micro` tiene CPU compartida, así que cada operación cuesta más que en un servidor dedicado.
4. **El tiempo en la base es solo el 25 % del total**: unos 31 s de 120 s. El resto son idas y vueltas entre Cloud Run y Cloud SQL, y procesamiento en Python. La cantidad de consultas por fila importa tanto como lo que tarda cada una.

**En una copia local con el mismo código, un lote de 5.000 filas tarda 14 s.** Con una base rápida y local, las mismas 30 consultas por fila no se notan; en producción, sí.

**Comprobación de los recorridos de tabla** (para correr en `psql` mientras corre un lote, antes de implementar):

```sql
SELECT relname, seq_scan, idx_scan, n_live_tup, last_analyze, last_autoanalyze
FROM pg_stat_user_tables
WHERE relname IN ('empresa', 'empresa_campo_historia', 'empresa_atributo', 'telefono', 'telefono_vinculo')
ORDER BY relname;
```

Si `seq_scan` crece de una consulta a otra en `empresa` y `empresa_campo_historia`, la causa de los planes queda confirmada.

## 2. Objetivos

1. **Ritmo:** el preview y la confirmación procesan **al menos 100 filas por segundo** en la instancia actual (`db-f1-micro`), sin agrandarla. Con ese ritmo, las 193.556 filas tardan unos 30 minutos por operación, y cada lote de 5.000 filas menos de 1 minuto.
2. **Consultas por fila:** menos de **0,1 consultas por fila en promedio** (unas pocas consultas por cada tanda de 500 filas), en lugar de las 30 de hoy.
3. **El ritmo no cae a lo largo del lote:** la fila 4.800 se procesa tan rápido como la primera.
4. **El resultado no cambia:** los conteos, la historia, los valores vigentes, los atributos, los teléfonos, los orígenes y los contactos quedan **idénticos** a los del procesamiento actual. Los tests existentes siguen pasando.

## 3. Fuera de alcance

- Agrandar Cloud SQL. Queda como recurso si, después de esto, no se llega a 100 filas por segundo. Ver la sección 7.
- Cambiar las reglas de negocio de la carga.

## 4. Requisitos (P0)

### V1. Planes de consulta correctos (arreglo inmediato)

- **Antes del primer lote** de cada operación (preview, confirmación, deshacer, borrado) se ejecuta `ANALYZE` sobre las tablas que la carga toca: `empresa`, `empresa_campo_historia`, `empresa_atributo`, `telefono`, `telefono_vinculo`, `telefono_vinculo_origen`, `contacto` y `sucursal`.
- **Dentro de la transacción de cada lote:**
  - `SET LOCAL plan_cache_mode = force_custom_plan`, para que psycopg no fije un plan genérico armado con estadísticas viejas;
  - y, como resguardo para las tablas que pueden estar vacías al principio, `SET LOCAL enable_seqscan = off`. Así Postgres usa los índices para las búsquedas por `rut`, `empresa_id`, `e164` y `telefono_id`, aunque las estadísticas digan que la tabla está vacía.
- **Al confirmar,** después de cada N lotes (por defecto 5) se ejecuta `ANALYZE` de esas tablas, fuera de la transacción del lote, para que las estadísticas acompañen el crecimiento.

**Criterios de aceptación:**
- [ ] Con la base vacía, durante un lote, `seq_scan` de `empresa` y de `empresa_campo_historia` **no crece** (se verifica con la consulta de la sección 1).
- [ ] `SELECT * FROM empresa WHERE rut = $1` tarda menos de 1 ms en promedio según `pg_stat_statements`.

### V2. Procesar por tandas, no fila por fila

`cargas.procesar` se reorganiza para trabajar **por tandas de 500 filas** dentro del lote (tamaño configurable). Por cada tanda:

1. **Precarga en pocas consultas:**
   - las empresas existentes por RUT (`WHERE rut = ANY(%s)`);
   - su historia por campo, con la misma lógica de `_CANDIDATOS_SQL` pero `WHERE h.empresa_id = ANY(%s)`;
   - sus atributos vigentes;
   - los teléfonos por `e164 = ANY(%s)` y sus vínculos con las empresas de la tanda;
   - los contactos de esas empresas;
   - los catálogos (atributos, orígenes y naturalezas), una sola vez por lote y no por fila. Hoy se repite, por ejemplo, `SELECT * FROM atributo WHERE clave = ANY($1)`.
2. **Decisión en memoria:** la regla de supervivencia (`ganador`), las altas y actualizaciones, los conflictos, los orígenes y los contactos se calculan en Python con los datos precargados. Se usa la misma función `ganador`, para que el resultado sea idéntico.
3. **Escritura en bloque:**
   - las empresas nuevas, con un `INSERT … SELECT unnest(...) RETURNING id, rut` o `executemany` con `returning`;
   - la historia, los atributos, los vínculos, los orígenes y los teléfonos, con `COPY` o `executemany`;
   - las actualizaciones de valores vigentes, con un `UPDATE … FROM (VALUES …)` por tanda.
4. **Progreso:** se informa por tanda. Así la pantalla avanza de a 500 filas, y no queda en «0 de N» durante minutos como ahora.

**Deshacer y borrado** (`lotes`, `borrado`) aplican la misma idea donde hoy recorren empresa por empresa: recalcular los valores vigentes por tandas con una sola consulta de historia por tanda.

**Criterios de aceptación:**
- [ ] Con un test de equivalencia, las mismas 20.000 filas sintéticas procesadas con el algoritmo actual y con el nuevo dan la **misma** base, comparando tablas completas: empresa, historia, atributos, teléfonos, vínculos, orígenes, contactos, rechazos y conteos. Incluye RUT repetidos, actualizaciones contra datos existentes, conflictos con la sala, teléfonos compartidos, atributos de lista con traducción y contactos.
- [ ] En el test de volumen, el promedio de consultas por fila es menor a 0,1. Se mide con un contador de `execute` en los tests o con `pg_stat_statements`.
- [ ] Todos los tests existentes siguen pasando.

### V3. Medición en el log

- Cada lote registra `filas_por_segundo`, la cantidad de consultas del lote y el tiempo en base contra el tiempo total. Por ejemplo: `carga=9 preview lote=1/40 filas=4812 segundos=38 filas_s=126 consultas=410`.
- Si un lote baja de 20 filas por segundo, se registra un warning con esos datos.

## 5. Verificación en producción

1. Desplegar (sección 6).
2. Crear la carga con el archivo de 193.556 filas.
3. Con `pg_stat_statements_reset()` y la consulta de la sección 1, confirmar que no hay recorridos de tabla y que las consultas promedian menos de 1 ms.
4. En el log, cada lote tiene que mostrar `filas_s` de 100 o más, y el preview completo terminar en menos de 40 minutos.

## 6. Despliegue

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

`api` ya aplica las migraciones y despliega el servicio de tareas (D52). Antes de desplegar, borrar las cargas #8 y #9 con «Borrar carga».

## 7. Costo

**Ninguno adicional.** Se hacen muchas menos consultas, así que la base y Cloud Run trabajan menos tiempo.

Si después de implementarlo no se llega a 100 filas por segundo, la opción siguiente es pasar Cloud SQL a una instancia con CPU dedicada:

- `db-custom-1-3840` (1 vCPU, 3,75 GB): unos **US$50 por mes**, contra los US$9–10 de la `db-f1-micro`, en us-central1;
- `db-g1-small` (CPU compartida, más rápida que la micro): unos **US$25–30 por mes**.

Ninguna se recomienda antes de medir el resultado de V1 y V2.
