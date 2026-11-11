# SPEC — Borrar estudios y muestras, borrar cargas en cualquier estado y verificación de reproducibilidad con borrados

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, proyecto GCP `equipos-base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_borrado_estudios_muestras_y_cargas_en_curso.md`, para que Claude Code lo implemente y lo despliegue.
**Depende de:** rama `feat/borrar-empresas-y-cargas` (commit `3ba63f9`: borrado de empresas y cargas, migración 0007, D36). **Hay que mergearla en `main` antes de empezar.** Este spec la extiende.
**Fecha:** 11/11/2026

---

## 1. Problema

1. **No se pueden borrar estudios ni muestras.** Las pruebas de sorteo quedan para siempre. Además, una muestra «activa» sigue bloqueando a sus empresas (regla de disponibilidad `muestra_activa`) y no hay forma de liberarlas salvo cerrándola.
2. **No se pueden borrar cargas trabadas.** «Borrar carga» se oculta en la web y la API responde 409 cuando la carga está «analizando» o «en proceso»:
   - La web oculta el botón si `enCurso` (en `web/public/js/vistas/cargas.js`).
   - `borrado.pedir_borrado_carga` rechaza si hay una tarea «corriendo» de menos de 30 minutos.

   Una carga puede quedar así para siempre: su tarea quedó «pendiente» porque Cloud Tasks no la ejecutó (pasó con el bug de la URL sin `/api`), o quedó «corriendo» porque se reinició la instancia de Cloud Run. Ninguna de las dos se recupera sola.
3. **«Verificar reproducibilidad» da «¡El re-sorteo no coincide!» después de borrar empresas.** El borrado de la rama anterior elimina las filas de la empresa en `marco_snapshot_item` y en `muestra_item`. `muestras.verificar` vuelve a sortear sobre un marco al que le faltan empresas, entra la siguiente en orden, y el resultado ya no se puede distinguir de una alteración real de la muestra.

## 2. Decisiones ya tomadas (Germán Araújo, 11/11/2026)

| Tema | Decisión |
|---|---|
| Lo que el campo dejó en la base al borrar una muestra o un estudio | **Se conserva.** Se borran la muestra, sus ítems, sus intentos del CDR y sus filas del .sav. No se tocan los contactos y teléfonos nuevos, la calidad de los números, la historia de valores ni el último contacto efectivo (enfriamiento). |
| Cargas «analizando» o «en proceso» | **Cancelar y borrar.** Se pueden borrar siempre: si la tarea sigue corriendo, se cancela sin aplicar nada; si quedó trabada, se borra directo. |
| Quién borra estudios y muestras | **Solo el administrador**, igual que empresas y cargas. |
| Arreglo de «Verificar reproducibilidad» | **Va en este mismo spec.** |
| Heredado de D36 | Borrado definitivo, sin papelera, con confirmación escrita y registro en Auditoría. La auditoría nunca se borra. |

## 3. Objetivos

1. Un administrador elimina un estudio de prueba completo (partes, muestras, ingestas .sav y actividad de campo) desde su pantalla, sin tocar la base a mano.
2. Ninguna carga queda imposible de borrar, cualquiera sea su estado.
3. Después de borrar empresas, «Verificar reproducibilidad» sigue dando una respuesta correcta y explicable.
4. Cada borrado queda en Auditoría con quién, qué y cuánto.

## 4. Fuera de alcance

- **Borrar una parte suelta de un estudio.** Se borra el estudio entero o una muestra. Queda como P2.
- **Revertir en la base lo aprendido por el campo.** Es una decisión explícita: se conserva.
- **Papelera o restauración.** Igual que D36.
- **Borrar intentos del CDR sin ítem asociado** (llamadas que no cruzaron con ninguna muestra). No pertenecen a ningún estudio y quedan como están.
- **Cancelar tareas desde una pantalla de tareas.** Solo se cancelan como parte de un borrado.

## 5. Historias de usuario

- Como **administrador**, quiero borrar una muestra de prueba para que sus empresas vuelvan a estar disponibles y la lista de muestras quede limpia.
- Como **administrador**, quiero borrar un estudio entero con sus muestras y sus .sav para sacar pruebas o estudios cargados por error.
- Como **administrador**, quiero borrar una carga que quedó «analizando» o «en proceso», aunque su tarea no termine nunca.
- Como **administrador**, si borro una carga mientras su tarea está corriendo de verdad, quiero que la tarea se detenga sin aplicar nada a la base.
- Como **jefe de estudio**, después de que se borraron empresas de mi muestra, quiero que la verificación me diga que el sorteo es reproducible y cuántas empresas se borraron después, en lugar de una alarma falsa.
- Como **jefe de estudio**, si la muestra fue alterada de verdad, quiero que la verificación siga diciendo «No coincide».
- Como **coordinador o jefe**, no quiero ver los botones de borrar.

