# Despliegue: alta de usuarios con enlace de acceso

Este documento lleva a producción el cambio de [`specs/SPEC_alta_usuarios_enlace_acceso.md`](../specs/SPEC_alta_usuarios_enlace_acceso.md) sobre una instalación que ya existe (proyecto `equipos-base-empresas`). Para una instalación desde cero alcanza con la [guía de despliegue](despliegue.md), que ya incluye estos pasos.

**Qué cambia para las personas:**

- El administrador da de alta a alguien solo desde la pantalla **Usuarios** (email, nombre, rol). Ya no se crea nada en la consola de Firebase.
- La persona recibe un correo de `notificaciones@equipos.com.uy` con un enlace para crear su contraseña.
- El login muestra siempre por qué no se pudo entrar: no estás dado de alta, acceso desactivado, clave incorrecta o error de conexión.

**Tiempo estimado:** 20 a 30 minutos, más la espera del correo. La web y la API quedan sin servicio solo los segundos del despliegue de Cloud Run.

## Antes de empezar

| Qué | Dónde | Quién |
| --- | --- | --- |
| Acceso a la cuenta de Google de `notificaciones@equipos.com.uy`, con verificación en dos pasos activa | Workspace | Operaciones |
| Permisos de Owner en el proyecto `equipos-base-empresas` | Google Cloud | Quien despliega |
| La Mac preparada (`gcloud`, `firebase`, repositorio al día) | Ver [despliegue.md](despliegue.md), "Preparar la Mac" | Quien despliega |
| SPF, DKIM y DMARC de `equipos.com.uy` configurados (los usa `paneles`) | Consola de Workspace | Operaciones (si no están, los correos pueden caer en spam) |

Traé el repositorio al día:

```bash
cd ~/base-empresas && git pull
```

## Paso 1 — Contraseña de aplicación exclusiva

1. Entrar a la cuenta de Google de `notificaciones@equipos.com.uy` → **Seguridad** → **Contraseñas de aplicaciones**.
2. Crear una nueva con el nombre **Base de Empresas** y copiarla. Debe ser una contraseña **nueva y exclusiva** de este proyecto, para poder revocarla sin afectar a `paneles` ni a `plataforma-informes-ec`.
3. Guardarla en Secret Manager (los espacios entre los grupos de letras no importan):

```bash
printf '%s' 'CONTRASEÑA-DE-APLICACION' | gcloud secrets create empresas-smtp-password --project equipos-base-empresas --data-file=-
```

Si se saltea este paso, el script del paso 2 la pide por la terminal sin mostrarla.

## Paso 2 — Permisos, API, migración y web

El rol nuevo de la cuenta de servicio (**Firebase Authentication Admin**, para crear cuentas, deshabilitarlas y generar enlaces) lo agrega el subcomando `base`; los demás pasos ya existían:

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh base
```

```bash
PROYECTO=equipos-base-empresas ADMIN_EMAILS=garaujo@equipos.com.uy ./infra/desplegar.sh api
```

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh migrar
```

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh web
```

- `api` despliega la API con `SMTP_PASSWORD` (desde el secreto), `SMTP_USUARIO`, `SMTP_HOST`, `SMTP_PORT` y `APP_URL` (`https://equipos-base-empresas.web.app` por defecto; si se usa un dominio propio, pasarlo como `APP_URL=https://...` y agregarlo en Firebase → Authentication → Configuración → Dominios autorizados).
- `migrar` aplica `db/empresas/0004_alta_con_enlace.sql`: agrega a `usuario` las columnas del último reenvío y crea la tabla `correo_envio`. Es compatible hacia atrás.
- `web` publica el login corregido y la pantalla Usuarios nueva.

## Paso 3 — Administrador inicial

La cuenta del administrador inicial se creó a mano en la consola antes de este cambio, así que hay que mandarle un enlace nuevo. La cuenta queda verificada y no se crea otra:

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh invitar
```

Salida esperada:

```
▶ Administradores iniciales: enlace de acceso
  garaujo@equipos.com.uy: reenviado · correo enviado
