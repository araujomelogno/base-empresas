# SPEC — Conteo de llamadas del CDR, rendimiento por origen sin depender de muestras y lista exportable de empresas llamadas

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, proyecto GCP `equipos-base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_conteo_llamadas_cdr_y_rendimiento_por_origen.md`, para que Claude Code lo implemente y lo despliegue.
**Base:** `main` en `f55a30a`.
**Versión:** 2 (11/11/2026). Reemplaza la versión 1: se quita todo lo relativo a campañas y el rendimiento por origen deja de depender de las muestras.

---

## 1. Problema

### 1.1 La columna «Llamadas» no cuenta llamadas

En Actividad → «Corridas del job del CDR»:

- **«Llamadas»** muestra `conteos.filas_leidas` (en `web/public/js/vistas/campo.js`): las **filas** leídas de la tabla del CDR antes de cualquier filtro (`api/app/jobs/cdr_job.py`). Ese número incluye:
  - las filas del último segundo de la corrida anterior, que se vuelven a leer y se descartan después (`ya_enviada`);
  - cada tramo de una misma llamada (mismo `uniqueid`);
  - las llamadas a destinos internos (anexos, colas).
- **«Nuevos»** muestra `intentos_nuevos`: las llamadas que cruzaron con un teléfono de la base y no estaban guardadas. El nombre no dice qué son.
- El resto del desglose (`internas`, `no_normalizables`, `no_cruzan`, `duplicados`, `asociados_a_item`, `a_conciliacion`) se guarda en cada corrida, pero no se muestra.

### 1.2 «Rendimiento por origen» no muestra llamadas a empresas que no están en una muestra

Por ejemplo, una corrida informa 51 llamadas a empresas, pero esas llamadas no aparecen en «Rendimiento por origen». Causa, revisada en el código:

- Los filtros de estudio y muestra de Actividad (`actividad._filtros`) seleccionan intentos **por `item_id`**, es decir, solo las llamadas asociadas a un ítem de muestra.
- Una llamada a empresa queda **sin ítem** cuando:
  - la empresa no está en ninguna muestra activa;
  - la llamada se hizo fuera de las fechas de campo del estudio;
  - o el número coincide con más de un ítem y la llamada queda pendiente en Conciliación.
- Esas llamadas se guardan, pero los indicadores no las ven y la pantalla no avisa que quedaron afuera.
- Además, la columna «Llamados» de la tarjeta cuenta **teléfonos**, no llamadas, y eso confunde.

### 1.3 No se puede ver a qué empresas se llamó

Actividad muestra totales, pero no la lista de empresas detrás de esos números. Por ejemplo, no hay forma de saber quiénes son las 51 empresas llamadas en una corrida, ni de exportarlas.

## 2. Decisiones (Germán Araújo, 11/11/2026)

| Tema | Decisión |
|---|---|
| Qué es una «llamada» | Los criterios del dashboard de productividad CATI: **una llamada por `uniqueid`** (los tramos de una misma llamada cuentan una vez), **con destino externo** (no interno según `destinos_internos` de la configuración), sin contar dos veces las filas que se vuelven a leer. |
| Campañas | **No se filtra por campaña.** Se cuentan todas las llamadas, con o sin campaña. |
| Rendimiento por origen | **No depende de las muestras.** Cuenta todas las llamadas a empresas de la base, estén o no asociadas a un ítem de muestra. |
| Lista de empresas | Se puede ver y **exportar** la lista de empresas llamadas, desde una corrida y desde Actividad. |

## 3. Objetivos

1. «Llamadas» de una corrida es la cantidad de llamadas hechas, con el mismo criterio que el dashboard de productividad.
2. Si una corrida informa N llamadas a empresas, esas N llamadas aparecen en «Rendimiento por origen» para el mismo período.
3. Cualquier número de llamadas a empresas que muestre la pantalla se puede abrir como lista y exportar a CSV.

## 4. Fuera de alcance

- **Filtrar o excluir por campaña.**
- **Cambiar la regla que asocia una llamada a un ítem de muestra.** Sigue igual: una muestra activa y dentro de las fechas de campo. Solo deja de condicionar el rendimiento por origen.
- **Cambiar la definición de llamada atendida** (D35).
- **Recalcular los conteos de las corridas anteriores.** Aplican desde el despliegue; un reproceso con «Correr ahora» y fechas los recalcula.
- **Exportar datos de contactos** (nombres de personas) en la lista. Ver R4.

## 5. Historias de usuario

- Como **coordinador de campo**, quiero que «Llamadas» sea la cantidad de llamadas hechas, igual que en el dashboard de productividad.
- Como **coordinador de campo**, quiero ver en cada corrida cuántas llamadas fueron a empresas de la base y a cuántos teléfonos.
- Como **coordinador o jefe de estudio**, quiero que «Rendimiento por origen» incluya todas las llamadas a empresas del período, aunque esas empresas no estén en una muestra.
- Como **coordinador o jefe de estudio**, quiero ver y exportar la lista de empresas a las que se llamó (de una corrida, de un período o de un origen), para revisarlas o cruzarlas con otras fuentes.

