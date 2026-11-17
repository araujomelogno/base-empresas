"""Actualiza el manual de Word para SPEC_templates_sorteo_sin_telefono_formatos_csv: guías 7, 10, 15 y 24, y guía 25 nueva.

Uso: python docs/build/manual_templates.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
"""
import copy
import itertools
import sys

import docx
from docx.oxml.ns import qn
from PIL import Image

RUTA, IMG = sys.argv[1], sys.argv[2]
d = docx.Document(RUTA)
ids = itertools.count(9800)


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


# ── Guía 7: armado de la muestra ──
cambiar_imagen("Figura 26.", "16-nueva-muestra", 0.6)
item(par("1 \tFiltros"), [("Filtros", True), (": «+ Agregar filtro» ofrece cualquier dato de la empresa (campos y atributos "
                          "activos), los orígenes de los teléfonos, «Incluir la base provisoria» e «Incluir empresas sin teléfono "
                          "discable». Sin filtros entra toda la base disponible.", False)])
item(par("2 \tEstratos"), [("Estratos", True), (": «+ Agregar estrato» con cualquier dato (para un número, sus tramos) y tocá "
                           "Ver marco disponible.", False)])
item(par("3 \tMarco disponible"), [("Marco disponible", True), (": cuántas empresas cumplen los filtros, cuántas están "
                                   "disponibles, cuántas excluye cada regla y cuántas hay en cada estrato (y cuántas sin teléfono).", False)])
item(par("4 \tTamaño por estrato"), [("Tamaño por estrato", True), (": titulares y reemplazos de cada estrato. «Aplicar a todos» "
                                     "los carga de una vez. Guardar como template… guarda los pasos 1 a 3 (guía 25).", False)])
desde = par("Desde el estudio, + Nueva muestra:")
desde._p.addnext(texto([("Partir de un template.", True), (" Si ya hay templates de sorteo, el primer selector completa los pasos "
                        "1 a 3 con los valores de uno. Todo se puede ajustar antes de sortear (guía 25).", False)]))

reemplazar(par("Filtros por atributo y por origen."), [
    ("Filtros y estratos con cualquier dato.", True),
    (" Cualquier campo de la empresa y cualquier atributo de empresa activo sirve como filtro y como estrato, sin que un "
     "administrador lo habilite antes. Cada tipo de dato tiene su control: botones para las listas, «Contiene», «Es uno de» "
     "o «Tiene dato» para los textos, desde/hasta para números y fechas (detalle en la guía 25).", False)])
cambiar_imagen("Figura 26b.", "54-asistente-filtros", 0.95)
caption_texto("Figura 26b.", "Filtros y estratos con cualquier dato")
p1 = par("1 \tAtributos")
item(p1, [("+ Agregar filtro", True), (": el buscador encuentra el dato; cada filtro tiene «Incluir empresas sin dato».", False)])
p3 = par("3 \tEstratificar por un atributo")
item(p3, [("Incluir empresas sin teléfono discable", True), (": desmarcado por defecto; marcado, entran solo en esta muestra.", False)])
p4 = item_nuevo(p3, 4, [("Tramos", True), (": para estratificar por un número, escribí dónde empieza cada tramo o tocá "
                                          "«Cuartiles» o «Tramos iguales».", False)])
item_nuevo(p4, 5, [("Ver marco disponible", True), (": recalcula el marco y los estratos con los filtros y estratos elegidos.", False)])

# ── Guía 10: formatos del CSV ──
despues = par("Después cargá el CSV en uContact como lista de la campaña")
nuevos10 = [
    texto([("Formato.", True), (" Una fila por empresa (la opción por defecto): cada empresa una vez, con sus números y orígenes "
           "en tel_1, tel_2…; las empresas sin teléfono salen con esas columnas vacías. Una fila por número: una fila por cada "
           "número discable, así que una empresa con 3 números sale 3 veces. La ayuda debajo del botón cambia según la opción, y "
           "el archivo se llama …_por_empresa.csv o …_por_numero.csv.", False)]),
    imagen("55-formatos-csv", 0.5),
    caption("29c", "Formato del CSV"),
]
for el in reversed(nuevos10):
    despues._p.addnext(el)

