"""Configuración parametrizable y versionada (R1.12).

Cada cambio crea una versión nueva (autor, fecha, comentario). Las muestras guardan la
versión con la que se sortearon. El código nunca tiene estos valores fijos: los lee de acá.
"""
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from . import auditoria

CAMPOS_CSV = ("id_item", "tel_e164", "tel_nacional", "tel_sin_mas", "rut", "razon_social", "fantasia",
              "contacto", "contacto_cargo", "departamento", "localidad", "estrato", "link", "parte", "muestra",
              "origen_telefono")
FUSIONES = ("rut", "telefono", "razon_social", "dominio")


class Franja(BaseModel):
    nombre: str
    dias: list[int] = Field(description="1 = lunes … 7 = domingo")
    desde: str
    hasta: str

    @field_validator("desde", "hasta")
    @classmethod
    def hora(cls, v):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("hora HH:MM")
        return v

    @field_validator("dias")
    @classmethod
    def dias_ok(cls, v):
        if not v or any(d < 1 or d > 7 for d in v):
            raise ValueError("días entre 1 y 7")
        return v


class ColumnaCsv(BaseModel):
    columna: str
    campo: str

    @field_validator("campo")
    @classmethod
    def campo_ok(cls, v):
        if v not in CAMPOS_CSV:
            raise ValueError(f"campo desconocido; opciones: {', '.join(CAMPOS_CSV)}")
        return v


class CsvUcontact(BaseModel):
    separador: str = ";"
    columnas: list[ColumnaCsv]


def validar_consulta_cdr(consulta: str) -> str:
    """Consulta propia del CDR: un solo SELECT, con uno (desde) o dos (desde, hasta) %s."""
    c = consulta.strip().rstrip(";").strip()
    if not re.match(r"(?is)^select\b", c):
        raise ValueError("la consulta tiene que empezar con SELECT")
    if ";" in c:
        raise ValueError("la consulta tiene que ser una sola sentencia (sin ;)")
    n = len(re.findall(r"(?<!%)%s", c))
    if n not in (1, 2):
        raise ValueError("la consulta tiene que tener uno (desde) o dos (desde, hasta) %s")
    return c


class ConfigCdr(BaseModel):
    """Conexión a la base MySQL del CDR de uContact. La contraseña NO va acá: vive en Secret
    Manager (empresas-cdr-mysql-password), porque los parámetros se guardan en la base y se ven
    en el historial de configuración."""
    host: str = ""
    puerto: int = Field(3306, ge=1, le=65535)
    base: str = ""
    usuario: str = ""
    tabla: str = "cdr"
    consulta: str | None = None
    tls: Literal["requerido", "preferido", "desactivado"] = "preferido"
    zona_horaria: str = "America/Montevideo"
    lote_tamano: int = Field(2000, ge=1, le=20000)
    activo: bool = False

    @field_validator("host", "base", "usuario")
    @classmethod
    def sin_espacios(cls, v):
        return v.strip()

    @field_validator("tabla")
    @classmethod
    def tabla_ok(cls, v):
        if not re.fullmatch(r"[A-Za-z0-9_$]+(\.[A-Za-z0-9_$]+)?", v.strip()):
            raise ValueError("nombre de tabla inválido (letras, números, _ y $; opcionalmente base.tabla)")
        return v.strip()

    @field_validator("consulta")
    @classmethod
    def consulta_ok(cls, v):
        if v is None or not v.strip():
            return None
        return validar_consulta_cdr(v)

    @field_validator("zona_horaria")
    @classmethod
    def zona_ok(cls, v):
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"zona horaria desconocida: {v}") from e
        return v

    @model_validator(mode="after")
    def completo_si_activo(self):
        if self.activo:
            faltan = [c for c in ("host", "base", "usuario") if not getattr(self, c)]
            if faltan:
                raise ValueError(f"para activar el job del CDR faltan: {', '.join(faltan)}")
        return self


PROVEEDORES = ("google_places", "brave", "claude")
DOMINIOS_GENERICOS = ["gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "live.com", "adinet.com.uy", "vera.com.uy",
                      "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "wa.me", "whatsapp.com",
                      "google.com", "sites.google.com", "wixsite.com", "blogspot.com", "mercadolibre.com.uy",
                      "paginasamarillas.com.uy", "guiamovil.com.uy", "ancel.com.uy"]
DIRECTORIOS = ["facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "youtube.com", "tiktok.com",
               "wa.me", "whatsapp.com", "google.com", "maps.google.com", "mercadolibre.com.uy", "paginasamarillas.com.uy",
               "guiamovil.com.uy", "uruguayempresas.com", "empresasuruguay.com.uy", "infoisinfo.com.uy", "cylex.com.uy",
               "dateas.com", "tuugo.com.uy", "foursquare.com", "tripadvisor.com", "wikipedia.org", "dnb.com", "bps.gub.uy",
               "dgi.gub.uy", "gub.uy"]


