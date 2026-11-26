"""Excel de «3 · Tamaño por estrato y reemplazos» (SPEC_muestras_marco_excel_sistematico, R2; D56).

Descarga: una hoja «Tamaños» con una fila por estrato (total, sorteables, no sorteables, titulares y reemplazos
editables, «¿Alcanza?» y un tamaño proporcional sugerido, con fórmulas), una hoja «Instrucciones» y una oculta
«_meta» (estudio, muestra, versión y un hash de los filtros y estratos). La hoja «Tamaños» queda protegida sin
contraseña, con solo Titulares y Reemplazos desbloqueadas.

Importación: lee la hoja «Tamaños» por nombre de columna y devuelve los tamaños para la pantalla, sin guardar nada.
"""
import datetime as dt
import hashlib
import io
import json
import re
import unicodedata

from fastapi import HTTPException
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter

from . import criterios as crit

VERSION = 1
HOJA = "Tamaños"
COLUMNAS = ("Estrato", "Total en el marco", "Sorteables", "No sorteables", "Titulares", "Reemplazos", "¿Alcanza?",
            "Tamaño proporcional sugerido")
# Lo que define qué estratos hay: si cambia, el Excel se armó con otro marco
_CLAVES_HASH = ("filtros", "campos", "atributos", "origenes", "incluir_provisoria", "estratificar_por", "estratos_def")


def hash_criterios(c: dict) -> str:
    base = {k: c.get(k) for k in _CLAVES_HASH if c.get(k)}
    return hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()[:40] or "x"


def nombre_archivo(estudio: str | None, muestra: str | None) -> str:
    return f"tamanos_{_slug(estudio or 'template')}_{_slug(muestra) if muestra else 'nueva'}_{dt.date.today():%Y%m%d}.xlsx"


def armar(estratos: list[dict], criterios: dict, tamanos: dict[str, tuple[int, int]], meta: dict,
          resumen_criterios: list[str]) -> bytes:
    """estratos: [{estrato, total, sorteables, no_sorteables}] en el orden de la pantalla.
    tamanos: {estrato: (titulares, reemplazos)} cargados en ese momento."""
    wb = Workbook()
    ws = wb.active
    ws.title = HOJA
    negrita = Font(bold=True)
    gris = PatternFill("solid", fgColor="F2F2F2")
    editable = PatternFill("solid", fgColor="FFF4D6")
    ws.append(list(COLUMNAS))
    for c in ws[1]:
        c.font, c.fill = negrita, gris
        c.alignment = Alignment(wrap_text=True, vertical="center")
    n = len(estratos)
    ultima = n + 1
    tot = ultima + 1
    for i, e in enumerate(estratos, start=2):
        t, r = tamanos.get(e["estrato"], (None, None))
        ws.append([e["estrato"], e.get("total", 0), e.get("sorteables", 0), None, t, r, None, None])
        ws.cell(i, 4, f"=B{i}-C{i}")
        ws.cell(i, 7, f'=IF(N(E{i})+N(F{i})<=C{i},"Sí","Faltan "&(N(E{i})+N(F{i})-C{i}))')
        ws.cell(i, 8, f"=IF($C${tot}=0,0,ROUND(C{i}/$C${tot}*$E${tot},0))")
        for col in (5, 6):
            ws.cell(i, col).protection = Protection(locked=False)
            ws.cell(i, col).fill = editable
            ws.cell(i, col).number_format = "0"
    ws.cell(tot, 1, "Total").font = negrita
    for col in (2, 3, 4, 5, 6):
        letra = get_column_letter(col)
        ws.cell(tot, col, f"=SUM({letra}2:{letra}{ultima})" if n else 0).font = negrita
    ws.cell(tot, 7, f'=IF(E{tot}+F{tot}<=C{tot},"Sí","Faltan "&(E{tot}+F{tot}-C{tot}))' if n else "").font = negrita
    for col, ancho in zip("ABCDEFGH", (42, 12, 12, 13, 12, 13, 14, 16)):
        ws.column_dimensions[col].width = ancho
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "B2"
    # Protegida sin contraseña: no se rompe la columna Estrato sin querer, pero quien sabe la puede desproteger
    ws.protection.sheet = True
    ws.protection.formatColumns = False
    ws.protection.formatRows = False

    ins = wb.create_sheet("Instrucciones")
    lineas = [
        ("Tamaño por estrato y reemplazos", True),
        ("", False),
        ("Completá las columnas Titulares y Reemplazos (en amarillo) de la hoja «Tamaños». Podés usar fórmulas.", False),
        ("No agregues, borres ni renombres estratos: la columna Estrato es la clave con la que se importa.", False),
        ("Una celda vacía cuenta como 0. Los valores tienen que ser enteros, sin decimales ni signo negativo.", False),
        ("«¿Alcanza?» compara titulares + reemplazos con las sorteables del estrato.", False),
        ("«Tamaño proporcional sugerido» reparte el total de titulares en proporción a las sorteables (solo ayuda).", False),
        ("Después, en la pantalla, tocá «Importar Excel» y guardá: importar no guarda nada.", False),
        ("La hoja está protegida sin contraseña (Revisar → Desproteger hoja) para no romper los estratos sin querer.", False),
        ("", False),
        ("Criterios del marco", True),
        *[(x, False) for x in resumen_criterios],
        ("", False),
        (f"Método de sorteo: {crit.METODOS.get(criterios.get('metodo') or 'aleatorio')}", False),
        (f"Marco consultado: {dt.datetime.now():%d/%m/%Y %H:%M}", False),
    ]
    for texto, neg in lineas:
        ins.append([texto])
        if neg:
            ins.cell(ins.max_row, 1).font = Font(bold=True, size=12)
    ins.column_dimensions["A"].width = 110

    m = wb.create_sheet("_meta")
    for k, v in (("version", VERSION), ("estudio_id", meta.get("estudio_id")), ("muestra_id", meta.get("muestra_id")),
                 ("hash_criterios", hash_criterios(criterios)), ("metodo", criterios.get("metodo") or "aleatorio")):
        m.append([k, v])
    m.sheet_state = "hidden"
    wb.calculation.fullCalcOnLoad = True   # que Excel y LibreOffice calculen las fórmulas al abrir
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()