# ── Guía 15: atributos ──
cambiar_imagen("Figura 40b.", "33-atributos", 0.9)
reemplazar(par("Atributos de empresa. En Administración"), [
    ("Atributos de empresa.", True),
    (" En Administración → Atributos se definen los datos que traen las bases y que no son campos del sistema: cantidad de "
     "empleados, exporta sí/no, cámara a la que pertenece… Un atributo nuevo se puede mapear en la próxima carga y usar para "
     "filtrar y estratificar muestras, sin tocar código y sin habilitarlo antes.", False)])
item(par("1 \t+ Nuevo atributo"), [("+ Nuevo atributo", True), (": nombre visible, tipo (texto, número, fecha o lista de "
                                    "opciones) y sinónimos para que las cargas lo reconozcan solas. La clave se genera sola.", False)])
item(par("2 \tEditar: nombre, opciones, sinónimos, uso"), [("Editar", True), (": nombre, opciones, sinónimos y activo. Desactivar lo saca del mapeo y de los filtros "
                         "y estratos de las muestras nuevas, pero conserva los valores. Solo se borra un atributo sin valores y que "
                         "no se use en una muestra activa.", False)])

# ── Guía 24: nombres de los formatos ──
reemplazar(par("Qué incluir. Al exportar"), [
    ("Qué incluir.", True),
    (" Al exportar, el panel elige los atributos de empresa (todos y ninguno), los números (todos los discables o solo los "
     "verificados) y, si tu usuario tiene el permiso, los contactos (nombre, cargo, área, email, teléfonos y atributos de "
     "contacto). Por defecto, todo; la elección queda guardada en la muestra. Formato: Una fila por empresa (por defecto, con "
     "los teléfonos en tel_1, tel_2…) o Una fila por número (guía 10). Cada exportación queda en Auditoría con las columnas "
     "incluidas.", False)])

