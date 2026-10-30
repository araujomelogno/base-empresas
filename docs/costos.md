# Costos

**La fase 0 no tiene costo de infraestructura. La fase 1 arranca en aproximadamente US$10–25 por mes**: Cloud SQL con el tamaño más chico (`db-f1-micro`) en Iowa (`us-central1`), y el resto de los servicios dentro de sus niveles gratuitos con el volumen previsto (menos de 50 usuarios internos, decenas de miles de empresas, unos pocos estudios a empresas por año). No hay gasto en APIs de enriquecimiento hasta la fase 2.

Los precios son de lista en dólares, sin impuestos, tomados en octubre de 2026. Los de las instancias de núcleo compartido de Cloud SQL salen de fuentes de terceros porque Google no los publica en una tabla fácil de citar; hay que confirmarlos en la [calculadora de Google Cloud](https://cloud.google.com/products/calculator) antes de aprobar el presupuesto. La configuración de cada servicio es la que crea `infra/desplegar.sh`.

## Resumen

| Concepto | Fase 0 | Fase 1, inicio (por mes) |
| --- | --- | --- |
| Infraestructura en Google Cloud y Firebase | US$0 | **US$10–25** |
| Servidor Ubuntu (job del CDR) | Ya existe | Ya existe |
| APIs de enriquecimiento (Places, búsqueda, IA) | — | US$0 (fase 2) |
| **Total recurrente** | **US$0** | **US$10–25** |

El PRD estimaba US$65–100 por mes para la infraestructura. La diferencia sale de dos decisiones (D27 y D31 en `docs/decisiones.md`): todo en Iowa y Cloud SQL con el tamaño mínimo para empezar.

## Fase 0

La fase 0 son scripts de Python (`fase0/`) que corren en una laptop o en el servidor Ubuntu sobre copias de los datos. No se crea ningún recurso en la nube.

| Concepto | Costo |
| --- | --- |
| Infraestructura | US$0 |
| Licencias | US$0 (Python y librerías libres) |
| Esfuerzo | 1–2 semanas de análisis según el spec: correr los experimentos A–D con un estudio terminado, acordar el bloque estándar con coordinación de campo y cargar la hoja "excluidos" |

## Fase 1: infraestructura mensual

| Componente | Configuración | Cálculo | US$ / mes |
| --- | --- | --- | --- |
| Cloud SQL Postgres (Enterprise) | `db-f1-micro`: núcleo compartido, 0,6 GB, 10 GB SSD, backups diarios y recuperación a un punto en el tiempo | ver detalle abajo | 10–14 |
| Cloud Run (API) | 1 vCPU, 1 GiB, mínimo 0 instancias, máximo 3; cobro por pedido | dentro del nivel gratuito | 0–5 |
| Cloud Run job (migraciones) | unos segundos por despliegue | dentro del nivel gratuito | 0 |
| Cloud Tasks | cientos de tareas por mes | primer millón de operaciones gratis | 0 |
| Cloud Scheduler | 1 trabajo (export de auditoría) | 3 trabajos gratis por cuenta | 0 |
| Cloud Storage | bases y .sav subidos, pocos GB | ≈ US$0,02 por GB | 0–1 |
| Secret Manager | 3 secretos | 6 versiones activas gratis | 0–1 |
| Artifact Registry y Cloud Build | imágenes de la API, pocos despliegues | 0,5 GB y minutos de build gratis | 0–2 |
| BigQuery | auditoría, menos de 10 GB | 10 GB y 1 TB de consultas gratis | 0–2 |
| Firebase Authentication | email y clave, menos de 50 usuarios | gratis | 0 |
| Firebase Hosting | web estática de menos de 1 MB | gratis | 0 |
| Cloud Logging y Monitoring | registros de la API | 50 GB gratis por proyecto | 0 |
| **Total** | | | **≈ 10–25** |

### Detalle de Cloud SQL

Cloud SQL se paga por hora mientras la instancia existe, aunque nadie la use. Es el único costo fijo.

| Ítem | Cálculo | US$ / mes |
| --- | --- | --- |
| Instancia `db-f1-micro` | 730 h × US$0,0105–0,015 | 7,7–11 |
| Disco SSD | 10 GB × US$0,17 | 1,7 |
| Backups y registros de recuperación | ≈ 2–10 GB × US$0,08 | 0,2–0,8 |
| **Total** | | **≈ 10–14** |

### Qué se resigna con `db-f1-micro`

- **Sin SLA de Google:** es una instancia de núcleo compartido. Para el arranque y el piloto es aceptable; los backups diarios y la recuperación a un punto en el tiempo siguen activos.
- **Poca capacidad:** 0,6 GB de memoria y 25 conexiones. La API se despliega con 5 conexiones por instancia y hasta 3 instancias para no pasarse. Las cargas grandes y los sorteos tardan más (corren en segundo plano, con barra de avance).
- **Sin descuento por compromiso de uso** (no aplica a núcleo compartido).

Las señales para pasar al siguiente tamaño y el paso a paso están en [`docs/cambio_a_small.md`](cambio_a_small.md).

## Escalones de Cloud SQL

Todos en Iowa, con 10 GB de disco y backups. El cambio entre escalones es un comando y unos minutos sin servicio; no se migran datos.

| Tamaño | CPU | Memoria | Conexiones | Instancia + disco + backups (US$ / mes) | Total infraestructura (US$ / mes) | Cuándo |
| --- | --- | --- | --- | --- | --- | --- |
| **`db-f1-micro`** (inicio) | compartida | 0,6 GB | 25 | ≈ 10–14 | ≈ 10–25 | Arranque y piloto |
| `db-g1-small` | compartida | 1,7 GB | 50 | ≈ 26–30 | ≈ 26–40 | Cuando aparecen las señales de `cambio_a_small.md` o en uso diario |
| `db-custom-1-3840` | 1 vCPU dedicada | 3,75 GB | ≈ 100 | ≈ 52 | ≈ 52–65 | Uso intensivo; tiene SLA y admite descuento por compromiso |

Cálculo de `db-custom-1-3840`: 1 vCPU × 730 h × US$0,0413 + 3,75 GB × 730 h × US$0,007 ≈ US$49, más disco y backups.

## Lo que puede hacer subir la factura

- **Almacenamiento de Cloud SQL:** tiene autoincremento. 50.000 empresas con su historia, teléfonos e intentos ocupan pocos GB; cada 10 GB adicionales suman unos US$1,7 por mes. El disco no se puede achicar después.
- **Instancia mínima de Cloud Run:** con mínimo 0, la primera llamada después de un rato sin uso tarda unos segundos en arrancar. Mantener una instancia siempre encendida cuesta del orden de US$10 por mes; se activa con `--min-instances 1` si molesta la espera.
- **Consultas largas en BigQuery:** solo si se consulta la auditoría con mucha frecuencia; el primer TB por mes es gratis.
- **Registros:** un error en bucle puede generar muchos registros. La alerta de errores 5xx sugerida en la guía de despliegue lo detecta.

El máximo de instancias de Cloud Run y de 2 tareas simultáneas en la cola limitan el costo aunque haya un pico de uso.

## Esfuerzo de la fase 1

El spec estima 7–8 semanas después de la fase 0. Lo construido en este repositorio cubre las cuatro iteraciones en código, tests y documentación; lo que queda es lo que no se puede hacer sin el entorno real:

| Iteración | Alcance | Estimación del spec | Pendiente para cerrarla |
| --- | --- | --- | --- |
| 1 — Base | R1.1–R1.4, R1.12, R1.13 | 2 semanas | Cargar las bases propias reales y la hoja "excluidos" |
| 2 — Muestra | R1.5–R1.7 | 2 semanas | Validar el formato del CSV con una importación de prueba en uContact |
| 3 — Campo | R1.8–R1.10 | 2 semanas | Instalar el job del CDR en el servidor Ubuntu; bloque estándar en Alchemer |
| 4 — Piloto | R1.11 y un estudio real de punta a punta | 1–2 semanas | Correr el estudio piloto y medir las métricas de la fase 1 |

Para pasar el esfuerzo a dinero: horas de cada rol × tarifa interna de Equipos. No se incluye acá porque depende de quién haga cada tarea.

## Referencia: fase 2

Fuera del alcance actual, pero para dimensionar (PRD): el enriquecimiento con cascada (Google Places, búsqueda web y extracción con IA), aplicado solo a las empresas que entran a muestra (unas 3.000 por mes, 40% llegando a pasos pagos), suma aproximadamente **US$50–60 por mes**. La carga semilla de 50.000 empresas sin cascada costaría unos US$2.400 por única vez; con cascada, una fracción.

## Fuentes

- [Cloud SQL — precios](https://cloud.google.com/sql/pricing): Enterprise con CPU dedicada, US$0,0413 por vCPU-hora y US$0,007 por GB-hora en Iowa.
- Núcleo compartido (`db-f1-micro` ≈ US$0,0105–0,015 por hora; `db-g1-small` ≈ US$0,033–0,035 por hora): [Bytebase](https://www.bytebase.com/dbcost/cloudsql-pricing/), [Cloud Price Check](https://cloudpricecheck-com.pages.dev/gcp/cloud-sql-pricing), [Spare Cores](https://sparecores.com/database/gcp/db-g1-small).
- Conexiones máximas por tamaño (25 y 50): [Demystifying max_connections in Cloud SQL for PostgreSQL](https://dev.to/gleb_otochkin/demystifying-max-connections-limit-in-cloud-sql-for-postgresql-55o6).
- [Cloud Run — precios](https://cloud.google.com/run/pricing), [Cloud Tasks](https://cloud.google.com/tasks/pricing), [Cloud Scheduler](https://cloud.google.com/scheduler/pricing), [Secret Manager](https://cloud.google.com/secret-manager/pricing), [Cloud Storage](https://cloud.google.com/storage/pricing), [BigQuery](https://cloud.google.com/bigquery/pricing) y [Firebase](https://firebase.google.com/pricing): niveles gratuitos.
- [Calculadora de Google Cloud](https://cloud.google.com/products/calculator), para confirmar los precios.
