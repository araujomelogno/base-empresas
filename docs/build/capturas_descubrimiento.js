// Capturas de SPEC_descubrimiento_que_aporta (D58): «Qué aporta» en el preview de un lote, el filtro y «Omitir las que no
// aportan», «Qué se agregó» después de confirmar y el enlace al lote en la ficha. Confirma el lote LOTE (en preview).
//   BASE=http://localhost:8080 LOTE=11 RUT_FICHA=55001217 node docs/build/capturas_descubrimiento.js docs/manual/img
const { chromium } = require('playwright');
const OUT = process.argv[2], BASE = process.env.BASE || 'http://localhost:8080';
const LOTE = process.env.LOTE || '11', RUT_FICHA = process.env.RUT_FICHA || '55001217';

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 1.5, locale: 'es-UY', acceptDownloads: true });
  const p = await ctx.newPage();
  const errores = [];
  p.on('pageerror', e => errores.push(e.message));
  p.on('console', m => { if (m.type() === 'error') errores.push(m.text()); });
  const w = (ms = 900) => p.waitForTimeout(ms);
  const ir = async (ruta, ms = 1500) => { await p.goto(`${BASE}/#/inicio`); await w(400); await p.goto(`${BASE}/#/${ruta}`); await w(ms); };
  await p.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: {}, authMode: "dev", apiBase: "/api", tz: "America/Montevideo" };' }));
  await p.goto(BASE); await w(600);
  await p.fill('#login-user', 'admin@equipos.com.uy'); await p.click('#login-btn'); await w(1200);

  // 82 · El preview con «Qué aporta»
  await ir(`descubrimiento/${LOTE}`, 2000);
  const tarjeta = p.locator('.card', { has: p.locator('[data-tabs="de-filtro"]') });
  console.log('stats:', (await p.locator('.stat-grid').first().innerText()).replace(/\s+/g, ' '));
  await p.locator('.stat-grid').first().screenshot({ path: `${OUT}/82-descubrimiento-resumen.png` });
  await tarjeta.screenshot({ path: `${OUT}/83-descubrimiento-que-aporta.png` });

  // 84 · Filtro «Coinciden sin aporte» y «Omitir las que no aportan» (antes, alguien las había pasado a «Completar»)
  for (const s of await p.$$('tr[data-grupo="sin_aporte"] [data-sel]')) await s.selectOption('completar');
  const antes = await p.$$eval('tr[data-grupo] [data-sel]', s => s.map(x => x.value));
  await p.click('[data-tabs="de-filtro"] [data-tab="sin_aporte"]'); await w(400);
  console.log('visibles en «sin aporte»:', await p.$$eval('tr[data-grupo]', t => t.filter(x => x.style.display !== 'none').length));
  await p.click('#de-omitir'); await w(600);
  const despues = await p.$$eval('tr[data-grupo] [data-sel]', s => s.map(x => x.value));
  console.log('selección antes:', antes.join(','), '· después:', despues.join(','));
  await tarjeta.screenshot({ path: `${OUT}/84-descubrimiento-sin-aporte.png` });
  await p.evaluate(() => document.querySelectorAll('.toast').forEach(t => t.remove()));
  await p.click('[data-tabs="de-filtro"] [data-tab=""]'); await w(300);

  // CSV
  const [bajada] = await Promise.all([p.waitForEvent('download'), p.click('#de-csv')]);
  console.log('csv:', bajada.suggestedFilename());

  // 85 · Confirmar: «Qué se agregó». Se completa una sin aporte (queda «Sin cambios») y la que coincide por nombre
  await p.selectOption('tr[data-grupo="sin_aporte"] [data-sel] >> nth=0', 'completar');
  await p.selectOption('tr[data-grupo="aporta"] [data-sel] >> nth=-1', 'completar');
  await p.click('#de-confirmar'); await w(2500);
  await p.evaluate(() => document.querySelectorAll('.toast').forEach(t => t.remove()));
  console.log('aviso:', (await p.locator('.alert-success').innerText()).replace(/\s+/g, ' '));
  await p.locator('.alert-success').screenshot({ path: `${OUT}/85-descubrimiento-confirmado.png` });
  await p.locator('.card', { has: p.locator('[data-tabs="de-filtro"]') }).screenshot({ path: `${OUT}/86-descubrimiento-que-se-agrego.png` });

  // 87 · La ficha: el dato que vino del descubrimiento lleva al lote
  await ir(`empresas/${RUT_FICHA}`, 2000);
  const kv = p.locator('.card', { hasText: 'Valores vigentes' });
  console.log('enlace:', await kv.locator(`a[href="#/descubrimiento/${LOTE}"]`).count());
  await kv.screenshot({ path: `${OUT}/87-ficha-dato-del-lote.png` });

  console.log('errores de la página:', errores.length ? errores : 'ninguno');
  await b.close();
})();
