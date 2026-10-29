"""Experimento A: ¿se puede asociar cada llamada a un teléfono de la lista por su número destino?

Normaliza a E.164 (app.telefonos) el destino de todas las llamadas del CDR del período,
de campañas y manuales, y lo cruza con los teléfonos de la lista del estudio. Lo que no
cruza se clasifica: interno, especial o de servicio, número fuera de lista (fijo o celular),
internacional o no normalizable. Criterio go: ≥ 95% de las llamadas salientes externas
cruzan con la lista o quedan explicadas por una regla.

    python fase0/exp_a_cdr.py --lista lista.xlsx --cdr cdr.csv [--prefijos-salida 9] [--internos ^3\\d{3}$]
"""
import argparse
import datetime as dt
import sys
from collections import Counter, defaultdict

import comun
from comun import Lista, md_tabla, pct, telmod, texto

UMBRAL = 95.0

# Columna lógica → nombres posibles (Asterisk/uContact primero, después el export de la web de uContact)
COLUMNAS_CDR = {
    "calldate": ["calldate", "fecha/hora", "fecha_hora", "fecha", "start", "inicio"],
    "dst": ["dst", "destino", "destination", "numero", "número"],
    "src": ["src", "origen", "source"],
    "duration": ["duration", "duración", "duracion"],
    "billsec": ["billsec", "conversación", "conversacion", "tiempo_conversacion"],
    "disposition": ["disposition", "disposición", "disposicion"],
    "userfield": ["userfield", "campo usuario", "campo_usuario"],
    "peeraccount": ["peeraccount", "agente", "agent", "encuestador"],
    "uniqueid": ["uniqueid", "guid", "linkedid", "id_llamada"],
    "accountcode": ["accountcode", "campaña", "campania", "campaign", "cola", "queue"],
}

# Categorías de cada llamada y si cuentan como cruzada/explicada
CATEGORIAS = [
    ("cruza", "Cruza con la lista", True),
    ("otra_lista", "Cruza con otra lista del período", True),
    ("especial", "Especial o de servicio (0800, 0900, cortos)", True),
    ("fuera_fijo", "Número fuera de lista (fijo)", False),
    ("fuera_celular", "Número fuera de lista (celular)", False),
    ("internacional", "Internacional", False),
    ("no_normalizable", "No normalizable", False),
]


def _fecha(v) -> dt.datetime | None:
    if isinstance(v, dt.datetime):
        return v
    s = texto(v)
    if not s:
        return None
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y"):
        try:
            return dt.datetime.fromisoformat(s) if fmt is None else dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def mapear_columnas(columnas, forzadas: dict | None = None) -> dict:
    """Columna lógica → columna del archivo. Las forzadas por argumento ganan."""
    salida = {}
    for logica, nombres in COLUMNAS_CDR.items():
        forzada = (forzadas or {}).get(logica)
        salida[logica] = comun.exigir_columna(columnas, forzada, "CDR") if forzada else comun.buscar_columna(columnas, nombres)
    if not salida["dst"]:
        raise comun.ErrorFase0(f"CDR: no se encontró la columna de destino (columnas: {', '.join(columnas)}); usá --col-dst")
    return salida


def _clasificar(destino, internos, prefijos, lista: Lista, otras: list[Lista]):
    """Devuelve (categoría o 'interno', Telefono | None)."""
    d = str(destino or "").strip()
    if not d:
        return "no_normalizable", telmod.Telefono(None, "invalido", "", "vacío")
    if telmod.es_interno(d, internos):
        return "interno", None
    n = telmod.normalizar(d, prefijos)
    if n.tipo == "interno":
        return "interno", n
    if n.e164 and n.e164 in lista.por_tel:
        return "cruza", n
    if n.e164 and any(n.e164 in o.por_tel for o in otras):
        return "otra_lista", n
    if n.tipo == "especial":
        return "especial", n
    if n.tipo == "fijo":
        return "fuera_fijo", n
    if n.tipo == "celular":
        return "fuera_celular", n
    if n.tipo == "internacional":
        return "internacional", n
    return "no_normalizable", n


