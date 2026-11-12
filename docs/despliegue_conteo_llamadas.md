# Despliegue: conteo de llamadas del CDR y empresas llamadas

Este documento lleva a producción el cambio de [`specs/SPEC_conteo_llamadas_cdr_y_rendimiento_por_origen.md`](../specs/SPEC_conteo_llamadas_cdr_y_rendimiento_por_origen.md) en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**. Para una instalación desde cero alcanza con la [guía de despliegue](despliegue.md).

**Qué cambia para las personas:**

- **Corridas del job del CDR** (Actividad):
  - **Llamadas** es la cantidad de llamadas hechas, igual que en el dashboard de productividad: los tramos de una llamada cuentan una vez, sin las llamadas a anexos internos y sin filtro de campaña.
  - Columnas nuevas: **A empresas**, **Teléfonos** y **Empresas**.
  - **Ver detalle** muestra el embudo de la corrida y **Exportar empresas** abre la lista.
- **Rendimiento por origen**:
  - Cuenta todas las llamadas a empresas de la base, estén o no en una muestra.
  - Con un estudio o una muestra elegidos, filtra por empresa, así que cuenta también la llamada hecha antes del campo o la que quedó en Conciliación.
  - Columnas «Teléfonos llamados», «Llamadas» y «Empresas llamadas»; cada número de llamadas o de empresas abre la lista.
- **Empresas llamadas**:
  - Una lista de empresas con sus teléfonos y su origen, llamadas, atendidas, fechas, encuestadores y muestra.
  - Se descarga en CSV, y cada descarga queda en Auditoría.
  - La ven el administrador, el coordinador y el jefe.

**Tiempo estimado:** 15 a 20 minutos. **Costo:** ninguno adicional.

## Paso a paso

Los cuatro pasos son obligatorios y van en este orden. `cdr` hace falta porque el conteo nuevo vive en el job; `migrar`, porque crea la tabla que guarda las llamadas a empresas de cada corrida.

```bash
cd ~/base-empresas && git checkout main && git pull
```

```bash
export REGION=us-central1
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh migrar
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh cdr
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Si se usa IP fija para el CDR, `api` y `cdr` van con `IP_FIJA=1`, como siempre. Después, recargá la aplicación con **Cmd+Shift+R**.

`migrar` aplica `db/empresas/0009_conteo_llamadas.sql`, que es compatible hacia atrás:

- Crea `cdr_corrida_intento`, con las llamadas a empresas de cada corrida, nuevas o ya registradas.
- Agrega índices en `intento.lote_id` y `cdr_lote.corrida_id`.

## Después del despliegue

Las corridas anteriores muestran «—» en las columnas nuevas. Para recalcular una:

1. En **Configuración → CDR**, usá **Reprocesar desde** con las fechas de esa corrida (por ejemplo, la de las 51 llamadas a empresas) y tocá **Reprocesar**.
2. En **Actividad → Corridas del job del CDR**, la corrida nueva tiene que mostrar **A empresas = 51**. **Ver detalle** muestra «0 nuevas, 51 ya registradas».
3. En **Rendimiento por origen**, con **Desde** y **Hasta** en ese período, la fila **Total** de **Llamadas** tiene que incluir esas 51 y coincidir con «Llamadas a empresas» del tablero.
4. **Exportar empresas** en esa corrida, y **Descargar CSV**: el archivo abre en Excel con tildes, y el total de llamadas de arriba de la lista es 51.
5. En **Auditoría** figura `actividad.exportar_empresas`.

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| Las corridas nuevas siguen mostrando «—» | El job sigue con la imagen anterior | Correr el paso `cdr` (o `api`, que también actualiza la imagen del job) |
| «Exportar empresas» de una corrida anterior trae pocas empresas | Las corridas anteriores solo conocen los intentos nuevos de sus lotes | Reprocesar ese período: la corrida nueva tiene todas sus llamadas a empresas |
| La suma de «Llamadas» de la lista es mayor que el total de arriba | Una llamada a un número compartido por varias empresas aparece en la fila de cada una | Es esperado; el total de arriba cuenta cada llamada una vez |
| El rol de lectura no ve el botón «Empresas llamadas» | La lista es para administrador, coordinador y jefe | Es esperado |

**Volver atrás:** redirigir el tráfico de Cloud Run a la revisión anterior de la API, volver a desplegar el job con esa imagen y revertir la web en Firebase Hosting (ver [despliegue.md](despliegue.md), "Actualizaciones"). La migración 0009 puede quedar aplicada.
