"""Proveedores del enriquecimiento (SPEC_fase2_enriquecimiento, B2; D45): Google Places, Brave Search, la lectura
del sitio web, la extracción con un modelo chico de Claude y la búsqueda web con Claude (D57, último recurso).

Cada función hace UNA llamada (paga o no) y devuelve datos ya limpios. El costo y los topes los maneja
enriquecimiento.py antes de llamar. Las claves salen de Secret Manager (secretos.leer) y nunca se registran.
En los tests los proveedores se reemplazan (monkeypatch) y ningún test hace llamadas pagas; con
PROVEEDORES_MODO=simulado responden con datos de ejemplo (demo local).

Datos personales (Ley 18.331): solo se guardan datos institucionales. El prompt de la extracción los prohíbe
y la salida se valida: se descartan los teléfonos asociados a una persona y los emails que no son genéricos.
"""
import hashlib
import html as htmlmod
import ipaddress
import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field

import httpx

from . import secretos, settings, telefonos as telmod
from .util import dominio, sin_tildes

log = logging.getLogger(__name__)
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
UA = "Mozilla/5.0 (compatible; BaseEmpresas/1.0)"


class ProveedorError(Exception):
    """La llamada falló. cobrada indica si el proveedor igual la cobra; clave_invalida, que no tiene sentido seguir."""

    def __init__(self, mensaje: str, cobrada: bool = False, clave_invalida: bool = False):
        super().__init__(mensaje)
        self.cobrada = cobrada
        self.clave_invalida = clave_invalida


DETALLE_MAX = 300   # caracteres del motivo que devuelve el proveedor


def detalle_error(r: httpx.Response, k: str | None = None) -> str:
    """El motivo que devuelve el proveedor en el cuerpo de un error, legible y recortado, sin la clave (D57, B2).
    Brave: {"error": {"detail": "...", "meta": {"errors": [{"loc": [...], "msg": "..."}]}}};
    Google: {"error": {"message": "..."}}; Anthropic: {"error": {"message": "..."}}."""
    try:
        j = r.json()
    except ValueError:
        texto = (r.text or "").strip()
    else:
        e = j.get("error") if isinstance(j, dict) else None
        partes = []
        if isinstance(e, dict):
            for x in ((e.get("meta") or {}).get("errors") or []):
                loc = [str(c) for c in (x.get("loc") or []) if c not in ("query", "body")]
                partes.append(f"{'.'.join(loc) + ': ' if loc else ''}{x.get('msg') or ''}".strip())
            if not partes:
                partes.append(str(e.get("detail") or e.get("message") or e.get("status") or ""))
        elif isinstance(j, dict) and j.get("detail"):
            partes.append(str(j["detail"]))
        texto = "; ".join(x for x in partes if x) or json.dumps(j, ensure_ascii=False)
    texto = re.sub(r"\s+", " ", texto).strip()
    if k:
        texto = texto.replace(k, "***")
    return texto[:DETALLE_MAX]


def clave(proveedor: str) -> str | None:
    if settings.PROVEEDORES_MODO == "simulado":
        return "simulada"
    return secretos.leer(settings.SECRETOS_PROVEEDORES[proveedor])


# ─────────────────────────────────────────────────────────────
# Google Places Text Search (New)
# ─────────────────────────────────────────────────────────────

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
# Teléfono y sitio están en el SKU Text Search Enterprise (precio en la configuración). No se pide la ubicación:
# los términos permiten guardarla solo 30 días y no hace falta.
PLACES_CAMPOS = ("places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
                 "places.internationalPhoneNumber,places.websiteUri,places.addressComponents,places.businessStatus,"
                 "nextPageToken")


@dataclass
class Lugar:
    place_id: str
    nombre: str
    direccion: str | None = None
    telefono: str | None = None
    web: str | None = None
    departamento: str | None = None
    localidad: str | None = None
    cerrado: bool = False


def _departamento(componentes) -> tuple[str | None, str | None]:
    dep = loc = None
    for c in componentes or []:
        tipos = c.get("types") or []
        texto = c.get("longText") or c.get("shortText")
        if "administrative_area_level_1" in tipos:
            dep = re.sub(r"(?i)^departamento de\s+|\s+department$", "", texto or "").strip() or None
        elif "locality" in tipos:
            loc = texto
    return dep, loc


