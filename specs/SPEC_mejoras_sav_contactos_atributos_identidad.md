# SPEC — Teléfonos y encuestas del .sav, contactos completos, atributos normalizados, exportación configurable, base provisoria (empresas sin RUT) y reglas de fusión en cascada

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, proyecto GCP `equipos-base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_mejoras_sav_contactos_atributos_identidad.md`, para que Claude Code lo implemente y lo despliegue **por fases** (sección 8).
**Base:** `main` en `f71ab7c`.
**Origen:** lista de 20 pedidos de Germán Araújo y brainstorming del 12/11/2026. Los pedidos 4 y 8 son el mismo (clave automática de atributos) y no hay pedido 9.
**Fecha:** 12/11/2026

---

## 1. Problema

Con las primeras cargas y la primera ingesta .sav reales aparecieron cuatro grupos de problemas:

1. **El .sav no deja en la base lo que la sala aprendió.**
   - Hoy un número adicional (`EC_TEL_ALT`) y el número con el que se habló (`EC_TEL_USADO`) entran «sin verificar» (`resultados.aplicar`). El número usado solo pasa a verificado si además viene `EC_CALIDAD_TEL` = «corresponde».
   - Un número nuevo puede no agregarse sin que la ingesta explique por qué: la fila no se asoció a ningún ítem, o el número no se pudo normalizar.
   - El contacto no queda relacionado con el número por el que se habló con él.
   - Las encuestas hechas solo cuentan si la fila se asoció a un ítem.
   - La línea de tiempo de la empresa no muestra contactos (`actividad.linea_de_tiempo` no los consulta).
2. **Los contactos están a medias.** Solo los crea el .sav: no se pueden cargar, agregar, editar ni borrar a mano, y no tienen atributos propios.
3. **Los atributos se duplican y cuesta crearlos.**
   - La clave se escribe a mano (`catalogos.crear_atributo` exige el formato `^[a-z][a-z0-9_]*$`).
   - Nada detecta que «Cant. empleados» y «Cantidad de empleados» son el mismo atributo.
   - Los valores de lista distinguen mayúsculas de minúsculas.
4. **El modelo de identidad es rígido.**
   - No hay dónde cargar una base que **no trae RUT** (por ejemplo, un directorio o un relevamiento web): todas sus filas se rechazan, aunque sean empresas reales. Lo mismo pasa con una fila que trae otro identificador en lugar del RUT, como la del «RUT con 7 dígitos».
   - La carga admite una sola regla de fusión (`carga.regla_fusion`), cuando en la práctica se necesita una cascada: primero RUT, después nombre, después dirección.

A esto se suman errores visibles: el contador de muestras activas, el contador de intermediarios después de borrar empresas, la lista de ítems de la muestra sin paginar y la búsqueda por `EC_ID_ITEM`.

## 2. Decisiones tomadas (Germán Araújo, 12/11/2026)

| # | Tema | Decisión |
|---|---|---|
| D-a | Teléfonos del .sav | **El número con el que se habló (`EC_TEL_USADO`) queda verificado para la empresa**, exista o no en la base. Como toda fila del .sav es una encuesta completa (D-b), esto vale para todas las filas (pedido 15, aclarado el 12/11/2026). El número adicional (`EC_TEL_ALT`) también queda verificado (pedido 1). Ver Q1 sobre la calidad negativa explícita. |
| D-b | Encuestas hechas | **Toda fila del .sav es una encuesta completa**: Alchemer exporta solo las completas (aclarado el 12/11/2026). No se busca el resultado en ninguna variable. Cuenta **esté o no asociada** a un ítem; las no asociadas se muestran aparte para conciliarlas. |
| D-c | Bases sin RUT | Se manejan como una **base provisoria**: empresas que directamente no traen RUT, que se cargan, consultan y depuran por separado de la base definitiva. **Se pueden sortear y llamar** antes de tener RUT. Pasan a la base definitiva cuando se les agrega el RUT o cuando se fusionan con una empresa que tiene RUT. |
| D-d | Contactos en cargas | Cambia lo que se decidió antes: **los contactos pueden venir en una carga.** |
| D-e | Alcance | **Un solo spec**, implementado por fases (sección 8). |

## 3. Objetivos

1. Toda la información de contacto que trae el .sav (número usado, número adicional, contacto) termina en la ficha. Si una fila no se aplica, la ingesta dice por qué, fila por fila.
2. «Encuestas completas» en Actividad coincide con la cantidad de completas del .sav de cada parte.
3. Un data steward administra contactos (alta, edición, borrado, atributos) sin depender del .sav.
4. En las cargas no se crean atributos duplicados: el sistema propone el atributo o el valor existente cuando son parecidos.
5. Una base sin RUT se puede cargar, sortear y llamar, y las filas que coinciden por reglas flexibles se fusionan solo con confirmación humana.

## 4. Fuera de alcance

- **Enriquecimiento automático del RUT de las provisorias** (búsqueda en DGI o en la web). Hoy el RUT se agrega a mano, por carga o desde el .sav. Queda como P2.
- **Deduplicar contactos entre empresas distintas**, por ejemplo una persona que trabaja en dos empresas. Cada contacto pertenece a una empresa.
- **Atributos de empresa desde el .sav.** Este spec agrega atributos de *contacto* desde el .sav (pedido 10). Los de empresa quedan como P1.
- **Cambiar el formato que espera uContact.** El CSV para uContact sigue siendo un renglón por teléfono. La planilla por empresa es un formato adicional.
- **Similitud con IA o servicios externos.** La similitud usa `pg_trgm` y normalización de texto dentro de Cloud SQL.

