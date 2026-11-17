# Despliegue: templates de sorteo, empresas sin teléfono, filtros y estratos con todos los datos y formatos del CSV

Este documento lleva a producción [`specs/SPEC_templates_sorteo_sin_telefono_formatos_csv.md`](../specs/SPEC_templates_sorteo_sin_telefono_formatos_csv.md) en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**. Para una instalación desde cero alcanza con la [guía de despliegue](despliegue.md).

**Qué cambia para las personas** (detalle en el manual, guías 7, 10 y 25):

| Requisito | Qué cambia |
| --- | --- |
| R1 · Formatos del CSV | En el detalle de la muestra, el selector **Formato** dice **«Una fila por empresa»** (primera y por defecto) y **«Una fila por número»**. La ayuda debajo del botón explica cada uno. Los archivos se llaman `muestra{N}_parte{M}_por_empresa.csv` y `…_por_numero.csv`. **El contenido no cambia.** |
| R2 · Templates de sorteo | «Nueva muestra» arranca con **Partir de un template**. En el paso 3, **Guardar como template…**; en el detalle de una muestra, **Guardar configuración como template**. Menú nuevo **Templates de sorteo** (jefe y administrador). |
| R3 · Empresas sin teléfono | El paso 1 agrega **Incluir empresas sin teléfono discable**, desmarcado por defecto. En la muestra, **Empresas de la muestra → Sin teléfono**. |
| R4 · Filtros y estratos | Cualquier campo de la empresa y cualquier atributo de empresa activo sirve como filtro y como estrato: «Contiene», «Es uno de», «Tiene dato», rangos, **tramos** para números, «Otros» para textos, año o semestre para fechas. En **Administración → Atributos** desaparecen las casillas «filtro» y «estrato». |

**Tiempo estimado:** 15 minutos. **Costo:** ninguno adicional.

## Paso a paso

Los tres pasos son obligatorios y van en este orden. `migrar` aplica `0012_templates_sorteo.sql`.

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

**Qué hace `0012_templates_sorteo.sql`** (compatible hacia atrás; las muestras existentes no cambian):

- crea la tabla `muestra_template` y la columna `muestra.template_id` (`ON DELETE SET NULL`);
- quita el CHECK que limitaba «estrato» a los atributos de lista;
- agrega índices de `empresa_atributo` por atributo y valor (texto, número y fecha);
- crea la función `norm_txt` (texto sin mayúsculas, tildes ni espacios de más), que usan «Es uno de…» y los estratos de texto.

## Verificación

Con una muestra de prueba, como jefe de proyecto:

1. **Formatos:** en una muestra activa, el selector muestra «Una fila por empresa» (seleccionada) y «Una fila por número»; la ayuda cambia al cambiar la opción. Bajá los dos: los archivos terminan en `_por_empresa.csv` y `_por_numero.csv`.
2. **Template:** en **Nueva muestra**, armá filtros (por ejemplo, un departamento y el atributo «Exporta = Sí»), estratos (tamaño × departamento) y tamaños, y tocá **Guardar como template…**. En otro estudio, **Partir de un template** completa los tres pasos con los mismos valores.
3. **Sin teléfono:** marcá **Incluir empresas sin teléfono discable** y tocá **Ver marco disponible**: aparece «Sin teléfono» en los totales y por estrato. Después de sortear, **Empresas de la muestra → Sin teléfono** las lista y el CSV «Una fila por empresa» las trae con los teléfonos vacíos.
4. **Filtros y estratos:** creá una muestra filtrada por un atributo de texto («Es uno de…») y estratificada por tramos de un atributo numérico (por ejemplo, empleados con 1, 5, 20, 100): el paso 3 muestra 1–4, 5–19, 20–99, 100 o más y (sin dato).
5. **Reproducibilidad:** en la muestra sorteada, **Verificar reproducibilidad** da «Reproducible ✓». Editar después el template no cambia esa muestra.
6. Con un usuario **coordinador**, el menú no muestra «Templates de sorteo» ni el botón «Guardar como template».

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| «Nueva muestra» no muestra «Partir de un template» | No hay templates activos todavía | Guardar uno desde el paso 3 o desde una muestra |
| Un template avisa «se quitó el filtro por X» | El atributo se desactivó o se fusionó después de guardar el template | Es esperado: revisá los pasos y guardá el template actualizado |
| «Definí los tramos de X» al ver el marco | Se estratificó por un número sin tramos | Escribí los tramos o usá «Cuartiles» / «Tramos iguales» |
| La opción «Incluir empresas sin teléfono» está marcada y gris | La regla «sin teléfono discable» está apagada en Configuración | Es esperado: en ese caso entran en todas las muestras |
| Un script que bajaba el CSV buscaba `ucontact_muestra…` o `planilla_muestra…` | Cambió el nombre del archivo (R1) | Usar `…_por_numero.csv` y `…_por_empresa.csv`; el parámetro `formato` de la API no cambió |

**Volver atrás:** redirigir el tráfico de Cloud Run a la revisión anterior de la API y revertir la web en Firebase Hosting (ver [despliegue.md](despliegue.md), «Actualizaciones»). La migración 0012 puede quedar aplicada: la versión anterior no usa la tabla ni la columna nuevas. **Atención:** las muestras creadas con filtros o estratos nuevos (campos, tramos, «Incluir empresas sin teléfono») no se pueden volver a sortear con la versión anterior; las ya sorteadas siguen funcionando.
