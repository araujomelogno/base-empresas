# Fase 0 — Validar los cruces

Scripts en Python para probar, con datos reales de un estudio a empresas ya terminado, que
**las llamadas** (por número destino) y **las respuestas** (por el .sav) se asocian a la empresa
y al teléfono sin trabajo manual (ver `specs/Spec Fase 0 y 1.md`, sección "Fase 0"). No se
despliega nada: corren en el servidor Ubuntu o en una laptop, sobre copias de los datos.

Los scripts reusan los módulos puros del backend (`api/app/telefonos.py`, `rut.py`,
`lectores.py`, `sav.py`), así las reglas que se validan acá son las mismas que usa el sistema.
No necesitan base de datos.

## Requisitos

Python 3.11+ con las dependencias del backend (`pip install -r api/requirements.txt`; alcanza con
fastapi, psycopg, psycopg_pool, pandas, openpyxl, pyreadstat). Los comandos se corren desde la raíz
del repo. Todo lo que generan va a `fase0/salida/` (ignorado por git: puede tener datos reales).

## Insumos

| Insumo | Formato | Lo usa |
| --- | --- | --- |
| Lista de teléfonos del estudio reciente | .xlsx/.csv con RUT, teléfono(s) y, si lo hay, `id_item` | A, B |
| CDR del período de campo (todas las llamadas, campañas y manuales) | .csv/.xlsx exportado de la base `uc` de uContact | A |
| .sav de cada parte (exportación de Alchemer) | .sav | B |
| Hoja "excluidos" del Excel de referencia | .xlsx | catálogo de naturalezas |
| 2 o 3 bases propias de estudios anteriores | .xlsx/.csv | D |

**CDR.** Por defecto se usan las columnas de la tabla `cdr` de Asterisk/uContact: `calldate`, `dst`,
`src`, `duration`, `billsec`, `disposition`, `userfield`, `peeraccount`, `uniqueid`, `accountcode`.
También se reconocen los encabezados del export de la web de uContact (`Fecha/Hora`, `Destino`,
`Agente`, `Campo Usuario`, `GUID`, `Disposición`, `Cola`). Si el archivo usa otros nombres:
`--col-dst`, `--col-calldate`, `--col-uniqueid`, etc. Para sacar el CDR directo de MySQL:

```sql
SELECT uniqueid, calldate, src, dst, duration, billsec, disposition, userfield, peeraccount, accountcode
FROM cdr WHERE calldate >= '2026-09-01' AND calldate < '2026-10-01' ORDER BY calldate, uniqueid;
```

Las columnas de la lista y de las bases (RUT, teléfono, razón social, `id_item`) se detectan por
nombre o por contenido; si la detección falla, se indican con `--col-rut`, `--col-tel` (repetible),
`--col-id`, `--col-razon`.

## Experimentos

| # | Script | Qué hace | Criterio go |
| --- | --- | --- | --- |
| A | `exp_a_cdr.py` | Normaliza a E.164 el destino de cada llamada, descarta los destinos internos y cruza con los teléfonos de la lista. Lo que no cruza se clasifica: especial/servicio, fuera de lista (fijo o celular), internacional, no normalizable. Separa campaña y manual, sugiere prefijos de salida y lista los destinos que no cruzan más frecuentes. | ≥ 95% de las llamadas salientes externas cruzan o quedan explicadas por una regla |
| B | `exp_b_sav.py` | Lee cada .sav, propone el mapeo con `app.sav.proponer` (identificador, bloque estándar, códigos) y asocia cada fila a una empresa de la lista: `id_item` → RUT → teléfono usado. Informa el bloque estándar presente/faltante y los códigos sin mapear. | ≥ 95% de las filas de cada .sav asociadas; las que no, con motivo |
| C | `alchemer_bloque_estandar.md` / `.json` | Bloque estándar de variables `EC_*` y cómo armarlo en Alchemer. Es manual: se acuerda con coordinación de campo. | Bloque acordado |
| D | `exp_d_bases.py` | Une las bases por RUT: RUTs inválidos (por motivo), sin RUT, duplicados en y entre bases, razón social en conflicto, teléfonos compartidos por ≥ N RUTs y distribución para ajustar el umbral. | Conteos documentados; umbral confirmado o ajustado |

Además:

- `cargar_excluidos.py`: catálogo inicial de naturalezas jurídicas desde la hoja "excluidos".
- `informe.py`: corre A, B y D, agrega C y el catálogo, y escribe `fase0/salida/informe_validacion.md`
  con la decisión go/no-go.
- `datos/reglas_normalizacion.md`: reglas de normalización de teléfonos uruguayos (con ejemplos).
- `datos/destinos_internos.csv`: lista inicial de destinos internos a ignorar en el CDR (patrones de la
  configuración inicial + filas a completar con coordinación de campo).
