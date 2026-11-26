# SPEC — Armado de muestras: aviso de espera, Excel de tamaños, marco completo y sorteo sistemático por CIIU

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_muestras_marco_excel_sistematico.md`, para que Claude Code lo implemente y lo despliegue.
**Base:** `main` en `e523914` (PR #25, D55).
**Reemplaza en parte:** `SPEC_templates_sorteo_sin_telefono_formatos_csv.md`, requisito R3 («Incluir empresas sin teléfono discable»): esa opción se elimina (R3 de este documento).
**Fecha:** 25/11/2026
**Decisiones de Germán Araújo (brainstorming del 24–25/11):**
- Se elimina la opción «Incluir empresas sin teléfono discable». Las empresas sin teléfono aparecen en el marco como **no sorteables** y nunca se sortean.
- En el sorteo sistemático, el reemplazo de cada titular es **el vecino en la lista**.
- La lista se ordena por **CIIU completo**.

---

## 1. Problema

1. **Sin aviso de espera.** Con la base grande (≈193.000 empresas), «Ver marco disponible» y elegir un template tardan varios segundos. El botón queda activo y no hay ninguna señal de que algo está pasando: el usuario vuelve a hacer clic y dispara consultas repetidas.
2. **Tamaños a mano.** En «3 · Tamaño por estrato y reemplazos» hay que tipear titulares y reemplazos estrato por estrato. Con muchos estratos (por ejemplo, departamento × tamaño) es lento y propenso a errores, y la distribución suele calcularse antes en una planilla.
3. **El marco oculta empresas.** `previsualizar_marco` devuelve por estrato solo las empresas sorteables. Las que quedan afuera (sin teléfono, «calientes» por enfriamiento o muestra activa, origen no elegido, etc.) se ven solo como un total general de «Excluidas». No se sabe cuántas empresas tiene realmente cada estrato ni por qué se pierden.
4. **Un solo método de sorteo.** Hoy el sorteo es aleatorio simple dentro de cada estrato (orden `sha256(semilla:empresa_id)`). No hay forma de asegurar que la muestra recorra todo el abanico de actividades dentro de un estrato.

## 2. Objetivos

1. Ninguna consulta del armado se puede disparar dos veces por doble clic, y el usuario siempre ve que se está consultando.
2. Los tamaños de una muestra con 50 o más estratos se cargan con un Excel en menos de 2 minutos, sin tipear en la pantalla.
3. Para cada estrato se ve el total de empresas, cuántas son sorteables y cuántas no, con el motivo.
4. El jefe de campo puede elegir sorteo **aleatorio simple** o **sistemático por CIIU**, y ambos son reproducibles con «Verificar reproducibilidad».

## 3. Fuera de alcance

- **Otras variables de orden para el sistemático** (tamaño, departamento, etc.). Solo CIIU completo. El diseño deja lugar para agregarlas (P2).
- **Asignación automática de tamaños** (proporcional, Neyman). El Excel permite calcularlos afuera.
- **Sortear empresas no sorteables.** Ninguna opción permite incluir sin teléfono o bloqueadas.
- **Cambiar muestras ya sorteadas.** Las muestras activas o cerradas no se tocan y se siguen verificando como hoy.

## 4. Historias de usuario

- Como **jefe de campo**, quiero que el botón se deshabilite y aparezca un aviso mientras se consulta el marco, para no lanzar la consulta dos veces ni pensar que se colgó.
- Como **jefe de campo**, quiero bajar los estratos a un Excel, completar titulares y reemplazos con fórmulas y subirlo, para no tipear cientos de números.
- Como **jefe de campo**, quiero saber, por estrato, cuántas empresas no puedo sortear y por qué, para decidir si cambio filtros o estratos.
- Como **jefe de campo**, quiero un sorteo sistemático ordenado por CIIU, para que cada estrato quede representado en todas sus actividades.
- Como **auditor**, quiero que «Verificar reproducibilidad» funcione igual con los dos métodos.

## 5. Requisitos (P0)

### R1. Aviso de espera en el armado

Se aplica a toda acción que consulta el marco o lo recalcula:

- «Ver marco disponible» (asistente «Nueva muestra», detalle de una muestra en borrador y edición de template);
- elegir un template en «Partir de un template» (`#m-template`);
- «Sortear».

