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