## 6. Requisitos

### P0 — Imprescindibles

#### E1. Borrar muestra (administrador)

**Dónde:** botón **«Borrar muestra»** (rojo) en el detalle de la muestra, visible solo para admin y en cualquier estado (borrador, activa o cerrada).

**Confirmación:** un modal informa cuántos ítems, intentos del CDR y filas del .sav se van a borrar, y aclara que lo que la base aprendió de las empresas se conserva. Para habilitar el borrado hay que escribir **BORRAR**.

**API:** `DELETE /api/muestras/{id}`, solo admin. Se ejecuta como **tarea** (Cloud Tasks, payload con la clave `borrar_muestra_id`), porque una muestra puede tener miles de ítems e intentos. Devuelve `tarea_id`.

**Qué se borra:**

| Dato | Tratamiento |
|---|---|
| `muestra_item` e `item_parte_estado` de la muestra | Se borran. |
| `intento` con `item_id` de esos ítems | Se borran. |
| `sav_fila` con `item_id` de esos ítems | Se borran. |
| `conciliacion` que apunte a esos intentos o filas del .sav | Se borra. |
| `marco_snapshot` y `marco_snapshot_item` de la muestra | Se borran, si ninguna otra muestra usa ese snapshot. |
| Ítems borrados de la muestra (tabla nueva de V1) | Se borran. |
| `muestra` | Se borra. |
| Empresas, historia por campo (incluida la de fuente `sala`), vínculos y su estado, contactos, teléfonos, `ultimo_contacto_efectivo` | **No se tocan.** |
| Auditoría | Se agrega `muestra.borrar` con estudio, nombre, estado, semilla y conteos. |

**Criterios de aceptación**
- [ ] Una muestra activa borrada deja de bloquear a sus empresas: aparecen como disponibles en el próximo marco, salvo que tengan enfriamiento por contacto efectivo.
- [ ] Si una empresa tuvo un contacto efectivo en esa muestra, conserva su `ultimo_contacto_efectivo` y sigue en enfriamiento.
- [ ] Los contactos y teléfonos que llegaron por el .sav de esa muestra siguen en la ficha. Su linaje muestra el estudio y la parte (como hoy, vía `detalle`), y si el enlace a la ingesta ya no existe, la ficha muestra «ingesta borrada» en lugar de fallar.
- [ ] Un usuario que no es admin recibe 403 y no ve el botón.
- [ ] Al terminar, la web vuelve al detalle del estudio y avisa con los conteos.

#### E2. Borrar estudio (administrador)

**Dónde:** botón **«Borrar estudio»** (rojo) en el detalle del estudio, visible solo para admin.

**Confirmación:** un modal informa la cantidad de muestras, ítems, ingestas .sav, filas del .sav e intentos. Para habilitar el borrado hay que escribir el **nombre del estudio**.

**API:** `DELETE /api/estudios/{id}`, solo admin. Se ejecuta como tarea (payload con la clave `borrar_estudio_id`).

**Qué hace, en una sola transacción:**

1. Borra cada muestra del estudio con la regla de E1.
2. Borra todas las ingestas .sav de sus partes (`sav_ingesta`), incluidas sus filas del .sav sin ítem asociado y la `conciliacion` que apunte a ellas.
3. Borra el archivo .sav de cada ingesta (la fila de `archivo` y el objeto en el bucket), si ninguna otra ingesta ni carga lo usa. Si el bucket falla, se registra en el log sin revertir la transacción, igual que en el borrado de cargas.
4. Borra las partes (`parte`).
5. Borra el estudio (`estudio`).
6. Registra `estudio.borrar` en Auditoría con los conteos.

Si una ingesta .sav de ese estudio tiene una tarea pendiente o corriendo (`sav.confirmar`, `sav.remapear`), se cancela con el mecanismo de E3 antes de borrar.

**Criterios de aceptación**
- [ ] Después de borrar, el estudio no aparece en «Estudios y muestras» y `GET /api/estudios/{id}` da 404.
- [ ] Lo aprendido por el campo se conserva, igual que en E1.
- [ ] Borrar un estudio sin muestras ni .sav funciona y deja `estudio.borrar` en Auditoría.
- [ ] Si se escribe mal el nombre, el modal no deja continuar.

#### E3. Borrar cargas en cualquier estado (cancelación de tareas)

**Cambios en lo que ya existe:**
- La web muestra «Borrar carga» también en «analizando» y «en proceso».
- `pedir_borrado_carga` deja de responder 409 por tarea corriendo.

