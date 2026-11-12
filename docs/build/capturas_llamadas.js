// Capturas del conteo de llamadas del CDR para el manual (guía 11): rendimiento por origen,
// corridas del job y lista de empresas llamadas. Requiere la API en modo dev con la demo cargada y
// al menos una corrida del job con el conteo nuevo (ver docs/build/README.md):
//   BASE=http://localhost:8080 node docs/build/capturas_llamadas.js docs/manual/img
const { chromium } = require('playwright');
const OUT = process.argv[2], BASE = process.env.BASE || 'http://localhost:8080';

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1360, height: 1000 }, deviceScaleFactor: 1.5, locale: 'es-UY' });
  const w = (ms = 900) => p.waitForTimeout(ms);
  await p.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: {}, authMode: "dev", apiBase: "/api", tz: "America/Montevideo" };' }));
  await p.goto(BASE); await w(600);
  await p.fill('#login-user', 'coord@equipos.com.uy'); await p.click('#login-btn'); await w(1200);
  await p.goto(`${BASE}/#/actividad`); await w(2500);
  await p.locator('#a-origenes .card').screenshot({ path: `${OUT}/40-rendimiento-origen.png` });
  await p.locator('.card', { hasText: 'Corridas del job del CDR' }).screenshot({ path: `${OUT}/41-corridas-cdr.png` });
  await p.click('[data-corrida-detalle]'); await w(600);
  await p.locator('.modal-box').screenshot({ path: `${OUT}/42-corrida-embudo.png` });
  await p.click('.modal-foot .btn-orange'); await w(300);
  await p.click('a:has-text("Exportar empresas") >> nth=0'); await w(1800);
  await p.screenshot({ path: `${OUT}/43-empresas-llamadas.png`, clip: { x: 240, y: 0, width: 1120, height: 820 } });
  await b.close();
})();
