"""Agrega al manual de Word las guías 19 a 24 (SPEC_mejoras_sav_contactos_atributos_identidad) y corrige lo que cambió."""
import copy
import itertools
import sys

import docx
from docx.oxml.ns import qn
from PIL import Image

RUTA, IMG = sys.argv[1], sys.argv[2]
d = docx.Document(RUTA)
ids = itertools.count(9700)


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


# ── Correcciones de lo que cambió ──
t = tabla_con("En el .sav")
filas = [r.cells[0].text.strip() for r in t.rows]
celda(t, filas.index("EC_TEL_ALT"), 1, "Número adicional: se crea si no existe, se vincula con origen Sala y queda verificado")
celda(t, filas.index("EC_RESP_*"), 1, "Contacto nuevo o actualizado con su cargo y área, relacionado con el número por el que se habló")
i = filas.index("EC_RESULTADO")
celda(t, i, 0, "EC_TEL_USADO")
celda(t, i, 1, "El número con el que se habló queda verificado con origen Sala, aunque fuera nuevo (si EC_CALIDAD_TEL dice "
               "no corresponde, inexistente o intermediario, gana eso)")
i = filas.index("Completa, parcial o rechazo")
celda(t, i, 0, "Cada fila del .sav")
celda(t, i, 1, "Es una encuesta completa: el ítem queda completa en la parte y la empresa actualiza su último contacto efectivo")
t = tabla_con("Variable")
i = [r.cells[0].text.strip() for r in t.rows].index("EC_RESULTADO")
celda(t, i, 1, "Ya no hace falta")
celda(t, i, 2, "Desde noviembre de 2026 toda fila del .sav es una encuesta completa (Alchemer exporta solo las completas): "
               "no se mapea un resultado (guía 23)")
t = tabla_con("Pestaña")
i = [r.cells[0].text.strip() for r in t.rows].index("Contactos")
celda(t, i, 1, "Personas de la empresa con cargo, área, email, sus teléfonos («se habló el …») y sus atributos. "
               "El data steward los agrega, edita y borra (guía 19)")
reemplazar(par("Que el archivo tenga una columna de RUT."), [(
    "Que el archivo tenga una columna de RUT. Las filas sin RUT o con RUT inválido se rechazan, salvo que elijas el destino "
    "«Base provisoria» o marques «Enviar las filas sin RUT válido a la base provisoria» (guía 20).", False)])
reemplazar(par("Los contactos no se cargan desde una base"), [(
    "Los contactos pueden venir en la base, uno por fila, en el bloque «Contacto» del mapeo (guía 19).", False)])

