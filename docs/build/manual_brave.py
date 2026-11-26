"""Actualiza el manual de Word: enriquecimiento (D57). Guía 27 (el paso 5 en la cascada y el origen nuevo), guía 33 nueva
(el motivo de cada error, la pestaña «Con error» y la búsqueda web con Claude; figuras 44ad a 44ai) y el glosario. Se aplica
después de manual_muestras.py.

Uso: python docs/build/manual_brave.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
"""
import copy
import itertools
import sys

import docx
from docx.oxml.ns import qn
from PIL import Image

RUTA, IMG = sys.argv[1], sys.argv[2]
d = docx.Document(RUTA)
ids = itertools.count(9999)


def par(prefijo, estilo=None):
    return next(p for p in d.paragraphs if p.text.strip().startswith(prefijo) and (estilo is None or p.style.name == estilo))


T_TEXTO = par("Corregir un mapeo.")
RPR_NEG, RPR_NOR = copy.deepcopy(T_TEXTO.runs[0]._r.rPr), copy.deepcopy(T_TEXTO.runs[1]._r.rPr)
T_H2 = par("Administrador/a", "Heading 2")
T_H3 = par("Guía 18.", "Heading 3")
T_CAPTION = par("Figura 44.")
T_IMAGEN = d.paragraphs[[i for i, p in enumerate(d.paragraphs) if p.text.startswith("Figura 44.")][0] - 1]
assert T_IMAGEN._p.xpath(".//w:drawing")
ANCHO_MAX = int(T_IMAGEN._p.find(".//" + qn("wp:extent")).get("cx"))


def _limpiar(el):
    for h in list(el):
        if h.tag != qn("w:pPr"):
            el.remove(h)


def _run(el, texto, rpr):
    r = el.makeelement(qn("w:r"), {})
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    t = r.makeelement(qn("w:t"), {qn("xml:space"): "preserve"})
    t.text = texto
    r.append(t)
    el.append(r)


def texto(segs, plantilla=T_TEXTO):
    el = copy.deepcopy(plantilla._p)
    _limpiar(el)
    for t, neg in segs:
        _run(el, t, RPR_NEG if neg else RPR_NOR)
    return el


def titulo(t, plantilla):
    el = copy.deepcopy(plantilla._p)
    rpr = plantilla.runs[0]._r.rPr
    _limpiar(el)
    _run(el, t, rpr)
    return el


def imagen(nombre, ancho=1.0):
    el = copy.deepcopy(T_IMAGEN._p)
    rid, _ = d.part.get_or_add_image(f"{IMG}/{nombre}.png")
    el.find(".//" + qn("a:blip")).set(qn("r:embed"), rid)
    w, h = Image.open(f"{IMG}/{nombre}.png").size
    cx = int(ANCHO_MAX * ancho)
    cy = int(cx * h / w)
    for tag in ("wp:extent", "a:ext"):
        e = el.find(".//" + qn(tag))
        e.set("cx", str(cx))
        e.set("cy", str(cy))
    pr = el.find(".//" + qn("wp:docPr"))
    pr.set("id", str(next(ids)))
    pr.set("name", nombre)
    return el


def caption(numero, t):
    el = copy.deepcopy(T_CAPTION._p)
    runs = el.findall(qn("w:r"))
    runs[0].find(qn("w:t")).text = f"Figura {numero}. "
    runs[1].find(qn("w:t")).text = t
    for r in runs[2:]:
        el.remove(r)
    return el


def tabla(filas):
    plantilla = next(t for t in d.tables if t.rows[0].cells[0].text.strip() == "Para…")
    tbl = copy.deepcopy(plantilla._tbl)
    trs = tbl.findall(qn("w:tr"))
    for tr in trs[2:]:
        tbl.remove(tr)
    for _ in filas[2:]:
        tbl.append(copy.deepcopy(trs[1]))
    t = docx.table.Table(tbl, plantilla._parent)
    for i, f in enumerate(filas):
        for j, v in enumerate(f):
            p = t.rows[i].cells[j].paragraphs[0]
            for r in p.runs[1:]:
                r._r.getparent().remove(r._r)
            p.runs[0].text = v
    return tbl


