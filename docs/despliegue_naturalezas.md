# Despliegue: editar y borrar naturalezas jurídicas

Este documento lleva a producción el cambio en **Administración → Naturalezas jurídicas** en el proyecto `equipos-base-empresas`, región **Iowa (`us-central1`)**, desde tu MacBook. La decisión está en [`docs/decisiones.md`](decisiones.md) (D49) y el uso, en el manual (guía 17).

**Qué cambia para las personas** (solo el administrador):

| Acción | Qué hace |
| --- | --- |
| **Editar** | Cambia el nombre y la marca «excluida». El código no se cambia: lo usan la historia de las empresas, la configuración y las muestras. |
| **Borrar** | Aparece solo en las naturalezas que ninguna empresa tiene ni tuvo; las demás dicen «en uso». Si estaba excluida, se crea una versión nueva de la configuración. |
| **+ Naturaleza** | Ya no deja crear un código que existe (antes lo pisaba en silencio). |

**Tiempo estimado:** 10 minutos. **Costo:** ninguno. **Sin migración:** no cambia la base de datos.

## Paso a paso

Se despliegan la API y la web, en este orden:

```bash
cd ~/base-empresas && git checkout main && git pull
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh api
```

```bash
PROYECTO=equipos-base-empresas REGION=us-central1 ./infra/desplegar.sh web
```

Si ya está mergeado el fix de región del script, la variable es `EMPRESAS_REGION=us-central1`. Si se usa IP fija para el CDR, `api` va con `IP_FIJA=1`, como siempre. Después, recargá la aplicación con **Cmd+Shift+R**.

## Verificación

Como administrador, en **Administración → Naturalezas jurídicas**:

1. Cada fila tiene **Editar**. Cambiá el nombre de una naturaleza y guardá: la lista muestra el nombre nuevo y **Auditoría** registra `naturaleza.editar` con el antes y el después.
2. Las naturalezas que tienen empresas dicen **en uso**; las demás tienen **Borrar**. Borrá una que no uses: desaparece de la lista y queda `naturaleza.borrar` en Auditoría.
3. **+ Naturaleza** con un código que ya existe avisa «Ya existe la naturaleza …: editala desde la lista».
4. Con un usuario data steward la pantalla se ve igual que antes, sin botones.

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| No aparecen los botones Editar y Borrar | La web quedó en caché o no se desplegó | Cmd+Shift+R; si sigue, correr `./infra/desplegar.sh web` |
| «Método no permitido» al editar | Se desplegó la web pero no la API | Correr `./infra/desplegar.sh api` |
| «… figura en la historia de N datos de empresas: no se puede borrar» | Alguna empresa tuvo esa naturaleza alguna vez | Es esperado: la historia la sigue usando. Se puede cambiar el nombre |

**Volver atrás:** redirigir el tráfico de Cloud Run a la revisión anterior de la API y revertir la web en Firebase Hosting (ver [despliegue.md](despliegue.md), «Actualizaciones»). No hay nada que deshacer en la base.
