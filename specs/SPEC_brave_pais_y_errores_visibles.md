# SPEC — Brave Search: país no admitido, errores visibles y búsqueda web con Claude como último paso

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_brave_pais_y_errores_visibles.md`, para que Claude Code lo implemente y lo despliegue.
**Base:** `main` en `6b811ee` (PR #26).
**Fecha:** 26/11/2026

---

## 1. Problema

- En la corrida de enriquecimiento #2 (1 empresa, «4 Cabezas SAS»), el paso **Brave Search** terminó en **error**. Places dio «sin resultado».
- La clave de Brave funciona: una llamada desde la terminal **sin** `country` ni `search_lang` devolvió resultados. Además, si la clave fuera inválida, el proveedor habría quedado apagado («rechazó la clave»).
- **Causa confirmada (26/11/2026):** `proveedores.brave_buscar` manda `country=uy`, y Brave responde **HTTP 422**, `code: VALIDATION`, `loc: ["query","country"]`: «Input should be 'AR', 'AU', 'AT', 'BE', 'BR', 'CA', 'CL', 'DK', 'FI', 'FR', 'DE', 'GR', 'HK', 'IN', 'ID', 'IT', 'JP', 'KR', 'MY', 'MX', 'NL', 'NZ', 'NO', 'CN', 'PL', 'PT', 'PH', 'RU', 'SA', 'ZA', 'ES', 'SE', 'CH', 'TW', 'TR', 'GB', 'US' or 'ALL'». Uruguay no está en la lista.
- La pantalla de la corrida muestra «error» pero **no el motivo**: queda guardado en `enriquecimiento_paso.detalle->>'error'` y solo se ve con SQL.
- **Claude solo se usa si hay un sitio.** Hoy Claude solo lee el sitio que encontraron Places o Brave. Si ninguno de los dos encontró nada, la empresa termina «sin resultado» y no hay otro intento. Claude no puede contestar «de memoria» un teléfono, porque inventaría números; necesita buscar en la web.

## 2. Objetivos

1. Brave Search no devuelve error por los parámetros que manda la aplicación.
2. El motivo de cualquier error de un proveedor se ve en la pantalla, sin SQL.
3. Las empresas en las que Places y Brave no encontraron nada tienen un último intento: Claude con búsqueda web. Solo se aceptan los teléfonos cuya fuente se pudo verificar.

## 3. Fuera de alcance

- Cambiar la regla de sitio oficial o el orden de los pasos 1 a 4 actuales.
- Cambiar de proveedor de búsqueda.
- Usar Claude **sin** búsqueda web para conseguir datos de contacto.
- Usar Brave o Claude en el **descubrimiento** de empresas nuevas (sección 7, P2).

## 4. Requisitos (P0)

### B1. Parámetros de Brave

- En `brave_buscar`, `country` pasa de `uy` a **`ALL`**. Si no se manda, Brave usa `US` por defecto, así que se manda explícitamente. La consulta ya incluye «Uruguay» y la localidad.
- `search_lang=es` se mantiene solo si está en la lista de valores admitidos de la API de Brave. Si no está, se saca.
- Se agrega `ui_lang=es-UY` solo si Brave lo admite (lista de la API). Si no, no se agrega.
- Los valores quedan como constantes en `proveedores.py`, con un comentario con el enlace a la referencia de la API, para no volver a adivinarlos.

### B2. Diagnóstico del error

- Si Brave responde 4xx, el `ProveedorError` incluye el `detail` del cuerpo de la respuesta (el JSON de error de Brave, recortado a 300 caracteres). Ejemplo: «Brave Search respondió 422: country: Input should be …».
- Lo mismo para Places y Claude: el mensaje de error incluye el detalle que devuelve el proveedor, sin la clave.
- Si Brave responde **429** (límite de pedidos por segundo del plan), se reintenta **una vez** después de 1,1 segundos y no se cobra el reintento fallido. Si vuelve a dar 429, el paso queda en error con ese motivo.

### B3. Motivo visible en la pantalla de la corrida

- En la tabla **Pasos**, cuando hay errores, cada fila de proveedor muestra debajo el motivo más frecuente (por ejemplo, «422: country …» × 1).
- En la lista **Empresas**, el chip «error» de cada empresa muestra el motivo al pasar el mouse (`title`).
- `detalle` de la corrida en la API (`enriquecimiento.detalle`) devuelve, por proveedor, los motivos de error agrupados con su cantidad.

### B4. Paso 5: búsqueda web con Claude (último recurso)

**Cuándo se ejecuta.** Al final de la cascada, solo si:
- la empresa **sigue sin teléfono discable** después de los pasos 1 a 4;
- el paso 4 (lectura del sitio + Claude) **no se ejecutó** porque no había sitio, o se ejecutó y no encontró nada;
- el proveedor nuevo `claude_web` está **activo** y quedan fondos en el tope de la corrida.

**Cómo funciona.**
- Llamada a la API de Anthropic con la **herramienta de búsqueda web del servidor** (`web_search`), con el modelo configurado (`modelo_claude`) y un máximo de **3 búsquedas por empresa** (`max_uses`, configurable). Si la API lo admite, se limita la ubicación de usuario a Uruguay (`user_location.country = "UY"`).
- Las instrucciones le dan la razón social, el nombre de fantasía, el RUT, la localidad y el departamento, y le piden devolver un JSON con: `telefonos` (cada uno con la `url` de la página donde aparece), `web`, `email` institucional, `direccion` y `confianza` (de 0 a 1). También le piden que devuelva vacío si no encuentra una fuente que corresponda claramente a **esa** empresa, y que nunca devuelva nombres ni datos personales (misma regla que el paso 4).

**Verificación obligatoria (contra números inventados).**
- Por cada teléfono, la aplicación baja la `url` citada con el mismo lector del paso 4 (`leer_sitio` o una lectura de página única) y comprueba que el número, normalizado, **aparece en esa página**. Si no aparece, la página no responde o la URL no se citó, el teléfono se **descarta** y queda registrado como «no verificado» en el detalle del paso.
- Se descartan las URLs de directorios configurados (`cfg["directorios"]`) si el número no aparece junto al nombre de la empresa en la página.
- Solo entran los teléfonos verificados con `confianza ≥ 0,5`.

**Origen y trazabilidad.**
- Los teléfonos que entran tienen el origen **«Búsqueda web (Claude)»**, con la URL de la fuente, separado de «web» (paso 4) y de «google_places». Así se puede medir su tasa de contacto en el rendimiento por origen.
- El paso queda en `enriquecimiento_paso` con proveedor `claude_web`, la cantidad de búsquedas, los tokens, el costo, los teléfonos propuestos y verificados y las URLs.
- Se puede deshacer como cualquier otro resultado de la corrida.

**Costo y topes.**
- Configuración → Enriquecimiento agrega: interruptor «Búsqueda web con Claude» (**desactivado por defecto**), «búsquedas máximas por empresa» (por defecto 3) y «precio por búsqueda» (por defecto **US$0,01**, es decir, US$10 cada 1.000). Los tokens se cobran con los precios de Claude ya configurados.
- Antes de llamar se reserva el costo máximo de la empresa: `max_uses × precio_busqueda + tokens estimados` (por defecto 30.000 de entrada y 2.000 de salida). Si no alcanza el tope, se detiene como hoy («por el tope»).
- El **estimado previo a la aprobación** suma este paso para la fracción de empresas que se espera que lleguen a él (por defecto, 1 − tasa de éxito de Places), y lo muestra por separado: «Búsqueda web (Claude): hasta US$X».
- Se usa la misma clave de Anthropic (`empresas-anthropic-key`). No hacen falta claves nuevas.

**Pantalla.**
- En «Pasos», la fila «Búsqueda web (Claude)» muestra cantidad, resultado, costo y cuántos teléfonos se propusieron y cuántos se verificaron.
- En la ficha de la empresa, el teléfono muestra el origen y el enlace a la página fuente.

### Criterios de aceptación

**B1 a B3**
- [ ] Con la clave actual, enriquecer «4 Cabezas SAS» deja el paso Brave en «ok» o «sin resultado», nunca en «error» por parámetros.
- [ ] Un test con una respuesta 422 simulada guarda y muestra el detalle del error.
- [ ] Un test con 429 y después 200 da «ok» con un solo cobro.
- [ ] Ningún mensaje de error ni registro contiene la clave del proveedor.

**B4**
- [ ] Con `claude_web` desactivado, la cascada se comporta exactamente como hoy (test de no regresión).
- [ ] Una empresa en la que Places y Brave no encuentran nada pasa por el paso 5. Una que consiguió teléfono en los pasos 2 a 4 **no** pasa.
- [ ] Test con una respuesta simulada que trae un teléfono cuya URL **no** contiene el número: el teléfono se descarta y el paso queda «sin resultado» con «1 no verificado».
- [ ] Test con un teléfono cuya URL sí lo contiene: entra con origen «Búsqueda web (Claude)» y la URL.
- [ ] El costo cobrado es búsquedas usadas × precio + tokens reales, y nunca supera la reserva.
- [ ] Al alcanzar el tope, la corrida se detiene antes de llamar y lo conseguido queda guardado.
- [ ] Deshacer la corrida saca los teléfonos de este origen.
- [ ] Ningún test hace llamadas pagas (proveedor simulado, como los demás).

## 5. Despliegue

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Si hace falta registrar el origen nuevo o el proveedor `claude_web` en un catálogo, va en una migración que `api` aplica antes de publicar. No desplegar con una corrida de enriquecimiento en curso.

**Después de desplegar:**
1. Enriquecer «4 Cabezas SAS» con `claude_web` desactivado y verificar que Brave ya no da error.
2. Correr una muestra de 50 a 100 empresas sin el paso 5 y mirar el porcentaje «sin resultado».
3. Activar «Búsqueda web con Claude» y repetirlo solo sobre las que quedaron sin resultado. Comparar cuántas consiguen teléfono verificado y a qué costo.

## 6. Costo

- **B1 a B3: ninguno adicional.** El reintento por 429 se hace una sola vez y solo se cobra si responde bien (unos US$0,005 por búsqueda, como cualquier otra).
- **B4: solo si se activa, y solo para las empresas que llegan al paso 5.**
  - Búsquedas: US$0,01 cada una, con un máximo de 3 por empresa, o sea hasta US$0,03.
  - Tokens: los resultados de búsqueda entran como tokens de entrada, entre 10.000 y 30.000 por empresa. Con Haiku son unos US$0,01 a 0,03; depende del precio cargado en Configuración.
  - **Total: unos US$0,03 a 0,06 por empresa** que llega a este paso. Por ejemplo, si 1.000 empresas de una muestra quedan sin resultado después de Places y Brave, el paso 5 cuesta unos **US$30 a 60**. Se controla con el tope de la corrida y el estimado previo.

## 7. Consideraciones futuras (P2): Brave y Claude en el descubrimiento

Hoy el descubrimiento («imprentas en Salto») usa solo Google Places, porque devuelve fichas de negocio estructuradas: nombre, teléfono, dirección, sitio y `place_id` para no repetir. Brave devuelve páginas web sueltas (directorios, notas, listados) y no empresas, así que harían falta Claude para extraer las empresas de cada página, verificación de cada dato y deduplicación más difícil. Sale más caro por empresa nueva y con más ruido.

Si después se ve que Places no cubre bien algún rubro (empresas sin ficha en Google Maps), se puede agregar un modo «Descubrimiento en la web» con Claude y búsqueda web, que use las mismas reglas de verificación por URL que B4. Va en una spec aparte, después de medir B4.
