# Despliegue: borrar estudios y muestras, y cargas en cualquier estado

Este documento lleva a producción el cambio de [`specs/SPEC_borrado_estudios_muestras_y_cargas_en_curso.md`](../specs/SPEC_borrado_estudios_muestras_y_cargas_en_curso.md) en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**. Para una instalación desde cero alcanza con la [guía de despliegue](despliegue.md): la migración nueva se aplica en el paso 2 como las demás.

**Qué cambia para las personas** (todo es solo para administradores):

- **Borrar muestra**, en el detalle de la muestra, en cualquier estado. Sus empresas vuelven a estar disponibles, salvo las que quedaron en enfriamiento.
- **Borrar estudio**, en el detalle del estudio: partes, muestras, ingestas .sav y sus archivos.
- Lo que el campo dejó en la base **se conserva**: contactos y teléfonos nuevos, calidad de los números, historia y último contacto efectivo.
- **Borrar carga** funciona en cualquier estado, también «analizando» o «en proceso». Si una tarea la está procesando, se cancela sin aplicar nada. El detalle avisa cuando una tarea está **trabada**.
- **Verificar reproducibilidad** ya no da una falsa alarma después de borrar empresas. Puede responder «Reproducible ✓ — N empresas se borraron después del sorteo» o «No verificable», si el borrado se hizo con la versión anterior.

**Tiempo estimado:** 15 minutos. **Costo:** ninguno adicional.

## Paso a paso

Los tres pasos son obligatorios y van en este orden: la API nueva tiene que estar publicada antes de la migración, y la web después de las dos.

```bash
cd ~/base-empresas && git checkout main && git pull
```

```bash
export REGION=us-central1
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh migrar
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Después, en el navegador, recargá la aplicación con **Cmd+Shift+R** para que tome la web nueva. Si se usa IP fija para el CDR, el despliegue de la API va con `IP_FIJA=1`, como siempre.

`migrar` aplica `db/empresas/0008_borrado_estudios_muestras.sql`, que es compatible hacia atrás:

- Agrega el estado `cancelada` a las tareas.
- Crea `muestra_item_borrado`, donde quedan registrados los ítems de muestra que se van con un borrado de empresa o de carga.
- Quita la FK de `marco_snapshot_item.empresa_id`: el marco congelado ya no se toca nunca.
- Agrega índices para que los borrados no recorran tablas enteras.

## Verificación en producción

Marcá cada punto:

- [ ] **Carga trabada:** abrí una carga que esté «analizando» o «en proceso» y tocá **Borrar carga**. El modal dice qué tarea se cancela. Al confirmar con BORRAR, la carga desaparece de la lista.
- [ ] **Verificación con borrados:** sorteá una muestra de prueba en un estudio de prueba, abrí la ficha de una de sus empresas y tocá **Borrar empresa**. En la muestra aparece «1 empresa borrada después del sorteo», y **Verificar reproducibilidad** responde «Reproducible ✓ — 1 empresa se borró después del sorteo».
- [ ] **Borrar muestra:** en esa muestra, **Borrar muestra** (escribiendo BORRAR). La pantalla vuelve al estudio con los conteos.
- [ ] **Borrar estudio:** en el estudio de prueba, **Borrar estudio** (escribiendo su nombre). Desaparece de «Estudios y muestras».
- [ ] **Auditoría:** figuran `empresa.borrar`, `carga.borrar`, `muestra.borrar` y `estudio.borrar`, con quién y los conteos.
- [ ] Con un usuario que no es administrador, los botones de borrar no aparecen.

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| El borrado termina con «… sigue ocupada por una tarea que todavía no terminó de detenerse» | La tarea cancelada tardó más de 2 minutos en soltar la carga, la muestra o el estudio | Esperar unos minutos y volver a borrar |
| «Verificar reproducibilidad» dice «No verificable» | Se borraron empresas de esa muestra con la versión anterior del borrado, que también borraba filas del marco congelado | Es esperado para esas muestras: no se pueden reconstruir. Si hace falta una muestra verificable, sortear una nueva |
| Un botón de borrar no aparece | El usuario no es administrador, o la web vieja quedó en caché | Entrar como administrador; recargar con Cmd+Shift+R |
| Una tarea figura «cancelada» en una carga que ya no existe | Es el registro de la tarea que se canceló al borrar | Nada |

**Volver atrás:** redirigir el tráfico de Cloud Run a la revisión anterior de la API y revertir la web en Firebase Hosting (ver [despliegue.md](despliegue.md), "Actualizaciones"). La migración 0008 puede quedar aplicada. Hay dos detalles: la versión anterior no muestra los ítems borrados en la verificación, y si borra empresas vuelve a quitar filas del marco congelado.
