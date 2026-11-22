"""Lectura de bases en .xlsx, .csv y .sav a una lista de filas (dict columna → valor)."""
import csv
import io
import os
import tempfile

from fastapi import HTTPException

from .util import texto


def leer_tabla(datos: bytes, tipo: str, avance=None) -> tuple[list[str], list[dict], dict]:
    """Devuelve (columnas, filas, metadatos). Los metadatos solo vienen para .sav. Arma la lista entera: para un
    archivo grande, iterar_tabla (D52) lo recorre sin tener todas las filas en memoria.
    avance(n): se llama cada 5.000 filas leídas (para mostrar «Leyendo el archivo… N filas»)."""
    if tipo == "sav":
        return leer_sav(datos)
    columnas, filas = iterar_tabla(datos, tipo)
    salida = []
    for f in filas:
        salida.append(f)
        if avance and len(salida) % 5000 == 0:
            avance(len(salida))
    return columnas, salida, {}


def iterar_tabla(datos: bytes, tipo: str):
    """(columnas, iterador de filas) de un .csv o un .xlsx, de a una fila (R1, D52): nunca tiene el archivo entero
    parseado en memoria. El Excel se abre en modo read_only y el CSV se recorre con un lector por líneas."""
    if tipo == "csv":
        return _csv(datos)
    if tipo == "xlsx":
        return _xlsx(datos)
    raise HTTPException(415, f"Tipo no soportado: {tipo}")


def _decodificar(datos: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return datos.decode(enc)
        except UnicodeDecodeError:
            continue
    raise HTTPException(422, "No se pudo leer la codificación del CSV")


def _csv(datos: bytes):
    txt = _decodificar(datos)
    muestra = txt[:20000]
    try:
        dialecto = csv.Sniffer().sniff(muestra, delimiters=";,\t|")
    except csv.Error:
        dialecto = csv.excel
        dialecto.delimiter = ";" if muestra.count(";") > muestra.count(",") else ","
    lector = csv.reader(io.StringIO(txt), dialecto)
    try:
        columnas = _columnas(next(lector))
    except StopIteration:
        raise HTTPException(422, "El archivo está vacío") from None

    def filas():
        for f in lector:
            if any(c.strip() for c in f):
                yield dict(zip(columnas, _rellenar(f, len(columnas))))
    return columnas, filas()


def estimar_filas(datos: bytes, tipo: str) -> int:
    """Cuántas filas tiene el archivo, sin parsearlo: los saltos de línea de un CSV, o la dimensión que declara la
    primera hoja de un Excel (si no la declara, por el tamaño). Sirve para decidir si se lee en segundo plano."""
    if tipo == "csv":
        return max(0, datos.count(b"\n") - 1)
    if tipo == "xlsx":
        import re
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(datos)) as z:
                hojas = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/") and n.endswith(".xml"))
                if hojas:
                    with z.open(hojas[0]) as h:
                        inicio = h.read(4096)
                        m = re.search(rb'<dimension ref="[A-Z]+\d+:[A-Z]+(\d+)"', inicio)
                        if m:
                            return max(0, int(m.group(1)) - 1)
                        # Sin dimensión (algunos programas no la escriben): se cuentan las filas del XML sin parsearlo
                        n, resto = inicio.count(b"<row"), inicio[-8:]
                        while bloque := h.read(1 << 20):
                            n += (resto + bloque).count(b"<row") - resto.count(b"<row")
                            resto = bloque[-8:]
                        return max(0, n - 1)
        except (zipfile.BadZipFile, KeyError, ValueError):
            pass
        return len(datos) // 50
    return 0


def _xlsx(datos: bytes):
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    except Exception as e:
        raise HTTPException(422, f"No se pudo abrir el Excel: {e}") from e
    ws = wb.worksheets[0]
    crudas = ws.iter_rows(values_only=True)
    try:
        encabezado = next(crudas)
    except StopIteration:
        wb.close()
        raise HTTPException(422, "El Excel está vacío") from None
    columnas = _columnas(["" if c is None else str(c) for c in encabezado])

    def filas():
        try:
            for f in crudas:
                if f is None or all(c is None or str(c).strip() == "" for c in f):
                    continue
                yield dict(zip(columnas, _rellenar(list(f), len(columnas))))
        finally:
            wb.close()
    return columnas, filas()


def leer_sav(datos: bytes) -> tuple[list[str], list[dict], dict]:
    """Lee un .sav con pyreadstat (códigos crudos, sin aplicar etiquetas)."""
    import pyreadstat

    fd, ruta = tempfile.mkstemp(suffix=".sav")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
        df, meta = pyreadstat.read_sav(ruta, apply_value_formats=False, user_missing=True)
    except Exception as e:
        raise HTTPException(422, f"No se pudo leer el .sav: {e}") from e
    finally:
        os.unlink(ruta)
    columnas = list(df.columns)
    filas = []
    for rec in df.to_dict(orient="records"):
        filas.append({k: _valor_sav(v) for k, v in rec.items()})
    etiquetas = dict(zip(meta.column_names, meta.column_labels or [None] * len(columnas)))
    valores = {}
    for var, nombre_set in (meta.variable_to_label or {}).items():
        valores[var] = {_clave(k): v for k, v in meta.value_labels.get(nombre_set, {}).items()}
    return columnas, filas, {"etiquetas": etiquetas, "valores": valores}


def _valor_sav(v):
    if v is None:
        return None
    if isinstance(v, float):
        if v != v:
            return None
        return int(v) if v.is_integer() else v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    s = str(v)
    return s if s.strip() else None


def _clave(k) -> str:
    """Clave de un código de valor como texto: 1.0 -> '1'."""
    if isinstance(k, float) and k.is_integer():
        k = int(k)
    return str(k)


def clave_valor(v) -> str | None:
    t = texto(v)
    return None if t is None else _clave(v if not isinstance(v, str) else t)


def _columnas(encabezado: list[str]) -> list[str]:
    vistos: dict[str, int] = {}
    cols = []
    for i, c in enumerate(encabezado):
        c = (c or "").strip() or f"columna_{i + 1}"
        if c in vistos:
            vistos[c] += 1
            c = f"{c}_{vistos[c]}"
        else:
            vistos[c] = 1
        cols.append(c)
    return cols


def _rellenar(fila: list, n: int) -> list:
    fila = list(fila)[:n]
    return fila + [None] * (n - len(fila))
