# Despliegue: Brave sin país, errores visibles y búsqueda web con Claude

Este documento lleva a producción los cambios del enriquecimiento en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**, desde tu MacBook. La decisión está en [`docs/decisiones.md`](decisiones.md) (D57), el pedido en [`specs/SPEC_brave_pais_y_errores_visibles.md`](../specs/SPEC_brave_pais_y_errores_visibles.md) y el uso, en el manual («Enriquecer empresas» y «Enriquecimiento (configuración)»).

**Qué cambia:**

| Cambio | Detalle |
| --- | --- |
| Brave con `country=ALL` | Brave no admite `UY` y respondía 422. Ahora se manda `ALL` (la consulta ya dice «Uruguay»); `search_lang=es` sigue y `ui_lang` no se manda |
| El motivo de cada error | Los errores de Places, Brave y Claude traen el detalle que devuelve el proveedor (máximo 300 caracteres, nunca la clave). Un 429 de Brave se reintenta una vez después de 1,1 s y se cobra una sola vez |
| Errores en la pantalla | En la corrida, debajo de cada paso con error, el motivo más frecuente con su cantidad. Empresas con resultado «error» (pestaña «Con error») y el motivo al pasar el mouse |
| Paso 5: búsqueda web con Claude | Último intento para las empresas que siguen sin teléfono. Solo entran los teléfonos que aparecen en la página que Claude cita, con el origen nuevo «Búsqueda web (Claude)» y el enlace a esa página en la ficha. **Viene apagado** |
| Migración `0023_busqueda_web_claude.sql` | Registra el origen `claude_web` y lo agrega al check de proveedor de los pasos. No reescribe datos y tarda segundos |

**Tiempo estimado:** 15 minutos. **Costo del despliegue:** ninguno. El paso 5, solo si lo activás: unos US$0,03 a 0,06 por empresa que llega a él (búsquedas a US$0,01 más tokens).

**Claves:** ninguna nueva. El paso 5 usa la misma clave de Claude (`empresas-anthropic-key`).

## Antes de empezar

**No despliegues con una corrida de enriquecimiento en curso.** Mirá en **Base de datos → Enriquecimiento** que ninguna esté «en curso». La migración cambia el check de la tabla de pasos.

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

1. **Brave ya no da error.** Con la búsqueda web con Claude **apagada**, abrí la ficha de «4 Cabezas SAS» y tocá **✨ Enriquecer** → **Aprobar y enriquecer**. Como la empresa se enriqueció hace menos de 90 días, la estimación la saltea: bajá temporalmente «No volver a enriquecer antes de (días)» a 0 en Configuración → Enriquecimiento (y después volvelo a 90), o probá con otra empresa sin teléfono. El paso Brave Search tiene que quedar en «ok» o «sin resultado», nunca en «error».
2. **El motivo se ve.** Si algún paso da error, debajo de su fila aparece el motivo (por ejemplo, «… respondió 403: …»). No tiene que aparecer ninguna clave.
3. **Medí sin el paso 5.** Enriquecé una muestra de 50 a 100 empresas (desde la muestra, **✨ Enriquecer** → las sin teléfono) y anotá el porcentaje «sin resultado» y el gasto.
4. **Activá el paso 5.** En Configuración → Enriquecimiento, marcá **Búsqueda web con Claude** (búsquedas máximas 3, precio US$0,01) y **Guardar nueva versión**.
5. **Repetí solo sobre las que quedaron sin resultado.** La estimación muestra «Búsqueda web (Claude): hasta US$X». En la corrida, la fila **Búsqueda web (Claude)** dice cuántos teléfonos propuso, cuántos se verificaron y cuántas búsquedas hizo. Abrí la ficha de una empresa con teléfono nuevo: el origen dice «Búsqueda web (Claude)» con el enlace **página fuente**, y el número tiene que estar en esa página.
6. Compará cuántas consiguieron teléfono verificado y a qué costo. Si no conviene, desmarcá el paso 5: la cascada vuelve a ser la de antes.

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| `api` termina con «La migración falló» | Una corrida de enriquecimiento tenía tomada la tabla de pasos | No se publicó nada. Esperá a que termine y volvé a correr `api` |
| Brave sigue en error con «respondió 422: search_lang: …» | Brave dejó de admitir `es` | Pasame el motivo: se saca `search_lang` en `proveedores.py` (constante `BRAVE_IDIOMA`) |
| Brave en error con «respondió 429» | El plan de Brave limita los pedidos por segundo y el reintento también chocó | Volvé a enriquecer esas empresas (pestaña «Con error») más tarde, o subí el plan de Brave |
| Búsqueda web (Claude) en error con «Claude respondió 400: … web_search …» | La organización de Anthropic no tiene habilitada la búsqueda web, o el modelo configurado no la admite | Un administrador de la organización tiene que habilitar la búsqueda web en la consola de Anthropic. Si ya está habilitada, cambiá el modelo de Claude en Configuración |
| Búsqueda web (Claude) propone teléfonos pero no verifica ninguno | Las páginas citadas arman los números con JavaScript, o no responden | Es esperado: se prefiere perder un teléfono a aceptar uno inventado. El detalle del paso dice el motivo de cada descarte |
| La corrida se detiene «por el tope» enseguida | La reserva del paso 5 (unos US$0,04 por empresa) no entra en lo que queda del tope | Subí el tope por corrida o enriquecé menos empresas por vez |

**Volver atrás:** si el problema es el paso 5, alcanza con desmarcar **Búsqueda web con Claude**. Si hace falta volver a la versión anterior, redirigí el tráfico de `empresas-api` y `empresas-tareas` a la revisión anterior (ver [despliegue.md](despliegue.md), «Actualizaciones»). El origen nuevo y el check pueden quedar: la versión anterior no los usa. Ojo: la versión anterior vuelve a mandar `country=uy` y Brave vuelve a dar error.
