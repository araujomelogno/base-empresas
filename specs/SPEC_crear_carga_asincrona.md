# SPEC — «Siguiente» en la carga sin esperas mudas: lectura única del archivo y creación de la carga en segundo plano

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_crear_carga_asincrona.md`, para que Claude Code lo implemente y lo despliegue.
**Base:** `main` en `8f3d15b` (PR #20, cargas por lotes).
**Complementa:** `SPEC_cargas_grandes_por_lotes.md`: el requisito L1 dejó el procesamiento por lotes, pero el paso de crear la carga sigue siendo sincrónico.
**Fecha:** 22/11/2026

---

## 1. Problema

Con un archivo de **193.556 filas** (`acumulaGermanV7.xlsx`), al apretar **«Siguiente»** en el paso 2 de la carga no pasa nada visible: no aparece ningún aviso de que se esté procesando.

**Causa, revisada en el código:**

1. **«Analizar archivo»** (`POST /cargas/analizar`) lee y parsea el .xlsx entero. Esta vez funcionó porque quedó por debajo del límite.
2. **«Siguiente»** llama a **`POST /cargas/valores`** (`cargas.valores`). Esa función **vuelve a descargar el archivo del bucket y a parsear el .xlsx entero** (`_leer`) para contar los valores de origen y de los atributos de lista.
   - Es un pedido **sincrónico**.
   - **El botón no muestra nada mientras espera**: no se deshabilita, no hay spinner ni texto (`web/public/js/vistas/cargas.js`, `#c-siguiente`).
3. Si no hay valores para traducir, sigue con **`POST /cargas`** (`cargas.crear`), también sincrónico, que:
   - **parsea el .xlsx por tercera vez**;
   - vuelve a calcular `valores(...)`;
   - copia las 193.556 filas a `carga_fila`;
   - recién ahí crea la tarea del preview. La barra de progreso aparece solo después de este paso.
4. **Firebase Hosting corta a los 60 segundos** los pedidos que reenvía a Cloud Run. Parsear un .xlsx de casi 200.000 filas con openpyxl puede llevar uno o dos minutos. Entonces:
   - si el pedido supera ese tiempo, el navegador recibe un error (504) después de una espera muda;
   - **la API puede seguir trabajando del lado del servidor y crear la carga igual**. Si el usuario vuelve a apretar «Siguiente», se pueden crear **cargas duplicadas**.

**En resumen:** el archivo se parsea tres veces, dos de ellas dentro de pedidos sincrónicos que no muestran avance y que se cortan a los 60 segundos.

## 2. Objetivos

1. Con un archivo de 200.000 filas, desde que se aprieta «Siguiente» la pantalla **muestra el avance** en menos de 1 segundo, y nunca hay un error por el límite de 60 segundos.
2. **El archivo se parsea una sola vez**, al analizarlo.
3. Apretar «Siguiente» dos veces **no crea dos cargas**.

## 3. Fuera de alcance

- Subir archivos de más de 30 MB (límite de Firebase Hosting; P2 del spec de lotes).
- Cambiar el mapeo, la traducción de valores o las reglas de la carga.

## 4. Requisitos (P0)

### A1. «Analizar» parsea una vez y deja las filas listas

- Al analizar, las filas del archivo se guardan **una sola vez** en un almacenamiento intermedio ligado al `archivo_id`. Puede ser la misma tabla `carga_fila` con `archivo_id`, o una tabla `archivo_fila` (`archivo_id`, `fila`, `datos jsonb`).
- **Si el archivo es grande**, la lectura y el guardado se hacen **en segundo plano**, para no depender del límite de 60 segundos:
  - el pedido de subida solo guarda el archivo en el bucket, crea una tarea **«archivo.leer»** y responde enseguida con `tarea_id`;
  - la pantalla muestra «Leyendo el archivo… N filas» con la barra de progreso existente (`seguirTarea`);
  - cuando la tarea termina, devuelve las columnas, la cantidad de filas, el mapeo sugerido y la plantilla, igual que hoy.
