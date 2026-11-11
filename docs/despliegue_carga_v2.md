# Despliegue: carga v2 (atributos y origen del teléfono)

Este documento lleva a producción el cambio de [`specs/SPEC_carga_v2_atributos_y_origen_telefono.md`](../specs/SPEC_carga_v2_atributos_y_origen_telefono.md) sobre la instalación que ya existe (proyecto `equipos-base-empresas`). Para una instalación desde cero alcanza con la [guía de despliegue](despliegue.md): la migración nueva se aplica en el paso 2 como las demás.

**Qué cambia para las personas:**

- **Administración → Atributos:** un administrador crea datos nuevos de empresa (cantidad de empleados, exporta, cámara…) sin tocar código. La próxima carga ya los puede mapear, y el sorteo los puede usar para filtrar y estratificar.
- **Administración → Orígenes de teléfono:** el catálogo de dónde sale cada número (guía, DGI, web, estudio anterior…), en orden de prioridad.
- **Cargas:** el mapeo muestra solo lo que reconoció, en bloques (Empresa, Atributos, Teléfonos con su origen, Sucursal), y ya no ofrece campos de contacto. Los valores que no coinciden con el catálogo se traducen antes del preview. El preview cuenta filas sin teléfono, teléfonos por origen y atributos. Cada estado explica qué significa y qué sigue. Descartar deja la carga «descartada» (distinto de «deshecha»).
- **Muestras:** filtros por atributo y por origen de los teléfonos; estratos por atributo de lista. La exportación a uContact puede filtrar por origen y ordena los teléfonos por prioridad de origen.
- **Actividad:** tarjeta nueva **Rendimiento por origen**.
- **Ficha:** atributos en Datos y origen de cada número en Teléfonos.

**Tiempo estimado:** 15 a 20 minutos, más la carga inicial de los catálogos. La web y la API quedan sin servicio solo los segundos del despliegue de Cloud Run. **Costo:** ninguno adicional (tablas y pantallas sobre la misma base y la misma API).

## Antes de empezar

| Qué | Dónde | Quién |
| --- | --- | --- |
| Permisos de Owner en el proyecto `equipos-base-empresas` | Google Cloud | Quien despliega |
| La Mac preparada (`gcloud`, `firebase`, repositorio al día) | Ver [despliegue.md](despliegue.md), "Preparar la Mac" | Quien despliega |
| La lista inicial de orígenes y su prioridad (por ejemplo: Estudio anterior, Guía telefónica, DGI, Directorio de cámara, Web de la empresa) | Se cargan en la aplicación (paso 3) | Dirección y data steward |
| Los primeros atributos que se quieren cargar | Se cargan en la aplicación (paso 3) | Data steward |
| Que no haya una carga en curso | Pantalla **Cargas**: ninguna «analizando» ni «en proceso» | Data steward |

Traé el repositorio al día:

```bash
cd ~/base-empresas && git pull
```

## Paso 1 — API y migración

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh api
```

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh migrar
```

`migrar` aplica `db/empresas/0006_carga_v2.sql`, que es compatible hacia atrás:

- Crea `atributo`, `empresa_atributo`, `origen_telefono` (con **Sala**, **Manual** y **Sin dato**) y `telefono_vinculo_origen`.
- Le da origen a todos los vínculos teléfono–empresa que ya existían: **Sala** a los que llegaron por el .sav, **Manual** a los agregados en la ficha y **Sin dato** al resto.
- Agrega el estado `descartada` y pasa a ese estado las cargas «deshechas» que nunca se habían confirmado.
- Agrega `muestra.exportacion` (orígenes y orden del CSV).

Si se usa IP fija para el CDR, el despliegue de la API va con `IP_FIJA=1`, como siempre.

## Paso 2 — Web

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh web
```

Quien tenga la aplicación abierta tiene que recargar la página.

## Paso 3 — Cargar los catálogos

Con un usuario administrador:

1. **Administración → Orígenes de teléfono → + Nuevo origen**, uno por cada origen de la lista. Se agregan al final; con las flechas se ordenan por prioridad (arriba, los más confiables). «Sin dato» queda siempre al final.
2. **Administración → Atributos → + Nuevo atributo** para cada dato que se quiera guardar. Conviene completar los **sinónimos** con los nombres de columna que usan las bases (por ejemplo «empleados, personal, cant. empleados»): así la carga los reconoce sola. Marcá «filtro» si sirve para el sorteo y «estrato» si es una lista que sirve para estratificar.
3. Si alguna plantilla de carga tenía campos de contacto, la próxima vez que se use avisa que se ignoran. No hay que hacer nada.

## Paso 4 — Verificación

Es la definición de terminado del spec. Marcá cada punto:

- [ ] Una base real con dos columnas de teléfono y una columna de origen se cargó: la traducción de valores apareció para los orígenes escritos distinto, y el preview mostró teléfonos por origen y filas sin teléfono.
- [ ] La ficha de una empresa de esa carga muestra el origen de cada número.
- [ ] Se creó un atributo de lista, se cargó en una base y se usó como estrato en una muestra; **Verificar reproducibilidad** dio OK.
- [ ] Un CSV se exportó filtrado por un origen y otro ordenado por prioridad.
- [ ] La tarjeta **Rendimiento por origen** de Actividad muestra datos de un estudio con CDR y .sav ingeridos.
- [ ] Descartar una carga en preview la deja «descartada»; deshacer una confirmada la deja «deshecha».
- [ ] En **Auditoría** figuran los cambios de atributos y orígenes (`atributo.*`, `origen_telefono.*`) y de opciones de exportación (`muestra.exportacion`).

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| «Elegí el origen por defecto de los teléfonos de esta carga» | Falta el origen por defecto en el mapeo | Elegirlo en el bloque Teléfonos (si no se sabe, «Sin dato») |
| «Hay N valores sin traducir al catálogo» | Quedó algún valor de origen o de un atributo de lista sin decidir | Completar la tabla de traducción: un valor del catálogo, «Sin dato» o uno nuevo (administrador) |
| Una columna no aparece en el mapeo | El sistema no la reconoció | Agregarla con «+ Agregar campo» o «+ Agregar atributo»; si se repite, sumar el nombre como sinónimo del atributo |
| Un atributo no aparece en la carga | Está inactivo | Activarlo en Administración → Atributos |
| No se puede borrar un atributo u origen | Tiene valores o teléfonos, se usa en una muestra activa, o es de sistema | Desactivarlo en lugar de borrarlo |
| La contactabilidad por origen parece alta o baja | La definición de llamada atendida (decisión D35) no coincide con cómo se usa la disposición en el marcador | Revisarla con coordinación de campo; está en un solo lugar (`ATENDIDA` en `api/app/actividad.py`) |

**Volver atrás:** redirigir el tráfico de Cloud Run a la revisión anterior de la API y revertir la web en Firebase Hosting (ver [despliegue.md](despliegue.md), "Actualizaciones"). La migración 0006 puede quedar aplicada: la versión anterior ignora las tablas nuevas. La excepción es el estado `descartada`: la versión anterior no lo conoce y muestra esas cargas con la etiqueta en crudo, sin otro efecto.