# ── Guías 19 a 24 ──
ancla = par("Parte 4 · Mantener la base sana", "Heading 1")._p
nuevos = [
    titulo("Novedades de noviembre de 2026", T_H2),
    texto([("Estas guías cubren los cambios de noviembre de 2026: lo que trae el .sav, los contactos completos, la "
            "normalización de atributos, la exportación configurable y la base provisoria para empresas sin RUT.", False)]),

    titulo("Guía 19. Contactos: agregarlos, editarlos, borrarlos y cargarlos", T_H3),
    texto([("En la ficha.", True), (" En la pestaña Contactos, el data steward y el administrador tienen + Agregar contacto, "
           "Editar y Borrar. Nombre es obligatorio; cargo, área, email (se valida), sucursal, teléfonos (de la empresa o uno "
           "nuevo, que se vincula como manual) y atributos de contacto son opcionales. Si ya hay un contacto con ese nombre, el "
           "sistema avisa y ofrece editar el existente. Cada cambio queda en la línea de tiempo con el usuario.", False)]),
    imagen("46-contacto-form", 0.7),
    caption("44b", "Agregar un contacto"),
    texto([("Borrar es definitivo.", True), (" Es un dato personal (Ley 18.331): se van el contacto, su historia, sus teléfonos de "
           "contacto, sus atributos y su «no llamar». En Auditoría queda el borrado con el RUT, sin el nombre. Coordinador y "
           "lectura no ven los botones; el rol de lectura sigue viendo los contactos ocultos.", False)]),
    texto([("En la carga.", True), (" El mapeo tiene un bloque Contacto: nombre, cargo, área, email, teléfono del contacto y "
           "atributos de contacto, un contacto por fila. Si el contacto ya existe en la empresa (mismo nombre o email), se "
           "completan sus campos vacíos. Su teléfono se vincula a la empresa con el origen de la fila y queda como «número del "
           "contacto». Una fila con datos de contacto pero sin nombre se ignora y el preview lo cuenta. Deshacer o borrar la "
           "carga quita los contactos que trajo.", False)]),
    texto([("Atributos de contacto.", True), (" En Administración → Atributos, pestaña De contacto (por ejemplo, Decisor sí/no). "
           "Se cargan desde la carga, desde el .sav (cualquier variable, con traducción de valores para las listas) y desde la "
           "ficha. Se exportan, pero no filtran ni estratifican el sorteo.", False)]),

    titulo("Guía 20. La base provisoria: empresas sin RUT", T_H3),
    texto([("Qué es.", True), (" La base provisoria guarda las empresas que no traen RUT (un directorio, un relevamiento web). "
           "Se carga, se consulta y se depura por separado, y sus empresas se pueden sortear y llamar. Cada una tiene un código "
           "P-000123 que sirve en la ficha, el buscador, la exportación y el .sav.", False)]),
    texto([("Cargarla.", True), (" En el paso 2 de la carga, Destino → Base provisoria: la columna RUT pasa a ser opcional. Una "
           "fila con RUT válido va igual a la base definitiva (se puede desmarcar). Si la fila traía otro identificador (una "
           "cédula, un «RUT» de 7 dígitos), queda en el atributo Identificador informado. En una carga a la base definitiva, "
           "«Enviar las filas sin RUT válido a la base provisoria» evita rechazarlas.", False)]),
    imagen("47-base-provisoria", 0.95),
    caption("44c", "Base provisoria"),
    tabla([["Para…", "Hacé esto"],
           ["Pasarla a la base definitiva", "Agregar RUT: si el RUT es nuevo, pasa a la definitiva; si ya existe, el sistema ofrece fusionarla con esa empresa"],
           ["Unirla con una empresa que ya está", "Fusionar con…: una de las candidatas o una empresa que busques. Sus teléfonos, contactos, atributos e historia pasan a esa empresa, y sus ítems de muestra y llamadas se ven desde ella. Se puede deshacer"],
           ["Decir que no es ninguna de las candidatas", "Es otra empresa: las candidatas no se vuelven a proponer"],
           ["Completar muchos RUT de una vez", "Subí un archivo con codigo_provisorio;rut: primero muestra qué pasaría con cada fila y después aplica"],
           ["Encontrarla", "En Empresas, Base → provisoria o ambas, o buscá el código P-…"]]),
    texto([("Candidatas en la definitiva.", True), (" La pantalla muestra, por empresa, las de la base definitiva con el mismo "
           "teléfono, razón social o dirección parecidas, el mismo dominio web, o el RUT que trajo el .sav (que nunca se aplica "
           "solo). Inicio cuenta la base provisoria aparte; Empresas activas sigue contando solo la definitiva.", False)]),
    texto([("Sortear.", True), (" En Nueva muestra, «Incluir la base provisoria» viene desmarcado. Si lo marcás, las provisorias "
           "entran con su estrato y las mismas reglas de disponibilidad. El CSV trae EC_ID_EMPRESA con el código y EC_RUT vacío; "
           "el .sav se asocia por EC_ID_ITEM, como siempre.", False)]),

    titulo("Guía 21. Reglas de fusión y coincidencias a decidir", T_H3),
    texto([("Reglas en cascada.", True), (" Cada carga tiene una lista ordenada de reglas para reconocer una empresa que ya está "
           "(en las dos bases). El RUT va siempre primero. Después, las que agregues: razón social, teléfono, dominio web, "
           "dirección (con departamento) o email de contacto. Exacta: coincide después de normalizar (sin tildes, mayúsculas, "
           "puntuación ni «S.A.»); con una sola candidata se fusiona sola. Flexible: la similitud es igual o mayor que el umbral "
           "(0,85 por defecto) y siempre se consulta. Las reglas y el destino quedan en la plantilla.", False)]),
    imagen("48-destino-reglas", 0.45),
    caption("44d", "Destino y reglas de fusión de una carga"),
    texto([("Coincidencias a decidir.", True), (" En el preview, cada fila consultada aparece al lado de su candidata, con la "
           "regla y la similitud. Elegí Fusionar, Es otra empresa o Decidir después, o usá «Fusionar todas las de similitud ≥ 95 %». "
           "Al confirmar se usan esas decisiones; lo que queda en Decidir después va a Revisión de fusiones. Una coincidencia que "
           "uniría dos RUT distintos también se consulta. Deshacer la carga revierte lo que se fusionó en ella.", False)]),
    imagen("49-coincidencias", 0.95),
    caption("44e", "Coincidencias a decidir"),

    titulo("Guía 22. Atributos sin duplicados", T_H3),
    texto([("Crear un atributo.", True), (" Solo el nombre y el tipo son obligatorios. La clave se genera sola "
           "(cantidad_de_empleados; si ya existe, _2) y no cambia aunque cambies el nombre. Una lista puede quedar sin opciones: "
           "se completan en la carga. Si el nombre se parece a otro atributo, el sistema avisa y ofrece usar el existente.", False)]),
    texto([("En la carga.", True), (" Si una columna no se reconoce pero se parece a un atributo («Cant. Empleados» y Cantidad de "
           "empleados), aparece la sugerencia. Usar ese atributo la mapea y suma el nombre de la columna como sinónimo: la "
           "próxima base se reconoce sola. Los valores de lista no distinguen mayúsculas, tildes ni espacios («SI», «si» y «Sí» "
           "son «Sí»); los parecidos («Exportadora» y «Exportador») se sugieren en la traducción, nunca se aplican solos.", False)]),
    imagen("50-sugerencia-atributo", 0.85),
    caption("44f", "Columna parecida a un atributo existente"),
    texto([("Fusionar con….", True), (" En Administración → Atributos, junta un atributo duplicado dentro de otro del mismo "
           "ámbito: sus valores pasan al que queda (se recalcula el vigente), su nombre y sus sinónimos pasan a los sinónimos, "
           "las opciones se unifican y el duplicado queda inactivo con la nota «fusionado en …». No se puede si se usa como "
           "filtro o estrato de una muestra activa (el sistema dice cuál).", False)]),

    titulo("Guía 23. Lo que trae el .sav", T_H3),
    texto([("Toda fila es una encuesta completa.", True), (" Alchemer exporta solo las completas: el mapeo ya no pide un "
           "resultado ni el estado de Alchemer. Cada fila asociada deja el ítem completa en la parte y actualiza el último "
           "contacto efectivo de la empresa. Encuestas completas, en Actividad, cuenta todas las filas del .sav: asociadas a un "
           "ítem más las sin asociar (con un enlace a Conciliación).", False)]),
    texto([("Números verificados.", True), (" El número con el que se habló (EC_TEL_USADO) y el adicional (EC_TEL_ALT) se crean "
           "si no existen, se vinculan con origen Sala y quedan verificados. Si EC_CALIDAD_TEL dice que el número usado no "
           "corresponde, es inexistente o es de un intermediario, gana eso. El contacto queda relacionado con el número: la "
           "ficha dice «se habló el 22/10/2026 (Estudio, Parte)».", False)]),
    texto([("Lo que no se aplicó, fila por fila.", True), (" El detalle de la ingesta lista los motivos con conteos y filas "
           "de ejemplo: fila sin ítem asociado (en Conciliación), número no normalizable, número vacío.", False)]),
    imagen("52-ingesta-motivos", 0.8),
    caption("44g", "Motivos por fila en el detalle de la ingesta"),
    texto([("Línea de tiempo.", True), (" Lo que trajo cada ingesta se agrupa en una línea desplegable: «Ingesta .sav #12 "
           "(Estudio, Parte): 1 contacto nuevo, 1 teléfono verificado, ítem completo».", False)]),
    imagen("44-linea-tiempo-ingesta", 0.9),
    caption("44h", "La ingesta agrupada en la línea de tiempo"),
    texto([("Ingestas anteriores.", True), (" Para aplicarles la regla nueva, abrí cada una, Corregir mapeo y Reaplicar con este "
           "mapeo, sin cambiar nada.", False)]),

    titulo("Guía 24. Muestras: empresas, búsqueda y qué exportar", T_H3),
    texto([("Muestras activas.", True), (" El indicador de Inicio lleva a la lista. Una muestra activa que quedó sin empresas "
           "(se borraron todas) dice «activa, sin empresas» y se puede cerrar o borrar desde ahí.", False)]),
    texto([("Empresas de la muestra.", True), (" 50 por página, con el total arriba, filtros por estrato, rol, liberado y estado "
           "en cada parte, y búsqueda por RUT, razón social o EC_ID_ITEM. En Empresas, #1234 o item:1234 abre la ficha del "
           "ítem 1234 en la pestaña Muestras, con la fila resaltada.", False)]),
    imagen("45-empresas-muestra", 0.9),
    caption("44i", "Empresas de la muestra"),
    texto([("Qué incluir.", True), (" Al exportar, el panel elige los atributos de empresa (todos y ninguno), los números (todos "
           "los discables o solo los verificados) y, si tu usuario tiene el permiso, los contactos (nombre, cargo, área, email, "
           "teléfonos y atributos de contacto). Por defecto, todo; la elección queda guardada en la muestra. Formato uContact (un "
           "renglón por teléfono) o Planilla de la muestra (un renglón por empresa, con los teléfonos en tel_1, tel_2…). Cada "
           "exportación queda en Auditoría con las columnas incluidas.", False)]),
    imagen("51-que-incluir", 0.7),
    caption("44j", "Qué incluir al exportar"),
]
for el in nuevos:
    ancla.addprevious(el)

# Glosario
g = tabla_con("Término")
for termino, sig in (("Base provisoria", "Empresas que no traen RUT. Se pueden sortear y llamar; pasan a la base definitiva al "
                                         "agregarles el RUT o al fusionarlas con una empresa que lo tiene"),
                     ("Código provisorio", "P- más un número (P-000123): identifica a una empresa de la base provisoria")):
    tr = copy.deepcopy(g.rows[1]._tr)
    g._tbl.append(tr)
    fila = g.rows[-1]
    for j, v in enumerate((termino, sig)):
        p = fila.cells[j].paragraphs[0]
        for r in p.runs[1:]:
            r._r.getparent().remove(r._r)
        p.runs[0].text = v

d.save(RUTA)
print("ok")
