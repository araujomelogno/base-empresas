# Despliegue: Fase 2 — calidad de la base, enriquecimiento, posibles duplicados y descubrimiento

Este documento lleva a producción [`specs/SPEC_fase2_enriquecimiento.md`](../specs/SPEC_fase2_enriquecimiento.md) en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**, desde tu MacBook. Para una instalación desde cero alcanza con la [guía de despliegue](despliegue.md). Las decisiones están en [`docs/decisiones.md`](decisiones.md) (D45 a D48) y el uso, en el manual (guías 26 a 29).

**Qué cambia para las personas:**

| Etapa | Qué cambia |
| --- | --- |
| A · Calidad de la base | Menú **Administración → Calidad de la base** (admin, data steward y jefes): una tarjeta por dimensión con meta, estado, evolución y la lista de lo que la incumple. Un job diario guarda la foto de los indicadores. |
| B · Enriquecimiento | **✨ Enriquecer** en la muestra, en la ficha y al pie de Empresas («Enriquecer estas N empresas»), con estimación de costo que hay que aprobar, tope por corrida y tope mensual duro. Menú **Base de datos → Enriquecimiento** con las corridas. Configuración → **Enriquecimiento** (claves, precios y topes). Filtros nuevos en Empresas: **Teléfono** y **Sitio web**. |
| B4 · Duplicados | Menú **Base de datos → Posibles duplicados**: fusionar, «son grupo económico» o «sin relación». En Nueva muestra, **«Como máximo una empresa por grupo económico»** (marcada). Un job diario detecta los pares. |
| C · Descubrimiento | Menú **Base de datos → Buscar empresas nuevas**: búsqueda por rubro y zona en Google Places; las nuevas entran a la base provisoria. |

**Tiempo estimado:** 30 minutos, más lo que lleve conseguir las claves. **Costo:** infraestructura, ninguno adicional (3 secretos, centavos por mes); las APIs, por uso y siempre bajo el tope mensual (valor inicial US$100; ver el spec, sección 10).

## 1. Desplegar (las tres etapas van juntas)

Los cuatro pasos son obligatorios y van en este orden. `api` crea los tres secretos de los proveedores (vacíos) y habilita la API de Places; `migrar` aplica `0013_fase2_enriquecimiento.sql`; `programar` crea los dos jobs diarios nuevos.

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
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh programar
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Si ya está mergeado el fix de región del script, la variable es `EMPRESAS_REGION=us-central1`. Si se usa IP fija para el CDR, `api` va con `IP_FIJA=1`, como siempre. Después, recargá la aplicación con **Cmd+Shift+R**.

Con esto ya funcionan el **tablero de calidad** y los **posibles duplicados**. El enriquecimiento y el descubrimiento aparecen, pero todos los proveedores figuran «no configurado» hasta el paso 2.

**Qué hace `0013_fase2_enriquecimiento.sql`** (compatible hacia atrás; las muestras existentes no cambian):

- tablas `calidad_medicion` (foto diaria) y `calidad_alerta_revisada`;
- tablas `enriquecimiento_corrida` (corridas y lotes de descubrimiento) y `enriquecimiento_paso` (cada llamada con su costo: es el registro del gasto);
- tablas `grupo_economico` y `duplicado_par`, columnas `empresa.grupo_economico_id`, `empresa.alta_corrida_id`, `marco_snapshot_item.grupo_id` y `telefono.intermediario_motivo`;
- orígenes de sistema `google_places` («Google Places») y `web` («Sitio web»), con prioridad baja; atributos de sistema `email_institucional`, `google_place_id` y `rubro_descubrimiento`;
- la historia acepta las fuentes `enriquecimiento` y `descubrimiento`;
- funciones `razon_sin_sufijo` y `dominio_web`, con sus índices.

**Los jobs de `programar`** (Cloud Scheduler, hora de Montevideo): `empresas-auditoria-bq` a las 5:10 (como antes), `empresas-calidad` a las 5:20 (`POST /api/jobs/calidad`) y `empresas-duplicados` a las 5:30 (`POST /api/jobs/duplicados`).

## 2. Claves de los proveedores (antes de usar el enriquecimiento)

Se cargan desde la aplicación: van a Secret Manager y no se vuelven a mostrar. En la Mac, con el navegador:

