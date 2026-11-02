# SPEC — Alta de usuarios con enlace de acceso

**Sistema:** Base de Empresas · Equipos Consultores (`araujomelogno/base-empresas`)
**Corrige:** el alta en dos pasos (consola de Firebase + pantalla Usuarios), el email sin verificar de las cuentas creadas a mano, y un bug del login que oculta el error de la API
**Referencia:** `araujomelogno/plataforma-informes-ec` (`functions/portal/accesos.py`, `correo.py`, `plantillas.py` y su spec «Alta de usuarios con enlace de acceso y notificaciones por correo»), que a su vez porta `paneles`
**Estado:** Para desarrollo
**Última actualización:** 2026-11-02

---

## 1. Problem Statement

Hoy, para que una persona entre a la Base de Empresas hay que darla de alta **dos veces con el mismo email**: una cuenta en la consola de Firebase Authentication y un registro con su rol en la pantalla Usuarios. Si falta uno o hay un error de tipeo, la persona queda afuera. Además, las cuentas creadas a mano en la consola quedan con el email sin verificar y la API las rechaza ("El usuario no tiene email verificado").

Encima, el error no se ve. Cuando `/me` falla, `entrar()` (en `web/public/js/app.js`) muestra el error y enseguida cierra la sesión de Firebase. Eso dispara `onAuthStateChanged(null)`, que vuelve a dibujar el login **sin** el mensaje. Para el usuario, el botón "Ingresar" no hace nada. Pasó en el primer despliegue: el administrador inicial no pudo entrar y no había ningún mensaje.

`plataforma-informes-ec` ya resolvió el alta: el admin escribe solo el email, el sistema crea la cuenta con una clave aleatoria que nadie conoce y le manda a la persona un enlace para fijar la suya, desde `notificaciones@equipos.com.uy`. Este spec trae ese mismo modelo a la Base de Empresas.

## 2. Goals

1. **El alta es un solo paso:** el administrador escribe email, nombre y rol en la pantalla Usuarios. Nadie entra a la consola de Firebase, tampoco para el administrador inicial.
2. **Nadie conoce la contraseña de otro:** el 100% de las cuentas se crean con clave aleatoria; cada persona fija la suya desde el enlace.
3. **La persona entra sola:** al menos 90% de los usuarios nuevos fija su clave e ingresa dentro de los 7 días del alta, sin intervención.
4. **Un fallo de correo no rompe el alta:** si el SMTP falla, la cuenta queda creada y el administrador ve el motivo y el enlace para pasarlo por otro canal.
5. **Ningún error de ingreso queda oculto:** todo rechazo de la API se ve en el login con un mensaje que dice qué pasó.

## 3. Non-Goals

- **Ingreso con Google u otros proveedores.** Se mantiene email y contraseña, como en `plataforma-informes-ec` y `paneles`.
- **Plantillas de correo editables desde la aplicación.** Los usuarios son internos y pocos; los textos quedan fijos en el código en P0 (pasan a P1).
- **Avisos por correo de otros eventos** (muestra sorteada, ingesta terminada, etc.). Es otra iniciativa.
- **Proveedor transaccional de correo** (SendGrid, Mailgun). El volumen no lo justifica; se usa la cuenta de Workspace que ya se paga.
- **Invitaciones que duren días.** Se usa el enlace de Firebase (vence a la hora) más "Reenviar acceso". Una invitación propia exige tokens propios y suma trabajo.
- **Cambios en el modo dev, el job del CDR o los tokens de servicio.**

## 4. User Stories

**Administrador**

