# SPEC — Aceptar RUT de cualquier largo (sin control de largo)

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_rut_sin_control_de_largo.md`, para que Claude Code lo implemente y lo despliegue.
**Base:** `main` actual.
**Fecha:** 23/11/2026
**Decisión:** Germán Araújo pidió desactivar el control del largo del RUT. Se le presentaron como alternativas la base provisoria y la cédula como identificador, y eligió esta opción sabiendo sus riesgos (sección 6).

---

## 1. Problema

- Al cargar la base `acumulaGermanV7` (Mypes), se rechazan filas con el motivo «RUT con 7 dígitos (se esperan 12)» u «RUT con 8 dígitos…».
- `rut.validar` (`api/app/rut.py`) exige 12 dígitos, registro 01–22, «001» en las posiciones 9 a 11 y el dígito verificador.
- Esas filas son empresas de la base que se quieren tener, aunque su identificador no tenga el formato de RUT de la DGI. En bases como Mypes suelen ser cédulas de unipersonales.

## 2. Objetivo

Que una carga **no rechace** una fila porque su RUT tiene un largo distinto de 12. La fila entra a la base definitiva con ese número como identificador, igual que cualquier otra empresa.

## 3. Requisitos (P0)

### R1. Regla nueva de validación

`rut.validar` pasa a tener dos niveles:

| Caso | Resultado |
|---|---|
| Exactamente 12 dígitos | **Se valida como hoy**: registro, «001» y dígito verificador. Si falla, se rechaza con el motivo actual. Un RUT de 12 dígitos mal tipeado sigue sin entrar. |
| Entre **6 y 11 dígitos**, solo números (después de sacar puntos, guiones, espacios y el prefijo «UY») | **Se acepta** como identificador **«no verificado»**. No se controlan el largo, el registro ni el dígito verificador. |
| Vacío, con letras, o con más de 12 dígitos | Se rechaza como hoy. |

- **Ceros a la izquierda:** se mantiene la corrección actual (11 dígitos que empiezan con 1–9 → se agrega un 0 adelante y se valida como RUT de 12). Con 6 a 10 dígitos **no se agregan ceros**: se guarda el número tal como vino, normalizado a solo dígitos.
- **Interruptor:** la aceptación se controla en **Configuración → Cargas**, con la opción «Aceptar identificadores de 6 a 11 dígitos sin validar». Viene **activada**. Si se desactiva, el comportamiento vuelve a ser el de hoy.
- **Mismas reglas para todos:** se aplica igual en la carga, en la búsqueda, en la ficha, en el alta manual de empresas, en «Agregar RUT» de la base provisoria y en el `EC_RUT` del .sav.

### R2. Guardado y marca

- **Columna `empresa.rut`:** hoy es `char(12)`, que rellena con espacios un valor más corto. Pasa a ser `varchar(12)` (o `text` con un CHECK de solo dígitos). La migración convierte los valores existentes sin cambiarlos.
- **Columna nueva `empresa.rut_verificado`** (boolean): `true` para los RUT de 12 dígitos válidos y `false` para los aceptados por R1.
- **Unicidad:** se mantiene sobre el número normalizado. No puede haber dos empresas con el mismo identificador.
- **Ficha:** junto al identificador, los no verificados muestran la etiqueta **«RUT no verificado (N dígitos)»**.
- **Buscador:** se agrega el filtro «RUT verificado / no verificado».
- **Formato visible:** `rut.formatear` muestra los no verificados sin el formato `21.234.567.001-8`, solo con los dígitos.

### R3. Que nada del sistema dependa de 12 dígitos

Hay que revisar todos los lugares que asumen 12 dígitos. Al menos:

- **Web:** la ruta de la ficha, `RUTAS` en `web/public/js/app.js` (`/^empresas\/(\d{12})$/`), pasa a aceptar 6 a 12 dígitos. Los enlaces y `rutFmt` también.
- **Buscador:** hoy busca por RUT a partir de 4 dígitos, y eso sigue igual.
- **Exportación:** `EC_RUT` sale con el número tal cual. El link de Alchemer lleva ese valor.
- **.sav:** la asociación por `EC_RUT` compara contra el identificador normalizado.
- **Reglas de fusión:** la regla `rut` exacta compara los números normalizados.
- **Tablero de calidad:** la regla de **validez** («RUT con dígito verificador correcto») informa por separado cuántas empresas tienen RUT no verificado. Pasan a ser un indicador nuevo, «Empresas con RUT no verificado», en lugar de contar como incumplimiento.

**Criterios de aceptación:**

- [ ] Una carga con filas de RUT de 7 y 8 dígitos las da de alta en la base definitiva. Esas filas quedan con `rut_verificado = false` y aparecen en la ficha con la etiqueta.
- [ ] Un RUT de 12 dígitos con dígito verificador incorrecto **sigue rechazándose**.
- [ ] Un RUT con letras, vacío o de 13 dígitos sigue rechazándose.
- [ ] La ficha de una empresa con RUT de 7 dígitos abre por URL. El buscador la encuentra. Sale en el CSV de la muestra y el .sav se asocia por su `EC_RUT`.
- [ ] Dos filas con el mismo número de 8 dígitos son la misma empresa (una alta y una actualización).
- [ ] Con el interruptor de Configuración desactivado, esas filas vuelven a rechazarse.
- [ ] Los tests existentes siguen pasando, salvo los que verifican el rechazo por largo: se actualizan.

### R4. Volver a cargar las filas rechazadas

- La carga ya hecha sigue como está.
- Para incorporar las filas rechazadas, se vuelve a cargar el mismo archivo con la misma plantilla. Las empresas que ya entraron cuentan como «sin cambios» y las de 7 u 8 dígitos entran como altas.

## 4. Fuera de alcance

- Distinguir si el número es una cédula, un número de BPS u otra cosa.
- Unificar automáticamente una empresa con RUT no verificado con la misma empresa cuando aparezca con su RUT de 12 dígitos. Se hace con la fusión manual existente, o con la bandeja de duplicados de la fase 2 (mismo teléfono, web o dirección).

## 5. Despliegue

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

`api` aplica la migración (cambio de tipo de `empresa.rut` y columna `rut_verificado`) antes de publicar la versión. **No desplegar con una carga en curso.** **Costo: ninguno.**

## 6. Riesgos aceptados

| Riesgo | Mitigación |
|---|---|
| Entran errores de tipeo como empresas, por ejemplo un RUT al que le faltan dígitos | Quedan marcados como «no verificados», se pueden filtrar y el tablero de calidad los cuenta. |
| La misma empresa queda dos veces: con su cédula y con su RUT | Bandeja de duplicados de la fase 2 (mismo teléfono, web o dirección) y fusión manual. |
| Un número de 6 a 11 dígitos de otra persona o empresa coincide por casualidad | Mismo riesgo que con cualquier identificador. Se revisa en la ficha (historia por fuente). |
