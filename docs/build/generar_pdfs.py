"""Genera el manual de usuario en PDF con la estética de Equipos Consultores.

La guía de despliegue, el registro de decisiones y los costos quedan solo en Markdown
(docs/despliegue.md, docs/decisiones.md, docs/costos.md).

    pip install markdown pypdf
    python docs/build/generar_pdfs.py

Convierte el Markdown a HTML (portada, índice, estilos de marca) y lo imprime a PDF con
Chromium (Playwright de Node, ver pdf.js). Las imágenes se embeben en el HTML.
Requiere: pip install markdown pypdf; Node con Playwright.
"""
import base64
import datetime as dt
import html
import mimetypes
import pathlib
import re
import subprocess
import sys
import tempfile

import markdown

DOCS = pathlib.Path(__file__).resolve().parents[1]
RAIZ = DOCS.parent
LOGO = RAIZ / "web" / "public" / "img" / "isotipo.png"
SALIDA = DOCS / "pdf"

DOCUMENTOS = {
    "manual": (DOCS / "manual" / "manual_usuario.md", "Manual_de_usuario.pdf", True),
}

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]

CSS = """
@page { size: A4; margin: 20mm 17mm 20mm 17mm; }
@page :first { margin: 0; }
:root { --orange:#E96436; --orange-dark:#C8512A; --orange-light:#FDF0EB; --dark:#3A3838; --dark2:#222222;
        --gray:#7A7A7A; --gray-light:#EEEEEE; --gray-xlight:#F7F7F7; --border:#E2E2E2; --blue-light:#EAF1F8; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: 'Montserrat', sans-serif; font-size: 9.6pt; line-height: 1.6; color: var(--dark2); font-weight: 500; margin: 0; }
.portada { width: 210mm; height: 297mm; background: var(--dark); position: relative; overflow: hidden; color: #fff;
           display: flex; flex-direction: column; justify-content: center; padding: 0 26mm; break-after: page; }
.portada::before { content: ''; position: absolute; bottom: 9%; left: -12mm; width: 56mm; height: 56mm; background: var(--orange); opacity: .92; }
.portada::after { content: ''; position: absolute; top: 9%; right: -8mm; width: 32mm; height: 32mm; background: var(--orange); opacity: .2; }
.portada img { height: 30mm; width: auto; align-self: flex-start; margin-bottom: 14mm; position: relative; }
.portada .barra { width: 18mm; height: 2mm; background: var(--orange); margin-bottom: 7mm; }
.portada h1 { font-size: 34pt; font-weight: 800; letter-spacing: -0.02em; line-height: 1.1; margin: 0; color: #fff; }
.portada h1 em { color: var(--orange); font-style: normal; display: block; }
.portada .sub { font-size: 12.5pt; color: rgba(255,255,255,.7); margin-top: 6mm; font-weight: 600; }
.portada .pie { position: absolute; left: 26mm; right: 26mm; bottom: 22mm; display: flex; justify-content: flex-end;
                font-size: 8.5pt; color: rgba(255,255,255,.55); letter-spacing: .12em; text-transform: uppercase; font-weight: 700; }
.indice { break-after: page; }
.indice h2 { margin-top: 0; }
.indice ol { padding-left: 0; list-style: none; counter-reset: i; columns: 1; }
.indice li { counter-increment: i; padding: 2.2mm 0; border-bottom: 1px solid var(--border); font-weight: 600; color: var(--dark); }
.indice li::before { content: counter(i, decimal-leading-zero); color: var(--orange); font-weight: 800; margin-right: 5mm; }
.indice li ul { list-style: none; padding-left: 11mm; margin: 1mm 0 0; font-weight: 500; color: var(--gray); font-size: 8.8pt; }
.indice li ul li { border: none; padding: .6mm 0; counter-increment: none; }
.indice li ul li::before { content: none; }
h1, h2, h3, h4 { color: var(--dark); font-weight: 800; letter-spacing: -0.015em; line-height: 1.25; break-after: avoid; break-inside: avoid; }
h2 { font-size: 17pt; margin: 9mm 0 3.5mm; padding-top: 2mm; }
h2::before { content: ''; display: block; width: 13mm; height: 1.4mm; background: var(--orange); margin-bottom: 3.5mm; }
.secciones h2 { break-before: page; margin-top: 0; }
.secciones .intro + h2 { break-before: auto; margin-top: 8mm; }
h3 { font-size: 11.5pt; margin: 6mm 0 2mm; color: var(--orange-dark); }
h4 { font-size: 10pt; margin: 4mm 0 1.5mm; }
p { margin: 0 0 2.6mm; }
strong { font-weight: 700; color: var(--dark); }
a { color: var(--orange-dark); text-decoration: none; font-weight: 600; }
ul, ol { margin: 0 0 3mm; padding-left: 5.5mm; }
li { margin-bottom: 1mm; }
li::marker { color: var(--orange); font-weight: 700; }
code { font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; font-size: 8.2pt; background: var(--gray-xlight);
       border: 1px solid var(--border); border-radius: 2px; padding: 0 1.2mm; color: var(--dark); }
pre { background: var(--dark); color: #F3F3F3; border-radius: 3px; padding: 3.5mm 4.5mm; font-size: 7.9pt; line-height: 1.5;
      white-space: pre-wrap; word-break: break-word; break-inside: avoid; margin: 0 0 4mm; border-left: 1.2mm solid var(--orange); }
pre code { background: none; border: none; padding: 0; color: inherit; font-size: inherit; }
table { width: 100%; border-collapse: collapse; margin: 1mm 0 5mm; font-size: 8.4pt; break-inside: auto; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { text-align: left; font-size: 7pt; font-weight: 700; color: var(--gray); text-transform: uppercase; letter-spacing: .07em;
     padding: 2.2mm 2.8mm; background: var(--gray-xlight); border-bottom: 1px solid var(--border); border-top: 2px solid var(--dark); }
td { padding: 2mm 2.8mm; border-bottom: 1px solid var(--border); vertical-align: top; }
td:first-child { font-weight: 600; color: var(--dark); }
blockquote { margin: 3mm 0 5mm; padding: 3.2mm 4.5mm; background: var(--orange-light); border-left: 1.2mm solid var(--orange);
             border-radius: 0 3px 3px 0; break-inside: avoid; }
blockquote p:last-child { margin-bottom: 0; }
figure { margin: 3mm 0 6mm; break-inside: avoid; text-align: center; }
figure img { max-width: 100%; max-height: 205mm; object-fit: contain; border: 1px solid var(--border); border-radius: 3px;
             box-shadow: 0 1.5mm 5mm rgba(0,0,0,.08); }
figcaption { font-size: 7.6pt; color: var(--gray); margin-top: 2mm; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; }
hr { border: none; border-top: 1px solid var(--border); margin: 6mm 0; }
.intro { font-size: 10.5pt; }
"""