- Como administrador, quiero dar de alta a una persona escribiendo solo su email, nombre y rol, para no tener que crear nada en la consola de Firebase ni inventar una contraseña.
- Como administrador, quiero ver si el correo de acceso salió o falló, y por qué, para saber si tengo que pasarle el enlace por otro canal.
- Como administrador, quiero copiar el enlace una sola vez cuando el correo falló, para no dejar a la persona sin entrada.
- Como administrador, quiero reenviar el acceso a quien perdió o dejó vencer el enlace, para destrabarlo sin borrarlo y volverlo a crear.
- Como administrador, quiero que al desactivar a alguien en Usuarios no pueda entrar más, y que al reactivarlo pueda, para manejar altas y bajas desde un solo lugar.
- Como administrador inicial, quiero recibir mi enlace de acceso al terminar el despliegue, para entrar al sistema recién instalado sin pasos manuales.

**Usuario**

- Como usuario nuevo, quiero recibir un correo de Equipos con un enlace para crear mi contraseña, para entrar sin depender de que alguien me la dicte.
- Como usuario cuyo enlace venció, quiero que el correo y el login me digan cómo pedir otro, para no quedar trabado.
- Como usuario que no puede entrar, quiero ver en pantalla por qué (clave incorrecta, no estoy dado de alta, estoy inactivo), para saber qué hacer o a quién pedirle.

## 5. Requirements

### P0 — Must-Have

#### R1 — Mostrar siempre el error de ingreso (bug)

- [ ] **Dado** que el inicio de sesión en Firebase funcionó y `/me` responde con error, **cuando** la web cierra la sesión, **entonces** el login se vuelve a dibujar **con** el mensaje, no sin él.
- [ ] Se muestran con su mensaje los 403 ("no tiene acceso a la Base de Empresas"), los 401 ("Token inválido", "email no verificado") y los errores de red.
- [ ] El mensaje se limpia al iniciar un nuevo intento.
- [ ] Implementación sugerida: guardar el último error en el estado (por ejemplo `S.ultimoError`) antes del `signOut` y leerlo en el `renderLogin()` que dispara `onAuthStateChanged(null)`.
- [ ] Se puede desplegar solo y antes que el resto.

#### R2 — Alta con enlace de acceso

`POST /usuarios` (`api/app/routers/admin.py`, `guardar_usuario`) pasa a hacer, en el servidor:

- [ ] **Dado** un email sin cuenta en Firebase Authentication, **cuando** el administrador lo da de alta, **entonces** la API crea la cuenta con una clave aleatoria (`secrets.token_urlsafe`), que no se guarda, no se devuelve y no se loguea; crea el registro en `usuario` con su rol; genera el enlace con `auth.generate_password_reset_link(email, ActionCodeSettings(url=<URL de la web>))` y manda la plantilla "Bienvenida".
- [ ] La cuenta se crea con `email_verified=True`. Justificación: nadie conoce la clave aleatoria, así que la única forma de entrar es el enlace que llega a ese buzón, lo que prueba que la persona es dueña del email. Esto difiere de `plataforma-informes-ec` porque la API de la Base de Empresas exige email verificado.
- [ ] **Dado** un email que ya tiene cuenta en Firebase (por ejemplo, creada antes a mano en la consola), **entonces** no se crea otra ni se toca su clave: se crea o actualiza el registro en `usuario`, se marca la cuenta como verificada y la respuesta dice "La cuenta ya existía; usá «Reenviar acceso» si necesita entrar".
- [ ] Editar el nombre, el rol o el permiso de exportar contactos de un usuario existente no manda correo.
- [ ] Respuesta: `{email, estado: "creado" | "ya_existia" | "actualizado", correo: {enviado, detalle}, enlace?}`. El `enlace` solo vuelve si el correo no salió.
- [ ] Todo queda en auditoría como hoy (`usuario.guardar`), sin el enlace.

#### R3 — El correo es una comodidad, no un punto de falla

- [ ] Si el SMTP falla, la cuenta y el registro quedan creados. La pantalla muestra el motivo (por ejemplo, "Workspace rechazó la credencial") y el enlace en un modal "se muestra una sola vez" con botón Copiar.
- [ ] El enlace no se guarda en la base, en la auditoría ni en los logs.
- [ ] Los mensajes de error nunca incluyen la contraseña SMTP.

#### R4 — Reenviar acceso

