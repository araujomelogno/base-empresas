# SPEC — Rendimiento con cientos de miles de empresas y estadísticas al terminar cada carga

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_rendimiento_base_grande.md`, para que Claude Code lo implemente y lo despliegue.
**Base:** `main` en `6303f86` (PR #24).
**Fecha:** 24/11/2026

---

## 1. Problema

Después de la primera carga grande (193.553 empresas, 2,1 millones de filas de historia, 795.000 atributos y 170.000 vínculos de teléfono), la aplicación se volvió lenta y empezó a fallar:

- **Empresas:** la pantalla da «Error». Según los logs del 24/11 (01:08–01:13 UTC):
  - `GET /api/empresas/valores` tarda entre **11 y 22 s**;
  - `GET /api/empresas?pagina=1` tarda **9 s**;
  - después, `GET /api/empresas` y `/api/naturalezas` fallan con **500 tras 30 s**: `psycopg_pool.PoolTimeout: couldn't get a connection after 30.0 sec`.
- **El resto:** Inicio, Naturalezas, Atributos, Estudios y otras pantallas fallan con el mismo PoolTimeout. Pasa sobre todo mientras corre una carga, y también después.
- **Las estadísticas no eran la causa.** Hasta un `ANALYZE` manual del 24/11 a las 01:24, Postgres seguía con estadísticas del 20/11 (`n_live_tup = 0`). Con las estadísticas al día, **la pantalla de Empresas sigue tardando más de 5 s**: el problema principal son las consultas.

**Causas, revisadas en el código:**

| Pantalla o endpoint | Qué hace hoy | Por qué es lento con este volumen |
|---|---|---|
| `GET /api/empresas` (`routers/empresas.py`, `buscar`) | Une con la vista **`v_empresa_disponible`**, que calcula la disponibilidad de **todas** las empresas con la función `bloqueos(cfg)`: enfriamiento, muestra activa, sin teléfono discable, no llamar, naturaleza excluida. Además hace `count(*) OVER ()` para el total, un **subselect por fila** para contar los teléfonos discables (`v_vinculo_discable`) y `ORDER BY razon_social … OFFSET`. | Para mostrar 50 empresas evalúa las reglas de 193.553 y cuenta el total en cada pedido. |
| `GET /api/empresas/valores` | Tres `SELECT DISTINCT` sobre `empresa` (departamento, tamaño, CIIU a 2 dígitos) en cada apertura de la pantalla, y también en el armado de muestras. | Recorre la tabla entera tres veces en cada visita. |
| `GET /api/naturalezas` (`routers/admin.py`, `_USO_NATURALEZA`) | Para **cada** naturaleza del catálogo cuenta las empresas dos veces y además `empresa_campo_historia WHERE campo = 'naturaleza' AND valor = codigo`. | Con unas 20 naturalezas son unos 20 recorridos de 2,1 millones de filas de historia, porque no hay índice por (`campo`, `valor`). |
| `GET /api/inicio` | Cuenta las empresas disponibles con `v_empresa_disponible` y otros totales. | El mismo cálculo de disponibilidad para toda la base en cada visita. |
| Pool de la API | 5 conexiones por instancia y 30 s de espera; las consultas no tienen tiempo máximo. | Dos o tres consultas lentas ocupan el pool, y el resto de la aplicación falla con PoolTimeout. |

**Además, la base de Cloud SQL más chica (`db-f1-micro`, CPU compartida) amplifica todo:** las mismas consultas que en un servidor dedicado tardan menos de 1 s, acá tardan entre 10 y 20.

## 2. Objetivos

Con 200.000 empresas y la base actual (`db-f1-micro`):

1. **Empresas** (lista con filtros, página 1 o cualquier otra) responde en **menos de 1,5 s**. Los valores de los filtros, en **menos de 300 ms**.
2. **Inicio, Naturalezas, Atributos, Cargas y Estudios** responden en **menos de 1,5 s**.
3. **Cero errores PoolTimeout** en el uso normal y **mientras corre una carga**. Si una consulta igual tarda demasiado, la web muestra un mensaje claro en lugar de «Error».
4. **Después de cada carga, deshacer o borrado grande**, las estadísticas de la base quedan al día **sin intervención manual**.

## 3. Fuera de alcance