## 5. Historias de usuario

**Coordinador de campo**
- Después de ingerir el .sav, quiero que el número con el que se habló quede verificado en la empresa, aunque fuera nuevo, para que el próximo estudio lo use primero.
- Quiero ver, por cada fila del .sav que no se aplicó, el motivo (sin ítem, número no normalizable, sin response_id), para corregirlo.
- Quiero que las encuestas completas del .sav cuenten en Actividad aunque una fila todavía no esté conciliada.
- Quiero buscar una empresa por el `EC_ID_ITEM` que figura en Alchemer, para ir directo de una respuesta a su ficha.
- Quiero recorrer por páginas las empresas de una muestra grande.

**Data steward**
- Quiero agregar, editar y borrar contactos desde la ficha.
- Quiero cargar contactos y sus atributos junto con la base.
- Quiero que el sistema me avise, al cargar, si una columna o un valor se parece a un atributo o valor que ya existe, y me ofrezca usarlo en lugar de crear otro.
- Quiero crear un atributo escribiendo solo su nombre y su tipo.
- Quiero fusionar dos atributos que ya quedaron duplicados.
- Quiero cargar una base sin RUT y definir reglas de fusión en orden (RUT, nombre, dirección), cada una exacta o flexible, y decidir yo los casos flexibles.
- Quiero cargar una base que no trae RUT en una **base provisoria**, separada de la definitiva, y verla en su propia pantalla.
- Quiero completarle el RUT a una empresa provisoria (una por una o con un archivo), o fusionarla con una empresa existente, para pasarla a la base definitiva.

**Jefe de estudio**
- Al exportar una muestra, quiero elegir qué atributos, números y contactos van en el archivo (por defecto, todos).
- Quiero incluir la base provisoria en un sorteo cuando el estudio lo necesite.

**Todos**
- Quiero que los contadores de Inicio y del menú coincidan con las listas a las que llevan.
- Quiero ver en la línea de tiempo de la empresa los contactos que se agregaron o editaron, y desde qué ingesta.

## 6. Requisitos

Notación: **[n]** es el número del pedido original.

### Fase 1 — Errores y ajustes rápidos

#### F1.1 Contador de muestras activas [11]

- En Inicio, el indicador cuenta `muestra.estado = 'activa'`. Hay dos causas probables de que siga mostrando una muestra después de «borrarla»:
  - **Causa A:** se borraron todas sus empresas (borrar empresa o borrar carga), pero la muestra sigue existiendo, activa y con 0 ítems.
  - **Causa B:** la tarea de «Borrar muestra» no terminó.
- **Cambios:**
  - el número es un enlace a una lista de las muestras activas (estudio, nombre, ítems, fecha de sorteo);
  - las muestras activas sin ítems se muestran como «activa, sin empresas» y se pueden cerrar o borrar desde ahí;
  - si una tarea «Borrar muestra» queda en error o cancelada, la muestra lo indica en su detalle.
- **Criterios de aceptación:**
  - [ ] Después de «Borrar muestra» (tarea ok), el contador baja.
  - [ ] Una muestra activa con 0 ítems aparece en la lista con su aviso.

#### F1.2 Contador de intermediarios [14]

- **Causa confirmada:** el contador del menú y el de Inicio cuentan `telefono.intermediario = 'sospechoso'` sin mirar los vínculos. La lista (`intermediarios.sospechosos`), en cambio, solo muestra los teléfonos con empresas activas. Al borrar todas las empresas, quedaron 2 teléfonos marcados como sospechosos sin empresas.
- **Cambios:**
  - los contadores usan el mismo criterio que la lista;
  - después de borrar empresas, deshacer o borrar una carga, o fusionar, se reevalúan los teléfonos afectados. Si un sospechoso queda con menos RUTs que el umbral, vuelve a «sin marca», y el cambio queda en Auditoría (`telefono.sospechoso_retirado`). Los confirmados no se tocan, porque son una decisión humana.
- **Criterios de aceptación:**
  - [ ] Con todas las empresas borradas, el contador de intermediarios muestra 0.
  - [ ] Un teléfono con 5 RUTs (umbral 5) al que se le borra una empresa deja de ser sospechoso.

#### F1.3 «Empresas de la muestra», paginada [12]

- La sección «Ítems» del detalle de la muestra pasa a llamarse **«Empresas de la muestra»**.
- Muestra 50 filas por página, con el total arriba, y filtros por estrato, rol, liberado y estado en cada parte, más búsqueda por RUT, razón social o `EC_ID_ITEM`.
- Hoy `muestras.items` corta en 500 filas: se reemplaza por paginación del lado del servidor (`pagina`, `por_pagina`, `total`).
- **Criterio de aceptación:**
  - [ ] Una muestra de 1.200 ítems se recorre completa en 24 páginas, y los filtros se mantienen al cambiar de página.

#### F1.4 Búsqueda por `EC_ID_ITEM` [13]

- En Empresas, el buscador acepta `#1234` o `item:1234` y busca por `muestra_item.id`. El resultado lleva a la ficha, en la pestaña Muestras, con esa fila resaltada.
- La búsqueda por RUT no cambia.
- **Criterio de aceptación:**
  - [ ] `#1234` abre la empresa del ítem 1234; un número sin `#` sigue buscando por RUT.