def _entero(v) -> tuple[int | None, str | None]:
    """Celda → entero ≥ 0. Vacía = 0. Devuelve (valor, error)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return 0, None
    if isinstance(v, bool):
        return None, f"«{v}» no es un número"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not v.is_integer():
            return None, f"{v} tiene decimales"
        v = int(v)
    elif isinstance(v, str) and re.fullmatch(r"\s*\d+\s*", v):
        v = int(v)
    else:
        return None, f"«{v}» no es un número entero"
    if v < 0:
        return None, f"{v} es negativo"
    return v, None


def importar(contenido: bytes, criterios: dict, estratos: list[dict]) -> dict:
    """Lee el Excel y devuelve {tamanos, avisos, errores, importados}. estratos: los del marco actual."""
    try:
        wb = load_workbook(io.BytesIO(contenido), data_only=True)
    except Exception as e:
        raise HTTPException(422, "No se pudo leer el archivo: tiene que ser un Excel (.xlsx)") from e
    if HOJA not in wb.sheetnames:
        raise HTTPException(422, f"El archivo no tiene la hoja «{HOJA}»: descargá el Excel desde el paso 3 y completalo")
    ws = wb[HOJA]
    filas = list(ws.iter_rows(values_only=True))
    if not filas:
        raise HTTPException(422, f"La hoja «{HOJA}» está vacía")
    cab = {str(c).strip().lower(): i for i, c in enumerate(filas[0]) if c is not None}
    if "estrato" not in cab:
        raise HTTPException(422, f"La hoja «{HOJA}» no tiene la columna Estrato")
    ie, it, ir = cab["estrato"], cab.get("titulares"), cab.get("reemplazos")
    if it is None and ir is None:
        raise HTTPException(422, f"La hoja «{HOJA}» no tiene las columnas Titulares ni Reemplazos")
    avisos, errores = [], []
    if "_meta" in wb.sheetnames:
        meta = {r[0]: r[1] for r in wb["_meta"].iter_rows(values_only=True) if r and r[0]}
        if meta.get("hash_criterios") and meta["hash_criterios"] != hash_criterios(criterios):
            avisos.append("El Excel se armó con otros filtros o estratos; revisá los estratos")
    sorteables = {e["estrato"]: e.get("sorteables", 0) for e in estratos}
    sistematico = (criterios.get("metodo") or "aleatorio") == "sistematico_ciiu"
    tamanos, vistos = [], set()
    for k, fila in enumerate(filas[1:], start=2):
        nombre = fila[ie] if ie < len(fila) else None
        if nombre is None or str(nombre).strip() == "":
            continue
        nombre = str(nombre).strip()
        if nombre == "Total":
            continue
        if nombre not in sorteables:
            avisos.append(f"El estrato {nombre} no está en el marco (fila {k}): se ignora")
            continue
        t, et = _entero(fila[it] if it is not None and it < len(fila) else None)
        r, er = _entero(fila[ir] if ir is not None and ir < len(fila) else None)
        if et or er:
            errores.append(f"Fila {k} ({nombre}): " + "; ".join(x for x in (et and f"titulares {et}", er and f"reemplazos {er}") if x))
            continue
        if sistematico and t == 0 and r > 0:
            errores.append(f"Fila {k} ({nombre}): con sorteo sistemático, un estrato sin titulares no puede tener reemplazos")
            continue
        if nombre in vistos:
            avisos.append(f"El estrato {nombre} aparece dos veces: vale la última fila ({k})")
            tamanos = [x for x in tamanos if x["estrato"] != nombre]
        vistos.add(nombre)
        if t + r > sorteables[nombre]:
            avisos.append(f"El estrato {nombre} no alcanza: pide {t + r} y tiene {sorteables[nombre]} sorteables")
        tamanos.append({"estrato": nombre, "n": t, "reemplazos": r})
    for e in estratos:
        if e["estrato"] not in vistos and not any(f"({e['estrato']})" in x for x in errores):
            avisos.append(f"El estrato {e['estrato']} no está en el Excel: queda con el valor de la pantalla")
    return {"tamanos": tamanos, "avisos": avisos, "errores": errores, "importados": len(tamanos)}
