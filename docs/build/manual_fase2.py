"""Actualiza el manual de Word para SPEC_fase2_enriquecimiento: guía 7 (grupo económico en el sorteo) y guías 26 a 29
(calidad de la base, enriquecer empresas, posibles duplicados y grupos económicos, buscar empresas nuevas).

Uso: python docs/build/manual_fase2.py docs/Manual_de_usuario_Base_de_Empresas.docx docs/manual/img
"""
import copy
import itertools
import sys

import docx
from docx.oxml.ns import qn
from PIL import Image

RUTA, IMG = sys.argv[1], sys.argv[2]
d = docx.Document(RUTA)
ids = itertools.count(9900)


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




# ── Guía 7: la opción de grupo económico en el paso 1 ──
item(par("1 \tFiltros"), [("Filtros", True), (": «+ Agregar filtro» ofrece cualquier dato de la empresa (campos y atributos "
                          "activos), los orígenes de los teléfonos, «Incluir la base provisoria», «Incluir empresas sin teléfono "
                          "discable» y «Como máximo una empresa por grupo económico» (marcada; guía 28). Sin filtros entra toda "
                          "la base disponible.", False)])

# ── Guías 26 a 29 ──
ancla = par("Parte 4 · Mantener la base sana", "Heading 1")._p
nuevos = [
    titulo("Guía 26. Calidad de la base", T_H3),
    texto([("Dónde está.", True), (" Administración → Calidad de la base (data steward, jefes y administrador). Una tarjeta por "
           "dimensión, con su meta, su estado (cumple, cerca o no cumple) y la evolución de los últimos meses. Cada indicador "
           "tiene Ver la lista: las empresas, teléfonos o pares que lo incumplen, con enlace a cada ficha. Es la lista de "
           "trabajo de la semana.", False)]),
    tabla([["Dimensión", "Qué mide y cuál es la meta"],
           ["Validez", "RUT con dígito verificador correcto y teléfonos en formato uruguayo válido: 100 %"],
           ["Unicidad", "Una empresa por RUT, un teléfono por número (100 %) y los posibles duplicados sin resolver (0)"],
           ["Completitud", "Empresas disponibles con al menos 1 teléfono discable, CIIU y departamento: 90 % o más"],
           ["Exactitud", "Teléfonos verificados por la sala sobre el total de discables: que suba cada trimestre"],
           ["Actualidad", "Teléfonos discables verificados en los últimos 24 meses: 70 % o más"],
           ["Consistencia", "Naturaleza jurídica que no coincide con la razón social (por ejemplo, «SRL» con «… S.A.»): alertas revisadas"],
           ["Base provisoria", "Empresas sin RUT y cuántas tienen candidata en la definitiva (informativo)"]]),
    imagen("56-calidad", 0.75),
    caption("44l", "Calidad de la base"),
    texto([("Consistencia.", True), (" Cada alerta tiene Revisada: corregí la naturaleza o la razón social en la ficha, o "
           "marcala si está bien así. Vuelve a aparecer si después cambia alguno de los dos datos.", False)]),
    texto([("Evolución.", True), (" Todos los días, temprano, el sistema guarda una foto de los indicadores; la evolución se "
           "arma con esas fotos. El administrador puede guardar la de hoy con Guardar la foto de hoy.", False)]),
    texto([("Enriquecimiento.", True), (" La última tarjeta muestra el gasto del mes contra el tope mensual, el gasto por "
           "proveedor y el costo por teléfono verificado: lo gastado en enriquecimiento sobre los teléfonos de Google Places o "
           "del sitio web que la sala después verificó. La meta es US$0,10 o menos.", False)]),

    titulo("Guía 27. Enriquecer empresas", T_H3),
    texto([("Qué hace.", True), (" Busca, para empresas sin teléfono, un teléfono, el sitio web, la dirección y un email "
           "institucional (info@, contacto@…), de lo más barato a lo más caro: lo que ya hay en la base (gratis), Google "
           "Places, una búsqueda web (solo si falta el sitio) y la lectura del sitio con Claude (solo si todavía falta el "
           "teléfono). Por defecto se corta apenas consigue un teléfono.", False)]),
    tabla_mixta([["Desde…", "Cómo"],
                 ["Empresas", ("Enriquecer estas N empresas", ", al pie de la lista, con los filtros de la pantalla (hay "
                               "filtros nuevos Teléfono y Sitio web). Data steward y administrador")],
                 ["La ficha", ("✨ Enriquecer", ": solo esa empresa. Data steward y administrador")],
                 ["Una muestra", ("✨ Enriquecer", ": las empresas sin teléfono discable, o todas. También el jefe de proyecto")]]),
    texto([("Antes de gastar.", True), (" Se muestra la estimación: cuántas empresas se enriquecen y cuántas se saltean y por "
           "qué (ya tienen un teléfono verificado o discable, se enriquecieron en los últimos 90 días, están en no llamar, o "
           "son provisorias con candidata: conviene fusionarlas), el costo máximo y el esperado, cuántas llamadas entran en "
           "las gratuitas del mes y cuánto queda del tope mensual. Si el máximo supera lo permitido, elegís cuántas "
           "enriquecer (las primeras o al azar). Nada se gasta hasta Aprobar y enriquecer.", False)]),
    imagen("57-estimacion", 0.6),
    caption("44m", "Estimación antes de enriquecer"),
    texto([("La corrida.", True), (" Avanza empresa por empresa y se puede Cancelar. Antes de cada llamada paga se verifica el "
           "tope: si se llega, la corrida se detiene («detenida por tope»). En los dos casos lo conseguido queda guardado. Al "
           "terminar muestra cuántas empresas tienen teléfono nuevo, el gasto real por proveedor y la lista de empresas con "
           "su resultado. Base de datos → Enriquecimiento lista todas las corridas.", False)]),
    imagen("58-corrida", 0.85),
    caption("44n", "Una corrida de enriquecimiento"),
    texto([("Qué pasa con lo encontrado.", True), (" Los teléfonos entran sin verificar, con origen Google Places o Sitio web: "
           "salen en el CSV como cualquier teléfono discable y los verifica la sala con el .sav; la ficha dice de qué corrida "
           "salió cada uno. El sitio, la dirección y el email entran con confianza 30 y nunca reemplazan un dato de una carga "
           "(50) ni de la sala (80). Si el sitio es de un estudio contable o jurídico, sus teléfonos quedan como intermediario "
           "sospechoso, con el motivo. Nunca se guardan datos personales (nombres, celulares o emails de personas). Deshacer, "
           "en la corrida, quita lo que trajo, salvo los teléfonos que la sala ya verificó.", False)]),
    texto([("Configuración (administrador).", True), (" Configuración → Enriquecimiento: el estado y la clave de cada "
           "proveedor (Google Places, Brave Search y Claude; la clave va a Secret Manager y no se vuelve a mostrar; sin clave, "
           "la cascada lo saltea), los precios, el tope mensual duro (US$100 al empezar), el tope por corrida (US$20), el "
           "máximo de empresas por corrida (2.000), la confianza, los días antes de volver a enriquecer y dónde se corta la "
           "cascada. Todo, salvo las claves, se guarda con Guardar nueva versión.", False)]),
    imagen("61-config-enriquecimiento", 0.6),
    caption("44o", "Configuración del enriquecimiento"),

    titulo("Guía 28. Posibles duplicados y grupos económicos", T_H3),
    texto([("La bandeja.", True), (" Base de datos → Posibles duplicados muestra pares de empresas con RUT distinto que "
           "comparten un teléfono, el sitio web, la dirección (con el departamento) o una razón social casi igual. Se detectan "
           "todos los días; Detectar ahora lo hace en el momento. Los pares con más de 14 días sin resolver se marcan.", False)]),
    tabla([["Para…", "Hacé esto"],
           ["Son la misma empresa", "Fusionar: queda … (elegí cuál queda). Es la fusión de siempre: se deshace desde la ficha"],
           ["Son empresas distintas del mismo grupo", "Son grupo económico (con un nombre opcional). Quedan relacionadas, sin fusionarse"],
           ["No tienen nada que ver", "Sin relación: el par no se vuelve a proponer"]]),
    imagen("59-duplicados", 0.85),
    caption("44p", "Posibles duplicados"),
    texto([("En la ficha y en el sorteo.", True), (" La ficha de una empresa de un grupo muestra el grupo y las otras "
           "empresas que lo forman, y permite cambiarle el nombre o sacarla del grupo. En Nueva muestra, «Como máximo una "
           "empresa por grupo económico» viene marcada: si sale una empresa de un grupo que ya tiene otra en la muestra, se "
           "saltea y sigue la siguiente del orden. Verificar reproducibilidad sigue funcionando.", False)]),

    titulo("Guía 29. Buscar empresas nuevas", T_H3),
    texto([("Buscar.", True), (" Base de datos → Buscar empresas nuevas: escribí la búsqueda («imprentas en Salto») o armala "
           "con rubro, departamento y localidad, y elegí cuántas páginas pedir (20 resultados cada una; cada página es una "
           "llamada paga). Ver el costo muestra cuánto cuesta, con los mismos topes del enriquecimiento; Buscar hace las "
           "llamadas.", False)]),
    texto([("Revisar y confirmar.", True), (" Cada resultado queda en uno de tres casos: nueva (se ofrece el alta en la base "
           "provisoria), coincide con una empresa por teléfono, sitio o nombre y dirección (se ofrece completarla; si la "
           "coincidencia es por similitud, revisala) o ya guardada. Elegí qué hacer con cada uno y tocá Confirmar: nada se "
           "guarda antes. El lote Descubrimiento #N se puede Deshacer.", False)]),
    imagen("60-descubrimiento", 0.85),
    caption("44q", "Buscar empresas nuevas"),
    texto([("Después.", True), (" Las empresas nuevas entran a la base provisoria con código P-, teléfono sin verificar (origen "
           "Google Places) y el rubro buscado, y siguen el circuito de siempre: agregar el RUT o fusionar (guía 20).", False)]),
]
for el in nuevos:
    ancla.addprevious(el)

