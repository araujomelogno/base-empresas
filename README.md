# Base de Empresas — Equipos Consultores

Registro maestro de empresas por RUT del que salen muestras aleatorias y auditables para los estudios a empresas, con el CSV para uContact, el análisis del CDR por número destino y la ingesta del .sav de Alchemer que actualiza la base.

- Producto: [`docs/PRD.md`](docs/PRD.md)
- Alcance construido: [`specs/Spec Fase 0 y 1.md`](specs/Spec%20Fase%200%20y%201.md) (fase 0 y fase 1, R1.1–R1.13)

## Documentos

| Documento | PDF | Fuente |
| --- | --- | --- |
| Manual de usuario (con capturas) | [`docs/pdf/Manual_de_usuario.pdf`](docs/pdf/Manual_de_usuario.pdf) | [`docs/manual/manual_usuario.md`](docs/manual/manual_usuario.md) |
| Guía de despliegue | [`docs/pdf/Guia_de_despliegue.pdf`](docs/pdf/Guia_de_despliegue.pdf) | [`docs/despliegue.md`](docs/despliegue.md) |
| Registro de decisiones | [`docs/pdf/Registro_de_decisiones.pdf`](docs/pdf/Registro_de_decisiones.pdf) | [`docs/decisiones.md`](docs/decisiones.md) |
| Costos | [`docs/pdf/Costos.pdf`](docs/pdf/Costos.pdf) | [`docs/costos.md`](docs/costos.md) |

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `fase0/` | Experimentos A–D de la fase 0, bloque estándar de Alchemer, reglas de normalización, carga de la hoja "excluidos" |
| `db/` | Migraciones numeradas del esquema `empresas` (Postgres 16) y `migrate.py` |
| `api/` | API FastAPI para Cloud Run (`app/`), tests con Postgres real (`tests/`) y datos de demostración (`demo/`) |
| `web/` | Web sin framework para Firebase Hosting (`public/`) y `firebase.json` |
| `jobs/cdr/` | Job nocturno del CDR para el servidor Ubuntu (systemd o cron) |
| `infra/` | `desplegar.sh`: infraestructura de GCP, API, migraciones, web y Cloud Scheduler |
| `docs/` | Documentos, capturas y generador de PDFs |

## Arranque rápido (local)

```bash
pip install -r api/requirements-dev.txt
createdb empresas_dev
DATABASE_URL=postgresql://postgres@localhost/empresas_dev python api/demo/sembrar_demo.py
cd api && DATABASE_URL=postgresql://postgres@localhost/empresas_dev AUTH_MODE=dev SERVE_WEB=1 uvicorn app.main:app --port 8080
```

Abrir http://localhost:8080 y entrar con `admin@equipos.com.uy` (modo dev, sin clave). Los datos de la demo son ficticios.

## Tests

```bash
createdb empresas_test
cd api && TEST_DATABASE_URL=postgresql://postgres@localhost/empresas_test python -m pytest -q   # 77 tests, R1.1–R1.13
cd fase0 && python -m pytest -q
cd jobs/cdr && python -m pytest -q
```

## Despliegue

```bash
PROYECTO=<id del proyecto> ADMIN_EMAILS=<email> ./infra/desplegar.sh todo
```

Detalle en la [guía de despliegue](docs/despliegue.md).