- [ ] En la tabla de Usuarios, cada fila tiene "Reenviar acceso" (`POST /usuarios/{email}/reenviar-acceso`, solo admin).
- [ ] Genera un enlace nuevo y manda "Bienvenida" si la persona nunca ingresó o "Restablecer" si ya ingresó (mismo criterio que `_nunca_ingreso` en `plataforma-informes-ec`).
- [ ] Si la cuenta de Firebase no existe (usuario registrado antes de este cambio), la crea como en R2.
- [ ] Marca la cuenta como verificada si no lo estaba.
- [ ] Queda registrado quién lo pidió y cuándo (`usuario.ultimo_reenvio_por`, `usuario.ultimo_reenvio_en`, `usuario.reenvios`), y en auditoría como `usuario.reenviar_acceso`.
- [ ] Si el correo falla, mismo comportamiento que R3.

#### R5 — Activar y desactivar

- [ ] Desactivar un usuario en la pantalla Usuarios deshabilita también su cuenta de Firebase (`disabled=True`); reactivarlo la habilita.
- [ ] Un usuario desactivado ve en el login "Tu acceso está desactivado. Pedile a un administrador que lo reactive."
- [ ] Se mantiene la regla actual: un administrador no puede desactivarse ni quitarse el rol a sí mismo.

#### R6 — Administrador inicial sin pasos manuales

- [ ] `infra/desplegar.sh todo` (y un nuevo subcomando `infra/desplegar.sh invitar`) termina creando la cuenta de Firebase de cada email de `ADMIN_EMAILS` y mandándole su enlace de acceso, reusando la misma lógica de R2.
- [ ] Si el correo falla, el script imprime el enlace en la terminal una sola vez.
- [ ] Si la cuenta ya existe, no la toca y avisa cómo pedir otro enlace (`./infra/desplegar.sh invitar` o "¿Olvidaste tu contraseña?").
- [ ] El alta automática como administrador en el primer ingreso (`auth.py`) se mantiene.

#### R7 — Envío por Workspace

- [ ] Nuevo módulo `api/app/correo.py`, portado de `plataforma-informes-ec/functions/portal/correo.py`: SMTP de Google Workspace (`smtp.gmail.com:587`, STARTTLS) como `notificaciones@equipos.com.uy`, reintentos acotados, clasificación de errores y sin loguear credenciales.
- [ ] Plantillas fijas en el código (`api/app/plantillas.py`), en texto plano: "Bienvenida" y "Restablecer". Variables: `{{nombre}}`, `{{email}}`, `{{rol}}`, `{{enlace}}`, `{{url_app}}`, `{{admin}}`. Firma fija al pie: "Equipos Consultores · Base de Empresas — Este correo se envió automáticamente."
- [ ] La "Bienvenida" explica que el enlace vence en una hora y que, si venció, se pide otro con "¿Olvidaste tu contraseña?" en el login o a un administrador.
- [ ] Cada intento de envío deja una fila en una tabla nueva `correo_envio` (tipo, destinatario, estado enviado/fallido, motivo, intentos, disparado por, fecha). Nunca guarda el enlace. Se purga a los 90 días.
- [ ] Migración nueva `db/empresas/NNNN_alta_con_enlace.sql`, compatible hacia atrás: tabla `correo_envio` y columnas de reenvío en `usuario`.

#### R8 — Pantalla Usuarios

- [ ] El formulario pide email, nombre, rol y permiso de exportar contactos. Debajo: "La persona recibe un correo para crear su contraseña. No hace falta crear nada en Firebase."
- [ ] La tabla muestra, por usuario: activo, último ingreso (de Firebase, si existe), estado del último correo de acceso (enviado / fallido, con el motivo) y el botón "Reenviar acceso".
- [ ] El modal "se muestra una sola vez" aparece solo cuando el correo falló.

#### R9 — Despliegue, secretos y documentación