def places_buscar(consulta: str, pagina: str | None = None) -> tuple[list[Lugar], str | None]:
    """Una llamada Text Search. Devuelve (lugares, token de la página siguiente)."""
    if settings.PROVEEDORES_MODO == "simulado":
        return _sim_places(consulta, pagina)
    k = clave("google_places")
    if not k:
        raise ProveedorError("Google Places no está configurado", clave_invalida=True)
    cuerpo = {"textQuery": consulta, "regionCode": "UY", "languageCode": "es", "pageSize": 20}
    if pagina:
        cuerpo["pageToken"] = pagina
    try:
        r = httpx.post(PLACES_URL, json=cuerpo, timeout=TIMEOUT,
                       headers={"X-Goog-Api-Key": k, "X-Goog-FieldMask": PLACES_CAMPOS})
    except httpx.HTTPError as e:
        raise ProveedorError(f"Google Places no respondió ({type(e).__name__})") from e
    if r.status_code in (401, 403):
        raise ProveedorError(f"Google Places rechazó la clave ({r.status_code}): {detalle_error(r, k)}", clave_invalida=True)
    if r.status_code >= 400:
        raise ProveedorError(f"Google Places respondió {r.status_code}: {detalle_error(r, k)}")
    datos = r.json()
    lugares = []
    for p in datos.get("places") or []:
        dep, loc = _departamento(p.get("addressComponents"))
        lugares.append(Lugar(place_id=p.get("id"), nombre=(p.get("displayName") or {}).get("text") or "",
                             direccion=p.get("formattedAddress"),
                             telefono=p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber"),
                             web=p.get("websiteUri"), departamento=dep, localidad=loc,
                             cerrado=p.get("businessStatus") == "CLOSED_PERMANENTLY"))
    return lugares, datos.get("nextPageToken")


# ─────────────────────────────────────────────────────────────
# Brave Search
# ─────────────────────────────────────────────────────────────

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
# Parámetros de Brave (D57, B1). Referencia de la API, con las listas de valores admitidos:
#   https://api-dashboard.search.brave.com/app/documentation/web-search/query
#   https://api-dashboard.search.brave.com/app/documentation/web-search/codes
# - country: Brave no admite «UY» (HTTP 422 del 26/11/2026: «Input should be 'AR', 'AU', …, 'US' or 'ALL'»). Sin
#   country usa US, así que se manda ALL. La consulta ya lleva «Uruguay» y la localidad.
# - search_lang: «es» está admitido (aquel 422 rechazó solo country; la validación lista todos los campos inválidos).
# - ui_lang: no se manda. No se pudo confirmar que «es-UY» esté en la lista de la API, y sin él Brave responde igual.
BRAVE_PAIS = "ALL"
BRAVE_IDIOMA = "es"
BRAVE_RESULTADOS = 10
BRAVE_ESPERA_429 = 1.1   # el plan limita los pedidos por segundo: se reintenta una vez después de esto


@dataclass
class Resultado:
    url: str
    titulo: str = ""
    descripcion: str = ""


def brave_buscar(consulta: str) -> list[Resultado]:
    if settings.PROVEEDORES_MODO == "simulado":
        return _sim_brave(consulta)
    k = clave("brave")
    if not k:
        raise ProveedorError("Brave Search no está configurado", clave_invalida=True)
    params = {"q": consulta, "country": BRAVE_PAIS, "search_lang": BRAVE_IDIOMA, "count": BRAVE_RESULTADOS}
    for intento in (1, 2):
        try:
            r = httpx.get(BRAVE_URL, params=params, headers={"X-Subscription-Token": k, "Accept": "application/json"},
                          timeout=TIMEOUT)
        except httpx.HTTPError as e:
            raise ProveedorError(f"Brave Search no respondió ({type(e).__name__})") from e
        if r.status_code == 429 and intento == 1:   # límite por segundo del plan: un solo reintento (no se cobra)
            time.sleep(BRAVE_ESPERA_429)
            continue
        break
    if r.status_code in (401, 403):
        raise ProveedorError(f"Brave Search rechazó la clave ({r.status_code}): {detalle_error(r, k)}", clave_invalida=True)
    if r.status_code >= 400:
        raise ProveedorError(f"Brave Search respondió {r.status_code}: {detalle_error(r, k)}")
    return [Resultado(url=x.get("url") or "", titulo=x.get("title") or "", descripcion=x.get("description") or "")
            for x in ((r.json().get("web") or {}).get("results") or [])]