**Mecanismo de cancelación (sirve para cargas y para ingestas .sav):**
- La tabla `tarea` admite un estado nuevo, **`cancelada`** (migración: amplía el CHECK de `tarea.estado`).
- Al pedir el borrado, la API marca como `cancelada` toda tarea de esa carga en estado `pendiente` o `corriendo` (`carga.preview` o `carga.confirmar`; para un estudio, `sav.confirmar` o `sav.remapear`). Esta marca se hace en una conexión con autocommit, para que la vea la tarea que está corriendo.
- `tareas.ejecutar` no arranca tareas en estado `cancelada` (hoy solo arranca `pendiente` o `error`). Así, si Cloud Tasks la entrega tarde, no hace nada.
- **Una tarea que corre comprueba si fue cancelada** cada vez que informa progreso (`tareas.progreso`). Si lo fue, lanza una excepción que **revierte su transacción completa**: no se aplica nada.
  - La tarea cancelada termina en estado `cancelada`, no en `error`.
  - No marca la carga ni la ingesta como «error» (`_marcar_error_objeto` no se ejecuta).
- La tarea de borrado espera a que la tarea cancelada suelte la carga. En la práctica la espera la resuelven los locks de Postgres (`FOR UPDATE` sobre la carga y la FK `carga_alta_id`). Se fija un tope (`lock_timeout` de 2 minutos). Si el tope se agota, el borrado falla con un mensaje claro y se puede reintentar.
- Una tarea que figura «corriendo» pero cuyo proceso murió no tiene locks. El borrado sigue de inmediato.

**Criterios de aceptación**
- [ ] Una carga «analizando» con su tarea `pendiente` (simular Cloud Tasks caído) se borra. La tarea queda `cancelada` y, si después se ejecuta, no hace nada.
- [ ] Una carga «en proceso» cuya tarea está corriendo de verdad (test con una carga de miles de filas, cancelando a mitad de camino): la confirmación se detiene, **no queda ninguna empresa, historia ni vínculo de esa carga**, y la carga termina borrada.
- [ ] Una carga «en proceso» con su tarea «corriendo» huérfana (simular con un UPDATE manual) se borra sin esperar.
- [ ] El progreso de la confirmación sigue funcionando igual cuando nadie cancela (no hay regresión en los tests de carga).
- [ ] En la web, una tarea `cancelada` se muestra como «cancelada» (agregar ese estado a `est()` y a `seguirTarea`), no como error.

#### V1. «Verificar reproducibilidad» correcta después de borrados

**Modelo:**
- **El marco congelado no se toca nunca.** El borrado de empresas (`borrado.borrar_empresas`) deja de borrar filas de `marco_snapshot_item`. La migración quita la FK `marco_snapshot_item.empresa_id → empresa(id)`: el snapshot es un registro histórico, como la auditoría, y el `empresa_id` queda como número sin referencia. No es un dato personal: no identifica a la empresa sin la fila borrada.
- **Tabla nueva `muestra_item_borrado`** con `muestra_id`, `empresa_id` (sin FK), `estrato`, `rol`, `orden`, `liberado`, `borrado_por`, `fecha`, `accion` (`empresa.borrar` o `carga.borrar`) y `auditoria_id`. Antes de borrar los ítems de una empresa, el borrado copia ahí cada uno.

**`muestras.verificar`:**
1. Vuelve a sortear sobre el snapshot completo, igual que hoy.
2. Compara contra los ítems guardados más los borrados (`muestra_item` ∪ `muestra_item_borrado`).
3. Devuelve, además de lo que devuelve hoy, `items_borrados` y `snapshot_incompleto`.

**Resultados posibles en pantalla:**

| Caso | Mensaje |
|---|---|
| Coincide y no hubo borrados | «Reproducible ✓» (como hoy). |
| Coincide contando los borrados | «Reproducible ✓ — N empresas se borraron después del sorteo (ver Auditoría)», con la lista de RUT no disponible y la acción y fecha de cada borrado. |
| No coincide aun contando los borrados | «¡El re-sorteo no coincide! Revisar auditoría» (como hoy): es una alteración real. |
| Snapshot incompleto | «No verificable: se borraron empresas de esta muestra antes de que el sistema guardara los borrados (versión anterior). Ver Auditoría.» Se detecta cuando la cantidad de filas del snapshot es menor que `marco_snapshot.n`. |

El último caso existe porque las muestras afectadas por borrados hechos con la rama anterior perdieron filas del snapshot que no se pueden recuperar.

**Detalle de la muestra:** si hay ítems borrados, una línea lo indica («N empresas borradas después del sorteo»).