#### F1.5 Atributos opcionales y clave automática [3] [4] [8]

- Para crear un atributo **solo son obligatorios el nombre y el tipo**. Las opciones de un atributo de lista pueden quedar vacías: se completan en la carga, con la traducción de valores. Sinónimos, «filtro» y «estrato» son opcionales.
- Ningún flujo exige completar un atributo: la carga, la ficha, el .sav y el sorteo funcionan con atributos sin valor (en filtros y estratos, «sin dato»).
- **La clave se genera sola** a partir del nombre: minúsculas, sin tildes, guiones bajos y 40 caracteres como máximo. Si ya existe, se agrega `_2`, `_3`… Ya no se pide en la pantalla ni en la carga. Se muestra como dato de solo lectura y no cambia aunque después se cambie el nombre.
- **Criterios de aceptación:**
  - [ ] Crear «Cantidad de empleados» genera la clave `cantidad_de_empleados`; crear otro atributo con el mismo nombre genera `cantidad_de_empleados_2`.
  - [ ] La API sigue aceptando una clave explícita (para scripts), pero la web nunca la pide.

### Fase 2 — Lo que trae el .sav

#### F2.1 Número usado y número adicional verificados [1] [2] [15]

`resultados.aplicar` pasa a hacer esto:

| Variable | Tratamiento |
|---|---|
| `EC_TEL_USADO` (número con el que se habló) | Si no existe, se crea el teléfono. Se vincula a la empresa con origen `sala` y el vínculo queda **verificado**. Si ya estaba vinculado en otro estado, pasa a verificado (con historia de vínculo, fuente `sala` y el linaje de la fila). |
| `EC_TEL_ALT` (número adicional) | Igual: se crea si no existe, se vincula con origen `sala` y queda **verificado**. |
| `EC_CALIDAD_TEL` | Sigue funcionando como hoy (intermediario, inexistente, cerró). Ver la pregunta abierta Q1 sobre qué hacer si en la misma fila dice «no corresponde» para el número usado. |

- **Prefijos:** los números se normalizan con los prefijos de salida de la configuración. Así un número sin 0 inicial (por ejemplo `99123456`) se interpreta como celular uruguayo.
- **Motivo por fila:** cada fila del .sav guarda en `sav_fila.aplicado` (o en un campo nuevo `avisos`) por qué no se aplicó algo:
  - «fila sin ítem asociado: en Conciliación»;
  - «EC_TEL_USADO no normalizable: "xxxx"»;
  - «EC_TEL_ALT vacío».

  El detalle de la ingesta lista esos motivos con conteos y filas de ejemplo.
- **Conciliación:** al resolver una fila en Conciliación, se aplica completa. Hoy ya se aplica; hay que verificar que el teléfono y el contacto también se apliquen.
- **Criterios de aceptación:**
  - [ ] Una fila con `EC_TEL_USADO` = un número que no está en la base crea el teléfono, lo vincula a la empresa y lo deja verificado con origen Sala.
  - [ ] Una fila con un `EC_TEL_USADO` que ya estaba vinculado «sin verificar» lo pasa a verificado.
  - [ ] Una fila con `EC_TEL_ALT` deja ese número verificado.
  - [ ] Una fila sin ítem no aplica nada y el detalle de la ingesta dice «sin ítem asociado»; al conciliarla se aplica.
  - [ ] Volver a ingerir el mismo .sav no duplica nada (es idempotente, como hoy).

#### F2.2 El contacto queda relacionado con el número por el que se habló [2]

- Tabla nueva **`contacto_telefono`**: `contacto_id`, `telefono_id`, `fuente_tipo`, `fuente_id`, `primera_vez`, `ultima_vez`, `veces`. Reemplaza el uso de `telefono_vinculo.contacto_id`, que solo admite un contacto por número. Hay que migrar los datos existentes.
- El .sav, cuando trae `EC_RESP_NOMBRE` y `EC_TEL_USADO`, registra o actualiza esa relación con la fecha de la fila. Si también trae `EC_TEL_ALT`, ese número se relaciona con el contacto como «número del contacto».
- **En la ficha, pestaña Contactos:** columna **«Teléfonos»**, con cada número y la leyenda «se habló el dd/mm/aaaa (estudio, parte)» o «número del contacto».
- **Criterio de aceptación:**
  - [ ] Después de la ingesta, el contacto muestra «se habló el … al 2xxx xxxx (Estudio X, Parte A)».

#### F2.3 Toda fila del .sav es una encuesta completa [16]

**Cómo funciona hoy:**
- El resultado sale de la variable que el mapeo asigna al destino «resultado». Se reconoce sola si se llama `EC_RESULTADO` o `resultado`.
- Sus códigos no son fijos: el mapeo los traduce a completa, parcial, rechazo, etcétera, con una sugerencia a partir de la etiqueta del valor (por ejemplo, una etiqueta con «complet»).
- Si no hay `EC_RESULTADO`, se usa la columna `status` de Alchemer («Complete» → completa).
- **Si ninguna de las dos está mapeada, la fila queda sin resultado.** Entonces:
  - no marca el ítem como completo;
  - no cuenta como encuesta hecha;
  - no actualiza el último contacto efectivo, así que la empresa no entra en enfriamiento.

  Es lo más probable que haya pasado en tu ingesta.