Comportamiento:

- Al hacer clic, el botón (o el selector de template) **se deshabilita** y muestra un spinner hasta que llega la respuesta o un error.
- Se abre un **modal** que bloquea el asistente: «Recuperando el marco disponible…» (o «Aplicando el template…», «Sorteando…»), con un contador de segundos.
- A los 20 segundos el modal agrega: «La base es grande; puede tardar hasta 2 minutos». No tiene botón de cancelar.
- Al terminar, se cierra el modal y se rehabilita el control. Si falla, el modal muestra el mensaje de error del servidor (incluidos los 503 de `SPEC_rendimiento_base_grande`, P-5) con un botón «Cerrar», y el control se rehabilita.
- Mientras el modal está abierto no se puede disparar otra consulta del armado. Si el usuario cambia un filtro, el resultado anterior se marca como desactualizado («Volvé a consultar el marco») y no se reemplaza solo.
- Se implementa como un componente reutilizable en `web/public/js/ui.js` (por ejemplo, `conEspera(boton, texto, promesa)`).

**Criterios de aceptación:**
- [ ] Un doble clic en «Ver marco disponible» genera **un solo** `POST /muestras/marco` (verificable en la pestaña Red del navegador).
- [ ] Elegir un template muestra el modal hasta que los pasos 1 a 3 quedan cargados.
- [ ] Con un error del servidor, el modal muestra el mensaje y el botón vuelve a quedar activo.

### R2. Excel de «3 · Tamaño por estrato y reemplazos»

**Descarga.** En el paso 3 aparece «Descargar Excel», disponible después de «Ver marco disponible». El servidor arma el archivo con los criterios del asistente (aunque la muestra todavía no exista) y los tamaños cargados en ese momento:

- Endpoint: `POST /muestras/marco/tamanos.xlsx` con `{criterios, tamanos}`. Usa el mismo cálculo que `previsualizar_marco` (R3) y `openpyxl`, que ya está en `requirements.txt`.
- Nombre: `tamanos_<estudio>_<muestra o "nueva">_<aaaammdd>.xlsx`.

Hoja **«Tamaños»**, una fila por estrato, en el orden de la pantalla (`crit.orden_natural`):

| Columna | Editable | Contenido |
|---|---|---|
| Estrato | No | Etiqueta exacta del estrato (clave del import) |
| Total en el marco | No | Todas las empresas del estrato (R3) |
| Sorteables | No | Las que pueden salir sorteadas |
| No sorteables | No | Total − Sorteables |
| Titulares | **Sí** | Valor actual (vacío si no hay) |
| Reemplazos | **Sí** | Valor actual (vacío si no hay) |
| ¿Alcanza? | No | Fórmula: «Sí» si Titulares + Reemplazos ≤ Sorteables; «Faltan N» si no |

- Una fila de **totales** al final, con fórmulas.
- La hoja queda **protegida sin contraseña**, con desbloqueadas solo las columnas Titulares y Reemplazos. Así se evita romper la columna Estrato sin bloquear al usuario que sabe desprotegerla.
- Hoja **«Instrucciones»**: qué se puede editar, que no se agregan ni se renombran estratos, y los criterios resumidos (filtros, estratificación, método de sorteo, fecha del marco).
- Hoja oculta **«_meta»**: `estudio_id`, `muestra_id` (o vacío), versión del formato y un hash de los criterios de filtro y estratificación.

**Importación.** «Importar Excel» en el mismo paso:

- Endpoint: `POST /muestras/tamanos/importar` (multipart, con los criterios actuales). **No guarda nada**: devuelve `{tamanos, avisos, errores}` y la pantalla vuelca los valores en la tabla del paso 3. Se guardan con el botón habitual.
- Se lee la hoja «Tamaños» por **nombre de columna** (Estrato, Titulares, Reemplazos), no por posición.
- Reglas:

