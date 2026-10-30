# Job nocturno del CDR (R1.8)

`cdr_job.py` lee las llamadas nuevas de la base MySQL del CDR de uContact (`uc`) y las empuja a
la API (`POST /api/intentos/lote`). Corre a las 4:00 en una máquina de la red de Equipos, porque el
CDR no es accesible desde fuera: el servidor Ubuntu del dashboard de productividad (recomendado,
systemd) o una Mac de la oficina (launchd).

- Toma **todas** las llamadas, de campañas y del marcador manual: no filtra por campaña. La API
  normaliza el destino, descarta los destinos internos y cruza contra los teléfonos de la base.
- **Incremental:** `estado.json` guarda la última `calldate` enviada y los `uniqueid` de ese segundo.
  La consulta trae desde esa `calldate` (inclusive) y se saltean los ya enviados. El estado avanza
  **solo después de un POST exitoso**, lote a lote, y nunca retrocede.
- **Idempotente:** la API ignora los `cdr_id` repetidos, así que re-procesar un período no duplica intentos.
- Un `uniqueid` con varios tramos se envía una sola vez (el tramo con más `billsec`).

## Payload

Cada fila de `cdr` se envía como:

| Campo | Columna del CDR |
| --- | --- |
| `cdr_id` | `uniqueid` |
| `inicio` | `calldate` en ISO 8601 con la zona de Montevideo (`2026-10-28T10:15:00-03:00`) |
| `destino` | `dst` (crudo; lo normaliza la API) |
| `encuestador` | `peeraccount` |
| `duracion` | `billsec` (si no hay, `duration`) |
| `userfield` | `userfield` (disposición de llamada\|disposición de encuesta) |
| `disposicion` | `disposition` |
| `campania` | `accountcode` (o una columna `campania` si la consulta la devuelve) |

En lotes de `LOTE_TAMANO` (2000 por defecto): `{"origen": "uContact", "llamadas": [...]}` con el header
`X-Job-Token`. Imprime los conteos que devuelve la API (recibidas, internas, no cruzan, intentos nuevos,
asociados a ítem, duplicados…) sumados de todos los lotes.

## Instalación en el servidor Ubuntu

```bash
# 1. Código (o copiar solo jobs/cdr/)
sudo mkdir -p /opt/base-empresas && sudo chown equipos: /opt/base-empresas
git clone <repo> /opt/base-empresas
cd /opt/base-empresas/jobs/cdr

# 2. Entorno virtual
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Configuración (MySQL de solo lectura, URL de la API y JOB_TOKEN del Secret Manager)
cp cdr_job.env.example cdr_job.env
chmod 600 cdr_job.env
nano cdr_job.env

# 4. Prueba sin enviar nada: escribe el payload en un archivo
.venv/bin/python cdr_job.py --dry-run --dias 1
less cdr_payload_*.json

# 5. Primera carga real (por ejemplo, desde el inicio del período que interesa)
.venv/bin/python cdr_job.py --desde 2026-10-01

# 6. Timer de systemd (4:00, hora de Montevideo)
sudo cp cdr-job.service cdr-job.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cdr-job.timer
systemctl list-timers cdr-job.timer
```

Ajustar `User=` y las rutas de `cdr-job.service` si el usuario o la carpeta son otros.

**Alternativa con cron** (si no se usa systemd), con `crontab -e` del usuario del job:

```
CRON_TZ=America/Montevideo
0 4 * * * cd /opt/base-empresas/jobs/cdr && .venv/bin/python cdr_job.py >> /var/log/cdr_job.log 2>&1
```

## Instalación en una Mac

Sirve si el job corre en una Mac de la oficina en lugar del servidor Ubuntu. La Mac tiene que estar en
la red de Equipos (para llegar a MySQL), con la zona horaria de Montevideo y prendida a las 4:00: si
está dormida, `launchd` corre el job al despertarse; si está apagada, se saltea ese día y la corrida
siguiente trae todo lo pendiente (el job es incremental).

