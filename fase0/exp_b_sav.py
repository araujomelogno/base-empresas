"""Experimento B: ¿el .sav trae lo necesario para asociar cada respuesta a una empresa?

Lee cada .sav (app.lectores.leer_sav), usa app.sav.describir/proponer para sugerir el mapeo
(identificador, bloque estándar EC_*, valores de las variables codificadas) y asocia cada
fila a una empresa de la lista: por id_item si la lista lo trae, si no por RUT y, como
respaldo, por teléfono usado. Criterio go: ≥ 95% de las filas de cada .sav asociadas;
las que no, con motivo.

    python fase0/exp_b_sav.py --lista lista.xlsx --sav parteA.sav parteB.sav
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import comun
from comun import Lista, clave_id, md_tabla, pct, rutmod, telmod, texto

from app import sav as savmod  # noqa: E402  (comun ya agregó api/ al path)

UMBRAL = 95.0
PLANTILLA = comun.FASE0 / "alchemer_bloque_estandar.json"
BLOQUE = ["EC_ID_ITEM", "EC_RUT", "EC_TEL_USADO", "EC_CALIDAD_TEL", "EC_TEL_ALT", "EC_RESP_NOMBRE", "EC_RESP_CARGO",
          "EC_RESP_AREA", "EC_RESULTADO"]
# Variable del bloque → destino del mapeo de app.sav (EC_ID_ITEM es el identificador)
DESTINO_BLOQUE = {"EC_RUT": "rut", "EC_TEL_USADO": "tel_usado", "EC_CALIDAD_TEL": "calidad_tel", "EC_TEL_ALT": "tel_alt",
                  "EC_RESP_NOMBRE": "resp_nombre", "EC_RESP_CARGO": "resp_cargo", "EC_RESP_AREA": "resp_area",
                  "EC_RESULTADO": "resultado"}
TEL_NOMBRES = ["EC_TEL_USADO", "tel_usado", "telefono_usado", "telefono", "tel", "phone"]


def cargar_plantilla(ruta) -> dict | None:
    if not ruta or not Path(ruta).exists():
        return None
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


class Asociador:
    """Asocia una fila del .sav a una empresa de la lista (versión sin base de sav.Contexto)."""

    def __init__(self, lista: Lista):
        self.l = lista

    def _por_rut(self, valor, tel):
        r, motivo = rutmod.validar(valor)
        if r is None:
            return None, f"RUT inválido: {motivo}"
        filas = self.l.por_rut.get(r)
        if not filas:
            return None, "RUT no está en la lista"
        if len({self.l.empresa[i] for i in filas}) == 1:
            return self.l.empresa[filas[0]], None
        return None, "RUT en más de una empresa de la lista"

    def _por_tel(self, valor):
        n = telmod.normalizar(valor)
        if not n.e164:
            return None, f"teléfono no normalizable: {n.motivo}"
        emp = self.l.por_tel.get(n.e164)
        if not emp:
            return None, "teléfono no está en la lista"
        if len(emp) > 1:
            return None, f"teléfono compartido por {len(emp)} empresas (posible intermediario)"
        return next(iter(emp)), None

    def asociar(self, fila: dict, mapeo: dict, var_tel: str | None) -> tuple[str | None, str | None, str | None]:
        """Devuelve (empresa, método, motivo_si_no). Orden: id_item → RUT → teléfono."""
        ident = mapeo.get("identificador") or {}
        var_rut = (mapeo.get("variables") or {}).get("rut")
        if ident.get("tipo") == "rut":
            var_rut = ident["variable"]
        tel = texto(fila.get(var_tel)) if var_tel else None
        motivo = None
        if ident.get("tipo") == "id_item":
            idv = clave_id(fila.get(ident["variable"]))
            if idv and self.l.col_id:
                if idv in self.l.por_id:
                    return self.l.empresa[self.l.por_id[idv]], "id_item", None
                motivo = f"id_item {idv} no está en la lista"
            elif not idv:
                motivo = "sin id_item"
        valor_rut = texto(fila.get(var_rut)) if var_rut else None
        if valor_rut:
            emp, m = self._por_rut(valor_rut, tel)
            if emp:
                return emp, "RUT", None
            motivo = m if motivo is None or motivo == "sin id_item" else f"{motivo}; {m}"
        elif motivo is None:
            motivo = "sin RUT"
        if tel:
            emp, m = self._por_tel(tel)
            if emp:
                return emp, "teléfono", None
            motivo = f"{motivo}; {m}"
        elif not valor_rut and (motivo or "").startswith("sin"):
            motivo = "sin identificador (ni id_item, ni RUT, ni teléfono)"
        return None, None, motivo


def bloque_estandar(columnas, mapeo) -> list[tuple[str, str]]:
    """Estado de cada variable del bloque: presente, reconocida con otro nombre o falta."""
    idx = {c.lower(): c for c in columnas}
    salida = []
    for var in BLOQUE:
        if var.lower() in idx:
            salida.append((var, "presente"))
            continue
        if var == "EC_ID_ITEM":
            ident = mapeo.get("identificador") or {}
            otro = ident.get("variable") if ident.get("tipo") == "id_item" else None
        else:
            otro = (mapeo.get("variables") or {}).get(DESTINO_BLOQUE[var])
        salida.append((var, f"reconocida como `{otro}`" if otro else "falta"))
    return salida


def analizar_sav(ruta, lista: Lista, plantilla=None, var_tel=None) -> dict:
    columnas, filas, meta = comun.leer(ruta)
    if comun.tipo_archivo(ruta) != "sav":
        raise comun.ErrorFase0(f"{ruta}: el experimento B espera un .sav")
    desc = savmod.describir(columnas, filas, meta)
    mapeo = savmod.proponer(columnas, filas, meta, plantilla)
    var_tel = var_tel or mapeo.get("variables", {}).get("tel_usado") or comun.buscar_columna(columnas, TEL_NOMBRES)
    if not mapeo.get("identificador") and var_tel:
        # Fase 0: sin id_item ni RUT se prueba el teléfono (la API acepta solo id_item o RUT)
        mapeo["identificador"] = {"variable": var_tel, "tipo": "telefono"}
    asoc = Asociador(lista)
    c = Counter()
    metodos = Counter()
    motivos = Counter()
    sin_mapear = Counter()
    resultados = Counter()
    calidad = Counter()
    no_asociadas = []
    for i, f in enumerate(filas):
        c["filas"] += 1
        rid = texto(f.get(mapeo["response_id"])) if mapeo.get("response_id") else None
        if not rid:
            c["sin_response_id"] += 1
        emp, metodo, motivo = asoc.asociar(f, mapeo, var_tel)
        if emp:
            c["asociadas"] += 1
            metodos[metodo] += 1
        else:
            c["sin_asociar"] += 1
            motivos[re.sub(r"id_item \S+", "id_item", motivo)] += 1
            no_asociadas.append((Path(ruta).name, rid or f"fila {i + 1}", motivo))
        v, sm = savmod.valores_mapeados(f, mapeo)
        for destino, cod in sm.items():
            sin_mapear[(destino, cod)] += 1
        resultados[v.get("resultado", "—")] += 1
        if "calidad_tel" in v:
            calidad[v["calidad_tel"]] += 1
    porcentaje = pct(c["asociadas"], c["filas"])
    bloque = bloque_estandar(columnas, mapeo)
    falta_id = dict(bloque)["EC_ID_ITEM"] == "falta"
    return {
        "archivo": Path(ruta).name, "ruta": str(ruta), "n_variables": len(desc), "mapeo": mapeo, "var_tel": var_tel,
        "conteos": dict(c), "porcentaje": porcentaje, "go": porcentaje >= UMBRAL if c["filas"] else None,
        "metodos": dict(metodos), "motivos": dict(motivos), "bloque": bloque, "falta_id_item": falta_id,
        "sin_mapear": {f"{d}={cod}": n for (d, cod), n in sin_mapear.most_common()},
        "resultados": dict(resultados), "calidad": dict(calidad), "no_asociadas": no_asociadas,
    }


def ejecutar(lista, savs, col_tel=None, col_rut=None, col_id=None, plantilla=PLANTILLA, var_tel=None,
             dir_salida=comun.SALIDA) -> dict:
    lst = Lista(lista, col_tel, col_rut, col_id)
    tpl = cargar_plantilla(plantilla) if plantilla else None
    partes = [analizar_sav(s, lst, tpl, var_tel) for s in savs]
    total = sum(p["conteos"]["filas"] for p in partes)
    asociadas = sum(p["conteos"].get("asociadas", 0) for p in partes)
    go = all(p["go"] for p in partes) if partes and all(p["go"] is not None for p in partes) else None
    if dir_salida:
        for p in partes:
            comun.escribir(Path(dir_salida) / f"exp_b_mapeo_{Path(p['archivo']).stem}.json",
                           json.dumps(p["mapeo"], ensure_ascii=False, indent=2))
        filas_na = [x for p in partes for x in p["no_asociadas"]]
        detalle = comun.escribir_tabla(Path(dir_salida) / "exp_b_sin_asociar.csv", ["archivo", "response_id", "motivo"],
                                       filas_na) if filas_na else None
    else:
        detalle = None
    r = {"experimento": "B", "go": go, "porcentaje": pct(asociadas, total), "partes": partes, "detalle": detalle,
         "falla_por_url_variables": go is False and any(p["falta_id_item"] and not p["go"] for p in partes),
         "falta_id_item": [p["archivo"] for p in partes if p["falta_id_item"]]}
    r["markdown"] = markdown(r, lst)
    return r


def markdown(r: dict, lst: Lista) -> str:
    out = ["## Experimento B — Respuestas del .sav", ""]
    out.append(f"**Resultado: {comun.decision(r['go'])}** — {r['porcentaje']}% de las filas de todos los .sav se asocian "
               f"a una empresa de la lista (criterio: ≥ {UMBRAL:.0f}% en cada .sav).")
    if not lst.col_id:
        out += ["", "La lista no trae `id_item`: la asociación se hace por RUT y, como respaldo, por teléfono."]
    out += ["", md_tabla(["Archivo", "Filas", "Asociadas", "%", "Resultado", "Identificador propuesto", "Por método"],
                         [(p["archivo"], p["conteos"]["filas"], p["conteos"].get("asociadas", 0), p["porcentaje"],
                           comun.decision(p["go"]),
                           f"`{p['mapeo']['identificador'].get('variable')}` ({p['mapeo']['identificador'].get('tipo')})"
                           if p["mapeo"].get("identificador") else "ninguno",
                           ", ".join(f"{k}: {v}" for k, v in p["metodos"].items()))
                          for p in r["partes"]])]
    for p in r["partes"]:
        out += ["", f"### {p['archivo']}", ""]
        out.append(f"{p['n_variables']} variables. response_id: `{p['mapeo'].get('response_id') or 'no encontrado'}`. "
                   f"Teléfono usado: `{p['var_tel'] or 'no encontrado'}`.")
        out += ["", "**Bloque estándar**", "", md_tabla(["Variable", "Estado"], p["bloque"])]
        if p["motivos"]:
            out += ["", "**Filas sin asociar por motivo**", "",
                    md_tabla(["Motivo", "Filas"], sorted(p["motivos"].items(), key=lambda x: -x[1]))]
        if p["sin_mapear"]:
            out += ["", "**Códigos sin mapear** (el mapeo se corrige en la pantalla de ingesta)", ""]
            out += [f"- {k.split('=')[0]}: el {k.split('=')[1]} quedó sin mapear: {n} filas" for k, n in p["sin_mapear"].items()]
        if p["resultados"]:
            out += ["", "Resultado mapeado: " + ", ".join(f"{k} {v}" for k, v in sorted(p["resultados"].items(), key=lambda x: -x[1]))
                    + (". Calidad del teléfono: " + ", ".join(f"{k} {v}" for k, v in sorted(p["calidad"].items(), key=lambda x: -x[1]))
                       if p["calidad"] else "") + "."]
        if p["falta_id_item"]:
            out += ["", "Este .sav no trae `EC_ID_ITEM`: se asoció por RUT/teléfono. Para la fase 1 el link de Alchemer "
                        "tiene que llevar las URL variables del bloque estándar."]
    out += ["", "Mapeos propuestos guardados como `fase0/salida/exp_b_mapeo_<archivo>.json` (sirven de plantilla)."]
    if r["detalle"]:
        out.append(f"Filas sin asociar: `{comun.rel(r['detalle'])}`.")
    if r["go"] is False:
        if r["falla_por_url_variables"]:
            out += ["", "**Falla por URL variables faltantes** (spec): el identificador pasa a ser RUT + teléfono y se "
                        "exige el bloque estándar desde el primer estudio de la fase 1."]
        else:
            out += ["", "**No llega al 95%**: revisar los motivos de las filas sin asociar antes de decidir."]
    return "\n".join(out) + "\n"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lista", required=True, help="Lista del estudio (.xlsx/.csv) con id_item (si lo hay), RUT y teléfonos")
    p.add_argument("--sav", nargs="+", required=True, help="Uno o más .sav (uno por parte)")
    p.add_argument("--col-tel", action="append", help="Columna de teléfono de la lista (repetible)")
    p.add_argument("--col-rut", help="Columna de RUT de la lista")
    p.add_argument("--col-id", help="Columna id_item de la lista")
    p.add_argument("--var-tel", help="Variable del .sav con el teléfono usado (por defecto se detecta)")
    p.add_argument("--plantilla", default=str(PLANTILLA), help="Plantilla de mapeo (JSON); '' para no usar")
    p.add_argument("--salida", default=str(comun.SALIDA / "exp_b.md"), help="Markdown del resultado")
    return p


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    try:
        r = ejecutar(a.lista, a.sav, a.col_tel, a.col_rut, a.col_id, a.plantilla or None, a.var_tel)
    except comun.ErrorFase0 as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    comun.escribir(a.salida, r["markdown"])
    print(r["markdown"])
    print(f"→ {comun.rel(a.salida)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
