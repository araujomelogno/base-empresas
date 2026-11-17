// Capturas de SPEC_fase2_enriquecimiento para el manual (guía 26): calidad, estimación, corrida, posibles duplicados,
// descubrimiento y configuración del enriquecimiento. Requiere la API en modo dev con la demo recién cargada y los
// proveedores SIMULADOS (sin llamadas pagas):
//   PROVEEDORES_MODO=simulado (además de AUTH_MODE=dev SERVE_WEB=1 TASKS_MODE=inline) al levantar uvicorn
//   BASE=http://localhost:8080 node docs/build/capturas_fase2.js docs/manual/img
const { chromium } = require('playwright');
const OUT = process.argv[2], BASE = process.env.BASE || 'http://localhost:8080';

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1360, height: 1000 }, deviceScaleFactor: 1.5, locale: 'es-UY' });
  const w = (ms = 900) => p.waitForTimeout(ms);
  const ir = async (ruta, ms = 1500) => {
    await p.evaluate(() => { document.querySelectorAll('.modal-backdrop').forEach(m => m.remove());
      document.getElementById('toast-wrap')?.replaceChildren(); });
    await p.goto(`${BASE}/#/inicio`); await w(400);
    await p.goto(`${BASE}/#/${ruta}`); await w(ms);
  };
  // Área principal (sin el menú lateral), de alto fijo
  const principal = async (nombre, alto) => {
    await p.evaluate(() => document.getElementById('toast-wrap')?.replaceChildren());
    const h = alto || await p.evaluate(() => document.documentElement.scrollHeight);
    await p.screenshot({ path: `${OUT}/${nombre}.png`, fullPage: true, clip: { x: 240, y: 0, width: 1120, height: h } });
  };
  await p.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: {}, authMode: "dev", apiBase: "/api", tz: "America/Montevideo" };' }));
  await p.goto(BASE); await w(600);
  await p.fill('#login-user', 'admin@equipos.com.uy'); await p.click('#login-btn'); await w(1200);

  // 61 · Configuración → Enriquecimiento
  await ir('config', 2000);
  await p.locator('.card', { has: p.locator('#en-places') }).screenshot({ path: `${OUT}/61-config-enriquecimiento.png` });

  // 57 y 58 · Enriquecer las empresas sin teléfono de la lista
  await ir('empresas');
  await p.selectOption('#f-sin_telefono', 'true'); await p.click('#f-buscar'); await w(1500);
  await p.click('#e-enriquecer'); await w(1500);
  await p.locator('.modal-box').screenshot({ path: `${OUT}/57-estimacion.png` });
  await p.click('.modal-foot .btn-orange'); await w(4000);
  await principal('58-corrida');

  // 59 · Posibles duplicados (primeros pares)
  await ir('duplicados');
  await p.click('#dup-detectar'); await w(2500);
  await principal('59-duplicados', 900);

  // 60 · Buscar empresas nuevas: preview de un lote
  await ir('descubrimiento');
  await p.fill('#de-q', 'imprentas en Salto'); await p.click('#de-estimar'); await w(1500);
  await p.click('.modal-foot .btn-orange'); await w(2500);
  await principal('60-descubrimiento');

  // 56 · Calidad de la base (con la foto de hoy guardada)
  await ir('calidad', 2500);
  await p.click('#cal-medir'); await w(2500);
  await principal('56-calidad');
  await b.close();
})();