**Cambio (D-b):**
- **Toda fila del .sav es una encuesta completa.** El destino «resultado» y el status de Alchemer **se quitan del mapeo**: ya no se piden ni se usan para decidir el estado.
- Por cada fila con response_id:
  - si está **asociada a un ítem**, el estado del ítem en esa parte pasa a **«completa»**, con el encuestador, la fecha (`datesubmitted`) y el teléfono usado;
  - la empresa actualiza su **último contacto efectivo** con la fecha de la fila (para el enfriamiento), haya o no un valor de `contacto_efectivo` en la configuración;
  - **cuenta como encuesta completa** en todos los indicadores, esté o no asociada.
- Si un ítem tenía otro estado (por ejemplo, «en curso» marcado a mano o por una ingesta anterior), pasa a «completa». «Completa» es el estado más avanzado y no se pisa con otro.
- Una fila sin response_id no cuenta y se informa en la ingesta, como hoy.

**Dónde se ve:**
- Tablero de Actividad: «Encuestas completas» = filas del .sav asociadas + sin asociar, con el desglose y un enlace a Conciliación para las sin asociar.
- Por encuestador, con `EC_ENCUESTADOR` de la fila; si no viene, «(sin encuestador)».
- Detalle del estudio, por parte.
- Detalle de la ingesta: el total de completas = filas con response_id.

Los filtros de estudio y muestra toman las filas del .sav de las partes de ese estudio, sin depender del ítem. Para el período se usa la fecha de la fila.

**Migración de lo ya ingerido:** un **remapeo** de las ingestas existentes («Volver a aplicar», que ya existe como `sav.remapear`) aplica la regla nueva: marca completos los ítems, actualiza el último contacto efectivo y verifica los teléfonos usados. La guía de despliegue indica hacerlo con las ingestas que ya están cargadas.

**Criterios de aceptación:**
- [ ] Un .sav **sin** variable de resultado ni `status`, con 30 filas (25 asociadas, 5 no), muestra 30 en «Encuestas completas» (25 + 5 sin asociar). Los 25 ítems quedan «completa» en esa parte y sus empresas tienen el último contacto efectivo actualizado.
- [ ] El mapeo del .sav ya no pide «resultado» ni «estado de Alchemer».
- [ ] Al conciliar las 5, el total sigue en 30 y el desglose pasa a 30 + 0.
- [ ] Volver a aplicar una ingesta anterior marca como completos sus ítems.

#### F2.4 Línea de tiempo con contactos y lo que trajo el .sav [20]