Requisitos: Python 3.12 de Homebrew (`brew install python@3.12`) y el repositorio clonado en
`~/base-empresas`. No conviene clonarlo dentro de Documentos, Escritorio o Descargas: macOS no deja que
`launchd` lea esas carpetas sin un permiso extra.

```bash
cd ~/base-empresas/jobs/cdr
```

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
cp cdr_job.env.example cdr_job.env && chmod 600 cdr_job.env && open -e cdr_job.env
```

Completar `cdr_job.env` (MySQL de solo lectura, `API_URL` y `JOB_TOKEN`) y probar sin enviar nada:

```bash
.venv/bin/python cdr_job.py --dry-run --dias 1
```

Primera carga real (por ejemplo, desde el inicio del período que interesa):

```bash
.venv/bin/python cdr_job.py --desde 2026-10-01
```

Programarlo con `launchd` a las 4:00 (el archivo de ejemplo usa `/Users/USUARIO`; el comando lo cambia
por tu carpeta personal):

```bash
sed "s#/Users/USUARIO#$HOME#g" uy.equipos.cdr-job.plist > ~/Library/LaunchAgents/uy.equipos.cdr-job.plist
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/uy.equipos.cdr-job.plist
```

```bash
launchctl print gui/$(id -u)/uy.equipos.cdr-job | grep -E "state|last exit"
```

Para que la Mac se despierte sola un poco antes (opcional, pide la clave de administrador):

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 03:55:00
```

Correrlo a mano, ver el log y desinstalarlo:

```bash
launchctl kickstart gui/$(id -u)/uy.equipos.cdr-job
```

```bash
tail -n 100 ~/Library/Logs/cdr-job.log
```

```bash
launchctl bootout gui/$(id -u)/uy.equipos.cdr-job && rm ~/Library/LaunchAgents/uy.equipos.cdr-job.plist
```

## Uso

```bash
python cdr_job.py                                     # incremental desde estado.json
python cdr_job.py --dias 3                            # primera vez sin estado: últimos 3 días
python cdr_job.py --desde 2026-10-01 --hasta 2026-10-02   # re-procesar un día (no mueve el estado hacia atrás)
python cdr_job.py --desde "2026-10-01 00:00:00" --no-estado
python cdr_job.py --dry-run --salida /tmp/payload.json
python cdr_job.py --exportar-auditoria                # además POST /api/jobs/auditoria-bq
```

El export diario de auditoría a BigQuery ya lo dispara Cloud Scheduler (`infra/desplegar.sh`, 5:10);
`--exportar-auditoria` es para cuando no se use Cloud Scheduler.

Códigos de salida: 0 bien, 1 falló un envío (el estado queda en el último lote enviado; la próxima
corrida sigue desde ahí), 2 falta configuración, 3 falló el export de auditoría. Los errores de red y
las respuestas 5xx/429 se reintentan con espera exponencial (`HTTP_REINTENTOS`, 5 por defecto).

**Consulta.** Por defecto:

```sql
SELECT uniqueid, calldate, src, dst, duration, billsec, disposition, userfield, peeraccount, accountcode
FROM cdr WHERE calldate >= %s ORDER BY calldate, uniqueid
```

Se cambia con `CDR_SQL` (por ejemplo, si la tabla tiene otro nombre o hay que unir con la tabla de
campañas). Tiene que devolver esas columnas (con `AS` si se llaman distinto) y venir ordenada por
`calldate`. Con dos `%s` recibe `desde` y `hasta`, y el re-proceso de un período no lee de más.

## Logs (servidor Ubuntu)

```bash
journalctl -u cdr-job.service --since today
journalctl -u cdr-job.service -n 100 --no-pager
systemctl status cdr-job.service
cat /opt/base-empresas/jobs/cdr/estado.json
sudo systemctl start cdr-job.service     # correrlo a mano ahora
```

## Tests

```bash
cd jobs/cdr && python -m pytest -q       # MySQL y HTTP simulados; no necesitan pymysql
```