- **Agrandar Cloud SQL.** Queda como recurso si no se cumplen los objetivos (sección 9).
- **Cambiar las reglas de disponibilidad.** El resultado tiene que ser el mismo; solo cambia cuándo y cómo se calcula.
- **Búsqueda de texto completo o difusa en el buscador.** Sigue siendo por RUT, por razón social o fantasía con `ILIKE`, y por filtros.

## 4. Historias de usuario

- Como **cualquier usuario**, quiero abrir Empresas y filtrar sin esperas, aunque la base tenga cientos de miles de empresas.
- Como **data steward**, quiero seguir usando la aplicación mientras corre una carga grande.
- Como **jefe de estudio**, quiero que los valores de los filtros del sorteo aparezcan al instante.
- Como **administrador**, no quiero tener que entrar a `psql` a correr `ANALYZE` después de una carga.

## 5. Requisitos (P0)

### P-1. Estadísticas al terminar cada operación grande (pedido explícito)

- **Al terminar** una confirmación de carga, un deshacer, un borrado de carga, de estudio o de muestra, o una corrida de enriquecimiento o de descubrimiento, se ejecuta **`ANALYZE`** sobre las tablas que la operación tocó: `empresa`, `empresa_campo_historia`, `empresa_atributo`, `telefono`, `telefono_vinculo`, `telefono_vinculo_origen`, `contacto`, `sucursal`, `muestra_item`, `intento` y `sav_fila`, según el caso.
  - Corre fuera de la transacción de los lotes, como último paso de la tarea.
  - Las tablas se analizan **de a una**, para no frenar el resto.
  - Queda en el log con la duración: `ANALYZE empresa_campo_historia 42 s`.
- **Durante la confirmación** (ya pedido en `SPEC_lotes_rapidos`, V1) se analiza cada 5 lotes. Hay que verificar que esté implementado.
- **Job diario**, en el Scheduler existente: `ANALYZE` de las mismas tablas si cambiaron más del 10 % desde el último análisis (según `pg_stat_user_tables.n_mod_since_analyze`).
- **Autovacuum más agresivo:** la migración ajusta las tablas grandes (`empresa_campo_historia`, `empresa_atributo` y `empresa`) con `autovacuum_analyze_scale_factor = 0.02` y `autovacuum_vacuum_scale_factor = 0.05`.
- **Visible en la web:** el tablero de calidad (o Configuración) muestra «Estadísticas de la base actualizadas: hace N minutos».

**Criterios de aceptación:**
- [ ] Al terminar una carga, `pg_stat_user_tables.last_analyze` de `empresa` y de `empresa_campo_historia` es posterior al fin de la carga, y el log muestra los `ANALYZE`.
- [ ] Después de una carga de 200.000 filas, sin intervención manual, el plan de `SELECT … FROM empresa WHERE rut = …` usa el índice.

### P-2. Disponibilidad guardada, no calculada en cada pedido

- **Tabla nueva `empresa_disponibilidad`** (`empresa_id` PK, `disponible`, `reglas text[]`, `hasta`, `actualizado`), con índice por `disponible`. Es el resultado de `bloqueos(cfg)` para cada empresa.
- **Se recalcula de forma incremental, solo para las empresas afectadas:**
  - al terminar una carga, un deshacer o un borrado (las empresas tocadas);
  - al sortear, cerrar o borrar una muestra (sus empresas, por la regla de muestra activa);
  - al ingerir un .sav (enfriamiento por último contacto efectivo);
  - al cambiar un vínculo de teléfono, un «no llamar» o una naturaleza excluida (las empresas afectadas);
  - al cambiar la configuración de reglas de disponibilidad o los meses de enfriamiento (**recálculo completo** como tarea en segundo plano, con progreso);
  - en el job diario, para las empresas cuyo enfriamiento venció ese día (`hasta < now()`).
- **Quién la usa:**
  - el buscador, Inicio, el armado de muestras y el marco del sorteo leen `empresa_disponibilidad` en lugar de `v_empresa_disponible`;
  - la vista `v_empresa_disponible` puede quedar para la ficha de una empresa y para verificar.