| Caso | Resultado |
|---|---|
| Estrato del Excel que no existe en el marco actual | Se ignora, con aviso: «El estrato X no está en el marco» |
| Estrato del marco que no está en el Excel | Queda con el valor que tenía en pantalla, con aviso |
| Celda vacía | Se toma como 0 |
| Valor negativo, con decimales o texto | Error en esa fila: no se importa esa fila, el resto sí |
| Titulares + Reemplazos > Sorteables | Se importa igual, con aviso «no alcanza» (como hoy al tipear) |
| Hash de `_meta` distinto al de los criterios actuales | Aviso: «El Excel se armó con otros filtros o estratos; revisá los estratos» |
| Archivo sin la hoja «Tamaños» o sin la columna Estrato | Se rechaza el archivo con un mensaje claro |

- El resultado se muestra en un recuadro: «Se importaron N estratos · M avisos · K errores», con la lista desplegable.
- Disponible en el asistente, en una muestra en **borrador** y en la edición de **templates**. En una muestra sorteada solo se puede **descargar** (lectura).

**Criterios de aceptación:**
- [ ] Descargar, cambiar titulares y reemplazos de 50 estratos y subir el archivo deja esos 50 valores en la tabla, sin guardar hasta que el usuario guarda.
- [ ] Un Excel con un estrato renombrado lo ignora con aviso y no modifica los demás.
- [ ] Una fila con «-3» o «2,5» da error solo en esa fila.
- [ ] El archivo se abre en Excel y LibreOffice con la protección activa y las fórmulas calculadas.

### R3. Marco completo: todas las empresas, sorteo solo sobre las sorteables

**Previsualización (`previsualizar_marco`).** El cálculo de estratos se hace sobre **todo el universo** (empresas que cumplen los filtros), no solo sobre las sorteables:

- La respuesta agrega, por estrato: `total`, `sorteables`, `no_sorteables` y `motivos` (`{regla: cantidad}`, con las mismas claves que `exclusiones`: `sin_telefono_discable`, `enfriamiento`, `muestra_activa`, origen no elegido, etc.). Una empresa con más de un motivo cuenta en cada motivo, pero una sola vez en `no_sorteables`.
- `disponibles` pasa a ser sinónimo de `sorteables`, para no romper la pantalla actual mientras se migra.
- **Pantalla:** el resumen muestra Universo · Sorteables · No sorteables. La tabla por estrato tiene las columnas **Total · Sorteables · No sorteables**; al pasar el mouse o desplegar la fila se ve el detalle por motivo. Los tamaños pedidos se comparan contra **Sorteables**.
- Se puede exportar a CSV la lista de empresas no sorteables del marco, con su estrato y su motivo (botón «Descargar no sorteables»), para que el jefe pueda, por ejemplo, mandarlas a enriquecer.

**Sorteo (`sortear`).** No cambia lo que entra al sorteo: el snapshot (`marco_snapshot_item`) y el sorteo usan **solo las sorteables**. `resultado` agrega por estrato `total` y `no_sorteables` para el informe de la muestra.

**Eliminar «Incluir empresas sin teléfono discable»:**

- Se saca el checkbox `#m-sintel` del asistente y su texto de ayuda, y la columna «Sin teléfono» condicionada a esa opción.
- `_sin_telefono_permitido` deja de aplicarse en `previsualizar_marco` y en `sortear`. `_validar_criterios` descarta `incluir_sin_telefono` y, si venía en `true`, agrega el aviso: «La opción "Incluir empresas sin teléfono" ya no existe: las empresas sin teléfono no se sortean».
- **Templates** que la tenían: al aplicarlos, se descarta con ese aviso. Al guardar el template, se elimina del JSON.
- **Muestras en borrador** que la tenían: el aviso aparece en el detalle; al sortear, se ignora.
- **Muestras ya sorteadas** con esa opción: no se tocan. «Verificar reproducibilidad» trabaja sobre el snapshot congelado, así que no se afecta. El detalle sigue mostrando «Entraron N empresas sin teléfono discable» en esas muestras.
- La regla de Configuración «Excluir empresas sin teléfono discable» (`reglas_disponibilidad.sin_telefono_discable`) **se mantiene** y es la única que decide si una empresa sin teléfono es sorteable.

