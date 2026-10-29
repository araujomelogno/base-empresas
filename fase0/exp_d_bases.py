"""Experimento D: ¿cuánto se duplica y cuántos intermediarios hay en las bases propias?

Une 2 o 3 bases propias (.xlsx/.csv) por RUT y cuenta: filas, RUTs inválidos (por motivo),
filas sin RUT, RUTs válidos distintos, RUTs duplicados dentro de cada base y entre bases,
razones sociales en conflicto para el mismo RUT y teléfonos compartidos por ≥ N RUTs
(sospechosos de intermediario, N = 5 por defecto como en la configuración). Da además la
distribución de cuántos RUTs comparten cada teléfono, para confirmar o ajustar el umbral.

    python fase0/exp_d_bases.py --bases base1.xlsx base2.csv base3.xlsx [--umbral 5]
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

import comun
from comun import md_tabla, pct, razon_normalizada, rutmod, texto

TRAMOS = [(1, 1, "1"), (2, 2, "2"), (3, 4, "3–4"), (5, 9, "5–9"), (10, 19, "10–19"), (20, 10 ** 9, "20 o más")]
UMBRALES = (3, 4, 5, 6, 8, 10)


def ejecutar(bases, col_rut=None, col_tel=None, col_razon=None, umbral=None, prefijos=(), detalle_dir=comun.SALIDA,
             max_lista=40) -> dict:
    """`col_*` aplican a todas las bases (si no, se detectan por base)."""
    umbral = umbral or comun.config_seed().get("umbral_intermediario") or 5
    por_base = []
    rut_bases = defaultdict(set)            # rut → bases donde aparece
    rut_filas = Counter()                   # (base, rut) → filas
    razones = defaultdict(dict)             # rut → razón normalizada → razón original
    tel_ruts = defaultdict(set)             # e164 → ruts
    tel_tipo = {}
    invalidos = Counter()
    tel_invalidos = Counter()
    for ruta in bases:
        nombre = Path(ruta).name
        columnas, filas, _ = comun.leer(ruta)
        c_rut = comun.exigir_columna(columnas, col_rut, nombre) if col_rut else comun.detectar_columna_rut(columnas, filas)
        c_tel = [comun.exigir_columna(columnas, c, nombre) for c in col_tel] if col_tel \
            else comun.detectar_columnas_tel(columnas, filas)
        c_raz = comun.exigir_columna(columnas, col_razon, nombre) if col_razon else comun.detectar_columna_razon(columnas)
        if not c_rut:
            raise comun.ErrorFase0(f"{nombre}: no se encontró la columna de RUT; indicala con --col-rut")
        b = Counter(filas=len(filas))
        for f in filas:
            r, motivo = rutmod.validar(f.get(c_rut))
            if r is None:
                if motivo == "sin RUT":
                    b["sin_rut"] += 1
                else:
                    b["rut_invalido"] += 1
                    invalidos[motivo] += 1
                continue
            b["rut_valido"] += 1
            rut_bases[r].add(nombre)
            rut_filas[(nombre, r)] += 1
            raz = texto(f.get(c_raz)) if c_raz else None
            if raz and razon_normalizada(raz):
                razones[r].setdefault(razon_normalizada(raz), raz)
            for t in comun.telefonos_de(f, c_tel, prefijos):
                if t.e164:
                    tel_ruts[t.e164].add(r)
                    tel_tipo[t.e164] = t.tipo
                else:
                    tel_invalidos[t.tipo if t.tipo != "invalido" else (t.motivo or "invalido")] += 1
        ruts_base = {r for (bn, r) in rut_filas if bn == nombre}
        b["ruts_distintos"] = len(ruts_base)
        b["ruts_duplicados"] = sum(1 for r in ruts_base if rut_filas[(nombre, r)] > 1)
        b["filas_duplicadas"] = sum(rut_filas[(nombre, r)] - 1 for r in ruts_base)
        por_base.append({"archivo": nombre, "ruta": str(ruta), "col_rut": c_rut, "col_tel": c_tel, "col_razon": c_raz,
                         **b})

    total_filas = sum(b["filas"] for b in por_base)
    distintos = len(rut_bases)
    en_varias = {r for r, bs in rut_bases.items() if len(bs) > 1}
    conflictos = {r: sorted(v.values()) for r, v in razones.items() if len(v) > 1}
    dist = Counter()
    for ruts in tel_ruts.values():
        n = len(ruts)
        for lo, hi, etiqueta in TRAMOS:
            if lo <= n <= hi:
                dist[etiqueta] += 1
    por_umbral = {u: sum(1 for ruts in tel_ruts.values() if len(ruts) >= u) for u in UMBRALES}
    sospechosos = sorted(((e, ruts) for e, ruts in tel_ruts.items() if len(ruts) >= umbral), key=lambda x: -len(x[1]))
    ejemplo_razon = {r: next(iter(v.values())) for r, v in razones.items()}

    detalle = {}
    if detalle_dir:
        detalle["sospechosos"] = comun.escribir_tabla(
            Path(detalle_dir) / "exp_d_telefonos_compartidos.csv", ["e164", "nacional", "tipo", "ruts", "ejemplos"],
            [(e, comun.telmod.nacional(e), tel_tipo.get(e), len(rs),
              " / ".join(f"{r} {ejemplo_razon.get(r, '')}".strip() for r in sorted(rs)[:5])) for e, rs in sospechosos])
        if conflictos:
            detalle["conflictos"] = comun.escribir_tabla(
                Path(detalle_dir) / "exp_d_razon_social_conflictos.csv", ["rut", "bases", "razones_sociales"],
                [(r, ", ".join(sorted(rut_bases[r])), " | ".join(v)) for r, v in sorted(conflictos.items())])
    r = {
        "experimento": "D", "go": None, "umbral": umbral, "bases": por_base, "filas": total_filas,
        "sin_rut": sum(b["sin_rut"] for b in por_base), "rut_invalido": sum(b["rut_invalido"] for b in por_base),
        "invalidos_por_motivo": dict(invalidos), "ruts_distintos": distintos, "ruts_en_varias_bases": len(en_varias),
        "ruts_duplicados_en_base": sum(b["ruts_duplicados"] for b in por_base),
        "conflictos_razon": len(conflictos), "ejemplos_conflicto": list(conflictos.items())[:10],
        "telefonos": len(tel_ruts), "telefonos_invalidos": dict(tel_invalidos), "distribucion": dict(dist),
        "por_umbral": por_umbral, "sospechosos": [(e, len(rs)) for e, rs in sospechosos], "detalle": detalle,
        "solapamiento": _solapamiento(por_base, rut_bases),
    }
    r["markdown"] = markdown(r, sospechosos[:max_lista], ejemplo_razon, tel_tipo)
    return r


def _solapamiento(por_base, rut_bases):
    nombres = [b["archivo"] for b in por_base]
    filas = []
    for a in nombres:
        filas.append([a] + [sum(1 for bs in rut_bases.values() if a in bs and b in bs) for b in nombres])
    return nombres, filas


def markdown(r: dict, sospechosos, ejemplo_razon, tel_tipo) -> str:
    out = ["## Experimento D — Duplicados e intermediarios en bases propias", ""]
    out.append(f"{len(r['bases'])} bases, {r['filas']} filas, **{r['ruts_distintos']} RUTs válidos distintos**. "
               f"Sin RUT: {r['sin_rut']} ({pct(r['sin_rut'], r['filas'])}%). RUT inválido: {r['rut_invalido']} "
               f"({pct(r['rut_invalido'], r['filas'])}%). Teléfonos compartidos por ≥ {r['umbral']} RUTs: "
               f"**{len(r['sospechosos'])}**.")
    out += ["", md_tabla(["Base", "Filas", "RUT válido", "RUT inválido", "Sin RUT", "RUTs distintos",
                          "RUTs repetidos en la base", "Columnas (RUT · teléfono · razón)"],
                         [(b["archivo"], b["filas"], b.get("rut_valido", 0), b.get("rut_invalido", 0), b.get("sin_rut", 0),
                           b["ruts_distintos"], b["ruts_duplicados"],
                           f"{b['col_rut']} · {', '.join(b['col_tel']) or '—'} · {b['col_razon'] or '—'}")
                          for b in r["bases"]])]
    nombres, matriz = r["solapamiento"]
    out += ["", "**RUTs en común entre bases** (diagonal: RUTs distintos de cada base)", "",
            md_tabla(["Base"] + nombres, matriz), "",
            f"RUTs que aparecen en más de una base: {r['ruts_en_varias_bases']}. "
            f"RUTs repetidos dentro de una misma base: {r['ruts_duplicados_en_base']}. "
            f"RUTs con razón social distinta entre filas: {r['conflictos_razon']}."]
    if r["invalidos_por_motivo"]:
        out += ["", "**RUTs inválidos por motivo**", "",
                md_tabla(["Motivo", "Filas"], sorted(r["invalidos_por_motivo"].items(), key=lambda x: -x[1]))]
    if r["ejemplos_conflicto"]:
        out += ["", "**Ejemplos de razón social en conflicto**", "",
                md_tabla(["RUT", "Razones sociales"], [(k, " · ".join(v)) for k, v in r["ejemplos_conflicto"]])]
    out += ["", "**Teléfonos por cantidad de RUTs que los comparten**", "",
            md_tabla(["RUTs por teléfono", "Teléfonos"], [(e, r["distribucion"].get(e, 0)) for _, _, e in TRAMOS]), "",
            "**Teléfonos que quedarían sospechosos según el umbral**", "",
            md_tabla(["Umbral (≥ RUTs)", "Teléfonos sospechosos"],
                     [(f"{u}{' (actual)' if u == r['umbral'] else ''}", n) for u, n in r["por_umbral"].items()])]
    if sospechosos:
        out += ["", f"**Teléfonos compartidos por ≥ {r['umbral']} RUTs** ({len(r['sospechosos'])}; se muestran {len(sospechosos)})", "",
                md_tabla(["Teléfono", "Tipo", "RUTs", "Ejemplos"],
                         [(comun.telmod.nacional(e), tel_tipo.get(e), len(rs),
                           "; ".join(ejemplo_razon.get(x, x) for x in sorted(rs)[:3])) for e, rs in sospechosos])]
    if r["telefonos_invalidos"]:
        out += ["", "Teléfonos no discables: " + ", ".join(f"{k} {v}" for k, v in
                                                           sorted(r["telefonos_invalidos"].items(), key=lambda x: -x[1])) + "."]
    out += ["", _lectura_umbral(r)]
    for nombre, ruta in r["detalle"].items():
        out.append(f"Detalle ({nombre}): `{comun.rel(ruta)}`.")
    return "\n".join(out) + "\n"


def _lectura_umbral(r) -> str:
    """Ayuda para decidir: cuántos teléfonos hay justo debajo del umbral frente a los que lo superan."""
    u = r["umbral"]
    arriba = r["por_umbral"].get(u, len(r["sospechosos"]))
    debajo = r["por_umbral"].get(u - 2, 0) - arriba if (u - 2) in r["por_umbral"] else None
    txt = f"**Umbral de intermediario:** con {u} quedan {arriba} teléfonos sospechosos para revisar."
    if debajo is not None:
        txt += (f" Con {u - 2}–{u - 1} RUTs hay {debajo} más: si al revisarlos son mayormente estudios contables, "
                f"conviene bajar el umbral; si son grupos de empresas, confirmar {u}.")
    return txt + " La decisión final la toma el data steward con la lista de arriba."


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bases", nargs="+", required=True, help="Bases propias (.xlsx/.csv)")
    p.add_argument("--col-rut", help="Columna de RUT (si es igual en todas las bases)")
    p.add_argument("--col-tel", action="append", help="Columna de teléfono (repetible)")
    p.add_argument("--col-razon", help="Columna de razón social")
    p.add_argument("--umbral", type=int, help="RUTs por teléfono para sospechar intermediario (defecto: config, 5)")
    p.add_argument("--prefijos-salida", nargs="*", default=(), help="Prefijos a sacar antes de normalizar")
    p.add_argument("--salida", default=str(comun.SALIDA / "exp_d.md"), help="Markdown del resultado")
    return p


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    try:
        r = ejecutar(a.bases, a.col_rut, a.col_tel, a.col_razon, a.umbral, a.prefijos_salida)
    except comun.ErrorFase0 as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    comun.escribir(a.salida, r["markdown"])
    print(r["markdown"])
    print(f"→ {comun.rel(a.salida)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
