# Despliegue: cargas grandes por lotes

Este documento lleva a producción las cargas por lotes en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**, desde tu MacBook. La decisión está en [`docs/decisiones.md`](decisiones.md) (D50), el pedido en [`specs/SPEC_cargas_grandes_por_lotes.md`](../specs/SPEC_cargas_grandes_por_lotes.md) y el uso, en el manual («Cargas grandes»).

**Qué pasaba.** La confirmación de la carga #7 (190.000 filas) corrió en una sola transacción. A los 30 minutos la cortó el plazo de Cloud Run y Cloud Tasks, y Postgres revirtió todo: no quedó nada aplicado.

**Qué cambia:**

| Cambio | Para qué |
| --- | --- |
| El preview, la confirmación, «Deshacer» y «Borrar» corren **por lotes** de 5.000 filas, cada uno en su transacción | Ningún paso se acerca al límite de 30 minutos |
| El archivo se lee una sola vez y sus filas quedan en la tabla `carga_fila` hasta que la carga termina | Cada lote lee solo sus filas |
| Estado **«interrumpida»** con **Reanudar**, **Deshacer** y **Borrar** | Si algo se corta, no se pierde lo aplicado ni hay que tocar la base |
| Una carga pesada a la vez; las demás esperan en cola | La base no se satura y la web sigue respondiendo |
| Configuración → **Cargas grandes**: filas por lote, pausa entre lotes y minutos para dar una carga por cortada | Ajustarlo sin tocar código |
| El job diario de calidad marca como interrumpidas las cargas trabadas | Aunque nadie abra la pantalla |
| Migración `0015_cargas_por_lotes.sql` | Tablas `carga_fila`, `carga_lote` y `carga_trabajo`, estados nuevos y algunos índices |

**Tiempo estimado:** 20 minutos, más la carga de prueba. **Costo:** ninguno. La base sigue siendo la misma.

## Antes de empezar

- **Que no haya ninguna carga corriendo.** En **Cargas**, ninguna debe estar «analizando» ni «en proceso», salvo la #7, que está trabada. Un despliegue corta lo que esté corriendo.
- **La carga #7** quedó «en proceso» o «error», sin datos aplicados, porque se revirtió todo. Se borra **después** de desplegar (ver abajo), porque así el borrado ya corre por pasos.

## Paso a paso

Los cuatro pasos son obligatorios y van en este orden:

```bash
cd ~/base-empresas && git checkout main && git pull
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh migrar
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Si ya está mergeado el fix de región del script, la variable es `EMPRESAS_REGION=us-central1`. Si se usa IP fija para el CDR, `api` va con `IP_FIJA=1`, como siempre. Después, recargá la aplicación con **Cmd+Shift+R**.

No hace falta tocar Cloud Tasks, Cloud Scheduler ni el plazo de Cloud Run: cada lote es una tarea nueva de la misma cola.

## Borrar la carga #7 y volver a cargarla

1. **Cargas → #7 → Borrar carga** (administrador). El modal dice qué tarea se cancela; escribí BORRAR. La barra muestra los pasos del borrado. Al terminar, la carga desaparece de la lista.
2. **Primero una prueba de unas 20.000 filas.** Armá un archivo con las primeras 20.000 filas de la base y cargalo con la misma plantilla. Revisá que:
   - la barra diga «Lote N de 4 · X de 20.000 filas»;
   - el preview termine y diga cuánto tardó;
   - al confirmar, el detalle llegue a «4 de 4 lotes aplicados (20.000 filas)» y la carga quede «confirmada»;
   - mientras corre, la ficha de una empresa y Atributos respondan normalmente.

   Si querés, deshacela después (**Deshacer carga**) para cargar la base completa sin duplicar la fuente.
3. **La base completa (190.000 filas).** Volvé a crear la carga con el archivo y la plantilla de la #7, revisá el preview (38 lotes) y confirmá. Se puede seguir usando la aplicación mientras corre.

## Verificación

1. Los logs muestran una línea por lote, con su duración:

   ```bash
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="empresas-api" AND textPayload:"carga="' --project equipos-base-empresas --freshness=2h --limit 50 --format='table(timestamp,textPayload)'
   ```

   Cada lote de 5.000 filas debería tardar pocos minutos. Una línea con **ALARMA** quiere decir que un lote superó los 10 minutos: avisame.

2. Ninguna llamada de la web falla por falta de conexiones mientras corre la carga:

   ```bash
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="empresas-api" AND textPayload:"PoolTimeout"' --project equipos-base-empresas --freshness=2h --limit 10
   ```

   No tiene que devolver nada.

3. **Configuración → Cargas grandes** muestra 5.000 filas por lote, 1 s de pausa y 35 minutos.

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| La carga quedó «interrumpida» | Falló un lote, o se reinició el servidor (por ejemplo, por un despliegue) | Abrí el detalle: dice el error del lote. **Reanudar** sigue desde ahí sin repetir nada. Si el error se repite, pasame el mensaje |
| «Esperando a que termine la carga #N» y no arranca | La otra carga quedó trabada | Abrí la carga #N: la pantalla la marca «interrumpida» si no avanza hace más de 35 minutos, y la de la cola arranca sola |
| La barra no avanza y dice «todavía no arrancó» | Cloud Tasks no está pudiendo ejecutar la tarea | Ver «Problemas frecuentes» en [despliegue.md](despliegue.md) |
| Los lotes tardan más de 10 minutos | La base está muy cargada | Avisame. Para las cargas siguientes se puede bajar **Filas por lote** a 2.000 en Configuración → Cargas grandes (los lotes de una carga ya creada no cambian) |
| `migrar` falla en `0015_cargas_por_lotes.sql` | Raro: la migración solo agrega tablas, columnas e índices | Pasame el error del job `empresas-migrar` |

**Volver atrás:** redirigir el tráfico de Cloud Run a la revisión anterior de la API y revertir la web en Firebase Hosting (ver [despliegue.md](despliegue.md), «Actualizaciones»). La migración 0015 puede quedar: la versión anterior no usa las tablas nuevas. Antes, terminá o borrá las cargas que estén por lotes, porque la versión anterior no conoce los estados «interrumpida», «deshaciendo» ni «borrando».
