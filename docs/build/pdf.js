// Imprime un HTML a PDF A4 con Chromium (Playwright). Lo llama generar_pdfs.py.
//   node pdf.js entrada.html salida.pdf "Título del documento"
const { chromium } = require('playwright');

const [entrada, salida, titulo] = process.argv.slice(2);
const esc = (s) => String(s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.goto('file://' + entrada, { waitUntil: 'networkidle' });
  await p.evaluate(() => document.fonts.ready);
  await p.pdf({
    path: salida, format: 'A4', printBackground: true, preferCSSPageSize: true, displayHeaderFooter: true,
    headerTemplate: '<span></span>',
    footerTemplate: `<div style="width:100%; padding:0 17mm; font-family:Montserrat, sans-serif; font-size:7px; color:#7A7A7A;
      display:flex; justify-content:space-between; letter-spacing:.08em; text-transform:uppercase; font-weight:600;">
      <span><span style="color:#E96436">■</span>&nbsp; Equipos Consultores · Base de Empresas · ${esc(titulo)}</span>
      <span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
  });
  // La portada se imprime aparte, sin pie de página; generar_pdfs.py la reemplaza en la página 1
  await p.pdf({ path: salida + '.portada.pdf', format: 'A4', printBackground: true, preferCSSPageSize: true, pageRanges: '1' });
  await b.close();
})();
