---
titulo: Costos
subtitulo: Base de Empresas — Fase 0 y Fase 1
---

# Costos

**La fase 0 no tiene costo de infraestructura. La fase 1 cuesta aproximadamente US$80–100 por mes, y casi todo es la instancia de Cloud SQL**; el resto de los servicios entra en los niveles gratuitos con el volumen previsto (menos de 50 usuarios internos, decenas de miles de empresas, unos pocos estudios a empresas por año). No hay gasto en APIs de enriquecimiento hasta la fase 2.

Los precios son de lista en dólares, sin impuestos, tomados en octubre de 2026. Los de Cloud SQL en São Paulo son una **estimación** a partir de los de Iowa (la región de referencia de Google) con un recargo regional del orden de 50%; hay que confirmarlos en la [calculadora de Google Cloud](https://cloud.google.com/products/calculator) antes de aprobar el presupuesto. La configuración de cada servicio es la que crea `infra/desplegar.sh`.

## Resumen

| Concepto | Fase 0 | Fase 1 (por mes) |
| --- | --- | --- |
| Infraestructura en Google Cloud y Firebase | US$0 | **US$80–100** |
| Servidor Ubuntu (job del CDR) | Ya existe | Ya existe |
| APIs de enriquecimiento (Places, búsqueda, IA) | — | US$0 (fase 2) |
| **Total recurrente** | **US$0** | **US$80–100** |

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
| Cloud SQL Postgres (Enterprise) | 1 vCPU, 3,75 GB, 20 GB SSD, backups diarios y recuperación a un punto en el tiempo, São Paulo | ver detalle abajo | 75–90 |
| Cloud Run (API) | 1 vCPU, 1 GiB, mínimo 0 instancias, máximo 4; cobro por pedido | dentro del nivel gratuito | 0–5 |
| Cloud Run job (migraciones) | unos segundos por despliegue | dentro del nivel gratuito | 0 |
| Cloud Tasks | cientos de tareas por mes | primer millón de operaciones gratis | 0 |
| Cloud Scheduler | 1 trabajo (export de auditoría) | 3 trabajos gratis por cuenta | 0 |
| Cloud Storage | bases y .sav subidos, pocos GB | US$0,02–0,04 por GB | 0–1 |
| Secret Manager | 3 secretos | 6 versiones activas gratis | 0–1 |
| Artifact Registry y Cloud Build | imágenes de la API, pocos despliegues | 0,5 GB y minutos de build gratis | 0–2 |
| BigQuery | auditoría, menos de 10 GB | 10 GB y 1 TB de consultas gratis | 0–5 |
| Firebase Authentication | email y clave, menos de 50 usuarios | gratis | 0 |
| Firebase Hosting | web estática de menos de 1 MB | gratis | 0 |
| Cloud Logging y Monitoring | registros de la API | 50 GB gratis por proyecto | 0 |
| **Total** | | | **≈ 80–100** |

### Detalle de Cloud SQL

Cloud SQL se paga por hora mientras la instancia existe, aunque nadie la use. Es el único costo fijo relevante.

| Ítem | Iowa (precio de lista) | São Paulo (estimado) |
| --- | --- | --- |
| 1 vCPU × 730 h × US$0,0413 | US$30,1 | ≈ US$45 |
| 3,75 GB × 730 h × US$0,007 | US$19,2 | ≈ US$29 |
| 20 GB SSD × US$0,17 | US$3,4 | ≈ US$5 |
| Backups y registros de recuperación (≈ 10–20 GB) | US$1–2 | ≈ US$1,5–3 |
| **Total** | **≈ US$54** | **≈ US$80** |

### Lo que puede hacer subir la factura

- **Almacenamiento de Cloud SQL:** tiene autoincremento. 50.000 empresas con su historia, teléfonos e intentos ocupan pocos GB; cada 10 GB adicionales suman unos US$2–3 por mes.
- **Instancia mínima de Cloud Run:** con mínimo 0, la primera llamada después de un rato sin uso tarda unos segundos en arrancar. Mantener una instancia siempre encendida cuesta del orden de US$10 por mes; se activa con `--min-instances 1` si molesta la espera.
- **Consultas largas en BigQuery:** solo si se consulta la auditoría con mucha frecuencia; el primer TB por mes es gratis.
- **Registros:** un error en bucle puede generar muchos registros. La alerta de errores 5xx sugerida en la guía de despliegue lo detecta.

El máximo de 4 instancias de Cloud Run y de 2 tareas simultáneas en la cola limitan el costo aunque haya un pico de uso.

## Cómo bajar el costo

| Opción | Ahorro aproximado | Contra |
| --- | --- | --- |
| Compromiso de uso de Cloud SQL a 1 año | 25% de vCPU y memoria (≈ US$18/mes) | Se paga aunque se dé de baja el sistema |
| Compromiso a 3 años | 52% (≈ US$38/mes) | Plazo largo para un sistema nuevo |
| Región Iowa (`us-central1`) en vez de São Paulo | ≈ US$25/mes | Más latencia desde Montevideo y datos fuera de la región |
| Instancia de núcleo compartido (`db-g1-small`) durante el piloto | ≈ US$40–50/mes | Sin SLA ni capacidad para cargas grandes; hay que cambiarla antes de operar |
| Compartir la instancia de Cloud SQL con otro sistema (por ejemplo, paneles) | ≈ US$75–90/mes | Se pierde el aislamiento que motivó un sistema independiente (PRD) |

La recomendación es empezar sin compromiso y evaluar el de 1 año después del piloto, cuando el sistema esté en uso estable.

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

Fuera del alcance actual, pero para dimensionar (PRD): el enriquecimiento con cascada (Google Places, búsqueda web y extracción con IA), aplicado solo a las empresas que entran a muestra (unas 3.000 por mes, 40% llegando a pasos pagos), suma aproximadamente **US$50–60 por mes**, con lo que el total recurrente quedaría en US$130–160. La carga semilla de 50.000 empresas sin cascada costaría unos US$2.400 por única vez; con cascada, una fracción.

## Fuentes

- [Cloud SQL — precios](https://cloud.google.com/sql/pricing): Enterprise, US$0,0413 por vCPU-hora y US$0,007 por GB-hora en Iowa.
- [Cloud Run — precios](https://cloud.google.com/run/pricing), [Cloud Tasks](https://cloud.google.com/tasks/pricing), [Cloud Scheduler](https://cloud.google.com/scheduler/pricing), [Secret Manager](https://cloud.google.com/secret-manager/pricing), [Cloud Storage](https://cloud.google.com/storage/pricing), [BigQuery](https://cloud.google.com/bigquery/pricing) y [Firebase](https://firebase.google.com/pricing): niveles gratuitos.
- [Calculadora de Google Cloud](https://cloud.google.com/products/calculator), para confirmar los precios de São Paulo.
