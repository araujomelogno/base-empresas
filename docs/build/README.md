# Generación de documentos

Los PDF de `docs/pdf/` salen de los Markdown de `docs/` con la estética de Equipos.

```bash
pip install markdown pypdf
python docs/build/generar_pdfs.py                 # todos
python docs/build/generar_pdfs.py manual          # manual | despliegue | decisiones | costos
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
