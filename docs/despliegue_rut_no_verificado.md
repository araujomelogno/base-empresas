# Despliegue: aceptar RUT de cualquier largo (RUT no verificado)

Este documento lleva a producción la aceptación de identificadores de 6 a 11 dígitos en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**, desde tu MacBook. La decisión está en [`docs/decisiones.md`](decisiones.md) (D54), el pedido en [`specs/SPEC_rut_sin_control_de_largo.md`](../specs/SPEC_rut_sin_control_de_largo.md) y el uso, en el manual («Cargar una base»).

**Qué pasaba.** La carga de `acumulaGermanV7` (Mypes) rechazaba las filas con «RUT con 7 dígitos (se esperan 12)» u «8 dígitos». Suelen ser cédulas de unipersonales.

**Qué cambia:**

| Cambio | Detalle |
| --- | --- |
| Un identificador de **6 a 11 dígitos** se acepta como **RUT no verificado** | Entra a la base definitiva con ese número, sin controlar el registro ni el dígito verificador |
| Un RUT de **12 dígitos** se sigue validando | Si tiene el dígito verificador mal, se rechaza como siempre |
| Con letras, vacío o con más de 12 dígitos | Se rechaza como siempre |
| Interruptor en **Configuración → Cargas grandes** | «Aceptar identificadores de 6 a 11 dígitos sin validar». Viene **activado**; desactivado, vuelve el comportamiento anterior |
| Ficha, buscador y calidad | La ficha muestra «RUT no verificado (N dígitos)», el buscador tiene el filtro «RUT verificado / no verificado» y el tablero de calidad los cuenta aparte |
| Migración `0019_rut_sin_control_de_largo.sql` | `empresa.rut` pasa de `char(12)` a `varchar(12)` (solo dígitos) y se agrega `empresa.rut_verificado`. Los RUT que ya están no cambian |

**Tiempo estimado:** 15 minutos. **Costo:** ninguno.

## Antes de empezar

**No despliegues con una carga en curso.** Mirá en **Cargas** que ninguna esté en «analizando», «en proceso», «deshaciendo» o «borrando» con la barra moviéndose. La migración cambia el tipo de la columna del RUT y, durante unos segundos, bloquea la tabla de empresas.

## Paso a paso

`api` aplica la migración antes de publicar la versión nueva (D52):

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

## Sumar las filas que se rechazaron

La carga ya hecha queda como está. Para incorporar las filas que se rechazaron por el largo, **volvé a cargar el mismo archivo con la misma plantilla**: las empresas que ya entraron cuentan como «sin cambios» y las de 7 u 8 dígitos entran como altas.

## Verificación

1. En la carga nueva, el preview muestra las altas de las filas que antes se rechazaban. En «Rechazos por motivo» ya no aparece «RUT con 7 dígitos».
2. **Empresas → filtro «RUT no verificado» → Buscar**: aparecen esas empresas, con la etiqueta «no verificado».
3. La ficha de una de ellas abre (por ejemplo `#/empresas/4567891`) y muestra «RUT no verificado (7 dígitos)».
4. **Calidad de la base → Validez**: aparece «Empresas con RUT no verificado» con su cantidad.

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| `api` termina con «La migración falló» | La tabla estaba bloqueada por una carga en curso, u otro error | No se publicó nada. Esperá a que termine la carga y volvé a correr `api`. Si sigue, pasame el error del job `empresas-migrar` |
| Las filas cortas se siguen rechazando | El interruptor está desactivado | Configuración → Cargas grandes → marcar «Aceptar identificadores de 6 a 11 dígitos sin validar» → Guardar |
| La ficha de un RUT corto da «no encontrada» | La web vieja quedó en caché | Cmd+Shift+R; si sigue, `./infra/desplegar.sh web` |

**Volver atrás:** desactivá el interruptor en Configuración. Así las cargas vuelven a rechazar los identificadores cortos sin desplegar nada. Para volver a la versión anterior del código, redirigí el tráfico de `empresas-api` y `empresas-tareas` a la revisión anterior (ver [despliegue.md](despliegue.md), «Actualizaciones»). **Antes, borrá las empresas con RUT no verificado** (filtro «RUT no verificado»): la versión anterior no las reconoce.