- **Reproducibilidad del sorteo:** el sorteo puede seguir calculando la disponibilidad con `bloqueos(cfg)` sobre el marco filtrado al momento de sortear, para no depender de un recálculo pendiente. Lo que cambia es **el listado y los contadores**. Claude Code elige la opción más simple que garantice que el marco sea correcto, y la documenta en la decisión.
- **Test de equivalencia:** para un conjunto de datos de prueba, `empresa_disponibilidad` coincide exactamente con `bloqueos(cfg)` después de cada operación (carga, .sav, muestra, no llamar, cambio de configuración).

**Criterios de aceptación:**
- [ ] El buscador de Empresas no usa `v_empresa_disponible` ni `bloqueos()`. Se verifica con `EXPLAIN` en un test.
- [ ] Después de cada operación de la lista, la disponibilidad guardada coincide con la calculada (test de equivalencia).

### P-3. Lista de Empresas rápida

- **Sin `count(*) OVER ()`.** El total exacto se calcula **solo cuando hay filtros que lo hacen barato**, o se muestra un **estimado**: el contador guardado de P-4 para la búsqueda sin filtros, y `EXPLAIN` o la estadística del planificador para la búsqueda con filtros. La pantalla dice «≈ 193.500 empresas». Si el usuario pide el total exacto, se calcula con un botón.
- **Teléfonos discables:** en lugar del subselect por fila, una columna guardada `empresa.telefonos_discables` (o una columna en `empresa_disponibilidad`), que se mantiene en las mismas ocasiones que P-2.
- **Paginación por clave** (keyset) en lugar de `OFFSET` para las páginas siguientes: `WHERE (razon_social, codigo) > (…) ORDER BY razon_social, codigo LIMIT 50`. Hace falta el índice compuesto correspondiente.
- **Índices** para los filtros del buscador:
  - `empresa (base, baja, departamento)`, `(base, baja, tamano)` y `(base, baja, naturaleza_id)`, más índices parciales `WHERE baja IS NULL` donde convenga;
  - **trigramas** (`pg_trgm`, ya instalado) sobre la razón social y la fantasía para `ILIKE '%…%'`;
  - índice sobre `left(ciiu, 2)`.
- **Los filtros por atributo** usan los índices de `empresa_atributo` (atributo y valor) que ya pidió el spec de templates.

**Criterios de aceptación:**
- [ ] Con 200.000 empresas, la página 1 sin filtros, con un filtro de departamento y con una búsqueda por razón social («SRL», «pérez») responde en menos de 1,5 s, medido en producción con `pg_stat_statements` y en el log.
- [ ] La página 50 responde igual de rápido que la página 1.

### P-4. Valores de filtros y contadores precalculados

- **Tabla `resumen_base`** (clave, valor jsonb, actualizado) que guarda:
  - los **valores distintos** de departamento, tamaño, CIIU a 2 dígitos y localidad, con su cantidad de empresas;
  - los **contadores de Inicio**: empresas, disponibles, con teléfono discable, teléfonos, sospechosos, intermediarios, base provisoria;
  - el **uso de cada naturaleza jurídica**: empresas activas, todas, y filas de historia.
- **Cuándo se recalcula:**
  - al terminar cada operación grande, junto con P-1;
  - en el job diario;
  - con un botón «Recalcular» para administradores;
  - en las operaciones chicas (alta manual, editar una empresa, borrar una empresa), con una actualización incremental o marcando el resumen como «a recalcular» para el próximo job, que corre cada pocos minutos si hay cambios.
- **Quién lo usa:** `GET /api/empresas/valores`, `GET /api/inicio` y `GET /api/naturalezas` leen de `resumen_base`, con la fecha de actualización visible («actualizado hace 3 min»).
- **Índice** `empresa_campo_historia (campo, valor)`, para el recálculo del uso de naturalezas y para «¿se puede borrar esta naturaleza?».

**Criterios de aceptación:**
- [ ] `GET /api/empresas/valores` responde en menos de 300 ms y `GET /api/naturalezas` y `GET /api/inicio` en menos de 1 s, con 200.000 empresas.
- [ ] Después de una carga, los valores y contadores reflejan las empresas nuevas sin acción manual.

### P-5. La web no se queda sin conexiones

