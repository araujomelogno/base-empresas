# SPEC — Templates de sorteo, empresas sin teléfono, filtros y estratos con todos los atributos, y nombres de los formatos del CSV

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, proyecto GCP `equipos-base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_templates_sorteo_sin_telefono_formatos_csv.md`, para que Claude Code lo implemente y lo despliegue.
**Base:** `main` en `a36a2a0` (PR #15).
**Fecha:** 17/11/2026 (versión 3: se agrega R4, filtros y estratos con todos los atributos. Versión 2: se quita el CSV por empresa, que ya existe como formato «Planilla de la muestra»; queda solo el cambio de nombre de los formatos)

---

## 1. Problema

1. **Los nombres de los formatos del CSV no dicen qué generan.**
   - En el detalle de la muestra, el selector «Formato» de «Descargar CSV» ofrece «uContact: un renglón por teléfono» y «Planilla de la muestra: un renglón por empresa».
   - Las dos opciones ya existen y funcionan (`exportacion.filas_csv`), pero los nombres llevan a pensar que solo existe el formato por teléfono.
2. **Cada muestra se arma desde cero.** El asistente de «Nueva muestra» tiene tres pasos (`web/public/js/vistas/estudios.js`):
   1. Filtros, que incluyen atributos, orígenes y base provisoria;
   2. Estratos;
   3. Tamaño por estrato y reemplazos.

   No hay forma de guardar esa combinación y reutilizarla en otra muestra u otro estudio, aunque se repita en cada ola.
3. **Las empresas sin teléfono no pueden salir sorteadas.**
   - La regla de disponibilidad `sin_telefono_discable` (vista `bloqueos`, migración 0002) las saca del marco.
   - Hoy solo se puede apagar **para todo el sistema**, en Configuración → reglas de disponibilidad. No hay forma de decidirlo por muestra.
   - Para estudios donde el teléfono se consigue después (búsqueda web, otro canal), o para la base provisoria, esas empresas quedan afuera.

4. **No todos los datos de la empresa sirven para filtrar o estratificar.**
   - **Filtros (paso 1):** se aceptan cuatro campos fijos (`FILTROS`: CIIU, tamaño, departamento y naturaleza) y los atributos marcados como «filtro».
   - **Estratos (paso 2):** se aceptan cinco opciones fijas (`ESTRATIFICADORES`: tamaño, departamento, naturaleza y CIIU a 2 o a 1 dígito) y los atributos **de lista** marcados como «estrato».
   - **Lo que queda afuera:**
     - la localidad, el estado y otros campos fijos;
     - un atributo de texto, número o fecha;
     - cualquier atributo al que no le marcaron la casilla.

     Ninguno de estos se puede usar sin que un administrador lo habilite antes (y en algunos casos no se puede).

## 2. Objetivos

1. El selector de formato del CSV dice qué genera cada opción: una fila por empresa o una fila por número.
2. Armar una muestra con una configuración ya usada lleva un clic: elegir el template y revisar.
3. Cada muestra decide si incluye empresas sin teléfono, sin tocar la configuración general.
4. Cualquier dato de la empresa (campo fijo o atributo activo) se puede usar como filtro y como estrato al crear una muestra, sin configuración previa.

## 3. Fuera de alcance

- **Cambiar qué se sortea.** Se siguen sorteando empresas; los teléfonos son datos de la empresa.
- **Templates del paso 4** (nombre, semilla, sorteo) **ni de las opciones de exportación** («Qué incluir»). Solo pasos 1 a 3, como se pidió. Las opciones de exportación siguen guardadas por muestra.
- **Conseguir teléfonos para las empresas que no tienen.** Este spec solo permite sortearlas; enriquecerlas es otro tema.
- **Filtrar o estratificar por atributos de contacto.** Decidido: solo se usan datos de la empresa.
- **Compartir templates entre usuarios con permisos finos.** Todos los templates son visibles para quien puede crear muestras.

## 4. Historias de usuario

- Como **jefe de estudio**, quiero que las opciones de formato del CSV digan «una fila por empresa» o «una fila por número», para elegir sin dudar.
- Como **jefe de estudio**, quiero guardar los filtros, estratos y tamaños de una muestra como template, y usarlos en la próxima ola o en otro estudio, para no reconfigurar todo cada vez.
- Como **jefe de estudio**, quiero ver qué cambió si un template usa un atributo o un estrato que ya no existe, para corregirlo antes de sortear.
- Como **jefe de estudio**, quiero decidir en cada muestra si entran empresas sin teléfono, para estudios donde el teléfono se consigue después.
- Como **jefe de estudio**, quiero filtrar y estratificar por cualquier atributo de la empresa (por ejemplo, cantidad de empleados por tramos, o «cámara a la que pertenece»), sin pedirle antes a un administrador que lo habilite.
- Como **coordinador de campo**, quiero que las empresas sin teléfono aparezcan en el CSV con las columnas de teléfono vacías, para saber cuáles hay que conseguir.

## 5. Requisitos

### P0 — Imprescindibles

#### R1. Nombres de los formatos del CSV [1]

- **Lo que no cambia:** los dos formatos ya existen, y este spec **no cambia** el contenido de ninguno.
- **Lo que cambia:** el selector «Formato» del detalle de la muestra (`web/public/js/vistas/estudios.js`, `#mu-formato`) se renombra así:

  | Valor interno | Texto actual | Texto nuevo |
  |---|---|---|
  | `planilla` | «Planilla de la muestra: un renglón por empresa» | **«Una fila por empresa»** |
  | `ucontact` | «uContact: un renglón por teléfono» | **«Una fila por número»** |

- **Orden:** «Una fila por empresa» va **primero** y queda **seleccionada por defecto**.
- **Textos que acompañan al selector:** la ayuda debajo del botón cambia según la opción elegida.
  - Con «Una fila por empresa»: «Una fila por empresa liberada y pendiente en la parte, con sus números y orígenes en columnas tel_1, tel_2…».
  - Con «Una fila por número»: «Una fila por cada número discable de cada empresa: una empresa con 3 números sale 3 veces».
  - Las dos ayudas mantienen la aclaración sobre intermediarios, inexistentes, «no corresponde» y no llamar.
- **Nombre del archivo descargado:** debe reflejar el formato, con los sufijos `_por_empresa` o `_por_numero`.
- **Documentación:** el manual y cualquier otro texto de la web que nombre los formatos como «uContact» o «Planilla de la muestra» pasan a usar los nombres nuevos.

**Criterios de aceptación:**

- [ ] El selector muestra «Una fila por empresa» (primera y por defecto) y «Una fila por número».
- [ ] Los archivos que genera cada opción son iguales a los de hoy, salvo el nombre del archivo.
- [ ] La ayuda debajo del botón cambia según la opción elegida.

#### R2. Templates de sorteo [2]

**Qué guarda un template:** la combinación de los **pasos 1, 2 y 3** del asistente de «Nueva muestra»:

1. **Paso 1, filtros:** filtros de campo, filtros por atributo, orígenes de teléfono, «Incluir la base provisoria» e «Incluir empresas sin teléfono» (R3).
2. **Paso 2, estratos:** las variables de estratificación.
3. **Paso 3, tamaños:**
   - el tamaño por estrato y los reemplazos, ya sea el mismo para todos (`n_por_estrato`, `reemplazos_por_estrato`) o la lista con el tamaño de cada estrato;
   - los estratos con tamaño 0 que se descartaron.

Un template **no** guarda la semilla, el estudio, el nombre de la muestra ni las opciones de exportación.

**Modelo:** tabla `muestra_template` con estos campos:

- `id`, `nombre` (único) y `descripcion`;
- `criterios` (jsonb, con el mismo formato que `muestra.criterios`);
- `creado_por`, `creado`, `actualizado_por` y `actualizado`;
- `veces_usado` y `activo`.

Las muestras guardan **`template_id`** (nullable) y una copia propia de los criterios. **Editar el template después no cambia muestras ya creadas ni sorteadas**, para mantener la reproducibilidad.

**Uso en el asistente de «Nueva muestra»:**

- **Al principio:** un selector **«Partir de un template»** (opcional). Al elegir uno, los pasos 1 a 3 se completan con sus valores, y todo se puede ajustar antes de sortear.
- **Al final del paso 3:** el botón **«Guardar como template…»** pide nombre y descripción y guarda la configuración actual. Si se partió de un template, ofrece **«Actualizar template X»** o **«Guardar como nuevo»**.
- **Desde el detalle de una muestra ya creada:** **«Guardar configuración como template»**, para aprovechar muestras viejas.

**Validación al aplicar un template:** los criterios se revalidan con las reglas actuales (`_validar_criterios`). Si algo ya no existe, se avisa y se saca, sin bloquear el asistente:

- un atributo inactivo o que dejó de ser filtro o estrato;
- un origen borrado.

Si el template tiene **tamaños por estrato** y alguno de esos estratos no existe en el marco actual (por ejemplo, un departamento sin empresas), el paso 3 los muestra como «estrato del template sin empresas en el marco». Los estratos nuevos del marco que el template no tenía aparecen con tamaño 0 y se marcan como nuevos.

**Administración:** sección **«Templates de sorteo»** dentro de Estudios y muestras (para jefes y admin), con:

- la lista de templates, con su resumen de filtros, estratos y tamaño total, las veces usado y la última muestra que lo usó;
- las acciones **«Editar»** (abre los pasos 1 a 3 sin sortear), **«Duplicar»**, **«Desactivar»** y **«Borrar»** (solo si nunca se usó; si no, desactivar).

**Auditoría:** se registran `muestra_template.crear`, `muestra_template.editar`, `muestra_template.borrar` y `muestra.crear` con `template_id`.

**Permisos:** los mismos que para crear muestras (jefe y admin).

**Criterios de aceptación:**

- [ ] Guardar como template una muestra con filtros (departamento y atributo «Exporta = Sí»), estratos (tamaño × departamento) y tamaños por estrato, y aplicarlo en otro estudio, completa los tres pasos con los mismos valores.
- [ ] Editar el template después no cambia los criterios de la muestra que ya lo usó, y **Verificar reproducibilidad** de esa muestra sigue dando OK.
- [ ] Aplicar un template que usa un atributo desactivado avisa «se quitó el filtro por X: el atributo ya no está activo» y permite seguir.
- [ ] Un estrato del template sin empresas en el marco actual aparece marcado en el paso 3.
- [ ] Un coordinador no ve la opción de guardar templates.

#### R3. Empresas sin teléfono en el sorteo [3]

- El **paso 1 (Filtros)** agrega la opción **«Incluir empresas sin teléfono discable»**, desmarcada por defecto (ver Q1). Se guarda en `muestra.criterios` (`incluir_sin_telefono`) y en los templates.
- **Al sortear con la opción marcada:**
  - la regla `sin_telefono_discable` **no se aplica para esa muestra**;
  - las demás reglas sí se aplican: enfriamiento, muestra activa, no llamar, naturaleza excluida, baja y cerrada;
  - el resumen del sorteo informa cuántas empresas sin teléfono entraron, por estrato.
- **Al sortear con la opción desmarcada:** el comportamiento es el de hoy.
- **Configuración general:** sigue existiendo el interruptor de Configuración → reglas de disponibilidad. Si está apagado para todo el sistema, la opción de la muestra aparece marcada y deshabilitada, con la leyenda «desactivado en la configuración general».
- **Reproducibilidad:** la opción forma parte de los criterios congelados en el snapshot, así que **Verificar reproducibilidad** la respeta.
- **El filtro por origen de teléfono** sigue funcionando igual: si la muestra filtra por orígenes, una empresa sin teléfonos no tiene ningún teléfono de ese origen y no entra. El paso 1 lo explica cuando las dos opciones están activas.
- **CSV:** en el formato «Una fila por empresa», las empresas sin teléfono salen con las columnas `tel_*` vacías, como ya pasa hoy. En «Una fila por número» no salen, porque no tienen números. El resumen de la exportación las cuenta aparte en los dos formatos.
- **Detalle de la muestra:** columna o filtro **«Sin teléfono»** en «Empresas de la muestra», para encontrarlas y completarlas desde la ficha.

**Criterios de aceptación:**

- [ ] Con la opción desmarcada, una empresa sin teléfono no entra al marco, como hoy.
- [ ] Con la opción marcada, entra. El resumen del sorteo la cuenta como «sin teléfono», y el CSV «Una fila por empresa» la trae con las columnas de teléfono vacías.
- [ ] Si después se le agrega un teléfono en la ficha, la próxima exportación lo incluye.
- [ ] Verificar reproducibilidad de una muestra con la opción marcada da OK.

#### R4. Filtros y estratos con todos los atributos disponibles [nuevo]

**Qué datos se pueden usar.** Al crear una muestra (y en los templates de R2), los pasos 1 y 2 ofrecen:

- **todos los campos fijos de la empresa** con sentido para filtrar o estratificar: razón social, nombre de fantasía, naturaleza jurídica, CIIU (completo, a 2 dígitos y a 1 dígito), tamaño, departamento, localidad, dirección, web y estado;
- **todos los atributos de empresa activos**, de cualquier tipo (texto, número, fecha o lista).

Los atributos inactivos o fusionados no aparecen. **Los atributos de contacto no se ofrecen ni para filtrar ni para estratificar** (decisión de Germán Araújo, 17/11/2026).

**Las casillas «Sirve como filtro del sorteo» y «Sirve como estrato»** de Administración → Atributos dejan de restringir: se quitan del formulario, de la lista de atributos y de las validaciones (`_validar_criterios`, el CHECK `estratificable` de la migración 0006). Las columnas pueden quedar en la base sin uso, o se reemplazan por «Destacar en el sorteo», que solo ordena el selector (P1).

**Paso 1, filtros, según el tipo del dato:**

| Tipo | Opciones de filtro |
|---|---|
| Lista (y naturaleza, tamaño, departamento, estado) | Elegir una o varias opciones |
| Texto (y razón social, fantasía, localidad, dirección, web, CIIU) | «Contiene…», «Es uno de…» (con la lista de valores existentes y su cantidad de empresas, hasta 200), «Tiene dato» o «No tiene dato» |
| Número | Rango «desde / hasta» |
| Fecha | Rango «desde / hasta» |

- Cada filtro tiene la casilla **«Incluir empresas sin dato»**, desmarcada por defecto.
- Los filtros se combinan con «y»: todos tienen que cumplirse.
- El selector agrupa los datos en «Campos de la empresa» y «Atributos», con un buscador por nombre.

**Paso 2, estratos, según el tipo del dato:**

| Tipo | Cómo se arman los estratos |
|---|---|
| Lista (y naturaleza, tamaño, departamento, estado) | Un estrato por opción |
| Texto (y localidad, CIIU) | Un estrato por valor distinto, comparando sin distinguir mayúsculas, tildes ni espacios. Si hay más de 30 valores, se avisa y se ofrece **«Agrupar en Otros los valores con menos de N empresas»** o **«Quedarse con los N más frecuentes y el resto en Otros»**. |
| Número | **Tramos** que define el usuario. Por ejemplo, para empleados: 1–4, 5–19, 20–99 y 100 o más. Se ofrecen **tramos sugeridos**: cuartiles del marco o tramos iguales, y se pueden editar. |
| Fecha | Por año, por semestre, o por tramos que define el usuario |

- Las empresas sin dato van siempre a un estrato «(sin dato)», como hoy.
- **Combinación:** se pueden combinar varios datos, como hoy (por ejemplo, tamaño × departamento × tramo de empleados). Si la combinación da más de 200 estratos, el paso 2 avisa antes de seguir.
- **Vista previa:** antes del paso 3 se muestra el marco por estrato, con la cantidad de empresas de cada uno. Ya existe `POST /muestras/marco`.

**Reproducibilidad:**

- Los tramos, los agrupamientos en «Otros» y la normalización de textos quedan guardados en `muestra.criterios` y en los templates.
- El estrato de cada empresa se calcula al sortear y se congela en el snapshot, como hoy. **Verificar reproducibilidad** no depende de cómo cambien después los valores de los atributos.
- Si un template usa un tramo o un agrupamiento, al aplicarlo se recalculan las cantidades por estrato con el marco nuevo, pero se respetan los tramos guardados.

**Rendimiento:** los filtros sobre atributos se resuelven con consultas sobre `empresa_atributo` (con índices por atributo y valor). La vista previa del marco debe responder en menos de 5 segundos con 100.000 empresas.

**Criterios de aceptación:**

- [ ] Un atributo de texto **sin** la casilla «filtro» marcada se puede usar como filtro («Es uno de…»), y como estrato con los valores agrupados en «Otros».
- [ ] Un atributo numérico «Cantidad de empleados» se puede estratificar con los tramos 1–4, 5–19, 20–99 y 100+. El paso 3 muestra un estrato por tramo, más «(sin dato)».
- [ ] La localidad y el estado aparecen como filtro y como estrato.
- [ ] Una muestra estratificada por tramos de un atributo numérico se guarda como template y, aplicada en otro estudio, conserva esos tramos.
- [ ] Cambiar después el valor de un atributo en una empresa sorteada no altera **Verificar reproducibilidad**.
- [ ] Administración → Atributos ya no muestra las casillas «filtro» y «estrato».
- [ ] Los atributos de contacto no aparecen en los selectores de filtros ni de estratos, y la API rechaza un criterio que los use.

### P1 — Deseables

- **P1.1** Al aplicar un template, un **preview del marco** (cantidad de empresas por estrato) antes del paso 3. Ya existe `POST /muestras/marco` y se puede reutilizar.
- **P1.2** Exportar e importar templates como JSON, para pasarlos entre ambientes.
- **P1.3** «Destacar en el sorteo» por atributo: los atributos destacados aparecen primero en los selectores de filtros y estratos.
- **P1.4** Filtros combinados con «o» (por ejemplo, «Exporta = Sí» o «Cámara = X»).

### P2 — A futuro

- Templates que también guarden las opciones de exportación.
- Templates por cliente o por tipo de estudio, con etiquetas.

## 6. Datos y migración

- Migración `0012_templates_sorteo.sql` (incluye quitar el CHECK de `estratificable` e índices de `empresa_atributo` por atributo y valor):
  - tabla `muestra_template`;
  - columna `muestra.template_id`, que referencia a `muestra_template` con `ON DELETE SET NULL`.
- No hace falta migrar las muestras existentes: el criterio `incluir_sin_telefono` ausente equivale a `false`.
- Tests para los criterios de R1 a R4. La suite completa sigue pasando.
- `docs/decisiones.md`: **D44**, con tres puntos: los templates son copias de criterios, no referencias vivas; las empresas sin teléfono son opcionales por muestra; y todo dato de la empresa sirve como filtro y estrato (se reemplaza la habilitación por casillas de la Carga v2).
- Manual de usuario: nombres nuevos de los formatos del CSV y secciones «Templates de sorteo», «Empresas sin teléfono» y «Filtros y estratos». Regenerar el Word y el PDF.

## 7. Métricas de éxito

| Métrica | Meta |
|---|---|
| Muestras creadas desde un template, a 60 días | ≥ 50 % de las muestras nuevas |
| Errores de reproducibilidad en muestras creadas desde un template | 0 |

## 8. Despliegue

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh migrar
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Si ya está mergeado el fix de región, se usa `EMPRESAS_REGION=us-central1`. Después, recargar con Cmd+Shift+R y verificar con una muestra de prueba:

1. Revisar que el selector de formato muestre los nombres nuevos.
2. Guardar la configuración como template y aplicarlo en una muestra nueva.
3. Sortear con «Incluir empresas sin teléfono».
4. Crear una muestra filtrada por un atributo de texto y estratificada por tramos de un atributo numérico.

## 9. Costo

**Ninguno adicional.** Es una tabla chica y consultas sobre la misma Cloud SQL y la misma API.

## 10. Preguntas abiertas

| # | Pregunta | Quién | ¿Bloquea? |
|---|---|---|---|
| Q1 | «Incluir empresas sin teléfono», ¿viene **desmarcado** (propuesta, para no cambiar los estudios actuales) o marcado por defecto? | Germán | No |
