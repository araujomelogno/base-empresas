# Cambio de Cloud SQL de db-f1-micro a db-g1-small

La Base de Empresas arranca con la instancia de Cloud SQL más chica, **`db-f1-micro`**, en Iowa (`us-central1`), para bajar el costo mientras el uso es bajo (ver `docs/costos.md` y la decisión D31 en `docs/decisiones.md`). Este documento explica **cuándo** conviene pasar a **`db-g1-small`** y **cómo** hacerlo sin perder datos.

El cambio es reversible, no requiere migrar datos ni cambiar código. La base queda **sin servicio unos minutos** mientras se reinicia.

## Qué cambia

| | `db-f1-micro` (actual) | `db-g1-small` |
| --- | --- | --- |
| CPU | Núcleo compartido (≈ 0,2 vCPU) | Núcleo compartido (≈ 0,5 vCPU) |
| Memoria | 0,6 GB | 1,7 GB |
| Conexiones máximas de Postgres | 25 | 50 |
| Conexiones por instancia de la API (`DB_POOL_MAX`) | 5 | 8 |
| Instancias máximas de Cloud Run | 3 | 4 |
| Costo de la instancia en Iowa | ≈ US$8–11 por mes | ≈ US$24–26 por mes |
| SLA de Google | No | No |

El disco (10 GB con autoincremento), los backups y la región no cambian. La diferencia de costo es de unos **US$15–18 por mes**.

## Cuándo cambiar

Conviene pasar a `db-g1-small` cuando aparece **alguna** de estas señales, o antes de que el sistema pase del piloto al uso diario con estudios reales:

| Señal | Dónde se ve |
| --- | --- |
| CPU de Cloud SQL por encima del 80% de forma sostenida en horario de uso | Consola → SQL → `empresas-pg` → *Supervisión* (CPU utilization) |
| Memoria cerca del 100% o reinicios inesperados de la instancia | Misma pantalla (Memory usage) y *Operaciones* de la instancia |
| Errores `remaining connection slots are reserved` o `too many clients` | Cloud Run → `empresas-api` → *Registros* |
| El preview o la confirmación de una carga de más de 20.000 filas tarda más de 15 minutos | Barra de avance de la carga en la web |
| Sortear una muestra o abrir el tablero de actividad tarda más de 10 segundos | Uso diario |
| Más de 10 personas usando el sistema al mismo tiempo | Uso diario |

Para mirar cuántas conexiones hay abiertas en un momento dado (Consola → SQL → `empresas-pg` → *Cloud SQL Studio*):

```sql
SELECT count(*) AS conexiones, max_conn::int AS maximo
FROM pg_stat_activity, (SELECT setting AS max_conn FROM pg_settings WHERE name = 'max_connections') m
GROUP BY max_conn;
```

## Antes de cambiar

1. **Elegí la ventana.** El reinicio deja la base fuera de servicio entre 1 y 5 minutos. Evitá los horarios automáticos: el job del CDR (4:00), el export de auditoría (5:10) y el backup diario (6:00). Un día hábil al mediodía o al terminar la jornada funciona bien.
2. **Avisá a los usuarios** que el sistema no va a responder unos minutos.
3. **Verificá que no haya tareas corriendo** (cargas o ingestas en proceso). En Cloud SQL Studio:

   ```sql
   SELECT id, tipo, estado, creado FROM empresas.tarea WHERE estado IN ('pendiente', 'corriendo');
   ```

   Si hay alguna, esperá a que termine. Las que queden a mitad no se pierden: Cloud Tasks las reintenta y se pueden volver a lanzar desde la pantalla, pero es más prolijo esperar.
4. Tené a mano el id del proyecto y una sesión de `gcloud` con permisos de administración (`gcloud auth login`).

## Paso a paso

Desde la raíz del repositorio:

```bash
PROYECTO=equipos-base-empresas TIER=db-g1-small ./infra/desplegar.sh redimensionar
```

El comando:

1. Lee el tamaño actual de la instancia `empresas-pg`.
2. Hace un **backup a pedido** ("antes de pasar a db-g1-small").
3. Cambia el tamaño (`gcloud sql instances patch --tier db-g1-small`). La instancia se reinicia.
4. Actualiza la API en Cloud Run: `DB_POOL_MAX=8` y hasta 4 instancias, para aprovechar las 50 conexiones.
5. Muestra el tamaño y el estado final de la instancia.

Si preferís hacerlo a mano, son los mismos comandos:

```bash
gcloud sql backups create --instance empresas-pg --description "antes de pasar a db-g1-small"
gcloud sql instances patch empresas-pg --tier db-g1-small
gcloud run services update empresas-api --region us-central1 --max-instances 4 --update-env-vars DB_POOL_MAX=8
```

Los despliegues siguientes (`./infra/desplegar.sh api`) leen el tamaño real de la instancia y mantienen estos valores solos; no hace falta volver a indicar `TIER`.

## Verificación

```bash
gcloud sql instances describe empresas-pg --format 'value(settings.tier,state)'
# db-g1-small	RUNNABLE

URL=$(gcloud run services describe empresas-api --region us-central1 --format 'value(status.url)')
curl -s $URL/api/salud
# {"ok":true}

gcloud run services describe empresas-api --region us-central1 --format yaml | grep -A1 DB_POOL_MAX
# - name: DB_POOL_MAX
#   value: '8'
```

Después, en la web:

- Entrar y ver la pantalla de inicio.
- Abrir una empresa y una muestra.
- Si había una carga o ingesta pendiente, confirmar que terminó.

## Si algo sale mal

- **La instancia no vuelve a `RUNNABLE` en 10 minutos:** revisá Consola → SQL → `empresas-pg` → *Operaciones*. Google puede tardar más si la zona está cargada; no lances otro cambio mientras haya una operación en curso.
- **La API da errores de conexión después del cambio:** forzá una revisión nueva de Cloud Run para que abra conexiones nuevas:

  ```bash
  gcloud run services update empresas-api --region us-central1 --update-env-vars REINICIO=$(date +%s)
  ```

- **Volver a `db-f1-micro`:** el mismo comando con el tamaño anterior. Vuelve a poner `DB_POOL_MAX=5` y 3 instancias.

  ```bash
  PROYECTO=equipos-base-empresas TIER=db-f1-micro ./infra/desplegar.sh redimensionar
  ```

- **Hace falta recuperar datos:** el backup a pedido queda en Consola → SQL → `empresas-pg` → *Copias de seguridad*. Restaurarlo pisa la base actual; para revisar sin tocar producción, cloná la instancia (ver `docs/despliegue.md`, Backups y restauración).

## Después del cambio

- Actualizá la tabla de **Fase 1: infraestructura mensual** de `docs/costos.md` con el tamaño nuevo.
- Marcá en `docs/decisiones.md` (D31) la fecha del cambio.
- El cambio queda registrado, con fecha y autor, en Consola → SQL → `empresas-pg` → *Operaciones*.

## El paso siguiente

Si con `db-g1-small` vuelven a aparecer las mismas señales, el próximo tamaño es una instancia con CPU dedicada, `db-custom-1-3840` (1 vCPU, 3,75 GB, unas 100 conexiones, ≈ US$50 por mes en Iowa). Esa ya tiene SLA de Google y admite descuento por compromiso de uso. El procedimiento es el mismo:

```bash
PROYECTO=equipos-base-empresas TIER=db-custom-1-3840 ./infra/desplegar.sh redimensionar
```
