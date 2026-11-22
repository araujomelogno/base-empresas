# Despliegue: robustez de las cargas por lotes

Este documento lleva a producción la robustez de las cargas por lotes en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**, desde tu MacBook. La decisión está en [`docs/decisiones.md`](decisiones.md) (D52), el pedido en [`specs/SPEC_cargas_lotes_robustez.md`](../specs/SPEC_cargas_lotes_robustez.md) y el uso, en el manual («Cargas grandes», guía 30).

**Qué pasaba.** La carga #8 (`acumulaGermanV7.xlsx`, 193.556 filas) quedó «interrumpida» sin ningún lote hecho:

- Un proceso de la API se murió unas 40 veces seguidas, casi seguro por falta de memoria: había 2 procesos en 1 GiB y uno tenía el Excel entero en memoria.
- Al apagarse la instancia murió el proceso que corría el lote 1.
- La tarea quedó «corriendo» sin que nadie la retomara durante 35 minutos.
- Además, la versión con lotes se publicó antes que su migración, y la API dio errores hasta que se aplicó.

**Qué cambia:**

| Cambio | Para qué |
| --- | --- |
| El archivo se lee de a una fila y se guarda sin armar la lista entera | Leer 200.000 filas usa unos 100 MB, no cientos |
| Servicio de Cloud Run nuevo, **`empresas-tareas`**: 1 proceso, una tarea a la vez, 2 GiB. Cloud Tasks le manda las tareas pesadas | Una carga grande no deja sin memoria a la web, que sigue en `empresas-api` |
| Cada tarea «late» cada 30 s; si su proceso muere, el reintento de Cloud Tasks la **retoma sola** a los 3 minutos, desde el lote que faltaba | Sin «Reanudar» a mano |
| La cola reintenta hasta 5 veces (de 30 s a 5 min) | Lo anterior funciona aunque el pedido se corte |
| Si una tarea no avanza en **10 minutos** (antes 35), se vuelve a encolar sola una vez; si se corta de nuevo, queda «interrumpida» | Respaldo |
| Un despliegue en medio de una carga devuelve el lote en curso a la cola | La carga sigue en la versión nueva, sin quedar interrumpida |
| **`desplegar.sh api` aplica las migraciones antes de publicar** la versión nueva, y no publica si fallan | Nunca más código sin su migración |
| Si igual falta una migración, el log lo dice al arrancar y los administradores ven una **franja roja** | Se ve enseguida, sin errores 500 sueltos |
| La pantalla muestra «Lote 1 de 40 · fila 2.300 de 4.812 · 1 min 40 s» y avisa si un lote pasa de 10 minutos | Saber que avanza |
| Migración `0017_tareas_robustas.sql` | Columnas de la tarea para el latido y la reanudación |

Este despliegue incluye también el PR anterior (#21, «Siguiente» sin esperas), que todavía no estaba en producción.

**Tiempo estimado:** 25 minutos, más la carga. **Costo:** US$0 con el volumen actual. Los dos servicios escalan a cero: los 2 GiB de `empresas-tareas` se cobran solo mientras corre una tarea, y una carga de dos horas queda dentro del nivel gratuito de Cloud Run.

## Antes de empezar

- **Que no haya ninguna carga avanzando.** La #8 está «interrumpida»: no importa. Si hay otra en «analizando» o «en proceso» con la barra moviéndose, esperá a que termine.
- **No hace falta subir la memoria de `empresas-api` a mano** (la medida provisoria del pedido): con este cambio las cargas ya no corren ahí.

## Paso a paso

Con el script nuevo, **`api` ya aplica las migraciones** (0016 y 0017) antes de publicar. No hace falta correr `migrar` aparte.

```bash
cd ~/base-empresas && git checkout main && git pull
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

`api` hace, en orden:

1. construye la imagen;
2. corre el job `empresas-migrar` con esa imagen. Si falla, se detiene con «✖ La migración falló: NO se desplegó la versión nueva»;
3. ajusta los reintentos de la cola `empresas-tareas`;
4. crea o actualiza el servicio **`empresas-tareas`**;
5. actualiza `empresas-api`, que desde ahí le manda las tareas.

Si ya está mergeado el fix de región del script, la variable es `EMPRESAS_REGION=us-central1`. Si se usa IP fija para el CDR, `api` va con `IP_FIJA=1`, como siempre. Después, recargá la aplicación con **Cmd+Shift+R**.

## Retomar la carga #8

Abrí **Cargas → #8 → Reanudar**. El preview sigue desde el lote 1 en el servicio de tareas. En unos minutos tiene que aparecer «Lote 1 de 40 · fila … de …».

Si en 10 minutos no aparece, borrala con **Borrar carga** y volvé a crearla con el mismo archivo y la misma plantilla.

## Verificación

1. Los dos servicios están arriba:

   ```bash
   gcloud run services list --project equipos-base-empresas --region us-central1
   ```

   Tienen que aparecer `empresas-api` y `empresas-tareas`.

2. Los lotes avanzan con poca memoria. Cada línea dice cuánto usó el proceso (`rss_mb=antes→después`, en MB):

   ```bash
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="empresas-tareas" AND textPayload:"carga="' --project equipos-base-empresas --freshness=2h --limit 50 --format='table(timestamp,textPayload)'
   ```

   Lo normal es unos cientos de MB. Si ves un warning «más del 75 % del límite», avisame.

3. No murió ningún proceso durante la carga:

   ```bash
   gcloud logging read 'resource.type="cloud_run_revision" AND textPayload:"died"' --project equipos-base-empresas --freshness=6h --limit 10
   ```

   No tiene que devolver nada.

4. La web responde normalmente mientras corre la carga: la ficha de una empresa, Atributos y Actividad.

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| `api` termina con «La migración falló» | Error en una migración | No se publicó nada; sigue la versión anterior. Pasame el error del job `empresas-migrar` (Cloud Run → Jobs → empresas-migrar → Ejecuciones) |
| Franja roja «Faltan migraciones: …» arriba de la aplicación | Se publicó una imagen sin su migración (por ejemplo, a mano) | `PROYECTO=equipos-base-empresas ./infra/desplegar.sh migrar` |
| La barra dice «todavía no arrancó» | Cloud Tasks no llega a `empresas-tareas` | Revisá que `empresas-api` tenga `TAREAS_URL` con la URL de `empresas-tareas` (Cloud Run → empresas-api → Revisiones → Variables). Si no, corré `./infra/desplegar.sh tareas` |
| «Este lote está tardando más de lo normal» | Un lote lento o un proceso que murió | Esperá: si no avanza en 3 minutos, se retoma solo. Si la carga queda «interrumpida», tocá Reanudar y pasame las líneas `carga=` del log |
| Errores 503 de `/api/tareas/…/ejecutar` en el log | Normal: Cloud Tasks reintentó una tarea que seguía viva en otro proceso | Nada |

**Volver atrás:** redirigir el tráfico de `empresas-api` a la revisión anterior (ver [despliegue.md](despliegue.md), «Actualizaciones») y quitarle la variable `TAREAS_URL`, para que las tareas vuelvan a correr en la API:

```bash
gcloud run services update empresas-api --region us-central1 --project equipos-base-empresas --remove-env-vars TAREAS_URL
```

El servicio `empresas-tareas` puede quedar: sin tareas, no cuesta nada. Las migraciones 0016 y 0017 también pueden quedar.