- `linea_de_tiempo` suma eventos de:
  - contactos: alta, edición (qué cambió), borrado y fuente (carga #, ingesta # con estudio y parte, manual con usuario);
  - relación contacto–teléfono: «se habló con Ana Gómez al 2xxx»;
  - atributos de contacto.
- Para eso se necesita **historia de contactos**: tabla `contacto_historia` (append-only, con la misma excepción de purga que la historia de empresa) con `contacto_id`, `campo`, `valor`, `fuente_tipo`, `fuente_id`, `actor`, `detalle` y `fecha`. Se migran como «alta» los contactos que ya existen.
- Los eventos de una misma ingesta .sav se agrupan en una línea desplegable: «Ingesta .sav #12 (Estudio X, Parte A): 1 contacto nuevo, 1 teléfono verificado, ítem completo».
- **Criterio de aceptación:**
  - [ ] Después de una ingesta que agregó un contacto y verificó un número, la línea de tiempo muestra el grupo de la ingesta con los dos eventos.

### Fase 3 — Contactos completos

#### F3.1 Alta, edición y borrado manual [6] [7]

- **Pestaña Contactos de la ficha:** botones **«+ Agregar contacto»**, **«Editar»** y **«Borrar»** por fila, para los roles admin y data steward.
- **Campos del contacto:** nombre (obligatorio), cargo, área, email (con validación de formato), sucursal (opcional), teléfonos (elegir de los de la empresa o agregar uno nuevo, que se vincula como manual) y atributos de contacto (F3.3).
- **Edición:** cada campo que cambia queda en `contacto_historia` con fuente `manual` y el usuario.
- **Borrado:** es **definitivo** (dato personal, Ley 18.331). Se borran el contacto, sus relaciones con teléfonos y sus atributos, y su «no llamar» por contacto. En Auditoría queda `contacto.borrar` con el RUT de la empresa y el id del contacto, **sin el nombre**. La historia del contacto se borra con la excepción de purga (migración 0007).
- **Duplicados:** si al agregar un contacto el nombre normalizado coincide con uno existente de la misma empresa, se avisa y se ofrece editar el existente.
- El rol de lectura sigue viendo «(dato personal oculto)».
- **Criterios de aceptación:**
  - [ ] Un steward agrega, edita y borra un contacto. La línea de tiempo muestra el alta y la edición; Auditoría registra el borrado sin el nombre.
  - [ ] Un coordinador o un usuario de lectura no ve los botones y recibe 403 en la API.

#### F3.2 Contactos en la carga [6] (D-d)

- El mapeo de la carga suma un **bloque «Contacto»**:
  - campos: nombre, cargo, área, email, teléfono del contacto y atributos de contacto;
  - **un contacto por fila** (P1: varios contactos por fila con columnas numeradas).
- Se quita el aviso actual («los campos de contacto se ignoran»). Las plantillas viejas con campos de contacto pasan a usarlos.
- **Reglas:**
  - el contacto se identifica dentro de la empresa por nombre normalizado o por email;
  - si ya existe, se completan los campos vacíos, igual que hoy con el .sav;
  - el teléfono del contacto se vincula a la empresa con el origen de la fila y se relaciona con el contacto (`contacto_telefono`, como «número del contacto»).
- **Preview:** contactos nuevos, contactos actualizados y filas con contacto sin nombre (se ignoran, con aviso).
- **Deshacer y borrar una carga** quita los contactos que trajo, como ya pasa con los vínculos.
- **Criterio de aceptación:**
  - [ ] Una base con columnas «Contacto», «Cargo», «Email» y «Tel. contacto» crea los contactos, relaciona sus teléfonos, y deshacer la carga los quita.

#### F3.3 Atributos de contacto [10]

- El catálogo de atributos suma un **ámbito**: `empresa` o `contacto`. En Administración → Atributos aparecen dos pestañas: «De empresa» y «De contacto». Valen las mismas reglas de F1.5 y F4.1: clave automática, sinónimos y normalización.
- Valores en la tabla `contacto_atributo`, con historia en `contacto_historia` (campo `atributo.<clave>`).
- **Se cargan desde:**
  - la carga (bloque Contacto);
  - el .sav: en el mapeo del .sav, además de las variables `EC_*`, se puede asociar cualquier variable a un atributo de contacto, con la misma traducción de valores que en la carga para los de lista;
  - la ficha (F3.1).
- Se pueden exportar (F5.1). No se usan para filtrar ni estratificar el sorteo (P2).
- **Criterio de aceptación:**
  - [ ] Un atributo de contacto «Decisor (Sí/No)» se carga desde el .sav mapeando la variable `Q12` y aparece en la ficha del contacto.

### Fase 4 — Normalización de atributos

#### F4.1 Atributos parecidos en la carga [5]

- **Al proponer el mapeo**, cada columna que no reconoce exactamente se compara contra los nombres y sinónimos de los atributos del ámbito (empresa o contacto). La comparación normaliza (minúsculas, sin tildes, puntuación ni palabras vacías como «de», «la», «cant.») y usa similitud de trigramas (`pg_trgm`, umbral configurable, 0,6 por defecto).
  - Si hay un atributo parecido, la web lo sugiere: «"Cant. empleados" se parece a **Cantidad de empleados** (82 %). ¿Usar ese atributo?». Al aceptar, el nombre de la columna se agrega como sinónimo.
- **Al crear un atributo nuevo** desde la carga («+ Agregar atributo») o desde Administración, si hay uno parecido, se avisa y se ofrece usarlo.
- **Valores de los atributos de lista:**
  - se comparan sin distinguir mayúsculas, tildes ni espacios: «montevideo», «MONTEVIDEO» y «Montevideo » son la misma opción, y se guarda la forma del catálogo;
  - los valores parecidos pero no iguales («Exportadora» y «Exportador») aparecen en la traducción de valores con la sugerencia.
- **Atributos de texto:** se recortan los espacios. Por atributo se puede elegir «normalizar a Mayúscula inicial», «MAYÚSCULAS» o «sin cambios» (por defecto, sin cambios).
- **Criterios de aceptación:**
  - [ ] Una columna «Cant. Empleados» en una base nueva sugiere el atributo existente «Cantidad de empleados».
  - [ ] Los valores «SI», «si» y «Sí» de una lista con la opción «Sí» se cargan como «Sí» sin pedir traducción.

#### F4.2 Fusionar atributos [5]

- En Administración → Atributos, **«Fusionar con…»** fusiona el atributo A dentro de B, siempre que sean del mismo ámbito y de tipos compatibles:
  - los valores de A pasan a B como historia nueva (fuente `fusion`, con `detalle.fusionado_de = A`), y se recalcula el valor vigente de B;
  - los nombres y sinónimos de A se agregan a los sinónimos de B, y las opciones de lista se unifican;
  - A queda inactivo, con la nota «fusionado en B».
- **Bloqueo:** no se puede fusionar si A se usa como filtro o estrato de una muestra activa (se avisa cuál).
- Queda en Auditoría (`atributo.fusionar`).
- **Criterio de aceptación:**
  - [ ] Después de fusionar «Empleados» en «Cantidad de empleados», las empresas que solo tenían «Empleados» muestran el valor en «Cantidad de empleados», y una carga nueva con la columna «Empleados» se mapea sola a B.

### Fase 5 — Exportación configurable

#### F5.1 Elegir atributos, números y contactos al exportar [17]

- Al exportar una muestra, un panel **«Qué incluir»** guarda la elección en `muestra.exportacion`. Por defecto está todo marcado:
  - **Atributos de empresa:** uno por uno, con «todos» y «ninguno».
  - **Números:** todos los discables (como hoy, con los filtros de origen y orden ya existentes) y, opcionalmente, «incluir también no verificados» (por defecto, solo discables).
  - **Contactos:** nombre, cargo, área, email, teléfonos del contacto y atributos de contacto. **Solo aparece para usuarios con el permiso «exportar contactos»** (ya existe por usuario). Sin ese permiso, los contactos no se exportan aunque estén guardados en la muestra.
- **Formatos:**
  - **«uContact»** (actual): un renglón por teléfono, con las columnas de siempre más las elegidas. Los contactos van en columnas `contacto_1_*`, `contacto_2_*`… (hasta 3 por defecto, configurable).
  - **«Planilla de la muestra»** (nuevo): un renglón por empresa, con los teléfonos en `tel_1…tel_n`, sus orígenes, los atributos y los contactos.
- Cada exportación registra en Auditoría las columnas incluidas.
- **Criterios de aceptación:**
  - [ ] Sin tocar nada, el CSV de uContact incluye todos los atributos activos y, para quien tiene el permiso, los contactos.
  - [ ] Si se desmarca un atributo, la elección queda guardada para la próxima exportación de esa muestra.
  - [ ] Un usuario sin permiso de contactos no ve esa sección y su CSV no los trae.

### Fase 6 — Identidad: base provisoria (empresas sin RUT) y reglas de fusión en cascada

#### F6.1 Base provisoria: empresas sin RUT [18] (D-c)

**Concepto:** el sistema maneja **dos bases**:

- la **base definitiva**: empresas con RUT válido, como hoy;
- la **base provisoria**: empresas que **no traen RUT**.

La provisoria se carga, se consulta y se depura por separado. Sus empresas se pueden sortear y llamar (D-c). Una empresa pasa a la definitiva cuando se le agrega el RUT o cuando se fusiona con una empresa de la definitiva.

**Modelo:**
- Para no duplicar teléfonos, contactos, muestras, CDR y .sav, las dos bases comparten la tabla `empresa`, con una columna nueva **`base`** (`definitiva` | `provisoria`).
- `empresa.rut` admite NULL **solo** en la provisoria. La regla es un CHECK: `base = 'provisoria' OR rut IS NOT NULL`. La unicidad sigue igual para los RUT no nulos.
- Cada empresa provisoria tiene un **código provisorio** visible: **`P-` + id** (por ejemplo, `P-004213`). Sirve en la URL de la ficha, en el buscador, en la exportación y en el .sav.
- Si la fila traía algún identificador que no es un RUT válido (una cédula, un número de BPS, un «RUT» de 7 dígitos), se guarda como atributo de sistema **`id_informado`**, para no perderlo.

**Carga a la base provisoria:**
- Al crear una carga se elige el **destino**: **«Base definitiva»** (como hoy: la columna RUT es obligatoria) o **«Base provisoria»** (la columna RUT es opcional). El destino queda en la carga y en la plantilla.
- En una carga a la base provisoria, las filas **no se rechazan por falta de RUT**. Cada fila pasa por las reglas de fusión (F6.2), que comparan contra **las dos bases**:
  - si coincide con una empresa de la **definitiva**, actualiza esa empresa (no se crea una provisoria);
  - si coincide con una **provisoria**, actualiza esa provisoria;
  - si no coincide con ninguna, se da de alta en la provisoria.
- Si una fila trae un **RUT válido**, se aplican las reglas como en una carga a la definitiva, y la fila entra o actualiza la **base definitiva**. Una opción de la carga, activada por defecto, permite desactivarlo para dejar todo en la provisoria.
- En una carga a la **base definitiva**, una opción **«Enviar las filas sin RUT válido a la base provisoria»** (desactivada por defecto) evita rechazarlas. Con esa opción, la fila del «RUT con 7 dígitos» habría entrado a la provisoria, con ese número en `id_informado`.
- El preview muestra por separado: altas en la definitiva, altas en la provisoria, actualizaciones de cada base y coincidencias a decidir.

**Pantalla «Base provisoria»** (menú Base de datos, para data steward y admin):
- Lista de empresas provisorias con código, razón social, departamento, teléfonos, carga de origen, muestras en las que está y **candidatas en la definitiva** (por las reglas flexibles, con su similitud).
- Acciones por empresa:
  - **«Agregar RUT»**;
  - **«Fusionar con…»**: elegir una empresa de la definitiva entre las candidatas o buscándola;
  - **«Es otra empresa»**: descarta las candidatas.
- **Completar RUT por archivo:** se sube un CSV con `codigo_provisorio;rut` (o con columnas que permitan aplicar las reglas de fusión) y se procesa como una carga, con preview.
- Contadores en Inicio: «Base provisoria: N empresas, M con candidatas en la definitiva». La cifra «Empresas» de Inicio sigue contando solo la definitiva.

**Uso de las provisorias:**
- **Buscador de Empresas:** filtro **«Base: definitiva / provisoria / ambas»** (por defecto, definitiva). La ficha de una provisoria muestra la etiqueta **«Provisoria»** y las acciones para pasarla a definitiva.
- **Sorteo:** cada muestra tiene un criterio **«Incluir la base provisoria»**. Ver Q2 sobre el valor por defecto. Las provisorias entran al marco con su estrato, y se les aplican igual el enfriamiento, el «no llamar» y las demás reglas de disponibilidad.
- **Exportación:** `EC_RUT` vacío y columna nueva `EC_ID_EMPRESA` con el código provisorio. El link de Alchemer lleva `EC_ID_ITEM`, como hoy, así que el .sav se asocia por ítem igual.
- **.sav:** si la fila de una provisoria trae un `EC_RUT` válido, se propone completar el RUT. No se aplica solo: queda como candidata en la pantalla «Base provisoria», para confirmar.

**Pasar a la definitiva:**
- **Agregar el RUT** (desde la ficha, la pantalla «Base provisoria», un archivo o el .sav):
  - si el RUT es válido y no existe, la empresa pasa a `base = 'definitiva'`;
  - si ya existe, se ofrece **fusionar** la provisoria dentro de la empresa que tiene ese RUT.
- **La fusión** usa la fusión existente, que es reversible. Mueve teléfonos, contactos, sucursales, atributos e historia. Los **ítems de muestra** y los **intentos** siguen apuntando a la provisoria absorbida y se ven desde la absorbente, igual que hoy con el último contacto efectivo. Así no se rompe la reproducibilidad del sorteo.
- Todo paso a la definitiva queda en la historia de la empresa y en Auditoría (`empresa.promover`, `empresa.fusionar`).

**Criterios de aceptación:**
- [ ] Una base de 100 filas **sin columna RUT**, cargada con destino «Base provisoria», crea hasta 100 empresas provisorias con código `P-`. Las filas que coinciden con empresas existentes las actualizan en lugar de crear provisorias.
- [ ] En esa misma carga, una fila con RUT válido entra a la base definitiva.
- [ ] Una carga a la base definitiva sin la opción de enviar a la provisoria sigue rechazando las filas sin RUT, como hoy. Con la opción, esas filas entran a la provisoria.
- [ ] La pantalla «Base provisoria» lista las provisorias con sus candidatas. «Agregar RUT» con un RUT nuevo la pasa a la definitiva, y con un RUT existente ofrece fusionar.
- [ ] La cifra «Empresas» de Inicio no cuenta las provisorias, que tienen su propio contador.
- [ ] Una muestra con «Incluir la base provisoria» sortea provisorias. El CSV trae `EC_ID_EMPRESA` y el .sav se asocia por `EC_ID_ITEM`.
- [ ] Después de fusionar una provisoria con una empresa definitiva, la definitiva muestra las muestras y las llamadas de la provisoria.

#### F6.2 Reglas de fusión en cascada, exactas o flexibles [19]

- **Configuración por carga** (y guardada en la plantilla): una **lista ordenada de reglas**, cada una con un criterio y un tipo.
  - **Criterios:** `rut`, `razon_social`, `telefono`, `dominio_web`, `direccion` (dirección normalizada más departamento) y `email` (de contacto). Más adelante, cualquier atributo marcado como identificador (P2).
  - **Tipo:**
    - **exacta:** coincidencia después de normalizar (sin tildes, mayúsculas, puntuación ni sufijos societarios como «S.A.» o «SRL» en la razón social; dígitos para el teléfono);
    - **flexible:** similitud igual o mayor que un umbral configurable por regla (por defecto 0,85), con `pg_trgm`.
  - Valor por defecto: `[rut exacta]` (equivale al comportamiento actual). Reemplaza el campo único `carga.regla_fusion`; las cargas existentes se migran como una lista de una regla.
- **Funcionamiento por fila:** se prueban las reglas en orden y gana la primera que da resultado.
  - **Exacta con una sola candidata:** se fusiona sola.
  - **Exacta con varias candidatas:** pasa a revisión.
  - **Flexible:** **siempre se consulta.**
  - **Ninguna regla aplica:** alta como empresa nueva. Si la fila no tiene RUT, se da de alta en la base provisoria cuando el destino de la carga es la provisoria, o cuando está activa la opción de enviar las filas sin RUT; si no, se rechaza.
  - **Las reglas comparan contra las dos bases**, la definitiva y la provisoria.
- **Consulta al usuario en la carga:**
  - el preview tiene un paso nuevo, **«Coincidencias a decidir»**, con cada fila y su candidata lado a lado: datos de la fila, datos de la empresa, regla y porcentaje de similitud;
  - por fila se elige «Fusionar», «Es otra empresa» o «Decidir después»;
  - hay acciones masivas («fusionar todas las de similitud ≥ 95 %», «ninguna»);
  - lo que queda en «Decidir después» va a la bandeja de **Revisión de fusiones** existente (`revision_fusion`, con el criterio y la similitud).
- **La confirmación usa las decisiones** tomadas en el preview, y quedan en el linaje de la carga.
- **Criterios de aceptación:**
  - [ ] Con las reglas `[rut exacta, razón social flexible 0,85, dirección exacta]`, una fila sin RUT con «PEREZ HNOS SA» frente a «Pérez Hnos. S.A.» aparece en «Coincidencias a decidir» con su porcentaje; si se elige «Fusionar», se actualiza esa empresa.
  - [ ] Una fila cuyo RUT coincide se fusiona sola sin consultar, aunque otra regla posterior también coincida.
  - [ ] Las decisiones pendientes terminan en Revisión de fusiones.
  - [ ] Deshacer la carga revierte también las fusiones decididas en ella.

### Transversal

- **Migraciones:**
  - `0009_*`: `contacto_telefono`, `contacto_historia`, `contacto_atributo`, ámbito de atributo, `pg_trgm` e índices de similitud;
  - `0010_*`: base provisoria (`empresa.base`, `rut` nulo solo en la provisoria, destino de la carga) y reglas de fusión.
  - Las dos deben ser compatibles hacia atrás.
- **Tests** para cada criterio de aceptación. La suite completa sigue pasando.
- **Decisiones:**
  - D39: toda fila del .sav es una encuesta completa (sin variable de resultado), con verificación del número usado y conteo sin depender del ítem;
  - D40: los contactos como entidad (cargas, manual, atributos, borrado definitivo);
  - D41: normalización y fusión de atributos;
  - D42: la base provisoria (empresas sin RUT, sorteables);
  - D43: reglas de fusión en cascada.
  - Además, actualizar en D-d la decisión anterior sobre contactos en las cargas.
- **Manual de usuario:** secciones nuevas por fase. Regenerar el Word y el PDF.

## 7. Métricas de éxito

| Métrica | Cómo se mide | Meta |
|---|---|---|
| Teléfonos verificados por la sala | Vínculos verificados con fuente `sala` después de cada ingesta | 100 % de las filas asociadas con `EC_TEL_USADO` normalizable |
| Filas .sav no aplicadas sin motivo | Filas sin motivo en el detalle de la ingesta | 0 |
| Diferencia entre completas del .sav y de Actividad | Comparación por parte | 0 |
| Atributos duplicados creados en cargas | Atributos nuevos con similitud ≥ 0,6 a uno existente, en 30 días | 0 |
| Empresas de la base provisoria que pasan a la definitiva | % de provisorias con RUT o fusionadas, a los 90 días de cargadas | Línea de base en la primera carga; meta a definir |
| Fusiones flexibles decididas en la carga | % de coincidencias flexibles resueltas antes de confirmar | ≥ 80 % |

## 8. Fases y orden de implementación

Cada fase se puede mergear y desplegar sola.

| Fase | Contenido | Por qué en ese orden | Despliegue |
|---|---|---|---|
| **1** | F1.1–F1.5 (errores, paginación, búsqueda, atributos opcionales y clave automática) | Rápida y desbloquea el uso diario | api, web |
| **2** | F2.1–F2.4 (.sav: teléfonos, contacto–teléfono, completas, línea de tiempo) | Lo que más afecta al campo en curso | api, migrar, web |
| **3** | F3.1–F3.3 (contactos completos y atributos de contacto) | Usa `contacto_historia` y `contacto_telefono` de la fase 2 | api, migrar, web |
| **4** | F4.1–F4.2 (normalización y fusión de atributos) | Aplica a los atributos de empresa y de contacto | api, migrar, web |
| **5** | F5.1 (exportación configurable) | Necesita contactos y atributos de contacto | api, web |
| **6** | F6.1–F6.2 (base provisoria y reglas en cascada) | Cambia el modelo de identidad: al final y con más pruebas | api, migrar, web |

Comandos por fase, siempre con la región explícita:

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh migrar   # fases 2, 3, 4 y 6
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Si ya está mergeado el fix de región, se usa `EMPRESAS_REGION=us-central1`. Después de cada fase, recargar con Cmd+Shift+R y recorrer los criterios de aceptación de esa fase con una carga y un .sav de prueba.

## 9. Riesgos

| Riesgo | Mitigación |
|---|---|
| Verificar números que la sala marcó mal | Queda el linaje (ingesta y encuestador) y el estado se puede corregir en la ficha. Ver Q1 sobre la calidad negativa explícita. |
| Fusiones flexibles erróneas | Nunca se aplican solas; quedan en el linaje de la carga y se revierten al deshacerla. |
| Provisorias duplicadas entre sí | Las reglas de fusión también comparan contra las provisorias. Hay un reporte de provisorias parecidas entre sí (P1). |
| Exportar datos personales sin permiso | Los contactos solo para usuarios con el permiso. Auditoría de columnas exportadas. |
| `rut` nulo rompe consultas que asumen RUT | El CHECK limita el `rut` nulo a la base provisoria. Revisar todas las consultas y vistas que usan `rut` (buscador, ficha por URL, exportación, .sav, fusión, indicadores) y agregar el filtro de base donde corresponda. Tests de regresión con provisorias. |
| Rendimiento de la similitud en cargas grandes | Índices GIN de trigramas sobre la razón social y la dirección normalizadas; comparación solo contra candidatos del mismo departamento cuando hay dato. |

## 10. Costo

**Ninguno adicional en infraestructura.** `pg_trgm` es una extensión incluida en Cloud SQL para PostgreSQL. Las tablas nuevas y la similitud corren en la misma instancia (db-f1-micro). Si las cargas con reglas flexibles sobre bases de más de 50.000 filas resultan lentas, la opción sería subir la instancia a db-g1-small. Eso cuesta unos USD 25–30 por mes adicionales y **no se recomienda hasta medirlo**.

## 11. Preguntas abiertas

| # | Pregunta | Quién | ¿Bloquea? |
|---|---|---|---|
| Q1 | Si una fila trae en `EC_CALIDAD_TEL` «no corresponde», «inexistente» o «intermediario» para el número usado, ¿gana la calidad (el número **no** queda verificado) o igual se verifica? Este spec asume que **gana la calidad explícita**, por ser la información más específica. | Germán | Fase 2 |
| Q2 | En el sorteo, ¿«Incluir la base provisoria» viene **marcado o desmarcado** por defecto? Este spec propone desmarcado, para no cambiar sin querer el marco de los estudios en curso. | Germán / jefes de estudio | Fase 6 |
| Q3 | ¿Qué otros criterios de fusión hacen falta además de RUT, razón social, teléfono, dominio, dirección y email? | Data steward | No |
| Q4 | ¿Cuántos contactos por empresa como máximo en el CSV de uContact (por defecto 3)? | Coordinación de campo | No |
