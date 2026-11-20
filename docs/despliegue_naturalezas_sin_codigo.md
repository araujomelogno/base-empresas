# Despliegue: arreglo de «Failed to fetch» al borrar naturalezas jurídicas

Este documento lleva a producción el arreglo del borrado y la edición de naturalezas jurídicas en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**, desde tu MacBook. La decisión está en [`docs/decisiones.md`](decisiones.md) (D49, punto 5) y el uso, en el manual (guía 17).

**Qué pasaba.** En producción hay una naturaleza con el **código vacío**: la dejó el alta anterior, que no validaba el código. La pantalla armaba la dirección del borrado con el código, así que iba a `/api/naturalezas/`. La API respondía con una redirección (307) a la dirección directa de Cloud Run y el navegador la cortaba: «Failed to fetch». Los logs lo muestran así:

```
STATUS  REQUEST_URL
307     https://empresas-api-…run.app/api/naturalezas/
```

**Qué cambia:**

| Cambio | Para qué |
| --- | --- |
| Editar y borrar usan el id interno de la naturaleza, no el código | Funcionan aunque el código esté vacío o tenga caracteres raros |
| Una naturaleza **sin uso** puede corregir su código | Para arreglar la que quedó sin código, en lugar de borrarla |
| La lista marca **sin código** en rojo | Para encontrarla |
| Migración `0014_naturaleza_codigo.sql`: la base rechaza códigos vacíos de acá en adelante | Que no vuelva a pasar. No toca las filas que ya existen |

**Tiempo estimado:** 15 minutos. **Costo:** ninguno.

## Paso a paso

Los tres pasos son obligatorios y van en este orden:

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

## Arreglar la naturaleza sin código

En **Administración → Naturalezas jurídicas**, la fila sin código aparece con la marca roja **sin código**. Si ninguna empresa la tiene:

- **Editar** → escribí un código (por ejemplo, las iniciales del nombre) → **Guardar**. Si estaba excluida, sigue excluida con el código nuevo; o
- **Borrar**, si no la necesitás.

## Verificación

1. Borrar una naturaleza sin uso responde «… borrada» y la fila desaparece.
2. Los logs ya no muestran el 307; el DELETE va a `/api/naturalezas/<número>` y responde 200:

   ```bash
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="empresas-api" AND httpRequest.requestMethod="DELETE"' --project equipos-base-empresas --freshness=1h --limit 5 --format='table(timestamp,httpRequest.status,httpRequest.requestUrl)'
   ```

3. **+ Naturaleza** sin código avisa «Completá el código y el nombre».

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| Sigue el «Failed to fetch» | La web vieja quedó en caché o no se desplegó | Cmd+Shift+R; si sigue, correr `./infra/desplegar.sh web` |
| «No existe esa naturaleza» al editar o borrar | Se desplegó la web pero no la API | Correr `./infra/desplegar.sh api` |
| `migrar` falla en `0014_naturaleza_codigo.sql` | Muy raro: la regla es `NOT VALID` y no revisa las filas viejas | Pasame el error del job `empresas-migrar` |

**Volver atrás:** redirigir el tráfico de Cloud Run a la revisión anterior de la API y revertir la web en Firebase Hosting (ver [despliegue.md](despliegue.md), «Actualizaciones»). La regla de la migración 0014 puede quedar: solo impide códigos vacíos.
