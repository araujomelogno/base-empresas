# Generación del manual en PDF

`docs/pdf/Manual_de_usuario.pdf` sale de `docs/manual/manual_usuario.md` con la estética de Equipos.
La guía de despliegue, las decisiones y los costos quedan solo en Markdown.

```bash
pip install markdown pypdf
python docs/build/generar_pdfs.py
```

## Capturas del manual

Se toman de la aplicación corriendo en local con los datos de demostración:

```bash
createdb empresas_demo
DATABASE_URL=postgresql://postgres@localhost/empresas_demo python api/demo/sembrar_demo.py
cd api && DATABASE_URL=postgresql://postgres@localhost/empresas_demo AUTH_MODE=dev SERVE_WEB=1 uvicorn app.main:app --port 8080 &
node docs/build/capturas.js http://localhost:8080 docs/manual/img <rut de una empresa con llamadas> \
  api/demo/clima_parte_a_ola1.sav <un .csv chico para el paso de mapeo>
```
