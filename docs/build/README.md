# Generación del manual en PDF

`docs/pdf/Manual_de_usuario.pdf` sale de `docs/manual/manual_usuario.md` con la estética de Equipos.
La guía de despliegue, las decisiones y los costos quedan solo en Markdown.

Una vez, en la Mac (con el entorno virtual del repositorio activado):

```bash
pip install markdown pypdf
```

```bash
(cd docs/build && npm install && npx playwright install chromium)
```

Después, cada vez:

```bash
python docs/build/generar_pdfs.py
```

## Capturas del manual

Se toman de la aplicación corriendo en local con los datos de demostración. Desde la raíz del repositorio:

```bash
createdb empresas_demo
```

```bash
DATABASE_URL=postgresql://postgres@localhost/empresas_demo python api/demo/sembrar_demo.py
```

```bash
(cd api && DATABASE_URL=postgresql://postgres@localhost/empresas_demo AUTH_MODE=dev SERVE_WEB=1 uvicorn app.main:app --port 8080)
```

En otra Terminal, también desde la raíz:

```bash
node docs/build/capturas.js http://localhost:8080 docs/manual/img <rut de una empresa con llamadas> api/demo/clima_parte_a_ola1.sav <un .csv chico para el paso de mapeo>
```

Las capturas del login y de **Usuarios** (`01`, `27`, `29`, `30` y `31`) salen de otro script. Necesita una base de demostración recién cargada y la API con el SMTP apuntando a un puerto cerrado, para que se vea el caso "el correo no salió":

```bash
createdb empresas_demo_usuarios
```

```bash
DATABASE_URL=postgresql://postgres@localhost/empresas_demo_usuarios python api/demo/sembrar_demo.py
```

```bash
(cd api && DATABASE_URL=postgresql://postgres@localhost/empresas_demo_usuarios AUTH_MODE=dev SERVE_WEB=1 APP_URL=https://equipos-base-empresas.web.app SMTP_PASSWORD=prueba SMTP_HOST=127.0.0.1 SMTP_PORT=1 uvicorn app.main:app --port 8080)
```

En otra Terminal:

```bash
BASE=http://localhost:8080 node docs/build/capturas_usuarios.js docs/manual/img
```

## Captura de la conexión al CDR

`capturas_cdr.js` saca `32-config-cdr.png` (tarjeta del CDR en Configuración). Sirve la misma API en modo dev con la demo; como en local no hay un MySQL de uContact, el script simula una respuesta exitosa de «Probar conexión». Con la API levantada como arriba:

```bash
BASE=http://localhost:8080 node docs/build/capturas_cdr.js docs/manual/img
```

## Capturas de la carga v2 (atributos y origen del teléfono)

`capturas_carga_v2.js` saca las figuras 33 a 40 (atributos, orígenes, mapeo, traducción de valores, preview, filtros de la muestra, exportación por origen y rendimiento por origen), con los números de las referencias del manual. Necesita la demo recién sembrada (la plantilla «directorio de prueba» no tiene que existir, para que aparezca la traducción) y un CSV con columnas `RUT;Razón social;Tel 1;Origen 1;Tel 2;Origen 2;Cant. empleados;Exporta;Cámara`, con valores de origen escritos distinto del catálogo (por ejemplo «guia», «GUIA TEL.», «PAGINAS BLANCAS») y «si», «No», «s/d» en Exporta:

```bash
BASE=http://localhost:8080 node docs/build/capturas_carga_v2.js docs/manual/img base_prueba.csv
```

Las figuras se insertaron en `docs/Manual_de_usuario_Base_de_Empresas.docx` (guías 1, 3, 7, 10, 11 y 15) y el PDF se regeneró con LibreOffice:

```bash
soffice --headless --convert-to pdf docs/Manual_de_usuario_Base_de_Empresas.docx --outdir docs
```

## Capturas del conteo de llamadas

`capturas_llamadas.js` saca las figuras 40 a 43 (rendimiento por origen, corridas del job del CDR, detalle de una corrida y empresas llamadas). Necesita la demo y al menos una corrida del job con el conteo nuevo:

```bash
BASE=http://localhost:8080 node docs/build/capturas_llamadas.js docs/manual/img
```

## Capturas de .sav, contactos, atributos, exportación y base provisoria

`capturas_mejoras.js` saca las imágenes 44 a 52 de las guías 19 a 24 (línea de tiempo con la ingesta agrupada, empresas de la muestra, agregar un contacto, base provisoria, destino y reglas de fusión, coincidencias a decidir, atributo parecido, qué incluir al exportar y motivos por fila de la ingesta). Necesita la demo **recién cargada**: el script crea un atributo de contacto y hace una carga a la base provisoria.

```bash
BASE=http://localhost:8080 node docs/build/capturas_mejoras.js docs/manual/img
```

Después, `docs/build/manual_mejoras.py` agregó las guías al Word (`docs/Manual_de_usuario_Base_de_Empresas.docx`); el PDF se regenera con:

