# Bloque estándar de variables para cuestionarios a empresas (Experimento C)

Todo cuestionario a empresas lleva este bloque con **los mismos nombres de variable**, así el
mapeo del .sav se reusa como plantilla de un estudio a otro (R1.9) y la base se actualiza con
lo que aprende la sala (R1.10). La versión que lee la máquina está en
[`alchemer_bloque_estandar.json`](alchemer_bloque_estandar.json): tiene la misma estructura que la
propuesta de mapeo de `api/app/sav.py` (`response_id`, `identificador`, `variables`, `valores`)
y se puede cargar como plantilla de la parte.

Estado: **propuesta, pendiente de acuerdo con coordinación de campo** (criterio de éxito del
experimento C).

## Variables

| Variable | Tipo en el .sav | Cómo se arma en Alchemer | Contenido | Obligatoria |
| --- | --- | --- | --- | --- |
| `EC_ID_ITEM` | Numérica | URL variable oculta (Hidden Value) | Identificador del ítem de muestra (`id_item` del CSV de uContact) | Sí |
| `EC_RUT` | Texto | URL variable oculta (Hidden Value) | RUT de la empresa, 12 dígitos sin puntos | Sí |
| `EC_TEL_USADO` | Texto | URL variable oculta; pregunta si se llamó a otro número | Teléfono con el que se hizo la encuesta | Sí |
| `EC_CALIDAD_TEL` | Numérica con etiquetas | Pregunta cerrada (radio), interna del encuestador | Calidad del número marcado (códigos abajo) | Sí |
| `EC_TEL_ALT` | Texto | Pregunta abierta | Número alternativo que dieron | No |
| `EC_RESP_NOMBRE` | Texto | Pregunta abierta | Nombre de quien contestó | No |
| `EC_RESP_CARGO` | Texto | Pregunta abierta | Cargo de quien contestó | No |
| `EC_RESP_AREA` | Texto | Pregunta abierta | Área de quien contestó | No |
| `EC_RESULTADO` | Numérica con etiquetas | Pregunta cerrada al final, o estado de Alchemer | Resultado del contacto (códigos abajo) | Sí |

Además el .sav de Alchemer trae `responseid` (identificador de la respuesta, base de la
idempotencia), `status` y `datesubmitted`; no hay que agregarlas.

### Códigos

`EC_CALIDAD_TEL`

| Código | Etiqueta | Valor en el sistema | Efecto en la base |
| --- | --- | --- | --- |
| 1 | Corresponde a la empresa | `corresponde` | Vínculo teléfono–empresa verificado |
| 2 | No es de la empresa | `no_corresponde` | Vínculo "no corresponde"; sale de las exportaciones |
| 3 | Estudio contable o jurídico | `intermediario` | Teléfono intermediario confirmado |
| 4 | La empresa cerró | `cerro` | La empresa pasa a estado "cerrada" |
| 5 | Número inexistente | `inexistente` | Vínculo inexistente |

`EC_RESULTADO`

| Código | Etiqueta | Valor en el sistema |
| --- | --- | --- |
| 1 | Completa | `completa` |
| 2 | Rechazo | `rechazo` |
| 3 | No corresponde | `no_corresponde` |
| 4 | Agendada | `agendada` |

Si un estudio no usa `EC_RESULTADO`, el sistema toma el `status` de Alchemer
(Complete → completa, Partial → parcial, Disqualified → descalificada). `EC_RESULTADO` gana
cuando están las dos.

## Cómo se arma en Alchemer

1. **URL variables ocultas** (`EC_ID_ITEM`, `EC_RUT`, `EC_TEL_USADO`): en la primera página,
   agregar una acción *Hidden Value* por variable con el valor `[url("EC_ID_ITEM")]` (y
   `[url("EC_RUT")]`, `[url("EC_TEL_USADO")]`). El nombre de la variable en la URL distingue
   mayúsculas: usar exactamente estos.
2. **Preguntas** (`EC_CALIDAD_TEL`, `EC_TEL_ALT`, `EC_RESP_*`, `EC_RESULTADO`): crearlas en una
   página de cierre, visibles solo para el encuestador.
3. **Nombre de la variable en la exportación:** en cada elemento, poner como alias de la pregunta
   (*Question Alias* / alias de reporte) el nombre `EC_…` exacto, para que la exportación a SPSS
   use ese nombre. Verificarlo en la exportación de prueba (paso 6).
4. **Códigos:** en las preguntas cerradas, cargar los *Reporting Values* de cada opción con el
   código de la tabla (1…5 y 1…4), para que el .sav traiga el código y la etiqueta.
5. Guardar el bloque como **plantilla / biblioteca** de Alchemer ("Bloque estándar EC") para copiarlo
   en cada cuestionario nuevo.
6. **Prueba:** abrir el link con valores de prueba, completar dos respuestas, exportar el .sav y
   correr `python fase0/exp_b_sav.py --lista <lista> --sav <export>.sav`: las 9 variables del bloque
   tienen que figurar como "presente".

## Link con URL variables

El CSV que genera el sistema para uContact (R1.7) trae, por renglón, el link de la parte con las
URL variables completas:

```
https://survey.alchemer.com/s3/<survey_id>/<nombre>?EC_ID_ITEM=1234&EC_RUT=211234560019&EC_TEL_USADO=29011234
```

- `EC_RUT` sin puntos ni guion; `EC_TEL_USADO` en formato nacional (`29011234`, `099123456`).
- Si el encuestador termina haciendo la encuesta en otro número (el que le dieron por teléfono), lo
  corrige en la pregunta de confirmación de `EC_TEL_USADO` y anota el alternativo en `EC_TEL_ALT`.
- **Si el experimento A no llega al 95%,** `EC_TEL_USADO` pasa a ser pregunta obligatoria (no solo
  URL variable).
- **Si el experimento B falla porque faltan las URL variables,** el identificador pasa a ser
  RUT + teléfono y el bloque es obligatorio desde el primer estudio de la fase 1.