- `datos_ejemplo/generar.py`: datos sintéticos para probar todo sin datos reales.

## Comandos

Probar con datos sintéticos (genera `fase0/salida/ejemplo/` y el informe):

```bash
python fase0/datos_ejemplo/generar.py
python fase0/informe.py --ejemplo
```

Con los datos reales:

```bash
# A — llamadas por número destino
python fase0/exp_a_cdr.py --lista datos/lista_estudio.xlsx --cdr datos/cdr_periodo.csv \
    [--desde 2026-09-01 --hasta 2026-09-30] [--prefijos-salida 9] [--internos '^3\d{3}$' 29001234] \
    [--otras-listas datos/lista_otro_estudio.xlsx] [--detalle fase0/salida/exp_a_no_cruzan.xlsx]

# B — respuestas del .sav (uno por parte)
python fase0/exp_b_sav.py --lista datos/lista_estudio.xlsx --sav datos/parte1.sav datos/parte2.sav

# D — bases propias
python fase0/exp_d_bases.py --bases datos/base1.xlsx datos/base2.csv datos/base3.xlsx [--umbral 5]

# Catálogo de naturalezas excluidas (SQL; opcionalmente por la API)
python fase0/cargar_excluidos.py datos/referencia.xlsx [--hoja excluidos]
python fase0/cargar_excluidos.py datos/referencia.xlsx --api https://<api> --token <ID token de Firebase>
python fase0/cargar_excluidos.py datos/referencia.xlsx --api http://localhost:8080 --dev-user admin@equipos.com.uy

# Informe completo
python fase0/informe.py --lista datos/lista_estudio.xlsx --cdr datos/cdr_periodo.csv \
    --sav datos/parte1.sav datos/parte2.sav --bases datos/base1.xlsx datos/base2.csv \
    --excluidos datos/referencia.xlsx [--prefijos-salida 9]
```

Cada experimento escribe su markdown (`fase0/salida/exp_a.md`, `exp_b.md`, `exp_d.md`) y el detalle:
`exp_a_no_cruzan.csv`, `exp_b_sin_asociar.csv`, `exp_b_mapeo_<archivo>.json` (mapeo propuesto, sirve de
plantilla de la parte), `exp_d_telefonos_compartidos.csv`, `exp_d_razon_social_conflictos.csv`.

Tests (con los datos sintéticos, sin base de datos):

```bash
cd fase0 && python -m pytest -q
```

## Cómo leer el go/no-go

**A.** La base del porcentaje son las llamadas *salientes externas*: todas menos las internas (las que
cumplen un patrón de `destinos_internos`). Cuentan como cruzadas o explicadas: las que cruzan con la
lista, las que cruzan con `--otras-listas` del mismo período y las especiales (0800, 0900, cortos).
No cuentan: números fuera de lista, internacionales y no normalizables. Antes de dar un no-go:

1. Mirar "Posibles prefijos de salida": si la central agrega un dígito, correr con `--prefijos-salida`.
2. Mirar "Destinos que no cruzan más frecuentes": un número propio, un buzón o un número de supervisor
   va a `datos/destinos_internos.csv`; si son de otro estudio del período, pasar su lista con `--otras-listas`.
3. Comparar campaña y manual: si el manual cruza mucho peor, el problema es cómo se marca a mano.

Si aun así **A < 95%**: `EC_TEL_USADO` pasa a ser pregunta obligatoria y el cruce de llamadas queda
como informativo.

**B.** Se exige ≥ 95% en *cada* .sav. El informe muestra con qué método se asoció cada fila (id_item,
RUT, teléfono), qué variables del bloque estándar faltan y los motivos de las filas sin asociar. Si
**B falla porque faltan las URL variables** (`EC_ID_ITEM`/`EC_RUT`): el identificador pasa a ser
RUT + teléfono y se exige el bloque estándar desde el primer estudio de la fase 1. Si pasa pero algún
.sav no trae `EC_ID_ITEM`, el informe lo marca igual: la plantilla de Alchemer es obligatoria desde el
piloto.

**C.** Queda como checklist manual en el informe.

**D.** No tiene go/no-go: documenta los conteos. La tabla "Teléfonos que quedarían sospechosos según el
umbral" y la lista de teléfonos compartidos sirven para que el data steward confirme el umbral de
intermediario (5 por defecto) o lo ajuste en la configuración.

**Decisión global** (`informe.py`): **GO** si A y B pasan; **GO con ajustes** si alguno falla (se
aplican los planes B del spec, listados en el informe); **INCOMPLETA** si faltan insumos de A o B.
