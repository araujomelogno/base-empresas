# SPEC — Robustez de las cargas por lotes: memoria, tareas que mueren y migraciones al desplegar

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, proyecto GCP `equipos-base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_cargas_lotes_robustez.md`, para que Claude Code lo implemente y lo despliegue.
**Base:** `main` en `5b75eaa` (PR #21).
**Complementa:** `SPEC_cargas_grandes_por_lotes.md` (D50) y `SPEC_crear_carga_asincrona.md` (D51).
**Fecha:** 22/11/2026
**Origen:** la carga #8 (`acumulaGermanV7.xlsx`, 193.556 filas, 40 lotes) quedó «interrumpida» con 0 de 40 lotes de preview. Se analizaron los logs de Cloud Run del 22/11/2026.

---

## 1. Problema

Línea de tiempo según los logs, en hora UTC (Montevideo es UTC−3):

| Hora | Revisión | Qué pasó |
|---|---|---|
| 20:18 | `00018` (PR #20, lotes) | Se despliega la versión con lotes. |
| 20:21 | `00018` | `GET /api/cargas` falla 4 veces: **`UndefinedColumn: column c.tarea_id does not exist`** en `lotes.revisar_trabadas()`. **El código nuevo quedó en producción antes que su migración** (0015). |
| 20:28 → 20:31 | `00018` | Se analiza el archivo y se crea la carga #8 (`POST /cargas`, 200). En esta versión, `crear` parsea el .xlsx entero en un worker y copia las 193.556 filas. |
| 21:01:56 | instancia `d6bfe` | Termina un paso de la tarea 25 (el armado de los lotes). |
| **21:12 → 21:17** | instancia `d6bfe` | **Un worker de uvicorn muere y el que lo reemplaza muere cada 6–7 segundos, unas 40 veces seguidas** («Child process [N] died»). El otro worker, que corría el lote 1 del preview, sigue vivo. |
| 21:17:01 | instancia `d6bfe` | Cloud Run apaga la instancia (SIGTERM). **Muere el worker que corría el lote 1.** |
| 22:18 | nueva instancia | `revisar_trabadas` marca la carga #8 como interrumpida: «no avanzó en más de 35 minutos». **No hay ninguna línea `carga=8 preview lote=…`**: ningún lote llegó a terminar. |

**Causas:**

1. **Memoria.** La API corre con `--memory 1Gi` y **2 workers** (`Dockerfile`: `uvicorn --workers 2`).
   - Parsear un .xlsx de casi 200.000 filas deja a un worker con cientos de MB ocupados. Python no devuelve esa memoria al sistema.
   - Si el otro worker procesa un lote al mismo tiempo, la instancia queda al borde del límite. Cada worker nuevo es eliminado apenas arranca: el patrón de «died» cada 6–7 segundos es el típico del OOM killer del kernel dentro del contenedor.
   - Es la explicación más probable, pero no está confirmada: Cloud Run no registró un «Memory limit exceeded», porque mataron procesos hijos y no el contenedor entero.
2. **Una tarea cuyo proceso muere queda «corriendo» para siempre.**
   - `tareas.ejecutar` solo toma tareas en estado `pendiente` o `error`. Si Cloud Tasks reintenta, la tarea ya figura `corriendo` y el reintento no hace nada.
   - Recién a los **35 minutos** sin avance la carga pasa a «interrumpida», y hay que apretar «Reanudar» a mano.
   - Con lotes que duran pocos minutos, 35 minutos de espera no tienen sentido.
3. **Desplegar la API antes de migrar rompe la aplicación.** `desplegar.sh api` publica el código nuevo y `migrar` es un paso aparte. Si se corren en ese orden, o si se olvida `migrar`, la API falla con errores 500 hasta que se aplica la migración.
4. **La versión de PR #21 no está en producción.** La última revisión es la `00018`, de PR #20, y PR #21 se mergeó después. Por eso `crear` todavía parsea el archivo dentro del pedido.

## 2. Objetivos

1. La carga de 193.556 filas termina el preview y la confirmación sin que muera ningún proceso. **Ningún «Child process died»** durante una carga.
2. Si igual muere un proceso o se reinicia una instancia, **la carga sigue sola** en menos de 5 minutos, sin intervención humana y sin repetir lotes ya hechos.
3. **Nunca hay código en producción sin su migración aplicada.**

## 3. Fuera de alcance

- Cambiar la lógica de negocio de la carga (mapeo, reglas, conteos).
- Agrandar Cloud SQL.

## 4. Requisitos (P0)

### R1. Memoria acotada durante las cargas

- **Lectura en streaming.** El .xlsx se lee con openpyxl en modo `read_only` (o el CSV con un lector por líneas) y las filas se guardan en `archivo_fila` en tandas de 5.000. **Nunca se tienen las 200.000 filas en memoria a la vez**: hoy `lectores.leer_tabla` devuelve la lista completa.
  - Esto aplica a la lectura de PR #21 («archivo.leer») y a cualquier otro lugar que hoy llame a `_leer` o a `leer_tabla` sobre el archivo completo.
  - Ejemplos: `asegurar_filas`, `valores`, y el remapeo y la ingesta del .sav si comparten el lector.
- **Procesos aislados.** Las tareas pesadas (lectura del archivo, lotes de preview, confirmación, deshacer y borrado) corren en **un solo proceso por instancia**. Para eso hay que elegir una de estas dos opciones y dejarla en la decisión D52:
  - **Opción a, recomendada:** un **servicio de Cloud Run aparte para tareas** (`empresas-tareas`), con 1 worker, concurrencia 1 y 2 GiB. Cloud Tasks apunta a ese servicio. La API de la web sigue con 2 workers y 1 GiB, así que la web no se ve afectada por una carga pesada.
  - **Opción b:** dejar un solo servicio, pero con **1 worker** y **2 GiB**.
- **Medición.** Cada lote registra en el log la memoria del proceso (RSS) al empezar y al terminar: `carga=8 preview lote=1/40 filas=4.8xx segundos=… rss_mb=…`. Si supera el 75 % del límite, deja un warning.
- **Liberar memoria.** Después de cada tanda grande, se descartan las listas y se llama a `gc.collect()`.

**Criterios de aceptación:**
- [ ] Con un .xlsx sintético de 200.000 filas, la memoria del proceso nunca supera los 600 MB durante la lectura ni durante un lote. Hay un test o script de medición en `docs/build`.
- [ ] Durante una carga de 200.000 filas no aparece ningún «Child process … died» en los logs.
- [ ] La web responde normalmente mientras corre la carga.

### R2. Las tareas que mueren se retoman solas

- **Latido.** Mientras corre una tarea, un hilo actualiza `tarea.actualizado` cada **30 segundos**. Así una tarea viva nunca parece trabada, aunque un lote largo tarde en informar progreso.
- **Retomar en lugar de ignorar.** `tareas.ejecutar` también toma una tarea en estado `corriendo` si su `actualizado` tiene más de **3 minutos**: el proceso que la corría murió. La marca como `corriendo` con un nuevo dueño y sigue desde el lote que no se terminó (los lotes terminados están en `carga_lote`). Cloud Tasks reintenta solo cuando el pedido muere, así que esto alcanza para retomar sin intervención.
- **Reintentos de Cloud Tasks.** La cola `empresas-tareas` tiene que reintentar las tareas que fallan por conexión cortada o por un 5xx, por ejemplo hasta 5 veces con backoff de 30 s a 5 min. Hay que verificar la configuración de la cola en `desplegar.sh` y documentarla.
- **Respaldo.** `revisar_trabadas` baja el umbral de 35 a **10 minutos** (configurable). Antes de marcar la carga como «interrumpida», **la reencola una vez sola** (reanudación automática). Solo si falla de nuevo queda «interrumpida» para que una persona decida.
- **Despliegues.** Al recibir SIGTERM (despliegue o cierre de la instancia), el worker deja de tomar lotes nuevos, termina o revierte el lote en curso y libera la tarea con un `actualizado` viejo. Así otra instancia la retoma enseguida.

**Criterios de aceptación:**
- [ ] Si se mata a mano el proceso que corre el lote 3 de 10 (test con `kill -9` en un entorno de prueba, o simulado), el lote 3 se reintenta solo y la carga termina sin intervención, con los mismos conteos que sin corte.
- [ ] Desplegar mientras corre una carga no la deja interrumpida: sigue en la revisión nueva.
- [ ] Una tarea viva con un lote de 8 minutos no se marca como trabada.

### R3. Nunca código sin su migración

- **`desplegar.sh api` corre `migrar` antes de pasar el tráfico a la revisión nueva:**
  1. construye la imagen;
  2. ejecuta el job `empresas-migrar` con esa imagen;
  3. si la migración falla, **no despliega** y lo dice;
  4. si sale bien, despliega la API.

  Las migraciones ya se escriben compatibles hacia atrás, así que la versión anterior sigue funcionando con la base migrada mientras dura el despliegue.
- **Al arrancar, la API compara** las migraciones del código con las aplicadas (`public.empresas_migraciones`). Si falta alguna:
  - escribe un error claro en el log: «Faltan migraciones: 0015, 0016. Corré `desplegar.sh migrar`»;
  - `GET /api/me` devuelve un aviso que la web muestra a los administradores en una franja roja, en lugar de errores 500 sueltos.
- `docs/despliegue.md` se actualiza: `api` ya incluye la migración, y `migrar` solo hace falta por separado en casos especiales.

**Criterios de aceptación:**
- [ ] `desplegar.sh api` con una migración nueva la aplica y recién después publica la revisión.
- [ ] Si se despliega a mano una imagen con una migración sin aplicar, los administradores ven la franja con las migraciones que faltan, y el log lo dice al arrancar.

### R4. Progreso visible del primer lote

- En el detalle de la carga, mientras corre un lote, se muestran el número de fila que va procesando y el tiempo transcurrido: «Lote 1 de 40 · fila 2.300 de 4.812 · 1 min 40 s».
- Si un lote supera **10 minutos**, aparece el aviso: «Este lote está tardando más de lo normal; si no avanza en 3 minutos, el sistema lo retoma solo».

## 5. Despliegue

Este cambio modifica cómo se despliega. La primera vez, con el `desplegar.sh` actual, el orden es: **primero `migrar`, después `api`**.

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh migrar
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Si se elige la opción a de R1, `desplegar.sh` agrega un paso para el servicio de tareas (por ejemplo, `./infra/desplegar.sh tareas`) y lo incluye en `todo`. Si ya está mergeado el fix de región, se usa `EMPRESAS_REGION=us-central1`.

Después: «Reanudar» la carga #8, o borrarla y crearla de nuevo, y verificar en el log que los lotes avanzan con `rss_mb` bajo.

## 6. Costo

- **Memoria a 2 GiB, solo mientras corren tareas.** Cloud Run cobra la memoria por segundo de uso, y con `min-instances 0` no cuesta nada sin uso. Un GiB extra durante 2 horas de carga son unos 7.200 GiB-segundo. Eso queda dentro del nivel gratuito mensual de Cloud Run (360.000 GiB-segundo). Por encima, son centavos de dólar por carga.
- **Servicio de tareas aparte (opción a):** sin costo fijo, por la misma razón (escala a cero).
- **Cloud Tasks y el latido:** algunas operaciones más por carga, dentro del millón gratuito por mes.
- **Total esperado: US$0 adicionales** con el volumen actual.

## 7. Qué hacer ya, sin esperar la implementación

1. **Desplegar PR #21 en el orden correcto** (primero `migrar`, después `api`, después `web`).
2. **Subir la memoria de la API a 2 GiB** como medida provisoria:

   ```bash
   gcloud run services update empresas-api --memory 2Gi --region us-central1 --project equipos-base-empresas
   ```

   El próximo `desplegar.sh api` la vuelve a dejar en 1 GiB, salvo que se cambie `--memory` en el script (parte de R1).
3. **Reanudar la carga #8.** Si en 10 minutos no aparece «Lote 1 de 40», borrarla y crearla de nuevo.
