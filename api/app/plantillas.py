"""Plantillas fijas de los correos de acceso, en texto plano (R7).

Variables: {{nombre}}, {{email}}, {{rol}}, {{enlace}}, {{url_app}}, {{admin}}.
"""
import re

FIRMA = "--\nEquipos Consultores · Base de Empresas — Este correo se envió automáticamente."

BIENVENIDA = {
    "asunto": "Tu acceso a la Base de Empresas de Equipos",
    "cuerpo": """Hola {{nombre}}:

{{admin}} te dio acceso a la Base de Empresas de Equipos Consultores con el rol {{rol}}.

Para entrar, primero creá tu contraseña con este enlace:

{{enlace}}

El enlace vence en una hora. Si venció, entrá a {{url_app}}, escribí tu email ({{email}}) y tocá
«¿Olvidaste tu contraseña?», o pedile a un administrador que te reenvíe el acceso.

Después vas a entrar siempre desde {{url_app}} con tu email y la contraseña que elijas.

""" + FIRMA,
}

RESTABLECER = {
    "asunto": "Restablecé tu contraseña de la Base de Empresas",
    "cuerpo": """Hola {{nombre}}:

{{admin}} pidió un enlace nuevo para que puedas entrar a la Base de Empresas de Equipos Consultores.

Elegí una contraseña nueva con este enlace:

{{enlace}}

El enlace vence en una hora. Si venció, entrá a {{url_app}}, escribí tu email ({{email}}) y tocá
«¿Olvidaste tu contraseña?», o pedile a un administrador que te reenvíe el acceso.

Si no esperabas este correo, podés ignorarlo: tu contraseña actual sigue funcionando.

""" + FIRMA,
}

PLANTILLAS = {"bienvenida": BIENVENIDA, "restablecer": RESTABLECER}
ROLES_LEGIBLES = {"admin": "administrador/a", "steward": "data steward", "jefe": "jefe/a de proyecto",
                  "coordinador": "coordinador/a de campo", "lectura": "lectura"}


def render(tipo: str, variables: dict) -> tuple[str, str]:
    """Devuelve (asunto, cuerpo) con las variables reemplazadas."""
    p = PLANTILLAS[tipo]

    def sustituir(texto):
        return re.sub(r"\{\{(\w+)\}\}", lambda m: str(variables.get(m.group(1), "")), texto)

    return sustituir(p["asunto"]), sustituir(p["cuerpo"])
