# SPEC — Una muestra cerrada aparece como «empresa cerrada»

**Sistema:** Base de Empresas (repo `araujomelogno/base-empresas`, región **us-central1**)
**Destino:** `specs/SPEC_etiqueta_estado_muestra_cerrada.md`, para que Claude Code lo implemente y lo despliegue.
**Base:** `main` en `f71ab7c`. **Tamaño:** corrección chica, solo en la web.
**Fecha:** 12/11/2026

## 1. Problema

En la ficha de la empresa, la pestaña **Muestras** muestra el estado de cada muestra. Cuando una muestra está cerrada, dice **«empresa cerrada»** y debería decir **«muestra cerrada»**. Pasa lo mismo en otros dos lugares:

- la lista de muestras del detalle del estudio (`web/public/js/vistas/estudios.js`, columna Estado);
- la cabecera del detalle de la muestra (`estudios.js`, `pageHeader` de la muestra).

**Causa:** la función `est()` (`web/public/js/ui.js`) traduce cada estado con un único diccionario global de etiquetas. Ese diccionario tiene `cerrada: 'empresa cerrada'`, pensado para el estado de la **empresa** (`activa | cerrada | desconocida`). Pero la muestra usa el mismo valor `cerrada` en su estado (`borrador | activa | cerrada`), y entonces hereda la etiqueta de la empresa. Puede pasar lo mismo con cualquier otro valor que compartan dos entidades, por ejemplo `activa`.

## 2. Requisitos (P0)

1. **Etiquetas por contexto:** `est()` (o una variante) recibe el **tipo de objeto** y usa la etiqueta de ese tipo, si existe:
   - **muestra:** `borrador` → «borrador», `activa` → «muestra activa», `cerrada` → «muestra cerrada»;
   - **empresa:** `activa` → «activa», `cerrada` → «empresa cerrada», `desconocida` → «desconocida» (como hoy).

   Si no hay etiqueta para ese tipo, usa la global.
2. **Usar el contexto de muestra** en todos los lugares donde se muestra el estado de una muestra:
   - pestaña Muestras de la ficha (`web/public/js/vistas/base.js`);
   - lista de muestras del estudio (`estudios.js`);
   - cabecera del detalle de la muestra (`estudios.js`);
   - selectores o filtros que muestren el estado de la muestra, si los hay.
3. **Revisar los otros estados con valores compartidos.** Buscar en el diccionario global los valores que se usan para más de una entidad (por ejemplo `activa`, `error`, `confirmada`, `deshecha`) y darles una etiqueta por contexto donde la global no corresponda. Dejar la lista de lo revisado en el PR.
4. **El color del estado no cambia:** la clase CSS sigue siendo `est-<estado>`.

## 3. Criterios de aceptación

- [ ] Ficha de una empresa con una muestra cerrada: la columna Estado dice «muestra cerrada».
- [ ] Ficha de una empresa con estado cerrada: la cabecera y la pestaña Datos siguen diciendo «empresa cerrada».
- [ ] Detalle de estudio y detalle de muestra cerrada: dicen «muestra cerrada».
- [ ] Ningún otro estado de la aplicación cambia de texto, salvo los que se corrijan en el punto 3 y figuren en el PR.

## 4. Fuera de alcance

Cambiar los valores guardados en la base: solo cambian los textos de la web.

## 5. Despliegue y costo

Solo web:

```bash
cd ~/base-empresas && git checkout main && git pull
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Recargar con Cmd+Shift+R. **Costo: ninguno.**
