"""Proveedores del enriquecimiento (SPEC_fase2_enriquecimiento, B2; D45): Google Places, Brave Search, la lectura
del sitio web y la extracción con un modelo chico de Claude.

Cada función hace UNA llamada (paga o no) y devuelve datos ya limpios. El costo y los topes los maneja
enriquecimiento.py antes de llamar. Las claves salen de Secret Manager (secretos.leer) y nunca se registran.
En los tests los proveedores se reemplazan (monkeypatch) y ningún test hace llamadas pagas; con
PROVEEDORES_MODO=simulado responden con datos de ejemplo (demo local).

Datos personales (Ley 18.331): solo se guardan datos institucionales. El prompt de la extracción los prohíbe
y la salida se valida: se descartan los teléfonos asociados a una persona y los emails que no son genéricos.
"""
import hashlib
import html as htmlmod
import json
import logging
import re
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
        raise ProveedorError(f"Google Places rechazó la clave ({r.status_code})", clave_invalida=True)
    if r.status_code >= 400:
        raise ProveedorError(f"Google Places respondió {r.status_code}")
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
    try:
        r = httpx.get(BRAVE_URL, params={"q": consulta, "country": "uy", "search_lang": "es", "count": 10},
                      headers={"X-Subscription-Token": k, "Accept": "application/json"}, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise ProveedorError(f"Brave Search no respondió ({type(e).__name__})") from e
    if r.status_code in (401, 403):
        raise ProveedorError(f"Brave Search rechazó la clave ({r.status_code})", clave_invalida=True)
    if r.status_code >= 400:
        raise ProveedorError(f"Brave Search respondió {r.status_code}")
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
    except anthropic.AuthenticationError as e:
        raise ProveedorError("Claude rechazó la clave", clave_invalida=True) from e
    except anthropic.PermissionDeniedError as e:
        raise ProveedorError("La clave de Claude no tiene permiso", clave_invalida=True) from e
    except anthropic.NotFoundError as e:
        raise ProveedorError(f"Modelo de Claude inexistente: {modelo}", clave_invalida=True) from e
    except anthropic.RateLimitError as e:
        raise ProveedorError("Claude: límite de uso, se reintenta en la próxima corrida") from e
    except anthropic.APIStatusError as e:
        raise ProveedorError(f"Claude respondió {e.status_code}") from e
    except anthropic.APIConnectionError as e:
        raise ProveedorError("Claude no respondió") from e
    ent, sal = r.usage.input_tokens, r.usage.output_tokens
    if r.stop_reason == "refusal":
        return {}, ent, sal
    texto_r = next((b.text for b in r.content if b.type == "text"), "")
    try:
        return json.loads(texto_r), ent, sal
    except json.JSONDecodeError:
        return {}, ent, sal


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