- [ ] Secreto nuevo `empresas-smtp-password` en Secret Manager, con una **contraseña de aplicación exclusiva** de `notificaciones@equipos.com.uy` para este proyecto (Workspace permite varias), para poder revocarla sin afectar a `paneles` ni a `plataforma-informes-ec`.
- [ ] `infra/desplegar.sh`: monta el secreto como `SMTP_PASSWORD`; pasa `SMTP_USUARIO`, `SMTP_HOST`, `SMTP_PORT` y `APP_URL` (URL de Hosting) como variables; agrega a la cuenta de servicio `empresas-api` el rol **Firebase Authentication Admin** (`roles/firebaseauth.admin`), necesario para crear cuentas, deshabilitarlas y generar enlaces.
- [ ] Si `empresas-smtp-password` no existe, el script lo pide por la terminal (sin eco) y lo crea, igual que hace con los tokens.
- [ ] `docs/despliegue.md`, paso 3 (Usuarios): reescribirlo. El administrador inicial recibe su enlace al terminar el paso 2; el resto se da de alta solo desde la pantalla Usuarios.
- [ ] `docs/despliegue.md`: agregar las variables nuevas a la tabla, el paso de la contraseña de aplicación, y en "Problemas frecuentes" los casos de correo fallido, enlace vencido y usuario desactivado.
- [ ] `docs/decisiones.md`: nueva decisión **D32 — Alta con enlace de acceso**, con el problema, la decisión, la diferencia con `plataforma-informes-ec` (`email_verified=True`) y las alternativas descartadas (ingreso con Google, alta en la consola).
- [ ] `docs/costos.md`: agregar la fila del secreto y del SMTP.
- [ ] Manual de usuario: secciones de alta, reenviar acceso y primer ingreso.

#### R10 — Tests

- [ ] API (mockeando el Admin SDK de Firebase y el SMTP):
  - Alta de un email nuevo → cuenta creada con `email_verified=True`, registro en `usuario`, correo "Bienvenida" enviado, sin `enlace` en la respuesta.
  - Alta con SMTP fallido → cuenta y registro creados, `correo.enviado=false` con motivo, `enlace` en la respuesta.
  - Alta de un email con cuenta existente → no se crea otra cuenta, no se manda correo, la cuenta queda verificada.
  - Edición de rol de un usuario existente → no manda correo.
  - Reenviar acceso → "Bienvenida" si nunca ingresó, "Restablecer" si ya ingresó; registra quién y cuándo.
  - Desactivar / reactivar → la cuenta de Firebase queda `disabled=True` / `False`.
  - El enlace no aparece en auditoría, en `correo_envio` ni en los logs capturados.
  - Las acciones de usuarios rechazan a quien no es administrador (403).
- [ ] Siguen pasando todos los tests existentes de `api`, `fase0` y `jobs/cdr`.

### P1 — Nice-to-Have

- **"¿Olvidaste tu contraseña?" por Workspace.** El login usa un endpoint público `POST /acceso/restablecer` que manda la plantilla "Restablecer" desde `notificaciones@` (como `solicitar_restablecimiento` en `plataforma-informes-ec`): responde igual exista o no la cuenta y tiene un tope de 3 pedidos por hora por dirección. Hoy sale del remitente por defecto de Firebase.
- **Plantillas editables** desde la pantalla Configuración, guardadas en la configuración versionada, con validación de variables y "Enviarme una prueba".
- **Último ingreso en la ficha del usuario** guardado en `usuario` al resolver `/me`, para no depender de Firebase al listar.

### P2 — Future Considerations

- Avisos por correo de eventos del sistema (muestra lista, ingesta terminada, tarea con error), reusando `correo.py` y `correo_envio`.
- Alta masiva desde un Excel de emails y roles.

## 6. Migración del estado actual

- La cuenta que ya se creó a mano en la consola (`garaujo@equipos.com.uy`) se resuelve con "Reenviar acceso" o con `./infra/desplegar.sh invitar`: la cuenta queda verificada y llega un enlace para fijar una clave nueva.
- Los usuarios ya registrados en `usuario` sin cuenta en Firebase se resuelven con "Reenviar acceso" (R4 crea la cuenta).
- Después del despliegue, deshabilitar en Firebase Authentication → Configuración la **creación de cuentas por parte de los usuarios**, para que solo la API pueda crear cuentas.