```bash
soffice --headless --convert-to pdf --outdir docs docs/Manual_de_usuario_Base_de_Empresas.docx
```

## Capturas de templates de sorteo, filtros y estratos, y formatos del CSV

`capturas_templates.js` saca `16-nueva-muestra` (asistente partiendo de un template), `33-atributos` (ya sin las casillas «filtro» y «estrato»), `53-templates`, `54-asistente-filtros` (con las marcas 1 a 5 de la guía 7) y `55-formatos-csv`. Necesita la demo **recién cargada, sin templates**: el script guarda uno.

```bash
BASE=http://localhost:8080 node docs/build/capturas_templates.js docs/manual/img
```

`manual_templates.py` actualiza el Word (guías 7, 10, 15 y 24, guía 25 nueva, tabla de lectura y glosario) a partir del manual anterior; después se regenera el PDF:

```bash
python docs/build/manual_templates.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
```

```bash
soffice --headless --convert-to pdf docs/Manual_de_usuario_Base_de_Empresas.docx --outdir docs
```

## Capturas y manual de la Fase 2 (calidad, enriquecimiento, duplicados y descubrimiento)

`capturas_fase2.js` saca `56-calidad`, `57-estimacion`, `58-corrida`, `59-duplicados`, `60-descubrimiento` y `61-config-enriquecimiento`. Necesita la demo **recién cargada** y la API con los proveedores **simulados** (sin llamadas pagas):

```bash
cd api && DATABASE_URL=postgresql://postgres@localhost/empresas_demo AUTH_MODE=dev SERVE_WEB=1 TASKS_MODE=inline PROVEEDORES_MODO=simulado uvicorn app.main:app --port 8080
```

```bash
BASE=http://localhost:8080 node docs/build/capturas_fase2.js docs/manual/img
```

`manual_fase2.py` agrega al Word las guías 26 a 29 (y la opción de grupo económico en la guía 7, la tabla de lectura y el glosario) a partir del manual anterior; después se regenera el PDF:

```bash
python docs/build/manual_fase2.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
```

```bash
soffice --headless --convert-to pdf docs/Manual_de_usuario_Base_de_Empresas.docx --outdir docs
```

## Naturalezas jurídicas (editar y borrar)

La captura `25-naturalezas.png` la saca `capturas.js` (como siempre, con la demo recién cargada). `manual_naturalezas.py` actualiza el párrafo de la guía 17 del Word (la figura 42 se cambió una vez, en el PR anterior); después se regenera el PDF:

```bash
python docs/build/manual_naturalezas.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
```

## Cargas por lotes (guía 30)

`capturas_lotes.js` saca `62-carga-por-lotes`, `63-carga-interrumpida` y `64-config-cargas`. Necesita la demo recién cargada, dos cargas nuevas (por ejemplo, dos CSV de 30 filas con RUTs que no estén en la demo) y, para ilustrar, la primera en «interrumpida» (4 de 10 lotes) y la segunda «en proceso» (lote 13 de 38), ajustadas a mano en `carga`, `carga_lote` y `tarea` de la base de la demo. Los números de carga se pasan con `CARGA_INTERRUMPIDA` y `CARGA_EN_CURSO`:

```bash
CARGA_INTERRUMPIDA=4 CARGA_EN_CURSO=5 BASE=http://localhost:8080 node docs/build/capturas_lotes.js docs/manual/img
```

`manual_lotes.py` agrega al Word la guía 30, los estados nuevos de la guía 3, el parámetro de la guía 15 y dos filas de Solución de problemas; después se regenera el PDF:

```bash
python docs/build/manual_lotes.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
```

```bash
soffice --headless --convert-to pdf docs/Manual_de_usuario_Base_de_Empresas.docx --outdir docs
```

## Crear la carga sin esperas (guía 30, D51)

`65-carga-leyendo.png` (un archivo grande leyéndose en segundo plano) y `66-ir-a-la-carga.png` (el aviso de una carga del mismo archivo que se está creando) se sacaron con la API en `TASKS_MODE=background`, un .xlsx de 190.000 filas y un corte simulado del primer pedido de crear la carga (Playwright `route.abort` después de que el pedido llegó a la API). `manual_carga_asincrona.py` agrega esas figuras y sus párrafos a la guía 30 (corre las figuras 44s y 44t a 44u y 44v) y una fila de Solución de problemas; se aplica después de `manual_lotes.py` y después se regenera el PDF:

```bash
python docs/build/manual_carga_asincrona.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
```

```bash
soffice --headless --convert-to pdf docs/Manual_de_usuario_Base_de_Empresas.docx --outdir docs
```

## Robustez de las cargas (guía 30, D52)

`medir_memoria.py` mide el pico de memoria al leer un .xlsx sintético de 200.000 filas y en un lote de preview y uno de confirmación, cada fase en un proceso aparte (criterio: menos de 600 MB). Necesita una base vacía y migrada:

```bash
DATABASE_URL=postgresql://postgres@localhost/empresas_medir python docs/build/medir_memoria.py 200000
```