def _palabras(nombre: str) -> list[str]:
    from .util import razon_normalizada

    return [p for p in razon_normalizada(nombre).split() if len(p) >= 3]


def sitio_oficial(resultados: list[Resultado], nombre: str, directorios: list[str]) -> str | None:
    """El sitio que mejor coincide con el nombre, descartando directorios, redes sociales y guías."""
    palabras = _palabras(nombre)
    if not palabras:
        return None
    pegado = "".join(palabras)
    mejor, puntos = None, 0.0
    for r in resultados:
        d = dominio(r.url)
        if not d or any(d == x or d.endswith("." + x) for x in directorios):
            continue
        etiqueta = re.sub(r"[^a-z0-9]", "", d.split(".")[0])
        p = sum(1 for w in palabras if w in etiqueta) / len(palabras)
        if etiqueta and (etiqueta in pegado or pegado.startswith(etiqueta)):
            p = max(p, 0.9)
        if p > puntos:
            mejor, puntos = r.url, p
    return mejor if puntos >= 0.5 else None


# ─────────────────────────────────────────────────────────────
# Sitio web: portada y página de contacto (como texto)
# ─────────────────────────────────────────────────────────────

MAX_CARACTERES = 24000   # ≈ 6.000 tokens entre las dos páginas


def _texto(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", html)
    # Los enlaces tel: y mailto: suelen tener el dato que no se ve en el texto
    html = re.sub(r'(?i)<a[^>]+href="(tel|mailto):([^"]+)"[^>]*>', lambda m: f" {m.group(2)} ", html)
    texto = htmlmod.unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", texto)).strip()


def _contacto(html: str, base: str) -> str | None:
    for m in re.finditer(r'(?i)<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', html):
        href, etiqueta = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).lower()
        if re.search(r"contact|contacto|ubicaci", href.lower() + " " + etiqueta):
            return str(httpx.URL(base).join(href))
    return None


def leer_sitio(url: str) -> tuple[str, list[str]]:
    """Portada y página de contacto (máximo 2 páginas). Devuelve (texto, urls leídas). No es un paso pago."""
    if settings.PROVEEDORES_MODO == "simulado":
        return _sim_sitio(url)
    if not re.match(r"(?i)^https?://", url):
        url = "https://" + url
    leidas, partes = [], []
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": UA}) as c:
            r = c.get(url)
            r.raise_for_status()
            leidas.append(str(r.url))
            partes.append(_texto(r.text))
            otra = _contacto(r.text, str(r.url))
            if otra and otra != str(r.url):
                try:
                    r2 = c.get(otra)
                    if r2.status_code < 400:
                        leidas.append(str(r2.url))
                        partes.append(_texto(r2.text))
                except httpx.HTTPError:
                    pass
    except httpx.HTTPError as e:
        raise ProveedorError(f"No se pudo leer el sitio ({type(e).__name__})") from e
    return "\n\n".join(partes)[:MAX_CARACTERES], leidas


# ─────────────────────────────────────────────────────────────
# Extracción con Claude (salida estructurada) y validación de datos personales
# ─────────────────────────────────────────────────────────────

