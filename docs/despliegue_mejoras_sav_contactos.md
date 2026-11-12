# Despliegue: .sav, contactos, atributos, exportación y base provisoria

Este documento lleva a producción [`specs/SPEC_mejoras_sav_contactos_atributos_identidad.md`](../specs/SPEC_mejoras_sav_contactos_atributos_identidad.md) en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**. Las seis fases del spec vienen en un mismo PR (un commit por fase) y se despliegan juntas. Para una instalación desde cero alcanza con la [guía de despliegue](despliegue.md).

**Qué cambia para las personas** (detalle en el manual, guías 19 a 24):

| Fase | Qué cambia |
| --- | --- |
| 1 | El contador de **Muestras activas** lleva a su lista; el de **Intermediarios** coincide con la bandeja. **Empresas de la muestra** se recorre por páginas, con filtros. El buscador acepta **`#1234`** (EC_ID_ITEM). Un atributo se crea con **nombre y tipo**: la clave se genera sola. |
| 2 | **Toda fila del .sav es una encuesta completa.** El número usado y el adicional quedan **verificados**. El detalle de la ingesta dice qué no se aplicó, fila por fila. El contacto queda relacionado con el número por el que se habló. La línea de tiempo agrupa lo que trajo cada ingesta. |
| 3 | **Contactos completos:** agregar, editar y borrar en la ficha; bloque **Contacto** en la carga; **atributos de contacto** (desde la carga, el .sav o la ficha). |
| 4 | Al cargar, el sistema **sugiere el atributo parecido** en lugar de crear otro; los valores de lista no distinguen mayúsculas ni tildes; **«Fusionar con…»** junta dos atributos duplicados. |
| 5 | Al exportar una muestra, **«Qué incluir»** (atributos, números y contactos) y el formato nuevo **«Planilla de la muestra»**. |
| 6 | **Base provisoria** para empresas sin RUT (cargar, buscar, sortear, llamar, agregar el RUT o fusionar) y **reglas de fusión en cascada** con **«Coincidencias a decidir»** en el preview. |

**Tiempo estimado:** 30 a 40 minutos, más el reaplicado de las ingestas. **Costo:** ninguno adicional (`pg_trgm` viene con Cloud SQL; todo corre en la misma instancia).

## Antes de empezar

- Avisá que durante el despliegue no se confirmen cargas ni ingestas (unos 10 minutos).
- Las migraciones son compatibles hacia atrás: no borran nada. Todo lo que existe queda en la **base definitiva**, y cada carga anterior queda con su regla como una lista de una regla.

## Paso a paso

Los pasos van en este orden. `migrar` aplica dos migraciones: `0010_sav_contactos.sql` y `0011_base_provisoria.sql`.

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
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Si ya está mergeado el fix de región del script, la variable es `EMPRESAS_REGION=us-central1`. Si se usa IP fija para el CDR, `api` va con `IP_FIJA=1`, como siempre. Después, recargá la aplicación con **Cmd+Shift+R**.

**Qué hacen las migraciones:**

- `0010_sav_contactos.sql`:
  - `contacto_telefono` (contacto ↔ número; se migran los `telefono_vinculo.contacto_id` existentes) y `contacto_historia` (append-only; los contactos existentes entran como «alta»);
  - `sav_fila.avisos`, `sav_fila.fecha` y `sav_fila.encuestador`;
  - ámbito de atributo (`empresa` | `contacto`) y `contacto_atributo`;
  - la extensión **`pg_trgm`** y las columnas de normalización y fusión de atributos.
- `0011_base_provisoria.sql`:
  - `empresa.base`, `rut` nulo solo en la provisoria (CHECK) y la columna generada `codigo` (RUT o `P-000123`);
  - el atributo de sistema `id_informado`;
  - destino, reglas, opciones y decisiones de la carga (las cargas existentes se migran como `[rut exacta]` o `[rut exacta, su regla]`);
  - `carga_promocion`, `provisoria_descarte`, `provisoria_rut_propuesto` e índices de trigramas sobre razón social y dirección.

### Si `migrar` falla al crear `pg_trgm`

`pg_trgm` es una extensión «trusted»: la crea el usuario dueño de la base. Si el job de migración dice `permission denied to create extension "pg_trgm"`, creala una vez con el usuario `postgres` desde la consola:

1. En la consola de GCP, abrí **SQL → la instancia de la base → Cloud SQL Studio**, y entrá con el usuario `postgres` a la base `empresas`.
2. Ejecutá:

   ```sql
   CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA public;
   ```

3. Volvé a correr el paso `migrar`.

## Después del despliegue: reaplicar las ingestas del .sav

Las ingestas anteriores se ingirieron con la regla vieja (sin resultado mapeado, las filas no contaron). Para aplicarles la regla nueva — **ítems completos, último contacto efectivo actualizado y números usados verificados** — hay que reaplicarlas una por una. Es idempotente: no duplica nada.