def sugerir_prefijos(no_normalizables: Counter) -> list[tuple[str, int]]:
    """Prefijos de salida candidatos: dígitos iniciales que, sacados, dejan un fijo o celular válido."""
    votos = Counter()
    for destino, n in no_normalizables.items():
        d = "".join(ch for ch in destino if ch.isdigit())
        for k in (1, 2, 3):
            if len(d) - k >= 8 and telmod.normalizar(d[k:]).discable:
                votos[d[:k]] += n
                break
    return [(p, n) for p, n in votos.most_common(3) if n >= 3]


def ejecutar(lista, cdr, col_tel=None, col_rut=None, col_id=None, columnas_cdr=None, prefijos=None,
             internos_extra=(), internos_csv=comun.INTERNOS_CSV, otras_listas=(), desde=None, hasta=None,
             top=50, detalle=None) -> dict:
    """Corre el experimento. `lista` y `cdr` son rutas. Devuelve dict con métricas y markdown."""
    cfg = comun.config_seed()
    prefijos = list(prefijos if prefijos is not None else cfg.get("prefijos_salida") or [])
    internos = comun.destinos_internos(internos_csv, internos_extra)
    lst = Lista(lista, col_tel, col_rut, col_id, prefijos=prefijos)
    otras = [Lista(o, prefijos=prefijos) for o in otras_listas]
    columnas, filas, _ = comun.leer(cdr)
    col = mapear_columnas(columnas, columnas_cdr)

    c = Counter()
    por_cat = Counter()
    por_origen = defaultdict(Counter)       # campaña / manual → categoría
    motivos = Counter()
    destinos_nc = defaultdict(lambda: {"n": 0, "cat": None, "tel": None, "ejemplo": None})
    no_norm = Counter()
    vistos = set()
    llamados = set()
    fechas = []
    for f in filas:
        c["filas"] += 1
        uid = texto(f.get(col["uniqueid"])) if col["uniqueid"] else None
        if uid:
            if uid in vistos:
                c["tramos_duplicados"] += 1
                continue
            vistos.add(uid)
        fecha = _fecha(f.get(col["calldate"])) if col["calldate"] else None
        if fecha and ((desde and fecha.date() < desde) or (hasta and fecha.date() > hasta)):
            c["fuera_de_periodo"] += 1
            continue
        if fecha:
            fechas.append(fecha)
        c["llamadas"] += 1
        destino = f.get(col["dst"])
        cat, n = _clasificar(destino, internos, prefijos, lst, otras)
        if cat == "interno":
            c["internas"] += 1
            continue
        c["externas"] += 1
        por_cat[cat] += 1
        origen = "campaña" if col["accountcode"] and texto(f.get(col["accountcode"])) else "manual"
        por_origen[origen][cat] += 1
        if cat == "cruza":
            llamados.add(n.e164)
            continue
        if cat == "no_normalizable":
            motivos[n.motivo] += 1
            no_norm[str(destino or "")] += 1
        if cat in ("otra_lista", "especial"):
            continue
        clave = n.e164 or str(destino or "").strip() or "(vacío)"
        reg = destinos_nc[clave]
        reg["n"] += 1
        reg["cat"], reg["tel"], reg["ejemplo"] = cat, n, reg["ejemplo"] or str(destino)

    explicadas = sum(por_cat[k] for k, _, ok in CATEGORIAS if ok)
    porcentaje = pct(explicadas, c["externas"])
    go = porcentaje >= UMBRAL if c["externas"] else None
    top_nc = sorted(destinos_nc.items(), key=lambda kv: -kv[1]["n"])
    sugeridos = sugerir_prefijos(no_norm)

    ruta_detalle = None
    if detalle:
        cat_nombre = {k: n for k, n, _ in CATEGORIAS}
        ruta_detalle = comun.escribir_tabla(detalle, ["destino_e164_o_crudo", "llamadas", "categoria", "tipo", "motivo",
                                                      "nacional", "ejemplo_crudo"],
                                            [(k, r["n"], cat_nombre[r["cat"]], r["tel"].tipo, r["tel"].motivo or "",
                                              telmod.nacional(r["tel"].e164) or "", r["ejemplo"])
                                             for k, r in top_nc[:top]])
    res = {
        "experimento": "A", "go": go, "porcentaje": porcentaje, "porcentaje_cruza": pct(por_cat["cruza"], c["externas"]),
        "conteos": dict(c), "por_categoria": dict(por_cat), "motivos_no_normalizable": dict(motivos),
        "por_origen": {k: dict(v) for k, v in por_origen.items()}, "prefijos_sugeridos": sugeridos,
        "cobertura_lista": pct(len(llamados), len(lst.por_tel)), "telefonos_llamados": len(llamados),
        "top_no_cruzan": [(k, r["n"], r["cat"]) for k, r in top_nc[:top]], "detalle": ruta_detalle,
        "internos": internos, "prefijos": prefijos, "columnas": col,
        "periodo": (min(fechas).date().isoformat(), max(fechas).date().isoformat()) if fechas else None,
    }
    res["markdown"] = markdown(res, lst, top_nc[:min(top, 15)])
    return res