class ConfigEnriquecimiento(BaseModel):
    """B1 (SPEC_fase2_enriquecimiento). Las claves de API NO van acá: viven en Secret Manager (una por proveedor)."""
    google_places_activo: bool = True
    brave_activo: bool = True
    claude_activo: bool = True
    # Precios unitarios (verificados el 17/11/2026; se actualizan a mano si el proveedor cambia precios)
    precio_places: float = Field(0.035, ge=0, le=10)          # US$ por llamada Text Search Enterprise
    places_gratis_mes: int = Field(1000, ge=0, le=1_000_000)  # llamadas sin costo por mes
    precio_brave: float = Field(0.005, ge=0, le=10)           # US$ por búsqueda
    modelo_claude: str = "claude-haiku-5-5"
    precio_claude_entrada: float = Field(0.10, ge=0, le=1000)  # US$ por millón de tokens
    precio_claude_salida: float = Field(0.50, ge=0, le=1000)
    tokens_entrada_estimados: int = Field(6000, ge=100, le=200_000)
    tokens_salida_estimados: int = Field(400, ge=10, le=20_000)
    # Topes
    tope_mensual: float = Field(100.0, ge=0, le=100_000)
    tope_corrida: float = Field(20.0, ge=0, le=100_000)
    max_empresas_corrida: int = Field(2000, ge=1, le=100_000)
    # Datos que entran: confianza baja (cargas 50, sala 80) para no pisar datos de mejor fuente
    confianza: int = Field(30, ge=1, le=100)
    dias_sin_reenriquecer: int = Field(90, ge=0, le=3650)
    # Q1: «telefono» corta la cascada apenas hay un teléfono; «telefono_y_web» sigue hasta tener los dos
    corte: Literal["telefono", "telefono_y_web"] = "telefono"
    similitud_places: float = Field(0.6, ge=0.1, le=1.0)
    tasa_exito_places: float = Field(0.6, ge=0, le=1)          # mientras no haya historia
    max_paginas_descubrimiento: int = Field(3, ge=1, le=3)
    directorios: list[str] = Field(default_factory=lambda: list(DIRECTORIOS))

    @field_validator("modelo_claude")
    @classmethod
    def modelo_ok(cls, v):
        v = v.strip()
        if not re.fullmatch(r"claude-[a-z0-9.\-]+", v):
            raise ValueError("modelo de Claude inválido (por ejemplo claude-haiku-5-5)")
        return v

    @model_validator(mode="after")
    def topes_ok(self):
        if self.tope_corrida > self.tope_mensual:
            raise ValueError("el tope por corrida no puede ser mayor que el tope mensual")
        return self


def enriquecimiento(parametros: dict) -> dict:
    """Bloque enriquecimiento de una versión de configuración, con los valores por defecto."""
    return ConfigEnriquecimiento.model_validate(parametros.get("enriquecimiento") or {}).model_dump()


class ConfigCargas(BaseModel):
    """Cargas por lotes (D50): cada lote es una transacción y un paso de la tarea."""
    tamano_lote: int = Field(5000, ge=500, le=20000)
    pausa_segundos: float = Field(1.0, ge=0, le=60)       # respiro para la base entre lote y lote
    minutos_trabada: int = Field(10, ge=5, le=240)        # sin latido más que esto: se retoma sola una vez (D52)


def cargas(parametros: dict) -> dict:
    """Bloque cargas de una versión de configuración, con los valores por defecto. En los tests, CARGAS_TAMANO_LOTE y
    CARGAS_PAUSA fuerzan lotes chicos y sin pausa (para que toda carga tenga varios lotes)."""
    from . import settings

    c = ConfigCargas.model_validate(parametros.get("cargas") or {}).model_dump()
    if settings.CARGAS_TAMANO_LOTE:
        c["tamano_lote"] = settings.CARGAS_TAMANO_LOTE
    if settings.CARGAS_PAUSA is not None:
        c["pausa_segundos"] = settings.CARGAS_PAUSA
    return c


def cdr(parametros: dict) -> dict:
    """Bloque cdr de una versión de configuración, con los valores por defecto (las versiones
    anteriores a este cambio no lo tienen)."""
    return ConfigCdr.model_validate(parametros.get("cdr") or {}).model_dump()