**Criterios de aceptación**
- [ ] Muestra sorteada → se borra una empresa titular → «Verificar» da «Reproducible ✓ — 1 empresa se borró después del sorteo».
- [ ] Muestra sorteada → se borra una carga con 3 empresas de la muestra → «Reproducible ✓ — 3 empresas…».
- [ ] Muestra sorteada → se altera a mano un `orden` en `muestra_item` (test) → «No coincide».
- [ ] Muestra cuyo snapshot perdió filas (simular borrándolas a mano) → «No verificable…».
- [ ] Borrar la muestra entera (E1) también borra sus filas de `muestra_item_borrado`.
- [ ] Los demás criterios de borrado de D36 siguen pasando, con el cambio de que el snapshot no se toca.

#### E4. Migración y tests

- Migración nueva `0008_borrado_estudios_muestras.sql`:
  - estado `cancelada` en `tarea`;
  - tabla `muestra_item_borrado`;
  - se quita la FK de `marco_snapshot_item.empresa_id`;
  - índices: `sav_ingesta.parte_id`, `muestra.estudio_id`, `intento.item_id` (ya existe; verificar) y `tarea` por estado y por `payload->>'carga_id'`.
- Tests nuevos (`api/tests/test_borrado_estudios.py` y casos de cancelación) para todos los criterios. La suite completa sigue pasando.

### P1 — Deseables

- **P1.1 Vista previa de conteos:** endpoint de solo lectura que el modal usa antes de confirmar, para muestra, estudio y carga.
- **P1.2 Manual de usuario:** secciones «Borrar una muestra», «Borrar un estudio», «Borrar una carga trabada» y «Qué significa "N empresas borradas después del sorteo"». Regenerar el Word y el PDF.
- **P1.3 Liberar tareas huérfanas:** las tareas «corriendo» de más de 30 minutos (más que el `dispatch_deadline` de 1800 s) se muestran como «trabada» en el detalle de la carga y de la ingesta.

### P2 — A futuro

- Borrar una parte suelta de un estudio.
- Pantalla de tareas con «Cancelar» para cualquier tarea.
- Borrado masivo de cargas o estudios.

## 7. Documentación

- `docs/decisiones.md`: **D37 — Borrado de estudios y muestras, cancelación de tareas y verificación con borrados**, con las decisiones de la sección 2 y el modelo de V1 (el snapshot es inmutable).
- Ajustar **D36**: el borrado de empresas ya no toca el marco congelado.
- Guía corta `docs/despliegue_borrado_estudios.md`, con todos los comandos y la región explícita:

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh migrar
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Los tres pasos son obligatorios y en ese orden. Después, recargar con Cmd+Shift+R. Si ya está mergeado el fix de región, se usa `EMPRESAS_REGION=us-central1`.

**Verificación en producción:**
1. Borrar una carga que hoy esté «analizando».
2. Sortear una muestra de prueba, borrar una de sus empresas y comprobar «Reproducible ✓ — 1 empresa…».
3. Borrar esa muestra y después su estudio.
4. Revisar Auditoría.

## 8. Riesgos

| Riesgo | Mitigación |
|---|---|
| Borrar por error un estudio en campo | Solo admin; hay que escribir el nombre del estudio; Auditoría; backup diario de Cloud SQL. |
| Cancelar una confirmación deja datos a medias | La confirmación corre en una sola transacción. La cancelación lanza una excepción y se revierte todo (hay un criterio de aceptación con test). |
| El borrado queda esperando un lock para siempre | `lock_timeout` de 2 minutos, mensaje claro y reintento. |
| Perder la trazabilidad del sorteo | El snapshot pasa a ser inmutable y los ítems borrados se registran. Solo las muestras dañadas antes de este cambio quedan «no verificables», y la pantalla lo dice. |
| Linaje que apunta a ingestas borradas | La ficha muestra «ingesta borrada»; el estudio y la parte siguen en el `detalle` de la historia. |

## 9. Costo

**Ninguno adicional.** Se usan la misma Cloud SQL, Cloud Run, Cloud Tasks y el mismo bucket. Las tareas de borrado son pocas y quedan dentro del millón de operaciones gratuitas mensuales de Cloud Tasks. Borrar los archivos .sav reduce levemente el costo de Storage.

## 10. Preguntas abiertas

| Pregunta | Quién | ¿Bloquea? |
|---|---|---|
| ¿Hay que avisar al coordinador de campo cuando se borra una muestra activa? | Coordinación de campo | No |
| Las muestras ya dañadas por borrados anteriores, ¿se dejan como «no verificables» o se vuelven a sortear? | Jefe de estudio | No |