def markdown(r: dict, lst: Lista, top_nc) -> str:
    c = r["conteos"]
    ext = c.get("externas", 0)
    out = ["## Experimento A — Llamadas por número destino", ""]
    out.append(f"**Resultado: {comun.decision(r['go'])}** — {r['porcentaje']}% de las llamadas salientes externas "
               f"cruzan con la lista o quedan explicadas por una regla (criterio: ≥ {UMBRAL:.0f}%). "
               f"Cruce directo con la lista: {r['porcentaje_cruza']}%.")
    out += ["", "**Lista del estudio**", "", md_tabla(["Dato", "Valor"], lst.resumen()), ""]
    periodo = f"{r['periodo'][0]} a {r['periodo'][1]}" if r["periodo"] else "—"
    out += ["**CDR**", "", md_tabla(["Dato", "Valor"], [
        ("Período", periodo),
        ("Filas del archivo", c.get("filas", 0)),
        ("Tramos duplicados (mismo uniqueid, se cuenta uno)", c.get("tramos_duplicados", 0)),
        ("Fuera del período pedido", c.get("fuera_de_periodo", 0)),
        ("Llamadas analizadas", c.get("llamadas", 0)),
        ("Internas (destinos internos, se ignoran)", c.get("internas", 0)),
        ("Salientes externas (base del %)", ext),
    ]), ""]
    out.append("Columnas usadas: " + ", ".join(f"`{k}`→`{v}`" for k, v in r["columnas"].items() if v) + ".")
    out.append("Destinos internos: " + ", ".join(f"`{p}`" for p in r["internos"]) + ". Prefijos de salida: "
               + (", ".join(f"`{p}`" for p in r["prefijos"]) or "ninguno") + ".")
    out += ["", "**Clasificación de las llamadas externas**", ""]
    out.append(md_tabla(["Categoría", "Llamadas", "% externas", "¿Cruza o explicada?"],
                        [(nombre, r["por_categoria"].get(k, 0), pct(r["por_categoria"].get(k, 0), ext), "sí" if ok else "no")
                         for k, nombre, ok in CATEGORIAS]))
    if r["por_origen"]:
        out += ["", "**Por origen** (campaña = tiene `accountcode`; manual = sin campaña)", ""]
        filas = []
        for origen, cats in sorted(r["por_origen"].items()):
            tot = sum(cats.values())
            ok = sum(cats.get(k, 0) for k, _, e in CATEGORIAS if e)
            filas.append((origen, tot, cats.get("cruza", 0), f"{pct(ok, tot)}%"))
        out.append(md_tabla(["Origen", "Externas", "Cruzan", "% cruza o explicada"], filas))
    if r["motivos_no_normalizable"]:
        out += ["", "**No normalizables por motivo**", "",
                md_tabla(["Motivo", "Llamadas"], sorted(r["motivos_no_normalizable"].items(), key=lambda x: -x[1]))]
    if r["prefijos_sugeridos"]:
        out += ["", "**Posibles prefijos de salida** (dígitos que agrega la central; probar con `--prefijos-salida`):", ""]
        out += [f"- `{p}`: explicaría {n} llamadas no normalizables" for p, n in r["prefijos_sugeridos"]]
    if top_nc:
        out += ["", f"**Destinos que no cruzan más frecuentes** (top {len(top_nc)})", ""]
        cat_nombre = {k: n for k, n, _ in CATEGORIAS}
        out.append(md_tabla(["Destino", "Llamadas", "Categoría", "Motivo"],
                            [(k, v["n"], cat_nombre[v["cat"]], v["tel"].motivo or "") for k, v in top_nc]))
    out += ["", f"Cobertura: {r['telefonos_llamados']} de {len(lst.por_tel)} teléfonos de la lista recibieron al menos "
                f"una llamada ({r['cobertura_lista']}%)."]
    if r["detalle"]:
        out.append(f"Detalle de destinos que no cruzan: `{comun.rel(r['detalle'])}`.")
    if r["go"] is False:
        out += ["", "**Si no llega al 95%** (spec): se agrega la pregunta `EC_TEL_USADO` obligatoria en el cuestionario "
                    "y el cruce de llamadas queda como informativo. Antes, revisar la tabla de destinos que no cruzan: "
                    "si hay prefijos de la central o internos sin declarar, agregarlos y volver a correr."]
    return "\n".join(out) + "\n"


