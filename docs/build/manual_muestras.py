"""Actualiza el manual de Word: armado de muestras (D56). Guía 7 (pasos 1, 3 y 4 y la opción que ya no existe), guía 25
(empresas sin teléfono), guía 32 nueva (aviso de espera, sorteables y no sorteables, Excel de tamaños y sorteo
sistemático; figuras 44aa a 44ac) y el glosario. Se aplica después de manual_rendimiento.py.

Uso: python docs/build/manual_muestras.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
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


# ── Guía 7: pasos 1 y 3, y la opción que ya no existe ──
item(par("1 \tFiltros:"), [("Filtros: ", True), ("«+ Agregar filtro» ofrece cualquier dato de la empresa (campos y atributos "
     "activos), los orígenes de los teléfonos, «Incluir la base provisoria» y «Como máximo una empresa por grupo económico» "
     "(marcada; guía 28). Sin filtros entra toda la base.", False)])
item(par("3 \tMarco disponible:"), [("Marco disponible: ", True), ("cuántas empresas cumplen los filtros, cuántas son sorteables "
     "y cuántas no, con el motivo, y por estrato el total, las sorteables y las no sorteables (guía 32).", False)])
item(par("4 \tTamaño por estrato:"), [("Tamaño por estrato: ", True), ("el método de sorteo (aleatorio o sistemático por CIIU) y "
     "titulares y reemplazos de cada estrato: a mano, con «Aplicar a todos» o con el Excel de tamaños (guía 32). Guardar como "
     "template… guarda los pasos 1 a 3 (guía 25).", False)])
item(par("3 \tIncluir empresas sin teléfono discable:"), [("Incluir empresas sin teléfono discable: ", True),
     ("esta opción ya no existe (guía 32): las empresas sin teléfono son no sorteables.", False)])
reemplazar(par("Empresas sin teléfono. Incluir empresas"), [("Empresas sin teléfono. ", True), ("No se sortean: aparecen en el "
     "marco como no sorteables, y «Descargar no sorteables» las lista para trabajarlas (guía 32). Solo entran a las muestras si "
     "la regla «Excluir empresas sin teléfono discable» está apagada en Configuración. Las muestras sorteadas antes de "
     "noviembre de 2026 con la opción «Incluir empresas sin teléfono» no cambian.", False)])

# ── Guía 32 nueva, después de la guía 31 ──
ancla = par("Figura 44z.")._p
bloques = [
    titulo("Guía 32. Armar muestras: marco completo, Excel de tamaños y sorteo sistemático", T_H3),
    texto([("Mientras consulta. ", True), ("«Ver marco disponible», elegir un template y «Crear y sortear» pueden tardar varios "
           "segundos con la base grande. El botón queda deshabilitado y un aviso dice qué está haciendo, con los segundos que "
           "lleva; a los 20 segundos agrega «La base es grande; puede tardar hasta 2 minutos». Un doble clic hace una sola "
           "consulta. Si cambiás un filtro después de ver el marco, aparece «Volvé a consultar el marco».", False)]),
    imagen("73-espera-marco", 0.6), caption("44aa", "Mientras se consulta el marco"),
    texto([("Sorteables y no sorteables. ", True), ("El marco tiene todas las empresas que cumplen los filtros. Por estrato se ve "
           "el Total, las Sorteables (contra las que se comparan los tamaños pedidos) y las No sorteables, con el motivo al pasar "
           "el mouse: sin teléfono discable, enfriamiento, muestra activa, no llamar, naturaleza excluida, cerrada o sin teléfono "
           "del origen elegido. «Descargar no sorteables» baja la lista con su estrato y su motivo.", False)]),
    texto([("Ya no existe «Incluir empresas sin teléfono». ", True), ("Una empresa sin teléfono nunca se sortea, salvo que la regla "
           "general esté apagada en Configuración. Un template o un borrador que tenían la opción avisan y se sortean sin ella.", False)]),
    texto([("Excel de tamaños. ", True), ("En el paso 3, Descargar Excel baja una hoja con una fila por estrato: total, sorteables, "
           "no sorteables, Titulares y Reemplazos (en amarillo, las únicas editables), «¿Alcanza?» y un tamaño proporcional "
           "sugerido. Completalos (también con fórmulas) e Importar Excel los carga en la tabla, con un resumen de avisos y "
           "errores: un estrato que no está se ignora, una celda vacía es 0, un negativo o un decimal da error solo en esa fila. "
           "Importar no guarda: revisá y tocá Crear y sortear.", False)]),
    texto([("Sorteo sistemático por CIIU. ", True), ("En el paso 3, Método de sorteo. Aleatorio simple es el de siempre. "
           "Sistemático ordena cada estrato por CIIU completo y toma una empresa cada N/n con un arranque al azar: la muestra "
           "recorre todas las actividades (10 CIIU de 100 empresas y 50 titulares dan 5 por CIIU). El reemplazo de cada titular "
           "es su vecino en la lista: en Empresas de la muestra dice «Vecino de …», y sobre un titular, Liberar su reemplazo "
           "libera justo ese. «Verificar reproducibilidad» funciona igual con los dos métodos.", False)]),
    imagen("74-paso3-excel-metodo", 0.8), caption("44ab", "Paso 3: método, Excel de tamaños y sorteables por estrato"),
    imagen("75-vecino-de", 0.8), caption("44ac", "Reemplazos «Vecino de» en una muestra sistemática"),
]
for el in bloques:
    ancla.addnext(el)
    ancla = el

# ── Glosario ──
g = tabla_con("Término")
agregar_fila(g, ["Sorteable", "Empresa del marco que puede salir sorteada: no la bloquea ninguna regla ni el filtro de origen"])
agregar_fila(g, ["Sorteo sistemático", "Ordena el estrato por CIIU y toma una empresa cada N/n: la muestra recorre todas las "
                                       "actividades. El reemplazo de cada titular es su vecino en la lista"])

d.save(RUTA)
print("ok")
