# SPEC — Descubrimiento: qué aporta cada coincidencia

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_descubrimiento_que_aporta.md`, para que Claude Code lo implemente y lo despliegue.
**Base:** `main` en `6b811ee` (PR #26).
**Fecha:** 26/11/2026

---

## 1. Problema

- En el preview de un lote de descubrimiento, cada resultado que **coincide** con una empresa de la base muestra los datos de Google Places y la empresa con la que coincidió (RUT, razón social, regla, similitud). **No muestra qué aportaría «Completar la empresa»**: para saberlo hay que abrir la ficha y comparar a ojo.
- Muchas coincidencias no aportan nada. Por ejemplo, si la coincidencia fue por teléfono, la empresa ya tiene ese teléfono. Sin ver la diferencia, el jefe confirma a ciegas o revisa ficha por ficha.
- Después de confirmar, solo se ven totales («N empresas completadas, M teléfonos nuevos»). El detalle por empresa queda en la historia de cada ficha.

## 2. Objetivos

1. Antes de confirmar, para cada coincidencia se ve, dato por dato, si es **nuevo**, **igual** o **distinto**, y si el distinto reemplazaría al vigente o quedaría solo en la historia.
2. Se puede filtrar el preview para ver solo las coincidencias que aportan algo y omitir el resto con un clic.
3. Después de confirmar, se ve lo mismo por empresa: qué se agregó realmente.

## 3. Fuera de alcance

- Cambiar qué datos se completan. Hoy `confirmar` aplica dirección, sitio, teléfono y los atributos `google_place_id` y `rubro_descubrimiento`; departamento y localidad **no** se aplican al completar.
- Cambiar las reglas de coincidencia (`REGLAS`) o la regla de supervivencia (`empresas.ganador`).
- Editar datos campo por campo desde el preview (P2).

## 4. Historias de usuario

- Como **jefe de campo**, quiero ver qué aporta cada coincidencia antes de confirmar, para no completar empresas que no ganan nada ni pisar datos buenos.
- Como **jefe de campo**, quiero filtrar las coincidencias que no aportan nada y omitirlas juntas, para revisar solo las que importan.
- Como **auditor**, quiero ver después de confirmar qué cambió en cada empresa, sin abrir ficha por ficha.

## 5. Requisitos (P0)

### A1. Cálculo de «qué aporta» en el preview

En `descubrimiento.clasificar`, para cada fila con `caso = "coincide"`, se calcula `aporta`, una lista con un elemento por dato que se aplicaría al completar:

| Dato | Cómo se compara |
|---|---|
| **Teléfono** | El `e164` de Places contra los vínculos de la empresa (`telefono_vinculo`). Estados: `nuevo` (no lo tiene), `igual` (ya lo tiene) o `sin_dato` (Places no trajo teléfono discable). |
| **Sitio** | El dominio normalizado (`proveedores.dominio`) de Places contra el `web` vigente. Estados: `nuevo` (la empresa no tiene), `igual` (mismo dominio) o `distinto`. |
| **Dirección** | El texto de Places contra la `direccion` vigente, con la normalización y la similitud que ya usa la regla `direccion` (umbral 0,85). Estados: `nuevo`, `igual` (similitud ≥ umbral) o `distinto`. |
| **Place ID** | Si la empresa ya tiene `google_place_id`: `igual` o `distinto`. Si no tiene: `nuevo`. |

**Cuando es «distinto»**, se simula la regla de supervivencia con la misma función `empresas.ganador`: se agrega a las filas de historia de ese campo una fila candidata con `fuente_tipo = "descubrimiento"`, la confianza configurada (`cfg["confianza"]`) y la fecha actual, y se ve si gana. El estado pasa a ser:
- `reemplaza`: el valor de Places pasaría a ser el vigente;
- `solo_historia`: el vigente se mantiene (por ejemplo, porque viene de la sala o tiene más confianza) y el de Places queda solo en la historia.

**Resumen por fila:**
- `aporta_algo = true` si hay al menos un `nuevo` o un `reemplaza`.
- La acción sugerida por defecto pasa a ser **«No guardar»** cuando `aporta_algo = false`, aunque la regla sea exacta. Hoy se marca «Completar» si la regla es `fusionar`.

**Rendimiento:** los datos de las empresas coincidentes (vínculos, vigentes y place_id) se precargan en una sola consulta por lote, no una por fila. Un lote tiene como máximo unas 60 filas (3 páginas de 20).

### A2. Pantalla del preview

- **Columna nueva «Qué aporta»** entre «En la base» y «Qué hacer», solo en las filas «coincide». Un chip por dato:
  - verde **«Teléfono nuevo»**, **«Sitio nuevo»**, **«Dirección nueva»**;
  - naranja **«Sitio distinto: reemplaza»**, **«Dirección distinta: reemplaza»**, con el valor actual al pasar el mouse;
  - gris **«Dirección distinta: solo historia»**, con el motivo al pasar el mouse (por ejemplo, «el vigente viene de la sala»);
  - texto tenue **«ya lo tiene»** para los iguales;
  - si no aporta nada: **«No aporta nada»**.
- **Resumen arriba:** a las tarjetas actuales (nuevas, coinciden, ya guardadas) se agrega **«coinciden y aportan»**.
- **Filtro** sobre la tabla: Todas · Nuevas · Coinciden y aportan · Coinciden sin aporte · Ya guardadas.
- **Botón «Omitir las que no aportan»:** pone «No guardar» en todas las coincidencias con `aporta_algo = false`.
- En las coincidencias por regla **flexible** (nombre o dirección con similitud), se mantiene el aviso «revisá». La columna «Qué aporta» se muestra igual, porque ayuda a decidir si es la misma empresa.

### A3. Detalle después de confirmar

- `confirmar` guarda, por cada fila completada, lo que **realmente** pasó: teléfono vinculado nuevo o ya existente (el `nuevo` que devuelve `empresas.vincular`), y por cada campo de `aplicar_valores` si cambió el vigente o quedó como conflicto (los `cambios` y `conflictos` que ya devuelve).
- Se guarda en `resultado.confirmado.detalle` del lote: `[{i, empresa_id, telefono: "nuevo"|"ya_tenia"|null, web: "reemplazo"|"nuevo"|"historia"|"igual"|null, direccion: …}]`.
- En el lote confirmado, la columna «Qué aporta» pasa a llamarse **«Qué se agregó»** y muestra este resultado real.
- El aviso «Confirmado: …» agrega: «K empresas completadas sin cambios».

### Criterios de aceptación

- [ ] Una coincidencia por teléfono, contra una empresa que ya tiene ese teléfono, el mismo sitio y una dirección similar, muestra «No aporta nada» y queda en «No guardar» por defecto.
- [ ] Una coincidencia contra una empresa sin sitio muestra «Sitio nuevo» y queda en «Completar» por defecto.
- [ ] Si la dirección vigente viene de la sala, una dirección distinta de Places muestra «solo historia». Al confirmar, la vigente no cambia, y «Qué se agregó» dice «historia».
- [ ] Si la dirección vigente viene de una carga y la de Places gana por confianza o fecha, el preview muestra «reemplaza» y, después de confirmar, la ficha tiene la dirección de Places como vigente.
- [ ] «Omitir las que no aportan» cambia solo esas filas.
- [ ] La simulación del preview coincide con lo que pasa al confirmar en todos los casos del test (comparando `aporta` con `confirmado.detalle`).
- [ ] Un preview de 60 filas hace como máximo 5 consultas extra para calcular «Qué aporta».
- [ ] Los lotes viejos (sin `aporta`) se siguen viendo; la columna muestra «—».

## 6. Requisitos P1

- **Exportar el preview a CSV** con las columnas de Places, la empresa de la base y «Qué aporta», para revisarlo fuera de la aplicación.
- **En la ficha de la empresa,** el teléfono, sitio o dirección que vino de un descubrimiento muestra el enlace al lote.

## 7. Consideraciones futuras (P2)

- Elegir dato por dato qué completar (por ejemplo, el teléfono sí, la dirección no).
- Aplicar también departamento y localidad al completar, con la misma simulación.
- Usar la misma columna «Qué aporta» en el enriquecimiento, donde hoy solo se ve «con teléfono nuevo».

## 8. Despliegue

```bash
cd ~/base-empresas && git checkout main && git pull
export REGION=us-central1
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

No hay migraciones: todo va en el JSON `resultado` del lote. No desplegar con un lote de descubrimiento en «preview» que se quiera confirmar. Si lo hay, se confirma o se descarta antes, o se vuelve a buscar después del despliegue (cuesta otra vez las llamadas a Places).

## 9. Costo

**Ninguno adicional.** No hay llamadas nuevas a Google Places ni a otros proveedores: se compara con datos que ya están en la base.
