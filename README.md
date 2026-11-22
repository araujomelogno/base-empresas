# Base de Empresas — Equipos Consultores

Registro maestro de empresas por RUT del que salen muestras aleatorias y auditables para los estudios a empresas, con el CSV para uContact, el análisis del CDR por número destino y la ingesta del .sav de Alchemer que actualiza la base.

- Producto: [`docs/PRD.md`](docs/PRD.md)
- Alcance construido: [`specs/Spec Fase 0 y 1.md`](specs/Spec%20Fase%200%20y%201.md) (fase 0 y fase 1, R1.1–R1.13)

## Documentos

| Documento | Archivo |
| --- | --- |
| Manual de usuario (PDF con capturas) | [`docs/pdf/Manual_de_usuario.pdf`](docs/pdf/Manual_de_usuario.pdf) (fuente: [`docs/manual/manual_usuario.md`](docs/manual/manual_usuario.md)) |
| Guía de despliegue | [`docs/despliegue.md`](docs/despliegue.md) |
| Registro de decisiones | [`docs/decisiones.md`](docs/decisiones.md) |
| Costos | [`docs/costos.md`](docs/costos.md) |
| Cambio de Cloud SQL de `db-f1-micro` a `db-g1-small` | [`docs/cambio_a_small.md`](docs/cambio_a_small.md) |
| Despliegue del alta de usuarios con enlace de acceso | [`docs/despliegue_alta_usuarios.md`](docs/despliegue_alta_usuarios.md) |
| Despliegue del job del CDR en Google Cloud | [`docs/despliegue_job_cdr.md`](docs/despliegue_job_cdr.md) |
| Despliegue de la carga v2 (atributos y origen del teléfono) | [`docs/despliegue_carga_v2.md`](docs/despliegue_carga_v2.md) |
| Despliegue del borrado de estudios, muestras y cargas en curso | [`docs/despliegue_borrado_estudios.md`](docs/despliegue_borrado_estudios.md) |
| Despliegue del conteo de llamadas del CDR y empresas llamadas | [`docs/despliegue_conteo_llamadas.md`](docs/despliegue_conteo_llamadas.md) |
| Despliegue de .sav, contactos, atributos, exportación y base provisoria | [`docs/despliegue_mejoras_sav_contactos.md`](docs/despliegue_mejoras_sav_contactos.md) |
| Despliegue de templates de sorteo, empresas sin teléfono, filtros y estratos y formatos del CSV | [`docs/despliegue_templates_sorteo.md`](docs/despliegue_templates_sorteo.md) |
| Despliegue de la Fase 2: calidad de la base, enriquecimiento, posibles duplicados y descubrimiento | [`docs/despliegue_fase2_enriquecimiento.md`](docs/despliegue_fase2_enriquecimiento.md) |
| Despliegue de editar y borrar naturalezas jurídicas | [`docs/despliegue_naturalezas.md`](docs/despliegue_naturalezas.md) |
| Despliegue del arreglo «Failed to fetch» al borrar naturalezas sin código | [`docs/despliegue_naturalezas_sin_codigo.md`](docs/despliegue_naturalezas_sin_codigo.md) |
| Despliegue de las cargas grandes por lotes (preview, confirmación, deshacer y borrado) | [`docs/despliegue_cargas_por_lotes.md`](docs/despliegue_cargas_por_lotes.md) |
| Despliegue de «Siguiente» sin esperas: el archivo se lee una vez y la carga se crea en segundo plano | [`docs/despliegue_carga_asincrona.md`](docs/despliegue_carga_asincrona.md) |
| Despliegue de la robustez de las cargas: servicio de tareas, tareas que se retoman solas y migración antes de desplegar | [`docs/despliegue_robustez.md`](docs/despliegue_robustez.md) |

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `fase0/` | Experimentos A–D de la fase 0, bloque estándar de Alchemer, reglas de normalización, carga de la hoja "excluidos" |
| `db/` | Migraciones numeradas del esquema `empresas` (Postgres 16) y `migrate.py` |
| `api/` | API FastAPI para Cloud Run (`app/`), job nocturno del CDR (`app/jobs/cdr_job.py`, Cloud Run job), tests con Postgres real (`tests/`) y datos de demostración (`demo/`) |
| `web/` | Web sin framework para Firebase Hosting (`public/`) y `firebase.json` |
| `infra/` | `desplegar.sh`: infraestructura de GCP, API, migraciones, job del CDR, web y Cloud Scheduler |
| `docs/` | Documentos, capturas y generador de PDFs |

## Arranque rápido en una Mac

Con [Homebrew](https://brew.sh) (detalle en la [guía de despliegue](docs/despliegue.md), "Desarrollo local en la Mac"):

```bash
brew install python@3.12 postgresql@16 && brew services start postgresql@16
```

```bash
createuser -s postgres && createdb empresas_dev
```

```bash
python3.12 -m venv .venv && source .venv/bin/activate && pip install -r api/requirements-dev.txt
```

```bash
DATABASE_URL=postgresql://postgres@localhost/empresas_dev python api/demo/sembrar_demo.py
```

```bash
cd api && DATABASE_URL=postgresql://postgres@localhost/empresas_dev AUTH_MODE=dev SERVE_WEB=1 uvicorn app.main:app --port 8080
```

Abrir http://localhost:8080 y entrar con `admin@equipos.com.uy` (modo dev, sin clave). Los datos de la demo son ficticios.

## Tests

```bash
createdb empresas_test
```

```bash
(cd api && TEST_DATABASE_URL=postgresql://postgres@localhost/empresas_test python -m pytest -q)
```

```bash
(cd fase0 && python -m pytest -q)
```

## Despliegue

```bash
PROYECTO=<id del proyecto> ADMIN_EMAILS=<email> ./infra/desplegar.sh todo
```

Detalle en la [guía de despliegue](docs/despliegue.md).