Las figuras `62-carga-por-lotes` (ahora con la fila y el tiempo del lote) y `64-config-cargas` se sacaron de nuevo con `capturas_lotes.js` (`CARGA_INTERRUMPIDA=0` saltea la 63). `manual_robustez.py` actualiza la guía 30, el parámetro de la guía 15 y Solución de problemas; se aplica después de `manual_lotes.py` y `manual_carga_asincrona.py`, y después se regenera el PDF:

```bash
python docs/build/manual_robustez.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
```

```bash
soffice --headless --convert-to pdf docs/Manual_de_usuario_Base_de_Empresas.docx --outdir docs
```

## Lotes rápidos (guía 30, D53)

`manual_lotes_rapidos.py` agrega a la guía 30 el párrafo «El ritmo»; se aplica después de `manual_robustez.py` y después se regenera el PDF:

```bash
python docs/build/manual_lotes_rapidos.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
```

```bash
soffice --headless --convert-to pdf docs/Manual_de_usuario_Base_de_Empresas.docx --outdir docs
```

## RUT sin control de largo (D54)

`capturas_rut.js` saca `67-rut-no-verificado`, `68-filtro-rut` y de nuevo `64-config-cargas` (con el interruptor). Necesita la demo con dos empresas de identificador corto (`POST /api/empresas` con `"rut": "4.567.891"` y `"38123456"`). `manual_rut.py` actualiza las guías 1, 3 y 15, la tabla de calidad y el glosario; se aplica después de `manual_lotes_rapidos.py` y después se regenera el PDF:

```bash
python docs/build/manual_rut.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
```

```bash
soffice --headless --convert-to pdf docs/Manual_de_usuario_Base_de_Empresas.docx --outdir docs
```

## Rendimiento con una base grande (D55)

`capturas_rendimiento.js` saca `69-empresas-paginas` (total «≈» y páginas), `70-inicio-contadores`, `71-config-rendimiento` y `72-franja-carga` (la franja se simula con una carga en el lote 12 de 39). Las capturas del manual se sacaron contra la base del test de volumen (200.000 empresas sintéticas: `RUN_LENTOS=1 pytest tests/test_rendimiento.py -k volumen` con `TEST_DATABASE_URL` apuntando a una base aparte) y Postgres con `shared_preload_libraries=pg_stat_statements`, para que la tarjeta muestre las consultas lentas. `manual_rendimiento.py` agrega la guía 31, tres filas a «Solución de problemas» y dos al glosario; se aplica después de `manual_rut.py` y después se regenera el PDF:

```bash
python docs/build/manual_rendimiento.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
```

```bash
soffice --headless --convert-to pdf docs/Manual_de_usuario_Base_de_Empresas.docx --outdir docs
```

## Armado de muestras (D56)

`capturas_muestras.js` saca `73-espera-marco` (simula un marco que tarda 2,5 s y verifica que un doble clic haga un solo pedido), `74-paso3-excel-metodo` (método sistemático, Excel bajado, completado con `openpyxl` y vuelto a subir) y `75-vecino-de` (sortea una muestra sistemática de prueba en el estudio `ESTUDIO`). Necesita la demo con un estudio. `manual_muestras.py` actualiza las guías 7 y 25, agrega la guía 32 y dos términos al glosario; se aplica después de `manual_rendimiento.py` y después se regenera el PDF:

```bash
BASE=http://localhost:8080 ESTUDIO=1 node docs/build/capturas_muestras.js docs/manual/img
```

```bash
python docs/build/manual_muestras.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
```

```bash
soffice --headless --convert-to pdf docs/Manual_de_usuario_Base_de_Empresas.docx --outdir docs
```

## Enriquecimiento: errores visibles y búsqueda web con Claude (D57)

`capturas_brave.js` saca `76-pasos-motivo-error` y `77-empresas-con-error` (una corrida con errores: `CORRIDA_ERROR`), `78-pasos-busqueda-web` (una corrida que llegó al paso 5: `CORRIDA_WEB`), `79-config-busqueda-web`, `80-ficha-pagina-fuente` (la ficha de la empresa que enriqueció el paso 5: `RUT_WEB`) y `81-estimacion-busqueda-web` (abre la estimación de `RUT_EST` y la cancela). Necesita la demo con la búsqueda web activada. La corrida con errores se arma con la API en `PROVEEDORES_MODO=real` y claves falsas (sin red, cada proveedor falla con su motivo); la del paso 5, en modo simulado con Claude (paso 4) apagado y empresas sin teléfono. `manual_brave.py` actualiza la guía 27, agrega la guía 33 y un término al glosario; se aplica después de `manual_muestras.py` y después se regenera el PDF:

```bash
BASE=http://localhost:8080 CORRIDA_ERROR=4 CORRIDA_WEB=3 RUT_WEB=55001217 RUT_EST=550041118 node docs/build/capturas_brave.js docs/manual/img
```

```bash
python docs/build/manual_brave.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
```

```bash
soffice --headless --convert-to pdf docs/Manual_de_usuario_Base_de_Empresas.docx --outdir docs
```