## 6. Requisitos

### P0 — Imprescindibles

#### R1. «Llamadas» con los criterios del dashboard

El job del CDR guarda en cada corrida:

| Conteo | Definición |
|---|---|
| `filas_leidas` | Igual que hoy: las filas que devolvió la consulta. Va en el detalle. |
| `llamadas` | **Columna «Llamadas».** Llamadas únicas por `uniqueid` con destino externo, sin las del segundo ya procesado en la corrida anterior. No se filtra por campaña. |
| `internas`, `no_normalizables`, `no_cruzan`, `duplicados` | Igual que hoy. Van en el detalle. |

**Criterios de aceptación**
- [ ] Una llamada con tres tramos (mismo `uniqueid`) cuenta 1.
- [ ] Una llamada a un anexo interno no cuenta en «Llamadas» y suma en `internas`.
- [ ] Una llamada sin campaña cuenta igual que una con campaña.
- [ ] Las filas del último segundo que se vuelven a leer no cuentan dos veces.
- [ ] Con un CDR de ejemplo, «Llamadas» coincide con lo que contaría el dashboard de productividad para el mismo período sin filtro de campaña. Agregar un test con ese caso.

#### R2. Columnas de la tabla de corridas

| Columna | Conteo | Definición |
|---|---|---|
| Inicio, Origen, Estado | Igual que hoy | |
| **Llamadas** | `llamadas` | R1. |
| **Llamadas a empresas** | `llamadas_a_empresas` | Llamadas (R1) cuyo destino es un teléfono de la base, es decir, los intentos: **nuevos más ya registrados**, para que un reproceso no muestre 0. |
| **Teléfonos marcados** | `telefonos_marcados` | Teléfonos distintos de la base entre esas llamadas. |
| **Empresas llamadas** | `empresas_llamadas` | Empresas distintas vinculadas a esos teléfonos al momento de la llamada (`intento.empresas`). |
| Detalle | | Igual que hoy, más **«Ver detalle»** y **«Exportar empresas»** (R4). |

**«Ver detalle»** muestra el embudo de la corrida, con la cantidad de cada descarte:

> Filas leídas → Llamadas → Llamadas a empresas (nuevas / ya registradas) → Asociadas a una muestra / En Conciliación / Sin muestra

Los descartes que se detallan son: internas, no normalizables y números que no están en la base (por tipo). Para las corridas anteriores al despliegue, las columnas nuevas muestran «—» con la nota «corrida anterior al nuevo conteo».

**Criterios de aceptación**
- [ ] En una corrida normal, «Llamadas a empresas» es igual a los intentos nuevos.
- [ ] En un reproceso de un día ya procesado, «Llamadas a empresas» repite el número original, y el detalle dice «0 nuevas, N ya registradas».
- [ ] Asociadas a una muestra + En Conciliación + Sin muestra = Llamadas a empresas.

#### R3. «Rendimiento por origen» con todas las llamadas a empresas

- **Sin filtro de estudio ni de muestra**, la tarjeta cuenta **todos** los intentos del período (y del encuestador, si se eligió), tengan o no ítem de muestra. Hoy, el cálculo sin filtros ya incluye los intentos sin ítem. Lo que hay que garantizar es que ningún otro filtro los saque.
- **Con un estudio o una muestra seleccionados**, se filtra **por empresa**, no por ítem: cuentan las llamadas a empresas que pertenecen a alguna muestra de ese estudio (o a esa muestra), aunque la llamada no haya quedado asociada al ítem. Por ejemplo, una llamada hecha antes del inicio del campo, o una que quedó en Conciliación, igual cuenta. Este cambio aplica a la tarjeta de rendimiento por origen y a los indicadores del tablero de Actividad, para que los números de toda la pantalla coincidan.
- **Columnas de la tarjeta:**
  - «Llamados» pasa a llamarse **«Teléfonos llamados»**;
  - «Intentos» pasa a llamarse **«Llamadas»**;
  - se agrega **«Empresas llamadas»**;
  - el pie explica qué cuenta cada columna.
- Cada número de las columnas «Llamadas» y «Empresas llamadas», incluida la fila Total, es un enlace que abre la lista de R4 con esos filtros y ese origen.

**Criterios de aceptación**
- [ ] Si una corrida tiene 51 llamadas a empresas y ninguna está asociada a una muestra, la fila Total de «Rendimiento por origen» para ese período muestra 51 en «Llamadas».
- [ ] Filtrando por un estudio, una llamada a una empresa de su muestra hecha antes de `campo_desde` cuenta.
- [ ] Filtrando por un estudio, una llamada a una empresa que no está en ninguna de sus muestras no cuenta.
- [ ] La fila Total de «Llamadas» coincide con el total de llamadas del tablero de Actividad para los mismos filtros.

