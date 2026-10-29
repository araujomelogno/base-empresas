"""Informe de validación de la fase 0: corre A, B y D, lista C como manual y decide go/no-go.

Escribe fase0/salida/informe_validacion.md con los resultados de cada experimento y la
decisión según el spec:
  - si A < 95%: EC_TEL_USADO pasa a pregunta obligatoria y el cruce de llamadas queda informativo;
  - si B falla porque faltan las URL variables: el identificador pasa a RUT + teléfono y se exige
    el bloque estándar desde el primer estudio de la fase 1.

    python fase0/informe.py --lista L.xlsx --cdr cdr.csv --sav A.sav B.sav --bases b1.xlsx b2.csv \\
        [--excluidos referencia.xlsx] [--prefijos-salida 9]
    python fase0/informe.py --ejemplo        # con los datos sintéticos de fase0/salida/ejemplo/
"""
import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path

import cargar_excluidos
import comun
import exp_a_cdr
import exp_b_sav
import exp_d_bases
from comun import md_tabla


def _correr(nombre, fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except comun.ErrorFase0 as e:
        return {"error": str(e), "go": None, "markdown": f"## Experimento {nombre}\n\nNo se pudo correr: {e}\n"}
    except Exception as e:  # el informe sale igual, con el error a la vista
        traceback.print_exc()
        return {"error": repr(e), "go": None, "markdown": f"## Experimento {nombre}\n\nError inesperado: `{e!r}`\n"}


def _no_corrido(nombre, faltan):
    return {"go": None, "omitido": True,
            "markdown": f"## Experimento {nombre}\n\nNo ejecutado: faltan insumos ({faltan}).\n"}


def decidir(a: dict, b: dict) -> tuple[str, list[str]]:
    """Decisión global y ajustes que dispara el spec."""
    ajustes = []
    if a.get("go") is False:
        ajustes.append("**A < 95%:** se agrega la pregunta `EC_TEL_USADO` obligatoria en todos los cuestionarios y el "
                       "cruce de llamadas por destino queda como informativo (no se usa para el protocolo de intentos).")
    if b.get("go") is False:
        if b.get("falla_por_url_variables"):
            ajustes.append("**B falla por URL variables faltantes:** el identificador pasa a ser RUT + teléfono y el "
                           "bloque estándar de variables es obligatorio desde el primer estudio de la fase 1.")
        else:
            ajustes.append("**B < 95% por otros motivos:** revisar los motivos de las filas sin asociar antes de "
                           "empezar la iteración 3; la conciliación manual va a tener más carga.")
    elif b.get("falta_id_item"):
        ajustes.append("B pasa, pero hay .sav sin `EC_ID_ITEM` (" + ", ".join(b["falta_id_item"]) + "): exigir la "
                       "plantilla de Alchemer con el bloque estándar desde el piloto (riesgo del spec).")
    if a.get("go") is None or b.get("go") is None:
        global_ = "INCOMPLETA — faltan resultados de A o B"
    elif a["go"] and b["go"]:
        global_ = "GO"
    else:
        global_ = "GO con ajustes (plan B del spec)"
    return global_, ajustes


def generar(lista=None, cdr=None, savs=(), bases=(), excluidos=None, hoja_excluidos="excluidos", prefijos=None,
            internos=(), umbral=None, salida=comun.SALIDA / "informe_validacion.md", dir_detalle=comun.SALIDA) -> dict:
    dir_detalle = Path(dir_detalle)
    if lista and cdr:
        a = _correr("A", exp_a_cdr.ejecutar, lista, cdr, prefijos=prefijos, internos_extra=internos,
                    detalle=dir_detalle / "exp_a_no_cruzan.csv")
    else:
        a = _no_corrido("A — Llamadas por número destino", "lista del estudio y CDR")
    if lista and savs:
        b = _correr("B", exp_b_sav.ejecutar, lista, list(savs), dir_salida=dir_detalle)
    else:
        b = _no_corrido("B — Respuestas del .sav", "lista del estudio y .sav")
    if bases:
        d = _correr("D", exp_d_bases.ejecutar, list(bases), umbral=umbral, prefijos=prefijos or (), detalle_dir=dir_detalle)
    else:
        d = _no_corrido("D — Bases propias", "2 o 3 bases propias")
    nat = None
    if excluidos:
        nat = _correr("naturalezas", cargar_excluidos.ejecutar, excluidos, hoja_excluidos,
                      dir_detalle / "naturalezas_excluidas.sql")

    global_, ajustes = decidir(a, b)
    hoy = dt.date.today().isoformat()
    out = ["# Informe de validación — Fase 0", "", f"Generado el {hoy} con `fase0/informe.py`.", ""]
    insumos = [("Lista del estudio", [lista] if lista else []), ("CDR del período", [cdr] if cdr else []),
               (".sav", savs), ("Bases propias", bases), ("Hoja excluidos", [excluidos] if excluidos else [])]
    out += ["**Insumos**", "", md_tabla(["Insumo", "Archivo"], [(k, ", ".join(f"`{comun.rel(x)}`" for x in v) or "—")
                                                                for k, v in insumos]), ""]
    out += ["## Decisión", "", f"**{global_}**", ""]
    fila_a = f"{a['porcentaje']}% cruza o explicada" if "porcentaje" in a else a.get("error", "no ejecutado")
    fila_b = f"{b['porcentaje']}% de filas asociadas" if "porcentaje" in b else b.get("error", "no ejecutado")
    fila_d = (f"{d['ruts_distintos']} RUTs, {len(d['sospechosos'])} teléfonos ≥ {d['umbral']} RUTs"
              if "ruts_distintos" in d else d.get("error", "no ejecutado"))
    out.append(md_tabla(["#", "Pregunta", "Resultado", "Criterio", "Decisión"], [
        ("A", "¿Cada llamada se asocia a un teléfono de la lista por su destino?", fila_a, "≥ 95%", comun.decision(a.get("go"))),
        ("B", "¿El .sav trae lo necesario para asociar cada respuesta?", fila_b, "≥ 95% en cada .sav",
         comun.decision(b.get("go"))),
        ("C", "¿Qué variables tiene que tener todo cuestionario a empresas?", "Propuesta en alchemer_bloque_estandar.md",
         "Acordado con coordinación de campo", "manual"),
        ("D", "¿Cuánto se duplica y cuántos intermediarios hay?", fila_d, "Conteos documentados; umbral confirmado",
         "documentado" if "ruts_distintos" in d else "sin datos"),
    ]))
    if ajustes:
        out += ["", "**Ajustes que dispara el resultado:**", ""] + [f"- {x}" for x in ajustes]
    out += ["", a["markdown"], b["markdown"]]
    out += ["## Experimento C — Bloque estándar de variables (manual)", "",
            "No se automatiza: es un acuerdo con coordinación de campo. La propuesta está en "
            "`fase0/alchemer_bloque_estandar.md` y su versión para el sistema en `fase0/alchemer_bloque_estandar.json` "
            "(misma estructura que la propuesta de mapeo de la ingesta del .sav).", "",
            "- [ ] Revisar los cuestionarios del estudio usado en A y B y marcar qué variables del bloque ya existían.",
            "- [ ] Acordar nombres y códigos con coordinación de campo.",
            "- [ ] Cargar el bloque como plantilla en Alchemer y hacer una exportación .sav de prueba.",
            "- [ ] Correr `exp_b_sav.py` con esa exportación: las 9 variables tienen que figurar como presentes.", ""]
    out.append(d["markdown"])
    if nat is not None:
        out += ["## Catálogo de naturalezas excluidas", ""]
        if "filas" in nat:
            out += [md_tabla(["Código", "Nombre", "Excluida", "Código tomado de"],
                             [(f["codigo"], f["nombre"], "sí" if f["excluida"] else "no", f["origen_codigo"])
                              for f in nat["filas"]]), "",
                    f"SQL del catálogo: `{comun.rel(nat['sql'])}`. La marca de exclusión se fija por la API "
                    "(`cargar_excluidos.py --api …`), que crea la versión de configuración.", ""]
        else:
            out += [nat["markdown"], ""]
    out += ["## Entregables de la fase 0", "", md_tabla(["Entregable", "Dónde"], [
        ("Informe de validación con A–D y decisión go/no-go", "este archivo"),
        ("Reglas de normalización de teléfonos uruguayos", "`fase0/datos/reglas_normalizacion.md` (implementadas en `api/app/telefonos.py`)"),
        ("Lista inicial de destinos internos a ignorar en el CDR", "`fase0/datos/destinos_internos.csv`"),
        ("Bloque estándar de variables como plantilla en Alchemer", "`fase0/alchemer_bloque_estandar.md` / `.json`"),
        ("Catálogo inicial de naturalezas con la marca de exclusión", "`fase0/cargar_excluidos.py` → `fase0/salida/naturalezas_excluidas.sql`"),
    ])]
    texto_ = "\n".join(out) + "\n"
    if salida:
        comun.escribir(salida, texto_)
    return {"decision": global_, "ajustes": ajustes, "a": a, "b": b, "d": d, "naturalezas": nat, "markdown": texto_,
            "salida": salida}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ejemplo", action="store_true", help="Usar los datos de fase0/salida/ejemplo (los genera si faltan)")
    p.add_argument("--lista", help="Lista de teléfonos del estudio (.xlsx/.csv)")
    p.add_argument("--cdr", help="CDR del período de campo (.csv/.xlsx)")
    p.add_argument("--sav", nargs="*", default=(), help=".sav de cada parte")
    p.add_argument("--bases", nargs="*", default=(), help="Bases propias (.xlsx/.csv)")
    p.add_argument("--excluidos", help="Excel de referencia con la hoja 'excluidos'")
    p.add_argument("--hoja-excluidos", default="excluidos")
    p.add_argument("--prefijos-salida", nargs="*", default=None, help="Prefijos que agrega la central")
    p.add_argument("--internos", nargs="*", default=(), help="Patrones extra de destinos internos")
    p.add_argument("--umbral", type=int, help="Umbral de intermediario para D (defecto 5)")
    p.add_argument("--salida", default=str(comun.SALIDA / "informe_validacion.md"))
    a = p.parse_args(argv)
    if a.ejemplo:
        ej = comun.EJEMPLO
        if not (ej / "cdr_septiembre.csv").exists():
            sys.path.insert(0, str(comun.FASE0 / "datos_ejemplo"))
            import generar as gen
            gen.generar(ej)
        a.lista = a.lista or str(ej / "lista_estudio.xlsx")
        a.cdr = a.cdr or str(ej / "cdr_septiembre.csv")
        a.sav = a.sav or [str(ej / "parteA.sav"), str(ej / "parteB.sav")]
        a.bases = a.bases or [str(ej / n) for n in ("base_2024_industria.xlsx", "base_2025_servicios.csv",
                                                    "base_2025_comercio.xlsx")]
        a.excluidos = a.excluidos or str(ej / "referencia.xlsx")
    r = generar(a.lista, a.cdr, a.sav, a.bases, a.excluidos, a.hoja_excluidos, a.prefijos_salida, a.internos, a.umbral,
                Path(a.salida))
    print(r["markdown"])
    print(f"Decisión: {r['decision']}")
    print(f"→ {comun.rel(a.salida)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
