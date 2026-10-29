# Reglas de normalización de teléfonos uruguayos

Entregable de la fase 0 (R1.2). Las reglas están implementadas en `api/app/telefonos.py`
(`normalizar`, `es_interno`, `separar`, `nacional`) y las usan tanto el sistema como los scripts
de `fase0/`. Todo teléfono se guarda en **E.164** (`+598` + número nacional de 8 dígitos); si no
se puede normalizar, se guarda crudo con tipo `invalido` y motivo.

## Plan de numeración (vigente desde 2010)

| Tipo | Número nacional | Cómo se marca desde Uruguay | E.164 |
| --- | --- | --- | --- |
| Fijo Montevideo | `2XXXXXXX` (8 dígitos) | `2XXXXXXX` | `+5982XXXXXXX` |
| Fijo interior | `4XXXXXXX` (8 dígitos) | `4XXXXXXX` | `+5984XXXXXXX` |
| Celular | `9XXXXXXX` (8 dígitos, segundo dígito ≠ 0) | `09XXXXXXX` | `+5989XXXXXXX` |
| Especial | `0800`, `0900`, `0901`, `0904`, `0905`, `0909` + 4 dígitos | igual | `+598800XXXX…` (tipo `especial`, no discable) |

## Reglas, en el orden en que se aplican

1. **Limpieza:** se saca el interno escrito a mano (`int. 25`, `interno 25`, `ext 12`, `extensión 3`) y todo
   lo que no es dígito. Un número que vino como número de Excel (`29011234.0`) se toma entero.
2. **Prefijos de salida** (`prefijos_salida` en la configuración, `--prefijos-salida` en los scripts): si el
   número empieza con uno de ellos y después quedan al menos 8 dígitos, se saca. Sirve para los dígitos
   que agrega la central para tomar línea (por ejemplo `9`). Por defecto no hay ninguno.
3. **Código de país:** `+598`, `00598` o `598` seguido de 8 dígitos → se saca el `598`. Cualquier otro
   número que empieza con `+` o `00` es **internacional** (`+54…`); si tiene menos de 8 dígitos es inválido.
4. **Cero de larga distancia (formato anterior):** 9 dígitos que empiezan con `02` o `04` → se saca el 0
   (`029011234`, `042221234`, `(02) 901 1234`, `042 22 1234`).
5. **Celular con 0:** 9 dígitos que empiezan con `09` y el tercero no es 0 → celular (`098123456`).
6. **8 dígitos:** empieza con 2 o 4 → fijo; con 9 (segundo ≠ 0) → celular; con `0800`/`0900`… → especial.
7. **5 dígitos o menos:** interno (extensiones, colas). Los de 3 o 4 dígitos que empiezan con 1 y el 911
   son **especiales** (números cortos de servicio: 104, 1234…).
8. **7 dígitos:** inválido; es el formato anterior a 2010 y **no se completa solo** (no se sabe con
   certeza qué dígito agregar).
9. Cualquier otro largo: inválido con el motivo "N dígitos sin formato reconocido".

Una celda con varios números se separa antes con `separar()` por `/`, `;`, `,`, `|`, " y " u " o ":
`2901 1234 / 099 123 456; 4222 1234` → tres teléfonos.

## Destinos internos del CDR

Antes de normalizar el destino de cada llamada se descartan los **destinos internos**
(`destinos_internos` en la configuración; lista inicial en `fase0/datos/destinos_internos.csv`):
patrones regex si empiezan con `^` (`^\d{1,5}$`, `^\*`, `^#`) o números exactos tal como aparecen en el
CDR. Por eso en el CDR un `1234` cuenta como interno y no como número corto especial.

## Ejemplos

Tabla generada corriendo `normalizar()` (sin prefijos de salida):

| Entrada | E.164 | Tipo | Motivo |
| --- | --- | --- | --- |
| `+598 2901 1234` | +59829011234 | fijo |  |
| `00598 29011234` | +59829011234 | fijo |  |
| `598 29011234` | +59829011234 | fijo |  |
| `2901-1234` | +59829011234 | fijo |  |
| `29011234` | +59829011234 | fijo |  |
| `(02) 901 1234` | +59829011234 | fijo |  |
| `029011234` | +59829011234 | fijo |  |
| `4222 1234` | +59842221234 | fijo |  |
| `042 22 1234` | +59842221234 | fijo |  |
| `(042) 22 1234` | +59842221234 | fijo |  |
| `098 123 456` | +59898123456 | celular |  |
| `098123456` | +59898123456 | celular |  |
| `98123456` | +59898123456 | celular |  |
| `+598 98 123 456` | +59898123456 | celular |  |
| `59898123456` | +59898123456 | celular |  |
| `2901 1234 int. 25` | +59829011234 | fijo |  |
| `2901 1234 interno 25` | +59829011234 | fijo |  |
| `4733 1234 ext 12` | +59847331234 | fijo |  |
| `0800 1234` | +5988001234 | especial |  |
| `0900 1234` | +5989001234 | especial |  |
| `911` | — | especial | número corto de servicio |
| `104` | — | especial | número corto de servicio |
| `1234` | — | especial | número corto de servicio |
| `201` | — | interno | 5 dígitos o menos |
| `9011234` | — | invalido | 7 dígitos: formato anterior a 2010 |
| `29011234567` | — | invalido | 11 dígitos sin formato reconocido |
| `090 123 456` | — | invalido | 9 dígitos sin formato reconocido |
| `+54 11 4321 1234` | +541143211234 | internacional |  |
| `0054 11 4321 1234` | +541143211234 | internacional |  |
| `abc` | — | invalido | sin dígitos |
| (vacío) | — | invalido | vacío |

Con `prefijos_salida = ["9"]`: `929011234` → `+59829011234` (fijo).

Formato para discar (`nacional()`, el que va al CSV de uContact): `+59829011234` → `29011234`;
`+59898123456` → `098123456`.