def celda(t, fila, col, valor):
    p = t.rows[fila].cells[col].paragraphs[0]
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)
    p.runs[0].text = valor


def tabla_con(primera):
    return next(t for t in d.tables if t.rows[0].cells[0].text.strip() == primera)


def reemplazar(p, segs):
    el = texto(segs, p)
    p._p.addprevious(el)
    p._p.getparent().remove(p._p)




_paso = par("1 \tFiltros")._p.findall(qn("w:r"))
RPR_PASO_NEG, RPR_PASO_NOR = copy.deepcopy(_paso[3].find(qn("w:rPr"))), copy.deepcopy(_paso[4].find(qn("w:rPr")))
_celda = tabla_con("Para…").rows[1].cells[1].paragraphs[0].runs
RPR_CELDA_NOR = copy.deepcopy(_celda[1]._r.rPr)


def tabla_mixta(filas):
    """Como tabla(), pero la segunda columna lleva una parte en negrita y otra normal: (negrita, normal)."""
    tbl = tabla([[f[0], f[1] if isinstance(f[1], str) else f[1][0]] for f in filas])
    t = docx.table.Table(tbl, None)
    for i, f in enumerate(filas):
        if not isinstance(f[1], str):
            el = t.rows[i].cells[1].paragraphs[0]._p
            _run(el, f[1][1], RPR_CELDA_NOR)
    return tbl


def item(p, segs):
    """Reescribe un paso numerado (« 1 \\t…») conservando el número y el tabulador."""
    runs = p._p.findall(qn("w:r"))
    rpr_neg, rpr_nor = copy.deepcopy(RPR_PASO_NEG), copy.deepcopy(RPR_PASO_NOR)
    for r in runs[3:]:
        p._p.remove(r)
    if runs[2].find(qn("w:t")) is not None and runs[2].find(qn("w:t")).text not in (None, "\t"):
        runs[2].find(qn("w:t")).text = "\t"
    for t, neg in segs:
        _run(p._p, t, rpr_neg if neg else rpr_nor)


def item_nuevo(p, numero, segs):
    """Clona el paso p a continuación de sí mismo con otro número y otro texto."""
    el = copy.deepcopy(p._p)
    p._p.addnext(el)
    q = docx.text.paragraph.Paragraph(el, p._parent)
    el.findall(qn("w:r"))[1].find(qn("w:t")).text = f"{numero} "
    item(q, segs)
    return q


def cambiar_imagen(caption_prefijo, nombre, ancho=1.0):
    ps = d.paragraphs
    i = next(i for i, p in enumerate(ps) if p.text.startswith(caption_prefijo))
    viejo = ps[i - 1]._p
    assert viejo.xpath(".//w:drawing"), caption_prefijo
    viejo.addprevious(imagen(nombre, ancho))
    viejo.getparent().remove(viejo)


def caption_texto(prefijo, t):
    p = par(prefijo)
    p.runs[1].text = t
    for r in p.runs[2:]:
        r._r.getparent().remove(r._r)




def agregar_fila(t, valores):
    """Clona la última fila de la tabla t y le pone otros valores."""
    tr = copy.deepcopy(t.rows[-1]._tr)
    t._tbl.append(tr)
    for j, v in enumerate(valores):
        celda(t, len(t.rows) - 1, j, v)


# ── Guía 27: el paso 5 en la cascada y el origen nuevo ──
reemplazar(par("Qué hace. Busca, para empresas sin teléfono"), [("Qué hace. ", True), ("Busca, para empresas sin teléfono, un "
     "teléfono, el sitio web, la dirección y un email institucional (info@, contacto@…), de lo más barato a lo más caro: lo que "
     "ya hay en la base (gratis), Google Places, una búsqueda web (solo si falta el sitio), la lectura del sitio con Claude (solo "
     "si todavía falta el teléfono) y, si está activada, la búsqueda web con Claude como último intento (guía 33). Por defecto "
     "se corta apenas consigue un teléfono.", False)])
