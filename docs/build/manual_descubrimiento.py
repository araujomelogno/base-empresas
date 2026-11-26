"""Actualiza el manual de Word: qué aporta cada coincidencia del descubrimiento (D58). Guía 29 (remite a la nueva), guía 34
nueva (Qué aporta, filtro, «Omitir las que no aportan», CSV, Qué se agregó y el enlace en la ficha; figuras 44aj a 44an) y
el glosario. Se aplica después de manual_brave.py.

Uso: python docs/build/manual_descubrimiento.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
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


# ── Guía 29: remite a la guía 34 ──
p = par("Revisar y confirmar.")
p.runs[-1].text = p.runs[-1].text.rstrip() + " La columna Qué aporta dice qué agregaría completar cada coincidencia (guía 34)."

# ── Guía 34 nueva, después de la guía 33 ──
ancla = par("Figura 44ai.")._p
bloques = [
    titulo("Guía 34. Buscar empresas nuevas: qué aporta cada coincidencia", T_H3),
    texto([("Qué aporta. ", True), ("En el lote de una búsqueda, cada resultado que coincide con una empresa dice, dato por "
           "dato, qué agregaría «Completar la empresa»: en verde lo nuevo (Teléfono nuevo, Sitio nuevo, Dirección nueva); en "
           "naranja lo distinto que pasaría a ser el vigente («Sitio distinto: reemplaza», con los dos valores al pasar el "
           "mouse); en gris lo distinto que queda solo en la historia («Dirección distinta: solo historia», con el motivo: por "
           "ejemplo, el vigente viene de la sala o tiene más confianza); en texto tenue lo que ya tiene. Si no agrega nada, "
           "dice «No aporta nada».", False)]),
    imagen("82-descubrimiento-resumen", 0.8), caption("44aj", "La tarjeta «coinciden y aportan»"),
    imagen("83-descubrimiento-que-aporta", 1.0), caption("44ak", "Qué aporta cada coincidencia"),
    texto([("Revisar rápido. ", True), ("Las que no aportan nada quedan en «No guardar» aunque la coincidencia sea segura. El "
           "filtro (Todas · Nuevas · Coinciden y aportan · Coinciden sin aporte · Ya guardadas) muestra cada grupo, y «Omitir "
           "las que no aportan» pone «No guardar» en todas esas de una vez. Descargar CSV baja la lista con «Qué aporta» para "
           "revisarla fuera de la aplicación.", False)]),
    imagen("84-descubrimiento-sin-aporte", 1.0), caption("44al", "Coinciden sin aporte, después de «Omitir las que no aportan»"),
    texto([("Después de confirmar. ", True), ("La columna se llama Qué se agregó y muestra lo que pasó de verdad en cada empresa "
           "(Teléfono nuevo o ya lo tenía, Sitio: reemplazó al vigente, Dirección: solo historia…), o «Sin cambios». El aviso "
           "suma cuántas empresas se completaron sin cambios. En la ficha, el sitio o la dirección que vino del lote enlaza a "
           "ese lote.", False)]),
    imagen("86-descubrimiento-que-se-agrego", 1.0), caption("44am", "Qué se agregó, después de confirmar"),
    imagen("87-ficha-dato-del-lote", 0.8), caption("44an", "En la ficha, el dato enlaza al lote"),
]
for el in bloques:
    ancla.addnext(el)
    ancla = el

# ── Glosario ──
g = tabla_con("Término")
agregar_fila(g, ["Qué aporta", "En un lote de «Buscar empresas nuevas», lo que agregaría completar una empresa que coincide: "
                               "dato nuevo, que reemplaza al vigente, que queda solo en la historia o que ya tiene"])

d.save(RUTA)
print("ok")