**Criterios de aceptación:**
- [ ] En un estrato con 100 empresas, 20 sin teléfono y 5 en enfriamiento (1 con ambas cosas), la tabla muestra Total 100 · Sorteables 76 · No sorteables 24, y el detalle muestra sin teléfono 20 y enfriamiento 5.
- [ ] La suma de Sorteables por estrato es igual al `marco` actual y la suma de Total, al `universo`.
- [ ] Un sorteo nunca incluye una empresa no sorteable (test con el escenario anterior).
- [ ] Aplicar un template con `incluir_sin_telefono: true` muestra el aviso y el sorteo no incluye empresas sin teléfono.
- [ ] «Verificar reproducibilidad» de una muestra vieja con `incluir_sin_telefono` sigue dando «reproducible».

### R4. Sorteo sistemático por CIIU

**Selección del método.** En el paso 3 se agrega «Método de sorteo»: **Aleatorio simple** (por defecto, como hoy) o **Sistemático por CIIU**, con un texto de ayuda de una línea. Se guarda en `criterios.metodo` (`"aleatorio"` | `"sistematico_ciiu"`; si falta, `"aleatorio"`), en la muestra y en los templates. El resumen legible de criterios (`sorteo.js`) lo muestra.

**Algoritmo** (independiente en cada estrato; función pura `sortear_sistematico` junto a `sortear_snapshot`, que pasa a despachar según el método). Para un estrato con `N` empresas sorteables, `n` titulares y `r` reemplazos:

1. **Orden.** Se ordena la lista por `ciiu` completo (texto, ascendente). Las empresas sin CIIU van al final. Los empates (mismo CIIU) se ordenan por `clave_orden(semilla, empresa_id)`, igual que hoy. El orden es reproducible.
2. **Si `n ≥ N`,** todas son titulares y no hay reemplazos (aviso «no alcanza», como hoy).
3. **Arranque e intervalo, con aritmética entera** (sin flotantes, para que sea idéntico en cualquier máquina): el intervalo es `k = N / n` (puede ser fraccionario). Se toma `a = int(sha256(f"{semilla}:{estrato}:arranque"), 16) mod N`, que equivale a un arranque aleatorio en `[0, k)`. La posición del titular `i` (`i = 0 … n−1`) es `p_i = floor((a + i·N) / n)`. Las posiciones son distintas y están dentro de `[0, N)`.
4. **Reemplazos: vecino en la lista.** El reemplazo de un titular es la siguiente empresa de la lista (posición `p_i + 1`, circular: después de la última viene la primera) que no sea titular ni reemplazo ya asignado. Si `r > n`, se da una segunda vuelta: el siguiente vecino libre de cada titular, y así.
5. **Orden de los reemplazos.** Para que liberar «los próximos M reemplazos» de un estrato no favorezca los CIIU bajos, los reemplazos se numeran según un orden aleatorio de sus titulares: `clave_orden(semilla, titular_id)`. Con `r < n`, solo tienen reemplazo los primeros `r` titulares de ese orden.
6. **Un solo grupo económico** (`una_por_grupo`, B4): si la empresa de una posición pertenece a un grupo ya usado, se toma la siguiente de la lista que no esté elegida y cuyo grupo no esté usado. Como hoy, primero se completan los titulares de todos los estratos y después los reemplazos.
7. **Salida:** el mismo formato que hoy, `[(empresa_id, estrato, rol, orden)]`. Titulares con `orden` 1…n en el orden de la lista; reemplazos con `orden` n+1…n+r según el paso 5.

**Vínculo titular–reemplazo.** Columna nueva `muestra_item.reemplaza_a` (empresa_id del titular, nula en titulares y en el método aleatorio). En el detalle de la muestra y en la lista de ítems, cada reemplazo muestra «Vecino de <razón social del titular>». La liberación de reemplazos sigue siendo **por estrato y en orden**, como hoy.

**Snapshot y verificación.**

- Columna nueva `marco_snapshot_item.ciiu` (texto, nullable). Se llena **en todos los sorteos nuevos**, con los dos métodos, con el CIIU que tenía la empresa al sortear.
- `verificar` usa el método guardado en `criterios` y el CIIU congelado del snapshot. Si el método es sistemático y el snapshot no tiene CIIU (no debería pasar), el resultado es `no_verificable`.
- Los items borrados (`muestra_item_borrado`) se tratan igual que hoy.

**Validación:** con el método sistemático y `n = 0`, no se aceptan reemplazos en ese estrato (error en `_validar_criterios`: «Con sorteo sistemático, un estrato sin titulares no puede tener reemplazos»).