1. **Google Places.** En la consola de Google Cloud del proyecto `equipos-base-empresas`: **APIs y servicios → Credenciales → Crear credenciales → Clave de API**. En **Restricciones de API**, elegí solo **Places API (New)**. La facturación del proyecto tiene que estar activa (Places cobra por uso; las primeras 1.000 llamadas del mes son gratis).
2. **Brave Search.** En `https://api-dashboard.search.brave.com`, creá una suscripción a **Search** y copiá la clave. Confirmá el precio por búsqueda (el spec usa US$0,005, a confirmar).
3. **Claude.** En `https://platform.claude.com`, **Settings → API keys → Create key**. Conviene un workspace propio con un límite de gasto mensual.
4. En la aplicación, como administrador: **Configuración → Enriquecimiento**, pegá cada clave y tocá **Guardar clave**. El estado pasa a **activo**.
5. Revisá precios y topes (tope mensual US$100, por corrida US$20, 2.000 empresas por corrida) y tocá **Guardar nueva versión**.

Para apagar un proveedor sin desplegar (por ejemplo Places, si legal lo pide), desmarcá **usar** y guardá una versión nueva.

## Verificación

Con un usuario administrador:

1. **Calidad:** **Administración → Calidad de la base** muestra las 7 dimensiones con su valor y su meta; **Ver la lista** abre lo que incumple. **Guardar la foto de hoy** guarda una medición; al día siguiente el job habrá guardado otra. Para comprobar el job sin esperar:

   ```bash
   gcloud scheduler jobs run empresas-calidad --location us-central1 --project equipos-base-empresas
   ```

2. **Duplicados:** **Base de datos → Posibles duplicados → Detectar ahora** lista los pares con lo que comparten. Probá «Sin relación» en uno: no vuelve a aparecer.
3. **Enriquecimiento (con las claves cargadas):** en **Empresas**, filtrá **Teléfono → Sin teléfono discable** y un departamento chico, y tocá **Enriquecer estas N empresas**. La estimación muestra el costo máximo y el esperado; **no se gasta nada hasta aprobar**. Aprobá con pocas empresas (por ejemplo 5) y seguí la corrida hasta que termine. En la ficha de una empresa con teléfono nuevo, la pestaña Teléfonos dice «Google Places · enriquecimiento #N».
4. **Tope:** en **Calidad de la base → Enriquecimiento** el gasto del mes coincide con la suma de las corridas.
5. **Descubrimiento:** **Base de datos → Buscar empresas nuevas**, «imprentas en Salto», 1 página. Revisá el preview y confirmá dos o tres: aparecen en **Base provisoria** con código P-. **Deshacer** en el lote las anula.
6. **Sorteo:** en **Nueva muestra**, «Como máximo una empresa por grupo económico» aparece marcada. Una muestra sorteada con la opción da «Reproducible ✓».

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| Un proveedor sigue «no configurado» después de guardar la clave | La cuenta de servicio no tiene permiso sobre el secreto | Volver a correr `./infra/desplegar.sh api` (da `secretVersionManager` y `secretAccessor` sobre los tres secretos) |
| «No se pudo guardar la clave en Secret Manager» | El secreto no existe (no se corrió `api` con esta versión) | Correr `./infra/desplegar.sh api` |
| La corrida avisa «Google Places rechazó la clave (403)» y lo saltea | La API de Places no está habilitada, la clave está restringida a otra API o no hay facturación | En la consola: habilitar **Places API (New)**, revisar las restricciones de la clave y la facturación |
| «Claude rechazó la clave» o «Modelo de Claude inexistente» | Clave inválida o modelo mal escrito | Volver a cargar la clave; el modelo por defecto es `claude-haiku-5-5` |
| La corrida queda «detenida por tope» | Se llegó al tope de la corrida o al mensual | Es esperado: lo conseguido quedó guardado. Subir el tope en Configuración solo si dirección lo aprueba |
| El tablero dice «sin mediciones» al día siguiente | El job `empresas-calidad` no corrió | `gcloud scheduler jobs describe empresas-calidad --location us-central1 --project equipos-base-empresas` y revisar el último intento; si falta, correr `programar` |
| La bandeja de duplicados tiene muchísimos pares de un mismo dominio | Un dominio genérico (por ejemplo, de un proveedor de sitios) | Agregarlo a «Dominios que no cuentan como mismo sitio» en Configuración → Enriquecimiento y tocar **Detectar ahora** |

**Volver atrás:** redirigir el tráfico de Cloud Run a la revisión anterior de la API y revertir la web en Firebase Hosting (ver [despliegue.md](despliegue.md), «Actualizaciones»). La migración 0013 puede quedar aplicada: la versión anterior no usa las tablas ni las columnas nuevas. Los teléfonos ya enriquecidos quedan en la base con su origen (se pueden quitar deshaciendo cada corrida antes de volver atrás). Los jobs `empresas-calidad` y `empresas-duplicados` se pausan con:

```bash
gcloud scheduler jobs pause empresas-calidad --location us-central1 --project equipos-base-empresas
```

```bash
gcloud scheduler jobs pause empresas-duplicados --location us-central1 --project equipos-base-empresas
```