- **Criterio de «grande»:** más de 10 MB o más de 20.000 filas estimadas. Por debajo de eso puede seguir siendo sincrónico, como hoy.
- Las filas intermedias de un archivo que no llegó a usarse en ninguna carga se borran a las 24 horas (Scheduler diario).

### A2. Traducción de valores sin volver a leer el archivo

- `POST /cargas/valores` calcula los valores distintos con **una consulta sobre las filas ya guardadas**, por ejemplo con `jsonb ->> columna` y `GROUP BY`, sin descargar ni parsear el archivo.
- Para 200.000 filas tiene que responder en **menos de 5 segundos**. Si no se llega, pasa a ser una tarea con progreso, como A1.
- **Mientras espera**, el botón «Siguiente» queda **deshabilitado** y muestra **«Revisando los valores…»** con un spinner. Si hay un error, el botón vuelve a habilitarse y se muestra el mensaje.

### A3. Crear la carga responde enseguida

- `POST /cargas` **no parsea el archivo ni copia filas** dentro del pedido. Solo:
  - valida el mapeo, con las columnas ya conocidas del análisis;
  - verifica que no queden valores sin traducir, con la misma consulta de A2;
  - crea la carga y la plantilla;
  - encola la tarea de preview;
  - responde con `carga_id` y `tarea_id`.
- La **asignación de filas a lotes** se hace dentro de la **primera tarea del preview**, sobre las filas guardadas, con progreso: «Preparando los lotes… N de M filas». Esa asignación es la agrupación por RUT del spec de lotes, y es la que hoy hace `lotes.guardar_filas` dentro del pedido.
- **Apenas se aprieta «Siguiente»** aparece el avance: «Creando la carga…», después «Preparando los lotes…» y después «Calculando el preview (lote N de M)».

### A4. Sin cargas duplicadas

- El pedido de crear la carga lleva una **clave de idempotencia**, generada por la web al abrir el paso 2. Si llega dos veces la misma clave, se devuelve la carga ya creada, no una nueva.
- Además, mientras exista una carga «analizando» del mismo `archivo_id` creada por el mismo usuario en los últimos 10 minutos, «Siguiente» ofrece **«Ir a la carga #N que se está creando»** en lugar de crear otra.

## 5. Criterios de aceptación

- [ ] Con un .xlsx de unas 190.000 filas:
  - «Analizar» muestra el avance de lectura y termina sin errores;
  - «Siguiente» muestra el avance de inmediato;
  - en ningún paso hay un 504 ni una espera sin indicación.
- [ ] El archivo se parsea **una sola vez** por carga: se verifica con un log «archivo N parseado» o con un contador en los tests.
- [ ] `POST /cargas/valores` y `POST /cargas` responden en menos de 5 s con 200.000 filas.
- [ ] Apretar «Siguiente» dos veces seguidas crea **una** carga.
- [ ] Con archivos chicos (menos de 20.000 filas) el flujo se ve igual que hoy, sin pasos extra.
- [ ] Los tests actuales de cargas siguen pasando.

## 6. Qué hacer ahora con la carga trabada

- Probablemente ya se creó una carga desde el «Siguiente» que no mostró nada (el servidor siguió trabajando después del corte de 60 segundos).
- Revisar la lista de **Cargas**:
  - si hay una carga nueva de `acumulaGermanV7` en «analizando» o en «preview», seguir desde ahí;
  - si hay más de una, **borrar las duplicadas** con «Borrar carga».
- No volver a apretar «Siguiente» con el mismo archivo hasta revisar la lista.

## 7. Despliegue

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh migrar
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Si se agrega la limpieza diaria de filas intermedias, también hay que correr `programar`. Si ya está mergeado el fix de región, se usa `EMPRESAS_REGION=us-central1`.

## 8. Costo

**Ninguno adicional.** Son las mismas tareas de Cloud Tasks y Cloud Run. Se parsea el archivo una vez en lugar de tres, así que el consumo de CPU baja. Las filas intermedias ocupan en Cloud SQL lo mismo que hoy `carga_fila`, unos cientos de MB para 200.000 filas, y se liberan al terminar.