- **Tiempo máximo por consulta de la web:** `statement_timeout` de **15 s** en las conexiones de la API (`empresas-api`), configurable. El servicio de tareas (`empresas-tareas`) no tiene ese límite. Si una consulta lo supera, la API responde **503** con el mensaje «La consulta tardó demasiado. Si hay una carga grande en curso, probá en unos minutos.», y la web lo muestra tal cual.
- **Espera del pool:** se baja de 30 s a **10 s**. Un pedido que no consigue conexión responde 503 con «La base está ocupada; reintentá en unos segundos», y la web reintenta una vez sola.
- **Pool:** se revisa `DB_POOL_MAX` de la API y de tareas contra las conexiones de la `db-f1-micro` (25), dejando margen para el job del CDR y la migración. Se documenta el cálculo.
- **Aviso de carga en curso:** si hay una carga, un deshacer o un borrado corriendo, la web muestra una franja: «Hay una carga grande en curso (lote N de M): algunas pantallas pueden estar lentas».
- **Menos pedidos en paralelo:** la pantalla Empresas no vuelve a pedir `valores` en cada visita, porque los cachea en el navegador por 10 minutos o hasta que cambia la fecha de `resumen_base`.

**Criterios de aceptación:**
- [ ] Mientras corre la confirmación de una carga de 200.000 filas, abrir Inicio, Empresas, Cargas y Naturalezas no da PoolTimeout. Responde en menos de 3 s o muestra el mensaje de base ocupada.
- [ ] Una consulta forzada a tardar más de 15 s (en un test) devuelve 503 con el mensaje, y el pool sigue disponible para otros pedidos.

### P-6. Medición

- **Middleware de la API:** registra los pedidos que tardan más de 2 s (endpoint, duración, usuario).
- **`pg_stat_statements`:** queda activada (ya se creó la extensión el 23/11). El tablero de calidad o Configuración muestra para administradores **las 10 consultas más lentas** de los últimos 7 días.
- **Test de volumen:** se agrega un test (marcado como lento) que carga 200.000 empresas sintéticas y verifica los tiempos de P-3 y P-4 en el entorno de test.

## 6. Despliegue

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh programar
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

- `api` aplica la migración: las tablas `empresa_disponibilidad` y `resumen_base`, los índices y los ajustes de autovacuum.
- **Crear los índices sobre 2 millones de filas puede tardar varios minutos.** Hay que usar `CREATE INDEX CONCURRENTLY`, fuera de una transacción, para no bloquear la aplicación. Si el sistema de migraciones no lo permite, se hace en un paso aparte documentado.
- Después de migrar, una tarea inicial **llena `empresa_disponibilidad` y `resumen_base`** para las 193.553 empresas, con progreso visible. Hasta que termine, el buscador usa el cálculo anterior.
- `programar` actualiza el job diario (estadísticas, vencimientos de enfriamiento, resumen).
- **No desplegar con una carga en curso.**

## 7. Métricas de éxito

| Métrica | Meta |
|---|---|
| Tiempo de `GET /api/empresas` (p95) | < 1,5 s |
| Tiempo de `GET /api/empresas/valores` (p95) | < 300 ms |
| Errores PoolTimeout por día | 0 |
| Antigüedad de las estadísticas de `empresa` después de una carga | < 10 min |

## 8. Riesgos

| Riesgo | Mitigación |
|---|---|
| La disponibilidad guardada queda desactualizada (una regla cambió y no se recalculó) | Recálculo en cada operación que la afecta, job diario y test de equivalencia. El sorteo verifica contra `bloqueos(cfg)` (P-2). |
| Totales aproximados confunden | Se marcan con «≈», con un botón para el total exacto. |
| Los índices nuevos ocupan disco | Del orden de cientos de MB. El disco de 10 GB tiene autoincremento; se informa el tamaño después de migrar. |

## 9. Costo

**Ninguno adicional.** Son tablas, índices y jobs sobre la misma Cloud SQL y Cloud Run. Las tablas nuevas y los índices ocupan algo de disco (del orden de cientos de MB). El almacenamiento SSD de Cloud SQL cuesta unos US$0,17 por GB por mes en us-central1, así que el agregado es de centavos.

Si con todo esto no se llega a los objetivos, el paso siguiente es agrandar la base:

- `db-g1-small`, unos **US$25–30 por mes**;
- o una instancia con CPU dedicada (`db-custom-1-3840`), unos **US$50 por mes**.

Antes hay que medir el efecto de este spec.
