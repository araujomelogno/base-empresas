// Capturas de SPEC_rut_sin_control_de_largo (D54): la ficha de una empresa con RUT no verificado, el filtro del
// buscador y el interruptor de Configuración. Requiere la demo con dos empresas de identificador corto, por ejemplo:
//   POST /api/empresas {"rut": "4.567.891", "razon_social": "Carpintería Rodríguez (unipersonal)"}
//   BASE=http://localhost:8080 node docs/build/capturas_rut.js docs/manual/img
const { chromium } = require('playwright');
const OUT = process.argv[2], BASE = process.env.BASE || 'http://localhost:8080';

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1360, height: 1000 }, deviceScaleFactor: 1.5, locale: 'es-UY' });
  const errores = [];
  p.on('pageerror', e => errores.push(e.message));
  p.on('console', m => { if (m.type() === 'error') errores.push(m.text()); });
  const w = (ms = 900) => p.waitForTimeout(ms);
  const ir = async (ruta, ms = 1500) => { await p.goto(`${BASE}/#/inicio`); await w(400); await p.goto(`${BASE}/#/${ruta}`); await w(ms); };
  await p.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: {}, authMode: "dev", apiBase: "/api", tz: "America/Montevideo" };' }));
  await p.goto(BASE); await w(600);
  await p.fill('#login-user', 'admin@equipos.com.uy'); await p.click('#login-btn'); await w(1200);

  // 67 · Ficha de una empresa con RUT no verificado (abre por URL con 7 dígitos)
  await ir('empresas/4567891', 2000);
  console.log('ficha:', (await p.textContent('.page-header, header')).replace(/\s+/g, ' ').slice(0, 160));
  await p.screenshot({ path: `${OUT}/67-rut-no-verificado.png`, clip: { x: 240, y: 0, width: 1120, height: 330 } });

  // 68 · Buscador filtrado por «RUT no verificado»
  await ir('empresas');
  await p.selectOption('#f-rut_verificado', 'false'); await p.click('#f-buscar'); await w(1500);
  console.log('lista:', (await p.textContent('table')).replace(/\s+/g, ' ').slice(0, 200));
  await p.screenshot({ path: `${OUT}/68-filtro-rut.png`, clip: { x: 240, y: 0, width: 1120, height: 520 } });

  // 64 · Configuración → Cargas grandes (con el interruptor nuevo)
  await ir('config', 2000);
  await p.locator('.card', { has: p.locator('#c-lote') }).screenshot({ path: `${OUT}/64-config-cargas.png` });
  console.log('interruptor marcado:', await p.isChecked('#c-rut-cortos'));
  console.log('errores:', errores);
  await b.close();
})();
