// Capturas de SPEC_muestras_marco_excel_sistematico (D56): el aviso de espera, el paso 3 con Total · Sorteables ·
// No sorteables, el método de sorteo y el Excel importado, y el detalle de una muestra sistemática («Vecino de»).
// También verifica que un doble clic en «Ver marco disponible» haga un solo pedido.
//   BASE=http://localhost:8080 ESTUDIO=1 node docs/build/capturas_muestras.js docs/manual/img
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const OUT = process.argv[2], BASE = process.env.BASE || 'http://localhost:8080', ESTUDIO = process.env.ESTUDIO || '1';

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1360, height: 1000 }, deviceScaleFactor: 1.5, locale: 'es-UY', acceptDownloads: true });
  const p = await ctx.newPage();
  const errores = [];
  p.on('pageerror', e => errores.push(e.message));
  p.on('console', m => { if (m.type() === 'error') errores.push(m.text()); });
  const w = (ms = 900) => p.waitForTimeout(ms);
  await p.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: {}, authMode: "dev", apiBase: "/api", tz: "America/Montevideo" };' }));
  await p.goto(BASE); await w(600);
  await p.fill('#login-user', 'admin@equipos.com.uy'); await p.click('#login-btn'); await w(1200);

  // El marco tarda 2,5 s (simulado) para ver el modal y contar los pedidos
  let pedidosMarco = 0;
  await p.route('**/api/muestras/marco', async r => {
    pedidosMarco++;
    await new Promise(ok => setTimeout(ok, 2500));
    await r.continue();
  });
  await p.goto(`${BASE}/#/estudios/${ESTUDIO}/nueva-muestra`); await w(2000);
  await p.selectOption('#m-add-estrato', 'departamento'); await w(500);
  await p.dblclick('#m-marco');
  await w(700);
  const modal = await p.textContent('.modal-backdrop.espera');
  console.log('modal:', modal.replace(/\s+/g, ' ').trim(), '· botón deshabilitado:', await p.isDisabled('#m-marco'));
  // 73 · El aviso de espera
  await p.screenshot({ path: `${OUT}/73-espera-marco.png`, clip: { x: 330, y: 300, width: 700, height: 300 } });
  await p.waitForSelector('#m-metodo', { timeout: 30000 }); await w(600);
  console.log('pedidos de /muestras/marco con doble clic:', pedidosMarco);
  await p.unroute('**/api/muestras/marco');

  // Excel: se descarga, se completan titulares y reemplazos y se importa
  await p.selectOption('#m-metodo', 'sistematico_ciiu');
  const [bajada] = await Promise.all([p.waitForEvent('download'), p.click('#m-excel-bajar')]);
  const archivo = path.join(require('os').tmpdir(), 'tamanos_capturas.xlsx');
  await bajada.saveAs(archivo);
  console.log('excel:', bajada.suggestedFilename());
  const { execFileSync } = require('child_process');
  execFileSync('python3', ['-c', `
import sys
from openpyxl import load_workbook
wb = load_workbook(sys.argv[1]); ws = wb["Tamaños"]
for i in range(2, ws.max_row):
    s = ws.cell(i, 3).value or 0
    ws.cell(i, 5, max(1, s // 4)); ws.cell(i, 6, 1 if s > 3 else 0)
wb.save(sys.argv[1])`, archivo]);
  await p.setInputFiles('#m-excel-archivo', archivo); await w(2000);
  fs.unlinkSync(archivo);
  console.log('import:', (await p.textContent('#m-excel-res')).replace(/\s+/g, ' ').slice(0, 120));
  // 74 · Paso 3: método, Excel y Total · Sorteables · No sorteables
  await p.locator('#m-estratos .card').screenshot({ path: `${OUT}/74-paso3-excel-metodo.png` });

  // Un cambio de filtro marca el marco como desactualizado
  await p.click('#m-provisoria'); await w(400);
  console.log('desactualizado:', await p.isVisible('#m-marco-viejo'));
  await p.click('#m-provisoria'); await w(300);
  await p.click('#m-marco'); await p.waitForSelector('.modal-backdrop.espera', { state: 'detached', timeout: 30000 }); await w(600);

  // Sortear (sistemático)
  await p.fill('#m-nombre', 'Sistemática por CIIU');
  await p.click('#m-sortear'); await w(500);
  await p.click('.modal-foot .btn-orange'); await w(500);
  await p.waitForURL(/#\/muestras\/\d+/, { timeout: 60000 }); await w(2500);
  await p.selectOption('#mu-rol', 'reemplazo'); await w(1200);
  console.log('reemplazo:', (await p.textContent('#mu-items tbody tr')).replace(/\s+/g, ' ').slice(0, 160));
  // 75 · Detalle: «Vecino de …»
  await p.locator('#mu-items').screenshot({ path: `${OUT}/75-vecino-de.png` });
  console.log('errores:', errores);
  await b.close();
})();
