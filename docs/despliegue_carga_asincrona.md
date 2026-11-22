# Despliegue: crear la carga sin esperas mudas

Este documento lleva a producción el arreglo de «Siguiente» en la carga, en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**, desde tu MacBook. La decisión está en [`docs/decisiones.md`](decisiones.md) (D51), el pedido en [`specs/SPEC_crear_carga_asincrona.md`](../specs/SPEC_crear_carga_asincrona.md) y el uso, en el manual («Cargas grandes», guía 30).

**Qué pasaba.** Con `acumulaGermanV7.xlsx` (193.556 filas), «Siguiente» no mostraba nada. El archivo se volvía a leer entero al revisar los valores y otra vez al crear la carga, dentro de pedidos que Firebase Hosting corta a los 60 segundos. El navegador recibía un error, pero la API seguía y podía crear la carga igual: un segundo «Siguiente» creaba otra.

**Qué cambia:**

| Cambio | Para qué |
| --- | --- |
| El archivo se lee **una sola vez**, al analizarlo, y sus filas quedan en la tabla `archivo_fila` | Revisar los valores y crear la carga ya no lo vuelven a leer |
| Un archivo de más de 20.000 filas (o de más de 10 MB) se lee **en segundo plano**, con «Leyendo el archivo… N filas» | No depende del corte de 60 segundos |
| «Revisar los valores» y «Crear la carga» responden en menos de un segundo; los lotes los arma el preview, con «Preparando los lotes…» | «Siguiente» muestra el avance enseguida |
| Una clave por paso de mapeo, y el aviso **«Ir a la carga #N»** | «Siguiente» dos veces no crea dos cargas |
| El job diario de calidad libera las filas de los archivos que no se usaron (a las 24 horas) | No ocupar disco de más. No hace falta otro Cloud Scheduler |
| Migración `0016_archivo_fila.sql` | La tabla nueva y las columnas de `archivo` y `carga` |

**Tiempo estimado:** 15 minutos. **Costo:** ninguno. El archivo se parsea una vez en lugar de tres.

## Antes de empezar: la carga que quedó del «Siguiente» mudo

Probablemente ya se creó una carga con el «Siguiente» que no mostró nada: el servidor siguió trabajando después del corte.

1. Abrí **Cargas** y buscá las de `acumulaGermanV7`.
2. Si hay **una** en «analizando» o en «preview», seguí desde ahí después de desplegar.
3. Si hay **más de una**, dejá la más avanzada y borrá las otras con **Borrar carga**.
4. No vuelvas a tocar «Siguiente» con ese archivo hasta desplegar.

Que no haya ninguna carga corriendo (en «analizando» con la barra avanzando, «en proceso», «deshaciendo» o «borrando») mientras desplegás.

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

**No hace falta correr `programar`:** la limpieza de las filas intermedias va en el job diario de calidad, que ya existe.

## Verificación

1. **Cargas → Nueva carga** con `acumulaGermanV7.xlsx`: al tocar **Analizar archivo** aparece «Leyendo el archivo… N filas» y, al terminar, el mapeo.
2. **Siguiente** dice «Revisando los valores…» y después, si no hay valores para traducir, la barra muestra enseguida «Creando la carga…», «Preparando los lotes…» y «Calculando el preview… Lote N de M».
3. En **Cargas** hay una sola carga nueva de ese archivo.
4. El archivo se leyó una sola vez:

   ```bash
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="empresas-api" AND textPayload:"parseado"' --project equipos-base-empresas --freshness=1h --limit 10 --format='table(timestamp,textPayload)'
   ```

   Una línea «archivo N parseado: 193556 filas en … s» por archivo.

5. Ningún 504 en la API:

   ```bash
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="empresas-api" AND httpRequest.status=504' --project equipos-base-empresas --freshness=1h --limit 10
   ```

   No tiene que devolver nada.

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| «Leyendo el archivo…» no avanza y dice «todavía no arrancó» | Cloud Tasks no está pudiendo ejecutar la tarea | Ver «Problemas frecuentes» en [despliegue.md](despliegue.md) |
| La lectura termina con error | El archivo está dañado o no es una planilla | Abrilo en Excel, guardalo de nuevo como .xlsx (o como CSV) y volvé a subirlo |
| «Siguiente» sigue sin mostrar nada | La web vieja quedó en caché o no se desplegó | Cmd+Shift+R; si sigue, correr `./infra/desplegar.sh web` |
| «Archivo inexistente» o un error al crear la carga | Se desplegó la web pero no la API, o falta la migración | Correr `./infra/desplegar.sh api` y `./infra/desplegar.sh migrar` |
| `migrar` falla en `0016_archivo_fila.sql` | Raro: solo agrega una tabla, columnas e índices | Pasame el error del job `empresas-migrar` |

**Volver atrás:** redirigir el tráfico de Cloud Run a la revisión anterior de la API y revertir la web en Firebase Hosting (ver [despliegue.md](despliegue.md), «Actualizaciones»). Antes, terminá o borrá las cargas creadas con esta versión que estén en «analizando», «preview» o «interrumpida»: guardan sus datos en `archivo_fila`, que la versión anterior no lee. La migración 0016 puede quedar.
