# Despliegue: armado de muestras (marco completo, Excel de tamaños y sorteo sistemático)

Este documento lleva a producción los cambios del armado de muestras en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**, desde tu MacBook. La decisión está en [`docs/decisiones.md`](decisiones.md) (D56), el pedido en [`specs/SPEC_muestras_marco_excel_sistematico.md`](../specs/SPEC_muestras_marco_excel_sistematico.md) y el uso, en el manual («Sortear una muestra», «El marco: sorteables y no sorteables», «Excel de tamaños» y «Sorteo sistemático por CIIU»).

**Qué cambia:**

| Cambio | Detalle |
| --- | --- |
| Aviso de espera | «Ver marco disponible», elegir un template y sortear deshabilitan el botón y muestran un aviso con los segundos; un doble clic hace una sola consulta |
| Marco completo | Por estrato: Total · Sorteables · No sorteables, con el motivo. «Descargar no sorteables» baja la lista en CSV |
| Sin «Incluir empresas sin teléfono» | La opción se elimina: las empresas sin teléfono son no sorteables. Solo la regla de Configuración las deja entrar. Las muestras ya sorteadas no cambian |
| Excel de tamaños | En el paso 3, «Descargar Excel» e «Importar Excel» (importar no guarda nada) |
| Sorteo sistemático por CIIU | «Método de sorteo» en el paso 3. El reemplazo de cada titular es su vecino en la lista («Vecino de …») y se puede liberar uno puntual |
| Migración `0022_muestras_sistematico.sql` | Columnas nuevas y nulas: `marco_snapshot_item.ciiu`, `marco_snapshot.ciiu_congelado` y `muestra_item.reemplaza_a`. No reescribe datos y tarda segundos |

**Tiempo estimado:** 15 minutos. **Costo:** ninguno.

## Antes de empezar

**No despliegues con un sorteo o una carga en curso.** Mirá en **Cargas** que ninguna esté en «en proceso», «deshaciendo» o «borrando», y avisá al equipo que no sortee durante esos minutos. La migración agrega columnas a las tablas de muestras.

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

## Verificación

1. **Nueva muestra → Ver marco disponible:** aparece el aviso «Recuperando el marco disponible…» y el botón queda gris hasta que llega. El resumen dice Cumplen filtros · Sorteables · No sorteables.
2. En el paso 3, la tabla tiene **Total · Sorteables · No sorteables**; pasando el mouse por un número de No sorteables se ve el motivo.
3. **Descargar Excel**, cambiá algunos titulares y **Importar Excel**: el recuadro dice «Se importaron N estratos…» y los valores aparecen en la tabla.
4. Con **Método de sorteo: Sistemático por CIIU**, sorteá una muestra de prueba. En **Empresas de la muestra → Reemplazos**, cada uno dice «Vecino de …». **Verificar reproducibilidad** da «Reproducible ✓».
5. **Verificar reproducibilidad** de una muestra vieja sigue dando «Reproducible ✓».
6. Borrá la muestra de prueba si no la vas a usar (detalle de la muestra → **Borrar muestra**).

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| `api` termina con «La migración falló» | Un sorteo o una carga tenía tomada la tabla | No se publicó nada. Esperá a que termine y volvé a correr `api` |
| Un template avisa «La opción "Incluir empresas sin teléfono" ya no existe» | El template tenía la opción vieja | Es esperado. Guardá el template de nuevo para que el aviso no vuelva |
| «Ver marco disponible» dice «La consulta tardó demasiado» | Un marco muy grande, o una carga en curso (D55) | Probá de nuevo en unos minutos. Si pasa seguido sin cargas, pasame qué filtros y estratos usabas |
| El Excel se abre con «¿Alcanza?» vacío | El programa no recalculó al abrir | En Excel: Fórmulas → Calcular ahora; en LibreOffice: Datos → Calcular → Recalcular |

**Volver atrás:** redirigí el tráfico de `empresas-api` y `empresas-tareas` a la revisión anterior (ver [despliegue.md](despliegue.md), «Actualizaciones»). Las columnas nuevas pueden quedar: la versión anterior no las usa. Las muestras sorteadas con el método sistemático se verifican solo con la versión nueva.
