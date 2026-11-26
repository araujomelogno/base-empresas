# Despliegue: qué aporta cada coincidencia del descubrimiento

Este documento lleva a producción «Qué aporta» en los lotes de «Buscar empresas nuevas», en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**, desde tu MacBook. La decisión está en [`docs/decisiones.md`](decisiones.md) (D58), el pedido en [`specs/SPEC_descubrimiento_que_aporta.md`](../specs/SPEC_descubrimiento_que_aporta.md) y el uso, en el manual («Buscar empresas nuevas»).

**Qué cambia:**

| Cambio | Detalle |
| --- | --- |
| Columna «Qué aporta» | En el preview de un lote, cada coincidencia dice dato por dato (teléfono, sitio, dirección) si es nuevo, igual, o distinto y reemplazaría al vigente o quedaría solo en la historia (misma regla de supervivencia) |
| «No guardar» por defecto | Una coincidencia que no aporta nada queda en «No guardar» aunque la regla sea exacta |
| Filtro y «Omitir las que no aportan» | Todas · Nuevas · Coinciden y aportan · Coinciden sin aporte · Ya guardadas; el botón pone «No guardar» en todas las que no aportan |
| «Qué se agregó» | Después de confirmar, lo que pasó de verdad en cada empresa, y el aviso suma «K empresas completadas sin cambios» |
| CSV del preview | «Descargar CSV» en el lote, con «Qué aporta» (y «Qué se agregó» si está confirmado) |
| Ficha | El sitio o la dirección que vino de un descubrimiento o de un enriquecimiento enlaza al lote |

**Tiempo estimado:** 10 minutos. **Costo:** ninguno (no hay llamadas nuevas a Google Places). **Migraciones:** ninguna: todo va en el JSON `resultado` del lote.

## Antes de empezar

**Si hay un lote de descubrimiento en «preview» que quieras confirmar, confirmalo o descartalo antes de desplegar.** Un lote en preview armado con la versión anterior se puede confirmar igual después del despliegue, pero no tiene «Qué aporta» (la columna muestra «—») y conserva la selección por defecto de antes. Para verlo con «Qué aporta» hay que volver a buscar, y eso cuesta otra vez las llamadas a Places.

## Paso a paso

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

1. **Base de datos → Buscar empresas nuevas**: hacé una búsqueda de una página de un rubro donde ya tengas empresas (por ejemplo, «imprentas en Montevideo»).
2. En el lote, arriba aparece la tarjeta **coinciden y aportan**, y cada coincidencia tiene la columna **Qué aporta**. Las que dicen «No aporta nada» están en «No guardar».
3. Pasá el mouse por un chip naranja o gris: muestra el valor vigente y, en el gris, por qué no se reemplaza.
4. Probá el filtro y **Omitir las que no aportan**. **Descargar CSV** baja `descubrimiento_N.csv`.
5. Confirmá. La columna pasa a **Qué se agregó** y el aviso dice cuántas se completaron sin cambios. Abrí la ficha de una empresa completada: en «Valores vigentes», el sitio o la dirección nuevos enlazan a «descubrimiento #N».
6. Un lote viejo se sigue viendo, con «—» en «Qué aporta».

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| «Qué aporta» muestra «—» en un lote nuevo | El navegador tiene la versión anterior de la pantalla | Recargá con Cmd+Shift+R |
| «Qué se agregó» no coincide con lo que decía «Qué aporta» | Entre el preview y la confirmación entró un dato nuevo para esa empresa (una carga, la sala) | Es esperado: «Qué se agregó» muestra lo que pasó de verdad |
| Un sitio «ya lo tiene» cambió de forma en la ficha (`http://` → `https://www.`) | Mismo dominio con otro texto: «Completar» lo agrega igual a la historia y, si gana, cambia el texto | Es el mismo sitio. Si molesta, editalo en la ficha |

**Volver atrás:** redirigí el tráfico de `empresas-api` y `empresas-tareas` a la revisión anterior (ver [despliegue.md](despliegue.md), «Actualizaciones»). Los lotes armados con esta versión se siguen viendo y confirmando con la anterior (los datos nuevos del JSON se ignoran).