## 7. Costos y límites

Costo recurrente adicional esperado: **US$0**.

| Ítem | Uso estimado | Costo |
| --- | --- | --- |
| Firebase Authentication (email y contraseña, Admin SDK) | Decenas de usuarios internos | US$0 (tramo gratuito) |
| Secret Manager (`empresas-smtp-password`) | 1 secreto, pocos accesos | US$0 dentro del tramo gratuito (después, US$0,06 por versión activa al mes) |
| SMTP de Google Workspace | Decenas de correos al mes | Incluido en la licencia de `notificaciones@`, que ya se paga |
| Cloud SQL (`correo_envio`) | Pocas filas | Despreciable |

**Límite a tener en cuenta:** 2.000 destinatarios por día por cuenta de Workspace, compartidos entre `paneles`, `plataforma-informes-ec` y este sistema. Con el volumen de altas de la Base de Empresas no es un riesgo, pero conviene saberlo.

## 8. Success Metrics

| Métrica | Meta | Cómo se mide | Cuándo |
| --- | --- | --- | --- |
| Altas que requieren tocar la consola de Firebase | 0 | Guía de despliegue y operación | Al cerrar el PR |
| Correos de acceso enviados OK | ≥ 98% | `correo_envio` enviados / total | 2 semanas |
| Usuarios nuevos que ingresan en 7 días | ≥ 90% | Primer ingreso en Firebase ≤ 7 días después del alta | 1 mes |
| Altas que necesitan "Reenviar acceso" | ≤ 20% | Usuarios con ≥ 1 reenvío / altas | 1 mes |
| Intentos de ingreso fallidos sin mensaje visible | 0 | Prueba manual de cada caso de R1 y R5 | Antes de desplegar |

## 9. Open Questions

| Pregunta | Quién | ¿Bloquea? |
| --- | --- | --- |
| ¿Se genera una contraseña de aplicación exclusiva de `notificaciones@` para este proyecto? Se recomienda que sí. | Operaciones | Sí, para desplegar R7 |
| ¿Qué URL va en los correos: `<proyecto>.web.app` o un dominio propio? Si es propio, hay que agregarlo a los dominios autorizados de Firebase. | Operaciones | No: es configuración (`APP_URL`) |
| ¿SPF, DKIM y DMARC de `equipos.com.uy` ya están configurados (por `paneles`)? Si no, los correos pueden caer en spam. | Operaciones | No |

## 10. Timeline Considerations

- Un PR, estimado en 1 a 2 días de desarrollo y pruebas, porque reusa `correo.py` y la lógica de `accesos.py` de `plataforma-informes-ec`.
- **Bloquea el paso 3 del despliegue en curso.** R1 (el bug) puede ir primero, solo, para destrabar el diagnóstico.
- Pasos manuales fuera del código: crear la contraseña de aplicación en `notificaciones@` (5 minutos) y, después de verificar, deshabilitar la creación de cuentas por parte de los usuarios en Firebase.

## 11. Definition of Done

- [ ] R1 a R10 implementados con sus criterios verificados.
- [ ] Desplegado con `./infra/desplegar.sh todo` en el proyecto `equipos-base-empresas`.
- [ ] El administrador inicial recibió su enlace al terminar el despliegue, fijó su clave y entró.
- [ ] Ese administrador dio de alta a un segundo usuario solo desde la pantalla Usuarios, y ese usuario entró con el enlace del correo.
- [ ] Con `SMTP_PASSWORD` inválida, un alta terminó bien y mostró el enlace una sola vez.
- [ ] Un usuario desactivado no pudo entrar y vio el mensaje correspondiente.
- [ ] `docs/despliegue.md`, `docs/decisiones.md`, `docs/costos.md` y el manual actualizados.