class Parametros(BaseModel):
    umbral_intermediario: int = Field(ge=2, le=100)
    meses_enfriamiento: int = Field(ge=0, le=120)
    reglas_disponibilidad: dict[str, bool]
    naturalezas_excluidas: list[str]
    reglas_fusion: list[str]
    confianza_fuentes: dict[str, int]
    destinos_internos: list[str]
    prefijos_salida: list[str] = []
    # SPEC_mejoras_sav_contactos: similitud para sugerir atributos parecidos (F4.1), contactos por
    # empresa en el CSV de uContact (F5.1) y umbral por defecto de las reglas de fusión flexibles (F6.2)
    umbral_similitud_atributos: float = Field(0.6, ge=0.3, le=1.0)
    contactos_por_empresa_csv: int = Field(3, ge=0, le=10)
    umbral_fusion_flexible: float = Field(0.85, ge=0.5, le=1.0)
    franjas: list[Franja]
    contacto_efectivo: list[str]
    csv_ucontact: CsvUcontact
    cdr: ConfigCdr = Field(default_factory=ConfigCdr)
    # SPEC_fase2_enriquecimiento: enriquecimiento (B1) y dominios que no cuentan como «mismo sitio» en los duplicados (B4)
    enriquecimiento: ConfigEnriquecimiento = Field(default_factory=ConfigEnriquecimiento)
    dominios_genericos: list[str] = Field(default_factory=lambda: list(DOMINIOS_GENERICOS))
    cargas: ConfigCargas = Field(default_factory=ConfigCargas)

    @field_validator("reglas_disponibilidad")
    @classmethod
    def reglas_ok(cls, v):
        validas = {"enfriamiento", "muestra_activa", "sin_telefono_discable"}
        extra = set(v) - validas
        if extra:
            raise ValueError(f"reglas desconocidas: {', '.join(sorted(extra))}. "
                             "La exclusión por naturaleza y no llamar están siempre activas.")
        return v

    @field_validator("reglas_fusion")
    @classmethod
    def fusion_ok(cls, v):
        if "rut" not in v or any(x not in FUSIONES for x in v):
            raise ValueError(f"reglas de fusión posibles: {', '.join(FUSIONES)} (rut es obligatoria)")
        return v

    @field_validator("destinos_internos")
    @classmethod
    def regex_ok(cls, v):
        for p in v:
            if p.startswith("^"):
                try:
                    re.compile(p)
                except re.error as e:
                    raise ValueError(f"patrón inválido {p!r}: {e}") from e
        return v

    @field_validator("contacto_efectivo")
    @classmethod
    def efectivo_ok(cls, v):
        validos = {"completa", "parcial", "rechazo"}
        if any(x not in validos for x in v):
            raise ValueError("contacto efectivo: completa, parcial, rechazo")
        return v


def vigente(conn) -> tuple[int, dict]:
    r = conn.execute("SELECT version, parametros FROM config_version ORDER BY version DESC LIMIT 1").fetchone()
    return r["version"], r["parametros"]


def obtener(conn, version: int) -> dict:
    r = conn.execute("SELECT parametros FROM config_version WHERE version = %s", (version,)).fetchone()
    if r is None:
        raise HTTPException(404, f"No existe la versión de configuración {version}")
    return r["parametros"]


def validar(parametros: dict) -> dict:
    try:
        return Parametros.model_validate(parametros).model_dump()
    except ValidationError as e:
        errores = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())
        raise HTTPException(422, f"Configuración inválida: {errores}") from e


def guardar(conn, parametros: dict, autor: str, comentario: str | None = None) -> int:
    limpios = validar(parametros)
    codigos = {r["codigo"] for r in conn.execute("SELECT codigo FROM naturaleza_juridica")}
    faltan = set(limpios["naturalezas_excluidas"]) - codigos
    if faltan:
        raise HTTPException(422, f"Naturalezas inexistentes en el catálogo: {', '.join(sorted(faltan))}")
    _, anterior = vigente(conn)
    version = conn.execute(
        "INSERT INTO config_version (parametros, autor, comentario) VALUES (%s, %s, %s) RETURNING version",
        (Jsonb(limpios), autor, comentario),
    ).fetchone()["version"]
    # Espejo del flag en el catálogo (la fuente de verdad versionada es la config).
    conn.execute("UPDATE naturaleza_juridica SET excluida = (codigo = ANY(%s))", (limpios["naturalezas_excluidas"],))
    cambios = {k: {"antes": anterior.get(k), "despues": v} for k, v in limpios.items() if anterior.get(k) != v}
    auditoria.registrar(conn, autor, "config.cambiar", "config_version", version,
                        {"comentario": comentario, "cambios": cambios})
    return version


def historial(conn) -> list[dict]:
    return conn.execute(
        "SELECT version, autor, comentario, fecha FROM config_version ORDER BY version DESC"
    ).fetchall()
