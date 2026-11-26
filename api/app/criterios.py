"""Criterios del sorteo: filtros y estratos con todos los datos de la empresa (SPEC_templates_sorteo, R4; D44).

Datos disponibles:
- campos fijos de la empresa (razón social, fantasía, naturaleza, CIIU completo / 2 / 1 dígitos, tamaño,
  departamento, localidad, dirección, web y estado);
- todos los atributos de empresa activos, de cualquier tipo. Nunca los de contacto.

Filtros según el tipo: lista (una o varias opciones); texto («contiene», «es uno de» sin mayúsculas ni
tildes, «tiene dato» / «no tiene dato»); número y fecha (desde / hasta). Cada filtro puede «incluir
empresas sin dato». Se combinan con «y».

Estratos según el tipo: lista (uno por opción); texto (uno por valor normalizado, con «Otros» opcional);
número (tramos que define el usuario); fecha (año, semestre o tramos). Sin dato: «(sin dato)».
Las reglas (tramos, agrupamientos) quedan en los criterios; el estrato de cada empresa se congela en el
snapshot al sortear, así que Verificar reproducibilidad no depende de cambios posteriores.
"""
import datetime as dt
import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from . import catalogos

SIN_DATO = "(sin dato)"
OTROS = "Otros"
PREFIJO = catalogos.PREFIJO
TIPOS = ("lista", "texto", "numero", "fecha")
MAX_VALORES_TEXTO = 30
MAX_ESTRATOS = 200
_TILDES = str.maketrans("áéíóúüñàèìòùâêîôûäëïö", "aeiouunaeiouaeiouaeio")

# clave → (nombre, tipo, expresión SQL sobre empresa e y naturaleza_juridica n)
CAMPOS = {
    "razon_social": ("Razón social", "texto", "e.razon_social"),
    "fantasia": ("Nombre de fantasía", "texto", "e.fantasia"),
    "naturaleza": ("Naturaleza jurídica", "lista", "n.codigo"),
    "ciiu": ("CIIU", "texto", "e.ciiu"),
    "ciiu2": ("CIIU a 2 dígitos", "lista", "nullif(left(e.ciiu, 2), '')"),
    "ciiu1": ("CIIU a 1 dígito", "lista", "nullif(left(e.ciiu, 1), '')"),
    "tamano": ("Tamaño", "lista", "e.tamano"),
    "departamento": ("Departamento", "lista", "e.departamento"),
    "localidad": ("Localidad", "texto", "e.localidad"),
    "direccion": ("Dirección", "texto", "e.direccion"),
    "web": ("Web", "texto", "e.web"),
    "estado": ("Estado", "lista", "e.estado"),
}
ESTADOS_EMPRESA = ["activa", "cerrada", "desconocida"]
# Formato anterior de filtros (listas de valores y prefijos de CIIU): se sigue aceptando
FILTROS_LEGADO = ("ciiu", "tamano", "departamento", "naturaleza")


def norm_txt(s) -> str | None:
    """Igual que la función SQL norm_txt (migración 0012): sin mayúsculas, tildes ni espacios de más."""
    if s is None:
        return None
    t = " ".join(str(s).strip().lower().translate(_TILDES).split())
    return t or None


def definiciones(conn) -> dict[str, dict]:
    """Los datos que se pueden usar como filtro o estrato: {clave: {nombre, tipo, opciones, sql | atributo_id}}."""
    out = {k: {"clave": k, "nombre": n, "tipo": t, "sql": s, "grupo": "campo",
               "opciones": ESTADOS_EMPRESA if k == "estado" else None} for k, (n, t, s) in CAMPOS.items()}
    for a in catalogos.atributos(conn, True, "empresa"):
        if a["fusionado_en"]:
            continue
        out[PREFIJO + a["clave"]] = {"clave": PREFIJO + a["clave"], "nombre": a["nombre"], "tipo": a["tipo"],
                                     "atributo_id": a["id"], "grupo": "atributo",
                                     "opciones": a["opciones"] if a["tipo"] == "lista" else None}
    return out


# ─────────────────────────────────────────────────────────────
# Validación
# ─────────────────────────────────────────────────────────────