def _fecha_arg(s):
    return dt.date.fromisoformat(s)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lista", required=True, help="Lista de teléfonos del estudio (.xlsx/.csv)")
    p.add_argument("--cdr", required=True, help="Export del CDR del período de campo (.csv/.xlsx)")
    p.add_argument("--col-tel", action="append", help="Columna de teléfono de la lista (repetible; por defecto se detecta)")
    p.add_argument("--col-rut", help="Columna de RUT de la lista (por defecto se detecta)")
    p.add_argument("--col-id", help="Columna id_item de la lista (opcional)")
    for logica in COLUMNAS_CDR:
        p.add_argument(f"--col-{logica}", dest=f"col_{logica}", help=f"Columna del CDR para {logica}")
    p.add_argument("--prefijos-salida", nargs="*", default=None, help="Prefijos que agrega la central (ej. 9 0)")
    p.add_argument("--internos", nargs="*", default=(), help="Patrones extra de destinos internos (regex con ^ o número)")
    p.add_argument("--internos-csv", default=str(comun.INTERNOS_CSV), help="CSV con patrones de destinos internos")
    p.add_argument("--otras-listas", nargs="*", default=(), help="Listas de otros estudios del mismo período")
    p.add_argument("--desde", type=_fecha_arg, help="Primer día del período (AAAA-MM-DD)")
    p.add_argument("--hasta", type=_fecha_arg, help="Último día del período (AAAA-MM-DD)")
    p.add_argument("--top", type=int, default=50, help="Cantidad de destinos que no cruzan en el detalle")
    p.add_argument("--detalle", default=str(comun.SALIDA / "exp_a_no_cruzan.csv"), help="Archivo de detalle (.csv o .xlsx)")
    p.add_argument("--salida", default=str(comun.SALIDA / "exp_a.md"), help="Markdown del resultado")
    return p


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    forzadas = {k: getattr(a, f"col_{k}") for k in COLUMNAS_CDR if getattr(a, f"col_{k}")}
    try:
        r = ejecutar(a.lista, a.cdr, a.col_tel, a.col_rut, a.col_id, forzadas, a.prefijos_salida, a.internos,
                     a.internos_csv, a.otras_listas, a.desde, a.hasta, a.top, a.detalle)
    except comun.ErrorFase0 as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    comun.escribir(a.salida, r["markdown"])
    print(r["markdown"])
    print(f"→ {comun.rel(a.salida)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