INSTRUCCIONES = """Extraés datos INSTITUCIONALES de una empresa uruguaya a partir del texto de su sitio web.

Devolvé solo lo que está en el texto, sin inventar:
- telefonos: los números de contacto de la empresa (centralita, oficina, ventas, WhatsApp de la empresa). Para cada uno, \
"asociado_a_persona" es true si el texto lo presenta junto al nombre de una persona (por ejemplo «Juan Pérez – 099 123 456»).
- emails: solo direcciones genéricas de la empresa (info@, contacto@, ventas@, administracion@…).
- direccion: la dirección de la empresa, si figura.
- es_estudio_contable_juridico: true si el sitio es de un estudio contable, jurídico, escribanía o asesoría que \
representa a otras empresas (no de la empresa buscada).
- confianza: de 0 a 1, cuán seguro estás de que el sitio es de la empresa buscada.

Está PROHIBIDO devolver datos personales: no incluyas nombres de personas, emails personales (nombre.apellido@…) \
ni celulares de personas."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "telefonos": {"type": "array", "items": {
            "type": "object",
            "properties": {"numero": {"type": "string"}, "asociado_a_persona": {"type": "boolean"}},
            "required": ["numero", "asociado_a_persona"], "additionalProperties": False}},
        "emails": {"type": "array", "items": {"type": "string"}},
        "direccion": {"type": ["string", "null"]},
        "es_estudio_contable_juridico": {"type": "boolean"},
        "confianza": {"type": "number"},
    },
    "required": ["telefonos", "emails", "direccion", "es_estudio_contable_juridico", "confianza"],
    "additionalProperties": False,
}


@dataclass
class Extraccion:
    telefonos: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    direccion: str | None = None
    estudio: bool = False
    confianza: float = 0.0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    descartados: int = 0         # cuántos datos personales se descartaron (sin guardarlos)


def claude_extraer(texto: str, empresa: str, modelo: str) -> Extraccion:
    """Una llamada a Claude y la validación de su salida. El costo sale de usage (tokens de entrada y de salida)."""
    datos, ent, sal = claude_api(texto, empresa, modelo)
    return validar_extraccion(datos, texto, ent, sal)


def error_claude(e: Exception, modelo: str, k: str | None) -> Exception:
    """Traduce un error del SDK de Anthropic a ProveedorError, con el detalle que devuelve la API y sin la clave."""
    import anthropic

    def det(x) -> str:
        r = getattr(x, "response", None)
        return detalle_error(r, k) if r is not None else str(getattr(x, "message", "") or x)[:DETALLE_MAX]

    if isinstance(e, anthropic.AuthenticationError):
        return ProveedorError(f"Claude rechazó la clave: {det(e)}", clave_invalida=True)
    if isinstance(e, anthropic.PermissionDeniedError):
        return ProveedorError(f"La clave de Claude no tiene permiso: {det(e)}", clave_invalida=True)
    if isinstance(e, anthropic.NotFoundError):
        return ProveedorError(f"Modelo de Claude inexistente: {modelo}", clave_invalida=True)
    if isinstance(e, anthropic.RateLimitError):
        return ProveedorError(f"Claude: límite de uso, se reintenta en la próxima corrida ({det(e)})")
    if isinstance(e, anthropic.APIStatusError):
        return ProveedorError(f"Claude respondió {e.status_code}: {det(e)}")
    if isinstance(e, anthropic.APIConnectionError):
        return ProveedorError("Claude no respondió")
    return e


def claude_api(texto: str, empresa: str, modelo: str) -> tuple[dict, int, int]:
    """La llamada en sí (salida estructurada con JSON schema). Devuelve (datos, tokens de entrada, tokens de salida)."""
    if settings.PROVEEDORES_MODO == "simulado":
        return _sim_claude(texto), len(texto) // 4, 120
    import anthropic

    k = clave("claude")
    if not k:
        raise ProveedorError("Claude no está configurado", clave_invalida=True)
    cliente = anthropic.Anthropic(api_key=k, max_retries=2, timeout=60.0)
    try:
        r = cliente.messages.create(
            model=modelo, max_tokens=2000, system=INSTRUCCIONES,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": ESQUEMA}},
            messages=[{"role": "user", "content": f"Empresa buscada: {empresa}\n\nTexto del sitio:\n{texto}"}])
    except Exception as e:  # noqa: BLE001 - se traduce abajo
        raise error_claude(e, modelo, k) from e
    ent, sal = r.usage.input_tokens, r.usage.output_tokens
    if r.stop_reason == "refusal":
        return {}, ent, sal
    texto_r = next((b.text for b in r.content if b.type == "text"), "")
    try:
        return json.loads(texto_r), ent, sal
    except json.JSONDecodeError:
        return {}, ent, sal


# ─────────────────────────────────────────────────────────────
# Búsqueda web con Claude (D57, B4): último recurso, con verificación obligatoria de cada teléfono en su fuente
# ─────────────────────────────────────────────────────────────

INSTRUCCIONES_WEB = """Buscás en la web los datos de contacto INSTITUCIONALES de una empresa uruguaya.