def _numero(v, nombre):
    try:
        return Decimal(str(v).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise HTTPException(422, f"{nombre}: «{v}» no es un número válido") from None


def _fecha(v, nombre):
    try:
        return dt.date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        raise HTTPException(422, f"{nombre}: «{v}» no es una fecha válida (aaaa-mm-dd)") from None


def _texto_num(d: Decimal) -> str:
    return format(d.normalize(), "f")


def validar_filtro(meta: dict, spec) -> dict | None:
    """Normaliza el filtro de un dato según su tipo. None: no filtra."""
    s = spec or {}
    if isinstance(s, list):  # formato anterior: lista de valores
        s = {"valores": s}
    nombre, tipo = meta["nombre"], meta["tipo"]
    out = {}
    if s.get("tiene_dato") is not None:
        out["tiene_dato"] = bool(s["tiene_dato"])
        return out
    if tipo == "lista":
        valores = [str(v) for v in (s.get("valores") or []) if str(v).strip()]
        if meta.get("opciones") is not None:
            fuera = set(valores) - set(meta["opciones"])
            if fuera:
                raise HTTPException(422, f"{nombre}: valores que no son opciones: {', '.join(sorted(fuera))}")
        if valores:
            out["valores"] = valores
    elif tipo == "texto":
        if str(s.get("contiene") or "").strip():
            out["contiene"] = str(s["contiene"]).strip()
        valores = [str(v).strip() for v in (s.get("valores") or []) if norm_txt(v)]
        if valores:
            out["valores"] = valores
    else:
        for k in ("desde", "hasta"):
            v = s.get(k)
            if v in (None, ""):
                continue
            out[k] = _texto_num(_numero(v, nombre)) if tipo == "numero" else _fecha(v, nombre).isoformat()
    if not out:
        return None
    if s.get("incluir_sin_dato"):
        out["incluir_sin_dato"] = True
    return out


def validar_estrato(meta: dict, d) -> dict | None:
    """Regla de un estrato: tramos para números, año/semestre/tramos para fechas, «Otros» para textos."""
    d = d or {}
    nombre, tipo = meta["nombre"], meta["tipo"]
    if tipo == "numero":
        cortes = sorted({_numero(c, nombre) for c in (d.get("cortes") or []) if str(c).strip() != ""})
        if not cortes:
            raise HTTPException(422, f"Definí los tramos de {nombre} (por ejemplo 1, 5, 20, 100)")
        return {"cortes": [_texto_num(c) for c in cortes]}
    if tipo == "fecha":
        por = d.get("por") or "anio"
        if por not in ("anio", "semestre", "tramos"):
            raise HTTPException(422, f"{nombre}: estratificar por año, semestre o tramos")
        if por == "tramos":
            cortes = sorted({_fecha(c, nombre) for c in (d.get("cortes") or []) if str(c).strip()})
            if not cortes:
                raise HTTPException(422, f"Definí los tramos de fechas de {nombre}")
            return {"por": "tramos", "cortes": [c.isoformat() for c in cortes]}
        return {"por": por}
    if tipo == "texto" and d.get("agrupar"):
        if d["agrupar"] not in ("min", "top"):
            raise HTTPException(422, f"{nombre}: agrupar «min» (menos de N empresas) o «top» (los N más frecuentes)")
        try:
            n = int(d.get("n") or 0)
        except (TypeError, ValueError):
            n = 0
        if n < 1:
            raise HTTPException(422, f"{nombre}: indicá N para agrupar en «Otros»")
        return {"agrupar": d["agrupar"], "n": n}
    return None


AVISO_SIN_TELEFONO = 'La opción "Incluir empresas sin teléfono" ya no existe: las empresas sin teléfono no se sortean'
METODOS = {"aleatorio": "Aleatorio simple", "sistematico_ciiu": "Sistemático por CIIU"}
ORDEN_SISTEMATICO = ("ciiu",)   # P2: otras variables de orden


def validar(conn, c: dict, avisos: list | None = None, tamanos: bool = True) -> dict:
    """Valida y normaliza los criterios. Con avisos (aplicar un template), lo que ya no existe se saca y se
    avisa en lugar de rechazar. tamanos=False: el paso 3 puede faltar (template parcial)."""
    c = dict(c or {})
    defs = definiciones(conn)
    todos_attr = {a["clave"]: a for a in catalogos.atributos(conn)}

    def problema(msg):
        if avisos is None:
            raise HTTPException(422, msg)
        avisos.append(msg)

    filtros = {}
    for k, v in (c.get("filtros") or {}).items():
        if not v:
            continue
        if k not in FILTROS_LEGADO:
            problema(f"Filtro desconocido: {k}")
            continue
        filtros[k] = v
    campos = {}
    for k, spec in (c.get("campos") or {}).items():
        if k not in CAMPOS:
            problema(f"Dato desconocido para filtrar: {k}")
            continue
        f = validar_filtro(defs[k], spec)
        if f:
            campos[k] = f
    atributos = {}
    for clave, spec in (c.get("atributos") or {}).items():
        meta = defs.get(PREFIJO + clave)
        if meta is None:
            a = todos_attr.get(clave)
            if a is not None and a["ambito"] == "contacto":
                problema(f"Los atributos de contacto no se usan para filtrar: {a['nombre']}")
            elif a is not None:
                problema(f"Se quitó el filtro por {a['nombre']}: el atributo ya no está activo")
            else:
                problema(f"Se quitó el filtro por {clave}: el atributo no existe")
            continue
        try:
            f = validar_filtro(meta, spec)
        except HTTPException as e:
            if avisos is None:
                raise
            avisos.append(f"Se quitó el filtro por {meta['nombre']}: {e.detail}")
            continue
        if f:
            atributos[clave] = f
    origenes = sorted({o for o in (c.get("origenes") or []) if o})
    if origenes:
        conocidos = {o["codigo"] for o in catalogos.origenes(conn)}
        for o in sorted(set(origenes) - conocidos):
            problema(f"Se quitó el origen {o}: ya no existe")
        origenes = [o for o in origenes if o in conocidos]
    por, estratos_def = [], {}
    for k in c.get("estratificar_por") or []:
        meta = defs.get(k)
        if meta is None:
            a = todos_attr.get(k[len(PREFIJO):]) if k.startswith(PREFIJO) else None
            if a is not None and a["ambito"] == "contacto":
                problema(f"Los atributos de contacto no se usan para estratificar: {a['nombre']}")
            elif a is not None:
                problema(f"Se quitó el estrato por {a['nombre']}: el atributo ya no está activo")
            else:
                problema(f"No se puede estratificar por {k}")
            continue
        try:
            d = validar_estrato(meta, (c.get("estratos_def") or {}).get(k))
        except HTTPException as e:
            if avisos is None:
                raise
            avisos.append(f"Se quitó el estrato por {meta['nombre']}: {e.detail}")
            continue
        if k not in por:
            por.append(k)
        if d:
            estratos_def[k] = d
    metodo = c.get("metodo") or "aleatorio"
    if metodo not in METODOS:
        problema(f"Método de sorteo desconocido: {metodo}")
        metodo = "aleatorio"
    estratos = c.get("estratos") or []
    for e in estratos:
        if int(e.get("n", 0)) < 0 or int(e.get("reemplazos", 0)) < 0:
            raise HTTPException(422, "Tamaños y reemplazos no pueden ser negativos")
    if metodo == "sistematico_ciiu":   # D56: el reemplazo es el vecino de un titular
        sin_tit = [e["estrato"] for e in estratos if int(e.get("n", 0)) == 0 and int(e.get("reemplazos", 0)) > 0]
        if c.get("n_por_estrato") is not None and not estratos and int(c.get("n_por_estrato") or 0) == 0 \
                and int(c.get("reemplazos_por_estrato") or 0) > 0:
            sin_tit = ["todos"]
        if sin_tit:
            raise HTTPException(422, "Con sorteo sistemático, un estrato sin titulares no puede tener reemplazos"
                                     f" ({', '.join(sin_tit[:5])}{'…' if len(sin_tit) > 5 else ''})")
    if tamanos and not estratos and c.get("n_por_estrato") is None:
        raise HTTPException(422, "Indicá el tamaño por estrato (lista de estratos o n_por_estrato)")
    salida = {"filtros": filtros, "atributos": atributos, "origenes": origenes, "estratificar_por": por,
              "estratos": estratos, "n_por_estrato": c.get("n_por_estrato"),
              "reemplazos_por_estrato": c.get("reemplazos_por_estrato", 0)}
    # Las claves nuevas se guardan solo si se usan: los criterios de las muestras viejas no cambian
    if campos:
        salida["campos"] = campos
    if estratos_def:
        salida["estratos_def"] = estratos_def
    if c.get("estratos_descartados"):
        salida["estratos_descartados"] = sorted({str(x) for x in c["estratos_descartados"]})
    if c.get("incluir_provisoria"):  # F6.1 (Q2): desmarcado por defecto
        salida["incluir_provisoria"] = True
    if c.get("incluir_sin_telefono") and avisos is not None:  # D56: la opción se eliminó; se descarta con aviso
        avisos.append(AVISO_SIN_TELEFONO)
    if metodo != "aleatorio":   # sin la clave, aleatorio: los criterios de las muestras viejas no cambian
        salida["metodo"] = metodo
        salida["orden_sistematico"] = list(ORDEN_SISTEMATICO)
    if c.get("una_por_grupo"):  # Fase 2, B4 (Q3): la pantalla la trae marcada; sin la clave, como antes
        salida["una_por_grupo"] = True
    return salida


# ─────────────────────────────────────────────────────────────
# SQL del universo
# ─────────────────────────────────────────────────────────────

class Consulta:
    """Arma el SELECT del universo: columnas de estrato, joins por atributo y condiciones de filtro."""

    def __init__(self, defs: dict):
        self.defs = defs
        self.joins: dict[str, str] = {}

    def expr(self, clave: str) -> str:
        m = self.defs[clave]
        if "sql" in m:
            return m["sql"]
        alias = f"xa{int(m['atributo_id'])}"
        self.joins[alias] = (f"LEFT JOIN empresa_atributo {alias} ON {alias}.empresa_id = e.id"
                             f" AND {alias}.atributo_id = {int(m['atributo_id'])}")
        col = {"numero": "valor_numero", "fecha": "valor_fecha"}.get(m["tipo"], "valor_texto")
        return f"{alias}.{col}"

    def condicion(self, clave: str, spec: dict, args: list) -> str:
        m = self.defs[clave]
        x = self.expr(clave)
        vacio = f"({x} IS NULL OR {x}::text = '')"
        if "tiene_dato" in spec:
            return f"NOT {vacio}" if spec["tiene_dato"] else vacio
        partes = []
        if "valores" in spec:
            if m["tipo"] == "texto":
                partes.append(f"norm_txt({x}) = ANY(%s)")
                args.append([norm_txt(v) for v in spec["valores"]])
            else:
                partes.append(f"{x} = ANY(%s)")
                args.append(spec["valores"])
        if "contiene" in spec:
            partes.append(f"{x} ILIKE %s")
            args.append(f"%{spec['contiene']}%")
        cast = "numeric" if m["tipo"] == "numero" else "date"
        if "desde" in spec:
            partes.append(f"{x} >= %s::{cast}")
            args.append(spec["desde"])
        if "hasta" in spec:
            partes.append(f"{x} <= %s::{cast}")
            args.append(spec["hasta"])
        cond = " AND ".join(partes) or "TRUE"
        if spec.get("incluir_sin_dato"):
            cond = f"(({cond}) OR {vacio})"
        return f"({cond})"


# ─────────────────────────────────────────────────────────────
# Estratos
# ─────────────────────────────────────────────────────────────

def _fmt(d: Decimal) -> str:
    return _texto_num(d)


def _tramo(x, cortes: list[Decimal]) -> str:
    if x < cortes[0]:
        return f"menos de {_fmt(cortes[0])}"
    enteros = all(c == c.to_integral_value() for c in cortes)
    for a, b in zip(cortes, cortes[1:]):
        if a <= x < b:
            if enteros:
                return _fmt(a) if b - 1 == a else f"{_fmt(a)}–{_fmt(b - 1)}"
            return f"{_fmt(a)} a menos de {_fmt(b)}"
    return f"{_fmt(cortes[-1])} o más"


def _tramo_fecha(x: dt.date, cortes: list[dt.date]) -> str:
    if x < cortes[0]:
        return f"antes de {cortes[0].isoformat()}"
    for a, b in zip(cortes, cortes[1:]):
        if a <= x < b:
            return f"{a.isoformat()} a {(b - dt.timedelta(days=1)).isoformat()}"
    return f"{cortes[-1].isoformat()} en adelante"


def _etiquetas_texto(valores: list, regla: dict | None) -> dict:
    """norm → etiqueta (la forma más frecuente), con «Otros» según la regla de agrupamiento."""
    cuenta, formas = Counter(), {}
    for v in valores:
        n = norm_txt(v)
        if n is None:
            continue
        cuenta[n] += 1
        formas.setdefault(n, Counter())[str(v).strip()] += 1
    # La forma más frecuente; a igual frecuencia, la que no está toda en mayúsculas, y después la primera en orden
    etiqueta = {n: sorted(f.items(), key=lambda kv: (-kv[1], kv[0].isupper(), kv[0]))[0][0] for n, f in formas.items()}
    if regla and regla.get("agrupar") == "min":
        for n, k in cuenta.items():
            if k < regla["n"]:
                etiqueta[n] = OTROS
    elif regla and regla.get("agrupar") == "top":
        top = {n for n, _ in sorted(cuenta.items(), key=lambda kv: (-kv[1], etiqueta[kv[0]]))[: regla["n"]]}
        for n in cuenta:
            if n not in top:
                etiqueta[n] = OTROS
    return etiqueta


def etiquetas(filas: list[dict], criterios: dict, defs: dict) -> list[str]:
    """El estrato de cada fila del marco. Los textos se agrupan sobre el marco que se sortea."""
    por = criterios.get("estratificar_por") or []
    if not por:
        return ["Total"] * len(filas)
    reglas = criterios.get("estratos_def") or {}
    columnas = []
    for k in por:
        m = defs[k]
        col = [f.get(f"e:{k}") for f in filas]
        regla = reglas.get(k)
        if m["tipo"] == "texto":
            mapa = _etiquetas_texto(col, regla)
            columnas.append([mapa.get(norm_txt(v), SIN_DATO) if norm_txt(v) else SIN_DATO for v in col])
        elif m["tipo"] == "numero":
            cortes = [Decimal(x) for x in regla["cortes"]]
            columnas.append([SIN_DATO if v is None else _tramo(Decimal(v), cortes) for v in col])
        elif m["tipo"] == "fecha":
            regla = regla or {"por": "anio"}
            if regla["por"] == "anio":
                columnas.append([SIN_DATO if v is None else str(v.year) for v in col])
            elif regla["por"] == "semestre":
                columnas.append([SIN_DATO if v is None else f"{v.year} S{1 if v.month <= 6 else 2}" for v in col])
            else:
                cortes = [dt.date.fromisoformat(x) for x in regla["cortes"]]
                columnas.append([SIN_DATO if v is None else _tramo_fecha(v, cortes) for v in col])
        else:
            columnas.append([str(v) if v not in (None, "") else SIN_DATO for v in col])
    return [" | ".join(partes) for partes in zip(*columnas)]


def orden_natural(s: str):
    """Para mostrar los estratos en orden: «1–4», «5–19», «20–99», «100 o más»; «(sin dato)» y «Otros» al final."""
    base = [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]
    return (SIN_DATO in s or s.startswith(OTROS), [(0, t) if isinstance(t, int) else (1, t) for t in base])


def avisos_estratos(filas: list[dict], criterios: dict, defs: dict, n_estratos: int) -> list[str]:
    out = []
    reglas = criterios.get("estratos_def") or {}
    for k in criterios.get("estratificar_por") or []:
        if defs[k]["tipo"] == "texto" and not reglas.get(k):
            n = len({norm_txt(f.get(f"e:{k}")) for f in filas} - {None})
            if n > MAX_VALORES_TEXTO:
                out.append(f"{defs[k]['nombre']} tiene {n} valores distintos: conviene agrupar en «Otros» los valores con "
                           f"menos de N empresas o quedarse con los N más frecuentes")
    if n_estratos > MAX_ESTRATOS:
        out.append(f"La combinación da {n_estratos} estratos (más de {MAX_ESTRATOS}): revisá si hace falta tanto detalle")
    return out
