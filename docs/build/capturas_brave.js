// Capturas de SPEC_brave_pais_y_errores_visibles (D57): los motivos de error debajo de cada paso, la pestaña «Con error»,
// el paso 5 (búsqueda web con Claude) en una corrida y en la estimación, su configuración y la «página fuente» en la ficha.
// Requiere una corrida con errores (CORRIDA_ERROR), una que llegó al paso 5 (CORRIDA_WEB) y el RUT de la empresa que
// el paso 5 enriqueció (RUT_WEB). Con la búsqueda web activada en la configuración.
//   BASE=http://localhost:8080 CORRIDA_ERROR=4 CORRIDA_WEB=3 RUT_WEB=55001217 RUT_EST=550031117 \
//     node docs/build/capturas_brave.js docs/manual/img
const { chromium } = require('playwright');
const OUT = process.argv[2], BASE = process.env.BASE || 'http://localhost:8080';
const CE = process.env.CORRIDA_ERROR || '4', CW = process.env.CORRIDA_WEB || '3';
const RUT_WEB = process.env.RUT_WEB || '55001217', RUT_EST = process.env.RUT_EST || '550031117';

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1360, height: 1000 }, deviceScaleFactor: 1.5, locale: 'es-UY' });
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

  // 76 · Pasos con el motivo de cada error
  await ir(`enriquecimiento/${CE}`, 2000);
  const pasos = p.locator('.card', { hasText: 'Pasos' }).first();
  console.log('motivos:', (await p.locator('.motivo-error').allTextContents()).join(' | '));
  await pasos.screenshot({ path: `${OUT}/76-pasos-motivo-error.png` });

  // 77 · Empresas «Con error», con el motivo en el título del chip
  const tab = p.locator('[data-tabs="co-res"] [data-tab="error"]').first();
  if (await tab.count()) { await tab.click(); await w(1200); }
  console.log('title del chip:', await p.locator('.con-motivo').first().getAttribute('title'));
  await p.locator('.card', { hasText: 'Empresas' }).last().screenshot({ path: `${OUT}/77-empresas-con-error.png` });

  // 78 · Una corrida que llegó al paso 5
  await ir(`enriquecimiento/${CW}`, 2000);
  console.log('paso 5:', (await p.locator('.card', { hasText: 'Pasos' }).first().innerText()).replace(/\s+/g, ' ').slice(0, 300));
  await p.locator('.card', { hasText: 'Pasos' }).first().screenshot({ path: `${OUT}/78-pasos-busqueda-web.png` });

  // 79 · Configuración: el paso 5
  await ir('config', 2500);
  const fila = p.locator('.form-row', { has: p.locator('#en-act-claude_web') });
  await fila.scrollIntoViewIfNeeded(); await w(300);
  await fila.screenshot({ path: `${OUT}/79-config-busqueda-web.png` });

  // 80 · La ficha: origen «Búsqueda web (Claude)» con el enlace a la página fuente
  await p.setViewportSize({ width: 1900, height: 1000 });   // la tabla de teléfonos es ancha: que entre la columna Origen
  await ir(`empresas/${RUT_WEB}`, 2000);
  await p.locator('.tab', { hasText: 'Teléfonos' }).click(); await w(800);
  const enlace = p.locator('a', { hasText: 'página fuente' }).first();
  console.log('página fuente:', await enlace.getAttribute('href'), await enlace.getAttribute('rel'));
  const tel = p.locator('.card', { has: enlace }).first();
  await tel.screenshot({ path: `${OUT}/80-ficha-pagina-fuente.png` });
  await p.setViewportSize({ width: 1360, height: 1000 });

  // 81 · La estimación con la búsqueda web (se cancela: no se aprueba nada)
  await ir(`empresas/${RUT_EST}`, 2000);
  await p.click('#a-enriquecer'); await w(1500);
  console.log('estimación:', (await p.locator('.modal-box').innerText()).replace(/\s+/g, ' ').match(/Búsqueda web[^.]*\./)?.[0]);
  await p.locator('.modal-box').screenshot({ path: `${OUT}/81-estimacion-busqueda-web.png` });
  await p.locator('.modal-box button', { hasText: 'Cancelar' }).click(); await w(600);

  console.log('errores de la página:', errores.length ? errores : 'ninguno');
  await b.close();
})();