Usá la herramienta de búsqueda web (como máximo las búsquedas que tengas disponibles) y devolvé solo datos que \
encontraste en una página que corresponda claramente a ESA empresa (misma razón social o nombre de fantasía, y \
la misma localidad o departamento si figuran). Nunca contestes de memoria ni inventes números.

Al final, respondé SOLO con un objeto JSON, sin texto antes ni después, con esta forma:
{"telefonos": [{"numero": "…", "url": "la página exacta donde aparece ese número"}],
 "web": "sitio oficial de la empresa o null", "email": "email institucional genérico o null",
 "direccion": "dirección de la empresa o null", "confianza": 0.0}

- telefonos: solo números de contacto de la empresa (centralita, oficina, ventas, WhatsApp de la empresa), cada uno con \
la URL de la página donde lo leíste. Si no tenés la URL, no lo incluyas.
- email: solo direcciones genéricas (info@, contacto@, ventas@…).
- confianza: de 0 a 1, cuán seguro estás de que los datos son de esta empresa y no de otra con nombre parecido.
- Si no encontrás una fuente que corresponda claramente a esta empresa, devolvé la lista vacía y confianza 0.

Está PROHIBIDO devolver datos personales: nombres de personas, emails personales (nombre.apellido@…) ni celulares \
de personas."""


@dataclass
class BusquedaWeb:
    telefonos: list[dict] = field(default_factory=list)   # [{"numero", "url"}] tal como los propuso Claude
    web: str | None = None
    email: str | None = None
    direccion: str | None = None
    confianza: float = 0.0
    busquedas: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    rechazada: bool = False


def herramienta_busqueda(modelo: str, max_usos: int) -> dict:
    """La herramienta de búsqueda web del servidor de Anthropic. Haiku no admite la versión 20260209 (con filtrado
    dinámico): para Haiku va la versión básica. La ubicación se fija en Uruguay."""
    tipo = "web_search_20250305" if "haiku" in modelo else "web_search_20260209"
    return {"type": tipo, "name": "web_search", "max_uses": max_usos,
            "user_location": {"type": "approximate", "country": "UY", "timezone": "America/Montevideo"}}


def _json_de(texto: str) -> dict:
    """El objeto JSON de la respuesta (puede venir entre ```json … ``` o con texto alrededor)."""
    texto = texto.strip()
    m = re.search(r"\{.*\}", texto, re.S)
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return d if isinstance(d, dict) else {}


def claude_buscar_web(empresa: dict, modelo: str, max_usos: int) -> BusquedaWeb:
    """Una consulta a Claude con búsqueda web (hasta max_usos búsquedas). Devuelve lo que propone, SIN verificar:
    verificar_telefonos() descarta los números que no aparecen en la página citada."""
    if settings.PROVEEDORES_MODO == "simulado":
        return _sim_claude_web(empresa)
    import anthropic

    k = clave("claude")
    if not k:
        raise ProveedorError("Claude no está configurado", clave_invalida=True)
    datos = "\n".join(f"{t}: {v}" for t, v in (("Razón social", empresa.get("razon_social")),
                                                 ("Nombre de fantasía", empresa.get("fantasia")),
                                                 ("RUT", empresa.get("rut")), ("Localidad", empresa.get("localidad")),
                                                 ("Departamento", empresa.get("departamento"))) if v)
    pregunta = {"role": "user", "content": f"Empresa buscada (Uruguay):\n{datos}"}
    cliente = anthropic.Anthropic(api_key=k, max_retries=2, timeout=180.0)
    out, contenido = BusquedaWeb(), []
    for _ in range(4):   # pause_turn: el servidor cortó su bucle de búsquedas; se continúa sin agregar mensajes
        mensajes = [pregunta] + ([{"role": "assistant", "content": contenido}] if contenido else [])
        try:
            r = cliente.messages.create(model=modelo, max_tokens=4000, system=INSTRUCCIONES_WEB,
                                        tools=[herramienta_busqueda(modelo, max_usos)], messages=mensajes)
        except Exception as e:  # noqa: BLE001 - se traduce
            raise error_claude(e, modelo, k) from e
        out.tokens_entrada += r.usage.input_tokens
        out.tokens_salida += r.usage.output_tokens
        uso = getattr(r.usage, "server_tool_use", None)
        out.busquedas += int(getattr(uso, "web_search_requests", 0) or 0)
        contenido = contenido + list(r.content)
        if r.stop_reason != "pause_turn":
            break
    if r.stop_reason == "refusal":
        out.rechazada = True
        return out
    d = _json_de("".join(b.text for b in r.content if getattr(b, "type", None) == "text"))
    out.telefonos = [{"numero": str((t or {}).get("numero") or "").strip(), "url": str((t or {}).get("url") or "").strip()}
                     for t in (d.get("telefonos") or []) if isinstance(t, dict)]
    out.web = (str(d.get("web")).strip() or None) if d.get("web") else None
    out.email = (str(d.get("email")).strip().lower() or None) if d.get("email") else None
    out.direccion = str(d.get("direccion")).strip()[:200] if d.get("direccion") else None
    try:
        out.confianza = max(0.0, min(1.0, float(d.get("confianza") or 0)))
    except (TypeError, ValueError):
        out.confianza = 0.0
    return out


def leer_pagina(url: str) -> str:
    """Una sola página, como texto (para verificar que el número está ahí). No es un paso pago."""
    if settings.PROVEEDORES_MODO == "simulado":
        return _sim_pagina(url)
    if not re.match(r"(?i)^https?://", url):
        raise ProveedorError("URL inválida")

    def solo_publicas(req: httpx.Request):   # también en cada redirección
        if not host_publico(req.url.host):
            raise ProveedorError("la URL apunta a una dirección interna")

    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": UA},
                          event_hooks={"request": [solo_publicas]}) as c:
            r = c.get(url)
            r.raise_for_status()
            return _texto(r.text)
    except httpx.HTTPError as e:
        raise ProveedorError(f"No se pudo leer la página ({type(e).__name__})") from e


def host_publico(host: str) -> bool:
    """La URL la eligió el modelo a partir de páginas de terceros: no se lee nada que resuelva a una dirección privada,
    local o reservada (metadatos de la nube, servicios internos)."""
    host = (host or "").strip("[]").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".internal", ".local")):
        return False
    try:
        ips = {i[4][0] for i in socket.getaddrinfo(host, None)}
    except (socket.gaierror, UnicodeError):
        return False
    for ip in ips:
        a = ipaddress.ip_address(ip.split("%")[0])
        if not a.is_global or a.is_multicast:
            return False
    return bool(ips)


_NUMERO = re.compile(r"(?:\+?\s*598[\s.\-]*)?\(?\d[\d\s().\-]{5,16}\d")


def posiciones_numero(texto: str, e164: str) -> list[int]:
    """Dónde aparece el número en el texto, escrito de cualquier forma (con o sin 598, espacios, puntos o guiones)."""
    salida = []
    for m in _NUMERO.finditer(texto):
        n = telmod.normalizar(m.group(0))
        if n.e164 == e164:
            salida.append(m.start())
    return salida


@dataclass
class Verificacion:
    telefonos: list[tuple[str, str]] = field(default_factory=list)   # (e164, url) verificados
    no_verificados: list[dict] = field(default_factory=list)          # {"url", "motivo"} (sin el número)
    personales: int = 0


def verificar_telefonos(b: BusquedaWeb, nombre: str, directorios: list[str]) -> Verificacion:
    """Contra números inventados: cada teléfono tiene que aparecer en la página que Claude citó. En un directorio,
    además, junto al nombre de la empresa. Se descartan los que están junto al nombre de una persona."""
    v, paginas, vistos = Verificacion(), {}, set()
    palabras = _palabras(nombre)
    for t in b.telefonos:
        n = telmod.normalizar(t["numero"]) if t["numero"] else None
        url = t["url"]
        if not n or not n.discable or n.e164 in vistos:
            continue
        if not url or not re.match(r"(?i)^https?://", url):
            v.no_verificados.append({"url": url or None, "motivo": "sin la página donde aparece"})
            continue
        if url not in paginas:
            try:
                paginas[url] = leer_pagina(url)
            except ProveedorError as e:
                paginas[url] = None
                v.no_verificados.append({"url": url, "motivo": str(e)})
                continue
        texto = paginas[url]
        if texto is None:
            v.no_verificados.append({"url": url, "motivo": "la página no responde"})
            continue
        pos = posiciones_numero(texto, n.e164)
        if not pos:
            v.no_verificados.append({"url": url, "motivo": "el número no aparece en la página"})
            continue
        d = dominio(url)
        if d and any(d == x or d.endswith("." + x) for x in directorios):
            cerca = any(sum(1 for w in palabras if w in sin_tildes(texto[max(0, p - 300):p + 300].lower())) * 2
                        >= max(1, len(palabras)) for p in pos)
            if not cerca:
                v.no_verificados.append({"url": url, "motivo": "en un directorio, lejos del nombre de la empresa"})
                continue
        if n.tipo == "celular" and _cerca_de_persona(texto, t["numero"]):
            v.personales += 1
            continue
        vistos.add(n.e164)
        v.telefonos.append((n.e164, url))
    return v


# Emails institucionales: la parte local tiene que ser genérica
GENERICOS = ("info", "contacto", "contact", "ventas", "venta", "administracion", "admin", "recepcion", "consultas",
             "consulta", "hola", "comercial", "secretaria", "rrhh", "empleo", "compras", "facturacion", "atencion",
             "clientes", "cliente", "oficina", "reservas", "pedidos", "soporte", "mail", "correo", "general",
             "gerencia", "direccion", "cobranza", "cobranzas", "proveedores", "marketing", "prensa", "uruguay", "uy")
_TITULOS = r"(sr|sra|srta|lic|cr|cra|dr|dra|ing|esc|arq|prof)\.?"


def _email_generico(e: str) -> bool:
    local = e.split("@", 1)[0].lower()
    return any(local == g or local.startswith(g) or local.endswith(g) for g in GENERICOS) and "." not in local


def _cerca_de_persona(texto: str, crudo: str) -> bool:
    """El número aparece junto a un nombre de persona (dos palabras con mayúscula) o un título (Sr., Lic., Cr.…)."""
    digitos = re.sub(r"\D", "", crudo)[-8:]
    if not digitos:
        return False
    plano = re.sub(r"[^\w\n]+", " ", texto)
    for m in re.finditer(r"\d[\d ]{6,}\d", plano):
        if re.sub(r"\D", "", m.group(0))[-8:] != digitos:
            continue
        ventana = plano[max(0, m.start() - 60):m.start()]
        linea = ventana.split("\n")[-1]
        if re.search(rf"(?i)\b{_TITULOS}\s", linea + " "):
            return True
        vacias = {"Tel", "Telefono", "Teléfono", "Celular", "Cel", "Whatsapp", "WhatsApp", "Ventas", "Oficina",
                  "Contacto", "Fax", "Uruguay", "Montevideo", "Atención", "Atencion", "Clientes", "Central"}
        nombres = [w for w in re.findall(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}\b", linea) if w not in vacias]
        if len(nombres) >= 2:
            return True
    return False


def validar_extraccion(datos: dict, texto: str, ent: int = 0, sal: int = 0) -> Extraccion:
    out = Extraccion(tokens_entrada=ent, tokens_salida=sal)
    vistos = set()
    for t in datos.get("telefonos") or []:
        crudo = str((t or {}).get("numero") or "").strip()
        n = telmod.normalizar(crudo)
        if not n.discable or n.e164 in vistos:
            continue
        personal = bool(t.get("asociado_a_persona")) or (n.tipo == "celular" and _cerca_de_persona(texto, crudo))
        if personal:
            out.descartados += 1
            continue
        vistos.add(n.e164)
        out.telefonos.append(n.e164)
    for e in datos.get("emails") or []:
        e = str(e or "").strip().lower()
        if re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", e) and _email_generico(e):
            if e not in out.emails:
                out.emails.append(e)
        elif e:
            out.descartados += 1
    d = datos.get("direccion")
    out.direccion = str(d).strip()[:200] if d else None
    out.estudio = bool(datos.get("es_estudio_contable_juridico"))
    try:
        out.confianza = max(0.0, min(1.0, float(datos.get("confianza") or 0)))
    except (TypeError, ValueError):
        out.confianza = 0.0
    return out


# ─────────────────────────────────────────────────────────────
# Simulación (PROVEEDORES_MODO=simulado): demo local sin llamadas pagas, determinística
# ─────────────────────────────────────────────────────────────

def _sim_claude_web(empresa: dict) -> BusquedaWeb:
    """Determinística: la mitad encuentra un teléfono que su página contiene y algunas proponen uno que no está."""
    nombre = empresa.get("razon_social") or empresa.get("fantasia") or ""
    h = _h(nombre)
    slug = re.sub(r"[^a-z0-9]", "", sin_tildes(nombre.lower()))[:20] or "empresa"
    out = BusquedaWeb(busquedas=1 + h % 3, tokens_entrada=12000 + h % 5000, tokens_salida=300)
    if h % 2:
        out.telefonos = [{"numero": _sim_numero(slug), "url": f"https://www.{slug}.com.uy/contacto"}]
        out.confianza = 0.8
    elif h % 3 == 0:
        out.telefonos = [{"numero": _sim_numero(slug), "url": f"https://www.{slug}.com.uy/nosotros"}]
        out.confianza = 0.6
    return out


def _sim_numero(slug: str) -> str:
    return f"2{_h(slug) % 10000000:07d}"


def _sim_pagina(url: str) -> str:
    slug = re.sub(r"^https?://(www\.)?|\.com\.uy.*$", "", url)
    if url.endswith("/contacto"):
        return f"Contacto de {slug}. Teléfono: {_sim_numero(slug)}"
    return f"Página de {slug}, sin teléfonos."


def _h(s: str) -> int:
    return int(hashlib.sha256(sin_tildes(s.lower()).encode()).hexdigest()[:8], 16)


def _sim_places(consulta: str, pagina: str | None):
    nombre = re.split(r",| en | Uruguay", consulta)[0].strip()
    h = _h(consulta + (pagina or ""))
    if " en " in consulta:  # descubrimiento («imprentas en Salto»): una página de 5 resultados
        rubro, _, lugar = consulta.partition(" en ")
        lugar = lugar.replace(", Uruguay", "").strip()
        base = rubro.strip().rstrip("s").capitalize()
        lugares = [Lugar(place_id=f"sim-{_h(consulta)}-{i}", nombre=f"{base} {['del Litoral', 'Central', 'Norte', 'Moderna', 'Sur'][i]}",
                         direccion=f"Calle {i + 1} 123, {lugar}", telefono=f"4{_h(consulta) % 10}{(h + i) % 1000000:06d}",
                         web=None, departamento=lugar.split(",")[-1].strip() or None)
                   for i in range(5)]
        return lugares, None
    if h % 10 < 6:   # 60 % encuentra teléfono
        dep = consulta.split(",")[1].strip() if "," in consulta else None
        return [Lugar(place_id=f"sim-{h}", nombre=nombre, direccion=f"Av. Simulada {h % 3000}, {dep or 'Montevideo'}",
                      telefono=f"2{h % 10000000:07d}", web=f"https://www.{re.sub(r'[^a-z]', '', sin_tildes(nombre.lower()))[:14]}.com.uy"
                      if h % 2 else None, departamento=dep)], None
    return [], None


def _sim_brave(consulta: str):
    nombre = consulta.replace(" Uruguay", "").split(",")[0]
    slug = re.sub(r"[^a-z]", "", sin_tildes(nombre.lower()))[:14]
    return [Resultado(url="https://www.facebook.com/" + slug), Resultado(url=f"https://www.{slug}.com.uy/")]


def _sim_sitio(url: str):
    h = _h(url)
    return (f"Bienvenidos. Contacto: Tel. 2{h % 10000000:07d} · info@{dominio(url)} · Av. Italia {h % 5000}\n"
            f"Gerente: Martín Rodríguez 099 {h % 1000:03d} {h % 999:03d}"), [url]


def _sim_claude(texto: str) -> dict:
    tels = [{"numero": m, "asociado_a_persona": False} for m in re.findall(r"\b[249]\d{7}\b|\b09\d \d{3} \d{3}\b", texto)]
    return {"telefonos": tels, "emails": re.findall(r"[a-z0-9.]+@[a-z0-9.-]+", texto),
            "direccion": (re.search(r"Av\. [A-Za-z]+ \d+", texto) or [None])[0], "es_estudio_contable_juridico": False,
            "confianza": 0.8}