# Para quién es cada guía
t = d.tables[1]
filas = [r.cells[0].text.strip() for r in t.rows]
celda(t, filas.index("Data steward"), 2, "Guías 1 a 5, 19 a 22, 26 a 29 y la parte 4 (rutinas)")
celda(t, filas.index("Jefe/a de proyecto"), 2, "Guías 6 a 8, 24 a 28 y el recorrido completo (parte 5)")
celda(t, filas.index("Administrador/a"), 2, "Guías 14 a 18, 22, 25 a 29 y la parte 4")

# Glosario
g = tabla_con("Término")
for termino, sig in (("Enriquecimiento", "Búsqueda de teléfono, sitio, dirección y email de una empresa en Google Places, la web "
                                         "y su sitio, con costo estimado y tope"),
                     ("Grupo económico", "Empresas con RUT distinto relacionadas entre sí, sin fusionarse; el sorteo puede tomar "
                                         "como máximo una por grupo"),
                     ("Descubrimiento", "Búsqueda de empresas nuevas por rubro y zona en Google Places; las nuevas entran a la "
                                        "base provisoria")):
    tr = copy.deepcopy(g.rows[1]._tr)
    g._tbl.append(tr)
    for j, v in enumerate((termino, sig)):
        p = g.rows[-1].cells[j].paragraphs[0]
        for r in p.runs[1:]:
            r._r.getparent().remove(r._r)
        p.runs[0].text = v

d.save(RUTA)
print("ok")