1. Entrá con un usuario coordinador o administrador a **Ingesta .sav**.
2. Abrí cada ingesta de **Ingestas anteriores** (empezá por las de los estudios en curso).
3. Tocá **Corregir mapeo** y, sin cambiar nada, **Reaplicar con este mapeo**. El mapeo ya no muestra «resultado» ni «estado de Alchemer».
4. Al terminar, el detalle muestra **«N encuestas completas (filas con response_id): X asociadas a un ítem y Y sin asociar»** y la tarjeta **«Lo que no se aplicó, fila por fila»**.

## Verificación, fase por fase

Usá una carga de prueba y un .sav de prueba (por ejemplo, la demo de [`api/demo`](../api/demo)). Cada punto es un criterio de aceptación del spec.

**Fase 1**

1. En **Inicio**, tocá **Muestras activas**: lleva a la lista; una muestra activa sin empresas dice «activa, sin empresas» y se puede cerrar o borrar desde ahí.
2. El número de **Intermediarios** del menú coincide con la bandeja.
3. En una muestra, **Empresas de la muestra** pagina de a 50 y los filtros se mantienen al cambiar de página.
4. En **Empresas**, buscá `#` y un EC_ID_ITEM: abre la ficha en **Muestras** con la fila resaltada.
5. En **Administración → Atributos**, creá «Cantidad de empleados» solo con nombre y tipo: la clave queda `cantidad_de_empleados`.

**Fase 2**

1. Después de reaplicar una ingesta, en **Actividad** el número de **Encuestas completas** es igual a las filas del .sav (asociadas + sin asociar).
2. En la ficha de una empresa con encuesta, el número usado figura **verificado** con origen **Sala**, y la pestaña **Contactos** dice «se habló el … (Estudio, Parte)».
3. La **Línea de tiempo** tiene una línea «Ingesta .sav #…» desplegable con lo que trajo.

**Fase 3**

1. Con un data steward, en **Contactos** de una ficha: **+ Agregar contacto**, **Editar** y **Borrar**. En **Auditoría**, `contacto.borrar` no tiene el nombre.
2. Con un coordinador, los botones no aparecen.
3. Una carga con columnas «Contacto», «Cargo», «Email» y «Tel. contacto» crea los contactos; **Deshacer carga** los quita.

**Fase 4**

1. Una carga con la columna «Cant. Empleados» sugiere **Cantidad de empleados**; al aceptar, queda como sinónimo.
2. Valores «SI», «si» y «Sí» de una lista con la opción «Sí» se cargan sin pedir traducción.
3. **Fusionar con…** un atributo duplicado: sus valores aparecen en el que queda.

**Fase 5**

1. En una muestra activa, **Qué incluir**: desmarcá un atributo y volvé a abrir la muestra: sigue desmarcado.
2. Con un usuario sin permiso de contactos, la sección de contactos no aparece y el CSV no los trae.
3. **Formato → Planilla de la muestra** baja un renglón por empresa.

**Fase 6**

1. Una carga sin columna RUT con destino **Base provisoria** crea empresas con código `P-…`; las filas que coinciden con empresas existentes las actualizan.
2. En **Base provisoria**, **Agregar RUT** con un RUT nuevo la pasa a la definitiva; con un RUT que existe, ofrece fusionar.
3. **Inicio** muestra «Base provisoria» aparte; **Empresas activas** no la cuenta.
4. Con reglas `[RUT exacta, Razón social flexible 0,85]`, una fila «PEREZ HNOS SA» frente a «Pérez Hnos. S.A.» aparece en **Coincidencias a decidir**; **Decidir después** la manda a **Revisión de fusiones**.

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| `migrar` falla con `permission denied to create extension` | El usuario de la aplicación no puede crear `pg_trgm` | Crearla con `postgres` (ver arriba) y volver a migrar |
| «Encuestas completas» sigue en 0 para un estudio viejo | Sus ingestas no se reaplicaron | Reaplicar cada ingesta (ver arriba) |
| La ficha de una provisoria da 404 | La web quedó en caché | Recargar con Cmd+Shift+R |
| Un CSV de uContact trae columnas nuevas al final (`EC_ID_EMPRESA`, `atr_*`, `contacto_1_*`) | Es «Qué incluir» con todo marcado (por defecto) | Desmarcar en la muestra lo que no se quiera exportar; las columnas configuradas siguen primero y en el mismo orden |
| Una carga a la definitiva rechaza filas sin RUT | Es el comportamiento de siempre | Marcar «Enviar las filas sin RUT válido a la provisoria» o usar el destino «Base provisoria» |

**Volver atrás:** redirigir el tráfico de Cloud Run a la revisión anterior de la API y revertir la web en Firebase Hosting (ver [despliegue.md](despliegue.md), «Actualizaciones»). Las migraciones pueden quedar aplicadas: la versión anterior no usa las tablas ni las columnas nuevas. **Atención:** si ya se cargaron empresas provisorias (sin RUT), la versión anterior no las sabe mostrar; borralas o pasalas a la definitiva antes de volver atrás.