```

Si dice `correo NO enviado`, el motivo aparece al lado y el script imprime el enlace **una sola vez**: abrilo en el navegador (vence en una hora). Revisá la contraseña de aplicación (paso 1) antes de seguir.

Con el enlace, elegí la contraseña y entrá a la web.

## Paso 4 — Usuarios que ya estaban registrados

Las personas que ya estaban en la pantalla **Usuarios** pueden no tener cuenta en Firebase, o tenerla sin verificar. Para cada una, en **Usuarios** → **Reenviar acceso**: si no tenía cuenta, se crea; si la tenía, queda verificada; y le llega el correo.

## Paso 5 — Verificación

Es la definición de terminado del spec. Marcar cada punto:

- [ ] El administrador inicial recibió el enlace, fijó su clave y entró.
- [ ] Desde **Usuarios** dio de alta a un segundo usuario de prueba. A ese usuario le llegó el correo de bienvenida, fijó su clave con el enlace y entró.
- [ ] La columna **Correo de acceso** de ese usuario dice "enviado" y **Último ingreso** muestra la fecha.
- [ ] Al desactivar al usuario de prueba, ya no puede entrar y ve "Tu acceso está desactivado". Al reactivarlo, puede volver a entrar.
- [ ] Con un email que no está en **Usuarios**, el login muestra "no tiene acceso a la Base de Empresas".
- [ ] **Prueba de correo fallido** (opcional, con cuidado): cargar una versión inválida del secreto, redesplegar la API y dar de alta a otro usuario de prueba. El alta termina bien, la pantalla muestra el motivo y el enlace una sola vez. Después volver a la versión buena y redesplegar:

```bash
printf '%s' 'invalida' | gcloud secrets versions add empresas-smtp-password --project equipos-base-empresas --data-file=-
```

```bash
PROYECTO=equipos-base-empresas ./infra/desplegar.sh api
```

Para volver a la buena, agregar de nuevo la contraseña correcta como versión nueva (o deshabilitar la versión inválida en Secret Manager) y repetir `./infra/desplegar.sh api`.

## Paso 6 — Cerrar el registro público

Con todo verificado, en la consola de Firebase → **Authentication** → **Configuración** (*Settings*) → **Acciones del usuario** (*User actions*), desmarcar la creación de cuentas (*Enable create (sign-up)*). Así solo la API puede crear cuentas. La opción aparece en los proyectos con Firebase Authentication with Identity Platform; si no aparece, no es necesaria: la web no ofrece registrarse y la API rechaza a quien no está en **Usuarios**.

## Si algo sale mal

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| El alta responde "No se pudo conectar con Firebase Authentication" o "Firebase no generó el enlace" | Falta el rol Firebase Authentication Admin en la cuenta de servicio | `./infra/desplegar.sh base` y reintentar |
| Correo "fallido: Workspace rechazó la credencial" | Contraseña de aplicación mal copiada, revocada o de otra cuenta | Crear una nueva (paso 1), cargarla como versión nueva del secreto y `./infra/desplegar.sh api` |
| El enlace del correo da error de dominio no autorizado | `APP_URL` no está en los dominios autorizados de Firebase | Agregarlo en Authentication → Configuración → Dominios autorizados |
| `./infra/desplegar.sh invitar` responde 401 | El token del job no coincide con el de la API | Redesplegar la API (`./infra/desplegar.sh api`) para que tome el secreto vigente |
| `invitar` responde "ADMIN_EMAILS está vacía" | La API se desplegó sin administradores iniciales | `ADMIN_EMAILS=... ./infra/desplegar.sh api` |
| Los correos llegan a spam | SPF, DKIM o DMARC de `equipos.com.uy` | Revisarlos en la consola de Workspace |

**Volver atrás:** el cambio es compatible hacia atrás. Para volver a la versión anterior, redirigir el tráfico de Cloud Run a la revisión previa y revertir la web en Firebase Hosting (ver [despliegue.md](despliegue.md), "Actualizaciones"). La migración 0004 puede quedar aplicada: la versión anterior ignora la tabla y las columnas nuevas.

## Costos

Sin costo recurrente adicional: Firebase Authentication con decenas de usuarios internos es gratis, el secreto nuevo entra en el tramo gratuito de Secret Manager y el SMTP de Workspace está incluido en la licencia de `notificaciones@`. Límite a tener en cuenta: 2.000 destinatarios por día por cuenta de Workspace, compartidos con `paneles` y `plataforma-informes-ec`.