p = par("Qué pasa con lo encontrado.")
p.runs[1].text = p.runs[1].text.replace("con origen Google Places o Sitio web:",
                                        "con origen Google Places, Sitio web o Búsqueda web (Claude):")
assert "Búsqueda web (Claude)" in p.text

# ── Guía 33 nueva, después de la guía 32 ──
ancla = par("Figura 44ac.")._p
bloques = [
    titulo("Guía 33. Enriquecimiento: el motivo de cada error y la búsqueda web con Claude", T_H3),
    texto([("El motivo del error. ", True), ("Cuando un paso de una corrida da error, debajo de su fila en Pasos se ve el motivo "
           "que devolvió el proveedor y cuántas veces pasó (por ejemplo, «Google Places respondió 400: API key not valid… × 1»); "
           "si hubo más de uno, el resto aparece al pasar el mouse. Los mensajes nunca muestran la clave.", False)]),
    imagen("76-pasos-motivo-error", 0.55), caption("44ad", "El motivo del error debajo de cada paso"),
    texto([("Empresas con error. ", True), ("Una empresa que quedó sin teléfono porque algún paso falló tiene el resultado «error» "
           "y aparece en la pestaña Con error; el motivo se ve al pasar el mouse sobre el chip. «rechazó la clave» pide cargar una "
           "clave nueva en Configuración; «no respondió» suele ser un corte de red: volvé a enriquecer esas empresas más tarde.", False)]),
    imagen("77-empresas-con-error", 0.8), caption("44ae", "Empresas con error en una corrida"),
    texto([("Búsqueda web con Claude. ", True), ("Es el último paso, solo para las empresas que siguen sin teléfono después de "
           "Places, la búsqueda web y la lectura del sitio. Claude busca en la web (hasta 3 búsquedas por empresa) y propone "
           "teléfonos, cada uno con la página donde lo encontró. Solo entran los que se comprueban: el sistema abre esa página y "
           "el número tiene que estar escrito ahí; en un directorio, además, junto al nombre de la empresa. Los demás se "
           "descartan como «no verificados». En Pasos, la fila Búsqueda web (Claude) dice cuántos teléfonos propuso, cuántos se "
           "verificaron y cuántas búsquedas hizo.", False)]),
    imagen("78-pasos-busqueda-web", 0.55), caption("44af", "El paso 5 en una corrida"),
    texto([("Antes de aprobar. ", True), ("Con el paso activado, la estimación lo muestra aparte: «Búsqueda web (Claude): hasta "
           "US$X», con lo que se espera gastar. Antes de cada empresa se reserva lo máximo que puede costar; se cobra lo que "
           "realmente usó. Si no alcanza el tope, la corrida se detiene antes de llamar.", False)]),
    imagen("81-estimacion-busqueda-web", 0.6), caption("44ag", "La estimación con la búsqueda web"),
    texto([("En la ficha. ", True), ("Los teléfonos que entran tienen el origen Búsqueda web (Claude) y el enlace página fuente, "
           "a la página donde aparece el número. Se miden en Rendimiento por origen y se quitan con Deshacer, como los de los "
           "demás pasos.", False)]),
    imagen("80-ficha-pagina-fuente", 1.0), caption("44ah", "El origen y la página fuente en la ficha"),
    texto([("Configuración (administrador). ", True), ("En Configuración → Enriquecimiento: Búsqueda web con Claude (apagada "
           "al empezar; usa la misma clave de Claude), las búsquedas máximas por empresa (3) y el precio por búsqueda (US$0,01, "
           "o sea US$10 cada 1.000). Los tokens se cobran con los precios de Claude. Cuesta unos US$0,03 a 0,06 por empresa que "
           "llega a este paso.", False)]),
    imagen("79-config-busqueda-web", 0.8), caption("44ai", "La búsqueda web con Claude en Configuración"),
]
for el in bloques:
    ancla.addnext(el)
    ancla = el

# ── Glosario ──
g = tabla_con("Término")
agregar_fila(g, ["Búsqueda web (Claude)", "Último paso del enriquecimiento: Claude busca en la web y solo entran los teléfonos "
                                          "que aparecen en la página que cita"])

d.save(RUTA)
print("ok")