def frente(texto: str) -> tuple[dict, str]:
    meta = {}
    m = re.match(r"^---\n(.*?)\n---\n", texto, re.S)
    if m:
        for linea in m.group(1).splitlines():
            if ":" in linea:
                k, v = linea.split(":", 1)
                meta[k.strip()] = v.strip()
        texto = texto[m.end():]
    return meta, texto


def embeber(html_: str, base: pathlib.Path) -> str:
    def reemplazar(m):
        alt, src = m.group(1), m.group(2)
        ruta = (base / src).resolve()
        if not ruta.exists():
            raise SystemExit(f"Falta la imagen {ruta}")
        tipo = mimetypes.guess_type(ruta.name)[0] or "image/png"
        datos = base64.b64encode(ruta.read_bytes()).decode()
        return f'<figure><img src="data:{tipo};base64,{datos}" alt="{alt}" /><figcaption>{alt}</figcaption></figure>'

    # Imagen sola en un párrafo -> figura con epígrafe
    return re.sub(r'<p><img alt="([^"]*)" src="([^"]+)" ?/?></p>', reemplazar, html_)


def indice(cuerpo: str) -> str:
    items = []
    for m in re.finditer(r"<h2[^>]*>(.*?)</h2>|<h3[^>]*>(.*?)</h3>", cuerpo):
        if m.group(1):
            items.append([m.group(1), []])
        elif items:
            items[-1][1].append(m.group(2))
    lis = "".join(f"<li>{t}{'<ul>' + ''.join(f'<li>{s}</li>' for s in subs) + '</ul>' if subs and len(subs) <= 8 else ''}</li>"
                  for t, subs in items)
    return f'<section class="indice"><h2>Contenido</h2><ol>{lis}</ol></section>'


def construir(clave: str) -> pathlib.Path:
    fuente, nombre_pdf, con_indice = DOCUMENTOS[clave]
    meta, texto = frente(fuente.read_text(encoding="utf-8"))
    texto = re.sub(r"^# .*\n", "", texto, count=1, flags=re.M)  # el título va en la portada
    cuerpo = markdown.markdown(texto, extensions=["tables", "fenced_code", "sane_lists", "attr_list"])
    cuerpo = embeber(cuerpo, fuente.parent)
    i = cuerpo.find("<h2")
    if i > 0:  # la presentación antes de la primera sección no queda sola en una página
        cuerpo = f'<div class="intro">{cuerpo[:i]}</div>{cuerpo[i:]}'
    hoy = dt.date.today()
    titulo = meta.get("titulo", fuente.stem)
    partes = titulo.split(" ", 1)
    titulo_html = f"{html.escape(partes[0])}<em>{html.escape(partes[1])}</em>" if len(partes) == 2 else html.escape(titulo)
    portada = f"""<section class="portada"><img src="data:image/png;base64,{base64.b64encode(LOGO.read_bytes()).decode()}" />
      <div class="barra"></div><h1>{titulo_html}</h1><div class="sub">{html.escape(meta.get('subtitulo', ''))}</div>
      <div class="pie"><span>{MESES[hoy.month - 1]} {hoy.year}</span></div></section>"""
    doc = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>{html.escape(titulo)}</title>
      <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
      <style>{CSS}</style></head><body>{portada}{indice(cuerpo) if con_indice else ''}
      <main class="{'secciones' if clave == 'manual' else ''}">{cuerpo}</main></body></html>"""
    SALIDA.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(doc)
        ruta_html = f.name
    destino = SALIDA / nombre_pdf
    subprocess.run(["node", str(pathlib.Path(__file__).with_name("pdf.js")), ruta_html, str(destino), titulo],
                   check=True)
    pathlib.Path(ruta_html).unlink()
    _portada_sin_pie(destino)
    print(f"✔ {destino.relative_to(RAIZ)}")
    return destino


def _portada_sin_pie(destino: pathlib.Path):
    from pypdf import PdfReader, PdfWriter

    portada = destino.with_name(destino.name + ".portada.pdf")
    w = PdfWriter()
    w.add_page(PdfReader(portada).pages[0])
    for pag in PdfReader(destino).pages[1:]:
        w.add_page(pag)
    with open(destino, "wb") as f:
        w.write(f)
    portada.unlink()


if __name__ == "__main__":
    for clave in sys.argv[1:] or DOCUMENTOS:
        construir(clave)