#### R4. Lista de empresas llamadas, con exportación

**Dónde se abre:**
- desde una corrida, con «Exportar empresas» (las empresas de las llamadas de esa corrida);
- desde «Rendimiento por origen», haciendo clic en un número (las empresas de esa fila y esos filtros);
- desde Actividad, con un botón **«Empresas llamadas»** que usa los filtros actuales (estudio, muestra, encuestador, desde, hasta).

**Qué muestra:** una pantalla con una fila por empresa y estas columnas:

| Columna | Contenido |
|---|---|
| RUT | Con enlace a la ficha. |
| Razón social | |
| Departamento | |
| Teléfonos llamados | Uno o más, cada uno con su origen. |
| Llamadas | Cantidad en el período. |
| Atendidas | Cantidad de llamadas atendidas según D35. |
| Primera y última llamada | Fecha y hora. |
| Encuestadores | Los que llamaron. |
| Estudio / muestra | Si la empresa tiene ítem en alguna muestra; si no, «sin muestra». |
| Estado del ítem | Si tiene ítem en una muestra. |

**Exportación:** botón **«Descargar CSV»** con las mismas columnas (separador `;`, UTF-8 con BOM, como los demás CSV del sistema).

**API:** `GET /api/actividad/empresas-llamadas` con los mismos filtros de Actividad, más `corrida_id` y `origen` opcionales. Con `formato=csv` devuelve el archivo. Para filtrar por corrida, se toman los intentos cuyos `lote_id` pertenecen a los lotes de esa corrida (`cdr_lote.corrida_id`).

**Permisos:** pueden verla y exportarla los roles admin, coordinador y jefe (los mismos que ven Actividad). Cada exportación queda en Auditoría (`actividad.exportar_empresas`, con los filtros y la cantidad de filas). La lista **no incluye contactos** (nombres de personas), así que no se aplica la restricción de datos personales de la Ley 18.331.

**Criterios de aceptación**
- [ ] «Exportar empresas» de una corrida con 51 llamadas a empresas devuelve las empresas distintas de esas 51 llamadas. Por ejemplo, si hubo 51 llamadas a 40 empresas, el CSV tiene 40 filas con un total de 51 llamadas.
- [ ] Un clic en la fila de un origen en «Rendimiento por origen» devuelve solo las empresas llamadas a teléfonos de ese origen.
- [ ] El CSV abre bien en Excel, con tildes y ñ.
- [ ] El rol de lectura no ve el botón y recibe 403 en la API.
- [ ] La exportación queda en Auditoría.

#### R5. Tests y documentación

- Tests de R1 a R4: job con un CDR de ejemplo, tarjeta con y sin filtros, lista y CSV.
- `docs/decisiones.md`: **D38 — Qué es una llamada y cómo se cuentan las llamadas a empresas** (criterios del dashboard, sin filtro de campaña, rendimiento por origen sin depender de muestras, filtro por empresa en lugar de por ítem).
- Manual de usuario: explicar las columnas de la tabla de corridas y de «Rendimiento por origen», y cómo exportar las empresas llamadas. Regenerar el Word y el PDF.

### P1 — Deseables

- **P1.1** Que las llamadas por encuestador del tablero de Actividad usen la misma definición de llamada de R1.
- **P1.2** En la lista de R4, un filtro «solo sin muestra», para ver rápido las empresas llamadas que no están en ningún estudio.

### P2 — A futuro

- Desde la lista de R4, crear una muestra o agregar empresas a una muestra.

## 7. Despliegue

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh migrar
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh cdr
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

- `cdr` es obligatorio, porque el conteo nuevo vive en el job.
- `migrar` solo hace falta si se agregan índices (por ejemplo, `intento.lote_id`).
- Si ya está mergeado el fix de región, se usa `EMPRESAS_REGION=us-central1`.

**Después del despliegue:**
1. Lanzar «Correr ahora» con las fechas de la corrida de las 51 llamadas.
2. Verificar que «Llamadas a empresas» muestre 51 y que «Rendimiento por origen» las cuente.
3. Exportar la lista de empresas.

## 8. Costo

**Ninguno adicional.** El job lee las mismas filas que hoy; la lista y el CSV son consultas sobre tablas indexadas en la misma Cloud SQL y la misma API.

## 9. Preguntas abiertas

| Pregunta | Quién | ¿Bloquea? |
|---|---|---|
| ¿La lista de empresas llamadas debería incluir también los teléfonos que no están en la base (números llamados que no cruzaron)? Este spec dice que no: solo empresas de la base. | Germán | No |
