"""Actualiza el manual de Word: cargas grandes por lotes (D50). Agrega la guía 30, los estados nuevos de una carga en la
guía 3, el parámetro «Cargas grandes» en la guía 15 y una fila en Solución de problemas.

Uso: python docs/build/manual_lotes.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
"""
import copy
import itertools
import sys

import docx
from docx.oxml.ns import qn
from PIL import Image

RUTA, IMG = sys.argv[1], sys.argv[2]
d = docx.Document(RUTA)
ids = itertools.count(9980)


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


# ── Guía 3: estados nuevos y borrado en cualquier estado ──
estados = tabla_con("Estado")
for fila in (["Interrumpida", "Se cortó a mitad de camino; lo de los lotes terminados quedó · Reanudar, Deshacer o Borrar"],
             ["Deshaciendo", "Se está deshaciendo, por pasos · esperar; la barra muestra el avance"],
             ["Borrando", "Se está borrando, por pasos · esperar; si se cortó, volver a tocar Borrar carga"]):
    agregar_fila(estados, fila)

reemplazar(par("Una carga trabada también se borra."), [
    ("Borrar una carga en cualquier estado.", True),
    (" Borrar carga funciona también con la carga corriendo: el modal dice qué tarea se cancela; el lote en curso se "
     "revierte y lo que aplicaron los lotes anteriores se borra igual. El borrado corre por pasos (la carga queda "
     "«borrando»); si se corta, volver a tocar Borrar carga lo retoma desde donde quedó. Las cargas grandes se procesan "
     "por lotes: ver la guía 30.", False)])

# ── Guía 15: el parámetro de las cargas grandes ──
agregar_fila(tabla_con("Parámetro"), [
    "Cargas grandes", "Filas por lote (entre 500 y 20.000), pausa entre lotes y minutos sin avanzar para dar una carga por "
    "interrumpida (guía 30)", "5.000 filas, 1 s, 35 minutos"])

# ── Solución de problemas ──
problemas = tabla_con("Qué pasa")
agregar_fila(problemas, ["Una carga grande quedó «interrumpida»", "Falló un lote, se canceló o se reinició el servidor",
                         "Abrí su detalle: dice cuántos lotes se aplicaron y el error. Reanudar sigue desde ahí sin repetir "
                         "nada; Deshacer carga quita lo aplicado (guía 30)"])
agregar_fila(problemas, ["«Esperando a que termine la carga #N»", "Se procesa una carga grande a la vez",
                         "Nada: arranca sola cuando termina la otra"])

# ── Guía 30: Cargas grandes por lotes (después de la guía 29) ──
ancla = par("Después. Las empresas nuevas entran")._p
T_H3_30 = par("Guía 29.", "Heading 3")
bloques = [
    titulo("Guía 30. Cargas grandes por lotes", T_H3_30),
    texto([("Por lotes.", True), (" Una carga se procesa por lotes de 5.000 filas (se cambia en Configuración → Cargas "
           "grandes). Cada lote es una transacción: si algo se corta, lo que hicieron los lotes terminados queda y no hay "
           "que empezar de nuevo. Así se pueden cargar bases de cientos de miles de empresas. El preview, la confirmación, "
           "Deshacer carga y Borrar carga van todos por lotes o por pasos.", False)]),
    texto([("El avance.", True), (" La barra dice en qué lote va («Lote 13 de 38 · 60.000 de 190.000 filas») y el detalle, "
           "cuántos lotes se aplicaron y cuánto tardó el más lento. Después del preview, el detalle dice cuánto tardó: la "
           "confirmación suele tardar algo parecido. Mientras tanto se puede seguir usando la aplicación.", False)]),
    imagen("62-carga-por-lotes"),
    caption("44r", "Una carga grande aplicándose por lotes"),
    texto([("El mismo RUT, en el mismo lote.", True), (" Las filas con el mismo RUT van siempre juntas, aunque estén lejos "
           "en el archivo: cuentan una sola alta. Las filas sin RUT van al final; si son muchas, el preview avisa que sus "
           "conteos son aproximados (dos filas sin RUT del mismo archivo podrían coincidir entre sí).", False)]),
    texto([("Una carga grande a la vez.", True), (" Si confirmás, deshacés o borrás una carga mientras otra está corriendo, "
           "la segunda queda en cola con el aviso «Esperando a que termine la carga #N» y arranca sola cuando termina la "
           "primera.", False)]),
    texto([("Si queda «interrumpida».", True), (" Pasa si un lote falla, si se cancela, o si la tarea no avanza durante "
           "35 minutos (por ejemplo, porque se reinició el servidor). El detalle dice cuántos lotes se aplicaron y el error "
           "del lote que falló.", False)]),
    imagen("63-carga-interrumpida"),
    caption("44s", "Una carga interrumpida: 4 de 10 lotes aplicados"),
    tabla_mixta([["Para…", "Tocá…"],
                 ["Seguir desde el lote que falló", ("Reanudar", ". No repite lo ya aplicado: el resultado es el mismo que si no se hubiera cortado")],
                 ["Dejar la base como antes de la carga", ("Deshacer carga", ". Quita lo que aplicaron los lotes terminados")],
                 ["Eliminar la carga y lo que aplicó", ("Borrar carga", " (administrador)")]]),
    texto([("", False)]),
    texto([("Configuración.", True), (" El administrador ajusta las filas por lote (entre 500 y 20.000; más chico, más "
           "lotes pero cada uno más corto), la pausa entre lotes (para que la base respire) y los minutos sin avanzar para "
           "dar una carga por interrumpida.", False)]),
    imagen("64-config-cargas", 0.8),
    caption("44t", "Configuración de las cargas grandes"),
]
for el in bloques:
    ancla.addnext(el)
    ancla = el

# ── «Cómo usar este manual»: la guía 30 es del data steward y del administrador ──
for t in d.tables:
    for i, r in enumerate(t.rows):
        v = r.cells[2].text if len(r.cells) > 2 else ""
        if r.cells[0].text == "Data steward" and v.endswith("26 a 29 y la parte 4 (rutinas)"):
            celda(t, i, 2, v.replace("26 a 29", "26 a 30"))
        if r.cells[0].text == "Administrador/a" and v.endswith("25 a 29 y la parte 4"):
            celda(t, i, 2, v.replace("25 a 29", "25 a 30"))

d.save(RUTA)
print("ok")