**Criterios de aceptación:**
- [ ] Test con `N = 10`, `n = 3`, `r = 3` y una semilla fija: las posiciones son `floor((a + i·10)/3)` y cada reemplazo es la posición siguiente libre.
- [ ] Test con `N = 7`, `n = 5`, `r = 2` (k < 2): ningún reemplazo es también titular.
- [ ] La misma semilla y el mismo snapshot dan el mismo resultado en dos corridas (`verificar` devuelve `reproducible`).
- [ ] Con 1.000 empresas en 10 CIIU de 100 cada uno, `n = 50`: cada CIIU recibe exactamente 5 titulares.
- [ ] Con `una_por_grupo`, nunca hay dos empresas del mismo grupo y no se pierde la cuota de titulares si hay empresas disponibles.
- [ ] El método aleatorio da exactamente el mismo resultado que hoy para la misma semilla (test de no regresión con muestras existentes).
- [ ] Un template con método sistemático, al aplicarse, deja el método elegido en el paso 3.

## 6. Requisitos P1 (si entra en la misma entrega)

- **Liberar el reemplazo de un titular puntual:** desde la lista de ítems, sobre un titular, «Liberar su reemplazo», que libera el vecino asignado (`reemplaza_a`). Hoy se libera por estrato y en orden.
- **En el Excel, una columna «Tamaño proporcional sugerido»** (sorteables del estrato / sorteables totales × total pedido), como ayuda, no editable.

## 7. Consideraciones futuras (P2)

- Otras variables de orden para el sistemático (CIIU a 2 dígitos, tamaño, departamento, o varias encadenadas). Por eso `criterios.metodo` se guarda junto a un `criterios.orden_sistematico = ["ciiu"]` opcional, aunque hoy solo admita ese valor.
- Asignación automática de tamaños (proporcional o Neyman) dentro de la pantalla.

## 8. Métricas de éxito

- **Inmediatas:** cero consultas duplicadas de `/muestras/marco` en los logs de una semana (hoy aparecen pares con segundos de diferencia). Al menos una muestra armada con el Excel y una con el método sistemático en el primer mes.
- **Calidad:** todas las muestras sistemáticas pasan «Verificar reproducibilidad».

## 9. Preguntas abiertas

- **(Germán, no bloqueante)** Fase 2 de enriquecimiento: hoy se puede enriquecer «las empresas de la muestra sin teléfono discable». Sin la opción de incluirlas, esas empresas ya no entran a una muestra. La salida prevista es el CSV de «no sorteables» del marco (R3). ¿Hace falta, además, un botón «Enriquecer las sin teléfono de este marco»? Si se quiere, va en una spec aparte.
- **(Ingeniería, no bloqueante)** Si calcular las etiquetas de estrato sobre todo el universo (y no solo sobre las sorteables) supera los 15 s en la base grande, se puede contar por estrato en SQL con la disponibilidad guardada (`empresa_disponibilidad`, D55). Se mide antes de optimizar.

## 10. Documentación

- `docs/decisiones.md`: nueva decisión (D56) con los tres puntos de Germán y el algoritmo sistemático.
- Manual, sección del armado de muestras: aviso de espera, Excel, columnas Total/Sorteables/No sorteables, método de sorteo y «vecino de».
- `docs/despliegue_muestras_sistematico.md` con los pasos de la sección 11.

## 11. Despliegue

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

`api` aplica la migración antes de publicar la versión (columnas `marco_snapshot_item.ciiu` y `muestra_item.reemplaza_a`, ambas nullable, sin reescribir datos). **No desplegar con un sorteo o una carga en curso.**

## 12. Costo

**Ninguno adicional.** No hay servicios nuevos. El Excel se arma en el servicio `empresas-api` existente (pocos KB por estrato), y el cálculo por estrato sobre todo el universo usa la disponibilidad ya guardada (D55).

## 13. Referencia metodológica

El sistemático con orden por una variable de control equivale a una estratificación implícita: la muestra se reparte en proporción a cada CIIU dentro del estrato. Es el método `METHOD=SYS` con `CONTROL=` de PROC SURVEYSELECT (SAS), con intervalo fraccionario y arranque aleatorio, y lo usan los institutos de estadística en sus encuestas a empresas.
