// Capturas de SPEC_cargas_grandes_por_lotes para el manual (guía 30): una carga avanzando por lotes, una carga
// interrumpida y la configuración de las cargas grandes. Requiere la API en modo dev con la demo recién cargada y dos
// cargas en esos estados (ver docs/build/README.md, «Cargas por lotes»).
//   BASE=http://localhost:8080 node docs/build/capturas_lotes.js docs/manual/img
const { chromium } = require('playwright');
const OUT = process.argv[2], BASE = process.env.BASE || 'http://localhost:8080';
const EN_CURSO = process.env.CARGA_EN_CURSO || '5', INTERRUMPIDA = process.env.CARGA_INTERRUMPIDA || '4';

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1360, height: 1000 }, deviceScaleFactor: 1.5, locale: 'es-UY' });
  const w = (ms = 900) => p.waitForTimeout(ms);
  const ir = async (ruta, ms = 1500) => {
    await p.goto(`${BASE}/#/inicio`); await w(400);
    await p.goto(`${BASE}/#/${ruta}`); await w(ms);
  };
  // Parte de arriba del área principal (sin el menú lateral)
  const principal = async (nombre, alto) => {
    await p.evaluate(() => document.getElementById('toast-wrap')?.replaceChildren());
    await p.screenshot({ path: `${OUT}/${nombre}.png`, clip: { x: 240, y: 0, width: 1120, height: alto } });
  };
  await p.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: {}, authMode: "dev", apiBase: "/api", tz: "America/Montevideo" };' }));
  await p.goto(BASE); await w(600);
  await p.fill('#login-user', 'admin@equipos.com.uy'); await p.click('#login-btn'); await w(1200);

  // 62 · Una carga grande confirmándose: lote 13 de 38
  await ir(`cargas/${EN_CURSO}`, 2500);
  await principal('62-carga-por-lotes', 640);

  // 63 · Carga interrumpida: 4 de 10 lotes aplicados, con Reanudar, Deshacer y Borrar (CARGA_INTERRUMPIDA=0: no se saca)
  if (INTERRUMPIDA !== '0') {
    await ir(`cargas/${INTERRUMPIDA}`, 2000);
    await principal('63-carga-interrumpida', 600);
  }

  // 64 · Configuración → Cargas grandes
  await ir('config', 2000);
  await p.locator('.card', { has: p.locator('#c-lote') }).screenshot({ path: `${OUT}/64-config-cargas.png` });
  await b.close();
})();
