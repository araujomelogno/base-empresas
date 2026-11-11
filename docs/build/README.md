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
