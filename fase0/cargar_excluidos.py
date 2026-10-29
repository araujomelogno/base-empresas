"""Catálogo inicial de naturalezas jurídicas excluidas, desde la hoja "excluidos" (R1.4).

Lee la hoja del Excel de referencia, detecta las columnas de código y nombre (si no hay
código, lo toma del catálogo base del seed por nombre o lo arma con las iniciales) y:
  a) escribe fase0/salida/naturalezas_excluidas.sql con INSERT … ON CONFLICT en
     empresas.naturaleza_juridica (codigo, nombre);
  b) opcionalmente llama a la API: POST {API}/api/naturalezas {codigo, nombre, excluida: true}.

La marca de exclusión vive en la configuración versionada (naturalezas_excluidas, R1.12): el
SQL solo carga el catálogo; la exclusión se fija por la API, que crea la versión de config.

    python fase0/cargar_excluidos.py referencia.xlsx [--hoja excluidos] [--api URL --token T | --dev-user email]
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import comun
from comun import norm, texto

PALABRAS_VACIAS = {"de", "del", "la", "el", "los", "las", "u", "o", "y", "e", "en", "por", "con", "a"}
SI = {"si", "sí", "s", "x", "1", "true", "verdadero", "excluida", "excluido", "yes"}


def catalogo_seed() -> dict[str, str]:
    """Nombre normalizado → código, desde el INSERT de naturalezas de 0003_seed.sql."""
    try:
        sql = comun.SEED_SQL.read_text(encoding="utf-8")
    except OSError:
        return {}
    bloque = sql.split("INSERT INTO naturaleza_juridica", 1)[-1].split(";", 1)[0]
    return {norm(n): c for c, n in re.findall(r"\('([^']+)',\s*'([^']+)'\)", bloque)}


def codigo_desde_nombre(nombre: str, usados: set) -> str:
    palabras = [p for p in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+", nombre) if p.lower() not in PALABRAS_VACIAS]
    base = "".join(comun.norm(p)[0] for p in palabras if comun.norm(p)).upper()[:6] or "NAT"
    if len(base) < 2 and palabras:
        base = comun.norm(palabras[0]).upper()[:6]
    codigo, i = base, 2
    while codigo in usados:
        codigo, i = f"{base[:5]}{i}", i + 1
    return codigo


def leer_excluidos(ruta, hoja="excluidos", col_codigo=None, col_nombre=None, col_excluida=None) -> list[dict]:
    columnas, filas, _ = comun.leer(ruta, hoja if comun.tipo_archivo(ruta) == "xlsx" else None)
    c_cod = comun.exigir_columna(columnas, col_codigo, hoja) if col_codigo else \
        comun.buscar_columna(columnas, ["codigo", "código", "cod", "sigla", "abreviatura", "abrev"], contiene=True)
    c_nom = comun.exigir_columna(columnas, col_nombre, hoja) if col_nombre else \
        comun.buscar_columna(columnas, ["naturaleza_juridica", "naturaleza", "nombre", "descripcion", "denominacion",
                                        "forma_juridica", "tipo"], contiene=True)
    c_exc = comun.exigir_columna(columnas, col_excluida, hoja) if col_excluida else \
        comun.buscar_columna(columnas, ["excluida", "excluido", "excluir"], contiene=True)
    if c_nom is None or c_nom == c_cod:
        # Sin encabezados reconocibles: la columna de texto más larga es el nombre
        textos = [c for c in columnas if c != c_cod and any(texto(f.get(c)) for f in filas)]
        if not textos:
            raise comun.ErrorFase0(f"Hoja '{hoja}': no se encontró la columna con el nombre de la naturaleza")
        c_nom = max(textos, key=lambda c: sum(len(texto(f.get(c)) or "") for f in filas))
    seed = catalogo_seed()
    usados = set()
    salida = []
    for f in filas:
        nombre = texto(f.get(c_nom))
        if not nombre:
            continue
        codigo = (texto(f.get(c_cod)) or "").upper() if c_cod else ""
        origen = "hoja"
        if not codigo:
            codigo = seed.get(norm(nombre))
            origen = "catálogo base" if codigo else "generado"
            codigo = codigo or codigo_desde_nombre(nombre, usados | set(seed.values()))
        excluida = True
        if c_exc:
            excluida = (texto(f.get(c_exc)) or "").lower() in SI
        if codigo in usados:
            continue
        usados.add(codigo)
        salida.append({"codigo": codigo, "nombre": nombre, "excluida": excluida, "origen_codigo": origen})
    return salida


def _sql(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def generar_sql(filas: list[dict], origen: str) -> str:
    excl = [f["codigo"] for f in filas if f["excluida"]]
    lineas = [
        f"-- Catálogo de naturalezas jurídicas desde la hoja \"excluidos\" ({origen}).",
        "-- Generado por fase0/cargar_excluidos.py.",
        "--",
        "-- Este SQL solo carga el catálogo (código y nombre). La marca \"excluida de contacto\" NO se fija acá:",
        "-- vive en la configuración versionada (parámetro naturalezas_excluidas, R1.12) y la columna",
        "-- naturaleza_juridica.excluida se sincroniza desde ella. Fijarla por la API, que crea la versión",
        "-- de configuración con autor y fecha:",
        "--   python fase0/cargar_excluidos.py <excel> --api https://<api> --token <id token de Firebase>",
        "-- o desde la pantalla Configuración → Naturalezas.",
        f"-- Naturalezas a excluir: {', '.join(excl) or '(ninguna)'}",
        "",
        "INSERT INTO empresas.naturaleza_juridica (codigo, nombre) VALUES",
    ]
    valores = [f"  ({_sql(f['codigo'])}, {_sql(f['nombre'])})" for f in filas]
    lineas.append(",\n".join(valores))
    lineas.append("ON CONFLICT (codigo) DO UPDATE SET nombre = EXCLUDED.nombre;")
    return "\n".join(lineas) + "\n"


def enviar_api(filas: list[dict], api: str, token=None, dev_user=None, timeout=30) -> list[tuple]:
    """POST {api}/api/naturalezas por fila. Cada naturaleza excluida crea una versión de configuración."""
    url = api.rstrip("/") + "/api/naturalezas"
    cabeceras = {"Content-Type": "application/json"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    elif dev_user:
        cabeceras["X-Dev-User"] = dev_user
    else:
        raise comun.ErrorFase0("Para llamar a la API hace falta --token (Firebase) o --dev-user (modo dev)")
    resultados = []
    for f in filas:
        cuerpo = json.dumps({"codigo": f["codigo"], "nombre": f["nombre"], "excluida": f["excluida"]}).encode()
        req = urllib.request.Request(url, data=cuerpo, headers=cabeceras, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resultados.append((f["codigo"], r.status, json.loads(r.read() or b"{}")))
        except urllib.error.HTTPError as e:
            resultados.append((f["codigo"], e.code, e.read().decode("utf-8", "replace")[:300]))
        except urllib.error.URLError as e:
            resultados.append((f["codigo"], None, str(e.reason)))
    return resultados


def ejecutar(ruta, hoja="excluidos", salida=comun.SALIDA / "naturalezas_excluidas.sql", **cols) -> dict:
    filas = leer_excluidos(ruta, hoja, **cols)
    if not filas:
        raise comun.ErrorFase0(f"La hoja '{hoja}' no tiene filas con nombre")
    sql = comun.escribir(salida, generar_sql(filas, Path(ruta).name)) if salida else None
    return {"filas": filas, "sql": sql}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("excel", help="Excel de referencia (.xlsx) o .csv con la lista")
    p.add_argument("--hoja", default="excluidos", help="Nombre de la hoja (defecto: excluidos)")
    p.add_argument("--col-codigo", help="Columna del código (si no, se detecta)")
    p.add_argument("--col-nombre", help="Columna del nombre (si no, se detecta)")
    p.add_argument("--col-excluida", help="Columna sí/no de exclusión (si no hay, todas quedan excluidas)")
    p.add_argument("--salida", default=str(comun.SALIDA / "naturalezas_excluidas.sql"))
    p.add_argument("--api", help="URL base de la API (ej. https://base-empresas.web.app); llama a POST /api/naturalezas")
    p.add_argument("--token", help="ID token de Firebase de un administrador (Authorization: Bearer)")
    p.add_argument("--dev-user", help="Email para el header X-Dev-User (solo API en modo dev)")
    a = p.parse_args(argv)
    try:
        r = ejecutar(a.excel, a.hoja, a.salida, col_codigo=a.col_codigo, col_nombre=a.col_nombre,
                     col_excluida=a.col_excluida)
        print(comun.md_tabla(["Código", "Nombre", "Excluida", "Código tomado de"],
                             [(f["codigo"], f["nombre"], "sí" if f["excluida"] else "no", f["origen_codigo"])
                              for f in r["filas"]]))
        print(f"\n→ {comun.rel(r['sql'])}")
        if a.api:
            errores = 0
            for codigo, estado, cuerpo in enviar_api(r["filas"], a.api, a.token, a.dev_user):
                print(f"{codigo}: {estado} {cuerpo}")
                errores += estado != 200
            return 1 if errores else 0
    except comun.ErrorFase0 as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