# ── Guía 25 ──
ancla = par("Parte 4 · Mantener la base sana", "Heading 1")._p
nuevos = [
    titulo("Guía 25. Templates de sorteo, empresas sin teléfono, filtros y estratos", T_H3),
    texto([("Templates de sorteo.", True), (" Un template guarda los pasos 1 a 3 de una muestra (filtros, estratos con sus tramos "
           "y agrupamientos, y tamaños por estrato) para reusarlos en la próxima ola o en otro estudio. No guarda la semilla, el "
           "estudio, el nombre ni las opciones de exportación. Los usan el jefe de proyecto y el administrador.", False)]),
    tabla_mixta([["Para…", "Hacé esto"],
           ["Crear uno", ("Guardar como template…", " en el paso 3 de Nueva muestra (si partiste de uno, también Actualizar "
                          "template), o Guardar configuración como template en el detalle de una muestra ya creada")],
           ["Usarlo", ("Partir de un template", " en Nueva muestra: completa los pasos 1 a 3 y todo se puede ajustar antes de "
                       "sortear")],
           ["Revisar qué cambió", ("Leé los avisos", ": si el template usa algo que ya no existe (un atributo desactivado, un "
                                   "origen borrado), dice «se quitó el filtro por X: el atributo ya no está activo» y sigue. En el "
                                   "paso 3, un estrato del template sin empresas aparece marcado y los estratos nuevos vienen con "
                                   "tamaño 0 y la marca «nuevo»")],
           ["Administrarlos", ("Templates de sorteo", " (menú): Editar (los pasos 1 a 3, sin sortear), Duplicar, Desactivar y "
                               "Borrar (solo si nunca se usó)")]]),
    imagen("53-templates", 0.95),
    caption("44k", "Templates de sorteo"),
    texto([("Las muestras guardan su propia copia.", True), (" Editar un template después no cambia las muestras que ya lo usaron "
           "ni su reproducibilidad. Crear, editar, aplicar y borrar un template queda en Auditoría.", False)]),
    texto([("Empresas sin teléfono.", True), (" Incluir empresas sin teléfono discable (paso 1) viene desmarcado: como siempre, las "
           "empresas sin un número que se pueda llamar no entran. Marcado, entran solo en esa muestra (para estudios donde el "
           "teléfono se consigue después); las demás reglas se aplican igual. Si la regla está apagada en la Configuración "
           "general, la opción aparece marcada y deshabilitada. La vista previa y el resultado del sorteo dicen cuántas entraron, "
           "por estrato. Con un filtro por origen no entran (no tienen ningún número de ese origen). En la muestra, Empresas de "
           "la muestra → Sin teléfono las lista para completarlas desde la ficha; en cuanto tienen un número, la próxima "
           "exportación lo incluye. El CSV «Una fila por empresa» las trae con los teléfonos vacíos.", False)]),
    texto([("Filtros y estratos.", True), (" Sirve cualquier dato de la empresa: los campos fijos (razón social, fantasía, "
           "naturaleza, CIIU completo, a 2 y a 1 dígito, tamaño, departamento, localidad, dirección, web y estado) y todos los "
           "atributos de empresa activos. Los atributos de contacto no se usan. Los filtros se combinan con «y», y cada uno tiene "
           "«Incluir empresas sin dato».", False)]),
    tabla_mixta([["Si el dato es…", "Filtrás y estratificás así"],
           ["Una lista (y naturaleza, tamaño, departamento, estado)", ("Una o varias opciones", "; un estrato por opción")],
           ["Un texto (y razón social, localidad, dirección, web, CIIU)",
            ("«Contiene…», «Es uno de…», «Tiene dato» o «No tiene dato»", " («Es uno de» muestra los valores que existen y "
             "cuántas empresas tienen cada uno); un estrato por valor, sin distinguir mayúsculas, tildes ni espacios. Con muchos "
             "valores, «Agrupar en Otros los de menos de N empresas» o «Los N más frecuentes y el resto en Otros»")],
           ["Un número", ("Desde / hasta y tramos", ": 1, 5, 20, 100 da 1–4, 5–19, 20–99 y 100 o más; «Cuartiles» y «Tramos "
                          "iguales» los sugieren a partir del marco")],
           ["Una fecha", ("Desde / hasta", "; estratos por año, por semestre o por tramos")]]),
    texto([("Estratos combinados.", True), (" Se pueden combinar varios datos (tamaño × departamento × tramo de empleados). Las "
           "empresas sin dato van al estrato «(sin dato)». Si hay demasiados estratos o un texto con muchos valores, la vista "
           "previa avisa. El estrato de cada empresa se calcula al sortear y queda congelado: cambiar después un dato de una "
           "empresa sorteada no altera Verificar reproducibilidad.", False)]),
]
for el in nuevos:
    ancla.addprevious(el)

# Para quién es cada guía
t = d.tables[1]
filas = [r.cells[0].text.strip() for r in t.rows]
celda(t, filas.index("Jefe/a de proyecto"), 2, "Guías 6 a 8, 24, 25 y el recorrido completo (parte 5)")
celda(t, filas.index("Administrador/a"), 2, "Guías 14 a 18, 22, 25 y la parte 4")

# Glosario
g = tabla_con("Término")
tr = copy.deepcopy(g.rows[1]._tr)
g._tbl.append(tr)
for j, v in enumerate(("Template de sorteo", "Filtros, estratos y tamaños guardados para reusar en otra muestra; la muestra "
                                             "guarda su propia copia")):
    p = g.rows[-1].cells[j].paragraphs[0]
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)
    p.runs[0].text = v

d.save(RUTA)
print("ok")
